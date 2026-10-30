"""The checks every entry point shares, so the dashboard, CLI and bot cannot disagree."""

from __future__ import annotations

from decimal import Decimal

import pytest

from vinted_sniper.engine import validation
from vinted_sniper.engine.validation import InvalidInputError


@pytest.mark.parametrize(
    ("typed", "expected"),
    [("12,50", Decimal("12.50")), ("12.5", Decimal("12.50")), (" 30 ", Decimal("30.00"))],
)
def test_prices_accept_the_ways_people_write_them(typed: str, expected: Decimal) -> None:
    assert validation.parse_price(typed) == expected


def test_a_blank_price_means_no_limit() -> None:
    assert validation.parse_price("  ") is None


@pytest.mark.parametrize("typed", ["abc", "NaN", "sNaN", "Infinity", "1e999", "-5"])
def test_prices_that_are_not_prices_are_refused_not_dropped(typed: str) -> None:
    """The dashboard used to store all of these as "no limit", silently."""
    with pytest.raises(InvalidInputError):
        validation.parse_price(typed)


@pytest.mark.parametrize("typed", ["-5", "5", "abc", "1.5", str(10**20)])
def test_intervals_out_of_range_are_refused_not_clamped(typed: str) -> None:
    """-5 used to become 10, the most aggressive interval allowed."""
    with pytest.raises(InvalidInputError):
        validation.parse_interval(typed, default=60)


def test_a_blank_interval_takes_the_default() -> None:
    assert validation.parse_interval("", default=60) == 60


def test_an_invalid_regex_is_refused_with_the_reason() -> None:
    with pytest.raises(InvalidInputError, match="does not work"):
        validation.parse_regex("nike (air")


def test_quiet_hours_need_both_ends() -> None:
    with pytest.raises(InvalidInputError, match="both"):
        validation.parse_quiet_hours("23:00", None, "hold")


def test_quiet_hours_are_normalised() -> None:
    assert validation.parse_quiet_hours("7:05", "23:00", "SILENT") == ("07:05", "23:00", "silent")


def test_an_empty_quiet_window_is_refused() -> None:
    with pytest.raises(InvalidInputError, match="different time"):
        validation.parse_quiet_hours("23:00", "23:00", "hold")


def test_country_codes_are_upper_cased_and_checked() -> None:
    assert validation.parse_countries("fr, BE,fr") == ["FR", "BE"]
    with pytest.raises(InvalidInputError):
        validation.parse_countries("France")


def test_extra_sites_drop_the_primary_and_refuse_unknown_ones() -> None:
    assert validation.parse_tlds("vinted.de, fr, be", primary="fr") == ["de", "be"]
    with pytest.raises(InvalidInputError, match="not a Vinted"):
        validation.parse_tlds("xx", primary="fr")


def test_colours_are_normalised() -> None:
    assert validation.parse_color("007782") == "#007782"


@pytest.mark.parametrize("typed", ["0", "100"])
def test_deal_percentages_stay_between_1_and_99(typed: str) -> None:
    with pytest.raises(InvalidInputError):
        validation.parse_percent(typed, field="deal")


def test_ratings_are_stars() -> None:
    assert validation.parse_rating("4,5") == 4.5
    with pytest.raises(InvalidInputError):
        validation.parse_rating("6")


def test_long_names_are_refused() -> None:
    with pytest.raises(InvalidInputError):
        validation.parse_name("x" * 500, fallback="x")


def test_a_search_with_no_name_is_called_by_its_text_or_site() -> None:
    assert validation.default_search_name({"search_text": "nike air"}, "fr") == "nike air"
    assert validation.default_search_name({}, "de") == "vinted.de"


def test_time_zones_are_checked() -> None:
    assert validation.parse_timezone(":Europe/Paris") == "Europe/Paris"
    with pytest.raises(InvalidInputError):
        validation.parse_timezone("Mars/Olympus")


@pytest.mark.parametrize(("typed", "expected"), [("10", 10.0), ("12,9", 12.9), ("8 %", 8.0)])
def test_resale_fees_are_percentages(typed: str, expected: float) -> None:
    assert validation.parse_fee_pct(typed) == expected


def test_a_blank_resale_fee_means_none() -> None:
    assert validation.parse_fee_pct(" ") is None


@pytest.mark.parametrize("typed", ["100", "-1", "lots"])
def test_impossible_resale_fees_are_refused(typed: str) -> None:
    with pytest.raises(InvalidInputError):
        validation.parse_fee_pct(typed)
