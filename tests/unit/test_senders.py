"""What we actually send, and what we do when the platform pushes back."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from vinted_sniper.db.repo import PendingNotification
from vinted_sniper.deliver.ratelimit import Gate, TokenBucket
from vinted_sniper.deliver.telegram import TelegramSender
from vinted_sniper.vinted.models import Item


def notification(item_id: int, **kwargs: Any) -> PendingNotification:
    defaults: dict[str, Any] = {
        "item_id": item_id,
        "tld": "fr",
        "title": f"Item {item_id}",
        "url": f"https://www.vinted.fr/items/{item_id}",
        "price": Decimal("15.00"),
        "total_price": Decimal("16.45"),
        "currency": "EUR",
        "brand": "Nike",
        "size": "M",
        "condition": "Very good",
        "photo_url": f"https://images.vinted.net/{item_id}.jpeg",
        "photo_ts": 1_760_000_000,
        "seller_login": "sneakerfan",
        "seller_id": 12_345_678,
        "seller_rating": 0.96,
        "seller_feedback_count": 128,
    }
    defaults.update(kwargs)
    return PendingNotification(
        outbox_id=item_id,
        destination_id=1,
        query_id=1,
        query_name="my search",
        attempts=0,
        item=Item(**defaults),
        detected_at=1_760_000_100,
    )


class Recorder:
    """Captures requests and replays scripted responses."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.requests: list[httpx.Request] = []
        self._responses = list(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._responses:
            return self._responses.pop(0)
        return httpx.Response(204)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def payload(self, index: int = 0) -> Any:
        return json.loads(self.requests[index].content)


def fast_bucket() -> TokenBucket:
    """A bucket that never actually waits, so tests do not either."""
    return TokenBucket(1000.0, capacity=1000.0)


# --- Telegram ----------------------------------------------------------------------


async def test_telegram_sends_one_message_per_listing_with_a_photo_preview() -> None:
    recorder = Recorder(*[httpx.Response(200, json={"ok": True})] * 2)
    sender = TelegramSender(
        {"chat_id": "123"}, bot_token="t", client=recorder.client(), bucket=fast_bucket()
    )

    result = await sender.send([notification(1), notification(2)])

    assert result.delivered == [1, 2]
    payload = recorder.payload(0)
    assert payload["parse_mode"] == "HTML"
    assert payload["link_preview_options"]["prefer_large_media"] is True
    assert payload["reply_markup"]["inline_keyboard"][0][0]["url"].endswith("/items/1")


@pytest.mark.parametrize(
    "title",
    [
        "Nike Air Max 90 (2023) — 100% authentic!",
        "T-shirt <script>alert(1)</script>",
        "Vintage & rare • size M",
        "Levi's 501 W32/L34 [new]",
    ],
)
async def test_hostile_titles_do_not_break_the_message(title: str) -> None:
    recorder = Recorder(httpx.Response(200, json={"ok": True}))
    sender = TelegramSender(
        {"chat_id": "123"}, bot_token="t", client=recorder.client(), bucket=fast_bucket()
    )

    result = await sender.send([notification(1, title=title)])

    assert result.delivered == [1]
    text = recorder.payload()["text"]
    assert "<script>" not in text
    assert "&lt;" in text or "<b>" in text


async def test_a_burst_collapses_into_a_digest() -> None:
    recorder = Recorder(*[httpx.Response(200, json={"ok": True})] * 6)
    sender = TelegramSender(
        {"chat_id": "123"}, bot_token="t", client=recorder.client(), bucket=fast_bucket()
    )

    result = await sender.send([notification(i) for i in range(1, 9)])

    assert len(result.delivered) == 8
    assert len(recorder.requests) == 6, "five listings, then one digest for the rest"
    assert "3 more matches" in recorder.payload(5)["text"]


async def test_a_blocked_bot_stops_being_retried() -> None:
    recorder = Recorder(
        httpx.Response(
            403,
            json={"ok": False, "description": "Forbidden: bot was blocked by the user"},
        )
    )
    sender = TelegramSender(
        {"chat_id": "123"}, bot_token="t", client=recorder.client(), bucket=fast_bucket()
    )

    result = await sender.send([notification(1)])

    assert result.permanent_error is not None
    assert result.retry == []


async def test_telegram_rate_limits_are_honoured_exactly() -> None:
    recorder = Recorder(
        httpx.Response(
            429,
            json={
                "ok": False,
                "description": "Too Many Requests",
                "parameters": {"retry_after": 7},
            },
        )
    )
    sender = TelegramSender(
        {"chat_id": "123"}, bot_token="t", client=recorder.client(), bucket=fast_bucket()
    )

    result = await sender.send([notification(1)])

    assert result.retry_after_s == 7.0
    assert result.retry == [1]


async def test_forum_topics_are_supported() -> None:
    recorder = Recorder(httpx.Response(200, json={"ok": True}))
    sender = TelegramSender(
        {"chat_id": "-100123", "message_thread_id": "42"},
        bot_token="t",
        client=recorder.client(),
        bucket=fast_bucket(),
    )

    await sender.send([notification(1)])

    assert recorder.payload()["message_thread_id"] == "42"


# --- Pacing ------------------------------------------------------------------------


async def test_the_bucket_spaces_requests_out() -> None:
    clock = {"now": 0.0}
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock["now"] += seconds

    bucket = TokenBucket(2.0, capacity=1.0, clock=lambda: clock["now"], sleep=sleep)

    await bucket.acquire()
    await bucket.acquire()
    await bucket.acquire()

    assert slept, "a burst past the capacity has to wait"
    assert sum(slept) == pytest.approx(1.0, abs=0.01), "two per second means half a second each"


def test_a_closed_gate_reopens_on_its_own() -> None:
    clock = {"now": 100.0}
    gate = Gate(clock=lambda: clock["now"])

    assert gate.wait_s == 0.0
    gate.close_for(5.0)
    assert gate.wait_s == pytest.approx(5.0)

    clock["now"] += 5.1
    assert gate.wait_s == 0.0
