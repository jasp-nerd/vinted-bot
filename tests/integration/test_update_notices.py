"""Getting people onto new versions: updating by itself on new installs, a status alert per
release, and a version check that scripts and AI agents can read."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import LOCAL_CLIENT
from vinted_bot import __version__, cli
from vinted_bot.config import Settings
from vinted_bot.db import Database, apply_pending
from vinted_bot.db.repo import Repo
from vinted_bot.engine import self_update
from vinted_bot.engine.self_update import Install, InstallKind
from vinted_bot.web.server import create_app

UNATTENDED = Install(kind=InstallKind.UV_TOOL, supervisor="launchd", tool=Path("/usr/bin/uv"))
BY_HAND = Install(kind=InstallKind.PIPX, supervisor=None, tool=Path("/usr/bin/pipx"))
DOCKER = Install(kind=InstallKind.DOCKER, supervisor=None)
NEWER = "99.0.0"


async def _add_search(repo: Repo) -> None:
    await repo.add_query(
        name="Nike",
        url="https://www.vinted.fr/catalog?search_text=nike",
        tld="fr",
        params={"search_text": "nike"},
        poll_interval_s=60,
    )


# --- Updating by itself -----------------------------------------------------------------


async def test_a_new_install_from_the_installers_updates_itself(
    repo: Repo, settings: Settings
) -> None:
    await self_update.default_for_new_install(repo, UNATTENDED, settings)

    assert (await repo.app_settings(default_timezone="UTC")).auto_update


async def test_an_existing_install_keeps_what_it_had(repo: Repo, settings: Settings) -> None:
    await _add_search(repo)

    await self_update.default_for_new_install(repo, UNATTENDED, settings)

    assert not (await repo.app_settings(default_timezone="UTC")).auto_update


async def test_switching_it_off_on_a_new_install_sticks(repo: Repo, settings: Settings) -> None:
    await repo.set_auto_update(False)

    await self_update.default_for_new_install(repo, UNATTENDED, settings)

    assert not (await repo.app_settings(default_timezone="UTC")).auto_update


async def test_a_copy_that_cannot_restart_itself_is_left_alone(
    repo: Repo, settings: Settings
) -> None:
    await self_update.default_for_new_install(repo, BY_HAND, settings)

    assert not (await repo.app_settings(default_timezone="UTC")).auto_update


# --- The status alert -------------------------------------------------------------------


class Notices:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def __call__(self, message: str) -> None:
        self.sent.append(message)


async def test_a_new_release_is_announced_once_with_how_to_install_it(
    repo: Repo, settings: Settings
) -> None:
    notices = Notices()
    await repo.set_latest_version(NEWER)

    await self_update.announce_new_version(repo, BY_HAND, settings, notices)
    await self_update.announce_new_version(repo, BY_HAND, settings, notices)

    assert len(notices.sent) == 1
    assert f"vinted-bot {NEWER} is out" in notices.sent[0]
    assert "Update now" in notices.sent[0]
    assert f"/releases/tag/v{NEWER}" in notices.sent[0]


@pytest.mark.parametrize(
    ("install", "auto", "says"),
    [
        (UNATTENDED, True, "installs itself tonight"),
        (UNATTENDED, False, "click Update now"),
        (DOCKER, False, "docker compose pull"),
    ],
)
async def test_the_alert_says_how_this_copy_gets_it(
    repo: Repo, settings: Settings, install: Install, auto: bool, says: str
) -> None:
    notices = Notices()
    await repo.set_latest_version(NEWER)
    await repo.set_auto_update(auto)

    await self_update.announce_new_version(repo, install, settings, notices)

    assert says in notices.sent[0]


async def test_nothing_is_announced_when_up_to_date(repo: Repo, settings: Settings) -> None:
    notices = Notices()
    await repo.set_latest_version(__version__)

    await self_update.announce_new_version(repo, BY_HAND, settings, notices)

    assert notices.sent == []


# --- For scripts and agents -------------------------------------------------------------


async def _behind(db_path: Path) -> None:
    async with Database(db_path) as db:
        await apply_pending(db)
        await Repo(db).set_latest_version(NEWER)


def test_version_says_when_a_newer_one_is_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Run as the CLI runs it: no event loop yet, so --version starts its own."""
    db_path = tmp_path / "app.db"
    asyncio.run(_behind(db_path))
    capsys.readouterr()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VINTED_BOT_DB_PATH", str(db_path))

    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--version"])

    printed = capsys.readouterr().out.splitlines()
    assert printed[0] == f"vinted-bot {__version__}"
    assert printed[1].startswith(f"Version {NEWER} is out.")


def test_version_alone_without_a_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VINTED_BOT_DB_PATH", str(tmp_path / "missing.db"))

    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--version"])

    assert capsys.readouterr().out == f"vinted-bot {__version__}\n"
    assert not (tmp_path / "missing.db").exists()


async def test_update_facts_for_the_health_endpoint(repo: Repo, settings: Settings) -> None:
    await repo.set_latest_version(NEWER)

    facts = await self_update.update_facts(repo, BY_HAND, settings)

    assert facts == {
        "version": __version__,
        "latest_version": NEWER,
        "update_available": True,
        "how_to_update": "Open the dashboard and click Update now.",
    }


def test_the_health_endpoint_says_when_a_newer_one_is_out(tmp_path: Path, repo: Repo) -> None:
    settings = Settings(_env_file=None, db_path=tmp_path / "app.db")  # type: ignore[call-arg]
    with TestClient(create_app(settings, repo), client=LOCAL_CLIENT) as client:
        client.portal.call(repo.set_latest_version, NEWER)  # type: ignore[union-attr]
        health = client.get("/api/health").json()

    assert health["version"] == __version__
    assert health["latest_version"] == NEWER
    assert health["update_available"] is True
    assert health["how_to_update"]
