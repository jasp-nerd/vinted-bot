"""What we post to Discord, and what we do when Discord pushes back."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest

from tests.unit.sending import (
    Recorder,
    bare,
    cv2_problems,
    embed_problems,
    fast_bucket,
    notification,
)
from vinted_sniper.deliver.base import SenderConfigError
from vinted_sniper.deliver.discord import DiscordSender
from vinted_sniper.deliver.render import MINUS

HOOK = "https://discord.test/hook"


def sender(recorder: Recorder, *, dashboard_url: str | None = None, **config: Any) -> DiscordSender:
    return DiscordSender(
        {"url": HOOK, **config},
        dashboard_url=dashboard_url,
        client=recorder.client(),
        bucket=fast_bucket(),
    )


def all_text(payload: dict[str, Any]) -> str:
    """Every text display in a Components V2 payload, joined."""
    found: list[str] = []

    def walk(component: dict[str, Any]) -> None:
        if component["type"] == 10:
            found.append(component["content"])
        for child in component.get("components", []):
            walk(child)

    for component in payload["components"]:
        walk(component)
    return "\n".join(found)


def buttons(payload: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(component: dict[str, Any]) -> None:
        if component["type"] == 2:
            found.append(component)
        for child in component.get("components", []):
            walk(child)

    for component in payload["components"]:
        walk(component)
    return found


def rejected_components() -> httpx.Response:
    return httpx.Response(
        400,
        json={
            "code": 50035,
            "errors": {"components": {"0": {"_errors": [{"code": "UNION_TYPE_CHOICES"}]}}},
            "message": "Invalid Form Body",
        },
    )


# --- The card ------------------------------------------------------------------------


async def test_a_listing_goes_out_as_a_components_v2_card() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1)])

    assert cv2_problems(recorder.payload()) == []


async def test_components_are_switched_on_in_the_webhook_url() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1)])

    assert recorder.requests[0].url.params["with_components"] == "true"


async def test_the_card_names_the_app_and_its_icon() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1)])

    payload = recorder.payload()
    assert (payload["username"], payload["avatar_url"]) == (
        "vinted-sniper",
        "https://raw.githubusercontent.com/jasp-nerd/vinted-sniper/main/docs/media/icon-256.png",
    )


async def test_the_destination_can_rename_the_poster() -> None:
    recorder = Recorder()

    await sender(recorder, username="Deals", avatar_url="https://x.test/a.png").send(
        [notification(1)]
    )

    assert recorder.payload()["username"] == "Deals"


async def test_the_gallery_shows_four_photos_at_most() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1)])

    gallery = next(c for c in recorder.payload()["components"][0]["components"] if c["type"] == 12)
    assert len(gallery["items"]) == 4


async def test_the_total_price_is_the_big_number() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1)])

    assert "# £16.45\n-# £15.00 + buyer protection" in all_text(recorder.payload())


async def test_a_deal_is_badged_against_the_typical_price() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1, typical_price=Decimal("30.00"))])

    assert f"`Steal {MINUS}45% vs typical`" in all_text(recorder.payload())


async def test_a_deal_paints_the_accent_green() -> None:
    recorder = Recorder()

    await sender(recorder).send(
        [notification(1, typical_price=Decimal("30.00"), query_color="#3366ff")]
    )

    assert recorder.payload()["components"][0]["accent_color"] == 0x28865A


async def test_the_search_colour_paints_the_accent_otherwise() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1, query_color="#3366ff")])

    assert recorder.payload()["components"][0]["accent_color"] == 0x3366FF


async def test_a_price_drop_strikes_through_the_old_price() -> None:
    recorder = Recorder()

    await sender(recorder).send(
        [notification(1, kind="price_drop", previous_price=Decimal("25.00"))]
    )

    text = all_text(recorder.payload())
    assert "-# Price drop" in text and "~~£25.00~~" in text


async def test_a_sold_listing_has_no_buy_button() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1, kind="sold")])

    assert [b["label"] for b in buttons(recorder.payload())] == ["Open on Vinted"]


async def test_the_buttons_go_buy_message_open_dashboard() -> None:
    recorder = Recorder()

    await sender(recorder, dashboard_url="https://sniper.example.net").send([notification(1)])

    assert [b["label"] for b in buttons(recorder.payload())] == [
        "Buy",
        "Message seller",
        "Open on Vinted",
        "Dashboard",
    ]


async def test_a_loopback_dashboard_gets_no_button() -> None:
    recorder = Recorder()

    await sender(recorder, dashboard_url="http://127.0.0.1:8000").send([notification(1)])

    assert "Dashboard" not in [b["label"] for b in buttons(recorder.payload())]


async def test_labels_follow_the_listing_site() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1, tld="de", currency="EUR")])

    assert buttons(recorder.payload())[0]["label"] == "Kaufen"


async def test_the_relative_time_falls_back_to_detection() -> None:
    recorder = Recorder()

    await sender(recorder).send([bare(1)])

    assert "<t:1760000100:R>" in all_text(recorder.payload())


async def test_a_bare_listing_still_makes_a_valid_card() -> None:
    """Title, price, one photo and a site is all the newer catalog endpoint guarantees."""
    recorder = Recorder()

    await sender(recorder).send([bare(1)])

    assert cv2_problems(recorder.payload()) == []


async def test_a_bare_listing_links_to_an_absolute_url() -> None:
    recorder = Recorder()

    await sender(recorder).send([bare(1)])

    assert "https://www.vinted.fr/items/1-slug" in [b["url"] for b in buttons(recorder.payload())]


# --- Hostile titles ------------------------------------------------------------------


async def test_a_title_cannot_ping_anyone() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1, title="@everyone free stuff <@&123>")])

    assert recorder.payload()["allowed_mentions"] == {"parse": []}


async def test_a_title_mention_is_defused_in_the_text_too() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1, title="@everyone free stuff")])

    assert "@everyone" not in all_text(recorder.payload())


@pytest.mark.parametrize(
    ("title", "live_markup"),
    [
        ("**NEW** [link](https://evil.test)", "](https://evil.test)"),
        ("size <t:0:R> today", "<t:0:R>"),
        ("a_b ~~c~~ `d`", "~~c~~"),
    ],
)
async def test_title_markdown_renders_literally(title: str, live_markup: str) -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(1, title=title)])

    heading = next(
        line for line in all_text(recorder.payload()).splitlines() if line.startswith("### ")
    )
    assert live_markup not in heading


# --- Mentions and silence --------------------------------------------------------------


async def test_a_configured_role_is_pinged_and_only_that_role() -> None:
    recorder = Recorder()

    await sender(recorder, mention="<@&42>").send([notification(1)])

    payload = recorder.payload()
    assert payload["allowed_mentions"] == {"parse": [], "roles": ["42"]}
    assert payload["components"][0] == {"type": 10, "content": "<@&42>"}


async def test_a_malformed_mention_is_a_configuration_error() -> None:
    with pytest.raises(SenderConfigError):
        sender(Recorder(), mention="the deals role")


async def test_a_silent_listing_neither_pings_nor_buzzes() -> None:
    recorder = Recorder()

    await sender(recorder, mention="<@&42>").send([notification(1, silent=True)])

    payload = recorder.payload()
    assert payload["flags"] & (1 << 12)
    assert payload["allowed_mentions"] == {"parse": []}


async def test_a_thread_id_posts_into_that_thread() -> None:
    recorder = Recorder()

    await sender(recorder, thread_id="999").send([notification(1)])

    assert recorder.requests[0].url.params["thread_id"] == "999"


# --- Batches -------------------------------------------------------------------------


async def test_a_few_listings_share_one_message_as_cards() -> None:
    recorder = Recorder()

    result = await sender(recorder).send([notification(i) for i in range(1, 4)])

    assert (result.delivered, len(recorder.requests)) == ([1, 2, 3], 1)


async def test_three_full_cards_stay_inside_the_limits() -> None:
    recorder = Recorder()

    await sender(recorder, mention="<@&42>").send(
        [notification(i, title="x" * 300) for i in range(1, 4)]
    )

    assert [cv2_problems(recorder.payload(i)) for i in range(len(recorder.requests))] == [
        [] for _ in recorder.requests
    ]


async def test_a_burst_becomes_a_digest() -> None:
    recorder = Recorder()

    result = await sender(recorder).send([notification(i) for i in range(1, 10)])

    assert len(result.delivered) == 9
    assert len(recorder.requests) == 1, "nine separate cards would be a wall"


async def test_a_full_digest_stays_inside_the_limits() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(i, title="y" * 200) for i in range(1, 10)])

    assert cv2_problems(recorder.payload()) == []


async def test_a_digest_names_the_count_and_the_search() -> None:
    recorder = Recorder()

    await sender(recorder).send([notification(i) for i in range(1, 6)])

    assert all_text(recorder.payload()).startswith("### 5 new matches · my search")


async def test_compact_style_shows_one_listing_as_a_thumbnail_row() -> None:
    recorder = Recorder()

    await sender(recorder, style="compact").send([notification(1)])

    container = recorder.payload()["components"][0]
    assert [c["type"] for c in container["components"]] == [10, 9, 1]


async def test_an_unknown_style_is_a_configuration_error() -> None:
    with pytest.raises(SenderConfigError):
        sender(Recorder(), style="fancy")


async def test_destinations_saved_before_2_0_still_work() -> None:
    recorder = Recorder()
    legacy = DiscordSender({"webhook_url": HOOK}, client=recorder.client(), bucket=fast_bucket())

    result = await legacy.send([notification(1)])

    assert result.delivered == [1]


# --- Falling back to embeds ----------------------------------------------------------


async def test_a_refused_card_is_resent_as_an_embed() -> None:
    recorder = Recorder(rejected_components())

    result = await sender(recorder).send([notification(1)])

    assert result.delivered == [1]
    assert "embeds" in recorder.payload(1)


async def test_after_one_refusal_the_destination_stays_on_embeds() -> None:
    recorder = Recorder(rejected_components())
    discord = sender(recorder)
    await discord.send([notification(1)])

    await discord.send([notification(2)])

    assert len(recorder.requests) == 3, "no second attempt at a card"
    assert "embeds" in recorder.payload(2)


async def test_a_400_that_is_not_about_components_is_not_retried_as_embeds() -> None:
    recorder = Recorder(httpx.Response(400, json={"message": "Cannot send an empty message"}))

    result = await sender(recorder).send([notification(1)])

    assert (len(recorder.requests), result.delivered, result.retry) == (1, [], [])


async def test_the_embed_fallback_keeps_its_buttons() -> None:
    recorder = Recorder()

    await sender(recorder, style="classic").send([notification(1)])

    row = recorder.payload()["components"][0]
    assert [b["label"] for b in row["components"]] == ["Buy", "Message seller", "Open on Vinted"]


async def test_the_embed_card_folds_extra_photos_into_a_mosaic() -> None:
    recorder = Recorder()

    await sender(recorder, style="classic").send([notification(1)])

    embeds = recorder.payload()["embeds"]
    assert len(embeds) == 4
    assert {embed["url"] for embed in embeds} == {"https://www.vinted.co.uk/items/1"}


async def test_the_embed_card_stays_inside_the_limits() -> None:
    recorder = Recorder()

    await sender(recorder, style="classic").send([notification(1, title="z" * 400)])

    assert embed_problems(recorder.payload()) == []


async def test_a_stacked_embed_batch_stays_inside_the_limits() -> None:
    recorder = Recorder()

    await sender(recorder, style="classic").send(
        [notification(i, title="w" * 300) for i in range(1, 10)]
    )

    assert embed_problems(recorder.payload()) == []


async def test_stacked_embeds_each_carry_their_own_listing_link() -> None:
    recorder = Recorder()

    await sender(recorder, style="classic").send([notification(i) for i in range(1, 6)])

    urls = [embed["url"] for embed in recorder.payload()["embeds"]]
    assert len(set(urls)) == 5, "Discord folds together embeds that share a URL"


# --- Status ---------------------------------------------------------------------------


async def test_a_status_notice_is_a_plain_grey_card() -> None:
    recorder = Recorder()

    await sender(recorder).send_status("vinted.fr is blocking requests")

    container = recorder.payload()["components"][0]
    assert container["accent_color"] == 0x5A6566


async def test_a_status_notice_pings_nobody_even_with_a_mention_configured() -> None:
    recorder = Recorder()

    await sender(recorder, mention="<@&42>").send_status("stale search")

    assert recorder.payload()["allowed_mentions"] == {"parse": []}


# --- When Discord says no -------------------------------------------------------------


async def test_a_deleted_webhook_is_switched_off_rather_than_retried() -> None:
    recorder = Recorder(httpx.Response(404, json={"message": "Unknown Webhook"}))

    result = await sender(recorder).send([notification(1)])

    assert result.permanent_error is not None
    assert result.retry == [], "retrying a dead webhook spends the allowance that protects the rest"


async def test_rate_limiting_asks_for_the_wait_discord_specified() -> None:
    recorder = Recorder(httpx.Response(429, json={"retry_after": 3.5, "global": False}))

    result = await sender(recorder).send([notification(1)])

    assert (result.retry, result.retry_after_s, result.pause_all_for_s) == ([1], 3.5, None)


async def test_a_global_rate_limit_pauses_every_destination() -> None:
    recorder = Recorder(
        httpx.Response(
            429,
            json={"retry_after": 10.0, "global": True},
            headers={"x-ratelimit-scope": "global"},
        )
    )

    result = await sender(recorder).send([notification(1)])

    assert result.pause_all_for_s == 10.0


async def test_a_failure_mid_batch_hands_back_only_what_was_not_sent() -> None:
    recorder = Recorder(httpx.Response(200), httpx.Response(503))

    result = await sender(recorder, style="classic").send([notification(1), notification(2)])

    assert (result.delivered, result.retry) == ([1], [2])
