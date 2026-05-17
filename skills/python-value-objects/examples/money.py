from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Self


class NegativeAmountException(ValueError):
    def __init__(self, amount: Decimal) -> None:
        super().__init__(f"amount must be >= 0, got {amount}")


class InvalidCurrencyException(ValueError):
    def __init__(self, currency: str) -> None:
        super().__init__(f"currency must be 3 letters, got {currency!r}")


class CurrencyMismatchException(ValueError):
    def __init__(self, a: str, b: str) -> None:
        super().__init__(f"currencies differ: {a} vs {b}")


@dataclass(frozen=True, slots=True, kw_only=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise NegativeAmountException(self.amount)
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise InvalidCurrencyException(self.currency)
        # normalize without mutating self (frozen) by using object.__setattr__
        object.__setattr__(self, "currency", self.currency.upper())

    @classmethod
    def zero(cls, currency: str) -> Self:
        return cls(amount=Decimal("0"), currency=currency)

    @classmethod
    def from_cents(cls, cents: int, currency: str) -> Self:
        return cls(amount=Decimal(cents) / 100, currency=currency)

    @classmethod
    def from_string(cls, s: str) -> Self:
        amount_str, currency = s.rsplit(" ", 1)
        return cls(amount=Decimal(amount_str), currency=currency)

    def to_cents(self) -> int:
        return int(self.amount * 100)

    def __add__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __mul__(self, factor: Decimal | int) -> Money:
        return Money(amount=self.amount * Decimal(factor), currency=self.currency)

    def _same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchException(self.currency, other.currency)
