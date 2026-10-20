---
name: python-value-objects
description: |
  Use when defining domain primitives in any Python project — Money, EmailAddress,
  Color, Coordinates, IDs, anything where two instances with the same fields should
  be equal and where the values must satisfy invariants. Triggers on `.py` files
  defining `@dataclass`, on user questions about value objects, immutability,
  frozen dataclasses, slots, kw_only. Encodes: frozen + slots + kw_only,
  `__post_init__` invariants, equality by value, no identity, methods over
  external utility functions.
  Do NOT use for: aggregate roots (mutable, identity-based — see
  python-aggregate-and-repo); Pydantic models for HTTP I/O (see
  python-service-and-schema-cohesion).
license: MIT
compatibility: Python 3.12+.
metadata:
  tier: python
---

# Python value objects

A value object is a small, immutable bundle of fields that's equal to another instance with the same values. `Money(10, "USD") == Money(10, "USD")` is true. It has no identity — there's no `id` field, no "this is the canonical instance" semantics. You make new ones; you don't mutate them.

Domain code is much easier to reason about when the primitives are value objects: invariants live in one place, equality is meaningful, and "did this change?" is answered by `==` / `!=`.

This skill encodes the canonical shape: frozen dataclass with slots, kw_only fields, invariants in `__post_init__`, behavior as methods on the class.

## When to use this skill

Apply when defining:

- Domain primitives — `Money`, `EmailAddress`, `PhoneNumber`, `Address`, `Coordinates`
- Configuration values that should be tamper-proof
- Event payloads (events are facts; facts don't change)
- Result types from pure computations

Don't apply to:

- Anything with an `id` and a lifecycle (use `python-aggregate-and-repo`)
- API-shaped DTOs that need Pydantic validation (use `python-service-and-schema-cohesion`)
- Mutable holders of state (consider whether you actually need a class at all)

## The rules

### 1. `@dataclass(frozen=True, slots=True, kw_only=True)` — always all three

```python
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class Money:
    amount: Decimal
    currency: str
```

Why each flag:

- **`frozen=True`** — instances can't be mutated after construction. The whole point of a value object.
- **`slots=True`** — no `__dict__`; significantly smaller in memory, faster attribute access, catches typos at runtime (assigning to an unknown attribute raises). Modern Python (3.10+) supports this for dataclasses natively.
- **`kw_only=True`** — every field is keyword-only at the call site. `Money(10, "USD")` is rejected; `Money(amount=10, currency="USD")` is required. This makes call sites self-documenting and lets you reorder fields without breaking callers.

These three flags together are the canonical value object shape. Make them the default; deviate only with a reason.

### 2. Invariants in `__post_init__`, raising typed exceptions

```python
from app.common.exceptions import InvalidInputException


@dataclass(frozen=True, slots=True, kw_only=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise InvalidCurrencyException(self.currency)


class InvalidCurrencyException(InvalidInputException): ...
```

Invariants belong with the data. A three-letter currency is true of *every* `Money`, so `Money(amount=..., currency="dollars")` fails at construction — not "gets flagged elsewhere." Exception types are domain words, raised at the moment the data is wrong.

Only put an invariant on the value object if it holds for every use of it. `Money` is **signed**: refunds, credits, and balances go below zero, and `a - b` has to be able to. "Must not be negative" is a rule of the thing *holding* the money — a unit price, a payment amount — so it's checked there:

```python
def add_line(self, *, product_id: UUID, quantity: int, unit_price: Money) -> None:
    if unit_price.is_negative:
        raise NegativeUnitPriceException(unit_price)
    ...
```

**Exception base.** In a PyStack service, value-object exceptions inherit from `InvalidInputException` (`app/common/exceptions.py`), so the global handler maps them to 400 like every other domain error — a bare `ValueError` falls through to a 500. In a standalone library with no app exception hierarchy, `ValueError` is the right base.

**Location.** Value objects shared across aggregates (`Money`, `EmailAddress`) live in `app/common/value_objects.py`. One used by a single aggregate lives in that aggregate's model file.

### 3. Behavior as methods on the class

Operations on value objects are methods on the value object — never free `add_money(a, b)` functions.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Money:
    amount: Decimal
    currency: str

    def __add__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise CurrencyMismatchException(self.currency, other.currency)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise CurrencyMismatchException(self.currency, other.currency)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __mul__(self, factor: Decimal | int) -> "Money":
        return Money(amount=self.amount * Decimal(factor), currency=self.currency)

    def __neg__(self) -> "Money":
        return Money(amount=-self.amount, currency=self.currency)

    @property
    def is_negative(self) -> bool:
        return self.amount < 0

    @classmethod
    def zero(cls, currency: str) -> "Money":
        return cls(amount=Decimal("0"), currency=currency)
```

`total_a + total_b` reads naturally. `add_money(total_a, total_b)` reads like an accountant's macro.

### 4. Alternative constructors as `@classmethod`

Need to build a `Money` from a string? A database row? A JSON object? Each one is a classmethod on `Money`.

```python
@classmethod
def from_string(cls, s: str) -> "Money":
    amount_str, currency = s.rsplit(" ", 1)
    return cls(amount=Decimal(amount_str), currency=currency)

@classmethod
def from_cents(cls, cents: int, currency: str) -> "Money":
    return cls(amount=Decimal(cents) / 100, currency=currency)
```

Symmetric outbound: `def to_cents(self) -> int: return int(self.amount * 100)`.

### 5. Equality and hashability are automatic

`frozen=True` makes the class hashable. Equality compares all fields. You don't write `__eq__` or `__hash__`.

```python
Money(amount=Decimal("10"), currency="USD") == Money(amount=Decimal("10"), currency="USD")
# True

{Money(amount=Decimal("10"), currency="USD")}    # works — frozen makes hash work
```

Override `__eq__` only when you want a custom equality (e.g. case-insensitive `EmailAddress`).

### 6. Use `NewType` for ID-like value objects

For identifiers, a `NewType` over `UUID`/`int` is lighter than a full dataclass and gives type-level safety without runtime cost.

```python
from typing import NewType
from uuid import UUID

OrderId = NewType("OrderId", UUID)
CustomerId = NewType("CustomerId", UUID)
```

Use a full value object class when there's behavior, validation, or multiple fields. Use `NewType` when it's a single typed wrapper around a primitive.

SQLAlchemy can't map a `NewType` column on its own — see `python-typing-idioms` rule 3 for where PyStack uses `NewType` IDs and how to register them on `Base` if you want them on models too.

### 7. Persisting value objects on SA models

In the default style, value objects live *on* SA models: `composite()` for multi-column values like `Money`, a `TypeDecorator` for single-column ones like `EmailAddress`. The mapping code lives in `python-aggregate-and-repo` (rule 11); the value object stays free of SQLAlchemy imports.

### 8. Don't reach for Pydantic for value objects

Pydantic is great for I/O (parsing untrusted JSON, schema validation for HTTP). It's overkill for internal domain primitives: it carries serialization machinery, alias config, `model_validate` calls — none of which a `Money` needs.

```python
# Reach for this only at I/O boundaries
from pydantic import BaseModel

class MoneyDto(BaseModel):
    amount: Decimal
    currency: str

# Inside the domain, use the dataclass
@dataclass(frozen=True, slots=True, kw_only=True)
class Money:
    amount: Decimal
    currency: str
```

Put both translations on the DTO — `MoneyDto.from_money(money)` inbound, `dto.to_money()` outbound — so the value object never imports Pydantic.

## When to break these rules

- **`slots=True`** breaks multiple inheritance if subclasses don't also use slots. Drop it only if you have a real reason for an inheritance tree (rare — for value objects, just compose).
- **`kw_only=True`** can feel ceremonious for 1-field types. Keep it anyway for consistency; the readability win is real at 3+ fields.
- **`frozen=True`** doesn't deep-freeze contained mutable types (e.g. a `list` field is still mutable). For value objects, prefer `tuple` over `list`, `frozenset` over `set`, or wrap in immutable containers.

## See also

- `python-typing-idioms` — `NewType`, `Self`, narrowing
- `python-aggregate-and-repo` — mutable, identity-based, contains value objects
