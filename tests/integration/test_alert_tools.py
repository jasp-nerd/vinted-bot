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
from vinted_sniper.deliver.dispatcher import Dispatcher, skip_reason
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
