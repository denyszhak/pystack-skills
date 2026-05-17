"""PEP 695 generic repository — typed by aggregate."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol
from uuid import UUID


class HasId(Protocol):
    id: UUID


class Repo[T: HasId]:
    """Generic repo bound to anything with an `id: UUID`."""

    async def get(self, id: UUID) -> T | None:
        raise NotImplementedError

    async def add(self, item: T) -> None:
        raise NotImplementedError

    async def list_all(self) -> AsyncIterator[T]:
        raise NotImplementedError
        yield  # type: ignore[unreachable]


# Concrete repos pin T at the class level:
#
#   class OrderRepo(Repo[Order]): ...
#   class CustomerRepo(Repo[Customer]): ...
#
# The generic shape is rarely useful in production app code — concrete repos
# with specific methods read better. Use Repo[T] only when you genuinely need
# the same code across aggregate types (e.g. a test helper).
