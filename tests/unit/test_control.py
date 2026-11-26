"""Opening, starting and stopping: one copy at a time, stopped stays stopped, the icon."""

from __future__ import annotations

import base64
import plistlib
import subprocess
from pathlib import Path

import pytest

from vinted_bot import cli, control, instance, shortcuts
from vinted_bot.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, db_path=tmp_path / "data" / "app.db")  # type: ignore[call-arg]


# --- One copy at a time -----------------------------------------------------------------


def test_nothing_runs_until_the_lock_is_held(settings: Settings) -> None:
    assert instance.running(settings) is None

    with instance.Instance(settings):
        current = instance.running(settings)
        assert current is not None
        assert current.url == f"http://localhost:{settings.web_port}"

    assert instance.running(settings) is None


def test_a_second_copy_is_refused_and_told_where_the_first_is(settings: Settings) -> None:
    with instance.Instance(settings), pytest.raises(instance.AlreadyRunningError) as refused:
        instance.Instance(settings).__enter__()

    assert refused.value.running is not None
    assert refused.value.running.port == settings.web_port


def test_a_run_file_left_by_a_crash_does_not_count(settings: Settings) -> None:
    where = instance.folder(settings)
    where.mkdir(parents=True)
    (where / "vinted-bot.lock").write_text("\n")
    (where / "vinted-bot.run.json").write_text(
        '{"pid": 1, "port": 8000, "version": "x", "started_at": 0}'
    )

    assert instance.running(settings) is None


def test_stopping_on_purpose_is_remembered_until_cleared(settings: Settings) -> None:
    instance.mark_stopped(settings)
    assert instance.is_stopped(settings)

    instance.clear_stopped(settings)
    assert not instance.is_stopped(settings)


def test_stop_leaves_a_note_even_when_nothing_runs(settings: Settings) -> None:
    assert control.stop(settings, timeout=0) is False
    assert instance.is_stopped(settings)


# --- Which service started it -----------------------------------------------------------


def test_a_launch_agent_for_this_database_is_the_service(
    settings: Settings, tmp_path: Path
) -> None:
    agents = tmp_path / "home" / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    plist = {"EnvironmentVariables": {"VINTED_BOT_DB_PATH": str(settings.db_path)}}
    (agents / f"{control.LAUNCHD_LABEL}.plist").write_bytes(plistlib.dumps(plist))

    found = control.installed_service(settings, platform="darwin", home=tmp_path / "home")

    assert found is control.Service.LAUNCHD


def test_a_launch_agent_for_another_database_is_left_alone(
    settings: Settings, tmp_path: Path
) -> None:
    """A copy tried out with its own database must never start the installed one."""
    agents = tmp_path / "home" / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    plist = {"EnvironmentVariables": {"VINTED_BOT_DB_PATH": str(tmp_path / "other.db")}}
    (agents / f"{control.LAUNCHD_LABEL}.plist").write_bytes(plistlib.dumps(plist))

    assert control.installed_service(settings, platform="darwin", home=tmp_path / "home") is None


def test_a_systemd_unit_for_this_database_is_the_service(
    settings: Settings, tmp_path: Path
) -> None:
    unit = tmp_path / "home" / ".config" / "systemd" / "user" / control.SYSTEMD_UNIT
    unit.parent.mkdir(parents=True)
    unit.write_text(f'[Service]\nEnvironment="VINTED_BOT_DB_PATH={settings.db_path}"\n')

    found = control.installed_service(
        settings, platform="linux", home=tmp_path / "home", environ={}
    )

    assert found is control.Service.SYSTEMD


def test_the_windows_launcher_next_to_the_database_is_the_service(settings: Settings) -> None:
    where = instance.folder(settings)
    where.mkdir(parents=True)
    (where / control.WINDOWS_LAUNCHER).write_text("")

    assert control.installed_service(settings, platform="win32") is control.Service.WINDOWS


@pytest.mark.parametrize(
    ("environ", "platform", "expected"),
    [
        ({}, "darwin", True),
        ({}, "win32", True),
        ({"DISPLAY": ":0"}, "linux", True),
        ({}, "linux", False),
        ({"SSH_CONNECTION": "1.2.3.4 22 5.6.7.8 22"}, "darwin", False),
    ],
)
def test_a_browser_only_opens_where_someone_can_see_it(
    environ: dict[str, str], platform: str, expected: bool
) -> None:
    assert control.can_open_browser(environ, platform) is expected


# --- Saying how to start it again -------------------------------------------------------


def test_with_an_icon_people_are_sent_to_it(settings: Settings) -> None:
    instance.folder(settings).mkdir(parents=True)
    (instance.folder(settings) / "vinted-bot.shortcuts").write_text("{}")

    assert "Applications" in control.how_to_open(settings, "darwin")
    assert "Start menu" in control.how_to_open(settings, "win32")


def test_without_an_icon_people_are_sent_to_the_terminal(settings: Settings) -> None:
    assert control.how_to_open(settings, "darwin") == "type vinted-bot in Terminal"
    assert control.how_to_open(settings, "win32") == "type vinted-bot in PowerShell"


# --- The icon ---------------------------------------------------------------------------


def test_the_mac_icon_is_an_app_that_opens_the_dashboard(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shortcuts, "executable", lambda: Path("/opt/vb/bin/vinted-bot"))
    home = tmp_path / "home"

    made = shortcuts.make(settings, platform="darwin", home=home)

    app = home / "Applications" / "vinted-bot.app"
    assert made == [app]
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleExecutable"] == "vinted-bot"
    script = (app / "Contents" / "MacOS" / "vinted-bot").read_text()
    assert script == (
        "#!/bin/sh\n"
        f"export VINTED_BOT_DB_PATH={settings.db_path.resolve()}\n"
        "exec /opt/vb/bin/vinted-bot open --gui\n"
    )
    assert (app / "Contents" / "Resources" / "vinted-bot.icns").stat().st_size > 0
    assert shortcuts.made(settings)

    shortcuts.remove(settings, platform="darwin", home=home)
    assert not app.exists()
    assert not shortcuts.made(settings)


def test_the_windows_icons_are_read_back_on_a_german_windows(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Windows PowerShell 5.1 answers in the console's code page unless told otherwise, and
    # Python reads it as the ANSI one: cp850 and cp1252 on a German Windows, where a "ü"
    # (0x81 in cp850) is no character at all.
    places = [
        r"C:\Users\Jürgen\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\vinted-bot.lnk",
        r"C:\Users\Jürgen\Desktop\vinted-bot.lnk",
    ]

    def powershell(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        script = base64.b64decode(command[-1]).decode("utf-16-le")
        utf8 = "OutputEncoding = New-Object System.Text.UTF8Encoding" in script
        out = "".join(f"{place}\r\n" for place in places).encode("utf-8" if utf8 else "cp850")
        encoding = str(kwargs.get("encoding") or "cp1252")
        return subprocess.CompletedProcess(command, 0, out.decode(encoding), "")

    monkeypatch.setattr(shortcuts, "executable", lambda: Path(r"C:\vb\vinted-bot.exe"))
    monkeypatch.setattr(subprocess, "run", powershell)

    assert shortcuts.make(settings, platform="win32") == [Path(place) for place in places]


def test_the_linux_icon_is_a_menu_entry(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shortcuts, "executable", lambda: Path("/opt/vb/bin/vinted-bot"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    home = tmp_path / "home"

    entry, icon = shortcuts.make(settings, platform="linux", home=home)

    exec_line = next(line for line in entry.read_text().splitlines() if line.startswith("Exec="))
    assert exec_line == (
        f'Exec="env" "VINTED_BOT_DB_PATH={settings.db_path.resolve()}" '
        '"/opt/vb/bin/vinted-bot" "open" "--gui"'
    )
    assert icon.exists()


def test_odd_characters_in_paths_cannot_run_anything(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shortcuts, "executable", lambda: Path('/opt/v$b`x`"/bin/vinted-bot'))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    home = tmp_path / "home"

    app = shortcuts.make(settings, platform="darwin", home=home)[0]
    entry = shortcuts.make(settings, platform="linux", home=home)[0]

    script = (app / "Contents" / "MacOS" / "vinted-bot").read_text()
    assert "exec '/opt/v$b`x`\"/bin/vinted-bot' open --gui" in script
    assert '"/opt/v\\\\$b\\\\`x\\\\`\\\\"/bin/vinted-bot"' in entry.read_text()


def test_the_icon_is_made_once_so_a_deleted_one_stays_deleted(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[int] = []

    def make(settings: Settings, **_: object) -> list[Path]:
        made.append(1)
        shortcuts._write_marker(settings)
        return []

    monkeypatch.setattr(shortcuts, "executable", lambda: Path("/opt/vb/bin/vinted-bot"))
    monkeypatch.setattr(shortcuts, "make", make)

    assert shortcuts.ensure(settings)
    assert not shortcuts.ensure(settings)
    assert made == [1]


# --- Starting at login, and entries from older installers --------------------------------


def _launch_agent(settings: Settings, home: Path, **extra: object) -> Path:
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / f"{control.LAUNCHD_LABEL}.plist"
    data: dict[str, object] = {
        "Label": control.LAUNCHD_LABEL,
        "ProgramArguments": ["/opt/vb/bin/vinted-bot", "run"],
        "EnvironmentVariables": {"VINTED_BOT_DB_PATH": str(settings.db_path)},
        "KeepAlive": {"SuccessfulExit": False},
        **extra,
    }
    plist.write_bytes(plistlib.dumps(data))
    return plist


def test_switching_login_start_off_moves_the_launch_agent_aside(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    home = tmp_path / "home"
    plist = _launch_agent(settings, home)
    assert control.starts_at_login(settings, home=home) is True

    control.set_starts_at_login(settings, False, home=home)

    assert not plist.exists()
    assert control.starts_at_login(settings, home=home) is False
    assert control.installed_service(settings, platform="darwin", home=home) is (
        control.Service.LAUNCHD
    ), "still the service: the icon and updates go through it"

    control.set_starts_at_login(settings, True, home=home)
    assert plist.exists()


def test_an_old_launch_agent_is_brought_up_to_date(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Older installers' entries restarted vinted-bot after any exit, so Stop wouldn't stick."""
    monkeypatch.setattr("sys.platform", "darwin")
    home = tmp_path / "home"
    plist = _launch_agent(
        settings,
        home,
        KeepAlive=True,
        ProgramArguments=["/usr/bin/caffeinate", "-s", "/opt/vb/bin/vinted-bot", "run"],
    )

    assert control.upgrade_service(settings, home=home) is True

    data = plistlib.loads(plist.read_bytes())
    assert data["KeepAlive"] == {"SuccessfulExit": False}
    assert data["ProgramArguments"] == ["/opt/vb/bin/vinted-bot", "run"]
    assert control.upgrade_service(settings, home=home) is None, "only once"


def test_an_old_systemd_unit_is_brought_up_to_date(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(control, "_run", lambda _: True)
    home = tmp_path / "home"
    unit = home / ".config" / "systemd" / "user" / control.SYSTEMD_UNIT
    unit.parent.mkdir(parents=True)
    unit.write_text(
        f'[Service]\nEnvironment="VINTED_BOT_DB_PATH={settings.db_path}"\nRestart=always\n'
    )

    control.upgrade_service(settings, home=home)

    assert "Restart=on-failure" in unit.read_text()


def test_a_folder_that_cannot_be_locked_still_runs(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Some NAS shares can't be locked at all; that isn't "already running"."""
    import errno  # noqa: PLC0415
    import fcntl  # noqa: PLC0415

    def no_locks(*_: object) -> None:
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(fcntl, "flock", no_locks)

    with instance.Instance(settings):
        assert instance.running(settings) is None


def test_the_icon_finds_the_port_the_service_runs_on(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    _launch_agent(
        settings,
        tmp_path / "home",
        EnvironmentVariables={
            "VINTED_BOT_DB_PATH": str(settings.db_path),
            "VINTED_BOT_WEB_PORT": "8001",
        },
    )

    service = control.installed_service(settings)

    assert control._service_port(settings, service) == 8001


def test_when_launchd_refuses_it_starts_on_its_own(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """macOS with "Allow in the background" off for vinted-bot refuses both commands."""
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    _launch_agent(settings, tmp_path / "home")
    started: list[int] = []
    monkeypatch.setattr(control, "_run", lambda _: False)
    monkeypatch.setattr(control, "answers", lambda _: None)
    monkeypatch.setattr(control, "_start_alone", lambda _, port: started.append(port))
    monkeypatch.setattr(control, "wait_until_running", lambda *_, **__: None)

    control.start(settings)

    assert started == [settings.web_port]


# --- Windows: starting at sign-in without a window -------------------------------------


def _windows_install(settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A Windows install: the launcher next to the database, and the tool's own pythonw."""
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    where = instance.folder(settings)
    where.mkdir(parents=True)
    (where / control.WINDOWS_LAUNCHER).write_text("")
    scripts = tmp_path / "tool" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "pythonw.exe").write_text("")
    monkeypatch.setattr("sys.executable", str(scripts / "python.exe"))
    return scripts / "pythonw.exe"


def test_the_windows_startup_shortcut_runs_pythonw_rather_than_powershell(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Windows 11 opens PowerShell in Windows Terminal, which ignores -WindowStyle Hidden.
    pythonw = _windows_install(settings, tmp_path, monkeypatch)
    made: list[dict[str, str]] = []

    def run_powershell(
        script: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        made.append(env or {})
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(shortcuts, "run_powershell", run_powershell)

    control.set_starts_at_login(settings, True)

    assert made[0]["VB_TARGET"] == str(pythonw)
    module, *command = made[0]["VB_ARGS"].split()[1:]
    assert module == "vinted_bot"
    args = cli.build_parser().parse_args(command)
    assert (args.command, args.login) == ("start", True)


def test_at_sign_in_a_copy_stopped_on_purpose_stays_stopped(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[control.Service | None] = []

    def start_service(_: Settings, service: control.Service | None) -> bool:
        started.append(service)
        return True

    monkeypatch.setattr(control, "_start_service", start_service)

    instance.mark_stopped(settings)
    control.start_at_login(settings)
    assert started == []

    instance.clear_stopped(settings)
    control.start_at_login(settings)
    assert len(started) == 1


def test_an_old_windows_startup_shortcut_is_remade_once(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _windows_install(settings, tmp_path, monkeypatch)
    link = control._windows_startup_link()
    link.parent.mkdir(parents=True)
    remade: list[bool] = []
    monkeypatch.setattr(control, "set_starts_at_login", lambda _, on, **__: remade.append(on))

    # Shortcuts keep their arguments as UTF-16.
    old = r"-NoProfile -WindowStyle Hidden -File C:\vb\start-vinted-bot.ps1"
    link.write_bytes(b"L\0\0\0" + old.encode("utf-16-le"))
    control.upgrade_service(settings)
    assert remade == [True]

    link.write_bytes(b"L\0\0\0" + "-m vinted_bot start --login".encode("utf-16-le"))
    control.upgrade_service(settings)
    assert remade == [True]
