"""Per-destination choices, the test button and the alert preview."""

from __future__ import annotations

import asyncio
import json
import time
from decimal import Decimal

import httpx
import pytest

from tests.unit.sending import cv2_problems, notification, telegram_length
from vinted_sniper.config import Settings
from vinted_sniper.db.repo import Destination, Repo
from vinted_sniper.deliver import preview_payload, send_test
from vinted_sniper.deliver.base import SenderConfigError
from vinted_sniper.deliver.dispatcher import Dispatcher, Routing, deliver_silently, skip_reason
from vinted_sniper.vinted.models import Item


class Endpoint:
    def __init__(self, *responses: httpx.Response) -> None:
        self.requests: list[httpx.Request] = []
        self._responses = list(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._responses:
            return self._responses.pop(0)
        return httpx.Response(200, json={"ok": True})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


def destination(kind: str, config: dict[str, object]) -> Destination:
    return Destination(id=1, kind=kind, name="My channel", config=dict(config))


# --- Deals only ------------------------------------------------------------------------


def test_a_deals_only_destination_skips_an_ordinary_listing() -> None:
    reason = skip_reason(notification(1, typical_price=Decimal("17")), {"deals_only": True})

    assert reason is not None and reason.startswith("skipped:")


def test_a_deals_only_destination_takes_a_deal() -> None:
    assert skip_reason(notification(1, typical_price=Decimal("25")), {"deals_only": True}) is None


def test_a_custom_threshold_is_honoured() -> None:
    """16.45 against 25 is 34% under: enough for 30, not for 40."""
    listing = notification(1, typical_price=Decimal("25"))

    assert (
        skip_reason(listing, {"min_deal_pct": 30}) is None,
        skip_reason(listing, {"min_deal_pct": 40}) is not None,
    ) == (True, True)


def test_without_a_typical_price_nothing_counts_as_a_deal() -> None:
    assert skip_reason(notification(1), {"deals_only": True}) is not None


def test_a_watched_price_drop_always_gets_through() -> None:
    """The user asked to follow this listing; that is not a search match to filter."""
    drop = notification(1, kind="price_drop", previous_price=Decimal("30"))

    assert skip_reason(drop, {"deals_only": True}) is None


def test_an_unpicky_destination_skips_nothing() -> None:
    assert skip_reason(notification(1), {}) is None


# --- Tiers -------------------------------------------------------------------------------
# 16.45 against a typical 30 is 45% under (a steal); against 25, 34% (a deal); against 17,
# 3% (normal).


def test_a_steals_only_destination_skips_a_deal() -> None:
    reason = skip_reason(notification(1, typical_price=Decimal("25")), {"tiers": ["steal"]})

    assert reason is not None and "takes steals only" in reason


def test_a_steals_only_destination_takes_a_steal() -> None:
    assert skip_reason(notification(1, typical_price=Decimal("30")), {"tiers": ["steal"]}) is None


def test_a_destination_can_take_only_ordinary_listings() -> None:
    """A "feed" channel next to a "deals" one: everything the other does not get."""
    reason = skip_reason(notification(1, typical_price=Decimal("30")), {"tiers": ["normal"]})

    assert reason is not None


def test_deals_only_is_the_steal_and_deal_tiers() -> None:
    listing = notification(1, typical_price=Decimal("25"))

    assert skip_reason(listing, {"deals_only": True}) == skip_reason(
        listing, {"tiers": ["steal", "deal"]}
    )


def test_a_skip_says_how_far_under_typical_the_listing_was() -> None:
    reason = skip_reason(notification(1, typical_price=Decimal("17")), {"tiers": ["steal"]})

    assert reason is not None and reason.startswith("skipped: 3% under the typical price")


def test_an_unknown_tier_is_a_configuration_error() -> None:
    with pytest.raises(SenderConfigError):
        Routing.from_config({"tiers": ["bargain"]})


def test_tiers_may_be_typed_as_a_comma_separated_list() -> None:
    assert Routing.from_config({"tiers": "Steal, deal"}).tiers == {"steal", "deal"}


def test_tiers_that_are_not_a_list_are_a_configuration_error() -> None:
    with pytest.raises(SenderConfigError):
        Routing.from_config({"tiers": {"steal": True}})


def test_a_threshold_that_is_not_a_number_is_a_configuration_error() -> None:
    with pytest.raises(SenderConfigError):
        Routing.from_config({"min_deal_pct": "lots"})


def test_an_empty_tier_list_is_a_configuration_error() -> None:
    """Delivering nothing at all is what switching the destination off is for."""
    with pytest.raises(SenderConfigError):
        Routing.from_config({"tiers": []})


def test_silent_tiers_quiet_only_those_tiers() -> None:
    routing = Routing.from_config({"silent_tiers": ["normal"]})

    assert (
        deliver_silently(notification(1, typical_price=Decimal("17")), routing),
        deliver_silently(notification(2, typical_price=Decimal("30")), routing),
    ) == (True, False)


def test_a_watch_alert_is_never_silenced_by_tier() -> None:
    routing = Routing.from_config({"silent_tiers": ["normal"]})
    drop = notification(1, kind="price_drop", previous_price=Decimal("30"))

    assert deliver_silently(drop, routing) is False


async def test_skipped_listings_never_reach_the_destination(repo: Repo, settings: Settings) -> None:
    query_id = await repo.add_query(
        name="test", url="https://www.vinted.fr/catalog?search_text=x", tld="fr", params={},
        poll_interval_s=60,
    )  # fmt: skip
    query = await repo.get_query(query_id)
    assert query is not None
    destination_id = await repo.add_destination(
        kind="webhook", name="deals", config={"url": "https://example.test", "deals_only": True}
    )
    item = Item(
        item_id=1, tld="fr", title="x", url="https://www.vinted.fr/items/1",
        price=Decimal("10"), currency="EUR", photo_ts=int(time.time()),
    )  # fmt: skip
    await repo.record_new_items(query, [item], [destination_id])
    endpoint = Endpoint()
    dispatcher = Dispatcher(
        repo=repo,
        settings=settings,
        stop=asyncio.Event(),
        work_available=asyncio.Event(),
        client=endpoint.client(),
    )

    await dispatcher.drain()

    assert (len(endpoint.requests), await repo.outbox_depth()) == (0, 0)


async def test_a_silent_tier_reaches_the_destination_without_a_sound(
    repo: Repo, settings: Settings
) -> None:
    query_id = await repo.add_query(
        name="test", url="https://www.vinted.fr/catalog?search_text=x", tld="fr", params={},
        poll_interval_s=60,
    )  # fmt: skip
    query = await repo.get_query(query_id)
    assert query is not None
    destination_id = await repo.add_destination(
        kind="ntfy", name="feed", config={"topic": "feed", "silent_tiers": ["normal"]}
    )
    item = Item(
        item_id=1, tld="fr", title="x", url="https://www.vinted.fr/items/1",
        price=Decimal("10"), currency="EUR",
    )  # fmt: skip
    await repo.record_new_items(query, [item], [destination_id])
    endpoint = Endpoint()
    dispatcher = Dispatcher(
        repo=repo,
        settings=settings,
        stop=asyncio.Event(),
        work_available=asyncio.Event(),
        client=endpoint.client(),
    )

    await dispatcher.drain()

    assert json.loads(endpoint.requests[0].content)["priority"] == 2


async def test_a_destination_with_unknown_tiers_is_switched_off(
    repo: Repo, settings: Settings
) -> None:
    destination_id = await repo.add_destination(
        kind="ntfy", name="feed", config={"topic": "feed", "tiers": ["bargain"]}
    )
    query_id = await repo.add_query(
        name="test", url="https://www.vinted.fr/catalog?search_text=x", tld="fr", params={},
        poll_interval_s=60,
    )  # fmt: skip
    query = await repo.get_query(query_id)
    assert query is not None
    item = Item(
        item_id=1, tld="fr", title="x", url="https://www.vinted.fr/items/1",
        price=Decimal("10"), currency="EUR",
    )  # fmt: skip
    await repo.record_new_items(query, [item], [destination_id])
    dispatcher = Dispatcher(
        repo=repo,
        settings=settings,
        stop=asyncio.Event(),
        work_available=asyncio.Event(),
        client=Endpoint().client(),
    )

    await dispatcher.drain()

    destination = await repo.get_destination(destination_id)
    assert destination is not None and destination.active is False


# --- Test send -------------------------------------------------------------------------


async def test_the_test_button_sends_a_sample_listing(settings: Settings) -> None:
    endpoint = Endpoint()

    result = await send_test(
        destination("webhook", {"url": "https://example.test/hook"}),
        settings=settings,
        client=endpoint.client(),
    )

    assert result.ok is True
    assert json.loads(endpoint.requests[0].content)["items"][0]["title"].endswith("(test alert)")


async def test_a_test_against_a_deleted_webhook_says_so(settings: Settings) -> None:
    endpoint = Endpoint(httpx.Response(404, json={"message": "Unknown Webhook"}))

    result = await send_test(
        destination("discord", {"url": "https://discord.test/hook"}),
        settings=settings,
        client=endpoint.client(),
    )

    assert (result.ok, result.detail is not None) == (False, True)


async def test_a_test_of_a_misconfigured_destination_explains_without_sending(
    settings: Settings,
) -> None:
    endpoint = Endpoint()

    result = await send_test(destination("ntfy", {}), settings=settings, client=endpoint.client())

    assert (result.ok, endpoint.requests) == (False, [])


async def test_a_test_of_an_unpaired_telegram_chat_asks_for_pairing_first(
    settings: Settings,
) -> None:
    result = await send_test(destination("telegram", {"pairing_code": "abc"}), settings=settings)

    assert "pairing link" in result.message


async def test_a_test_send_follows_the_site_language(settings: Settings) -> None:
    endpoint = Endpoint()

    await send_test(
        destination("discord", {"url": "https://discord.test/hook"}),
        settings=settings,
        tld="nl",
        client=endpoint.client(),
    )

    assert "Kopen" in endpoint.requests[0].content.decode()


# --- Preview ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["listing", "price_drop", "sold", "reserved", "seller_upload"])
@pytest.mark.parametrize("count", [1, 3, 9])
def test_every_discord_preview_is_a_valid_card(kind: str, count: int) -> None:
    payload = preview_payload("discord", kind=kind, count=count, dashboard_url="https://x.test")

    assert cv2_problems(payload) == []


@pytest.mark.parametrize("style", ["photo", "gallery", "compact"])
def test_every_telegram_preview_names_its_method(style: str) -> None:
    payload = preview_payload("telegram", config={"style": style})

    assert (
        payload["method"]
        == {
            "photo": "sendPhoto",
            "gallery": "sendRichMessage",
            "compact": "sendMessage",
        }[style]
    )


def test_a_telegram_preview_caption_fits() -> None:
    payload = preview_payload("telegram")

    assert telegram_length(payload["params"]["caption"]) <= 1024


def test_a_preview_never_needs_or_shows_the_address() -> None:
    payload = preview_payload("ntfy", config={"topic": "t", "token": "tk_secret"})

    assert "tk_secret" not in json.dumps(payload)


def test_the_classic_preview_is_embeds() -> None:
    assert "embeds" in preview_payload("discord", config={"style": "classic"})


@pytest.mark.parametrize("kind", ["webhook", "apprise"])
def test_other_previews_render(kind: str) -> None:
    assert preview_payload(kind)


def test_an_unknown_kind_has_no_preview() -> None:
    with pytest.raises(ValueError, match="carrier pigeon"):
        preview_payload("carrier pigeon")
