from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.common.exceptions import InvalidInputException


class InvalidMoneyException(InvalidInputException):
    code = "invalid_money"


@dataclass(frozen=True, slots=True, kw_only=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise InvalidMoneyException("money amount cannot be negative")
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise InvalidMoneyException("currency must be a three-letter ISO code")

    @classmethod
    def zero(cls, currency: str) -> "Money":
        return cls(amount=Decimal("0.00"), currency=currency.upper())

    def quantized(self) -> "Money":
        return Money(
            amount=self.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            currency=self.currency.upper(),
        )

    def to_minor_units(self) -> int:
        return int((self.quantized().amount * Decimal("100")).to_integral_value())
