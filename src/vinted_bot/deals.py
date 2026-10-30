"""What makes a listing a deal, and what reselling it would leave you.

One definition, used everywhere a listing is called cheap: the search filters, the
per-destination routing and every alert's badge. They used to keep their own thresholds
(the badge said "deal" at 20%, a destination's "only deals" meant something else), and a
tier that means different things in two places is a tier nobody can route on.

Nothing here does I/O or knows about the database.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, get_args

# How far under the search's typical price a listing has to be for each tier. Smaller gaps
# are noise: the median wobbles by that much between checks.
STEAL_PCT = 40
DEAL_PCT = 20

Tier = Literal["steal", "deal", "normal"]
TIERS: tuple[Tier, ...] = get_args(Tier)

_CENT = Decimal("0.01")
_HUNDRED = Decimal(100)

# The currency each country site prices in, where it is not the euro. A resale price is
# typed in the search's own site's currency, so a margin is only worked out for listings
# priced in that currency: pounds minus euros is not a number anyone can act on.
_SITE_CURRENCY = {
    "co.uk": "GBP",
    "com": "USD",
    "pl": "PLN",
    "cz": "CZK",
    "se": "SEK",
    "dk": "DKK",
    "hu": "HUF",
    "ro": "RON",
}


def deal_percent(total: Decimal | None, typical: Decimal | None) -> int | None:
    """How far under the typical price a total is, in whole percent; negative if over."""
    if total is None or typical is None or typical <= 0:
        return None
    return round((typical - total) / typical * 100)


def tier_for(pct: int | None) -> Tier:
    """The tier for a distance under the typical price. No typical price is no claim."""
    if pct is None:
        return "normal"
    if pct >= STEAL_PCT:
        return "steal"
    if pct >= DEAL_PCT:
        return "deal"
    return "normal"


def site_currency(tld: str) -> str:
    return _SITE_CURRENCY.get(tld, "EUR")


def margin(
    total: Decimal | None,
    currency: str | None,
    *,
    site: str,
    resale_price: Decimal | None,
    fee_pct: float | None = None,
    shipping: Decimal | None = None,
) -> Decimal | None:
    """What is left after buying at `total` and reselling at `resale_price`.

    The resale side loses `fee_pct` percent to the platform it is sold on and `shipping`
    to the post. None when there is no resale price, no total, or the listing is priced
    in a different currency from the search's own site.
    """
    if resale_price is None or total is None:
        return None
    if (currency or "").upper() != site_currency(site):
        return None
    fee = Decimal(str(fee_pct or 0)) / _HUNDRED
    kept = resale_price * (1 - fee) - (shipping or Decimal(0))
    return (kept - total).quantize(_CENT)
