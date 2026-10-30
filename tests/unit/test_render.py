"""How a listing is worded before any channel lays it out."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from vinted_sniper.db.repo import PendingNotification
from vinted_sniper.deliver.labels import format_money, labels_for, money_text
from vinted_sniper.deliver.render import (
    BRAND_COLOUR,
    DEAL_COLOUR,
    MINUS,
    deal_for,
    deal_pct,
    reachable_dashboard,
    view,
)
from vinted_sniper.vinted.models import Item


def pending(**overrides: Any) -> PendingNotification:
    item_fields: dict[str, Any] = {
        "item_id": 7,
        "tld": "fr",
        "title": "Jean Levi's 501",
        "url": "https://www.vinted.fr/items/7",
        "price": Decimal("10.00"),
        "total_price": Decimal("11.20"),
        "currency": "EUR",
    }
    item_fields.update(overrides.pop("item", {}))
    fields: dict[str, Any] = {
        "outbox_id": 1,
        "destination_id": 1,
        "query_id": 3,
        "query_name": "levis",
        "attempts": 0,
        "item": Item(**item_fields),
        "detected_at": 1_760_000_000,
    }
    fields.update(overrides)
    return PendingNotification(**fields)


@pytest.mark.parametrize(
    ("total", "typical", "tier"),
    [("5.40", "10", "steal"), ("7.90", "10", "good"), ("8.50", "10", None), ("12", "10", None)],
)
def test_deal_tiers_follow_the_distance_from_the_typical_price(
    total: str, typical: str, tier: str | None
) -> None:
    deal = deal_for(deal_pct(Decimal(total), Decimal(typical)))

    assert (deal.tier if deal else None) == tier


def test_no_typical_price_means_no_deal_claim() -> None:
    assert deal_pct(Decimal("5"), None) is None


def test_the_badge_states_the_percentage_and_its_basis() -> None:
    listing = view(
        pending(item={"tld": "co.uk", "currency": "GBP"}, typical_price=Decimal("20.00")),
        dashboard_url=None,
    )

    assert listing.badge == f"Steal {MINUS}44% vs typical"


def test_a_deal_turns_the_accent_green_whatever_the_search_colour() -> None:
    listing = view(pending(query_color="#ff0000", typical_price=Decimal("30")), dashboard_url=None)

    assert listing.accent == DEAL_COLOUR


def test_the_search_colour_is_the_accent_otherwise() -> None:
    listing = view(pending(query_color="#ff0000"), dashboard_url=None)

    assert listing.accent == 0xFF0000


def test_a_malformed_search_colour_falls_back_to_the_brand() -> None:
    listing = view(pending(query_color="red"), dashboard_url=None)

    assert listing.accent == BRAND_COLOUR


@pytest.mark.parametrize(
    ("tld", "locale"),
    [("fr", "fr"), ("be", "fr"), ("at", "de"), ("nl", "nl"), ("cz", "cs"), ("co.uk", "en")],
)
def test_labels_follow_the_site(tld: str, locale: str) -> None:
    assert labels_for(tld).locale == locale


def test_an_unlisted_site_gets_english() -> None:
    assert labels_for("se").buy == "Buy"


@pytest.mark.parametrize(
    ("currency", "locale", "expected"),
    [
        ("EUR", "en", "€4.90"),
        ("EUR", "fr", "4,90 €"),
        ("EUR", "nl", "€ 4,90"),
        ("PLN", "pl", "4,90 zł"),
        ("GBP", "en", "£4.90"),
        ("SEK", "en", "4.90 kr"),
    ],
)
def test_prices_are_written_the_local_way(currency: str, locale: str, expected: str) -> None:
    assert format_money(Decimal("4.9"), currency, locale) == expected


def test_contract_money_always_has_two_decimals() -> None:
    """Prices come back from SQLite as floats; 15.0 must still read "15.00"."""
    assert money_text(Decimal("15.0")) == "15.00"


def test_the_total_leads_and_the_asking_price_is_the_small_print() -> None:
    listing = view(pending(), dashboard_url=None)

    assert (listing.price, listing.asking) == ("11,20 €", "10,00 €")


def test_a_relative_listing_url_is_made_absolute() -> None:
    listing = view(pending(item={"url": "/items/7-jean"}), dashboard_url=None)

    assert listing.url == "https://www.vinted.fr/items/7-jean"


def test_the_detection_time_stands_in_when_the_listing_time_is_unknown() -> None:
    listing = view(pending(item={"photo_ts": None}), dashboard_url=None)

    assert listing.listed_at == 1_760_000_000


def test_a_listing_with_only_the_basics_still_renders() -> None:
    """Vinted's newer endpoint often sends no brand, size, condition or seller rating."""
    listing = view(pending(), dashboard_url=None)

    assert (listing.facts, listing.rating, listing.seller_login) == ([], None, None)


def test_a_seller_without_reviews_is_called_new() -> None:
    listing = view(
        pending(item={"seller_rating": 0.0, "seller_feedback_count": 0}), dashboard_url=None
    )

    assert listing.rating == "nouveau vendeur"


def test_the_rating_reads_as_stars_with_its_review_count() -> None:
    listing = view(
        pending(item={"seller_rating": 0.96, "seller_feedback_count": 128}), dashboard_url=None
    )

    assert listing.rating == "★ 4.8 (128)"


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000", "http://localhost:8000/"])
def test_a_dashboard_only_this_machine_can_open_is_not_linked(url: str) -> None:
    assert reachable_dashboard(url) is None


def test_a_public_dashboard_is_linked_per_search() -> None:
    listing = view(pending(), dashboard_url="https://sniper.example.net/")

    assert listing.search_url == "https://sniper.example.net/searches/3"


@pytest.mark.parametrize(
    ("kind", "headline"),
    [
        ("price_drop", "Price drop"),
        ("sold", "Sold"),
        ("reserved", "Reserved"),
        ("seller_upload", "New from jansen"),
    ],
)
def test_each_kind_of_alert_has_its_own_headline(kind: str, headline: str) -> None:
    listing = view(
        pending(kind=kind, item={"tld": "co.uk", "seller_login": "jansen"}), dashboard_url=None
    )

    assert listing.headline == headline


def test_a_sold_listing_offers_nothing_to_buy() -> None:
    assert view(pending(kind="sold"), dashboard_url=None).can_buy is False
