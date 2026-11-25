"""Opening, starting and stopping vinted-bot: what the app icon and `vinted-bot` do.

The installers leave vinted-bot to the computer's own service manager (a LaunchAgent on
macOS, a systemd user service on Linux, a hidden launcher in the Startup folder on
Windows), which starts it at login and again after an update. Starting it goes through
that same manager, so there is never a second copy and the service keeps knowing about
it. Without one (installed with pipx or uv by hand) it starts in the background on its
own, writing to the same log file the installers use.

Stopping never goes through the service manager: it leaves a note (instance.py) that the
running app notices within a second, so it shuts down cleanly whatever started it, and a
service starting it at the next login sees the note and leaves it stopped.
"""

from __future__ import annotations

import contextlib
import os
import plistlib
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path

import httpx

from vinted_bot import instance, shortcuts
from vinted_bot.config import Settings, in_container

LAUNCHD_LABEL = "io.github.jasp-nerd.vinted-bot"
SYSTEMD_UNIT = "vinted-bot.service"
WINDOWS_LAUNCHER = "start-vinted-bot.ps1"

# Starting takes a few seconds; a slow disk or a first start with migrations, longer.
START_TIMEOUT_S = 60.0
STOP_TIMEOUT_S = 30.0
_POLL_S = 0.5


class Service(StrEnum):
    LAUNCHD = "launchd"
    SYSTEMD = "systemd"
    WINDOWS = "windows-launcher"


class ControlError(Exception):
    """Something the person needs to be told, in plain words."""


def _launchd_plist(home: Path) -> Path:
    """Where the LaunchAgent lives while it starts vinted-bot at login."""
    return home / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def _launchd_resting(settings: Settings) -> Path:
    """Where it waits while starting at login is switched off: launchd only loads
    ~/Library/LaunchAgents at login, and from here it can still be loaded by hand."""
    return instance.folder(settings) / f"{LAUNCHD_LABEL}.plist"


def _launchd_current(settings: Settings, home: Path) -> Path:
    at_login = _launchd_plist(home)
    return at_login if at_login.is_file() else _launchd_resting(settings)


def _systemd_unit(home: Path, environ: Mapping[str, str]) -> Path:
    config = (
        Path(environ["XDG_CONFIG_HOME"]) if environ.get("XDG_CONFIG_HOME") else home / ".config"
    )
    return config / "systemd" / "user" / SYSTEMD_UNIT


def installed_service(
    settings: Settings,
    *,
    platform: str | None = None,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Service | None:
    """The start-at-login entry the installer made for this copy, if there is one.

    Only an entry that runs this same database counts: a copy of vinted-bot tried out
    with another VINTED_BOT_DB_PATH must not start the installed one instead.
    """
    platform = platform or sys.platform
    home = home or Path.home()
    environ = os.environ if environ is None else environ
    ours = settings.db_path.expanduser().resolve()
    if platform == "darwin" and _same_db(_launchd_db(_launchd_current(settings, home)), ours):
        return Service.LAUNCHD
    if platform.startswith("linux") and _same_db(_systemd_db(_systemd_unit(home, environ)), ours):
        return Service.SYSTEMD
    if platform == "win32" and (instance.folder(settings) / WINDOWS_LAUNCHER).is_file():
        return Service.WINDOWS
    return None


def _same_db(theirs: str | None, ours: Path) -> bool:
    return theirs is not None and Path(theirs).expanduser().resolve() == ours


def _launchd_db(plist: Path) -> str | None:
    try:
        with plist.open("rb") as handle:
            data = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    value = data.get("EnvironmentVariables", {}).get("VINTED_BOT_DB_PATH")
    return value if isinstance(value, str) else None


_UNIT_DB = re.compile(r'^Environment="?VINTED_BOT_DB_PATH=([^"\n]+)"?\s*$', re.MULTILINE)


def _systemd_db(unit: Path) -> str | None:
    try:
        match = _UNIT_DB.search(unit.read_text(encoding="utf-8"))
    except OSError:
        return None
    return match.group(1) if match else None


def can_open_browser(
    environ: Mapping[str, str] | None = None, platform: str = sys.platform
) -> bool:
    """Whether a browser can open here: not over SSH, in a container or a desktop-less Linux."""
    environ = os.environ if environ is None else environ
    if environ.get("SSH_CONNECTION") or environ.get("SSH_TTY") or in_container():
        return False
    return not (
        platform.startswith("linux")
        and not environ.get("DISPLAY")
        and not environ.get("WAYLAND_DISPLAY")
    )


def answers(url: str) -> str | None:
    """Who answers at `url`: "vinted-bot", "other" for another program, or None."""
    try:
        response = httpx.get(f"{url}/healthz", timeout=2.0)
    except httpx.HTTPError:
        return None
    try:
        body = response.json()
    except ValueError:
        return "other"
    return "vinted-bot" if isinstance(body, dict) and "alive" in body else "other"


# --- Starting --------------------------------------------------------------------------

# A hidden console of its own (CREATE_NO_WINDOW) in its own process group, so closing the
# window it was started from doesn't take it along. Not DETACHED_PROCESS: PowerShell, which
# runs the Windows launcher, needs a console, and quietly does nothing without one.
_HIDDEN = 0x08000000 | 0x00000200


def _spawn(
    command: list[str], *, log: Path | None = None, env: dict[str, str] | None = None
) -> None:
    """Start `command` in the background, outliving this process."""
    output = log.open("ab") if log else subprocess.DEVNULL
    try:
        if sys.platform == "win32":
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=_HIDDEN,
                close_fds=True,
            )
        else:
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
                close_fds=True,
            )
    finally:
        if log and not isinstance(output, int):
            output.close()


def _run(command: list[str]) -> bool:
    try:
        result = subprocess.run(command, capture_output=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def start(settings: Settings) -> instance.Running:
    """Start vinted-bot if it isn't running, and wait until its dashboard answers."""
    if current := instance.running(settings):
        return current
    if _updating(settings):
        # The Windows launcher is installing an update and starts the app itself after;
        # a second launcher now would run the app on half-written files.
        return wait_until_running(settings, timeout=UPDATE_TIMEOUT_S)
    service = installed_service(settings)
    port = _service_port(settings, service)
    if answers(f"http://127.0.0.1:{port}") == "other":
        raise ControlError(
            f"Another program is using port {port}, so vinted-bot can't start there. "
            "Close that program, or give vinted-bot another port with VINTED_BOT_WEB_PORT."
        )
    instance.clear_stopped(settings)
    if not _start_service(settings, service):
        # No service, or it refused (macOS with "Allow in the background" switched off for
        # vinted-bot, systemd without a user session): run it in the background directly.
        _start_alone(settings, port)
    return wait_until_running(settings)


def _start_service(settings: Settings, service: Service | None) -> bool:
    match service:
        case Service.LAUNCHD:
            domain = f"gui/{os.getuid()}"  # type: ignore[attr-defined,unused-ignore]
            # Loaded but not running (stopped, or exited): kickstart. Not loaded (removed
            # with launchctl bootout): load it, and RunAtLoad starts it.
            return _run(["launchctl", "kickstart", f"{domain}/{LAUNCHD_LABEL}"]) or _run(
                ["launchctl", "bootstrap", domain, str(_launchd_current(settings, Path.home()))]
            )
        case Service.SYSTEMD:
            return _run(["systemctl", "--user", "start", SYSTEMD_UNIT])
        case Service.WINDOWS:
            launcher = instance.folder(settings) / WINDOWS_LAUNCHER
            _spawn(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "ByPass",
                    "-WindowStyle",
                    "Hidden",
                    "-File",
                    str(launcher),
                ]
            )
            return True
        case None:
            return False


def _start_alone(settings: Settings, port: int) -> None:
    env = {
        **os.environ,
        "VINTED_BOT_DB_PATH": str(settings.db_path.expanduser().resolve()),
        "VINTED_BOT_WEB_PORT": str(port),
    }
    _spawn([sys.executable, "-m", "vinted_bot", "run"], log=instance.log_file(settings), env=env)


# The Windows launcher leaves this next to the database while it installs an update.
_UPDATING = "vinted-bot.updating"
UPDATE_TIMEOUT_S = 240.0


def _updating(settings: Settings) -> bool:
    marker = instance.folder(settings) / _UPDATING
    try:
        return time.time() - marker.stat().st_mtime < UPDATE_TIMEOUT_S * 2
    except OSError:
        return False


def _service_port(settings: Settings, service: Service | None) -> int:
    """The port the service runs vinted-bot on, which the icon and a terminal don't know
    when the installer was given another one (VINTED_BOT_WEB_PORT=8001)."""
    if "web_port" in settings.model_fields_set:
        return settings.web_port
    found: str | None = None
    with contextlib.suppress(OSError, ValueError, plistlib.InvalidFileException):
        match service:
            case Service.LAUNCHD:
                with _launchd_current(settings, Path.home()).open("rb") as handle:
                    env = plistlib.load(handle).get("EnvironmentVariables", {})
                found = env.get("VINTED_BOT_WEB_PORT")
            case Service.SYSTEMD:
                text = _systemd_unit(Path.home(), os.environ).read_text(encoding="utf-8")
                match = re.search(r"VINTED_BOT_WEB_PORT=(\d+)", text)
                found = match.group(1) if match else None
            case Service.WINDOWS:
                text = (instance.folder(settings) / WINDOWS_LAUNCHER).read_text(
                    encoding="utf-8-sig"
                )
                match = re.search(r"VINTED_BOT_WEB_PORT = '(\d+)'", text)
                found = match.group(1) if match else None
    return int(found) if found and str(found).isdigit() else settings.web_port


def wait_until_running(settings: Settings, timeout: float = START_TIMEOUT_S) -> instance.Running:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = instance.running(settings)
        if current is not None and (not settings.web_enabled or answers(current.probe_url)):
            return current
        time.sleep(_POLL_S)
    raise ControlError(
        "vinted-bot didn't start. What it wrote is in the log: "
        f"{instance.log_file(settings)} (or run: vinted-bot logs)"
    )


# --- Stopping --------------------------------------------------------------------------


def stop(settings: Settings, timeout: float = STOP_TIMEOUT_S) -> bool:
    """Stop the running copy and keep it stopped. False when nothing was running."""
    current = instance.running(settings)
    if current is None:
        instance.mark_stopped(settings)
        return False
    instance.mark_stopped(settings)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if instance.running(settings) is None:
            return True
        time.sleep(_POLL_S)
    # It didn't notice (an older version, or stuck): ask the way a service manager would.
    if current.pid:
        with contextlib.suppress(OSError):
            os.kill(current.pid, signal.SIGTERM)
    return True


# --- Starting at login -------------------------------------------------------------------

_WINDOWS_STARTUP_MAKE = r"""
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($env:VB_LINK)
$link.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments = '-NoProfile -ExecutionPolicy ByPass -WindowStyle Hidden -File '
$link.Arguments = $arguments + '"' + $env:VB_LAUNCHER + '"'
$link.WorkingDirectory = $env:VB_DIR
$link.WindowStyle = 7
$link.Description = 'vinted-bot: alerts for new Vinted listings'
$link.Save()
"""


def _windows_startup_link(environ: Mapping[str, str] | None = None) -> Path:
    """The shortcut install.ps1 puts in the Startup folder (the same name and place)."""
    environ = os.environ if environ is None else environ
    appdata = Path(environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    return (
        appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "vinted-bot.lnk"
    )


def starts_at_login(settings: Settings, *, home: Path | None = None) -> bool | None:
    """Whether vinted-bot starts by itself when someone logs in; None where that isn't
    vinted-bot's to decide (no installer service, or a container)."""
    home = home or Path.home()
    match installed_service(settings, home=home):
        case Service.LAUNCHD:
            return _launchd_plist(home).is_file()
        case Service.SYSTEMD:
            try:
                result = subprocess.run(
                    ["systemctl", "--user", "is-enabled", SYSTEMD_UNIT],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
            except (OSError, subprocess.TimeoutExpired):
                return None
            return result.stdout.strip() == "enabled"
        case Service.WINDOWS:
            return _windows_startup_link().is_file()
        case None:
            return None


def set_starts_at_login(settings: Settings, on: bool, *, home: Path | None = None) -> None:
    """Switch starting at login on or off. Takes effect at the next login; the copy that
    runs now keeps running either way."""
    home = home or Path.home()
    match installed_service(settings, home=home):
        case Service.LAUNCHD:
            at_login, resting = _launchd_plist(home), _launchd_resting(settings)
            source, target = (resting, at_login) if on else (at_login, resting)
            if source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
        case Service.SYSTEMD:
            if not _run(["systemctl", "--user", "enable" if on else "disable", SYSTEMD_UNIT]):
                raise ControlError("systemd didn't accept the change. See: vinted-bot logs")
        case Service.WINDOWS:
            link = _windows_startup_link()
            if not on:
                link.unlink(missing_ok=True)
                return
            folder = instance.folder(settings)
            env = {
                **os.environ,
                "VB_LINK": str(link),
                "VB_LAUNCHER": str(folder / WINDOWS_LAUNCHER),
                "VB_DIR": str(folder),
            }
            link.parent.mkdir(parents=True, exist_ok=True)
            command = [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                shortcuts.encode_powershell(_WINDOWS_STARTUP_MAKE),
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                env=env,
                creationflags=0x08000000,
            )
            if result.returncode != 0:
                raise ControlError("Windows didn't accept the change.")
        case None:
            raise ControlError("This copy of vinted-bot isn't set up to start by itself.")


# --- Bringing an older installation's service up to date ---------------------------------


def upgrade_service(settings: Settings, *, home: Path | None = None) -> bool | None:
    """Rewrite a start-at-login entry written by an older installer, so a stop sticks.

    Before Stop existed the entries started vinted-bot again after any exit. A copy that
    updated itself still has that entry until the installer runs again; this fixes it in
    place. It also takes keeping the Mac awake out of the LaunchAgent, where it was fixed
    at install time, into the app, where Settings can switch it. Returns whether the old
    LaunchAgent kept the Mac awake (None when there was nothing to bring over).
    """
    home = home or Path.home()
    match installed_service(settings, home=home):
        case Service.LAUNCHD:
            return _upgrade_launchd(_launchd_current(settings, home))
        case Service.SYSTEMD:
            unit = _systemd_unit(home, os.environ)
            text = unit.read_text(encoding="utf-8")
            if "Restart=always" in text:
                unit.write_text(
                    text.replace("Restart=always", "Restart=on-failure"), encoding="utf-8"
                )
                _run(["systemctl", "--user", "daemon-reload"])
            return None
        case _:
            return None


def _upgrade_launchd(plist: Path) -> bool | None:
    with plist.open("rb") as handle:
        data = plistlib.load(handle)
    if data.get("KeepAlive") == {"SuccessfulExit": False}:
        return None
    arguments = list(data.get("ProgramArguments", []))
    kept_awake = arguments[:1] == ["/usr/bin/caffeinate"]
    if kept_awake:
        arguments = arguments[2:]
    data["ProgramArguments"] = arguments
    data["KeepAlive"] = {"SuccessfulExit": False}
    with plist.open("wb") as handle:
        plistlib.dump(data, handle)
    return kept_awake


def leave_stopped(settings: Settings) -> None:
    """Started by the service while stopped on purpose: make sure the service doesn't
    start it again this session, even with an entry that predates Stop."""
    match installed_service(settings):
        case Service.LAUNCHD:
            target = f"gui/{os.getuid()}/{LAUNCHD_LABEL}"  # type: ignore[attr-defined,unused-ignore]
            _spawn(["launchctl", "bootout", target])
        case Service.SYSTEMD:
            _spawn(["systemctl", "--user", "stop", "--no-block", SYSTEMD_UNIT])
        case _:
            pass


# --- Telling someone who clicked an icon -------------------------------------------------


def how_to_open(settings: Settings, platform: str = sys.platform) -> str:
    """How this person opens vinted-bot, in their computer's words, as the end of a
    sentence ("…, open vinted-bot from Applications…")."""
    if in_container():
        return "start the container (docker compose up -d) and open its address"
    if shortcuts.made(settings):
        if platform == "darwin":
            return (
                "open vinted-bot from Applications or Launchpad, or search for it with "
                "Spotlight (⌘ Space)"
            )
        if platform == "win32":
            return "open vinted-bot from the Start menu or your desktop"
        return "open vinted-bot from your apps menu, or type vinted-bot in a terminal"
    terminal = {"darwin": "Terminal", "win32": "PowerShell"}.get(platform, "a terminal")
    return f"type vinted-bot in {terminal}"


def how_to_start(settings: Settings, platform: str = sys.platform) -> str:
    return f"To start it again, {how_to_open(settings, platform)}."


def notify(title: str, text: str) -> None:
    """A passing notification, for the moment between clicking the icon and the page."""
    if sys.platform == "darwin" and shutil.which("osascript"):

        def q(value: str) -> str:
            return value.replace("\\", "\\\\").replace('"', '\\"')

        subprocess.run(
            ["osascript", "-e", f'display notification "{q(text)}" with title "{q(title)}"'],
            check=False,
            capture_output=True,
        )
    elif sys.platform.startswith("linux") and shutil.which("notify-send"):
        subprocess.run(["notify-send", title, text], check=False, capture_output=True)


def show_message(text: str) -> None:
    """A small dialog for the app icon, which has no terminal to print to."""
    if sys.platform == "darwin" and shutil.which("osascript"):
        quoted = text.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display dialog "{quoted}" with title "vinted-bot" buttons {{"OK"}} '
                "default button 1 with icon caution",
            ],
            check=False,
            capture_output=True,
        )
    elif sys.platform == "win32":
        import ctypes  # noqa: PLC0415

        ctypes.windll.user32.MessageBoxW(0, text, "vinted-bot", 0x10)  # type: ignore[attr-defined,unused-ignore]
    elif shutil.which("zenity"):
        subprocess.run(
            ["zenity", "--error", "--title=vinted-bot", f"--text={text}"],
            check=False,
            capture_output=True,
        )
    else:
        print(text, file=sys.stderr)
