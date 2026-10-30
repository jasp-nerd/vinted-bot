"""The dashboard's side of updating: what the banner offers, and the button behind it."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from vinted_bot import __version__
from vinted_bot.config import Settings
from vinted_bot.db.repo import Repo
from vinted_bot.engine.self_update import Install, InstallKind, Updater
from vinted_bot.web.server import create_app

BASE = "http://127.0.0.1"
NEWER = "99.0.0"


@pytest.fixture(autouse=True)
async def onboarded(repo: Repo) -> None:
    """Past the welcome steps, which have no banners."""
    await repo.set_onboarded(True)


@pytest.fixture
def dashboard(tmp_path: Path, repo: Repo) -> Iterator[Callable[[Install], TestClient]]:
    opened: list[tuple[TestClient, Updater]] = []

    def build(install: Install) -> TestClient:
        settings = Settings(_env_file=None, db_path=tmp_path / "app.db")  # type: ignore[call-arg]
        updater = Updater(settings, repo, asyncio.Event(), install, restart_grace_s=0)
        http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
        client = TestClient(create_app(settings, repo, http=http, updater=updater), base_url=BASE)
        client.__enter__()
        opened.append((client, updater))
        return client

    yield build
    for client, updater in opened:
        # An update started by a test runs on the client's own loop; let it finish there.
        client.portal.call(updater.settle)  # type: ignore[union-attr]
        client.__exit__(None, None, None)


def uv_install(tmp_path: Path, **kwargs: Any) -> Install:
    """A uv tool install whose uv refuses to run, so nothing really upgrades."""
    uv = tmp_path / "uv"
    uv.write_text("#!/bin/sh\nexit 1\n")
    uv.chmod(0o755)
    return Install(kind=InstallKind.UV_TOOL, tool=uv, **({"supervisor": "launchd"} | kwargs))


@pytest.fixture
async def released(repo: Repo) -> Repo:
    await repo.set_latest_version(NEWER)
    return repo


async def test_the_banner_offers_the_button_where_it_can_update_itself(
    tmp_path: Path, dashboard: Callable[[Install], TestClient], released: Repo
) -> None:
    page = dashboard(uv_install(tmp_path)).get("/").text

    assert "data-update-now" in page


async def test_the_banner_links_the_release_notes(
    tmp_path: Path, dashboard: Callable[[Install], TestClient], released: Repo
) -> None:
    page = dashboard(uv_install(tmp_path)).get("/").text

    assert f"https://github.com/jasp-nerd/vinted-bot/releases/tag/v{NEWER}" in page


async def test_docker_gets_the_command_instead_of_the_button(
    dashboard: Callable[[Install], TestClient], released: Repo
) -> None:
    page = dashboard(Install(kind=InstallKind.DOCKER, supervisor=None)).get("/").text

    assert (
        "data-update-now" in page,
        "docker compose pull &amp;&amp; docker compose up -d" in page,
    ) == (
        False,
        True,
    )


async def test_a_source_checkout_is_told_to_pull(
    dashboard: Callable[[Install], TestClient], released: Repo
) -> None:
    page = dashboard(Install(kind=InstallKind.SOURCE, supervisor=None)).get("/").text

    assert "git pull &amp;&amp; uv sync" in page


async def test_no_banner_when_up_to_date(
    tmp_path: Path, dashboard: Callable[[Install], TestClient], repo: Repo
) -> None:
    await repo.set_latest_version(__version__)

    page = dashboard(uv_install(tmp_path)).get("/").text

    assert "data-update=" not in page


async def test_the_button_is_refused_from_another_site(
    tmp_path: Path, dashboard: Callable[[Install], TestClient], released: Repo
) -> None:
    client = dashboard(uv_install(tmp_path))

    response = client.post("/api/update", headers={"Origin": "https://evil.example"})

    assert response.status_code == 403


async def test_the_button_starts_an_update(
    tmp_path: Path, dashboard: Callable[[Install], TestClient], released: Repo
) -> None:
    client = dashboard(uv_install(tmp_path))

    response = client.post("/api/update", headers={"Origin": BASE})

    assert (response.status_code, response.json()["phase"]) == (202, "upgrading")


async def test_the_status_reports_a_failed_upgrade_in_plain_words(
    tmp_path: Path, dashboard: Callable[[Install], TestClient], released: Repo
) -> None:
    client = dashboard(uv_install(tmp_path))
    client.post("/api/update", headers={"Origin": BASE})

    status = client.get("/api/update").json()
    for _ in range(100):
        if status["phase"] != "upgrading":
            break
        await asyncio.sleep(0.05)  # the update runs on the client's own loop and thread
        status = client.get("/api/update").json()

    assert (status["phase"], "keeps running" in status["message"]) == ("failed", True)


async def test_nothing_newer_is_a_clear_refusal(
    tmp_path: Path, dashboard: Callable[[Install], TestClient], repo: Repo
) -> None:
    client = dashboard(uv_install(tmp_path))

    response = client.post("/api/update", headers={"Origin": BASE})

    assert (response.status_code, response.json()["error"]) == (
        409,
        "There's no newer release to install.",
    )


async def test_automatic_updates_can_be_switched_on_where_they_work(
    tmp_path: Path, dashboard: Callable[[Install], TestClient], repo: Repo
) -> None:
    client = dashboard(uv_install(tmp_path))

    client.post("/settings", data={"key": "auto_update", "value": "1"}, headers={"Origin": BASE})

    assert (await repo.app_settings(default_timezone="UTC")).auto_update


async def test_automatic_updates_are_refused_without_a_supervisor(
    tmp_path: Path, dashboard: Callable[[Install], TestClient], repo: Repo
) -> None:
    client = dashboard(uv_install(tmp_path, supervisor=None))

    response = client.post(
        "/settings", data={"key": "auto_update", "value": "1"}, headers={"Origin": BASE}
    )

    assert (
        response.status_code,
        (await repo.app_settings(default_timezone="UTC")).auto_update,
    ) == (
        400,
        False,
    )


async def test_the_settings_page_offers_automatic_updates_only_where_they_work(
    tmp_path: Path, dashboard: Callable[[Install], TestClient], repo: Repo
) -> None:
    supervised = dashboard(uv_install(tmp_path)).get("/settings").text
    docker = dashboard(Install(kind=InstallKind.DOCKER, supervisor=None)).get("/settings").text

    assert ('data-setting="auto_update"' in supervised, 'data-setting="auto_update"' in docker) == (
        True,
        False,
    )
