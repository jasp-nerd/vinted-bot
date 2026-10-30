from __future__ import annotations

import pytest

from vinted_sniper.vinted import urls


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.vinted.fr/catalog?search_text=x", "fr"),
        ("https://vinted.de/catalog?search_text=x", "de"),
        ("https://www.vinted.co.uk/catalog?search_text=x", "co.uk"),
        ("https://www.vinted.com/catalog?search_text=x", "com"),
    ],
)
def test_country_site_comes_from_the_domain(url: str, expected: str) -> None:
    assert urls.extract_tld(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.ebay.fr/catalog?search_text=x",
        "https://www.vinted.zz/catalog?search_text=x",
    ],
)
def test_non_vinted_addresses_are_refused(url: str) -> None:
    with pytest.raises(urls.InvalidSearchURLError):
        urls.extract_tld(url)


def test_array_parameters_become_api_names() -> None:
    params = urls.parse_search_params(
        "https://www.vinted.fr/catalog?catalog[]=1904&brand_ids[]=53&status[]=6&status[]=1"
    )

    assert params["catalog_ids"] == "1904"
    assert params["brand_ids"] == "53"
    assert params["status_ids"] == "6,1", "repeated filters should combine, not overwrite"


def test_category_and_brand_landing_pages_carry_their_filter_in_the_path() -> None:
    assert urls.parse_search_params("https://www.vinted.fr/catalog/1904-femmes")["catalog_ids"] == (
        "1904"
    )
    assert urls.parse_search_params("https://www.vinted.fr/brand/53-nike")["brand_ids"] == "53"


def test_tracking_parameters_are_dropped() -> None:
    params = urls.parse_search_params(
        "https://www.vinted.fr/catalog?search_text=nike&time=1700000000"
        "&search_id=12345&page=3&disabled_personalization=true&utm_source=x"
    )

    assert set(params) == {"search_text", "order"}


def test_results_are_always_requested_newest_first() -> None:
    params = urls.parse_search_params("https://www.vinted.fr/catalog?search_text=x&order=relevance")

    assert params["order"] == "newest_first"


def test_same_search_pasted_twice_normalises_to_one_key() -> None:
    first = urls.normalise_search_url(
        "https://www.vinted.fr/catalog?search_text=nike&price_to=30&time=111&search_id=a"
    )
    second = urls.normalise_search_url(
        "https://www.vinted.fr/catalog?price_to=30&search_text=nike&time=222&search_id=b&page=2"
    )

    assert first == second


def test_multi_word_searches_keep_their_plus_signs() -> None:
    normalised = urls.normalise_search_url("https://www.vinted.fr/catalog?search_text=nike+air+max")

    assert "search_text=nike+air+max" in normalised
    assert "%2B" not in normalised, "a re-encoded plus turns the search into a literal '+'"


def test_url_without_filters_is_refused_with_advice() -> None:
    with pytest.raises(urls.InvalidSearchURLError, match="no search filters"):
        urls.normalise_search_url("https://www.vinted.fr/catalog")


def test_missing_scheme_is_tolerated() -> None:
    assert urls.normalise_search_url("www.vinted.fr/catalog?search_text=x").startswith("https://")


def test_deep_links_stay_on_the_search_country_site() -> None:
    assert urls.item_url("de", 42) == "https://www.vinted.de/items/42"
    assert urls.message_seller_url("de", 42).endswith("/items/42/want_it/new")
    assert "transaction%5Bitem_id%5D=42" in urls.buy_url("de", 42)


@pytest.mark.parametrize("tld", ["hr", "si", "ee", "lv", "bg"])
def test_the_newer_country_sites_are_accepted(tld: str) -> None:
    assert urls.extract_tld(f"https://www.vinted.{tld}/catalog?search_text=x") == tld


def test_the_mobile_host_counts_as_the_same_site() -> None:
    assert urls.extract_tld("https://m.vinted.fr/catalog?search_text=x") == "fr"


def test_every_ids_filter_the_site_puts_in_the_address_bar_is_kept() -> None:
    params = urls.parse_search_params(
        "https://www.vinted.fr/catalog?video_game_platform_ids[]=1281&patterns_ids[]=7"
    )

    assert (params["video_game_platform_ids"], params["patterns_ids"]) == ("1281", "7")


def test_the_api_spelling_of_a_filter_is_understood_too() -> None:
    params = urls.parse_search_params("https://www.vinted.fr/catalog?attribute_ids[brand]=53,14")

    assert params["brand_ids"] == "53,14"


def test_a_category_brand_landing_page_carries_both_filters() -> None:
    params = urls.parse_search_params("https://www.vinted.fr/catalog/1206-vestes/brand/53-nike")

    assert (params["catalog_ids"], params["brand_ids"]) == ("1206", "53")


def test_non_numeric_ids_are_dropped_like_the_site_drops_them() -> None:
    params = urls.parse_search_params("https://www.vinted.fr/catalog?brand_ids[]=53&brand_ids[]=x")

    assert params["brand_ids"] == "53"


def test_a_decimal_comma_in_a_price_becomes_a_dot() -> None:
    params = urls.parse_search_params("https://www.vinted.pl/catalog?search_text=x&price_to=12,50")

    assert params["price_to"] == "12.5"


def test_a_price_that_is_not_a_number_is_dropped_rather_than_guessed() -> None:
    params = urls.parse_search_params("https://www.vinted.fr/catalog?search_text=x&price_to=abc")

    assert "price_to" not in params


def test_a_literal_plus_in_the_search_survives_normalising() -> None:
    normalised = urls.normalise_search_url("https://www.vinted.fr/catalog?search_text=c%2B%2B")

    assert urls.parse_search_params(normalised)["search_text"] == "c++"


def test_the_address_is_found_inside_pasted_share_text() -> None:
    normalised = urls.normalise_search_url(
        "Look at this: https://www.vinted.fr/catalog?search_text=nike great finds"
    )

    assert normalised == "https://www.vinted.fr/catalog?order=newest_first&search_text=nike"


def test_an_upper_case_scheme_is_tolerated() -> None:
    assert urls.normalise_search_url("HTTPS://www.vinted.fr/catalog?search_text=x").startswith(
        "https://www.vinted.fr/"
    )


def test_a_single_listing_link_is_refused_with_its_own_reason() -> None:
    with pytest.raises(urls.InvalidSearchURLError, match="single listing"):
        urls.normalise_search_url("https://www.vinted.fr/items/123-nike-air")


def test_a_member_link_is_refused_with_its_own_reason() -> None:
    with pytest.raises(urls.InvalidSearchURLError, match="member"):
        urls.normalise_search_url("https://www.vinted.fr/member/7-someone")


def test_an_absurdly_long_url_is_refused() -> None:
    with pytest.raises(urls.InvalidSearchURLError, match="characters long"):
        urls.normalise_search_url("https://www.vinted.fr/catalog?search_text=" + "x" * 5000)


# --- Request-time translation ---------------------------------------------------------


def test_stored_list_filters_become_attribute_ids() -> None:
    translated = urls.catalogue_params(
        {"catalog_ids": "1206", "brand_ids": "53,14", "size_ids": "208", "status_ids": "6"}
    )

    assert translated == {
        "attribute_ids[catalog]": "1206",
        "attribute_ids[brand]": "53,14",
        "attribute_ids[size]": "208",
        "attribute_ids[status]": "6",
    }


def test_scalar_parameters_keep_their_names() -> None:
    translated = urls.catalogue_params(
        {"search_text": "nike air", "currency": "EUR", "order": "newest_first", "price_from": "5"}
    )

    assert translated == {
        "search_text": "nike air",
        "currency": "EUR",
        "order": "newest_first",
        "price_from": "5",
    }


def test_a_price_stored_with_a_comma_is_fixed_on_the_way_out() -> None:
    assert urls.catalogue_params({"price_to": "12,50"}) == {"price_to": "12.5"}


def test_two_spellings_of_one_filter_merge_without_duplicates() -> None:
    translated = urls.catalogue_params({"catalog": "1206", "catalog_ids": "1206,5"})

    assert translated == {"attribute_ids[catalog]": "1206,5"}


def test_unknown_stored_keys_are_not_sent() -> None:
    assert urls.catalogue_params({"search_text": "x", "utm_source": "y"}) == {"search_text": "x"}


def test_search_goes_to_the_api_host_of_the_country_site() -> None:
    assert urls.catalog_endpoint("co.uk") == "https://api.vinted.co.uk/svc-catalogue/items"


def test_the_us_site_keeps_www_in_its_api_host() -> None:
    assert urls.catalog_endpoint("com") == "https://api.www.vinted.com/svc-catalogue/items"
