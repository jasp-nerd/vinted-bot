"""Usage statistics end to end: when they are sent, what is in them, and switching off.

Sent to an httpx mock, never to the network.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.conftest import LOCAL_CLIENT
from vinted_bot import __version__, telemetry
from vinted_bot.config import Settings
from vinted_bot.db.repo import Repo
from vinted_bot.engine.self_update import Install, InstallKind
from vinted_bot.telemetry import recorder
from vinted_bot.telemetry.service import (
    HEARTBEAT_EVERY_S,
    PROJECT_KEY,
    Telemetry,
    never_here,
    switched_on,
)
from vinted_bot.web.server import create_app

INSTALLED = Install(kind=InstallKind.UV_TOOL, supervisor="launchd")


class Ingest:
    """Stands in for the proxy in front of PostHog."""

    def __init__(self) -> None:
        self.batches: list[dict[str, Any]] = []
        self.status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.status >= 300:
            return httpx.Response(self.status)
        self.batches.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "Ok"})

    @property
    def events(self) -> list[dict[str, Any]]:
        return [event for batch in self.batches for event in batch["batch"]]

    def named(self, name: str) -> list[dict[str, Any]]:
        return [event for event in self.events if event["event"] == name]


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def ingest() -> Ingest:
    return Ingest()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def make_telemetry(
    settings: Settings, repo: Repo, ingest: Ingest, clock: Clock
) -> Callable[..., Telemetry]:
    def build(**overrides: Any) -> Telemetry:
        http = httpx.AsyncClient(transport=httpx.MockTransport(ingest.handler))
        return Telemetry(
            overrides.pop("settings", settings),
            repo,
            asyncio.Event(),
            http,
            overrides.pop("install", INSTALLED),
            environ=overrides.pop("environ", {}),
            clock=clock,
            **overrides,
        )

    return build


# --- When it is on ----------------------------------------------------------------------


def test_development_ci_and_tests_never_send(settings: Settings) -> None:
    source = Install(kind=InstallKind.SOURCE, supervisor=None)
    mock = settings.model_copy(update={"fetch_mode": "mock"})

    assert never_here(settings, source, {})
    assert never_here(mock, INSTALLED, {})
    assert never_here(settings, INSTALLED, {"CI": "true"})
    assert never_here(settings, INSTALLED, {"PYTEST_CURRENT_TEST": "x"})
    assert not never_here(settings, INSTALLED, {})


async def test_on_unless_switched_off_and_the_environment_wins(
    settings: Settings, repo: Repo
) -> None:
    assert await switched_on(settings, repo)

    await repo.set_state_value("telemetry", "0")
    assert not await switched_on(settings, repo)

    forced = Settings(_env_file=None, db_path=settings.db_path, telemetry=True)  # type: ignore[call-arg]
    assert await switched_on(forced, repo)


async def test_switched_off_sends_nothing(
    make_telemetry: Callable[..., Telemetry], repo: Repo, ingest: Ingest
) -> None:
    await repo.set_state_value("telemetry", "0")
    usage = make_telemetry()

    await usage.tick()
    telemetry.event("page_viewed", page="/")
    await usage.tick()

    assert ingest.batches == []


async def test_running_from_source_sends_nothing(
    make_telemetry: Callable[..., Telemetry], ingest: Ingest
) -> None:
    usage = make_telemetry(install=Install(kind=InstallKind.SOURCE, supervisor=None))

    await usage.tick()

    assert ingest.batches == []


# --- What is sent -----------------------------------------------------------------------


async def test_a_new_install_says_so_once_then_starts(
    make_telemetry: Callable[..., Telemetry], repo: Repo, ingest: Ingest
) -> None:
    await make_telemetry().tick()
    await make_telemetry().tick()

    assert len(ingest.named("app_installed")) == 1
    assert len(ingest.named("app_started")) == 2
    first = ingest.events[0]
    assert ingest.batches[0]["api_key"] == PROJECT_KEY
    assert first["distinct_id"] == await repo.get_state_value("telemetry_install_id")
    assert first["properties"]["$process_person_profile"] is False
    assert first["properties"]["$geoip_disable"] is True
    assert first["properties"]["version"] == __version__
    started = ingest.named("app_started")[0]["properties"]
    assert started["install"] == "uv-tool"
    assert started["searches"] == 0
    assert started["days_since_install"] == 0


async def test_an_existing_install_is_not_counted_as_new(
    make_telemetry: Callable[..., Telemetry], repo: Repo, ingest: Ingest
) -> None:
    await repo.add_query(
        name="Nike",
        url="https://www.vinted.fr/catalog?search_text=nike",
        tld="fr",
        params={"search_text": "nike"},
        poll_interval_s=60,
    )

    await make_telemetry().tick()

    assert ingest.named("app_installed") == []
    assert ingest.named("app_started")[0]["properties"]["days_since_install"] is None


async def test_searches_are_described_by_counts_never_their_contents(
    make_telemetry: Callable[..., Telemetry], repo: Repo, ingest: Ingest
) -> None:
    await repo.add_query(
        name="Secret hunt",
        url="https://www.vinted.fr/catalog?search_text=rare+jordan&brand_ids[]=53",
        tld="fr",
        params={"search_text": "rare jordan", "brand_ids": "53"},
        poll_interval_s=5,
    )

    await make_telemetry().tick()

    started = ingest.named("app_started")[0]["properties"]
    assert started["searches"] == 1
    assert started["intervals"] == {"5": 1}
    assert started["sites"] == ["fr"]
    assert "search_text" in started["params"]
    sent = json.dumps(ingest.batches)
    assert "rare" not in sent
    assert "jordan" not in sent
    assert "Secret hunt" not in sent


async def test_an_update_is_reported_with_both_versions(
    make_telemetry: Callable[..., Telemetry], repo: Repo, ingest: Ingest
) -> None:
    await repo.set_state_value("telemetry_version", "2.2.0")

    await make_telemetry().tick()

    updated = ingest.named("app_updated")
    assert updated[0]["properties"]["from_version"] == "2.2.0"
    assert updated[0]["properties"]["to_version"] == __version__


async def test_the_daily_heartbeat_carries_the_days_counts_and_survives_a_restart(
    make_telemetry: Callable[..., Telemetry], repo: Repo, ingest: Ingest, clock: Clock
) -> None:
    usage = make_telemetry()
    await usage.tick()
    telemetry.count("checks_ok", 5)
    await usage.shutdown()

    # A restart: the counts so far come back from the database.
    recorder.deactivate()
    clock.now += HEARTBEAT_EVERY_S
    usage = make_telemetry()
    await usage.tick()
    telemetry.count("checks_ok", 2)
    await usage.tick()

    heartbeats = ingest.named("app_heartbeat")
    assert len(heartbeats) == 1
    assert heartbeats[0]["properties"]["counters"]["checks_ok"] == 5
    assert heartbeats[0]["properties"]["period_s"] == HEARTBEAT_EVERY_S
    clock.now += HEARTBEAT_EVERY_S
    await usage.tick()
    assert ingest.named("app_heartbeat")[1]["properties"]["counters"]["checks_ok"] == 2


async def test_firsts_are_sent_once_with_the_time_since_installing(
    make_telemetry: Callable[..., Telemetry], ingest: Ingest, clock: Clock
) -> None:
    usage = make_telemetry()
    await usage.tick()
    clock.now += 90
    telemetry.milestone("first_alert", channel="telegram")
    await usage.tick()
    telemetry.milestone("first_alert", channel="telegram")
    await usage.tick()

    firsts = ingest.named("first_alert")
    assert len(firsts) == 1
    assert firsts[0]["properties"]["seconds_since_install"] == 90
    assert firsts[0]["properties"]["channel"] == "telegram"


async def test_a_failed_send_is_retried_later_and_a_refused_one_dropped(
    make_telemetry: Callable[..., Telemetry], ingest: Ingest, clock: Clock
) -> None:
    usage = make_telemetry()
    ingest.status = 503
    await usage.tick()
    assert ingest.batches == []

    ingest.status = 200
    await usage.tick()  # still waiting out the pause
    assert ingest.batches == []
    clock.now += 120
    await usage.tick()
    assert ingest.named("app_started")

    ingest.status = 400
    telemetry.event("page_viewed", page="/")
    await usage.tick()
    ingest.status = 200
    clock.now += 120
    await usage.tick()
    assert ingest.named("page_viewed") == []


async def test_switching_off_in_the_dashboard_stops_at_once(
    make_telemetry: Callable[..., Telemetry], repo: Repo, ingest: Ingest
) -> None:
    from vinted_bot.telemetry.service import set_switch  # noqa: PLC0415

    usage = make_telemetry()
    await usage.tick()
    sent = len(ingest.events)
    telemetry.event("page_viewed", page="/")

    await set_switch(repo, False)
    await usage.tick()
    telemetry.event("page_viewed", page="/")
    await usage.tick()

    assert len(ingest.events) == sent


# --- The dashboard ----------------------------------------------------------------------


@pytest.fixture
def dashboard(tmp_path: Path, repo: Repo) -> Iterator[TestClient]:
    settings = Settings(_env_file=None, db_path=tmp_path / "app.db", web_enabled=True)  # type: ignore[call-arg]
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    with TestClient(create_app(settings, repo, http=http), client=LOCAL_CLIENT) as client:
        recorder.activate()
        yield client


def test_pages_and_actions_are_recorded_by_route_only(dashboard: TestClient) -> None:
    dashboard.get("/searches", headers={"user-agent": "Mozilla/5.0 (iPhone) Mobile"})
    dashboard.post("/settings", data={"key": "theme", "value": "dark"})
    dashboard.get("/api/health")

    events = recorder.take_events()

    assert [(e.name, e.properties.get("page") or e.properties.get("feature")) for e in events] == [
        ("page_viewed", "/searches"),
        ("feature_used", "/settings"),
    ]
    assert events[0].properties["screen"] == "phone"


def test_outside_links_are_recorded_by_name(dashboard: TestClient) -> None:
    dashboard.post("/api/out", content="kofi:settings")
    dashboard.post("/api/out", content="https://evil.example:anything")

    events = recorder.take_events()

    assert [(e.name, e.properties) for e in events] == [
        ("link_opened", {"link": "kofi", "place": "settings"})
    ]


def test_the_settings_page_has_a_switch_that_saves(dashboard: TestClient, repo: Repo) -> None:
    page = dashboard.get("/settings").text
    assert 'data-setting="telemetry"' in page
    assert "telemetry.md" in page

    saved = dashboard.post("/settings", data={"key": "telemetry", "value": "0"})

    assert saved.json() == {"ok": True}
    assert not recorder.is_active()
    assert 'data-setting="telemetry" checked' not in dashboard.get("/settings").text


def test_deal_badges_can_be_switched_off_for_the_whole_dashboard(
    dashboard: TestClient, repo: Repo
) -> None:
    assert 'data-deal-badges="off"' not in dashboard.get("/settings").text

    saved = dashboard.post("/settings", data={"key": "deal_badges", "value": "0"})

    assert saved.json() == {"ok": True}
    page = dashboard.get("/settings").text
    assert 'data-deal-badges="off"' in page
    assert 'data-setting="deal_badges" checked' not in page


def test_settings_show_one_section_at_a_time_with_support_under_each(
    dashboard: TestClient,
) -> None:
    page = dashboard.get("/settings").text

    assert '<div class="settings" data-tabs>' in page
    assert 'href="#support"' not in page
    assert page.index('class="settings__support"') > page.index('id="about"')


async def test_switching_off_and_on_again_before_a_send_records_again(
    make_telemetry: Callable[..., Telemetry], repo: Repo
) -> None:
    from vinted_bot.telemetry.service import set_switch  # noqa: PLC0415

    usage = make_telemetry()
    await usage.tick()
    await set_switch(repo, False)
    await set_switch(repo, True)

    await usage.tick()

    assert recorder.is_active()


async def test_filter_names_from_a_pasted_link_are_only_vinteds_own(
    make_telemetry: Callable[..., Telemetry], repo: Repo, ingest: Ingest
) -> None:
    await repo.add_query(
        name="x",
        url="https://www.vinted.fr/catalog?search_text=a&my_secret_hunt=1",
        tld="fr",
        params={"search_text": "a", "my_secret_hunt": "1"},
        poll_interval_s=60,
    )

    await make_telemetry().tick()

    params = ingest.named("app_started")[0]["properties"]["params"]
    assert params == {"search_text": 1, "other": 1}
