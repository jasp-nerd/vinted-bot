"""One listing, worked out once, before any channel formats it.

Every sender used to make its own decisions about which price leads, how a rating reads and
which links exist, and they drifted apart: Discord said "4.8 stars" where Telegram said
"96%". Now the decisions live here and the channel modules only lay the result out, so a
Discord card, a Telegram caption and an ntfy push always agree.

Nothing here does I/O, which is also what lets the dashboard preview an alert without
sending one.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from urllib.parse import quote, quote_plus, urljoin, urlparse

from vinted_bot.db.repo import PendingNotification
from vinted_bot.deals import Tier, deal_percent, tier_for
from vinted_bot.deliver.labels import (
    MINUS,
    Labels,
    format_money,
    format_rough_money,
    labels_for,
)
from vinted_bot.vinted import urls

BOT_NAME = "vinted-bot"
ICON_URL = "https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docs/media/icon-256.png"

# Accent colours. Green means "act on this"; the brand teal is for searches without a
# colour of their own; the grey is for messages about the app rather than a listing.
DEAL_COLOUR = 0x28865A
BRAND_COLOUR = 0x007782
STATUS_COLOUR = 0x5A6566

# Kinds a listing alert can be. Watches (price drops, sales) are things the user asked to
# follow explicitly; the rest are search matches.
KINDS = ("listing", "price_drop", "sold", "reserved", "removed", "seller_upload")

# Long titles are cut here everywhere. Vinted's own limit is about this, and anything
# longer is keyword stuffing that pushes the price off a phone screen.
MAX_TITLE = 120
MAX_SEARCH_NAME = 60
MAX_FACT = 60
# Searches on eBay past a dozen words find nothing; the first eighty characters of a
# Vinted title are the brand and model, the rest is condition and size.
MAX_QUERY = 80

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0"})

_ISO_BY_TLD = {"co.uk": "GB", "com": "US"}

# Which eBay answers "what does this actually sell for" for someone on each Vinted site.
# Belgium's French-language eBay lives on its own host; everything unlisted gets the
# international site.
_EBAY_BY_TLD = {
    "fr": "www.ebay.fr",
    "de": "www.ebay.de",
    "co.uk": "www.ebay.co.uk",
    "it": "www.ebay.it",
    "es": "www.ebay.es",
    "nl": "www.ebay.nl",
    "be": "www.befr.ebay.be",
    "pl": "www.ebay.pl",
    "at": "www.ebay.at",
    "ie": "www.ebay.ie",
    "com": "www.ebay.com",
}
_EBAY_DEFAULT = "www.ebay.com"

# Markdown characters that act anywhere in a line. The ones that only matter at the start
# of a line (#, >, -, 1.) are left alone: user text never starts one of our lines, and
# Apprise hands markdown unconverted to text-only services, where every needless
# backslash would show.
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]()])")


@dataclass(frozen=True, slots=True)
class Deal:
    tier: Literal["steal", "deal"]
    pct: int


@dataclass(frozen=True, slots=True)
class ListingView:
    """Everything a channel shows about one listing, already decided and formatted."""

    outbox_id: int
    # None for alerts from a watch rather than a search.
    query_id: int | None
    kind: str
    labels: Labels
    title: str
    url: str
    photos: tuple[str, ...]
    # The total including buyer protection: the number a buying decision compares.
    price: str | None
    # What the seller asks, shown under the total only when the two differ.
    asking: str | None
    previous_price: str | None
    typical: str | None
    deal: Deal | None
    # Signed: negative means dearer than usual. Kept for the JSON webhook even when it
    # is too small to badge.
    deal_pct: int | None
    # Which tier the listing falls in, for routing: "normal" when it is not notably cheap
    # or there is no typical price to compare with.
    tier: Tier
    # What reselling it would leave, already written as "+€19", when the search has a
    # resale price.
    margin: str | None
    size: str | None
    condition: str | None
    brand: str | None
    seller_login: str | None
    seller_url: str | None
    rating: str | None
    site: str
    flag: str
    # When the listing went up, or failing that when we first saw it. `listed_known`
    # says which, so the label can be honest: Vinted's search no longer says when a
    # listing went up, and calling the moment we found it "listed" claims a speed nobody
    # can check.
    listed_at: int
    listed_known: bool
    search_name: str
    search_url: str | None
    dashboard_url: str | None
    buy_url: str
    message_url: str
    favourites: int
    accent: int
    silent: bool
    item_id: int
    seller_id: int | None
    price_check_url: str
    photo_search_url: str | None

    @property
    def headline(self) -> str:
        """The one-line reason this alert exists."""
        labels = self.labels
        match self.kind:
            case "price_drop":
                return labels.price_drop
            case "sold":
                return labels.sold
            case "reserved":
                return labels.reserved
            case "removed":
                return labels.removed
            case "seller_upload":
                return labels.new_from.format(seller=self.seller_login or labels.seller)
            case _:
                return labels.new_match

    @property
    def time_label(self) -> str:
        """ "listed" when Vinted said when, "found" when the time is our own."""
        return self.labels.listed if self.listed_known else self.labels.found

    @property
    def margin_text(self) -> str | None:
        """ "margin ~+€19", or None without a resale price."""
        return f"{self.labels.margin} ~{self.margin}" if self.margin else None

    @property
    def summary(self) -> list[str]:
        """What follows the price on the first line: the deal badge and the margin.

        The first line is the one a phone shows on the lock screen, so it carries
        everything a buy-or-skip decision needs and nothing else.
        """
        return [part for part in (self.short_badge, self.margin_text) if part]

    @property
    def first_line_text(self) -> str:
        """The first line as plain text, for push titles that take no formatting."""
        line = " · ".join(part for part in (self.price, *self.summary, self.title) if part)
        return f"{self.headline}: {line}" if self.kind != "listing" else line

    @property
    def short_badge(self) -> str | None:
        """The tier and how far under typical, without the basis, for the first line."""
        if self.deal is None:
            return None
        tier = self.labels.steal if self.deal.tier == "steal" else self.labels.good_deal
        return f"{tier} {MINUS}{self.deal.pct}%"

    @property
    def badge(self) -> str | None:
        """ "Steal, 46% under typical" as a short badge, or None when it is not notably cheap."""
        if self.deal is None:
            return None
        tier = self.labels.steal if self.deal.tier == "steal" else self.labels.good_deal
        return f"{tier} {MINUS}{self.deal.pct}% {self.labels.vs_typical}"

    @property
    def can_buy(self) -> bool:
        """A sold, reserved or removed listing has nothing left to buy or ask about."""
        return self.kind not in {"sold", "reserved", "removed"}

    @property
    def facts(self) -> list[tuple[str, str]]:
        """Size, condition and brand, whichever the listing has, labelled."""
        pairs = [
            (self.labels.size, self.size),
            (self.labels.condition, self.condition),
            (self.labels.brand, self.brand),
        ]
        return [(label, value) for label, value in pairs if value]

    @property
    def price_note(self) -> str | None:
        """The small print under the price: what the seller asks, and the usual price."""
        parts = []
        if self.asking:
            parts.append(f"{self.asking} {self.labels.plus_protection}")
        if self.typical:
            parts.append(f"{self.labels.typical} ~{self.typical}")
        return " · ".join(parts) or None


def escape_markdown(text: str) -> str:
    """User text made inert for generic markdown: no links, emphasis or raw HTML.

    `<` becomes an entity rather than a backslash escape because markdown passes HTML
    through untouched, and an email built from a title saying <img src=...> should not
    load anything.
    """
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text).replace("<", "&lt;")


def deal_for(pct: int | None) -> Deal | None:
    """The badge-worthy part of a tier: None for an ordinary price."""
    tier = tier_for(pct)
    if pct is None or tier == "normal":
        return None
    return Deal(tier, pct)


def price_check_url(title: str, tld: str) -> str:
    """eBay's sold listings for this title, on the eBay that matches the Vinted site.

    Sold and completed rather than live listings: what things actually went for is the
    number a reseller checks, and asking prices are what the typical price already shows.
    """
    host = _EBAY_BY_TLD.get(tld, _EBAY_DEFAULT)
    return f"https://{host}/sch/i.html?_nkw={quote_plus(title)}&LH_Sold=1&LH_Complete=1"


def photo_search_url(photo: str) -> str:
    """Google Lens on the listing photo: finds the model, and stolen stock photos."""
    return f"https://lens.google.com/uploadbyurl?url={quote(photo, safe='')}"


def reachable_dashboard(url: str | None) -> str | None:
    """The dashboard address, unless it only works on the machine running the app.

    Alerts are mostly read on a phone, where a link to 127.0.0.1 is a button that does
    nothing. Setting WEB_PUBLIC_URL (or binding to a real address) brings the link back.
    """
    if not url:
        return None
    host = urlparse(url).hostname or ""
    return None if host in _LOOPBACK_HOSTS else url.rstrip("/")


def site_flag(tld: str) -> str:
    """The country site as a flag. It is where the listing is, not where the seller is."""
    return country_flag(_ISO_BY_TLD.get(tld, tld.upper()))


def country_flag(iso: str) -> str:
    """A two-letter country code as its flag, or "" for anything else."""
    iso = iso.upper()
    if len(iso) != 2 or not iso.isascii() or not iso.isalpha():  # noqa: PLR2004 - two letters
        return ""
    return "".join(chr(0x1F1E6 + ord(letter) - ord("A")) for letter in iso)


def absolute(url: str, tld: str) -> str:
    """Make a listing link absolute. Vinted's newer API answers with site-relative paths,
    and Discord and Telegram reject anything that is not a full https URL."""
    if url.startswith(("https://", "http://")):
        return url
    return urljoin(urls.site_root(tld), url)


def parse_colour(value: str | None) -> int | None:
    """A "#rrggbb" search colour as the integer Discord wants, or None if it is not one."""
    if not value:
        return None
    digits = value.strip().removeprefix("#")
    if len(digits) != 6:  # noqa: PLR2004 - rrggbb
        return None
    try:
        return int(digits, 16)
    except ValueError:
        return None


def _clip(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _rating(
    rating: float | None, reviews: int | None, country: str | None, labels: Labels
) -> str | None:
    """Vinted's 0..1 reputation as the five-star figure people know, with its review count,
    and the flag of the seller's country when a lookup told us it."""
    if reviews == 0:
        text = labels.new_seller
    elif rating is None:
        text = None
    else:
        stars = f"★ {round(rating * 50) / 10:.1f}"
        text = f"{stars} ({reviews})" if reviews else stars
    flag = country_flag(country) if country else ""
    return " · ".join(part for part in (text, flag) if part) or None


def view(notification: PendingNotification, *, dashboard_url: str | None) -> ListingView:
    """Decide how one queued notification should read."""
    item = notification.item
    labels = labels_for(item.tld)
    currency = item.currency

    def money(amount: Decimal | None) -> str | None:
        return format_money(amount, currency, labels.locale) if amount is not None else None

    total = item.total_price if item.total_price is not None else item.price
    asking = item.price if item.total_price is not None and item.price != total else None
    pct = deal_percent(total, notification.typical_price)
    deal = deal_for(pct)
    dashboard = reachable_dashboard(dashboard_url)

    accent = parse_colour(notification.query_color) or BRAND_COLOUR
    if deal is not None:
        accent = DEAL_COLOUR

    photos = tuple(
        absolute(photo, item.tld)
        for photo in (item.photo_urls or ((item.photo_url,) if item.photo_url else ()))
    )
    title = _clip(item.title, MAX_TITLE) or f"#{item.item_id}"
    margin = notification.margin

    return ListingView(
        outbox_id=notification.outbox_id,
        query_id=notification.query_id,
        kind=notification.kind if notification.kind in KINDS else "listing",
        labels=labels,
        title=title,
        url=absolute(item.url, item.tld),
        photos=photos,
        price=money(total),
        asking=money(asking),
        previous_price=money(notification.previous_price),
        typical=money(notification.typical_price),
        deal=deal,
        deal_pct=pct,
        tier=tier_for(pct),
        margin=format_rough_money(margin, currency, labels.locale) if margin is not None else None,
        size=_clip(item.size, MAX_FACT),
        condition=_clip(item.condition, MAX_FACT),
        brand=_clip(item.brand, MAX_FACT),
        seller_login=_clip(item.seller_login, MAX_FACT),
        seller_url=item.seller_url,
        rating=_rating(
            item.seller_rating, item.seller_feedback_count, notification.seller_country, labels
        ),
        site=f"vinted.{item.tld}",
        flag=site_flag(item.tld),
        listed_at=item.photo_ts or notification.detected_at or int(time.time()),
        listed_known=item.photo_ts is not None,
        search_name=_clip(notification.query_name, MAX_SEARCH_NAME) or "search",
        search_url=(
            f"{dashboard}/searches/{notification.query_id}"
            if dashboard and notification.query_id is not None
            else None
        ),
        dashboard_url=dashboard,
        # A link that is no listing page (the test alert's sample, which opens a real
        # search instead) has no buy or message page behind it either.
        buy_url=item.buy_url if "/items/" in item.url else absolute(item.url, item.tld),
        message_url=item.message_url if "/items/" in item.url else absolute(item.url, item.tld),
        favourites=item.favourite_count,
        accent=accent,
        silent=notification.silent,
        item_id=item.item_id,
        seller_id=item.seller_id,
        price_check_url=price_check_url(
            " ".join(item.title.split())[:MAX_QUERY] or title, item.tld
        ),
        photo_search_url=photo_search_url(photos[0]) if photos else None,
    )
