---
name: python-service-and-schema-cohesion
description: |
  Use when designing or editing services and schemas in a FastAPI + SQLAlchemy
  backend: files in `app/services/` and `app/schemas/`. Triggers on edits to
  those directories; on definitions of `class *Service`, `class *Command`,
  `class *Get`; on user mentions of "use case", "service layer", "Pydantic
  schema", "command", "response shape", "from_model", "to_new_X", "cohesion",
  "domain service", "policy", "god service", "business rule extraction".
  Encodes: class-when-state vs function-when-stateless, service returns Pydantic
  schema (not SA model), top-level service owns the transaction with
  `AsyncSession.begin()`, composable collaborators do not commit, pure domain
  services/policies for business rules that do not belong to one aggregate,
  schema naming (*Get / *Create / *Update / *Command), cohesion methods
  (`from_<source>` classmethod inbound, `to_<target>` method outbound), Pydantic v2
  `from_attributes=True`, no `utils.py` / no free transform functions.
  Do NOT use for: repos (use python-aggregate-and-repo), routes (use
  python-fastapi-sa-app-setup).
---

# Service layer and schema cohesion

The service layer is where use cases live: "place an order", "cancel a subscription", "refund a payment". An application service orchestrates aggregates (via repos) and external systems (via clients), owns the top-level transaction boundary, and returns a Pydantic schema — the use case result, ready for serialization.

Pure domain services and policies are extraction tools inside that shape. Use them when a business decision is too large for the application service but does not belong cleanly on one aggregate or value object.

Schemas live next to services because every transformation between domain and wire shape is a method on the schema class. Cohesion is the rule: if there's a translation `X → Y`, it's a method on one of those classes, never a free function.

## When to use this skill

- Adding a new use case (route → service method)
- Modifying an existing service to call new repos/clients
- Defining a new Pydantic schema for API I/O or external system payloads
- Adding a translation between a model and a schema, or between two schemas

## The rules

### 1. Class per file when there's state + multiple methods; functions otherwise

```python
# app/services/checkout.py — class form (shape; full version in examples/checkout_service.py)
class CheckoutService:
    def __init__(self, *, orders: OrderRepo, stripe: StripeClient, session: AsyncSession) -> None:
        self._orders, self._stripe, self._session = orders, stripe, session

    async def place_order(self, cmd: PlaceOrderCommand) -> OrderGet: ...
    async def cancel_order(self, cmd: CancelOrderCommand) -> OrderGet: ...
    async def refund_order(self, cmd: RefundOrderCommand) -> OrderGet: ...

# app/services/refunds.py — function form (single use case, no shared state)
async def issue_refund(
    cmd: RefundOrderCommand,
    *,
    orders: OrderRepo,
    stripe: StripeClient,
    session: AsyncSession,
) -> OrderGet: ...
```

Rule: class when the file has 2+ methods sharing deps. Function (or several functions) when each use case stands alone with no shared state.

Private helpers (used by methods or functions in the same file) stay in the same file as `_helper(...)` — no `utils.py`, no `helpers.py`.

### 2. Service returns a Pydantic schema, not the SA model

Returning the SA model leaks ORM lifecycle into routes (lazy loads after commit, session-bound state). The schema is the contract: a use case produces a `<Resource>Get` shape that the caller can serialize over HTTP, render in a CLI, or pass between services.

```python
# good
async def place_order(self, cmd: PlaceOrderCommand) -> OrderGet:
    ...
    return OrderGet.from_model(order)

# bad: leaks SA model into the caller
async def place_order(self, cmd: PlaceOrderCommand) -> Order:
    ...
    return order
```

The route is one line:

```python
@router.post("", status_code=status.HTTP_201_CREATED)
async def place_order(
    cmd: PlaceOrderCommand,
    service: Annotated[CheckoutService, Depends(get_checkout_service)],
) -> OrderGet:
    return await service.place_order(cmd)
```

### 3. Top-level use case owns the transaction

```python
async def place_order(self, cmd: PlaceOrderCommand) -> OrderGet:
    async with self._session.begin():
        order = cmd.to_new_order()
        order.place()
        await self._orders.add(order)      # writes to session

    return OrderGet.from_model(order)
```

Rules:
- Use `async with self._session.begin()` for write use cases. SQLAlchemy commits on success and rolls back on exception.
- No `commit()` / `begin()` in repos. Repos read/write through the session they're handed.
- No `commit()` / `begin()` in routes. Routes call one service method and return its schema.
- One top-level use case = one transaction owner. That owner is the outer service command method.
- All repos participating in a use case must be built from the same request-scoped `AsyncSession` (FastAPI caches `Depends(get_session)` per request by default).

Don't compose committing service methods. If `CheckoutService.place_order()` needs inventory reservation, don't call `InventoryService.reserve_command()` if that method owns its own transaction. Extract a non-committing collaborator operation:

```python
class InventoryAllocator:
    async def reserve(self, order: Order) -> None:
        # Uses repos built from the same session. No begin(), no commit().
        ...


class CheckoutService:
    async def place_order(self, cmd: PlaceOrderCommand) -> OrderGet:
        async with self._session.begin():
            order = cmd.to_new_order()
            await self._inventory.reserve(order)
            await self._orders.add(order)

        return OrderGet.from_model(order)
```

Top-level command methods own transactions. Composable operations assume the caller already owns the transaction.

### 4. Schema naming: `*Get`, `*Create`, `*Update`, `*Command`

| Suffix | When | Example |
|---|---|---|
| `*Get` | Response shape (returned by routes / services) | `OrderGet`, `LeadGet` |
| `*Create` | Plain-CRUD input for POST when there's no verb semantics | `CustomerCreate` |
| `*Update` | Plain-CRUD input for PATCH | `CustomerUpdate` |
| `*Command` | Input that drives a use case verb (with business semantics) | `PlaceOrderCommand`, `CancelOrderCommand` |

`PlaceOrderCommand` is *not* "create an Order with these fields" — it triggers the checkout use case, which charges a card, allocates inventory, emits events. Different mental model from `CustomerCreate` ("a new row in customers table").

Use the Command suffix when the input is a verb. Use Create/Update for plain CRUD. The split is intentional — it tells you which use case to look for in `app/services/`.

### 5. Cohesion methods — `from_<source>` classmethod inbound, `to_<target>` method outbound

The rule: every transformation lives on one of the involved classes, never as a free function.

```python
# app/schemas/order.py — shape; full version in examples/order_schemas.py
class OrderGet(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    customer_id: UUID
    status: OrderStatus
    total: Decimal
    lines: list[OrderLineGet]

    @classmethod
    def from_model(cls, order: Order) -> Self:        # inbound: classmethod on target
        return cls.model_validate(order)


class PlaceOrderCommand(BaseModel):
    customer_id: UUID
    currency: str
    lines: list[OrderLineInput]

    def to_new_order(self) -> Order: ...              # outbound: method on source
```

Pattern:
- **Inbound (foreign → this class)** — `@classmethod from_<source>(cls, x) -> Self`. Lives on the *target* class. `OrderGet.from_model(order)` / `LeadGet.from_openai(json)`.
- **Outbound (this class → foreign)** — `def to_<target>(self) -> Target`. Lives on the *source* class. `cmd.to_new_order()` / `cmd.to_openai()`.

The rule is symmetric and learnable. Apply it everywhere translations happen.

### 6. `ConfigDict(from_attributes=True)` on response schemas; wrap the call inside `from_model`

```python
class OrderGet(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    # ...

    @classmethod
    def from_model(cls, order: Order) -> Self:
        return cls.model_validate(order)
```

`from_attributes=True` enables Pydantic to read SA model attributes by name. But callers should still go through `from_model` — it's the documented contract for "how to build me." If the mapping ever stops being trivial (renames, derived fields), you change one method, not every caller.

### 7. YAGNI on schemas — don't pre-create what nothing uses

Don't pre-write `OrderUpdate` if no route updates orders. Don't add `OrderGet.from_dict(...)` because "someone might need it." Don't define `OrderListGet = list[OrderGet]` as a TypeAlias because "lists deserve names" — they don't.

Add a schema when a route or service needs it; add a classmethod when a translation is actually called.

### 8. Service constructor takes deps as kw-only

```python
class CheckoutService:
    def __init__(
        self,
        *,
        orders: OrderRepo,
        stripe: StripeClient,
        session: AsyncSession,
    ) -> None:
        self._orders = orders
        self._stripe = stripe
        self._session = session
```

`*,` makes every arg keyword-only. The call site (`get_checkout_service` in `app/deps/services.py`) becomes self-documenting and refactor-safe — reorder fields without breaking callers.

Private attributes are `_underscore` (Python convention). Pythonic, no need for explicit `private`.

### 9. Services don't talk to FastAPI

The service is HTTP-agnostic. It doesn't import `Request`, `Response`, `HTTPException`, or any FastAPI symbol. It returns Pydantic schemas and raises typed `*Exception`s; the router/exception-handler layer translates to HTTP.

This means: services are reusable in CLIs, batch jobs, gRPC, or tests, with no rewiring.

### 10. One service file per use case area, named by the area

`app/services/checkout.py` — orders, charges, refunds (the checkout area)
`app/services/onboarding.py` — customer signup, email verification, first-login setup
`app/services/billing.py` — subscriptions, invoices, dunning

Not `app/services/order.py` — that conflates "the Order resource" with "what use cases involve an order." The file name describes the *behavior*, not the *entity*.

A single service class can touch multiple aggregates (CheckoutService touches Order + Customer + maybe Inventory).

### 11. Extract pure domain services/policies before a service becomes a god class

Application services orchestrate. Domain services and policies decide.

Keep I/O in the application service:
- repo loads/saves
- `AsyncSession.begin()`
- external HTTP/client calls
- message publishing/outbox writes
- Pydantic command/response schemas

Move pure business decisions into a domain service or policy when the logic:
- spans multiple aggregates/value objects
- is reused by 2+ use cases
- has enough branching that it deserves direct unit tests
- would make the application service read like a wall of business rules instead of an orchestration flow

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class FulfillmentPlanner:
    split_threshold: int

    def plan(self, *, order: Order, inventory: InventorySnapshot) -> FulfillmentPlan:
        if order.line_count > self.split_threshold:
            return FulfillmentPlan.split(order, inventory)
        return FulfillmentPlan.single_shipment(order, inventory)


class CheckoutService:
    def __init__(
        self,
        *,
        orders: OrderRepo,
        inventory: InventoryClient,
        planner: FulfillmentPlanner,
        session: AsyncSession,
    ) -> None:
        self._orders = orders
        self._inventory = inventory
        self._planner = planner
        self._session = session

    async def place_order(self, cmd: PlaceOrderCommand) -> OrderGet:
        async with self._session.begin():
            order = await self._orders.get_or_raise(cmd.order_id)
            snapshot = await self._inventory.snapshot_for(order)
            plan = self._planner.plan(order=order, inventory=snapshot)
            order.reserve(plan)

        return OrderGet.from_model(order)
```

Rules for extracted domain services/policies:
- Sync by default. If it awaits, it is probably an application service or client.
- No `AsyncSession`, repos, FastAPI, Pydantic API schemas, or HTTP clients.
- Input/output are aggregates, value objects, plain dataclasses, enums, and primitives.
- Use a plain function when there is no configuration/state. Use a frozen dataclass when the rule carries named parameters.
- In the default SA-model style, keep small local policies in the same service file; promote to `app/services/<area>_policy.py` or `app/services/<area>/policies.py` when reused or long. Do not create `app/domain/` just for one policy.

## When to break these rules

- **Class vs function** — a function-form service with 1 method is fine. Promote to class when 2+ methods share deps.
- **Return schema vs SA model** — for internal service-to-service composition, returning the SA model is sometimes cleaner. Pick one direction per project and stick to it.
- **Raw session vs UnitOfWork** — `AsyncSession` is the default unit of work. Add a custom UoW only when it owns extra behavior beyond a transaction: outbox/event collection, multi-entrypoint wiring, or a real need to make repo construction impossible to split.
- **Domain service/policy extraction** — don't create one just because DDD has a name for it. Extract only when a pure business rule is hard to read, hard to test, or reused from inside the application service.
- **Cohesion** — when a translation is genuinely many-to-many (3 sources × 4 targets), accept the cohesion break and use a small module of free functions. Rare.
- **Naming** — Read/Get is mostly a style call. If your team prefers `*Read`, that's fine; stay consistent.

## Anti-patterns this displaces

- **`utils.py`** — every `def convert_X_to_Y(x):` belongs on `X` (as `to_Y(self)`) or on `Y` (as `from_X(cls, x)`).
- **Service classmethod constructors that build their own deps** — `CheckoutService.create()` that internally instantiates `OrderRepo()` and `StripeClient()` is reinventing DI poorly. Deps come in via `__init__`.
- **Composing committing services** — a top-level service method calling another top-level service method makes transaction ownership unclear. Extract a non-committing collaborator instead.
- **God service** — a service method that loads data, owns the transaction, calls clients, and also embeds hundreds of lines of pricing/eligibility/allocation rules. Keep orchestration in the application service; extract pure decisions to domain services/policies.
- **`@staticmethod` on a service that just calls a free function** — if it's a `@staticmethod`, it's a free function with extra steps.
- **Routes that try/except domain exceptions** — exception handlers do the routing. Routes never `try/except`.

## See also

- `python-aggregate-and-repo` — the aggregates and repos that services orchestrate
- `python-fastapi-sa-app-setup` — `get_checkout_service` provider in `app/deps/services.py`
- `python-external-client` — clients the services depend on
- `python-test-pyramid` — testing services against a real DB
