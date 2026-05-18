from collections import defaultdict
from collections.abc import Awaitable
from typing import Any, Protocol, TypeVar

import structlog

E = TypeVar("E")


class Handler(Protocol[E]):
    def __call__(self, event: E) -> Awaitable[None]: ...


log = structlog.get_logger(__name__)


class MessageBus:
    def __init__(self, *, swallow_handler_errors: bool = True) -> None:
        self._handlers: dict[type[object], list[Handler[Any]]] = defaultdict(list)
        self._swallow_handler_errors = swallow_handler_errors

    def subscribe(self, event_type: type[E], handler: Handler[E]) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: object) -> None:
        handlers = self._handlers.get(type(event), [])
        log.info("bus.publish", event=type(event).__name__, handlers=len(handlers))
        for handler in handlers:
            try:
                await handler(event)
            except Exception:
                log.exception(
                    "bus.handler.failed",
                    event=type(event).__name__,
                    handler=getattr(handler, "__name__", repr(handler)),
                )
                if not self._swallow_handler_errors:
                    raise
