---
name: python-typing-idioms
description: |
  Use when writing or modifying typed Python code (any project — libraries, services,
  scripts). Triggers on `.py` files with type annotations; on imports from `typing`,
  `typing_extensions`, `collections.abc`; on user questions about type hints,
  Protocol, generics, NewType, PEP 695. Encodes: Protocol over ABC for ports,
  `Self` for classmethod constructors, `NewType` for ID safety, PEP 695 type
  aliases and generics, `Annotated` for FastAPI/Pydantic metadata, alternative
  constructors via `@classmethod from_X(cls, ...) -> Self`, avoiding `Any`,
  narrowing patterns.
  Do NOT use for: untyped Python codebases that aren't ready to adopt type hints.
---

# Python typing idioms

Modern typed Python is a different language than typed Python five years ago. PEP 695 (Python 3.12) made generics and type aliases first-class. `Protocol` finally displaced `ABC` for most interface use cases. The `Self` type lets `@classmethod` constructors and builder-style methods type themselves correctly.

This skill encodes the idioms that hold up in 2026 typed Python.

## When to use this skill

Apply these rules whenever you're:

- Writing a new module with type annotations
- Adding types to existing code
- Designing a class hierarchy, especially one used as a port/interface
- Building cohesion methods (`from_X`, `to_Y`)
- Defining ID types or other domain primitives
- Working with FastAPI `Depends` (the `Annotated[X, Depends(...)]` pattern)

## The rules

### 1. `Protocol` for interfaces; `ABC` only when you need shared implementation

`abc.ABC` couples interface to inheritance. `Protocol` types by *shape*, which matches Python's duck typing and lets unrelated classes satisfy the contract without inheriting.

```python
from typing import Protocol

class Notifier(Protocol):
    async def send(self, to: str, body: str) -> None: ...


class EmailNotifier:                      # no Notifier in bases
    async def send(self, to: str, body: str) -> None: ...


class SMSNotifier:
    async def send(self, to: str, body: str) -> None: ...


async def notify(notifier: Notifier, to: str, body: str) -> None:
    await notifier.send(to, body)


await notify(EmailNotifier(), "user@x.com", "hi")
await notify(SMSNotifier(), "+1...", "hi")
```

Use `ABC` only when you genuinely need partial implementation that subclasses must extend. For pure interfaces (the common case), `Protocol`.

### 2. `Self` for classmethod constructors and self-returning methods

`Self` (PEP 673, Python 3.11+) lets a method return "the subclass that called me" without `TypeVar` ceremony.

```python
from typing import Self
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class Money:
    amount: Decimal
    currency: str

    @classmethod
    def zero(cls, currency: str) -> Self:
        return cls(amount=Decimal("0"), currency=currency)

    def with_amount(self, amount: Decimal) -> Self:
        return type(self)(amount=amount, currency=self.currency)
```

Subclassing `Money` keeps the type narrow: `USDMoney.zero("USD")` returns `USDMoney`, not `Money`.

### 3. `NewType` for ID safety

Raw `UUID` (or `int`, or `str`) lets you accidentally pass a `CustomerId` where an `OrderId` is expected. `NewType` creates a distinct type at type-check time with zero runtime cost.

```python
from typing import NewType
from uuid import UUID

OrderId = NewType("OrderId", UUID)
CustomerId = NewType("CustomerId", UUID)
ProductId = NewType("ProductId", UUID)


def get_order(order_id: OrderId) -> Order: ...


customer_id = CustomerId(uuid4())
get_order(customer_id)   # ty/mypy: error — CustomerId is not OrderId
```

Use `NewType` for every primary key and every identifier the user can hold. Cheap; pays for itself the first time you would have shipped a swap.

### 4. PEP 695 type aliases over `TypeAlias` and `Union`

PEP 695 (Python 3.12+) made type aliases a real statement.

```python
# Modern
type OrderEvent = OrderPlaced | OrderCancelled | OrderRefunded
type JSON = dict[str, "JSON"] | list["JSON"] | str | int | float | bool | None

# Old (still works, but verbose)
from typing import TypeAlias
OrderEvent: TypeAlias = "OrderPlaced | OrderCancelled | OrderRefunded"
```

`type` aliases are forward-reference-safe (the RHS isn't evaluated until you ask) — no `from __future__ import annotations` dance needed.

### 5. PEP 695 generics over `TypeVar`

PEP 695 generics use square-bracket syntax on the class or function — no `TypeVar` declaration needed.

```python
# Modern
class Repo[T]:
    async def get(self, id: UUID) -> T | None: ...
    async def add(self, item: T) -> None: ...


def first[T](items: Iterable[T]) -> T | None: ...

# Old
from typing import TypeVar
T = TypeVar("T")
class Repo(Generic[T]):
    async def get(self, id: UUID) -> T | None: ...
```

Reserve old-style `TypeVar` only for variance you need to declare (`TypeVar("T", covariant=True)`); PEP 695 has its own syntax for variance.

### 6. `Annotated` for FastAPI `Depends` and Pydantic metadata

`Annotated[X, metadata]` attaches non-type metadata to a type. FastAPI uses it for `Depends`; Pydantic uses it for `Field`. Always prefer the `Annotated` form over default-argument-as-marker.

```python
from typing import Annotated
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

router = APIRouter()


@router.get("/orders/{order_id}")
async def get_order(
    order_id: UUID,
    service: Annotated[OrderService, Depends(get_order_service)],
) -> OrderGet:
    return await service.get(order_id)


class CreateUser(BaseModel):
    email: Annotated[str, Field(min_length=5, max_length=254)]
    age: Annotated[int, Field(ge=0, le=150)]
```

`def get_order(... service: OrderService = Depends(get_order_service))` works but ages badly — the type and the metadata get separated by `=`, and it doesn't compose cleanly with chained metadata.

### 7. Alternative constructors are `@classmethod` returning `Self`

The Factory Method pattern in Python is a classmethod. Name them `from_<source>`. The source name follows the type or origin of the data.

```python
from typing import Self
from pydantic import BaseModel


class OrderGet(BaseModel):
    id: UUID
    customer_id: UUID
    status: str

    @classmethod
    def from_model(cls, order: Order) -> Self:
        return cls.model_validate(order, from_attributes=True)


class LeadGet(BaseModel):
    id: int
    title: str

    @classmethod
    def from_openai(cls, payload: dict[str, Any]) -> Self:
        return cls(id=int(payload["ID"]), title=payload["TITLE"])
```

Don't write `make_order_get(order)` or `convert_to_lead_get(payload)` as free functions. Cohesion: the schema knows how to be built from each of its sources.

### 8. Avoid `Any`; if forced, isolate it at the boundary

`Any` disables type checking entirely. It's necessary at trust boundaries (parsing JSON, calling untyped libraries) — but it shouldn't *spread*.

```python
# Bad — Any spreads through the rest of the function
def process(payload: dict[str, Any]) -> Any:
    name = payload["name"]      # name: Any
    return name.strip()         # return type: Any

# Good — Any is converted to a typed shape immediately
def process(payload: dict[str, Any]) -> str:
    name: str = payload["name"]
    return name.strip()


# Even better — parse with Pydantic at the boundary
class Payload(BaseModel):
    name: str

def process(raw: dict[str, Any]) -> str:
    return Payload.model_validate(raw).name.strip()
```

When you must use `Any`, narrow it to a typed value as soon as possible.

### 9. Narrow with `match` or `isinstance`; use `TypeIs` for custom predicates

```python
def render(event: OrderEvent) -> str:
    match event:
        case OrderPlaced(order_id=oid):
            return f"placed {oid}"
        case OrderCancelled(reason=r):
            return f"cancelled: {r}"
        case OrderRefunded(amount=a):
            return f"refunded {a}"
```

For custom predicates, prefer `TypeIs` (PEP 742, Python 3.13+) over `TypeGuard` — `TypeIs` narrows in both branches, `TypeGuard` only in the `True` branch.

```python
from typing import TypeIs

def is_uuid(s: str) -> TypeIs[str]:        # placeholder; real example below
    ...

# More realistic — narrowing a heterogeneous list
from typing import TypeIs

def is_str(x: object) -> TypeIs[str]:
    return isinstance(x, str)

def first_str(items: list[object]) -> str | None:
    for x in items:
        if is_str(x):
            return x                        # ty: x is str
    return None
```

### 10. `Final` for module-level constants; `Literal` for discriminators

```python
from typing import Final, Literal

MAX_RETRIES: Final = 3
DEFAULT_TIMEOUT: Final = 30.0

type Status = Literal["draft", "placed", "paid", "cancelled"]


def transition(order: Order, to: Status) -> None: ...

transition(order, "placed")    # ok
transition(order, "shipped")   # ty: not a Literal["draft", ...]
```

`Final` prevents accidental rebinding and signals "this is a constant" to readers and to `ty`. `Literal` gives a small enum-like type without the ceremony of `Enum` — fine for status strings, tags, modes.

For larger sets or sets with behavior, use `StrEnum`.

## When to break these rules

- **`Protocol`/`ABC`** — if you need to enforce interface usage at construction time (raise on instantiation of an abstract class), `ABC` does that; `Protocol` doesn't.
- **`Self`** — methods that always return a fixed concrete class (not the subclass) should name the class explicitly.
- **`NewType`** — primary keys and identifiers, yes; not every `int` is worth wrapping. Reserve for things you can confuse.
- **`Any`** — at the JSON parsing boundary, before Pydantic validation. Once parsed, never again.
- **`TypeIs`/`TypeGuard`** — only needed when `isinstance` and `match` can't express the predicate. Don't reach for them by default.

## See also

- `python-value-objects` — uses `NewType`, `Self`, frozen dataclasses
- `python-stdlib-idioms` — uses `Iterable[T]`, `AsyncIterator[T]` from `collections.abc`; tree composition with Protocol + dataclass
- `python-antipatterns-cheatsheet` — Factory Method redirect (use `@classmethod` returning `Self`)
