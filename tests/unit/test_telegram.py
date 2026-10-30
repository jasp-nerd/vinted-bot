"""What we send to Telegram, and how it steps down when Telegram cannot take it."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest

from tests.unit.sending import Recorder, bare, fast_bucket, notification, telegram_length
from vinted_sniper.deliver.base import SenderConfigError
from vinted_sniper.deliver.render import MINUS
from vinted_sniper.deliver.telegram import TelegramSender

OK = httpx.Response(200, json={"ok": True})


def sender(
    recorder: Recorder, *, dashboard_url: str | None = None, **config: Any
) -> TelegramSender:
    return TelegramSender(
        {"chat_id": "123", **config},
        bot_token="t",
        dashboard_url=dashboard_url,
        client=recorder.client(),
        bucket=fast_bucket(),
    )


def bad_request(description: str) -> httpx.Response:
    return httpx.Response(400, json={"ok": False, "error_code": 400, "description": description})


# --- The photo card -----------------------------------------------------------------


async def test_a_listing_is_sent_as_a_photo_with_a_caption() -> None:
    recorder = Recorder()

    result = await sender(recorder).send([notification(1)])

    assert result.delivered == [1]
    assert recorder.method() == "sendPhoto"
    assert recorder.payload()["photo"] == "https://images.vinted.net/1-0.jpeg"


async def test_the_caption_leads_with_the_total_price() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1)])

    assert recorder.payload()["caption"].startswith("<b>£16.45</b>")


async def test_the_caption_shows_a_deal_badge() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1, typical_price=Decimal("25.00"))])

    assert f"<i>Good deal {MINUS}34% vs typical</i>" in recorder.payload()["caption"]


async def test_the_listing_time_is_relative_and_rendered_by_the_app() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1)])

    assert '<tg-time unix="1760000000" format="r">' in recorder.payload()["caption"]


async def test_a_price_drop_strikes_through_the_old_price() -> None:
    recorder = Recorder()

    await sender(recorder).send(
        [notification(1, kind="price_drop", previous_price=Decimal("25.00"))]
    )

    caption = recorder.payload()["caption"]
    assert caption.startswith("<b>Price drop</b>") and "<s>£25.00</s>" in caption


async def test_buy_is_green_and_open_is_blue() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1)])

    rows = recorder.payload()["reply_markup"]["inline_keyboard"]
    assert [(b["text"], b.get("style")) for row in rows for b in row] == [
        ("Buy", "success"),
        ("Message seller", None),
        ("Open on Vinted", "primary"),
    ]


async def test_a_public_dashboard_adds_a_button() -> None:
    recorder = Recorder()

    await sender(recorder, dashboard_url="https://sniper.example.net").send([notification(1)])

    second_row = recorder.payload()["reply_markup"]["inline_keyboard"][1]
    assert second_row[1]["url"] == "https://sniper.example.net/searches/1"


async def test_every_button_is_an_https_link() -> None:
    recorder = Recorder()

    await sender(recorder, dashboard_url="https://sniper.example.net").send([bare(1)])

    rows = recorder.payload()["reply_markup"]["inline_keyboard"]
    assert all(button["url"].startswith("https://") for row in rows for button in row)


@pytest.mark.parametrize(
    "title",
    [
        "Nike Air Max 90 (2023) — 100% authentic!",
        "T-shirt <script>alert(1)</script>",
        "Vintage & rare • size M",
        "@everyone <b>bold</b> #hashtag",
    ],
)
async def test_hostile_titles_are_escaped(title: str) -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1, title=title, seller_login="<i>me</i>")])

    caption = recorder.payload()["caption"]
    assert "<script>" not in caption and "<i>me</i>" not in caption


async def test_a_caption_never_exceeds_telegram_s_limit() -> None:
    recorder = Recorder()
    huge = "é" * 500

    await sender(recorder).send(
        [
            notification(
                1,
                title=huge,
                brand=huge,
                size=huge,
                condition=huge,
                seller_login=huge,
                query_name=huge,
                typical_price=Decimal("90"),
            )
        ]
    )

    assert telegram_length(recorder.payload()["caption"]) <= 1024


async def test_a_bare_listing_still_gets_a_photo_card() -> None:
    recorder = Recorder()

    await sender(recorder).send([bare(1)])

    assert recorder.payload()["caption"].splitlines()[:2] == [
        "<b>15,00 €</b>",
        '<b><a href="https://www.vinted.fr/items/1-slug">Item 1</a></b>',
    ]


async def test_a_listing_without_a_photo_goes_as_text() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1, photo_url=None, photo_urls=())])

    assert recorder.method() == "sendMessage"


# --- Options --------------------------------------------------------------------------


async def test_a_silent_destination_never_buzzes() -> None:
    recorder = Recorder()

    await sender(recorder, silent=True).send([notification(1)])

    assert recorder.payload()["disable_notification"] is True


async def test_a_quiet_hours_listing_arrives_silently() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1, silent=True)])

    assert recorder.payload()["disable_notification"] is True


async def test_a_normal_listing_is_not_silenced() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1)])

    assert "disable_notification" not in recorder.payload()


@pytest.mark.parametrize("key", ["message_thread_id", "thread_id"])
async def test_forum_topics_are_supported(key: str) -> None:
    recorder = Recorder()

    await sender(recorder, chat_id="-100123", **{key: "42"}).send([notification(1)])

    assert recorder.payload()["message_thread_id"] == "42"


async def test_an_unknown_style_is_a_configuration_error() -> None:
    with pytest.raises(SenderConfigError):
        sender(Recorder(), style="carousel")


async def test_compact_style_uses_the_photo_as_a_link_preview() -> None:
    recorder = Recorder()

    await sender(recorder, style="compact").send([notification(1)])

    assert recorder.payload()["link_preview_options"]["url"] == "https://images.vinted.net/1-0.jpeg"


# --- Gallery and its fallbacks ----------------------------------------------------------


async def test_gallery_style_sends_a_rich_message_with_a_slideshow() -> None:
    recorder = Recorder()

    await sender(recorder, style="gallery").send([notification(1)])

    assert recorder.method() == "sendRichMessage"
    assert recorder.payload()["rich_message"]["html"].startswith("<tg-slideshow><img ")


async def test_the_gallery_keeps_title_hashtags_as_text() -> None:
    recorder = Recorder()

    await sender(recorder, style="gallery").send([notification(1, title="Top #vintage")])

    assert recorder.payload()["rich_message"]["skip_entity_detection"] is True


async def test_a_refused_rich_message_is_resent_as_a_photo() -> None:
    recorder = Recorder(httpx.Response(404, json={"ok": False, "description": "Not Found"}))

    result = await sender(recorder, style="gallery").send([notification(1)])

    assert result.delivered == [1]
    assert recorder.method(1) == "sendPhoto"


async def test_after_one_refusal_the_gallery_is_not_tried_again() -> None:
    recorder = Recorder(httpx.Response(404, json={"ok": False, "description": "Not Found"}))
    telegram = sender(recorder, style="gallery")
    await telegram.send([notification(1)])

    await telegram.send([notification(2)])

    assert recorder.method(2) == "sendPhoto"


async def test_a_photo_telegram_cannot_fetch_falls_back_to_a_preview() -> None:
    recorder = Recorder(bad_request("Bad Request: failed to get HTTP URL content"))

    result = await sender(recorder).send([notification(1)])

    assert result.delivered == [1]
    assert recorder.method(1) == "sendMessage"


async def test_a_malformed_caption_is_not_retried_as_text() -> None:
    recorder = Recorder(bad_request("Bad Request: can't parse entities"))

    result = await sender(recorder).send([notification(1)])

    assert (len(recorder.requests), result.delivered, result.retry) == (1, [], [])


# --- Bursts ----------------------------------------------------------------------------


async def test_a_burst_in_a_private_chat_collapses_after_five() -> None:
    recorder = Recorder()

    result = await sender(recorder).send([notification(i) for i in range(1, 9)])

    assert len(result.delivered) == 8
    assert len(recorder.requests) == 6, "five listings, then one digest for the rest"


async def test_a_group_digests_sooner() -> None:
    """Groups get twenty messages a minute, so individual alerts stop at three."""
    recorder = Recorder()

    await sender(recorder, chat_id="-100123").send([notification(i) for i in range(1, 9)])

    assert len(recorder.requests) == 4


async def test_the_digest_is_price_first() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(i) for i in range(1, 9)])

    lines = recorder.payload(5)["text"].splitlines()
    assert lines[0] == "<b>3 new matches</b> · my search"
    assert lines[2].startswith("<b>£16.45</b> · <a href=")


async def test_the_digest_previews_the_best_deal() -> None:
    recorder = Recorder()
    batch = [notification(i) for i in range(1, 7)] + [
        notification(7, typical_price=Decimal("40")),
        notification(8),
    ]

    await sender(recorder).send(batch)

    assert (
        recorder.payload(5)["link_preview_options"]["url"] == "https://images.vinted.net/7-0.jpeg"
    )


async def test_the_digest_fits_one_message() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(i, title="t" * 500) for i in range(1, 11)])

    assert telegram_length(recorder.payload(5)["text"]) <= 4096


# --- Status and errors -------------------------------------------------------------------


async def test_a_status_notice_is_escaped() -> None:
    recorder = Recorder()

    await sender(recorder).send_status("search <nike> is failing")

    assert "&lt;nike&gt;" in recorder.payload()["text"]


async def test_a_status_notice_is_heard() -> None:
    recorder = Recorder()

    await sender(recorder).send_status("vinted.fr is blocking requests")

    assert "disable_notification" not in recorder.payload()


async def test_a_blocked_bot_stops_being_retried() -> None:
    recorder = Recorder(
        httpx.Response(
            403, json={"ok": False, "description": "Forbidden: bot was blocked by the user"}
        )
    )

    result = await sender(recorder).send([notification(1)])

    assert (result.permanent_error is not None, result.retry) == (True, [])


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

    result = await sender(recorder).send([notification(1)])

    assert (result.retry_after_s, result.retry) == (7.0, [1])


async def test_an_unreadable_reply_is_retried() -> None:
    recorder = Recorder(httpx.Response(502, text="<html>bad gateway</html>"))

    result = await sender(recorder).send([notification(1)])

    assert result.retry == [1]
