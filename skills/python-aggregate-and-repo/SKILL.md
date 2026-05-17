---
name: python-aggregate-and-repo
description: |
  Use when designing or editing aggregates and their repositories in a FastAPI +
  SQLAlchemy backend: files in `app/models/` and `app/repos/`. Triggers on edits
  to those directories; on imports from `sqlalchemy.ext.asyncio`,
  `sqlalchemy.orm`; on user mentions of "aggregate", "repository", "consistency
  boundary", "ORM model with behavior", "use case loading". Encodes: SA model
  with behavior (no separate domain layer by default), repos return SA models,
  YAGNI on repo surface, typed `*Exception` raised from repo, no commit in repo,
  one repo per aggregate root, named query methods over generic filter objects.
  Do NOT use for: projects that have an explicit `domain/` directory with pure
  domain classes — use `python-pure-domain-layer` instead.
---

# Aggregate and repository pattern

The aggregate is the unit of consistency: a chunk of state that's loaded together, mutated together, and saved together as a single transaction. The repository is the only thing that reads or writes aggregates of its type. Together they're the heart of the data layer.

This skill encodes the **SA-model-with-behavior** style: the SQLAlchemy ORM model carries the business methods (`order.place()`, `customer.deactivate()`), and there's no separate pure-Python "domain" class. For most backend services — especially integration- and orchestration-heavy ones — this is the right trade-off. For invariant-dense systems where you want sub-millisecond invariant tests without a DB, see `python-pure-domain-layer`.

## When to use this skill

- Adding a new aggregate (Order, Customer, Subscription, Document, ...)
- Adding a method on an existing aggregate
- Adding a repo query that a service needs
- Refactoring a "fat router" or "anaemic model" into a proper aggregate

## The rules

### 1. SA model carries behavior; no separate domain class

The SA-mapped class holds the columns, the methods, the derived values, and the domain exceptions in one file. The shape:

```python
# app/models/order.py — shape only; see examples/order_model.py for the full version
class Order(Base):
    __tablename__ = "order"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customer.id"))
    status: Mapped[OrderStatus] = mapped_column(default=OrderStatus.DRAFT)
    lines: Mapped[list["OrderLine"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin",
    )

    @property
    def total(self) -> Decimal: ...                  # derived value

    @classmethod
    def new(cls, *, customer_id: UUID, currency: str) -> Self: ...   # constructor

    def add_line(self, *, product_id: UUID, quantity: int, unit_price: Decimal) -> None:
        if self.status is not OrderStatus.DRAFT:
            raise OrderAlreadyPlacedException(self.id)
        self.lines.append(OrderLine(...))            # mutation guarded by precondition

    def place(self) -> None: ...                     # transition, guarded
    def cancel(self, *, reason: str) -> None: ...    # idempotent guard
```

Methods enforce invariants through **precondition checks** at the top. `@property` is derived. Domain exceptions (`OrderNotFoundException`, `OrderAlreadyPlacedException`, `EmptyOrderException`) live in the same file, inherit from `app/common/exceptions.py` bases.

If a rule belongs entirely to this aggregate's state, keep it on the aggregate. If a rule is a pure decision but spans multiple aggregates/value objects (pricing, eligibility, fulfillment planning), extract a small domain service or policy and let the application service call it. If a rule needs I/O, it is not a domain service; keep the I/O in the application service or client.

### 2. One file per aggregate root in `app/models/`; one file per aggregate root in `app/repos/`

`Order` and `OrderLine` live in the same file because `OrderLine` is part of the Order aggregate — it can't exist without an Order, and no code outside Order's methods should mutate `OrderLine`.

By contrast, `Customer` is its own aggregate root, in its own file (`app/models/customer.py`).

Repos follow the same partition: `app/repos/order.py`, `app/repos/customer.py`. One repo per root.

### 3. Repo takes `AsyncSession` in constructor; methods return SA models

```python
# app/repos/order.py — shape only; see examples/order_repo.py for the full version
class OrderRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, order_id: UUID) -> Order | None:
        return await self._session.get(Order, order_id)

    async def get_or_raise(self, order_id: UUID) -> Order: ...
    async def add(self, order: Order) -> None: ...
    async def list_for_customer(self, customer_id: UUID) -> AsyncIterator[Order]: ...
```

Repo *uses* the session; it doesn't *own* the transaction. No `await self._session.commit()` and no `async with self._session.begin()` anywhere in the repo. The top-level service command owns the transaction boundary with `async with session.begin()` (see `python-service-and-schema-cohesion`). `add` flushes immediately so `IntegrityError` surfaces at the call site and translates to `UniqueViolationException`.

### 4. YAGNI on the repo surface

Implement only methods that a service currently calls. `get`, `get_or_raise`, `add` are the common minimum. `list_for_customer` exists because a route calls it. `delete` is added the day a service needs it.

A repo with 12 methods nobody uses is dead code. The skill of restraint is more valuable than a "complete" interface.

When in doubt: don't add it. Add it when a service demands it.

### 5. `add` vs `save` — be explicit about which case the service is in

```python
async def add(self, order: Order) -> None:
    """Insert a new aggregate. Fast: no SELECT, just INSERT."""
    self._session.add(order)
    try:
        await self._session.flush()
    except IntegrityError as exc:
        raise UniqueViolationException(...) from exc


async def save(self, order: Order) -> None:
    """Persist changes to an existing aggregate loaded earlier. Uses MERGE."""
    await self._session.merge(order)
```

The service knows which one applies:
- Just called `Order.new(...)`? → `repo.add(order)`
- Just called `repo.get_or_raise(...)`? → `repo.save(order)` (or skip the call entirely — SA's identity map auto-flushes changes to attached objects on commit; the explicit `save` makes the persistence boundary visible)

If you find yourself only ever using one of `add` / `save`, drop the other.

### 6. `get_or_raise` for the common "load or fail the use case" path

Services constantly do "load this thing or fail the use case." Codifying it in the repo eliminates the `if order is None: raise OrderNotFoundException(id)` boilerplate in every service method.

```python
async def get_or_raise(self, order_id: UUID) -> Order:
    order = await self.get(order_id)
    if order is None:
        raise OrderNotFoundException(order_id)
    return order
```

Both `get` and `get_or_raise` exist because some callers need "None is fine" (e.g. "check if exists"). The pair is cohesive; one calls the other.

### 7. Custom queries are named methods, not filter objects

Don't build a generic `def find(filter: OrderFilter) -> list[Order]`. Add named methods per real query:

```python
async def list_for_customer(self, customer_id: UUID) -> AsyncIterator[Order]: ...
async def list_recent_high_value(self, *, since: datetime, min_total: Decimal) -> AsyncIterator[Order]: ...
async def count_placed_today(self) -> int: ...
```

Named methods read like documentation of what queries the app actually runs. Filter objects look DRY but lose those names; `ty` can't catch "a filter that's never satisfiable."

Add a query method when a service needs it. Inline `select(...)` calls anywhere outside the repo are bugs.

### 8. Domain exceptions live next to the model

`OrderNotFoundException`, `OrderAlreadyPlacedException`, etc. are domain words. They live in `app/models/order.py`, next to `Order` itself. They inherit from the cross-cutting bases in `app/common/exceptions.py` (`NotFoundException`, `ConflictException`, ...) so they map to HTTP via the global handlers.

```python
# app/common/exceptions.py
class AppException(Exception): ...
class NotFoundException(AppException): ...        # → 404
class ConflictException(AppException): ...        # → 409
class InvalidInputException(AppException): ...      # → 400

# app/models/order.py
class OrderNotFoundException(NotFoundException): ...
class OrderAlreadyPlacedException(ConflictException): ...
```

Adding a new domain exception means adding one class next to the model. No handler edits, no per-route try/except.

### 9. Use `relationship(lazy="selectin")` for child collections

Async SQLAlchemy is sharp on lazy loading. `lazy="selectin"` eagerly loads children with a second SELECT after the parent — safe with async, fast for the common case. The alternative (`lazy="joined"`) works too but creates a wider cartesian.

```python
lines: Mapped[list["OrderLine"]] = relationship(
    cascade="all, delete-orphan",
    lazy="selectin",
)
```

Without an explicit loading strategy you'll hit `MissingGreenlet` on attribute access after commit.

### 10. `expire_on_commit=False` on the sessionmaker is mandatory

This isn't strictly aggregate code, but it has to be set in `app/db/__init__.py` or `repo.save` / `schema.from_model` will fail:

```python
app.state.db_session_factory = async_sessionmaker(pool, expire_on_commit=False)
```

After `session.commit()`, SA by default *expires* every attached object so the next attribute access triggers a re-fetch. In async, that re-fetch is a coroutine — and accessing it from a non-async context (like a Pydantic field) raises `MissingGreenlet`. Setting `expire_on_commit=False` keeps the attributes loaded.

## When to break these rules

- **Behavior on SA model** — if a method does no I/O but is complex enough to want sub-millisecond unit tests without a DB, factor the pure logic into a domain service/policy that the model or application service calls. Or switch to `python-pure-domain-layer`.
- **`get_or_raise`** — drop it if every caller wants `None` semantics. Add it when 2+ services duplicate the "raise if missing" pattern.
- **`add` vs `save` split** — fine to use just `save` if your app has no perf-sensitive insert path. Choose the API your services actually use.
- **`relationship(lazy="selectin")`** — for relationships you never access via the parent, use `lazy="raise"` to force explicit loading and catch bugs early.

## Anti-patterns this displaces

- **Singleton repo** — repos are constructed per-request via FastAPI `Depends`. Never module-level singletons; the `AsyncSession` is per-request.
- **Generic filter-based base class** — `class BaseRepo[T]: async def find(self, filter: dict) -> list[T]`. The query API tries to be one-size-fits-all and immediately breaks down per aggregate (some need `WHERE` joins, some need windowing, some need raw SQL). A base repo for CRUD basics (`get`, `add`, `save`, `get_or_raise`) IS fine — Cosmic Python uses one. The anti-pattern is trying to generalize *queries*, not trying to generalize *CRUD*.
- **Fat router** — routes that load, mutate, and save in a try/except. The aggregate's methods enforce invariants; the service orchestrates; the route just calls the service.

### Optional base repo for CRUD

If you have 5+ aggregates and the `get`/`add`/`save`/`get_or_raise` shape is identical across them, factor a typed base:

```python
class BaseRepo[T: Base]:
    def __init__(self, session: AsyncSession, model_cls: type[T]) -> None:
        self._session = session
        self._model_cls = model_cls

    async def get(self, id: UUID) -> T | None:
        return await self._session.get(self._model_cls, id)

    async def add(self, item: T) -> None:
        self._session.add(item)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise UniqueViolationException(...) from exc

    async def save(self, item: T) -> None:
        await self._session.merge(item)


class OrderRepo(BaseRepo[Order]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Order)

    async def get_or_raise(self, order_id: UUID) -> Order:
        order = await self.get(order_id)
        if order is None:
            raise OrderNotFoundException(order_id)        # aggregate-specific
        return order

    async def list_for_customer(self, customer_id: UUID) -> AsyncIterator[Order]:
        # specific query, lives on the subclass
        ...
```

`get_or_raise` is on the subclass because the exception is aggregate-specific (`OrderNotFoundException` vs `CustomerNotFoundException`). Or push it to the base if you're fine with a generic `NotFoundException` carrying the model class name.

## See also

- `python-service-and-schema-cohesion` — services that orchestrate aggregates + repos
- `python-fastapi-sa-app-setup` — how `app.state.db_session_factory` and `get_session` get wired
- `python-test-pyramid` — testing aggregates and repos against a real DB
- `python-pure-domain-layer` — the opt-in alternative when invariants justify a separate domain class
- `python-antipatterns-cheatsheet` — Singleton / Abstract Factory redirects
