from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from vinted_sniper.vinted.models import ParseError, parse_item, parse_seller

FIXTURES = Path(__file__).parent.parent / "fixtures" / "vinted"


def recorded(name: str) -> Any:
    """A real response, recorded live and anonymised (sellers renamed)."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def catalog_entry(**overrides: Any) -> dict[str, Any]:
    """A catalog entry shaped like the real thing, trimmed to what we read."""
    entry: dict[str, Any] = {
        "id": 9683334896,
        "title": "Nike Air",
        "url": "https://www.vinted.fr/items/9683334896-nike-air",
        "brand_title": "Nike Air",
        "size_title": "38.5",
        "status": "Bon état",
        "price": {"amount": "15.0", "currency_code": "EUR"},
        "total_item_price": {"amount": "16.45", "currency_code": "EUR"},
        "service_fee": {"amount": "1.45", "currency_code": "EUR"},
        "photo": {
            "full_size_url": "https://images.vinted.net/full.jpeg",
            "high_resolution": {"id": "abc", "timestamp": 1_755_374_000},
        },
        "photos": [
            {"full_size_url": "https://images.vinted.net/full.jpeg"},
            {"full_size_url": "https://images.vinted.net/back.jpeg"},
            {"url": "https://images.vinted.net/label.jpeg"},
        ],
        "user": {"id": 7, "login": "seller", "feedback_reputation": 0.93, "feedback_count": 41},
        "promoted": False,
        "favourite_count": 2,
        "view_count": 11,
        "item_box": {"accessibility_label": "Nike Air, brand: Nike, 15,00 €"},
    }
    entry.update(overrides)
    return entry


def test_a_full_entry_parses() -> None:
    item = parse_item(catalog_entry(), "fr")

    assert item.item_id == 9683334896
    assert item.title == "Nike Air"
    assert item.brand == "Nike Air"
    assert item.size == "38.5"
    assert item.condition == "Bon état"
    assert item.price == Decimal("15.0")
    assert item.total_price == Decimal("16.45")
    assert item.currency == "EUR"
    assert item.photo_ts == 1_755_374_000
    assert item.seller_login == "seller"
    assert item.seller_id == 7
    assert item.seller_feedback_count == 41
    assert item.seller_url == "https://www.vinted.fr/member/7"
    assert item.tld == "fr"


def test_an_anonymous_listing_has_no_seller_link() -> None:
    item = parse_item(catalog_entry(user=None), "fr")

    assert item.seller_url is None
    assert item.seller_feedback_count is None


def test_total_price_is_kept_apart_from_the_asking_price() -> None:
    item = parse_item(catalog_entry(), "fr")

    assert item.total_price is not None
    assert item.price is not None
    assert item.total_price > item.price
    assert "with protection" in item.price_line()


def test_price_line_stays_simple_when_there_is_no_fee() -> None:
    item = parse_item(
        catalog_entry(total_item_price={"amount": "15.0", "currency_code": "EUR"}), "fr"
    )

    assert item.price_line() == "15.0 EUR"


def test_a_listing_without_an_id_is_rejected() -> None:
    entry = catalog_entry()
    del entry["id"]

    with pytest.raises(ParseError):
        parse_item(entry, "fr")


@pytest.mark.parametrize(
    "overrides",
    [
        {"photo": None},
        {"photo": []},
        {"user": None},
        {"brand_title": ""},
        {"size_title": None},
        {"price": None},
        {"total_item_price": "not-a-price"},
        {"favourite_count": None},
    ],
)
def test_missing_or_reshaped_fields_do_not_lose_the_listing(overrides: dict[str, Any]) -> None:
    item = parse_item(catalog_entry(**overrides), "fr")

    assert item.item_id == 9683334896
    assert item.title == "Nike Air"


def test_every_photo_is_kept_for_the_gallery() -> None:
    item = parse_item(catalog_entry(), "fr")

    assert item.photo_urls == (
        "https://images.vinted.net/full.jpeg",
        "https://images.vinted.net/back.jpeg",
        "https://images.vinted.net/label.jpeg",
    )


def test_a_listing_without_the_photos_array_still_has_its_cover() -> None:
    entry = catalog_entry()
    del entry["photos"]

    item = parse_item(entry, "fr")

    assert item.photo_urls == ("https://images.vinted.net/full.jpeg",)


def test_junk_in_the_photos_array_does_not_lose_the_gallery() -> None:
    item = parse_item(
        catalog_entry(photos=[None, "text", {"url": "https://images.vinted.net/ok.jpeg"}, {}]),
        "fr",
    )

    assert item.photo_urls == ("https://images.vinted.net/ok.jpeg",)


def test_no_label_brand_reads_as_absent() -> None:
    assert parse_item(catalog_entry(brand_title="NO LABEL"), "fr").brand is None


def test_bare_numeric_price_is_accepted() -> None:
    item = parse_item(catalog_entry(price=12.5), "fr")

    assert item.price == Decimal("12.5")


def test_url_is_derived_when_the_payload_omits_it() -> None:
    entry = catalog_entry()
    del entry["url"]

    assert parse_item(entry, "de").url == "https://www.vinted.de/items/9683334896"


def test_raw_payload_is_only_kept_when_asked_for() -> None:
    assert parse_item(catalog_entry(), "fr").raw is None
    assert parse_item(catalog_entry(), "fr", keep_raw=True).raw is not None


def test_action_links_follow_the_country_site() -> None:
    item = parse_item(catalog_entry(), "co.uk")

    assert item.message_url.startswith("https://www.vinted.co.uk/")
    assert item.buy_url.startswith("https://www.vinted.co.uk/")


# --- Recorded svc-catalogue responses (October 2026) ----------------------------------


def search_entry(item_id: int) -> dict[str, Any]:
    entries = recorded("catalogue_fr.json")["items"]
    return next(entry for entry in entries if entry["id"] == item_id)


def test_every_recorded_search_result_parses() -> None:
    entries = recorded("catalogue_fr.json")["items"]

    items = [parse_item(entry, "fr") for entry in entries]

    assert [item.item_id for item in items] == [entry["id"] for entry in entries]


def test_a_relative_listing_path_becomes_a_link_on_the_right_site() -> None:
    item = parse_item(search_entry(10590400585), "fr")

    assert item.url == "https://www.vinted.fr/items/10590400585-nike-black-airforces"


def test_brand_size_and_condition_are_read_back_from_the_display_lines() -> None:
    item = parse_item(search_entry(10590400585), "fr")

    assert (item.brand, item.size, item.condition) == ("Nike", "38", "Très bon état")


def test_a_listing_without_a_size_keeps_its_brand_and_condition() -> None:
    item = parse_item(search_entry(10590422667), "fr")

    assert (item.brand, item.size, item.condition) == ("Valentino Rossi", None, "Très bon état")


def test_a_listing_without_a_brand_does_not_take_its_title_as_one() -> None:
    item = parse_item(search_entry(10590423322), "fr")

    assert item.brand is None


def test_display_keys_vinted_left_untranslated_read_as_absent() -> None:
    entry = search_entry(10590400585)
    entry["item_box"]["second_line"] = "size.776.title · status.6.title"

    item = parse_item(entry, "bg")

    assert (item.size, item.condition) == (None, None)


def test_search_results_carry_the_total_price_with_buyer_protection() -> None:
    item = parse_item(search_entry(10590400585), "fr")

    assert (item.price, item.total_price, item.currency) == (
        Decimal("39.99"),
        Decimal("42.69"),
        "EUR",
    )


def test_search_results_no_longer_say_when_a_listing_was_posted() -> None:
    item = parse_item(search_entry(10590400585), "fr")

    assert item.photo_ts is None


def test_a_wardrobe_listing_reads_its_plain_fields() -> None:
    entry = recorded("wardrobe_fr.json")["items"][0]

    item = parse_item(entry, "fr")

    assert (item.brand, item.size, item.condition) == ("Nike", "38", "Très bon état")


def test_a_wardrobe_listing_still_has_its_photo_time_and_gallery() -> None:
    entry = recorded("wardrobe_fr.json")["items"][0]

    item = parse_item(entry, "fr")

    assert (item.photo_ts, len(item.photo_urls)) == (1793318885, 6)


# --- Members --------------------------------------------------------------------------


def test_a_member_profile_gives_country_stars_and_review_count() -> None:
    seller = parse_seller(recorded("user_fr.json")["user"], "fr")

    assert (seller.country_code, seller.rating, seller.feedback_count) == ("IE", 5.0, 14)


def test_a_member_without_reviews_has_no_rating_rather_than_zero_stars() -> None:
    user = recorded("user_fr.json")["user"] | {"feedback_reputation": 0, "feedback_count": 0}

    assert parse_seller(user, "fr").rating is None


def test_a_member_without_an_id_is_rejected() -> None:
    with pytest.raises(ParseError):
        parse_seller({"login": "nobody"}, "fr")
