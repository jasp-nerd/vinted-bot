"""What has been recorded and not sent yet.

One recorder per process. Every function here is a no-op until `Telemetry` turns
recording on, cheap after that (a counter bump under a lock), and never raises: a report
that cannot be made is dropped, because nothing here may get in the way of an alert.
"""

from __future__ import annotations

import random
import sys
import threading
import time
import uuid
from collections import Counter, deque
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from vinted_bot.telemetry import errors

# Events waiting to be sent. Past this the oldest go, so a long time offline costs memory
# once, not without end.
MAX_EVENTS = 1000
# Measurements kept per name between two heartbeats, as a random sample past this.
MAX_SAMPLES = 1000
# The same error is reported once an hour at most; the repeats are counted instead.
ERROR_EVERY_S = 3600.0
# And no more than this many error reports a day in all.
MAX_ERRORS_PER_DAY = 50


@dataclass(frozen=True, slots=True)
class Pending:
    """An event as it will be sent."""

    uuid: str
    name: str
    properties: dict[str, Any]
    timestamp: str


@dataclass(slots=True)
class _State:
    active: bool = False
    counters: Counter[str] = field(default_factory=Counter)
    samples: dict[str, list[float]] = field(default_factory=dict)
    sample_counts: Counter[str] = field(default_factory=Counter)
    # Every measurement added up, not only the kept sample, so averages across installs
    # come out exact (sum of sums over sum of counts).
    sample_sums: dict[str, float] = field(default_factory=dict)
    events: deque[Pending] = field(default_factory=lambda: deque(maxlen=MAX_EVENTS))
    milestones: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_sent: dict[str, float] = field(default_factory=dict)
    errors_day: int = 0
    errors_today: int = 0


_lock = threading.Lock()
_state = _State()
_rng = random.Random()


def _pending(name: str, properties: dict[str, Any]) -> Pending:
    return Pending(
        uuid=str(uuid.uuid4()),
        name=name,
        properties=properties,
        timestamp=datetime.now(UTC).isoformat(timespec="milliseconds"),
    )


# --- Switching on and off -----------------------------------------------------------


def activate() -> None:
    with _lock:
        _state.active = True


def deactivate() -> None:
    """Stop recording and forget everything not sent yet."""
    with _lock:
        _state.active = False
        _state.counters.clear()
        _state.samples.clear()
        _state.sample_counts.clear()
        _state.sample_sums.clear()
        _state.events.clear()
        _state.milestones.clear()
        _state.last_sent.clear()


def is_active() -> bool:
    return _state.active


# --- Recording ------------------------------------------------------------------------


def count(name: str, n: int = 1) -> None:
    """Add `n` to one of the day's totals."""
    if not _state.active or n <= 0:
        return
    with _lock:
        _state.counters[name] += n


def sample(name: str, value: float) -> None:
    """Keep a measurement, such as how long Vinted took to answer, for the day's summary."""
    if not _state.active:
        return
    with _lock:
        _state.sample_counts[name] += 1
        _state.sample_sums[name] = _state.sample_sums.get(name, 0.0) + value
        kept = _state.samples.setdefault(name, [])
        if len(kept) < MAX_SAMPLES:
            kept.append(value)
        else:
            # Reservoir sampling: every measurement of the day has the same chance to stay.
            slot = _rng.randrange(_state.sample_counts[name])
            if slot < MAX_SAMPLES:
                kept[slot] = value


def event(name: str, *, once_per_s: float | None = None, key: str = "", **properties: Any) -> None:
    """Note that something happened. With `once_per_s`, repeats within that time are
    dropped, told apart by `key`: a form that saves at every keystroke is one use."""
    if not _state.active:
        return
    with _lock:
        if once_per_s is not None:
            now = time.monotonic()
            slot = f"{name}|{key}"
            last = _state.last_sent.get(slot)
            if last is not None and now - last < once_per_s:
                return
            _state.last_sent[slot] = now
        _state.events.append(_pending(name, properties))


def milestone(name: str, **properties: Any) -> None:
    """A first time worth knowing about (the first search, the first alert).

    `Telemetry` sends it once per install, with how long after installing it came, and
    ignores it from then on.
    """
    if not _state.active:
        return
    with _lock:
        _state.milestones.setdefault(name, properties)


def _error_allowed(fingerprint: str) -> bool:
    now = time.monotonic()
    day = int(time.time() // 86_400)
    if _state.errors_day != day:
        _state.errors_day, _state.errors_today = day, 0
    last = _state.last_sent.get(fingerprint)
    if (last is not None and now - last < ERROR_EVERY_S) or (
        _state.errors_today >= MAX_ERRORS_PER_DAY
    ):
        _state.counters["errors_repeated"] += 1
        return False
    _state.last_sent[fingerprint] = now
    _state.errors_today += 1
    return True


def capture_exception(exc: BaseException, *, where: str, handled: bool = True) -> None:
    """Report an error, with its stack, from the place named by `where`."""
    if not _state.active:
        return
    fingerprint = errors.fingerprint(exc, where)
    exceptions = errors.exception_list(exc, handled=handled)
    with _lock:
        if not _error_allowed(f"error|{fingerprint}"):
            return
        _state.events.append(
            _pending(
                "$exception",
                {
                    "$exception_list": exceptions,
                    "$exception_level": "error",
                    "where": where,
                },
            )
        )


def capture_message(name: str, detail: str | None = None) -> None:
    """Report an error the app noticed without an exception, under its log name."""
    if not _state.active:
        return
    with _lock:
        if not _error_allowed(f"message|{name}"):
            return
        _state.events.append(
            _pending(
                "$exception",
                {
                    "$exception_list": errors.message_list(name, detail),
                    "$exception_level": "error",
                    "where": name,
                },
            )
        )


# --- Taking what was recorded ---------------------------------------------------------


def take_events() -> list[Pending]:
    with _lock:
        taken = list(_state.events)
        _state.events.clear()
        return taken


def requeue(events: list[Pending]) -> None:
    """Put back events that could not be sent, ahead of anything newer."""
    if not _state.active:
        return
    with _lock:
        newer = list(_state.events)
        _state.events.clear()
        _state.events.extend(events + newer)


def take_milestones() -> dict[str, dict[str, Any]]:
    with _lock:
        taken = dict(_state.milestones)
        _state.milestones.clear()
        return taken


def _percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(share * (len(ordered) - 1)))]


def take_totals() -> tuple[dict[str, int], dict[str, dict[str, float]]]:
    """The counters and a summary of each measurement, and start again from zero."""
    with _lock:
        counters = dict(_state.counters)
        summaries = {
            name: {
                "count": _state.sample_counts[name],
                "sum": round(_state.sample_sums.get(name, 0.0), 1),
                "p50": round(_percentile(values, 0.5), 1),
                "p95": round(_percentile(values, 0.95), 1),
                "max": round(max(values), 1),
            }
            for name, values in _state.samples.items()
            if values
        }
        _state.counters.clear()
        _state.samples.clear()
        _state.sample_counts.clear()
        _state.sample_sums.clear()
        return counters, summaries


def peek_counters() -> dict[str, int]:
    with _lock:
        return dict(_state.counters)


def restore_counters(saved: object) -> None:
    """Add counters kept from before a restart to today's."""
    if not isinstance(saved, dict):
        return
    with _lock:
        _state.counters.update(
            {k: v for k, v in saved.items() if isinstance(k, str) and isinstance(v, int) and v > 0}
        )


# --- From the log ---------------------------------------------------------------------

_LOUD = frozenset({"warning", "error", "critical", "exception"})
# Logged as errors without the exception, which the code reports itself with its stack.
_REPORTED_ELSEWHERE = frozenset({"web.unhandled"})


def log_processor(
    _logger: Any, method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """A structlog step: count warnings by name, and report errors.

    An entry logged with an exception (`log.exception`, or `exc_info=`) is reported with
    its stack; an error without one, such as a reply from Vinted in the wrong shape, is
    reported under its log name. Only the name and the scrubbed `error` field are used,
    never the rest of the entry.
    """
    level = str(event_dict.get("level", method))
    if not _state.active or level not in _LOUD:
        return event_dict
    name = str(event_dict.get("event", ""))
    count(f"log:{name}")
    exc_info = event_dict.get("exc_info")
    exc: BaseException | None = None
    if isinstance(exc_info, BaseException):
        exc = exc_info
    elif isinstance(exc_info, tuple):
        exc = exc_info[1] if len(exc_info) > 1 else None
    elif exc_info:
        exc = sys.exc_info()[1]
    if exc is not None:
        capture_exception(exc, where=name)
    elif level in {"error", "critical"} and name not in _REPORTED_ELSEWHERE:
        detail = event_dict.get("error")
        capture_message(name, str(detail) if detail is not None else None)
    return event_dict
