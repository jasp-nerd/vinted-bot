"""Getting back to vinted-bot: one copy, Stop that sticks, the commands, and the links
that lead back to the dashboard from a phone."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import LOCAL_CLIENT
from vinted_bot import app, cli, control, instance, managed
from vinted_bot.botctl.telegram_bot import dashboard_text
from vinted_bot.config import Settings
from vinted_bot.db.repo import Repo
from vinted_bot.web.server import create_app


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    return Settings(_env_file=None, db_path=tmp_path / "app.db", **overrides)  # type: ignore[call-arg]


# --- `vinted-bot run` ----------------------------------------------------------------------


async def test_a_second_run_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    settings = _settings(tmp_path)
    with instance.Instance(settings):
        code = await app.run(settings)

    assert code == 1
    assert "already running" in capsys.readouterr().err


async def test_a_service_finding_a_copy_started_by_hand_exits_cleanly(tmp_path: Path) -> None:
    settings = _settings(tmp_path, supervised="launchd")
    with instance.Instance(settings):
        assert await app.run(settings) == 0


async def test_a_service_starting_it_after_a_stop_leaves_it_stopped(tmp_path: Path) -> None:
    settings = _settings(tmp_path, supervised="systemd")
    instance.mark_stopped(settings)

    assert await app.run(settings) == 0
    assert instance.is_stopped(settings), "only opening it again clears the stop"


async def test_a_running_app_stops_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path, web_enabled=False, fetch_mode="mock", mock_scenario_dir=tmp_path)
    monkeypatch.setattr(app, "STOP_CHECK_INTERVAL_S", 0.05)
    running = asyncio.create_task(app.run(settings))
    for _ in range(200):
        if instance.running(settings):
            break
        await asyncio.sleep(0.05)

    instance.mark_stopped(settings)

    assert await asyncio.wait_for(running, timeout=20) == 0
    assert instance.running(settings) is None


# --- The commands --------------------------------------------------------------------------


def test_open_when_running_opens_the_dashboard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings(tmp_path)
    opened: list[str] = []
    monkeypatch.setattr(control, "can_open_browser", lambda *_: True)
    monkeypatch.setattr(control, "answers", lambda _: "vinted-bot")
    monkeypatch.setattr("webbrowser.open", opened.append)

    with instance.Instance(settings):
        assert cli._open(settings, browser=True, gui=False) == 0

    assert opened == [f"http://localhost:{settings.web_port}"]
    assert "Starting" not in capsys.readouterr().out


def test_open_without_a_browser_prints_the_address(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(control, "can_open_browser", lambda *_: False)
    monkeypatch.setattr(control, "answers", lambda _: "vinted-bot")

    with instance.Instance(settings):
        cli._open(settings, browser=True, gui=False)

    assert f"Dashboard: http://localhost:{settings.web_port}" in capsys.readouterr().out


def test_another_program_on_the_port_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(control, "answers", lambda _: "other")

    assert cli._open(settings, browser=False, gui=False) == 1
    assert "Another program is using port" in capsys.readouterr().err


def _without_a_console(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """pythonw, as the Windows icon and Startup shortcut run it, started in the data folder."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdout", None)
    monkeypatch.setattr("sys.stderr", None)
    monkeypatch.setenv("VINTED_BOT_DB_PATH", str(tmp_path / "app.db"))
    shown: list[str] = []
    monkeypatch.setattr(control, "show_message", shown.append)
    return shown


def _windowless_log(tmp_path: Path) -> str:
    sys.stderr.close()
    return (tmp_path / cli.WINDOWLESS_LOG).read_text(encoding="utf-8")


def test_the_icon_says_what_is_wrong_with_a_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown = _without_a_console(tmp_path, monkeypatch)
    monkeypatch.setenv("VINTED_BOT_WEB_PORT", "not a port")

    assert cli.main(["open", "--gui"]) == 2

    assert len(shown) == 1
    assert shown[0] in _windowless_log(tmp_path)


def test_the_icon_writes_down_a_crash_and_says_where(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown = _without_a_console(tmp_path, monkeypatch)

    async def crash(_: object) -> int:
        raise RuntimeError("something nobody planned for")

    monkeypatch.setattr(cli, "_run", crash)

    assert cli.main(["open", "--gui"]) == 1

    assert "RuntimeError: something nobody planned for" in _windowless_log(tmp_path)
    assert str(tmp_path / cli.WINDOWLESS_LOG) in shown[0]


def test_vinted_bot_alone_means_open() -> None:
    args = cli.build_parser().parse_args([])

    assert args.command == "open"
    assert args.no_browser is False


async def test_address_lets_the_network_in_with_a_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr("vinted_bot.network.lan_addresses", lambda: ["192.168.1.20"])

    assert await cli._cmd_address(settings, allow_network=True) == 0

    out = capsys.readouterr().out
    assert "The dashboard now has a password" in out
    assert f"http://192.168.1.20:{settings.web_port}" in out
    assert "Scan this with your phone" in out


async def test_address_says_how_to_let_a_phone_in(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings(tmp_path)

    await cli._cmd_address(settings, allow_network=False)

    assert "vinted-bot address --allow-network" in capsys.readouterr().out


# --- Links back to the dashboard -----------------------------------------------------------


async def test_with_phone_access_on_alerts_link_this_computer_on_the_network(
    tmp_path: Path, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr("vinted_bot.network.lan_addresses", lambda: ["192.168.1.20"])
    monkeypatch.setattr(managed, "in_container", lambda: False)
    assert await managed.dashboard_url(settings, repo) == f"http://127.0.0.1:{settings.web_port}"

    await managed.set_phone_access(repo, True)

    assert await managed.dashboard_url(settings, repo) == f"http://192.168.1.20:{settings.web_port}"


async def test_telegram_dashboard_explains_how_when_only_this_computer_can_open_it(
    tmp_path: Path, repo: Repo
) -> None:
    text = await dashboard_text(repo, _settings(tmp_path))

    assert "Open on your phone" in text
    assert "vinted-bot address --allow-network" in text


async def test_telegram_dashboard_links_the_network_address(
    tmp_path: Path, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("vinted_bot.network.lan_addresses", lambda: ["192.168.1.20"])
    monkeypatch.setattr(managed, "in_container", lambda: False)
    await managed.set_phone_access(repo, True)

    text = await dashboard_text(repo, _settings(tmp_path))

    assert 'href="http://192.168.1.20:8000"' in text
    assert "same Wi-Fi" in text


# --- The dashboard -------------------------------------------------------------------------


@pytest.fixture
def dashboard(tmp_path: Path, repo: Repo) -> Any:
    with TestClient(create_app(_settings(tmp_path), repo), client=LOCAL_CLIENT) as client:
        yield client


def test_stop_in_settings_stops_and_says_how_to_start_again(
    dashboard: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("vinted_bot.web.routes.settings_page.in_container", lambda: False)
    assert 'data-action="/settings/stop"' in dashboard.get("/settings").text

    page = dashboard.post("/settings/stop").text

    assert "vinted-bot has stopped" in page
    assert "To start it again" in page
    assert instance.is_stopped(_settings(tmp_path))


def test_health_names_the_app(dashboard: TestClient) -> None:
    assert dashboard.get("/healthz").json()["app"] == "vinted-bot"


def test_the_installed_app_has_a_name_an_offline_page_and_a_service_worker(
    dashboard: TestClient,
) -> None:
    manifest = dashboard.get("/manifest.webmanifest").json()
    assert manifest["short_name"] == "vinted-bot"
    assert manifest["id"] == "/"
    assert "isn't running" in dashboard.get("/offline").text
    assert "caches.match" in dashboard.get("/sw.js").text


# --- The choices the installers used to ask --------------------------------------------------


def test_settings_offers_login_start_and_keeping_the_mac_awake(
    dashboard: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    switched: list[bool] = []
    monkeypatch.setattr(control, "starts_at_login", lambda *_, **__: True)
    monkeypatch.setattr(control, "set_starts_at_login", lambda _, on, **__: switched.append(on))
    monkeypatch.setattr("vinted_bot.engine.awake.available", lambda *_: True)
    monkeypatch.setattr("vinted_bot.web.core.in_container", lambda: False)

    page = dashboard.get("/settings").text
    assert 'data-setting="start_at_login" checked' in page
    assert 'data-setting="keep_awake"' in page

    assert dashboard.post("/settings", data={"key": "start_at_login", "value": "0"}).json() == {
        "ok": True
    }
    assert switched == [False]
    dashboard.post("/settings", data={"key": "keep_awake", "value": "0"})
    assert 'data-setting="keep_awake" checked' not in dashboard.get("/settings").text


def test_without_an_installer_service_there_is_no_login_switch(dashboard: TestClient) -> None:
    assert 'data-setting="start_at_login"' not in dashboard.get("/settings").text


async def test_keeping_awake_follows_the_old_launch_agent(
    tmp_path: Path, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Someone who said no to keeping the Mac awake keeps that answer after updating."""
    from vinted_bot.engine import awake  # noqa: PLC0415

    monkeypatch.setattr(control, "upgrade_service", lambda _: False)
    settings = _settings(tmp_path, supervised="launchd")

    await app._upgrade_service(settings, repo)

    assert await awake.wanted(repo, settings) is False


async def test_a_new_install_keeps_the_mac_awake_by_default(tmp_path: Path, repo: Repo) -> None:
    from vinted_bot.engine import awake  # noqa: PLC0415

    assert await awake.wanted(repo, _settings(tmp_path, supervised="launchd")) is True
    assert await awake.wanted(repo, _settings(tmp_path)) is False, "not when run by hand"


async def test_telegram_dashboard_in_docker_points_at_the_public_address_setting(
    tmp_path: Path, repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("vinted_bot.botctl.telegram_bot.in_container", lambda: True)

    text = await dashboard_text(repo, _settings(tmp_path, web_host="0.0.0.0"))

    assert "VINTED_BOT_WEB_PUBLIC_URL" in text
    assert "Open on your phone" not in text


def test_update_advice_from_a_terminal_sees_the_installers_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Typed in a terminal, VINTED_BOT_SUPERVISED isn't set, but the service restarts it."""
    monkeypatch.setattr(control, "installed_service", lambda _: control.Service.LAUNCHD)

    assert cli._install(_settings(tmp_path)).supervisor == "launchd"


async def test_no_new_version_notice_while_update_checks_are_off(
    tmp_path: Path, repo: Repo
) -> None:
    from vinted_bot.engine import self_update  # noqa: PLC0415

    sent: list[str] = []

    async def notify(message: str) -> None:
        sent.append(message)

    await repo.set_latest_version("99.0.0")
    await repo.set_update_check(False)

    await self_update.announce_new_version(
        repo, self_update.detect(_settings(tmp_path)), _settings(tmp_path), notify
    )

    assert sent == []
