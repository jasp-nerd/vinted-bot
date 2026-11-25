"""One running copy per database, and how other commands find it.

`vinted-bot run` holds an operating-system lock on a file next to the database for as long
as it runs, and writes `vinted-bot.run.json` beside it: its process id, port and version.
A second `run` finds the lock taken and says where the first one is, instead of checking
the same searches twice. The lock goes with the process, so a crash or a power cut never
leaves a stale "already running" behind; the run file alone proves nothing and is only
read while the lock is held.

The same folder holds `vinted-bot.stopped` while someone has stopped the app on purpose
(Settings, Stop vinted-bot, or `vinted-bot stop`). A running app notices it and shuts
down cleanly; a background service starting the app at login sees it and exits at once,
so "stopped" stays stopped until the person opens vinted-bot again.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO, Any

from vinted_bot import __version__
from vinted_bot.config import Settings
from vinted_bot.log import get_logger

log = get_logger(__name__)

_LOCK = "vinted-bot.lock"
_RUN = "vinted-bot.run.json"
_STOPPED = "vinted-bot.stopped"
# What the installers write the app's output to, in the same folder.
LOG = "vinted-bot.log"


def folder(settings: Settings) -> Path:
    """Where the database lives; the lock, run file and log sit next to it."""
    return settings.db_path.expanduser().resolve().parent


@dataclass(frozen=True, slots=True)
class Running:
    """A copy that is running now, as its run file describes it."""

    pid: int
    port: int
    version: str
    started_at: int

    @property
    def url(self) -> str:
        """The address to show and open in a browser."""
        return f"http://localhost:{self.port}"

    @property
    def probe_url(self) -> str:
        """The address to check it answers at. Not localhost: Windows tries IPv6 first,
        and a refused ::1 takes about two seconds there, longer than a check waits."""
        return f"http://127.0.0.1:{self.port}"


class AlreadyRunningError(Exception):
    def __init__(self, running: Running | None) -> None:
        super().__init__("vinted-bot is already running")
        self.running = running


# --- The lock --------------------------------------------------------------------------


# What a lock already held by another process raises. Anything else (ENOLCK, ENOTSUP on
# some network shares and container mounts) means the folder can't be locked at all.
_HELD = {errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES, getattr(errno, "EDEADLOCK", errno.EDEADLK)}


def _try_lock(handle: IO[str]) -> bool | None:
    """Take the lock without waiting. False when another process holds it, None when this
    folder can't be locked (some NAS shares), so nothing can tell either way."""
    try:
        if sys.platform == "win32":
            import msvcrt  # noqa: PLC0415 - Windows only

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl  # noqa: PLC0415 - not on Windows

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        return False if exc.errno in _HELD else None
    return True


def _unlock(handle: IO[str]) -> None:
    with contextlib.suppress(OSError):
        if sys.platform == "win32":
            import msvcrt  # noqa: PLC0415

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl  # noqa: PLC0415

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _open_lock(where: Path) -> IO[str]:
    where.mkdir(parents=True, exist_ok=True)
    # Append mode never truncates, and Windows needs a byte there to lock.
    handle = (where / _LOCK).open("a+", encoding="utf-8")
    if handle.tell() == 0:
        handle.write("\n")
        handle.flush()
    return handle


class Instance:
    """Held by `run` for as long as it runs. Use as a context manager."""

    def __init__(self, settings: Settings) -> None:
        self._folder = folder(settings)
        self._port = settings.web_port
        self._handle: IO[str] | None = None

    def __enter__(self) -> Instance:
        handle = _open_lock(self._folder)
        taken = _try_lock(handle)
        if taken is False:
            handle.close()
            raise AlreadyRunningError(_read_run_file(self._folder))
        if taken is None:
            # Run anyway, unguarded: refusing to start over a filesystem quirk is worse.
            log.warning("instance.cannot_lock", folder=str(self._folder))
        self._handle = handle
        running = Running(
            pid=os.getpid(), port=self._port, version=__version__, started_at=int(time.time())
        )
        (self._folder / _RUN).write_text(json.dumps(asdict(running)), encoding="utf-8")
        return self

    def __exit__(self, *_: object) -> None:
        with contextlib.suppress(OSError):
            (self._folder / _RUN).unlink()
        if self._handle is not None:
            _unlock(self._handle)
            self._handle.close()
            self._handle = None


def _read_run_file(where: Path) -> Running | None:
    try:
        data: Any = json.loads((where / _RUN).read_text(encoding="utf-8"))
        return Running(
            pid=int(data["pid"]),
            port=int(data["port"]),
            version=str(data["version"]),
            started_at=int(data["started_at"]),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def running(settings: Settings) -> Running | None:
    """The copy running on this database right now, or None.

    "Running" means the lock is held. When it is held but the run file can't be read (it
    is written a moment after the lock is taken), the configured port stands in.
    """
    where = folder(settings)
    if not (where / _LOCK).exists():
        return None
    handle = _open_lock(where)
    try:
        taken = _try_lock(handle)
        if taken:
            _unlock(handle)
        if taken is not False:
            return None
    finally:
        handle.close()
    return _read_run_file(where) or Running(pid=0, port=settings.web_port, version="", started_at=0)


# --- Stopped on purpose ----------------------------------------------------------------


def mark_stopped(settings: Settings) -> None:
    where = folder(settings)
    where.mkdir(parents=True, exist_ok=True)
    (where / _STOPPED).write_text(str(int(time.time())), encoding="utf-8")


def clear_stopped(settings: Settings) -> None:
    with contextlib.suppress(OSError):
        (folder(settings) / _STOPPED).unlink()


def is_stopped(settings: Settings) -> bool:
    return (folder(settings) / _STOPPED).exists()


def log_file(settings: Settings) -> Path:
    return folder(settings) / LOG
