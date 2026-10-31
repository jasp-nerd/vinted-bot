"""How a listing is worded before any channel lays it out."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from vinted_bot.db.repo import PendingNotification
from vinted_bot.deliver.labels import (
    MINUS,
    format_money,
    format_rough_money,
    labels_for,
    money_text,
)
from vinted_bot.deliver.preview import sample_notification
from vinted_bot.deliver.render import (
    BRAND_COLOUR,
    DEAL_COLOUR,
    escape_markdown,
    reachable_dashboard,
    view,
)
from vinted_bot.vinted.models import Item


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
    ("total", "tier"), [("5.40", "steal"), ("7.90", "deal"), ("8.50", "normal"), ("12", "normal")]
)
def test_the_view_carries_the_shared_tier(total: str, tier: str) -> None:
    listing = view(
        pending(item={"total_price": Decimal(total)}, typical_price=Decimal("10")),
        dashboard_url=None,
    )

    assert listing.tier == tier


def test_no_typical_price_means_no_deal_claim() -> None:
    assert view(pending(), dashboard_url=None).deal is None


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


def test_the_rating_ends_with_the_seller_s_country_when_known() -> None:
    listing = view(
        pending(item={"seller_rating": 0.96, "seller_feedback_count": 128}, seller_country="DE"),
        dashboard_url=None,
    )

    assert listing.rating == "★ 4.8 (128) · \U0001f1e9\U0001f1ea"


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000", "http://localhost:8000/"])
def test_a_dashboard_only_this_machine_can_open_is_not_linked(url: str) -> None:
    assert reachable_dashboard(url) is None


def test_a_public_dashboard_is_linked_per_search() -> None:
    listing = view(pending(), dashboard_url="https://bot.example.net/")

    assert listing.search_url == "https://bot.example.net/searches/3"


@pytest.mark.parametrize(
    ("kind", "headline"),
    [
        ("price_drop", "Price drop"),
        ("sold", "Sold"),
        ("reserved", "Reserved"),
        ("removed", "No longer listed"),
        ("seller_upload", "New from jansen"),
    ],
)
def test_each_kind_of_alert_has_its_own_headline(kind: str, headline: str) -> None:
    listing = view(
        pending(kind=kind, item={"tld": "co.uk", "seller_login": "jansen"}), dashboard_url=None
    )

    assert listing.headline == headline


def test_a_watch_alert_has_no_search_page_to_link() -> None:
    listing = view(pending(query_id=None), dashboard_url="https://bot.example.net/")

    assert listing.search_url is None


def test_a_sold_listing_offers_nothing_to_buy() -> None:
    assert view(pending(kind="sold"), dashboard_url=None).can_buy is False


def test_markdown_escaping_leaves_ordinary_punctuation_alone() -> None:
    """Text-only services receive the markdown as is, so needless backslashes would show."""
    assert escape_markdown("Levi's 501, W32. Size: M!") == "Levi's 501, W32. Size: M!"


# --- Phone-first details ----------------------------------------------------------------


def test_a_time_vinted_never_gave_is_labelled_as_found() -> None:
    listing = view(pending(item={"photo_ts": None}), dashboard_url=None)

    assert listing.time_label == "trouvé"


def test_a_known_listing_time_is_labelled_as_listed() -> None:
    listing = view(pending(item={"photo_ts": 1_759_999_000}), dashboard_url=None)

    assert listing.time_label == "publié"


@pytest.mark.parametrize(
    ("tld", "word"),
    [
        ("co.uk", "found"),
        ("fr", "trouvé"),
        ("de", "gefunden"),
        ("nl", "gevonden"),
        ("es", "encontrado"),
        ("it", "trovato"),
        ("pl", "znaleziono"),
        ("lt", "rasta"),
        ("cz", "nalezeno"),
    ],
)
def test_found_is_said_in_the_site_language(tld: str, word: str) -> None:
    assert labels_for(tld).found == word


def test_the_margin_is_a_rough_signed_figure_in_the_site_language() -> None:
    listing = view(pending(margin=Decimal("18.60")), dashboard_url=None)

    assert listing.margin_text == "marge ~+19 €"


def test_a_loss_reads_with_a_real_minus_sign() -> None:
    assert format_rough_money(Decimal("-4.20"), "GBP", "en") == f"{MINUS}£4"


def test_without_a_resale_price_there_is_no_margin() -> None:
    assert view(pending(), dashboard_url=None).margin_text is None


def test_the_first_line_summary_is_the_short_badge_then_the_margin() -> None:
    listing = view(
        pending(typical_price=Decimal("25.00"), margin=Decimal("12")), dashboard_url=None
    )

    assert listing.summary == [f"Super affaire {MINUS}55%", "marge ~+12 €"]


@pytest.mark.parametrize(
    ("tld", "host"),
    [
        ("fr", "www.ebay.fr"),
        ("de", "www.ebay.de"),
        ("co.uk", "www.ebay.co.uk"),
        ("be", "www.befr.ebay.be"),
        ("pl", "www.ebay.pl"),
        ("lt", "www.ebay.com"),
    ],
)
def test_the_price_check_goes_to_the_matching_ebay(tld: str, host: str) -> None:
    listing = view(pending(item={"tld": tld}), dashboard_url=None)

    assert listing.price_check_url.startswith(f"https://{host}/sch/i.html?")


def test_the_price_check_searches_sold_listings_for_the_title() -> None:
    listing = view(pending(), dashboard_url=None)

    assert listing.price_check_url.endswith("_nkw=Jean+Levi%27s+501&LH_Sold=1&LH_Complete=1")


def test_the_photo_search_hands_lens_the_photo_url() -> None:
    listing = view(
        pending(item={"photo_url": "https://images.vinted.net/a.jpg?s=1&t=2"}), dashboard_url=None
    )

    assert listing.photo_search_url == (
        "https://lens.google.com/uploadbyurl?url=https%3A%2F%2Fimages.vinted.net%2Fa.jpg%3Fs%3D1%26t%3D2"
    )


def test_a_listing_without_a_photo_has_no_photo_search() -> None:
    assert view(pending(), dashboard_url=None).photo_search_url is None


def test_a_test_alert_opens_a_real_search_rather_than_an_invented_listing() -> None:
    """Its "Open on Vinted" led to a listing that does not exist."""
    listing = view(sample_notification(tld="fr"), dashboard_url=None)

    assert {listing.url, listing.buy_url, listing.message_url} == {
        "https://www.vinted.fr/catalog?search_text=levi%27s%20501"
    }
