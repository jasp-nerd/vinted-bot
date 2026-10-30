"""ntfy, the JSON webhook and Apprise."""

from __future__ import annotations

import hashlib
import hmac
import sys
from decimal import Decimal
from typing import Any

import apprise
import httpx
import pytest
from apprise.decorators import notify

from tests.unit.sending import Recorder, bare, fast_bucket, notification
from vinted_sniper.deliver.apprise import AppriseSender
from vinted_sniper.deliver.base import SenderConfigError
from vinted_sniper.deliver.ntfy import NtfySender
from vinted_sniper.deliver.webhook import WebhookSender

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


async def test_ntfy_out_of_allowance_waits_a_minute() -> None:
    recorder = Recorder(httpx.Response(429))

    result = await ntfy(recorder).send([notification(1)])

    assert (result.retry, result.retry_after_s) == ([1], 60.0)


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


async def test_the_webhook_carries_the_previous_price_of_a_drop() -> None:
    recorder = Recorder()

    await hook(recorder).send([notification(1, kind="price_drop", previous_price=Decimal("20"))])

    item = recorder.payload()["items"][0]
    assert (item["kind"], item["previous_price"]) == ("price_drop", "20.00")


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


async def test_a_secret_signs_the_body_and_timestamp() -> None:
    recorder = Recorder()

    await hook(recorder, secret="s3cret").send([notification(1)])

    request = recorder.requests[0]
    timestamp = request.headers["x-vinted-sniper-timestamp"]
    expected = hmac.new(
        b"s3cret", timestamp.encode() + b"." + request.content, hashlib.sha256
    ).hexdigest()
    assert request.headers["x-vinted-sniper-signature"] == f"sha256={expected}"


async def test_without_a_secret_nothing_is_signed() -> None:
    recorder = Recorder()

    await hook(recorder).send([notification(1)])

    assert "x-vinted-sniper-signature" not in recorder.requests[0].headers


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


async def test_apprise_body_links_the_listing() -> None:
    await AppriseSender({"urls": ["vstest://"]}).send([notification(1)])

    assert "**[Item 1](https://www.vinted.co.uk/items/1)**" in _received[0]["body"]


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


def test_a_missing_apprise_extra_says_how_to_install_it(monkeypatch: pytest.MonkeyPatch) -> None:
    # None in sys.modules is how Python spells "this import fails".
    monkeypatch.setitem(sys.modules, "apprise", None)

    with pytest.raises(SenderConfigError, match=r"vinted-sniper\[apprise\]"):
        AppriseSender({"urls": ["vstest://"]})


async def test_ntfy_markdown_cannot_be_hijacked_by_a_seller_login() -> None:
    recorder = Recorder()

    await ntfy(recorder).send([notification(1, seller_login="[click](https://evil.test)")])

    assert "](https://evil.test)" not in recorder.payload()["message"]


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
