"""Canonical app/common/logging.py.

configure_logging(env=...) sets up structlog with a ContextVar-based
correlation_id and bridges stdlib logging into the same stream.
"""

from __future__ import annotations

import contextvars
import logging
from typing import Final

import structlog


correlation_id_var: Final[contextvars.ContextVar[str]] = contextvars.ContextVar(
    "correlation_id",
    default="-",
)


def _add_correlation_id(_logger, _method_name, event_dict):
    event_dict["correlation_id"] = correlation_id_var.get()
    return event_dict


def configure_logging(*, env: str) -> None:
    is_local = env == "local"

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        _add_correlation_id,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: structlog.types.Processor
    if is_local:
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
            foreign_pre_chain=shared_processors,
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)

    # Quiet down chatty libraries
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
