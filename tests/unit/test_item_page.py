"""Reading a listing back from its public page (recorded October 2026, sellers renamed)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from vinted_bot.vinted.errors import MalformedResponseError
from vinted_bot.vinted.item_page import parse_item_page

FIXTURES = Path(__file__).parent.parent / "fixtures" / "vinted"
AVAILABLE_ID = 10590400585
SOLD_ID = 9686460238


def page(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def available_page() -> str:
    return page("item_available_fr.html")


def flight_page(chunk: str) -> str:
    """A page carrying one flight chunk, built the way Next.js writes them."""
    return f"<html><script>self.__next_f.push([1,{json.dumps(chunk)}])</script></html>"


def test_a_listing_for_sale_reads_as_available() -> None:
    snapshot = parse_item_page(available_page(), "fr", AVAILABLE_ID)

    assert snapshot.status == "available"


def test_the_price_comes_with_its_currency() -> None:
    snapshot = parse_item_page(available_page(), "fr", AVAILABLE_ID)

    assert (snapshot.price, snapshot.currency) == (Decimal("39.99"), "EUR")


def test_the_page_restores_what_search_results_lost() -> None:
    snapshot = parse_item_page(available_page(), "fr", AVAILABLE_ID)

    assert (snapshot.brand, snapshot.size, snapshot.condition, snapshot.color) == (
        "Nike",
        "38",
        "Très bon état",
        "Noir",
    )


def test_every_photo_is_read_cover_first() -> None:
    snapshot = parse_item_page(available_page(), "fr", AVAILABLE_ID)

    assert len(snapshot.photo_urls) == 6
    assert snapshot.photo_url == snapshot.photo_urls[0]


def test_the_seller_and_their_reputation_are_read() -> None:
    snapshot = parse_item_page(available_page(), "fr", AVAILABLE_ID)

    assert (snapshot.seller_id, snapshot.seller_rating, snapshot.seller_feedback_count) == (
        1000001,
        1.0,
        14,
    )


def test_a_sold_listing_reads_as_sold() -> None:
    snapshot = parse_item_page(page("item_sold_nl.html"), "nl", SOLD_ID)

    assert snapshot.status == "sold"


def test_a_long_description_is_followed_to_where_the_page_keeps_it() -> None:
    snapshot = parse_item_page(page("item_sold_nl.html"), "nl", SOLD_ID)

    assert snapshot.description is not None
    assert snapshot.description.endswith("#highwaisted")


def test_a_reserved_listing_reads_as_reserved() -> None:
    html = available_page().replace('\\"is_reserved\\":false', '\\"is_reserved\\":true')

    assert parse_item_page(html, "fr", AVAILABLE_ID).status == "reserved"


def test_without_the_flight_data_the_structured_data_still_answers() -> None:
    html = (
        '<script type="application/ld+json">{"@type":"Product","name":"Coat",'
        '"offers":{"price":12.5,"priceCurrency":"PLN","availability":"InStock"}}</script>'
    )

    snapshot = parse_item_page(html, "pl", 1)

    assert (snapshot.title, snapshot.price, snapshot.currency, snapshot.status) == (
        "Coat",
        Decimal("12.5"),
        "PLN",
        "available",
    )


def test_a_page_with_none_of_the_expected_data_is_refused() -> None:
    with pytest.raises(MalformedResponseError, match="none of the data"):
        parse_item_page("<html><body>Just a moment...</body></html>", "fr", 1)


def test_a_page_that_does_not_say_whether_it_can_be_bought_is_refused() -> None:
    html = flight_page('{"value":{"id":"1","title":"Coat","can_buy":false,"is_reserved":false}}')

    with pytest.raises(MalformedResponseError, match="can be bought"):
        parse_item_page(html, "fr", 1)
