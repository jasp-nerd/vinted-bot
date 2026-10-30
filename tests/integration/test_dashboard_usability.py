"""The dashboard's round-three fixes: what people saw go wrong, pinned so it stays fixed.

Kept apart from test_web.py so each file stays about one thing; this one is about pages
telling the truth (statuses, counts, prices) and setup never losing what someone did.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.integration.test_web import SEARCH_URL, Outgoing, _found, _item, _search, _state_of
from vinted_bot.config import Settings
from vinted_bot.db.repo import Query, Repo
from vinted_bot.deliver.preview import sample_notification
from vinted_bot.web import core, data, views
from vinted_bot.web.routes import stats
from vinted_bot.web.server import create_app

TEMPLATES = Path(core.__file__).parent / "templates"
SCRIPT = Path(core.__file__).parent / "static" / "js" / "app.js"


@pytest.fixture
def outgoing() -> Outgoing:
    return Outgoing()


@pytest.fixture
def make_client(
    tmp_path: Path, repo: Repo, outgoing: Outgoing
) -> Iterator[Callable[..., TestClient]]:
    opened: list[TestClient] = []

    def build(*, raise_errors: bool = True, settings: Settings | None = None) -> TestClient:
        settings = settings or Settings(
            _env_file=None,  # type: ignore[call-arg]
            db_path=tmp_path / "app.db",
            web_enabled=True,
            timezone="UTC",
        )
        http = httpx.AsyncClient(transport=httpx.MockTransport(outgoing.handler))
        client = TestClient(
            create_app(settings, repo, http=http),
            base_url="http://127.0.0.1",
            raise_server_exceptions=raise_errors,
        )
        client.__enter__()
        opened.append(client)
        return client

    yield build
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


async def _onboarded(repo: Repo) -> None:
    await repo.set_onboarded(True)


# --- Pages that used to break ------------------------------------------------------------


async def test_deleting_a_search_with_a_euro_sign_confirms_on_the_next_page(
    client: TestClient, repo: Repo
) -> None:
    query_id = await _search(repo, name="Denim under €35")

    page = client.post(f"/searches/{query_id}/delete")

    assert 'Deleted "Denim under €35".' in html.unescape(page.text)


async def test_a_crash_inside_a_page_shows_the_error_page(
    make_client: Callable[..., TestClient], repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _search(repo)

    async def broken(*_: Any, **__: Any) -> list[dict[str, Any]]:
        raise RuntimeError("boom")

    monkeypatch.setattr(data, "searches", broken)
    page = make_client(raise_errors=False).get("/searches")

    assert (page.status_code, "Something went wrong on our side" in page.text) == (500, True)


def test_every_icon_the_pages_use_is_in_the_sprite() -> None:
    sprite = (TEMPLATES / "partials" / "icons.svg").read_text()
    have = set(re.findall(r'id="i-([a-z0-9-]+)"', sprite))
    used: set[str] = set()
    for path in [*TEMPLATES.rglob("*.html"), SCRIPT]:
        text = path.read_text()
        used |= set(re.findall(r'icon\("([a-z0-9-]+)"', text))
        used |= set(re.findall(r"#i-([a-z0-9-]+)", text))
    used |= {icon for _, icon in views.REJECTION_WORDS.values()}

    assert sorted(used - have) == []


async def test_a_search_page_leaves_the_header_search_box_empty(
    client: TestClient, repo: Repo
) -> None:
    query_id = await _search(repo)

    page = client.get(f"/searches/{query_id}").text

    assert re.search(r'id="q" name="q"[^>]*value=""', page)


# --- Finds ---------------------------------------------------------------------------------


async def test_blocking_a_seller_takes_their_finds_off_the_feed(
    client: TestClient, repo: Repo
) -> None:
    query_id = await _search(repo)
    await _found(repo, query_id, _item(1, title="Jean Levis", seller_id=5))
    await _onboarded(repo)

    client.post("/api/items/1/block-seller")

    assert "Jean Levis" not in client.get("/").text


async def test_a_price_filter_with_letters_says_so_and_stays_off(
    client: TestClient, repo: Repo
) -> None:
    query_id = await _search(repo)
    await _found(repo, query_id, _item(1))
    await _onboarded(repo)

    page = client.get("/?min=abc").text

    assert ("Type a price like 35" in page, 'class="chip is-on' in page) == (True, False)


# --- Searches ------------------------------------------------------------------------------


async def test_resuming_everything_counts_only_the_paused_ones(
    client: TestClient, repo: Repo
) -> None:
    first, second = await _search(repo, name="a"), await _search(repo, name="b")
    await repo.set_paused(second, True)

    page = client.post(
        "/searches/bulk", data={"ids": [str(first), str(second)], "action": "resume"}
    )

    assert "Resumed 1 search." in page.text


def test_a_price_from_a_pasted_link_shows_in_the_summary() -> None:
    query = Query(
        id=1,
        name="raincoats",
        url="https://www.vinted.nl/catalog?search_text=regenjas&price_to=20",
        tld="nl",
        params={"search_text": "regenjas", "price_to": "20"},
        poll_interval_s=60,
        paused=False,
    )

    assert "item price up to €20.00" in views.search_summary(query)


def test_the_resale_rules_show_in_the_summary() -> None:
    query = Query(
        id=1,
        name="retro",
        url="https://www.vinted.de/catalog?search_text=trikot",
        tld="de",
        params={"search_text": "trikot"},
        poll_interval_s=60,
        paused=False,
        resale_price=Decimal(55),
        min_margin=Decimal(8),
    )

    assert "resells for €55.00, at least €8.00 left" in views.search_summary(query)


# --- Where alerts go -----------------------------------------------------------------------


async def test_a_place_that_never_sent_is_not_called_working(
    client: TestClient, repo: Repo
) -> None:
    await repo.add_destination(kind="ntfy", name="My phone", config={"topic": "mags-x"})

    page = client.get("/alerts").text

    assert ("Not tested yet" in page, "Working" in page) == (True, False)


async def test_telegram_without_a_bot_token_says_it_cannot_send(
    client: TestClient, repo: Repo
) -> None:
    await repo.add_destination(kind="telegram", name="Telegram", config={"chat_id": "42"})

    assert "Needs the bot token" in client.get("/alerts").text


async def test_a_test_that_arrived_shows_on_the_card(client: TestClient, repo: Repo) -> None:
    destination_id = await repo.add_destination(
        kind="ntfy", name="My phone", config={"topic": "mags-x"}
    )

    client.post(f"/destinations/{destination_id}/test")

    assert "Test arrived" in client.get("/alerts").text


async def test_a_test_that_failed_shows_on_the_card(
    client: TestClient, repo: Repo, outgoing: Outgoing
) -> None:
    outgoing.status = 500
    destination_id = await repo.add_destination(
        kind="ntfy", name="My phone", config={"topic": "mags-x"}
    )

    client.post(f"/destinations/{destination_id}/test")

    assert "Last test failed" in client.get("/alerts").text


async def test_a_search_marks_a_route_to_a_switched_off_place(
    client: TestClient, repo: Repo
) -> None:
    query_id = await _search(repo)
    destination_id = await repo.add_destination(
        kind="discord", name="Flip Club", config={"url": "https://discord.com/api/webhooks/1/a"}
    )
    await repo.set_routes(query_id, [destination_id])
    await repo.deactivate_destination(destination_id, "webhook deleted")

    assert "Flip Club (off)" in client.get("/searches").text


async def test_the_alerts_page_offers_the_same_ntfy_name_on_every_load(
    client: TestClient,
) -> None:
    first = re.findall(r"data-ntfy-topic>([^<]+)<", client.get("/alerts").text)

    assert first == re.findall(r"data-ntfy-topic>([^<]+)<", client.get("/alerts").text)


async def test_the_alerts_page_offers_a_new_ntfy_name_once_one_is_used(
    client: TestClient, repo: Repo
) -> None:
    (offered,) = re.findall(r"data-ntfy-topic>([^<]+)<", client.get("/alerts").text)
    await repo.add_destination(kind="ntfy", name="My phone", config={"topic": offered})

    assert re.findall(r"data-ntfy-topic>([^<]+)<", client.get("/alerts").text) != [offered]


# --- Stats ---------------------------------------------------------------------------------


async def test_stats_leave_out_removed_places(client: TestClient, repo: Repo) -> None:
    destination_id = await repo.add_destination(
        kind="ntfy", name="Old phone", config={"topic": "mags-x"}
    )
    client.post(f"/destinations/{destination_id}/delete")

    assert "Old phone" not in client.get("/stats").text


@pytest.mark.parametrize(
    ("total", "earlier", "expected"),
    [
        (300, 3, None),
        (500, 40, {"text": "More than 10 times", "up": True}),
        (30, 40, {"text": "-25%", "up": False}),
    ],
)
def test_the_change_against_the_period_before_stays_readable(
    total: int, earlier: int, expected: dict[str, Any] | None
) -> None:
    assert stats._change(total, earlier) == expected


# --- Setup ---------------------------------------------------------------------------------


def _to_alerts(client: TestClient) -> str:
    page = client.post(
        "/welcome/search",
        data={
            "state": json.dumps({"tld": "fr"}),
            "submitted": "1",
            "mode": "paste",
            "link": SEARCH_URL,
        },
    )
    return _state_of(page.text)


def test_the_setup_offers_the_same_ntfy_name_after_a_reload(client: TestClient) -> None:
    _to_alerts(client)
    first = re.findall(r"data-ntfy-topic>([^<]+)<", client.get("/welcome/alerts").text)

    assert first and first == re.findall(
        r"data-ntfy-topic>([^<]+)<", client.get("/welcome/alerts").text
    )


async def test_changing_the_place_in_setup_replaces_it(client: TestClient, repo: Repo) -> None:
    state = _to_alerts(client)
    page = client.post(
        "/welcome/alerts",
        data={"state": state, "submitted": "1", "kind": "ntfy", "ntfy_topic": "mags-one"},
    )
    client.post(
        "/welcome/alerts",
        data={
            "state": _state_of(page.text),
            "submitted": "1",
            "kind": "ntfy",
            "ntfy_topic": "mags-two",
        },
    )

    active = await repo.list_destinations(active_only=True)
    assert ([d.config["topic"] for d in active], len(await repo.list_queries())) == (
        ["mags-two"],
        1,
    )


async def test_skipping_after_a_failed_test_keeps_the_search_without_a_place(
    client: TestClient, repo: Repo, outgoing: Outgoing
) -> None:
    outgoing.status = 500
    page = client.post(
        "/welcome/alerts",
        data={"state": _to_alerts(client), "submitted": "1", "kind": "ntfy", "ntfy_topic": "x"},
    )

    client.post("/welcome/test", data={"state": _state_of(page.text), "next": "ready"})

    assert (len(await repo.list_queries()), await repo.list_destinations()) == (1, [])


# --- Time zone -----------------------------------------------------------------------------


async def test_the_browsers_time_zone_is_kept_when_none_was_set(
    make_client: Callable[..., TestClient], repo: Repo, tmp_path: Path
) -> None:
    """UTC here stands for "the computer's zone couldn't be read": nobody set it."""
    unread = Settings.model_construct(
        _fields_set={"db_path", "web_enabled"},
        db_path=tmp_path / "app.db",
        web_enabled=True,
        timezone="UTC",
    )
    client = make_client(settings=unread)

    client.post("/settings", data={"key": "timezone_guess", "value": "Europe/Amsterdam"})

    assert (await repo.app_settings(default_timezone="UTC")).timezone == "Europe/Amsterdam"


async def test_the_browsers_time_zone_never_replaces_a_chosen_one(
    client: TestClient, repo: Repo
) -> None:
    await repo.set_timezone("Europe/Paris")

    client.post("/settings", data={"key": "timezone_guess", "value": "Europe/Amsterdam"})

    assert (await repo.app_settings(default_timezone="UTC")).timezone == "Europe/Paris"


# --- The test alert ------------------------------------------------------------------------


def test_the_test_alert_speaks_the_sites_language() -> None:
    item = sample_notification(tld="nl").item

    assert (item.condition, item.title.endswith("(testmelding)")) == ("Heel goed", True)


def test_the_test_alert_is_an_ordinary_listing() -> None:
    notification = sample_notification(tld="nl")

    assert (notification.typical_price, notification.margin) == (None, None)
