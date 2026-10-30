"""Installing a release from the app, restarting into it, and doing it unattended.

uv and the environment's Python are stand-in scripts that really run as child processes,
so what is tested is the app's handling of a real command: its output, exit code,
timeout and environment. What they print is what uv and Python print.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from vinted_sniper import __version__
from vinted_sniper.app import Application
from vinted_sniper.config import Settings
from vinted_sniper.db.repo import Repo
from vinted_sniper.engine import self_update
from vinted_sniper.engine.self_update import Install, InstallKind, Phase, Updater
from vinted_sniper.vinted.models import Item

NEWER = "99.0.0"
QUIET = self_update.QUIET_HOUR


def script(path: Path, body: str) -> Path:
    """An executable Python script, standing in for uv or an environment's python."""
    path.write_text(f"#!{sys.executable}\nimport os, sys, time\n{body}\n")
    path.chmod(0o755)
    return path


def fake_uv(tmp_path: Path, *, exit_code: int = 0, sleep_s: float = 0) -> Path:
    """Prints what uv prints, and notes the arguments and tool folder it was given."""
    return script(
        tmp_path / "uv",
        f"open({str(tmp_path / 'uv-call.json')!r}, 'w').write(__import__('json').dumps("
        "{'argv': sys.argv[1:], 'tool_dir': os.environ.get('UV_TOOL_DIR')}))\n"
        f"time.sleep({sleep_s})\n"
        "print('Resolved 40 packages in 812ms')\n"
        f"print('Updated vinted-sniper v{__version__} -> v{NEWER}')\n"
        f"sys.exit({exit_code})",
    )


def fake_python(tmp_path: Path, version: str = NEWER) -> Path:
    """The tool environment's interpreter, saying which version is now on disk."""
    return script(tmp_path / "python", f"print({version!r})")


def uv_install(tmp_path: Path, *, supervisor: str | None = "systemd", **kwargs: Any) -> Install:
    # Made only when not given: the stand-ins share their file names.
    if "tool" not in kwargs:
        kwargs["tool"] = fake_uv(tmp_path)
    if "python" not in kwargs:
        kwargs["python"] = fake_python(tmp_path)
    kwargs.setdefault("tool_env", {"UV_TOOL_DIR": str(tmp_path / "tools")})
    return Install(kind=InstallKind.UV_TOOL, supervisor=supervisor, **kwargs)


@pytest.fixture
async def released(repo: Repo) -> Repo:
    """A newer release, as the daily check against GitHub would have stored it."""
    await repo.set_latest_version(NEWER)
    return repo


def updater_for(
    settings: Settings, repo: Repo, install: Install, stop: asyncio.Event | None = None, **kw: Any
) -> Updater:
    kw.setdefault("restart_grace_s", 0)
    return Updater(settings, repo, stop or asyncio.Event(), install, **kw)


async def update(updater: Updater) -> Updater:
    await updater.start()
    await updater.settle()
    return updater


# --- Installing ---------------------------------------------------------------------


async def test_a_supervised_install_upgrades_then_exits_to_be_restarted(
    tmp_path: Path, settings: Settings, released: Repo
) -> None:
    stop = asyncio.Event()

    updater = await update(updater_for(settings, released, uv_install(tmp_path), stop))

    assert (updater.phase, updater.restart_requested, stop.is_set()) == (
        Phase.RESTARTING,
        True,
        True,
    )


async def test_the_upgrade_runs_uv_on_this_copys_tool_folder(
    tmp_path: Path, settings: Settings, released: Repo
) -> None:
    await update(updater_for(settings, released, uv_install(tmp_path)))

    call = json.loads((tmp_path / "uv-call.json").read_text())
    assert call == {
        "argv": ["tool", "upgrade", "vinted-sniper", "--no-progress"],
        "tool_dir": str(tmp_path / "tools"),
    }


async def test_what_uv_prints_is_kept_for_the_dashboard(
    tmp_path: Path, settings: Settings, released: Repo
) -> None:
    updater = await update(updater_for(settings, released, uv_install(tmp_path)))

    assert f"Updated vinted-sniper v{__version__} -> v{NEWER}" in updater.status()["output"]


async def test_a_note_is_left_for_the_next_start(
    tmp_path: Path, settings: Settings, released: Repo
) -> None:
    await update(updater_for(settings, released, uv_install(tmp_path)))

    note = json.loads(await released.get_state_value("update_pending") or "{}")
    assert (note["from"], note["to"], note["automatic"]) == (__version__, NEWER, False)


async def test_without_a_supervisor_it_installs_and_says_how_to_restart(
    tmp_path: Path, settings: Settings, released: Repo
) -> None:
    stop = asyncio.Event()

    updater = await update(
        updater_for(settings, released, uv_install(tmp_path, supervisor=None), stop)
    )

    assert (updater.phase, stop.is_set()) == (Phase.INSTALLED, False)
    assert "vinted-sniper run" in updater.status()["message"]


async def test_a_failing_upgrade_keeps_the_app_running_and_says_so(
    tmp_path: Path, settings: Settings, released: Repo
) -> None:
    stop = asyncio.Event()
    install = uv_install(tmp_path, tool=fake_uv(tmp_path, exit_code=2))

    updater = await update(updater_for(settings, released, install, stop))

    assert (updater.phase, stop.is_set()) == (Phase.FAILED, False)
    assert "keeps running" in updater.status()["message"]


async def test_a_failure_is_recorded_for_the_settings_page(
    tmp_path: Path, settings: Settings, released: Repo
) -> None:
    install = uv_install(tmp_path, tool=fake_uv(tmp_path, exit_code=2))

    await update(updater_for(settings, released, install))

    outcome = await self_update.last_outcome(released)
    assert outcome is not None
    assert not outcome.ok


async def test_an_upgrade_that_hangs_is_stopped(
    tmp_path: Path, settings: Settings, released: Repo
) -> None:
    install = uv_install(tmp_path, tool=fake_uv(tmp_path, sleep_s=30))

    updater = await update(updater_for(settings, released, install, command_timeout_s=0.5))

    assert updater.phase is Phase.FAILED
    assert "took longer" in updater.status()["message"]


async def test_no_restart_when_nothing_newer_landed(
    tmp_path: Path, settings: Settings, released: Repo
) -> None:
    """uv succeeding with nothing to do, e.g. PyPI a few minutes behind GitHub."""
    stop = asyncio.Event()
    install = uv_install(tmp_path, python=fake_python(tmp_path, __version__))

    updater = await update(updater_for(settings, released, install, stop))

    assert (updater.phase, stop.is_set()) == (Phase.FAILED, False)


async def test_never_restarts_into_an_older_version(
    tmp_path: Path, settings: Settings, released: Repo
) -> None:
    stop = asyncio.Event()
    install = uv_install(tmp_path, python=fake_python(tmp_path, "0.0.1"))

    await update(updater_for(settings, released, install, stop))

    assert not stop.is_set()


async def test_pipx_installs_upgrade_with_pipx(
    tmp_path: Path, settings: Settings, released: Repo
) -> None:
    install = Install(
        kind=InstallKind.PIPX,
        supervisor="systemd",
        tool=fake_uv(tmp_path),
        python=fake_python(tmp_path),
    )

    await update(updater_for(settings, released, install))

    assert json.loads((tmp_path / "uv-call.json").read_text())["argv"] == [
        "upgrade",
        "vinted-sniper",
    ]


async def test_the_windows_launcher_does_the_upgrade_after_the_app_exits(
    tmp_path: Path, settings: Settings, released: Repo
) -> None:
    """A running program's files are locked on Windows, so the app only steps aside."""
    install = Install(kind=InstallKind.UV_TOOL, supervisor="windows-launcher", windows=True)

    updater = await update(updater_for(settings, released, install))

    assert (updater.restart_requested, (tmp_path / "uv-call.json").exists()) == (True, False)


# --- Refusing ---------------------------------------------------------------------------


async def test_nothing_is_installed_without_a_newer_release(
    tmp_path: Path, settings: Settings, repo: Repo
) -> None:
    await repo.set_latest_version(__version__)

    with pytest.raises(self_update.UpdateRefusedError, match="no newer release"):
        await updater_for(settings, repo, uv_install(tmp_path)).start()


async def test_docker_never_updates_itself(settings: Settings, released: Repo) -> None:
    install = Install(kind=InstallKind.DOCKER, supervisor=None)

    with pytest.raises(self_update.UpdateRefusedError, match="docker compose pull"):
        await updater_for(settings, released, install).start()


async def test_one_update_at_a_time(tmp_path: Path, settings: Settings, released: Repo) -> None:
    install = uv_install(tmp_path, tool=fake_uv(tmp_path, sleep_s=0.5))
    updater = updater_for(settings, released, install)
    await updater.start()

    with pytest.raises(self_update.UpdateRefusedError, match="already under way"):
        await updater.start()
    await updater.settle()


async def test_a_failed_update_can_be_tried_again(
    tmp_path: Path, settings: Settings, released: Repo
) -> None:
    updater = updater_for(
        settings, released, uv_install(tmp_path, tool=fake_uv(tmp_path, exit_code=1))
    )
    await update(updater)
    updater.install = uv_install(tmp_path)

    await update(updater)

    assert updater.phase is Phase.RESTARTING


# --- After the restart ----------------------------------------------------------------


class Announcements:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def __call__(self, message: str) -> None:
        self.sent.append(message)


async def leave_note(repo: Repo, *, before: str, automatic: bool) -> None:
    note = {"from": before, "to": __version__, "automatic": automatic, "at": 1}
    await repo.set_state_value("update_pending", json.dumps(note))


async def test_an_automatic_update_tells_the_status_destinations(repo: Repo) -> None:
    await leave_note(repo, before="0.1.0", automatic=True)
    announce = Announcements()

    await self_update.finish_pending(repo, announce)

    assert len(announce.sent) == 1
    assert f"updated itself to version {__version__}" in announce.sent[0]


async def test_an_update_someone_clicked_is_not_announced(repo: Repo) -> None:
    await leave_note(repo, before="0.1.0", automatic=False)
    announce = Announcements()

    await self_update.finish_pending(repo, announce)

    assert announce.sent == []


async def test_a_successful_update_is_recorded(repo: Repo) -> None:
    await leave_note(repo, before="0.1.0", automatic=False)

    await self_update.finish_pending(repo, Announcements())

    outcome = await self_update.last_outcome(repo)
    assert outcome is not None
    assert (outcome.ok, outcome.message) == (True, f"Updated from 0.1.0 to {__version__}.")


async def test_coming_back_on_the_same_version_is_a_failed_update(repo: Repo) -> None:
    """What a failed upgrade by the Windows launcher looks like from inside the app."""
    await leave_note(repo, before=__version__, automatic=True)
    announce = Announcements()

    await self_update.finish_pending(repo, announce)

    outcome = await self_update.last_outcome(repo)
    assert outcome is not None
    assert (outcome.ok, announce.sent) == (False, [])


async def test_the_note_is_read_once(repo: Repo) -> None:
    await leave_note(repo, before="0.1.0", automatic=True)
    announce = Announcements()

    await self_update.finish_pending(repo, announce)
    await self_update.finish_pending(repo, announce)

    assert len(announce.sent) == 1


# --- Unattended -------------------------------------------------------------------------

AT_FOUR = datetime(2026, 10, 30, 4, 20, tzinfo=UTC)


@pytest.fixture
async def opted_in(released: Repo) -> Repo:
    await released.set_auto_update(True)
    await released.set_timezone("UTC")
    return released


async def test_it_updates_itself_in_the_quiet_hour(
    tmp_path: Path, settings: Settings, opted_in: Repo
) -> None:
    updater = updater_for(settings, opted_in, uv_install(tmp_path))

    started = await updater.maybe_update(AT_FOUR)
    await updater.settle()

    assert (started, updater.restart_requested) == (True, True)


async def test_the_note_marks_the_update_as_automatic(
    tmp_path: Path, settings: Settings, opted_in: Repo
) -> None:
    updater = updater_for(settings, opted_in, uv_install(tmp_path))

    await updater.maybe_update(AT_FOUR)
    await updater.settle()

    assert json.loads(await opted_in.get_state_value("update_pending") or "{}")["automatic"]


async def test_automatic_updates_are_off_unless_switched_on(
    tmp_path: Path, settings: Settings, released: Repo
) -> None:
    await released.set_timezone("UTC")

    assert not await updater_for(settings, released, uv_install(tmp_path)).maybe_update(AT_FOUR)


async def test_not_outside_the_quiet_hour(
    tmp_path: Path, settings: Settings, opted_in: Repo
) -> None:
    updater = updater_for(settings, opted_in, uv_install(tmp_path))

    assert not await updater.maybe_update(AT_FOUR.replace(hour=14))


async def test_the_quiet_hour_is_on_the_apps_own_clock(
    tmp_path: Path, settings: Settings, opted_in: Repo
) -> None:
    """04:20 in Amsterdam (winter time) is 03:20 in UTC."""
    await opted_in.set_timezone("Europe/Amsterdam")
    updater = updater_for(settings, opted_in, uv_install(tmp_path))

    assert await updater.maybe_update(datetime(2026, 11, 2, 3, 20, tzinfo=UTC))
    await updater.settle()


async def queue_an_alert(repo: Repo) -> None:
    query_id = await repo.add_query(
        name="x", url="https://www.vinted.fr/catalog", tld="fr", params={}, poll_interval_s=60
    )
    query = await repo.get_query(query_id)
    assert query is not None
    destination_id = await repo.add_destination(
        kind="webhook", name="hook", config={"url": "https://example.test/hook"}
    )
    item = Item(
        item_id=1,
        tld="fr",
        title="Coat",
        url="https://www.vinted.fr/items/1",
        price=Decimal("10"),
        total_price=Decimal("11.20"),
        currency="EUR",
        photo_ts=int(time.time()),
    )
    await repo.record_new_items(query, [item], [destination_id])


async def test_not_while_an_alert_is_on_its_way_out(
    tmp_path: Path, settings: Settings, opted_in: Repo
) -> None:
    await queue_an_alert(opted_in)
    updater = updater_for(settings, opted_in, uv_install(tmp_path))

    # Later than the alert was queued, so it is due.
    assert not await updater.maybe_update(datetime(2099, 1, 1, 4, 20, tzinfo=UTC))


async def test_an_alert_held_for_later_does_not_hold_the_update_up(
    tmp_path: Path, settings: Settings, opted_in: Repo
) -> None:
    """It waits in the database either way; a restart does not lose it."""
    await queue_an_alert(opted_in)
    updater = updater_for(settings, opted_in, uv_install(tmp_path))

    # Earlier than the alert's next attempt, as quiet hours or a retry delay would make it.
    assert await updater.maybe_update(AT_FOUR)
    await updater.settle()


async def test_not_without_something_to_restart_it(
    tmp_path: Path, settings: Settings, opted_in: Repo
) -> None:
    updater = updater_for(settings, opted_in, uv_install(tmp_path, supervisor=None))

    assert not await updater.maybe_update(AT_FOUR)


async def test_a_failed_automatic_update_waits_for_the_next_night(
    tmp_path: Path, settings: Settings, opted_in: Repo
) -> None:
    install = uv_install(tmp_path, tool=fake_uv(tmp_path, exit_code=1))
    updater = updater_for(settings, opted_in, install)
    await updater.maybe_update(AT_FOUR)
    await updater.settle()

    assert not await updater.maybe_update(AT_FOUR.replace(minute=40))


# --- The whole app ----------------------------------------------------------------------


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def test_the_app_exits_with_the_restart_code_after_an_update(
    tmp_path: Path, repo: Repo
) -> None:
    """Button to exit code: what the installers' services see when an update is done."""
    await repo.set_latest_version(NEWER)
    await repo.set_onboarded(True)
    port = free_port()
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        db_path=repo._db.path,  # the test's database, which already says a release is out
        fetch_mode="mock",
        mock_scenario_dir=tmp_path,
        web_port=port,
        log_level="WARNING",
    )
    app = Application(settings, install=uv_install(tmp_path))
    running = asyncio.create_task(app.run())
    try:
        response: httpx.Response | None = None
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as http:
            # Until the dashboard is listening, for up to ten seconds.
            for _ in range(200):
                with contextlib.suppress(httpx.TransportError):
                    response = await http.post("/api/update")
                if response is not None:
                    break
                await asyncio.sleep(0.05)
        exit_code = await asyncio.wait_for(running, timeout=20)
    finally:
        running.cancel()

    assert response is not None
    assert (response.status_code, exit_code) == (202, self_update.RESTART_EXIT_CODE)


def zone_where_it_is_four_now() -> str:
    """A fixed-offset zone whose clock currently reads 04:xx."""
    offset = (QUIET - datetime.now(UTC).hour + 12) % 24 - 12
    # Etc/GMT names count the other way round: Etc/GMT-2 is two hours ahead of UTC.
    return "Etc/GMT" if offset == 0 else f"Etc/GMT{-offset:+d}"


async def test_a_copy_that_just_started_does_not_update_straight_away(
    tmp_path: Path, settings: Settings, opted_in: Repo
) -> None:
    """The Windows launcher reads an exit in the first seconds as a failed start."""
    await opted_in.set_timezone(zone_where_it_is_four_now())
    stop = asyncio.Event()
    updater = updater_for(settings, opted_in, uv_install(tmp_path), stop)

    loop = asyncio.create_task(updater.run_automatically())
    await asyncio.sleep(0.2)
    stop.set()
    await loop

    assert updater.phase is Phase.IDLE
