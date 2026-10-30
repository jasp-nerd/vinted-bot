"""The client against recorded responses: what it asks for, and what each answer means."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import ScriptedTransport
from vinted_bot.db import Database
from vinted_bot.vinted.client import VintedClient
from vinted_bot.vinted.errors import (
    ApiChangedError,
    AuthExpiredError,
    BlockedError,
    InvalidSearchError,
    RateLimitedError,
)
from vinted_bot.vinted.session import SessionManager
from vinted_bot.vinted.transport import Response, TransportError

FIXTURES = Path(__file__).parent.parent / "fixtures" / "vinted"
HOMEPAGE_COOKIES = {
    "access_token_web": "token",
    "anon_id": "anon-123",
    "anonymous-iso-locale": "fr-FR",
}


def recorded(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def ok(body: str) -> Response:
    return Response(status_code=200, text=body, headers={}, cookies={})


@pytest.fixture
def sessions(db: Database, transport: ScriptedTransport) -> SessionManager:
    transport.queue_root(
        Response(status_code=200, text="<html></html>", headers={}, cookies=HOMEPAGE_COOKIES)
    )
    return SessionManager(db, transport)


@pytest.fixture
def client(transport: ScriptedTransport, sessions: SessionManager) -> VintedClient:
    return VintedClient(transport, sessions)


# --- Search ---------------------------------------------------------------------------


async def test_search_asks_the_search_service_with_translated_filters(
    client: VintedClient, transport: ScriptedTransport
) -> None:
    transport.queue(ok(recorded("catalogue_fr.json")))

    await client.search("fr", {"brand_ids": "53", "order": "newest_first"})

    request = transport.requests[-1]
    assert request["url"] == "https://api.vinted.fr/svc-catalogue/items"
    assert request["params"]["attribute_ids[brand]"] == "53"
    assert "brand_ids" not in request["params"]


async def test_search_names_the_market_and_the_visitor_it_belongs_to(
    client: VintedClient, transport: ScriptedTransport
) -> None:
    transport.queue(ok(recorded("catalogue_fr.json")))

    await client.search("fr", {"search_text": "nike"})

    headers = transport.requests[-1]["headers"]
    assert (headers["Locale"], headers["X-Anon-Id"]) == ("fr-FR", "anon-123")


async def test_search_returns_the_recorded_listings(
    client: VintedClient, transport: ScriptedTransport
) -> None:
    transport.queue(ok(recorded("catalogue_fr.json")))

    items = await client.search("fr", {"search_text": "nike"})

    assert len(items) == 6
    assert all(item.url.startswith("https://www.vinted.fr/items/") for item in items)


async def test_a_404_from_search_means_vinted_moved_it(
    client: VintedClient, transport: ScriptedTransport
) -> None:
    transport.queue_status(404, "<html>La page n'existe pas</html>")

    with pytest.raises(ApiChangedError):
        await client.search("fr", {"search_text": "nike"})


async def test_a_400_from_search_means_the_filters_need_editing(
    client: VintedClient, transport: ScriptedTransport
) -> None:
    transport.queue_status(400, json.dumps({"code": "INVALID_REQUEST", "message": "Bad params."}))

    with pytest.raises(InvalidSearchError, match="Bad params"):
        await client.search("fr", {"search_text": "nike"})


async def test_a_refused_search_marks_its_session_as_failed(
    client: VintedClient, transport: ScriptedTransport, sessions: SessionManager
) -> None:
    transport.queue_status(403, json.dumps({"code": "FORBIDDEN"}))

    with pytest.raises(BlockedError):
        await client.search("fr", {"search_text": "nike"})

    assert (await sessions.get("fr")).failed


async def test_an_expired_token_reported_in_the_body_is_an_auth_error(
    client: VintedClient, transport: ScriptedTransport
) -> None:
    transport.queue(ok(json.dumps({"code": "UNAUTHORIZED", "message": "Authorization failed."})))

    with pytest.raises(AuthExpiredError):
        await client.search("fr", {"search_text": "nike"})


async def test_a_rate_limit_carries_the_wait_vinted_asked_for(
    client: VintedClient, transport: ScriptedTransport
) -> None:
    transport.queue_status(429, "", **{"retry-after": "30"})

    with pytest.raises(RateLimitedError) as caught:
        await client.search("fr", {"search_text": "nike"})

    assert caught.value.retry_after == 30.0


# --- Members --------------------------------------------------------------------------


async def test_a_seller_lookup_reads_the_member_profile(
    client: VintedClient, transport: ScriptedTransport
) -> None:
    transport.queue(ok(recorded("user_fr.json")))

    seller = await client.seller("fr", 1000001)

    assert seller is not None
    assert (seller.country_code, seller.rating) == ("IE", 5.0)


async def test_a_seller_lookup_asks_the_member_endpoint(
    client: VintedClient, transport: ScriptedTransport
) -> None:
    transport.queue(ok(recorded("user_fr.json")))

    await client.seller("fr", 1000001)

    assert transport.requests[-1]["url"] == "https://www.vinted.fr/api/v2/users/1000001"


async def test_a_member_who_is_gone_is_none(
    client: VintedClient, transport: ScriptedTransport
) -> None:
    transport.queue_status(404, json.dumps({"code": 104, "message_code": "not_found"}))

    assert await client.seller("fr", 1) is None


async def test_a_refused_seller_lookup_is_raised_not_hidden(
    client: VintedClient, transport: ScriptedTransport
) -> None:
    transport.queue_status(403, "Forbidden")

    with pytest.raises(BlockedError):
        await client.seller("fr", 1)


async def test_a_members_uploads_come_from_their_wardrobe(
    client: VintedClient, transport: ScriptedTransport
) -> None:
    transport.queue(ok(recorded("wardrobe_fr.json")))

    items = await client.seller_items("fr", 1000001, per_page=2)

    assert [item.item_id for item in items] == [10590400585, 10240218409]
    assert transport.requests[-1]["params"]["per_page"] == "2"


async def test_a_gone_members_wardrobe_is_empty(
    client: VintedClient, transport: ScriptedTransport
) -> None:
    transport.queue_status(404, json.dumps({"code": 104}))

    assert await client.seller_items("fr", 1) == []


# --- Item pages -----------------------------------------------------------------------


async def test_an_item_snapshot_reads_the_public_page(
    client: VintedClient, transport: ScriptedTransport, sessions: SessionManager
) -> None:
    await sessions.get("fr")  # the homepage first, so the next page load is the item
    transport.queue_root(ok(recorded("item_available_fr.html")))

    snapshot = await client.item_snapshot("fr", 10590400585)

    assert (snapshot.status, snapshot.brand) == ("available", "Nike")


@pytest.mark.parametrize("status", [404, 410])
async def test_a_listing_whose_page_is_gone_reads_as_gone(
    client: VintedClient, transport: ScriptedTransport, sessions: SessionManager, status: int
) -> None:
    await sessions.get("fr")
    transport.queue_root(Response(status_code=status, text="", headers={}, cookies={}))

    snapshot = await client.item_snapshot("fr", 1)

    assert snapshot.status == "gone"


async def test_a_refused_item_page_is_raised(
    client: VintedClient, transport: ScriptedTransport, sessions: SessionManager
) -> None:
    await sessions.get("fr")
    transport.queue_root(Response(status_code=403, text="", headers={}, cookies={}))

    with pytest.raises(BlockedError):
        await client.item_snapshot("fr", 1)


# --- Diagnosis ------------------------------------------------------------------------


async def test_a_healthy_connection_is_reported_as_working(
    client: VintedClient, transport: ScriptedTransport
) -> None:
    transport.queue(ok(recorded("catalogue_fr.json")))

    diagnosis = await client.diagnose("fr")

    assert (diagnosis.reachable, diagnosis.got_session_cookie, diagnosis.catalog_ok) == (
        True,
        True,
        True,
    )
    assert diagnosis.problem is None


async def test_a_refused_homepage_reads_as_a_blocked_address(
    db: Database, transport: ScriptedTransport
) -> None:
    transport.queue_root(Response(status_code=403, text="", headers={}, cookies={}))
    client = VintedClient(transport, SessionManager(db, transport))

    diagnosis = await client.diagnose("fr")

    assert (diagnosis.problem, diagnosis.got_session_cookie, diagnosis.http_status) == (
        "blocked",
        False,
        403,
    )
    assert "IP address looks blocked" in diagnosis.message


async def test_no_connection_at_all_reads_as_offline(db: Database) -> None:
    class Offline(ScriptedTransport):
        async def get(self, url: str, **kwargs: object) -> Response:
            raise TransportError("Name or service not known")

    transport = Offline()
    client = VintedClient(transport, SessionManager(db, transport))

    diagnosis = await client.diagnose("fr")

    assert (diagnosis.reachable, diagnosis.problem) == (False, "offline")


async def test_a_refused_search_after_a_good_session_reads_as_blocked(
    client: VintedClient, transport: ScriptedTransport
) -> None:
    transport.queue_status(403, json.dumps({"code": "FORBIDDEN"}))

    diagnosis = await client.diagnose("fr")

    assert (diagnosis.got_session_cookie, diagnosis.catalog_ok, diagnosis.problem) == (
        True,
        False,
        "blocked",
    )


async def test_a_rate_limit_reads_as_slow_down(
    client: VintedClient, transport: ScriptedTransport
) -> None:
    transport.queue_status(429, "")

    diagnosis = await client.diagnose("fr")

    assert (diagnosis.problem, diagnosis.http_status) == ("rate_limited", 429)


async def test_a_moved_search_endpoint_reads_as_update_the_app(
    client: VintedClient, transport: ScriptedTransport
) -> None:
    transport.queue_status(404, "<html></html>")

    diagnosis = await client.diagnose("fr")

    assert diagnosis.problem == "api_changed"
    assert "update the app" in diagnosis.message


async def test_an_expired_session_is_renewed_once_during_a_diagnosis(
    client: VintedClient, transport: ScriptedTransport
) -> None:
    transport.queue_status(401, json.dumps({"code": "UNAUTHORIZED"}))
    transport.queue(ok(recorded("catalogue_fr.json")))

    diagnosis = await client.diagnose("fr")

    assert diagnosis.catalog_ok
