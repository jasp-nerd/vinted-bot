"""Turning an exception into a PostHog error-tracking event.

PostHog groups `$exception` events into issues by type and stack. Frames from this
package carry their line of code, since the code is public anyway; frames from libraries
carry only the module, function and line number; and no frame carries a path from the
user's disk.
"""

from __future__ import annotations

import linecache
import traceback
from types import TracebackType
from typing import Any

from vinted_bot.telemetry.scrub import scrub

# Enough to see where it went wrong, short enough that a deep stack stays small.
MAX_FRAMES = 30
# __cause__ and __context__ followed this many times at most.
MAX_CHAIN = 4

_PACKAGE = "vinted_bot"


def _relative(path: str) -> tuple[str, bool]:
    """A frame's file as it can be shown, and whether it is this package's."""
    normalised = path.replace("\\", "/")
    marker = f"/{_PACKAGE}/"
    if marker in normalised:
        return _PACKAGE + "/" + normalised.rsplit(marker, 1)[1], True
    for folder in ("/site-packages/", "/dist-packages/"):
        if folder in normalised:
            return normalised.rsplit(folder, 1)[1], False
    if "/lib/python" in normalised:
        # The standard library: lib/python3.13/asyncio/tasks.py -> asyncio/tasks.py
        tail = normalised.rsplit("/lib/python", 1)[1]
        return tail.split("/", 1)[1] if "/" in tail else tail, False
    return normalised.rsplit("/", 1)[-1], False


def _frames(tb: TracebackType | None) -> list[dict[str, Any]]:
    frames = []
    for summary in traceback.extract_tb(tb)[-MAX_FRAMES:]:
        filename, in_app = _relative(summary.filename)
        frame: dict[str, Any] = {
            "platform": "python",
            "filename": filename,
            "abs_path": filename,
            "module": filename.removesuffix(".py").replace("/", "."),
            "function": summary.name,
            "lineno": summary.lineno,
            "in_app": in_app,
        }
        if in_app and summary.lineno:
            line = linecache.getline(summary.filename, summary.lineno).strip()
            if line:
                frame["context_line"] = line
        frames.append(frame)
    return frames


def _chain(exc: BaseException) -> list[BaseException]:
    """The exception and what caused it, newest first; a group stands for its first error."""
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain and len(chain) < MAX_CHAIN:
        if isinstance(current, BaseExceptionGroup) and current.exceptions:
            current = current.exceptions[0]
            continue
        chain.append(current)
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return chain


def exception_list(exc: BaseException, *, handled: bool) -> list[dict[str, Any]]:
    return [
        {
            "type": type(error).__name__,
            "value": scrub(str(error)),
            "module": type(error).__module__,
            "mechanism": {"handled": handled, "synthetic": False, "type": "generic"},
            "stacktrace": {"type": "raw", "frames": _frames(error.__traceback__)},
        }
        for error in _chain(exc)
    ]


def fingerprint(exc: BaseException, where: str) -> str:
    """What makes two reports the same problem: the type and the deepest frame of ours."""
    first = _chain(exc)[0]
    ours = [f for f in _frames(first.__traceback__) if f["in_app"]]
    place = f"{ours[-1]['filename']}:{ours[-1]['function']}" if ours else ""
    return f"{type(first).__name__}|{place}|{where}"


def message_list(name: str, detail: str | None) -> list[dict[str, Any]]:
    """An error the app logged without an exception, such as a reply in the wrong shape."""
    return [
        {
            "type": name,
            "value": scrub(detail or name),
            "mechanism": {"handled": True, "synthetic": True, "type": "generic"},
        }
    ]
