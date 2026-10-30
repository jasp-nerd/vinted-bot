"""Logging setup.

Console output while you are watching it, JSON when something else is collecting it.
Log entries carry the search and site they belong to, so a failing search is easy to spot
among a dozen healthy ones.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, MutableMapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog

# These libraries are chatty at INFO and none of it is about your searches. aiosqlite logs
# every statement at DEBUG, which buried everything else when someone turned DEBUG on to
# attach logs to an issue.
_NOISY_LOGGERS = ("httpx", "httpcore", "aiogram.event", "uvicorn.access", "aiosqlite")


Stamper = Callable[[Any, str, MutableMapping[str, Any]], MutableMapping[str, Any]]


def local_timestamps(tz: ZoneInfo) -> Stamper:
    """Stamp each entry with the time on the reader's clock, offset included.

    UTC stamps in a container whose TZ says Amsterdam made every log line an hour or two
    off from what the dashboard and the alerts said.
    """

    def stamp(
        _logger: Any, _method: str, event: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        event["timestamp"] = datetime.now(tz).isoformat(timespec="seconds")
        return event

    return stamp


def configure(level: str = "INFO", fmt: str = "console", timezone: str = "UTC") -> None:
    """Set up structlog and the standard library logger it bridges to."""
    renderer: structlog.typing.Processor = (
        structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
        if fmt == "console"
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            local_timestamps(ZoneInfo(timezone)),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(level=level, stream=sys.stderr, format="%(message)s")
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str, **initial: Any) -> structlog.stdlib.BoundLogger:
    """Return a logger, optionally pre-bound with context such as a search id."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger.bind(**initial) if initial else logger
