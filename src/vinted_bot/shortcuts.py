"""The vinted-bot icon people click to get back to their dashboard.

Installed with the installers, vinted-bot runs in the background with nothing to click:
close the browser tab and the only way back was the address. So it makes an icon where
the system keeps apps, which runs `vinted-bot open --gui` (open the dashboard, starting
vinted-bot first if needed):

- macOS: ~/Applications/vinted-bot.app, found by Launchpad and Spotlight. A small bundle
  around a shell script. Made on this Mac, it carries no quarantine flag, so Gatekeeper
  never asks about it and no signing is needed.
- Windows: a Start menu shortcut and one on the desktop. They run pythonw, so no black
  window flashes up.
- Linux: an entry in the apps menu (~/.local/share/applications).

The app makes them itself the first time it runs under the installers' service, so a copy
that updated itself gets them too, and `vinted-bot shortcuts` (which the installers call)
makes them again. They are made once per layout: someone who deletes the desktop icon
doesn't find it back after every restart. `vinted-bot shortcuts --remove` takes them away,
which the installers' uninstall does.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

from vinted_bot import __version__, instance
from vinted_bot.config import Settings

# Raise when what gets made changes, so installs that already have icons get the new ones.
LAYOUT = 1
_MARKER = "vinted-bot.shortcuts"
APP_NAME = "vinted-bot"
BUNDLE_ID = "io.github.jasp-nerd.vinted-bot.open"
_LSREGISTER = Path(
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework"
    "/Support/lsregister"
)


def _asset(name: str) -> Path:
    return Path(str(resources.files("vinted_bot") / "assets" / name))


def executable() -> Path:
    """The `vinted-bot` command of this installation (next to its Python)."""
    scripts = Path(sys.executable).parent
    name = "vinted-bot.exe" if sys.platform == "win32" else "vinted-bot"
    found = scripts / name
    return found if found.exists() else Path(shutil.which("vinted-bot") or found)


# --- macOS -------------------------------------------------------------------------------


def _mac_app(home: Path) -> Path:
    return home / "Applications" / f"{APP_NAME}.app"


def _make_mac(home: Path, exe: Path, db: Path) -> list[Path]:
    app = _mac_app(home)
    shutil.rmtree(app, ignore_errors=True)
    macos = app / "Contents" / "MacOS"
    res = app / "Contents" / "Resources"
    macos.mkdir(parents=True)
    res.mkdir(parents=True)
    info = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": APP_NAME,
        "CFBundleIconFile": APP_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "LSMinimumSystemVersion": "11.0",
        # Opens the dashboard and is gone: no Dock icon bouncing for a second.
        "LSUIElement": True,
    }
    with (app / "Contents" / "Info.plist").open("wb") as handle:
        plistlib.dump(info, handle)
    script = macos / APP_NAME
    # Which database it opens, so a copy installed somewhere other than the default (a
    # VINTED_BOT_DATA_DIR) opens that one rather than starting an empty second copy.
    script.write_text(
        "#!/bin/sh\n"
        f"export VINTED_BOT_DB_PATH={shlex.quote(str(db))}\n"
        f"exec {shlex.quote(str(exe))} open --gui\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    shutil.copyfile(_asset("vinted-bot.icns"), res / f"{APP_NAME}.icns")
    # Tell Launchpad and Spotlight now rather than at their next look around.
    if _LSREGISTER.exists() and home == Path.home():
        subprocess.run([str(_LSREGISTER), "-f", str(app)], check=False, capture_output=True)
    return [app]


# --- Windows -----------------------------------------------------------------------------

# Paths travel in environment variables, so no quoting of user names with quotes in them.
_WINDOWS_MAKE = r"""
$shell = New-Object -ComObject WScript.Shell
$places = @(
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'vinted-bot.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'vinted-bot.lnk')
)
foreach ($place in $places) {
    $link = $shell.CreateShortcut($place)
    $link.TargetPath = $env:VB_TARGET
    $link.Arguments = $env:VB_ARGS
    $link.WorkingDirectory = $env:VB_DIR
    $link.IconLocation = $env:VB_ICON + ',0'
    $link.Description = 'Open vinted-bot: alerts for new Vinted listings'
    $link.Save()
    Write-Output $place
}
"""

_WINDOWS_REMOVE = r"""
foreach ($folder in @('Programs', 'Desktop')) {
    $place = Join-Path ([Environment]::GetFolderPath($folder)) 'vinted-bot.lnk'
    if (Test-Path -LiteralPath $place) {
        Remove-Item -LiteralPath $place -Force
        Write-Output $place
    }
}
"""


def _powershell(script: str, env: dict[str, str] | None = None) -> list[Path]:
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "ByPass",
            "-EncodedCommand",
            encode_powershell(script),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **(env or {})},
        creationflags=0x08000000,  # no window
    )
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or "PowerShell could not make the shortcuts")
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def _make_windows(settings: Settings, exe: Path) -> list[Path]:
    # pythonw runs the same code without a console window; the plain exe is the fallback.
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    target, arguments = (
        (pythonw, "-m vinted_bot open --gui") if pythonw.exists() else (exe, "open --gui")
    )
    folder = instance.folder(settings)
    icon = folder / "vinted-bot.ico"
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_asset("vinted-bot.ico"), icon)
    return _powershell(
        _WINDOWS_MAKE,
        {
            "VB_TARGET": str(target),
            "VB_ARGS": arguments,
            "VB_DIR": str(folder),
            "VB_ICON": str(icon),
        },
    )


# --- Linux -------------------------------------------------------------------------------


def _linux_paths(home: Path) -> tuple[Path, Path]:
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    return (
        data / "applications" / "vinted-bot.desktop",
        data / "icons" / "hicolor" / "512x512" / "apps" / "vinted-bot.png",
    )


def encode_powershell(script: str) -> str:
    """A script as -EncodedCommand takes it, which no command-line quoting can garble."""
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _desktop_arg(value: str) -> str:
    """One Exec argument, quoted the way the desktop entry spec asks."""
    escaped = "".join("\\" + c if c in '"`$\\' else c for c in value)
    # The key's value is itself an escaped string, so each backslash is written twice.
    return '"' + escaped.replace("\\", "\\\\").replace("%", "%%") + '"'


def _make_linux(home: Path, exe: Path, db: Path) -> list[Path]:
    entry, icon = _linux_paths(home)
    entry.parent.mkdir(parents=True, exist_ok=True)
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_asset("vinted-bot.png"), icon)
    command = " ".join(
        _desktop_arg(part)
        for part in ("env", f"VINTED_BOT_DB_PATH={db}", str(exe), "open", "--gui")
    )
    entry.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=vinted-bot\n"
        "Comment=Alerts for new Vinted listings\n"
        f"Exec={command}\n"
        "Icon=vinted-bot\n"
        "Terminal=false\n"
        "Categories=Network;Utility;\n",
        encoding="utf-8",
    )
    entry.chmod(0o755)
    return [entry, icon]


# --- Making and removing -----------------------------------------------------------------


def make(
    settings: Settings, *, platform: str = sys.platform, home: Path | None = None
) -> list[Path]:
    """Make (or remake) the icons for this installation. Returns what was written."""
    home = home or Path.home()
    exe = executable()
    db = settings.db_path.expanduser().resolve()
    if platform == "darwin":
        made = _make_mac(home, exe, db)
    elif platform == "win32":
        made = _make_windows(settings, exe)
    else:
        made = _make_linux(home, exe, db)
    _write_marker(settings)
    return made


def _write_marker(settings: Settings) -> None:
    """Remember that this installation has its icons, and for which program."""
    folder = instance.folder(settings)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / _MARKER).write_text(
        json.dumps({"layout": LAYOUT, "exe": str(executable())}), encoding="utf-8"
    )


def remove(
    settings: Settings, *, platform: str = sys.platform, home: Path | None = None
) -> list[Path]:
    """Take the icons away again. Returns what was removed."""
    home = home or Path.home()
    removed: list[Path] = []
    if platform == "darwin":
        app = _mac_app(home)
        if app.exists():
            shutil.rmtree(app, ignore_errors=True)
            removed.append(app)
    elif platform == "win32":
        removed = _powershell(_WINDOWS_REMOVE)
    else:
        for path in _linux_paths(home):
            if path.exists():
                path.unlink()
                removed.append(path)
    with contextlib.suppress(OSError):
        (instance.folder(settings) / _MARKER).unlink()
    return removed


def made(settings: Settings) -> bool:
    """Whether this installation has its icons (or had them, before someone deleted one)."""
    return (instance.folder(settings) / _MARKER).exists()


def ensure(settings: Settings) -> bool:
    """Make the icons if this installation never had them, or has ones from an older
    layout or another copy of the program. True when something was made."""
    marker = instance.folder(settings) / _MARKER
    with contextlib.suppress(OSError, ValueError):
        recorded = json.loads(marker.read_text(encoding="utf-8"))
        if recorded.get("layout") == LAYOUT and recorded.get("exe") == str(executable()):
            return False
    make(settings)
    return True
