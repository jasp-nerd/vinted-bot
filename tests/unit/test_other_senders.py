"""ntfy, the JSON webhook and Apprise."""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
from decimal import Decimal
from typing import Any

import apprise
import httpx
import pytest
from apprise.conversion import convert_between
from apprise.decorators import notify

from tests.unit.sending import Recorder, bare, fast_bucket, notification
from vinted_bot.deliver.apprise import AppriseSender, message, quiet_url
from vinted_bot.deliver.base import SenderConfigError
from vinted_bot.deliver.ntfy import NtfySender
from vinted_bot.deliver.render import view
from vinted_bot.deliver.webhook import WebhookSender

# --- ntfy ------------------------------------------------------------------------------


def ntfy(recorder: Recorder, **config: Any) -> NtfySender:
    return NtfySender({"topic": "deals", **config}, client=recorder.client(), bucket=fast_bucket())


async def test_ntfy_publishes_json_to_the_server_root() -> None:
    recorder = Recorder()

    await ntfy(recorder).send([notification(1)])

    assert (str(recorder.requests[0].url), recorder.payload()["topic"]) == (
        "https://ntfy.sh",
        "deals",
    )


async def test_ntfy_handles_accents_and_currency_signs() -> None:
    """Headers must be ASCII; a title like this used to fail before it was sent."""
    recorder = Recorder()

    result = await ntfy(recorder).send([notification(1, title="Très bon état", tld="fr")])

    assert result.delivered == [1]
    assert recorder.payload()["title"] == "16,45 £ · Très bon état"


async def test_the_ntfy_title_is_the_whole_decision_line() -> None:
    """The title is what the phone shows first: total, badge, margin, title."""
    recorder = Recorder()

    await ntfy(recorder).send([notification(1, typical_price=Decimal("40"), margin=Decimal("20"))])

    assert recorder.payload()["title"] == "£16.45 · Steal \u221259% · margin ~+£20 · Item 1"


async def test_ntfy_names_the_search_without_markdown_underscores() -> None:
    recorder = Recorder()

    await ntfy(recorder).send([notification(1)])

    last_line = recorder.payload()["message"].splitlines()[-1]
    assert "_" not in last_line


async def test_ntfy_shows_the_photo_and_opens_the_listing() -> None:
    recorder = Recorder()

    await ntfy(recorder).send([notification(1)])

    body = recorder.payload()
    assert (body["attach"], body["click"]) == (
        "https://images.vinted.net/1-0.jpeg",
        "https://www.vinted.co.uk/items/1",
    )


async def test_ntfy_offers_three_buttons_at_most() -> None:
    recorder = Recorder()

    await ntfy(recorder).send([notification(1)])

    assert [a["label"] for a in recorder.payload()["actions"]] == [
        "Buy",
        "Message seller",
        "Open on Vinted",
    ]


async def test_ntfy_sends_a_steal_at_top_priority() -> None:
    recorder = Recorder()

    await ntfy(recorder).send([notification(1, typical_price=Decimal("40"))])

    assert recorder.payload()["priority"] == 5


async def test_a_silenced_steal_does_not_buzz_on_ntfy() -> None:
    recorder = Recorder()

    await ntfy(recorder).send([notification(1, typical_price=Decimal("40"), silent=True)])

    assert recorder.payload()["priority"] == 2


async def test_ntfy_uses_the_configured_priority_otherwise() -> None:
    recorder = Recorder()

    await ntfy(recorder, priority=4).send([notification(1)])

    assert recorder.payload()["priority"] == 4


async def test_ntfy_accepts_a_full_topic_url() -> None:
    recorder = Recorder()

    await NtfySender(
        {"url": "https://push.example.net/alerts"}, client=recorder.client(), bucket=fast_bucket()
    ).send([notification(1)])

    assert (str(recorder.requests[0].url), recorder.payload()["topic"]) == (
        "https://push.example.net",
        "alerts",
    )


async def test_ntfy_sends_the_token_as_a_bearer() -> None:
    recorder = Recorder()

    await ntfy(recorder, token="tk_secret").send([notification(1)])

    assert recorder.requests[0].headers["authorization"] == "Bearer tk_secret"


async def test_ntfy_refusing_the_topic_switches_it_off() -> None:
    recorder = Recorder(httpx.Response(403))

    result = await ntfy(recorder).send([notification(1)])

    assert (result.permanent_error is not None, result.retry) == (True, [])


async def test_ntfy_says_when_a_status_notice_did_not_arrive() -> None:
    """It used to drop the answer, so a notice the server refused was counted as sent."""
    recorder = Recorder(httpx.Response(500))

    assert await ntfy(recorder).send_status("vinted.fr is down") == "ntfy answered 500"


async def test_ntfy_says_nothing_went_wrong_when_a_status_notice_arrived() -> None:
    assert await ntfy(Recorder()).send_status("vinted.fr is down") is None


async def test_ntfy_asking_to_slow_down_waits_a_minute() -> None:
    recorder = Recorder(httpx.Response(429))

    result = await ntfy(recorder).send([notification(1)])

    assert (result.retry, result.retry_after_s, result.pause_until) == ([1], 60.0, None)


async def test_ntfy_s_daily_limit_pauses_the_destination_until_midnight_utc() -> None:
    recorder = Recorder(
        httpx.Response(429, json={"code": 42908, "error": "limit reached: daily message quota"})
    )

    result = await ntfy(recorder).send([notification(1)])

    assert result.pause_until is not None and result.pause_until % 86_400 == 0
    assert result.error is not None and "daily message limit" in result.error


async def test_several_listings_waiting_together_go_out_as_one_ntfy_push() -> None:
    recorder = Recorder()

    result = await ntfy(recorder).send([notification(n) for n in (1, 2, 3, 4)])

    assert (len(recorder.requests), result.delivered) == (1, [1, 2, 3, 4])
    assert recorder.payload()["title"] == "4 new matches · my search"


async def test_a_couple_of_listings_still_get_a_push_each() -> None:
    recorder = Recorder()

    await ntfy(recorder).send([notification(1), notification(2)])

    assert len(recorder.requests) == 2


async def test_watch_alerts_keep_their_own_push_beside_a_digest() -> None:
    recorder = Recorder()
    batch = [notification(n) for n in (1, 2, 3)]
    batch.append(notification(4, kind="price_drop", previous_price=Decimal("20")))

    await ntfy(recorder).send(batch)

    assert len(recorder.requests) == 2


def test_ntfy_without_a_topic_is_a_configuration_error() -> None:
    with pytest.raises(SenderConfigError):
        NtfySender({})


# --- JSON webhook ------------------------------------------------------------------------


def hook(recorder: Recorder, **config: Any) -> WebhookSender:
    return WebhookSender(
        {"url": "https://example.test/hook", **config},
        client=recorder.client(),
        bucket=fast_bucket(),
    )


async def test_the_webhook_payload_is_version_two() -> None:
    recorder = Recorder()

    await hook(recorder).send([notification(1)])

    assert recorder.payload()["version"] == 2


async def test_the_webhook_keeps_every_version_one_field() -> None:
    recorder = Recorder()

    await hook(recorder).send([notification(1)])

    assert {
        "id",
        "site",
        "title",
        "url",
        "brand",
        "size",
        "condition",
        "price",
        "total_price",
        "currency",
        "photo_url",
        "listed_at",
        "seller",
        "seller_rating",
        "links",
    } <= set(recorder.payload()["items"][0])


async def test_the_webhook_carries_the_deal_and_the_gallery() -> None:
    recorder = Recorder()

    await hook(recorder).send([notification(1, typical_price=Decimal("30"))])

    item = recorder.payload()["items"][0]
    assert (item["deal_pct"], item["deal_tier"], item["typical_price"], len(item["photos"])) == (
        45,
        "steal",
        "30.00",
        6,
    )


async def test_the_webhook_names_an_ordinary_listing_s_tier() -> None:
    recorder = Recorder()

    await hook(recorder).send([notification(1, typical_price=Decimal("17"))])

    assert recorder.payload()["items"][0]["deal_tier"] == "normal"


async def test_the_webhook_carries_the_margin() -> None:
    recorder = Recorder()

    await hook(recorder).send([notification(1, margin=Decimal("19.1"))])

    assert recorder.payload()["items"][0]["margin"] == "19.10"


async def test_the_webhook_carries_the_previous_price_of_a_drop() -> None:
    recorder = Recorder()

    await hook(recorder).send([notification(1, kind="price_drop", previous_price=Decimal("20"))])

    item = recorder.payload()["items"][0]
    assert (item["kind"], item["previous_price"]) == ("price_drop", "20.00")


async def test_the_webhook_names_the_seller_s_country_when_a_lookup_found_it() -> None:
    recorder = Recorder()
    with_country = dataclasses.replace(notification(1), seller_country="BE")

    await hook(recorder).send([with_country])

    assert recorder.payload()["items"][0]["seller_profile"]["country"] == "BE"


async def test_a_silent_alert_says_so_in_the_webhook_payload() -> None:
    recorder = Recorder()

    await hook(recorder).send([notification(1, silent=True)])

    assert recorder.payload()["items"][0]["silent"] is True


async def test_webhook_prices_always_have_two_decimals() -> None:
    recorder = Recorder()

    await hook(recorder).send([bare(1)])

    assert recorder.payload()["items"][0]["price"] == "15.00"


async def test_webhook_listing_urls_are_absolute() -> None:
    recorder = Recorder()

    await hook(recorder).send([bare(1)])

    assert recorder.payload()["items"][0]["url"] == "https://www.vinted.fr/items/1-slug"


async def test_a_mixed_batch_is_split_so_each_post_names_its_own_search() -> None:
    recorder = Recorder()

    await hook(recorder).send(
        [
            notification(1, query_id=1, query_name="nike"),
            notification(2, query_id=2, query_name="levis"),
            notification(3, query_id=1, query_name="nike"),
        ]
    )

    assert [
        (recorder.payload(i)["search"], [item["id"] for item in recorder.payload(i)["items"]])
        for i in range(len(recorder.requests))
    ] == [("nike", [1, 3]), ("levis", [2])]


async def test_alerts_from_two_watches_are_posted_apart() -> None:
    """Watch alerts have no search; each POST still names the one watch it is about."""
    recorder = Recorder()

    await hook(recorder).send(
        [
            notification(1, query_id=None, watch_id=7, query_name="Barbour", kind="price_drop"),
            notification(2, query_id=None, watch_id=8, query_name="Good seller", kind="sold"),
        ]
    )

    assert [recorder.payload(i)["search"] for i in range(len(recorder.requests))] == [
        "Barbour",
        "Good seller",
    ]


async def test_a_secret_signs_the_body_and_timestamp() -> None:
    recorder = Recorder()

    await hook(recorder, secret="s3cret").send([notification(1)])

    request = recorder.requests[0]
    timestamp = request.headers["x-vinted-bot-timestamp"]
    expected = hmac.new(
        b"s3cret", timestamp.encode() + b"." + request.content, hashlib.sha256
    ).hexdigest()
    assert request.headers["x-vinted-bot-signature"] == f"sha256={expected}"


async def test_without_a_secret_nothing_is_signed() -> None:
    recorder = Recorder()

    await hook(recorder).send([notification(1)])

    assert "x-vinted-bot-signature" not in recorder.requests[0].headers


async def test_a_failed_second_search_keeps_the_first_delivered() -> None:
    recorder = Recorder(httpx.Response(200), httpx.Response(500))

    result = await hook(recorder).send([notification(1, query_id=1), notification(2, query_id=2)])

    assert (result.delivered, result.retry) == ([1], [2])


async def test_a_vanished_webhook_endpoint_is_switched_off() -> None:
    recorder = Recorder(httpx.Response(410))

    result = await hook(recorder).send([notification(1)])

    assert result.permanent_error is not None


# --- Apprise -----------------------------------------------------------------------------

# Apprise's own extension point: a made-up URL scheme handled in-process, so these tests
# run the real library end to end without any network.
_received: list[dict[str, Any]] = []
_answer = {"ok": True}


@notify(on="vstest")  # type: ignore[untyped-decorator,no-untyped-call]
def _capture(
    body: str, title: str, notify_type: str, *args: Any, attach: Any = None, **kwargs: Any
) -> bool:
    _received.append(
        {
            "title": title,
            "body": body,
            "type": notify_type,
            "attach": [a.url() for a in attach] if attach else [],
        }
    )
    return _answer["ok"]


@pytest.fixture(autouse=True)
def _fresh_capture() -> None:
    _received.clear()
    _answer["ok"] = True


async def test_apprise_sends_title_and_markdown_body() -> None:
    result = await AppriseSender({"urls": ["vstest://"]}).send([notification(1)])

    assert result.delivered == [1]
    assert _received[0]["title"] == "£16.45 · Item 1"


async def test_apprise_body_shows_the_margin() -> None:
    await AppriseSender({"urls": ["vstest://"]}).send([notification(1, margin=Decimal("5"))])

    assert "margin ~+£5" in _received[0]["body"]


async def test_apprise_body_links_the_listing() -> None:
    await AppriseSender({"urls": ["vstest://"]}).send([notification(1)])

    assert "**[Item 1](https://www.vinted.co.uk/items/1)**" in _received[0]["body"]


def test_an_email_body_keeps_its_links_in_the_plain_text_part() -> None:
    """Apprise's HTML-to-text conversion kept "Open on Vinted" and dropped the address."""
    _, body = message(view(notification(1), dashboard_url=None), links_written_out=True)

    # Apprise's own conversions, as its email plugin runs them.
    html = convert_between(apprise.NotifyFormat.MARKDOWN, apprise.NotifyFormat.HTML, body)  # type: ignore[no-untyped-call]
    text = convert_between(apprise.NotifyFormat.HTML, apprise.NotifyFormat.TEXT, html)  # type: ignore[no-untyped-call]

    assert "https://www.vinted.co.uk/items/1" in text


def test_other_services_keep_tidy_markdown_links() -> None:
    _, body = message(view(notification(1), dashboard_url=None))

    assert "](https://www.vinted.co.uk/items/1)" in body.splitlines()[-1]


async def test_apprise_attaches_the_cover_photo() -> None:
    await AppriseSender({"urls": ["vstest://"]}).send([notification(1)])

    assert _received[0]["attach"][0].startswith("https://images.vinted.net/1-0.jpeg")


async def test_apprise_failures_are_retried() -> None:
    _answer["ok"] = False

    result = await AppriseSender({"urls": "vstest://"}).send([notification(1), notification(2)])

    assert (result.delivered, result.retry) == ([], [1, 2])


async def test_apprise_status_notices_are_warnings() -> None:
    await AppriseSender({"urls": ["vstest://"]}).send_status("stale")

    assert _received[0]["type"] == apprise.NotifyType.WARNING


def test_apprise_without_urls_is_a_configuration_error() -> None:
    with pytest.raises(SenderConfigError):
        AppriseSender({"urls": []})


def test_an_unrecognised_apprise_url_is_reported_without_echoing_it() -> None:
    with pytest.raises(SenderConfigError) as raised:
        AppriseSender({"urls": ["vstest://", "nonsense://hunter2@host"]})

    assert "URL number 2" in str(raised.value) and "hunter2" not in str(raised.value)


async def test_ntfy_sends_plain_text_so_ios_shows_no_raw_markdown() -> None:
    """The iOS app does not render markdown; a seller's [link](...) stays inert text."""
    recorder = Recorder()

    await ntfy(recorder).send([notification(1, seller_login="[click](https://evil.test)")])

    assert "markdown" not in recorder.payload()


async def test_an_apprise_title_cannot_break_out_of_its_link() -> None:
    await AppriseSender({"urls": ["vstest://"]}).send(
        [notification(1, title="new] [free](https://evil.test")]
    )

    assert "](https://evil.test" not in _received[0]["body"]


async def test_an_apprise_title_cannot_inject_html_into_an_email() -> None:
    await AppriseSender({"urls": ["vstest://"]}).send(
        [notification(1, title='<img src="https://evil.test/pixel">')]
    )

    assert "<img" not in _received[0]["body"]


@pytest.mark.parametrize(
    ("url", "quiet"),
    [
        ("tgram://123:abc/456", "tgram://123:abc/456?silent=yes"),
        ("pover://user@token?priority=high", "pover://user@token?priority=low"),
        ("ntfys://ntfy.sh/topic?tags=x", "ntfys://ntfy.sh/topic?tags=x&priority=low"),
        ("mailtos://me:pw@gmail.com", "mailtos://me:pw@gmail.com"),
    ],
)
def test_a_silent_apprise_alert_asks_each_service_for_no_sound(url: str, quiet: str) -> None:
    assert quiet_url(url) == quiet


async def test_a_silent_apprise_alert_is_still_delivered() -> None:
    result = await AppriseSender({"urls": ["vstest://"]}).send([notification(1, silent=True)])

    assert (result.delivered, len(_received)) == ([1], 1)
