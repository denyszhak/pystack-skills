from __future__ import annotations

from dataclasses import dataclass
from typing import Self


class InvalidEmailException(ValueError):
    def __init__(self, value: str) -> None:
        super().__init__(f"not a valid email: {value!r}")


@dataclass(frozen=True, slots=True, kw_only=True)
class EmailAddress:
    value: str

    def __post_init__(self) -> None:
        if "@" not in self.value or len(self.value) < 5:
            raise InvalidEmailException(self.value)

    @classmethod
    def from_string(cls, value: str) -> Self:
        return cls(value=value.strip())

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EmailAddress):
            return NotImplemented
        return self.value.lower() == other.value.lower()

    def __hash__(self) -> int:
        return hash(self.value.lower())

    @property
    def local(self) -> str:
        return self.value.split("@", 1)[0]

    @property
    def domain(self) -> str:
        return self.value.split("@", 1)[1]
