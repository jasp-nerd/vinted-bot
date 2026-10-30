"""The dashboard's fourth round of fixes: what four testers of 2.1 ran into.

Grouped by page. Each test pins one thing a tester saw go wrong (or one thing they could
not do from the dashboard at all), so it stays fixed.
"""

from __future__ import annotations

import asyncio
import html
import json
import re
import time
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from tests.conftest import ScriptedTransport
from tests.integration import test_web as web
from tests.integration.test_web import SEARCH_URL, Outgoing, _found, _item, _search, _state_of
from vinted_bot.config import Settings
from vinted_bot.db.repo import Query, RejectedListing, RejectionRecord, Repo, Watch
from vinted_bot.engine import self_update
from vinted_bot.engine.validation import InvalidInputError
from vinted_bot.vinted.client import PER_PAGE, VintedClient
from vinted_bot.web import core, destinations, security, support, views
from vinted_bot.web.routes import api, watchlist

WEB = Path(core.__file__).parent

# The dashboard fixtures of test_web.py, shared rather than copied.
client = web.client
make_client = web.make_client
outgoing = web.outgoing
vinted = web.vinted


async def _destination(repo: Repo, kind: str = "ntfy", **config: Any) -> int:
    return await repo.add_destination(kind=kind, name="Phone", config=config or {"topic": "t1"})


# --- Windows -----------------------------------------------------------------------------


def test_nothing_in_the_dashboard_uses_a_date_format_windows_refuses() -> None:
    """strftime's "%-d" is glibc's; on Windows it raises, and the page answers 500."""
    offenders = [
        f"{path.relative_to(WEB)}:{number}"
        for path in WEB.rglob("*")
        if path.suffix in {".py", ".html"}
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"%-[A-Za-z]", line)
    ]

    assert offenders == []


def test_a_day_is_written_without_a_leading_zero() -> None:
    assert views.day_month(datetime(2026, 3, 7, tzinfo=ZoneInfo("UTC"))) == "7 Mar"


def test_a_time_on_another_day_says_the_day() -> None:
    moment = int(datetime(2026, 3, 7, 14, 5, tzinfo=ZoneInfo("UTC")).timestamp())

    assert views.clock(moment, ZoneInfo("UTC")) == "7 Mar 14:05"


async def test_the_pages_with_dates_render(client: TestClient, repo: Repo) -> None:
    """Stats, a blocked seller in Settings and an old check on a search's page."""
    query_id = await _search(repo)
    await repo.block_seller(99, login="spammer", tld="fr")
    long_ago = int(datetime(2026, 1, 5, tzinfo=ZoneInfo("UTC")).timestamp())
    await repo.record_success(
        query_id, newest_raw_ts=long_ago, newest_item_ts=long_ago, seen=1, stale_cycles=0
    )
    statuses = [client.get(p).status_code for p in ("/stats", "/settings", f"/searches/{query_id}")]

    assert statuses == [200, 200, 200]


# --- Alerts: status alerts, options, the sample, pairing ---------------------------------


async def test_status_alerts_can_be_switched_on_from_the_card(
    client: TestClient, repo: Repo
) -> None:
    destination_id = await _destination(repo)

    client.post(
        f"/destinations/{destination_id}/options",
        data={"tiers": ["steal", "deal", "normal"], "notify_status": "1"},
    )

    assert await repo.status_destination_ids() == [destination_id]


async def test_status_alerts_can_be_switched_off_again(client: TestClient, repo: Repo) -> None:
    destination_id = await repo.add_destination(
        kind="ntfy", name="Phone", config={"topic": "t1"}, notify_status=True
    )

    client.post(f"/destinations/{destination_id}/options", data={"tiers": ["steal"]})

    assert await repo.status_destination_ids() == []


async def test_a_place_added_on_the_alerts_page_hears_about_problems(
    client: TestClient, repo: Repo
) -> None:
    client.post("/destinations", data={"kind": "ntfy", "ntfy_topic": "mags-abc"})

    assert len(await repo.status_destination_ids()) == 1


async def test_the_card_explains_status_alerts(client: TestClient, repo: Repo) -> None:
    await _destination(repo)

    assert "Tell me when something stops working" in client.get("/alerts").text


async def test_a_telegram_chat_still_pairing_offers_no_test(client: TestClient, repo: Repo) -> None:
    await repo.add_destination(kind="telegram", name="Telegram", config={"pairing_code": "x"})

    assert "data-test-dest" not in client.get("/alerts").text


async def test_a_telegram_chat_still_pairing_does_not_count_as_a_place(
    client: TestClient, repo: Repo
) -> None:
    await _found(repo, await _search(repo), _item(1))
    await repo.add_destination(kind="telegram", name="Telegram", config={"pairing_code": "x"})

    assert "Finds only show on this page for now." in client.get("/").text


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("123456789012", "<@&123456789012>"),
        ("<@&123456789012>", "<@&123456789012>"),
        ("<@123456789012>", "<@123456789012>"),
        ("<@!123456789012>", "<@123456789012>"),
        ("user:123456789012", "<@123456789012>"),
        ("@here", "@here"),
    ],
)
def test_a_discord_mention_keeps_a_person_a_person(typed: str, stored: str) -> None:
    assert destinations.discord_mention(typed) == stored


def _options(kind: str, config: dict[str, Any], **form: Any) -> dict[str, Any]:
    return destinations.options(kind, {"tiers": ["steal", "deal", "normal"], **form}, config)


def test_discord_thread_name_and_picture_are_kept() -> None:
    config = _options(
        "discord",
        {"url": "u"},
        thread_id="42",
        username="Mags",
        avatar_url="https://x.test/a.png",
        silent="1",
    )

    assert [config[k] for k in ("thread_id", "username", "avatar_url", "silent")] == [
        "42",
        "Mags",
        "https://x.test/a.png",
        True,
    ]


def test_a_thread_id_must_be_a_number() -> None:
    with pytest.raises(InvalidInputError, match="number"):
        _options("discord", {"url": "u"}, thread_id="general")


def test_an_ntfy_server_and_token_can_be_set() -> None:
    config = _options("ntfy", {"topic": "t1"}, server="https://ntfy.example/", ntfy_token="tk_1")

    assert (config["server"], config["token"], config["topic"]) == (
        "https://ntfy.example",
        "tk_1",
        "t1",
    )


def test_an_empty_token_field_keeps_the_token() -> None:
    assert _options("ntfy", {"topic": "t1", "token": "tk_1"})["token"] == "tk_1"


def test_a_token_can_be_removed() -> None:
    assert "token" not in _options("ntfy", {"topic": "t1", "token": "tk_1"}, clear_ntfy_token="1")


def test_an_ntfy_place_stored_as_a_url_keeps_its_topic() -> None:
    config = _options("ntfy", {"url": "https://ntfy.sh/mags-1"})

    assert (config["topic"], "url" in config, "server" in config) == ("mags-1", False, False)


def test_ntfys_lowest_priority_is_accepted() -> None:
    assert _options("ntfy", {"topic": "t1"}, priority="1")["priority"] == 1


def test_webhook_headers_are_read_one_per_line() -> None:
    config = _options("webhook", {"url": "https://x.test"}, headers="X-Key: abc\nAuth: Bearer 1")

    assert config["headers"] == {"X-Key": "abc", "Auth": "Bearer 1"}


def test_a_header_without_a_value_is_refused() -> None:
    with pytest.raises(InvalidInputError, match="Name: value"):
        _options("webhook", {"url": "https://x.test"}, headers="X-Key")


def test_watch_alerts_can_be_turned_off_for_a_place() -> None:
    assert _options("ntfy", {"topic": "t1"})["watch_alerts"] is False


async def test_watch_alerts_show_as_on_by_default(client: TestClient, repo: Repo) -> None:
    await _destination(repo)

    assert re.search(r'name="watch_alerts" value="1" checked', client.get("/alerts").text)


async def test_an_old_deal_threshold_shows_as_the_tiers_it_amounts_to(
    client: TestClient, repo: Repo
) -> None:
    await _destination(repo, topic="t1", min_deal_pct=30)

    page = client.get("/alerts").text

    assert (re.search(r'value="normal" checked', page), "30% or more" in page) == (None, True)


def test_saving_the_tiers_replaces_the_old_deal_threshold() -> None:
    assert "min_deal_pct" not in _options("ntfy", {"topic": "t1", "min_deal_pct": 30})


async def test_a_paused_place_says_why_and_until_when(client: TestClient, repo: Repo) -> None:
    destination_id = await _destination(repo)
    await repo.pause_destination(
        destination_id, until=int(time.time()) + 3600, reason="ntfy.sh's daily limit is used up"
    )

    page = client.get("/alerts").text

    assert ("Paused until" in page, "daily limit is used up" in page) == (True, True)


async def test_the_sample_alert_shows_the_buttons_an_alert_has(
    client: TestClient, repo: Repo
) -> None:
    destination_id = await _destination(repo, "discord", url="https://discord.com/api/webhooks/1/a")

    sample = client.get(f"/destinations/{destination_id}/preview").text

    assert ("Open on Vinted" in sample, "<script" in sample) == (True, False)


async def test_the_telegram_sample_keeps_no_links_or_scripts(
    client: TestClient, repo: Repo
) -> None:
    destination_id = await _destination(repo, "telegram", chat_id="1")

    sample = client.get(f"/destinations/{destination_id}/preview").text

    assert ("Levi" in sample, "<a " in sample) == (True, False)


# --- Searches ----------------------------------------------------------------------------


async def test_saving_a_duplicated_search_starts_it(client: TestClient, repo: Repo) -> None:
    query_id = await _search(repo)
    edit = client.post(f"/searches/{query_id}/duplicate")
    copy = (await repo.list_queries())[-1]
    assert 'name="resume" value="1"' in edit.text

    client.post(
        f"/searches/{copy.id}",
        data={"link": f"{SEARCH_URL}&copy=1", "resume": "1", "interval": "60"},
    )

    stored = await repo.get_query(copy.id)
    assert stored is not None and not stored.paused


async def test_saving_a_paused_search_keeps_it_paused(client: TestClient, repo: Repo) -> None:
    query_id = await _search(repo)
    await repo.set_paused(query_id, True)

    client.post(f"/searches/{query_id}", data={"link": SEARCH_URL, "interval": "60"})

    stored = await repo.get_query(query_id)
    assert stored is not None and stored.paused


async def test_a_link_already_watched_points_to_its_search(client: TestClient, repo: Repo) -> None:
    client.post("/searches", data={"link": SEARCH_URL, "interval": "60"})
    (query,) = await repo.list_queries()
    query_id = query.id

    page = client.post("/searches", data={"link": SEARCH_URL, "interval": "60"})

    assert (
        page.status_code,
        'id="err-link"' in page.text,
        f'href="/searches/{query_id}"' in page.text,
    ) == (
        400,
        True,
        True,
    )


async def test_a_brand_picked_once_keeps_its_name(client: TestClient, repo: Repo) -> None:
    client.post(
        "/searches",
        data={
            "tld": "fr",
            "search_text": "jeans",
            "brand_ids": "10",
            "labels": json.dumps({"brand:10": "Levi's"}),
            "interval": "60",
        },
    )
    query = (await repo.list_queries())[-1]

    assert "Levi&#39;s" in client.get(f"/searches/{query.id}/edit").text


def test_a_single_brand_is_named_from_its_results() -> None:
    found = [_item(i, brand="Levi's") for i in range(3)]

    assert api.brand_names({"brand_ids": "10"}, found) == {"10": "Levi's"}


def test_several_brands_are_never_guessed() -> None:
    found = [_item(1, brand="Levi's"), _item(2, brand="Lee")]

    assert api.brand_names({"brand_ids": "10,11"}, found) == {}


async def test_the_editor_knows_every_sites_currency(client: TestClient) -> None:
    page = client.get("/searches/new").text

    raw = re.search(r'data-currencies="([^"]+)"', page)
    assert raw is not None and json.loads(html.unescape(raw.group(1)))["co.uk"] == "£"


async def test_a_full_first_page_is_called_at_least(
    make_client: Callable[..., TestClient],
    vinted: VintedClient,
    transport: ScriptedTransport,
    make_item: Callable[..., dict[str, Any]],
) -> None:
    dashboard = make_client(client=vinted)
    transport.queue_catalog([make_item(i, photo_ts=int(time.time())) for i in range(PER_PAGE)])

    answer = dashboard.post(
        "/api/preview", data={"tld": "fr", "link": "vinted.fr/catalog?search_text=nike"}
    ).json()

    assert (answer["count"], answer["page_full"]) == (PER_PAGE, True)


def _query(**fields: Any) -> Query:
    base: dict[str, Any] = {
        "id": 1,
        "name": "Jeans",
        "url": SEARCH_URL,
        "tld": "nl",
        "params": {"search_text": "jeans"},
        "poll_interval_s": 60,
        "paused": False,
    }
    return Query(**{**base, **fields})


@pytest.mark.parametrize(
    ("fields", "words"),
    [
        ({"regex": r"\b50[15]\b"}, r"title pattern \b50[15]\b"),
        ({"seller_min_reviews": 10}, "seller with 10+ reviews"),
        ({"skip_unrated_sellers": True}, "no brand-new sellers"),
        ({"quiet_start": "23:00", "quiet_end": "07:00"}, "quiet 23:00 to 07:00"),
    ],
)
def test_a_search_summary_names_every_rule(fields: dict[str, Any], words: str) -> None:
    assert words in views.search_summary(_query(**fields))


def _rejection(reason: str, detail: str, total: str = "21.50") -> RejectionRecord:
    return RejectionRecord(
        id=1,
        query_id=1,
        item_id=1,
        reason=reason,
        detail=detail,
        title="Jeans",
        total_price=Decimal(total),
        currency="PLN",
        photo_url=None,
        url=None,
        created_at=0,
    )


def test_too_expensive_says_both_prices_in_the_sites_money() -> None:
    record = _rejection("over_budget", "21.50 above limit 20")

    assert views.rejection_detail(record, _query(max_total_price=Decimal(20))) == (
        "21.50 zł with fees, over your limit of 20.00 zł"
    )


def test_a_listing_above_the_typical_price_is_called_above_it() -> None:
    record = _rejection("not_a_deal", "-11% under the typical 19.60, want 20%")

    assert views.rejection_detail(record, _query(deal_only_pct=20)) == (
        "11% above the typical 19.60 zł; this search wants 20% under"
    )


async def test_why_a_listing_was_not_sent_is_on_the_page_not_in_a_tooltip(
    client: TestClient, repo: Repo
) -> None:
    query_id = await _search(repo, max_total_price=Decimal(20))
    query = await repo.get_query(query_id)
    assert query is not None
    await repo.record_new_items(
        query,
        [],
        [],
        rejected=[RejectedListing(_item(5, total="25.00"), "over_budget", "25.00 above limit 20")],
    )

    page = client.get(f"/searches/{query_id}").text

    assert "€25.00 with fees, over your limit of €20.00" in page


def test_new_reasons_for_not_sending_have_words() -> None:
    assert {"too_old", "no_exchange_rate"} <= set(views.REJECTION_WORDS)


# --- Finds -------------------------------------------------------------------------------


async def test_hidden_finds_can_be_found_again(client: TestClient, repo: Repo) -> None:
    await _found(repo, await _search(repo), _item(1, title="Hidden jacket"), _item(2))
    await repo.set_onboarded(True)
    await repo.set_mark(1, "hidden")

    page = client.get("/?show=hidden").text

    assert ("Hidden jacket" in page, "Nike Air Max" in page) == (True, False)


async def test_the_hidden_chip_appears_once_something_is_hidden(
    client: TestClient, repo: Repo
) -> None:
    await _found(repo, await _search(repo), _item(1), _item(2))
    before = 'value="hidden"' in client.get("/").text
    await repo.set_mark(1, "hidden")

    assert (before, 'value="hidden"' in client.get("/").text) == (False, True)


async def test_with_every_search_paused_finds_do_not_promise_new_ones(
    client: TestClient, repo: Repo
) -> None:
    query_id = await _search(repo)
    await _found(repo, query_id, _item(1))
    await repo.set_paused(query_id, True)

    page = client.get("/").text

    assert ("appear here on their own" in page, "Every search is paused" in page) == (
        False,
        True,
    )


async def test_no_support_card_in_the_first_hour_after_setup(repo: Repo) -> None:
    now = int(time.time())
    await repo.record_support_card_shown(0, 0)
    await support.note_setup(repo, now - 600)

    assert await support.card_on_visit(repo, now) is None


# --- Watchlist ---------------------------------------------------------------------------


async def test_a_watch_added_by_link_sends_only_where_ticked(
    client: TestClient, repo: Repo
) -> None:
    phone = await _destination(repo)
    await _destination(repo, topic="t2")

    client.post("/watchlist", data={"url": "vinted.fr/items/123-jeans", "dest": str(phone)})

    (watch,) = await repo.list_watches()
    assert await repo.destination_ids_for_watch(watch.id) == [phone]


async def test_where_a_watch_sends_can_be_changed(client: TestClient, repo: Repo) -> None:
    phone = await _destination(repo)
    other = await _destination(repo, topic="t2")
    watch_id = await repo.add_watch(kind="seller", tld="fr", target_id=7, label="s7")

    client.post(f"/watchlist/{watch_id}/routes", data={"dest": str(other)})

    assert (await repo.destination_ids_for_watch(watch_id), phone != other) == ([other], True)


async def test_a_watched_find_is_named_after_its_title(client: TestClient, repo: Repo) -> None:
    await _found(repo, await _search(repo), _item(123, title="Blue rain jacket"))

    client.post("/watchlist", data={"url": "vinted.fr/items/123"})

    assert [w.label for w in await repo.list_watches()] == ["Blue rain jacket"]


def _watch(price: str | None) -> Watch:
    return Watch(
        id=1,
        kind="item",
        tld="fr",
        target_id=1,
        label="x",
        last_price=Decimal(price) if price else None,
        currency="EUR",
        last_status="available",
        last_checked_at=1,
        next_check_at=1,
        last_error=None,
        active=True,
        created_at=1,
    )


def test_a_watch_whose_price_has_not_moved_shows_the_total_with_fees() -> None:
    found = _item(1, total="19.60")  # item price 17.60

    assert watchlist.watch_price(_watch("17.60"), found) == ("€19.60", "incl. fees")


def test_a_watch_whose_price_moved_says_it_is_the_item_price() -> None:
    found = _item(1, total="19.60")

    assert watchlist.watch_price(_watch("15.00"), found) == ("€15.00", "item price, before fees")


# --- Setup -------------------------------------------------------------------------------


def _through_search(dashboard: TestClient, **extra: Any) -> str:
    page = dashboard.post(
        "/welcome/search",
        data={
            "state": json.dumps({"tld": "fr"}),
            "submitted": "1",
            "mode": "paste",
            "link": SEARCH_URL,
            **extra,
        },
    )
    return _state_of(page.text)


def _through_test(dashboard: TestClient, topic: str = "mags-abc") -> Any:
    return dashboard.post(
        "/welcome/alerts",
        data={
            "state": _through_search(dashboard),
            "submitted": "1",
            "kind": "ntfy",
            "ntfy_topic": topic,
        },
    )


def test_reloading_the_test_result_sends_nothing_more(
    client: TestClient, outgoing: Outgoing
) -> None:
    _through_test(client)
    sent = len(outgoing.requests)

    page = client.get("/welcome/test")

    assert (page.status_code, "Did it arrive?" in page.text, len(outgoing.requests)) == (
        200,
        True,
        sent,
    )


@pytest.mark.parametrize("path", ["/welcome/test", "/welcome/finish", "/welcome/skip"])
def test_a_setup_address_opened_on_its_own_never_answers_method_not_allowed(
    client: TestClient, path: str
) -> None:
    assert client.get(path).status_code == 200


def test_the_last_step_never_says_search_none(client: TestClient) -> None:
    page = client.get("/welcome/ready")

    assert (page.status_code, "None" in page.text) == (200, False)


def test_the_last_step_shows_the_search_after_a_reload(client: TestClient) -> None:
    _through_test(client)
    client.post("/welcome/test", data={"next": "ready"})

    assert "&#34;nike&#34;" in client.get("/welcome/ready").text


def test_skip_for_now_does_not_promise_a_test(client: TestClient) -> None:
    _through_search(client)

    page = client.get("/welcome/alerts").text

    assert 'data-cta-skip="Continue"' in page


async def test_running_setup_again_reuses_the_same_search_and_phone(
    client: TestClient, repo: Repo
) -> None:
    for _ in range(2):
        _through_test(client)
        client.post("/welcome/test", data={"next": "ready"})
        client.post("/welcome/finish", data={})

    counts = (len(await repo.list_queries()), len(await repo.list_destinations()))
    assert counts == (1, 1)


async def test_setup_again_offers_the_phone_name_already_in_use(
    client: TestClient, repo: Repo
) -> None:
    await repo.add_destination(kind="ntfy", name="Phone", config={"topic": "mags-old"})
    client.get("/alerts")  # used to swap the name setup offers
    _through_search(client)

    assert "data-ntfy-topic>mags-old<" in client.get("/welcome/alerts").text


async def test_setups_place_hears_when_something_stops_working(
    client: TestClient, repo: Repo
) -> None:
    _through_test(client)

    assert len(await repo.status_destination_ids()) == 1


async def test_setup_can_keep_to_sellers_in_the_country(client: TestClient, repo: Repo) -> None:
    state = _through_search(client, countries="FR")
    client.post("/welcome/alerts", data={"state": state, "submitted": "1", "kind": "skip"})

    (query,) = await repo.list_queries()
    assert query.countries == ["FR"]


def test_setup_offers_the_local_sellers_switch(client: TestClient) -> None:
    page = client.post("/welcome/search", data={"state": "{}", "tld": "nl"}).text

    assert "Only sellers in Netherlands" in page


def test_setup_offers_your_own_app_under_more_options(client: TestClient) -> None:
    _through_search(client)

    assert 'value="webhook"' in client.get("/welcome/alerts").text


# --- Docker and NAS ----------------------------------------------------------------------


@pytest.fixture
def in_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "in_container", lambda: True)


@pytest.mark.usefixtures("in_docker")
def test_settings_in_docker_never_say_only_this_computer(
    make_client: Callable[..., TestClient],
) -> None:
    page = make_client(web_host="0.0.0.0").get("/settings").text

    assert ("Only this computer can open" in page, "Only this computer again?" in page) == (
        False,
        False,
    )


@pytest.mark.usefixtures("in_docker")
def test_settings_in_docker_speak_to_nas_app_stores_too(
    make_client: Callable[..., TestClient],
) -> None:
    assert "NAS app store" in make_client(web_host="0.0.0.0").get("/settings").text


@pytest.mark.usefixtures("in_docker")
def test_the_ready_screen_in_docker_does_not_ask_to_keep_a_laptop_awake(
    make_client: Callable[..., TestClient],
) -> None:
    dashboard = make_client(web_host="0.0.0.0")
    _through_test(dashboard)
    dashboard.post("/welcome/test", data={"next": "ready"})

    assert "Keep your computer on" not in dashboard.get("/welcome/ready").text


async def test_the_docker_update_hint_does_not_assume_a_compose_folder(
    settings: Settings, repo: Repo
) -> None:
    install = self_update.Install(kind=self_update.InstallKind.DOCKER, supervisor=None)
    updater = self_update.Updater(settings, repo, asyncio.Event(), install)

    offer = core.update_offer(updater, "99.0.0")

    assert offer is not None and "NAS app store" in offer["hint"]


async def test_installing_updates_by_itself_shows_the_new_version(
    client: TestClient, repo: Repo
) -> None:
    await repo.set_onboarded(True)
    await repo.set_update_check(False)
    await repo.set_auto_update(True)
    await repo.set_latest_version("99.0.0")

    assert "Version 99.0.0 is out" in client.get("/settings").text


def test_the_unknown_address_page_says_compose_up_and_has_no_loop(
    make_client: Callable[..., TestClient],
) -> None:
    page = make_client(web_host="0.0.0.0").get("/", headers={"Host": "vinted.example:8000"})

    assert ("docker compose up -d" in page.text, "Back to your finds" in page.text) == (
        True,
        False,
    )
