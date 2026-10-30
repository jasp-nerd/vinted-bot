"""The one definition of a deal, and the resale margin."""

from __future__ import annotations

from decimal import Decimal

import pytest

from vinted_sniper.deals import deal_percent, margin, tier_for


@pytest.mark.parametrize(
    ("total", "tier"),
    [("5.40", "steal"), ("6.00", "steal"), ("7.90", "deal"), ("8.50", "normal"), ("12", "normal")],
)
def test_tiers_follow_the_distance_from_the_typical_price(total: str, tier: str) -> None:
    assert tier_for(deal_percent(Decimal(total), Decimal("10"))) == tier


def test_without_a_typical_price_a_listing_is_normal() -> None:
    assert tier_for(deal_percent(Decimal("5"), None)) == "normal"


def test_dearer_than_usual_is_a_negative_percentage() -> None:
    assert deal_percent(Decimal("12"), Decimal("10")) == -20


def test_margin_takes_the_fee_and_the_postage_off_the_resale_price() -> None:
    """60 resold on eBay at 10% is 54 kept, minus 5 postage is 49, minus 30 paid is 19."""
    assert margin(
        Decimal("30.00"),
        "EUR",
        site="fr",
        resale_price=Decimal("60"),
        fee_pct=10,
        shipping=Decimal("5"),
    ) == Decimal("19.00")


def test_a_margin_without_costs_is_the_plain_difference() -> None:
    assert margin(Decimal("42.90"), "EUR", site="de", resale_price=Decimal("50")) == Decimal("7.10")


def test_a_margin_can_be_a_loss() -> None:
    assert margin(Decimal("55"), "EUR", site="fr", resale_price=Decimal("50")) == Decimal("-5.00")


def test_no_resale_price_means_no_margin() -> None:
    assert margin(Decimal("10"), "EUR", site="fr", resale_price=None) is None


def test_a_listing_in_another_currency_gets_no_margin() -> None:
    """A search on vinted.fr also running on vinted.co.uk: pounds minus euros is nothing."""
    assert margin(Decimal("10"), "GBP", site="fr", resale_price=Decimal("50")) is None


def test_a_pound_search_works_out_a_pound_margin() -> None:
    assert margin(Decimal("10"), "GBP", site="co.uk", resale_price=Decimal("25")) == Decimal(
        "15.00"
    )
