"""Installing a newer release from the dashboard, and restarting into it.

updates.py notices that a release exists; this module installs it, but only where that is
safe and where the job can be finished:

* The copy was installed with `uv tool` or pipx, so one fixed command upgrades it in
  place from PyPI: the same command a person would type, from the same place the first
  install came from. The release's version, read from GitHub, only decides whether to
  run that command and what to call the result; it never becomes part of the command.
  A Docker container is replaced, never patched (whatever it changed inside itself is
  gone at its next recreate), and a source checkout belongs to whoever checked it out,
  so those two only get told the command to run.
* Something starts the app again when it exits: the LaunchAgent, systemd unit or Windows
  launcher written by the installers, which say so in VINTED_SNIPER_SUPERVISED. Then the
  app exits with RESTART_EXIT_CODE after the upgrade and comes back as the new version.
  Without one the upgrade still runs and the page says how to restart.

Windows is the exception to "upgrade in place": a running program's files are locked
there, so the app cannot replace them. It exits instead, and the installer's launcher
runs the upgrade while nothing is running, then starts it again.

Before every such exit a note goes into app_state. The next start reads it to say whether
the new version arrived, and for an automatic update tells the status destinations.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import shutil
import sys
import time
import tomllib
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from vinted_sniper import __version__
from vinted_sniper.config import Settings, in_container
from vinted_sniper.db.repo import Repo
from vinted_sniper.engine.updates import is_newer, release_notes_url
from vinted_sniper.log import get_logger

log = get_logger(__name__)

PACKAGE = "vinted-sniper"

# EX_TEMPFAIL from sysexits.h: "try again". The installers' services start the app again
# after any exit, and the Windows launcher reads this code as "upgrade, then start again".
RESTART_EXIT_CODE = 75
# How someone restarts a copy nothing restarts for them.
RESTART_COMMAND = f"{PACKAGE} run"

# uv and pipx finish in seconds; this bounds a download that hangs.
COMMAND_TIMEOUT_S = 300.0
# Long enough for an open dashboard to read "restarting" before the server goes away.
RESTART_GRACE_S = 1.5

# Automatic updates happen in this hour of the app's own time zone, when the fewest new
# listings appear and a minute without alerts costs the least.
QUIET_HOUR = 4
AUTO_CHECK_EVERY_S = 600.0

_PENDING_KEY = "update_pending"
_RESULT_KEY = "update_last_result"
_AUTO_TRIED_KEY = "update_auto_tried"

# Lines of upgrade output kept for the dashboard.
_OUTPUT_LINES = 60


class InstallKind(StrEnum):
    UV_TOOL = "uv-tool"
    PIPX = "pipx"
    DOCKER = "docker"
    SOURCE = "source"
    UVX = "uvx"
    OTHER = "other"


# What to type to update each kind by hand.
_MANUAL = {
    InstallKind.UV_TOOL: f"uv tool upgrade {PACKAGE}",
    InstallKind.PIPX: f"pipx upgrade {PACKAGE}",
    InstallKind.DOCKER: "docker compose pull && docker compose up -d",
    InstallKind.SOURCE: "git pull && uv sync",
    InstallKind.UVX: f"uvx {PACKAGE}@latest run",
    InstallKind.OTHER: f"pip install --upgrade {PACKAGE}",
}


# What to do around that command.
_MANUAL_HINT = {
    InstallKind.UV_TOOL: "Close vinted-sniper, run this, then start it again:",
    InstallKind.PIPX: "Run this, then restart vinted-sniper:",
    InstallKind.DOCKER: "In the folder with your docker-compose.yml, run:",
    InstallKind.SOURCE: "In your copy of the code, run this, then restart vinted-sniper:",
    InstallKind.UVX: "Stop vinted-sniper and start it again with:",
    InstallKind.OTHER: "Run this, then restart vinted-sniper:",
}


@dataclass(frozen=True, slots=True)
class Install:
    """How this copy was installed, and what that allows."""

    kind: InstallKind
    # What starts the app again after it exits, from VINTED_SNIPER_SUPERVISED.
    supervisor: str | None
    # The uv or pipx that upgrades it, when one was found.
    tool: Path | None = None
    # The uv tool environment and the folder its command lives in, so the upgrade lands
    # on this copy even if uv's own defaults point somewhere else.
    tool_env: Mapping[str, str] = field(default_factory=dict)
    windows: bool = False
    # The environment's interpreter, which reads what version is on disk after an upgrade.
    python: Path = field(default_factory=lambda: Path(sys.executable))

    @property
    def upgrades_from_launcher(self) -> bool:
        """Windows: the launcher upgrades while the app is stopped (see the module doc)."""
        return self.supervisor == "windows-launcher" and self.kind is InstallKind.UV_TOOL

    @property
    def can_upgrade(self) -> bool:
        """Whether the dashboard can install a release for this copy."""
        if self.upgrades_from_launcher:
            return True
        if self.kind not in {InstallKind.UV_TOOL, InstallKind.PIPX} or self.tool is None:
            return False
        # Unsupervised on Windows: its own files are locked, and nothing would upgrade them.
        return not self.windows

    @property
    def restarts_itself(self) -> bool:
        return self.supervisor is not None

    @property
    def can_update_automatically(self) -> bool:
        """Unattended means installed and running again with nobody there to restart it."""
        return self.can_upgrade and self.restarts_itself

    @property
    def manual_command(self) -> str:
        return _MANUAL[self.kind]

    @property
    def manual_hint(self) -> str:
        return _MANUAL_HINT[self.kind]

    def upgrade_command(self) -> list[str]:
        if self.tool is None:
            raise RuntimeError("no uv or pipx was found to run the upgrade with")
        if self.kind is InstallKind.PIPX:
            return [str(self.tool), "upgrade", PACKAGE]
        return [str(self.tool), "tool", "upgrade", PACKAGE, "--no-progress"]


# Package managers' folders, for a uv or pipx that came from Homebrew.
SYSTEM_BINS = (Path("/opt/homebrew/bin"), Path("/usr/local/bin"))


def _locate(
    name: str, first: list[Path], environ: Mapping[str, str], system_bins: tuple[Path, ...]
) -> Path | None:
    """The first of `first` that exists, then `name` on PATH, then in `system_bins`.

    The installers' services start with a bare PATH (launchd's is /usr/bin:/bin...), which
    is why the folders the installers use come before PATH, and Homebrew's after it.
    """
    for candidate in first:
        if candidate.is_file():
            return candidate
    if found := shutil.which(name, path=environ.get("PATH")):
        return Path(found)
    for folder in system_bins:
        if (folder / name).is_file():
            return folder / name
    return None


def _find_uv(
    environ: Mapping[str, str], home: Path, windows: bool, system_bins: tuple[Path, ...]
) -> Path | None:
    exe = "uv.exe" if windows else "uv"
    first = [Path(environ["UV"])] if environ.get("UV") else []
    first += [
        Path(environ[var]) / exe for var in ("UV_INSTALL_DIR", "XDG_BIN_HOME") if environ.get(var)
    ]
    # Where uv's own installer, and so both of ours, puts it; then where cargo does.
    first += [home / ".local" / "bin" / exe, home / ".cargo" / "bin" / exe]
    return _locate(exe, first, environ, system_bins)


def _find_pipx(
    environ: Mapping[str, str], home: Path, windows: bool, system_bins: tuple[Path, ...]
) -> Path | None:
    exe = "pipx.exe" if windows else "pipx"
    return _locate(exe, [home / ".local" / "bin" / exe], environ, system_bins)


def _receipt_bin_dir(prefix: Path) -> Path | None:
    """The folder uv put the `vinted-sniper` command in, from the tool's receipt."""
    try:
        receipt = tomllib.loads((prefix / "uv-receipt.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    for entry in receipt.get("tool", {}).get("entrypoints", []):
        path = entry.get("install-path") if isinstance(entry, dict) else None
        if isinstance(path, str) and entry.get("name") == PACKAGE:
            return Path(path).parent
    return None


def _kind(prefix: Path, package_dir: Path, container: bool) -> InstallKind:
    if container:
        return InstallKind.DOCKER
    # Both tools leave a file in the root of the environment they made.
    if (prefix / "uv-receipt.toml").is_file():
        return InstallKind.UV_TOOL
    if (prefix / "pipx_metadata.json").is_file():
        return InstallKind.PIPX
    # src/vinted_sniper inside a git checkout: an editable install or `uv run`.
    root = package_dir.parent.parent
    if (root / ".git").exists() and (root / "pyproject.toml").is_file():
        return InstallKind.SOURCE
    # uvx runs from a throwaway environment in uv's cache.
    if "archive-v0" in prefix.parts:
        return InstallKind.UVX
    return InstallKind.OTHER


def detect(
    settings: Settings,
    *,
    prefix: Path | None = None,
    package_dir: Path | None = None,
    container: bool | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    windows: bool | None = None,
    system_bins: tuple[Path, ...] | None = None,
) -> Install:
    """Work out how this copy was installed. The keywords exist for tests."""
    prefix = prefix or Path(sys.prefix)
    environ = os.environ if environ is None else environ
    home = home or Path.home()
    windows = sys.platform == "win32" if windows is None else windows
    if system_bins is None:
        system_bins = () if windows else SYSTEM_BINS
    kind = _kind(
        prefix,
        package_dir or Path(__file__).resolve().parents[1],
        in_container() if container is None else container,
    )
    tool: Path | None = None
    tool_env: dict[str, str] = {}
    if kind is InstallKind.UV_TOOL:
        tool = _find_uv(environ, home, windows, system_bins)
        tool_env["UV_TOOL_DIR"] = str(prefix.parent)
        if (bin_dir := _receipt_bin_dir(prefix)) is not None:
            tool_env["UV_TOOL_BIN_DIR"] = str(bin_dir)
    elif kind is InstallKind.PIPX:
        tool = _find_pipx(environ, home, windows, system_bins)
        # venvs/vinted-sniper inside PIPX_HOME.
        tool_env["PIPX_HOME"] = str(prefix.parent.parent)
    return Install(
        kind=kind,
        supervisor=settings.supervised,
        tool=tool,
        tool_env=tool_env,
        windows=windows,
    )


# --- Running an update -----------------------------------------------------------------


class Phase(StrEnum):
    IDLE = "idle"
    UPGRADING = "upgrading"
    # Installed; the process is about to exit so its supervisor starts the new version.
    RESTARTING = "restarting"
    # Installed, but nothing will restart it: the person has to.
    INSTALLED = "installed"
    FAILED = "failed"


class UpdateRefusedError(Exception):
    """Why an update cannot start, in words for the person who asked."""


@dataclass(frozen=True, slots=True)
class Outcome:
    ok: bool
    message: str
    at: int

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "message": self.message, "at": self.at}


async def last_outcome(repo: Repo) -> Outcome | None:
    raw = await repo.get_state_value(_RESULT_KEY)
    try:
        saved = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None
    if not isinstance(saved, dict):
        return None
    return Outcome(
        ok=bool(saved.get("ok")), message=str(saved.get("message", "")), at=int(saved.get("at", 0))
    )


async def _record(repo: Repo, ok: bool, message: str) -> None:
    outcome = Outcome(ok=ok, message=message, at=int(time.time()))
    await repo.set_state_value(_RESULT_KEY, json.dumps(outcome.as_dict()))
    log.info("update.finished", ok=ok, message=message)


class Updater:
    """One update at a time, its progress for the dashboard, and the restart after it.

    Shared by the dashboard's button and the automatic updates, so the two can never run
    an upgrade at the same time.
    """

    def __init__(
        self,
        settings: Settings,
        repo: Repo,
        stop: asyncio.Event,
        install: Install | None = None,
        *,
        command_timeout_s: float = COMMAND_TIMEOUT_S,
        restart_grace_s: float = RESTART_GRACE_S,
    ) -> None:
        self._settings = settings
        self._repo = repo
        self._stop = stop
        self.install = install or detect(settings)
        self._command_timeout_s = command_timeout_s
        self._restart_grace_s = restart_grace_s
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._phase = Phase.IDLE
        self._message = ""
        self._target: str | None = None
        self._output: deque[str] = deque(maxlen=_OUTPUT_LINES)
        # Tells an open dashboard that the process it polls is a new one.
        self.boot = secrets.token_hex(6)
        self.restart_requested = False

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def target(self) -> str | None:
        return self._target

    def status(self) -> dict[str, Any]:
        return {
            "phase": self._phase.value,
            "target": self._target,
            "message": self._message,
            "output": list(self._output),
            "running": __version__,
            "boot": self.boot,
        }

    async def start(self, *, automatic: bool = False) -> None:
        """Begin installing the latest release in the background.

        Raises UpdateRefusedError when this copy cannot update itself, an update is already
        under way, or there is nothing newer to install.
        """
        if not self.install.can_upgrade:
            raise UpdateRefusedError(
                f"This copy can't update itself. To update it, run: {self.install.manual_command}"
            )
        prefs = await self._repo.app_settings(default_timezone=self._settings.timezone)
        # From here to create_task nothing awaits, so two clicks cannot both get through.
        if self._phase in {Phase.UPGRADING, Phase.RESTARTING, Phase.INSTALLED}:
            raise UpdateRefusedError("An update is already under way.")
        # latest_version only ever comes from GitHub's latest release, so this is also the
        # check that the version is a real release.
        target = prefs.latest_version
        if target is None or not is_newer(target):
            raise UpdateRefusedError("There's no newer release to install.")
        self._phase, self._target = Phase.UPGRADING, target
        self._message = f"Installing version {target}…"
        self._output.clear()
        log.info("update.started", current=__version__, target=target, automatic=automatic)
        self._task = asyncio.create_task(self._run(target, automatic), name="update")

    async def settle(self) -> None:
        """Wait for an update in progress, so shutting down never cuts an install short."""
        if self._task is not None and not self._task.done():
            await asyncio.wait({self._task})

    async def _run(self, target: str, automatic: bool) -> None:
        try:
            async with self._lock:
                await self._install(target, automatic)
        except Exception as exc:
            # Whatever broke, the page must not say "installing" forever.
            log.exception("update.crashed", error=str(exc))
            self._phase = Phase.FAILED
            self._message = (
                f"The update stopped unexpectedly ({type(exc).__name__}). vinted-sniper keeps "
                f"running version {__version__}."
            )

    async def _install(self, target: str, automatic: bool) -> None:
        if self.install.upgrades_from_launcher:
            await self._restart(
                target,
                automatic,
                f"Closing so version {target} can install. This page reloads when "
                "vinted-sniper is back, in about a minute.",
            )
            return
        try:
            installed = await self._upgrade()
        except UpdateRefusedError as exc:
            self._phase, self._message = Phase.FAILED, str(exc)
            await _record(self._repo, False, self._message)
            return
        if self.install.restarts_itself:
            # The next start records how it went, from the note this leaves.
            await self._restart(
                installed, automatic, f"Updated to version {installed}, restarting…"
            )
        else:
            await _record(
                self._repo, True, f"Installed version {installed}; it starts at the next restart."
            )
            self._phase = Phase.INSTALLED
            self._message = (
                f"Version {installed} is installed. To start using it, restart vinted-sniper: "
                'stop it (Ctrl+C in its window, or pkill -f "vinted-sniper run" if it runs '
                f"in the background), then start it with: {RESTART_COMMAND}"
            )

    async def _upgrade(self) -> str:
        """Run uv or pipx; the newly installed version, or UpdateRefusedError saying why not."""
        still = f"vinted-sniper keeps running version {__version__}."
        env = {**os.environ, **self.install.tool_env, "NO_COLOR": "1"}
        try:
            code = await self._command(self.install.upgrade_command(), env)
        except TimeoutError:
            raise UpdateRefusedError(
                f"The update took longer than {int(self._command_timeout_s / 60)} minutes and "
                f"was stopped. {still}"
            ) from None
        except (OSError, RuntimeError) as exc:
            raise UpdateRefusedError(f"The update couldn't start ({exc}). {still}") from None
        if code != 0:
            tool = "pipx" if self.install.kind is InstallKind.PIPX else "uv"
            raise UpdateRefusedError(
                f"The update didn't install: {tool} stopped with an error (code {code}). "
                f"What it said is below. {still}"
            )
        installed = await self._installed_version()
        if installed is None or not is_newer(installed):
            raise UpdateRefusedError(
                "Nothing newer was installed. A new release can take a few minutes to reach "
                f"the package index; try again later. {still}"
            )
        return installed

    async def _command(self, argv: list[str], env: Mapping[str, str]) -> int:
        """Run a command, collecting what it prints line by line for the dashboard."""
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=dict(env),
        )
        stream = process.stdout
        assert stream is not None  # asked for a pipe above

        async def collect() -> int:
            async for line in stream:
                if text := line.decode(errors="replace").rstrip():
                    self._output.append(text)
            return await process.wait()

        try:
            return await asyncio.wait_for(collect(), timeout=self._command_timeout_s)
        except TimeoutError:
            process.kill()
            # Reads the pipe to its end, so it is closed and not left to the garbage
            # collector; bounded, because a child of the command could hold it open.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(process.communicate(), timeout=5)
            raise

    async def _installed_version(self) -> str | None:
        """The version now on disk, asked of a fresh interpreter: this one has the old
        version's metadata loaded."""
        process = await asyncio.create_subprocess_exec(
            self.install.python,
            "-I",
            "-c",
            f"from importlib.metadata import version; print(version({PACKAGE!r}))",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await asyncio.wait_for(process.communicate(), timeout=30)
        except TimeoutError:
            process.kill()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(process.communicate(), timeout=5)
            return None
        version = out.decode(errors="replace").strip()
        return version if process.returncode == 0 and version else None

    async def _restart(self, version: str, automatic: bool, message: str) -> None:
        """Leave a note for the next start, then shut down for the supervisor to restart."""
        note = {"from": __version__, "to": version, "automatic": automatic, "at": int(time.time())}
        await self._repo.set_state_value(_PENDING_KEY, json.dumps(note))
        self._phase, self._message = Phase.RESTARTING, message
        log.info("update.restarting", current=__version__, target=version)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=self._restart_grace_s)
        self.restart_requested = True
        self._stop.set()

    # --- Automatic updates ---------------------------------------------------------

    async def run_automatically(self) -> None:
        """Every few minutes, install a waiting release if the person asked for that.

        The first look comes one interval after starting, not at once: a copy that just
        started has had no chance to send what it found, and the Windows launcher reads an
        exit in its first seconds as a failed start rather than an update.
        """
        while True:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=AUTO_CHECK_EVERY_S)
            if self._stop.is_set():
                return
            try:
                await self.maybe_update(datetime.now().astimezone())
            except UpdateRefusedError as exc:
                log.info("update.auto_skipped", reason=str(exc))
            except Exception as exc:
                # A locked database or a broken note must not end the loop: tomorrow's
                # window is another chance.
                log.exception("update.auto_failed", error=str(exc))

    async def maybe_update(self, now: datetime) -> bool:
        """Start an automatic update if everything says yes. Whether one started.

        Yes means: switched on, a newer release known, this copy able to install it and
        restart, the quiet hour on the app's clock, no alert on its way out, and no
        attempt at this release yet today (a failure waits for tomorrow, not ten minutes).
        """
        if not self.install.can_update_automatically:
            return False
        prefs = await self._repo.app_settings(default_timezone=self._settings.timezone)
        if not prefs.auto_update or not is_newer(prefs.latest_version):
            return False
        local = now.astimezone(ZoneInfo(prefs.timezone))
        if local.hour != QUIET_HOUR:
            return False
        if due := await self._repo.notifications_due(int(now.timestamp())):
            log.info("update.auto_waiting", notifications_due=due)
            return False
        attempt = f"{prefs.latest_version} {local.date().isoformat()}"
        if await self._repo.get_state_value(_AUTO_TRIED_KEY) == attempt:
            return False
        await self._repo.set_state_value(_AUTO_TRIED_KEY, attempt)
        await self.start(automatic=True)
        return True


async def finish_pending(repo: Repo, announce: Callable[[str], Awaitable[None]]) -> None:
    """At startup: say how the update that restarted the app went.

    The note was left just before the previous process exited. If this process is newer
    than the one that left it, the update arrived.
    """
    raw = await repo.get_state_value(_PENDING_KEY)
    if not raw:
        return
    await repo.set_state_value(_PENDING_KEY, "")
    try:
        note = json.loads(raw)
        before, wanted, automatic = str(note["from"]), str(note["to"]), bool(note["automatic"])
    except (json.JSONDecodeError, KeyError, TypeError):
        log.warning("update.bad_note")
        return
    if not is_newer(__version__, before):
        await _record(
            repo,
            False,
            f"Version {wanted} didn't install, so this is still version {__version__}. "
            "The log file says why.",
        )
        return
    await _record(repo, True, f"Updated from {before} to {__version__}.")
    if automatic:
        await announce(
            f"vinted-sniper updated itself to version {__version__}. "
            f"What's new: {release_notes_url(__version__)}"
        )
