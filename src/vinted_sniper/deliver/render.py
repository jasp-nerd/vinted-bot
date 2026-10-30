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
from urllib.parse import urljoin, urlparse

from vinted_sniper.db.repo import PendingNotification
from vinted_sniper.deliver.labels import Labels, format_money, labels_for
from vinted_sniper.vinted import urls

BOT_NAME = "vinted-sniper"
ICON_URL = "https://raw.githubusercontent.com/jasp-nerd/vinted-sniper/main/docs/media/icon-256.png"

# Accent colours. Green means "act on this"; the brand teal is for searches without a
# colour of their own; the grey is for messages about the app rather than a listing.
DEAL_COLOUR = 0x28865A
BRAND_COLOUR = 0x007782
STATUS_COLOUR = 0x5A6566

# How far under the search's typical price a listing has to be before we call it out.
# Smaller gaps are noise: the median wobbles by that much between polls.
STEAL_PCT = 40
GOOD_DEAL_PCT = 20

# Kinds a listing alert can be. Watches (price drops, sales) are things the user asked to
# follow explicitly; the rest are search matches.
KINDS = ("listing", "price_drop", "sold", "reserved", "seller_upload")

# Long titles are cut here everywhere. Vinted's own limit is about this, and anything
# longer is keyword stuffing that pushes the price off a phone screen.
MAX_TITLE = 120
MAX_SEARCH_NAME = 60
MAX_FACT = 60

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0"})

_ISO_BY_TLD = {"co.uk": "GB", "com": "US"}

# Markdown characters that act anywhere in a line. The ones that only matter at the start
# of a line (#, >, -, 1.) are left alone: user text never starts one of our lines, and
# Apprise hands markdown unconverted to text-only services, where every needless
# backslash would show.
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]()])")

# A real minus sign: a hyphen in "-46%" reads as a dash, and wraps like one.
MINUS = "\u2212"


@dataclass(frozen=True, slots=True)
class Deal:
    tier: Literal["steal", "good"]
    pct: int


@dataclass(frozen=True, slots=True)
class ListingView:
    """Everything a channel shows about one listing, already decided and formatted."""

    outbox_id: int
    query_id: int
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
    size: str | None
    condition: str | None
    brand: str | None
    seller_login: str | None
    seller_url: str | None
    rating: str | None
    site: str
    flag: str
    # When the listing went up, or failing that when we first saw it.
    listed_at: int
    search_name: str
    search_url: str | None
    dashboard_url: str | None
    buy_url: str
    message_url: str
    favourites: int
    accent: int
    silent: bool

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
            case "seller_upload":
                return labels.new_from.format(seller=self.seller_login or labels.seller)
            case _:
                return labels.new_match

    @property
    def badge(self) -> str | None:
        """ "Steal, 46% under typical" as a short badge, or None when it is not notably cheap."""
        if self.deal is None:
            return None
        tier = self.labels.steal if self.deal.tier == "steal" else self.labels.good_deal
        return f"{tier} {MINUS}{self.deal.pct}% {self.labels.vs_typical}"

    @property
    def can_buy(self) -> bool:
        """A sold or reserved listing has nothing left to buy or ask about."""
        return self.kind not in {"sold", "reserved"}

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


def deal_pct(total: Decimal | None, typical: Decimal | None) -> int | None:
    """How far under the typical price a total is, in whole percent."""
    if total is None or typical is None or typical <= 0:
        return None
    return round((1 - total / typical) * 100)


def deal_for(pct: int | None) -> Deal | None:
    if pct is None:
        return None
    if pct >= STEAL_PCT:
        return Deal("steal", pct)
    if pct >= GOOD_DEAL_PCT:
        return Deal("good", pct)
    return None


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
    iso = _ISO_BY_TLD.get(tld, tld.upper())
    if len(iso) != 2 or not iso.isalpha():  # noqa: PLR2004 - flags are two letters
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


def _rating(rating: float | None, reviews: int | None, labels: Labels) -> str | None:
    """Vinted's 0..1 reputation as the five-star figure people know, with its review count."""
    if reviews == 0:
        return labels.new_seller
    if rating is None:
        return None
    stars = f"★ {round(rating * 50) / 10:.1f}"
    return f"{stars} ({reviews})" if reviews else stars


def view(notification: PendingNotification, *, dashboard_url: str | None) -> ListingView:
    """Decide how one queued notification should read."""
    item = notification.item
    labels = labels_for(item.tld)
    currency = item.currency

    def money(amount: Decimal | None) -> str | None:
        return format_money(amount, currency, labels.locale) if amount is not None else None

    total = item.total_price if item.total_price is not None else item.price
    asking = item.price if item.total_price is not None and item.price != total else None
    pct = deal_pct(total, notification.typical_price)
    deal = deal_for(pct)
    dashboard = reachable_dashboard(dashboard_url)

    accent = parse_colour(notification.query_color) or BRAND_COLOUR
    if deal is not None:
        accent = DEAL_COLOUR

    photos = tuple(
        absolute(photo, item.tld)
        for photo in (item.photo_urls or ((item.photo_url,) if item.photo_url else ()))
    )

    return ListingView(
        outbox_id=notification.outbox_id,
        query_id=notification.query_id,
        kind=notification.kind if notification.kind in KINDS else "listing",
        labels=labels,
        title=_clip(item.title, MAX_TITLE) or f"#{item.item_id}",
        url=absolute(item.url, item.tld),
        photos=photos,
        price=money(total),
        asking=money(asking),
        previous_price=money(notification.previous_price),
        typical=money(notification.typical_price),
        deal=deal,
        deal_pct=pct,
        size=_clip(item.size, MAX_FACT),
        condition=_clip(item.condition, MAX_FACT),
        brand=_clip(item.brand, MAX_FACT),
        seller_login=_clip(item.seller_login, MAX_FACT),
        seller_url=item.seller_url,
        rating=_rating(item.seller_rating, item.seller_feedback_count, labels),
        site=f"vinted.{item.tld}",
        flag=site_flag(item.tld),
        listed_at=item.photo_ts or notification.detected_at or int(time.time()),
        search_name=_clip(notification.query_name, MAX_SEARCH_NAME) or "search",
        search_url=f"{dashboard}/searches/{notification.query_id}" if dashboard else None,
        dashboard_url=dashboard,
        buy_url=item.buy_url,
        message_url=item.message_url,
        favourites=item.favourite_count,
        accent=accent,
        silent=notification.silent,
    )
