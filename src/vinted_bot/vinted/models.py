"""The shape of a listing, a seller, and a re-read item page.

Every `Item` field comes out of one search response, so a notification never needs a
second request. Parsing is deliberately forgiving: Vinted renames and reshapes fields
without warning, and a missing size should cost you the size line, not the alert.

What a search response carries changed in September 2026, when search moved to
`svc-catalogue`. Brand, size and condition survive only inside the localised display
lines of `item_box`; the seller's rating, the photo upload time and all photos but the
cover are gone. The older field names are still read first, because a member's wardrobe
(`/api/v2/wardrobe`) still answers in the old, richer shape.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict

from vinted_bot.vinted import urls


class ParseError(ValueError):
    """A listing was missing something we cannot sensibly invent, such as its id."""


class Item(BaseModel):
    """One Vinted listing, as much as the search response tells us about it."""

    model_config = ConfigDict(frozen=True)

    item_id: int
    tld: str
    title: str
    url: str

    brand: str | None = None
    size: str | None = None
    condition: str | None = None

    price: Decimal | None = None
    # What the buyer is actually charged, buyer protection included. Filters and
    # notifications lead with this, because it is the number people compare.
    total_price: Decimal | None = None
    currency: str | None = None

    photo_url: str | None = None
    # Every photo the response names, in order, cover first. Search results carry only
    # the cover since September 2026; a member's wardrobe and the item page carry all.
    photo_urls: tuple[str, ...] = ()
    # The main photo's upload time, the closest thing to "listed at" Vinted ever exposed.
    # Search results no longer carry it (always None there); wardrobe listings still do.
    photo_ts: int | None = None

    seller_login: str | None = None
    seller_id: int | None = None
    # Vinted's 0-1 reputation. Absent from search results now; see `SellerProfile`.
    seller_rating: float | None = None
    # How many reviews sit behind the rating. A 4.8 from three reviews and a 4.8 from
    # three hundred are different offers, so notifications show both together.
    seller_feedback_count: int | None = None

    promoted: bool = False
    favourite_count: int = 0
    view_count: int = 0

    # Vinted's own one-line description of the listing, already localised.
    summary: str | None = None
    raw: dict[str, Any] | None = None

    @property
    def listed_at(self) -> datetime | None:
        if self.photo_ts is None:
            return None
        return datetime.fromtimestamp(self.photo_ts, tz=UTC)

    @property
    def message_url(self) -> str:
        return urls.message_seller_url(self.tld, self.item_id)

    @property
    def buy_url(self) -> str:
        return urls.buy_url(self.tld, self.item_id)

    @property
    def seller_url(self) -> str | None:
        if self.seller_id is None:
            return None
        return urls.member_url(self.tld, self.seller_id)

    def price_line(self) -> str:
        """Price as a human reads it, showing the total when it differs from the ask."""
        if self.price is None:
            return "price unknown"
        currency = f" {self.currency}" if self.currency else ""
        if self.total_price is not None and self.total_price != self.price:
            return f"{self.price}{currency} ({self.total_price}{currency} with protection)"
        return f"{self.price}{currency}"


class SellerProfile(BaseModel):
    """What the public member page says about a seller.

    The catalog response names the seller but not where they ship from, so the country
    filter needs this second, cacheable lookup. Only fetched when a search asks for it.
    """

    model_config = ConfigDict(frozen=True)

    seller_id: int
    tld: str
    login: str | None = None
    # ISO 3166 alpha-2, e.g. 'FR'. None when the member hides their location.
    country_code: str | None = None
    # Stars, 0-5, as the site shows them. None for a member with no reviews yet.
    rating: float | None = None
    feedback_count: int | None = None
    business: bool = False


ItemStatus = Literal["available", "reserved", "sold", "gone"]


class ItemSnapshot(BaseModel):
    """A single listing re-read from its own page, for watching price drops and sales.

    The page also carries everything the search response lost (every photo, brand, size,
    condition, the seller's rating), so one fetch can enrich a listing that matched.
    """

    model_config = ConfigDict(frozen=True)

    item_id: int
    tld: str
    title: str | None = None
    # In the listing's own currency, which is the seller's. Search results on another
    # country's site show a converted amount instead (a Swedish listing seen on vinted.pl
    # is 649 SEK here and 261.75 PLN there), so compare snapshots with snapshots.
    price: Decimal | None = None
    # Not on the page: the buyer-protection fee is loaded separately by the site. Only
    # the search response has it.
    total_price: Decimal | None = None
    currency: str | None = None
    # 'available', 'reserved', 'sold' or 'gone' (the page no longer exists).
    status: ItemStatus = "available"
    photo_url: str | None = None
    photo_urls: tuple[str, ...] = ()
    brand: str | None = None
    size: str | None = None
    condition: str | None = None
    color: str | None = None
    description: str | None = None
    seller_id: int | None = None
    seller_login: str | None = None
    # Vinted's 0-1 reputation, the same scale as `Item.seller_rating`. None without reviews.
    seller_rating: float | None = None
    seller_feedback_count: int | None = None


DiagnosisProblem = Literal["offline", "blocked", "rate_limited", "api_changed", "unexpected"]


class Diagnosis(BaseModel):
    """Whether Vinted can be reached from this computer, in words a person can act on.

    `problem` is None when everything worked; otherwise it names the failure so the
    dashboard can link the matching troubleshooting section.
    """

    model_config = ConfigDict(frozen=True)

    tld: str
    reachable: bool
    got_session_cookie: bool
    catalog_ok: bool
    http_status: int | None
    message: str
    elapsed_ms: int
    problem: DiagnosisProblem | None = None


def first_of(source: dict[str, Any], *paths: str) -> Any:
    """Return the first present value among dotted paths. Tolerates renamed fields."""
    for path in paths:
        value: Any = source
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                value = None
                break
            value = value[part]
        if value is not None:
            return value
    return None


def money(value: Any) -> tuple[Decimal | None, str | None]:
    """Read a price, which arrives either as {'amount', 'currency_code'} or a bare number."""
    if value is None:
        return None, None
    if isinstance(value, dict):
        amount, currency = value.get("amount"), value.get("currency_code")
    else:
        amount, currency = value, None
    try:
        return (Decimal(str(amount)) if amount is not None else None), currency
    except (InvalidOperation, ValueError):
        return None, currency


def clean_text(value: Any) -> str | None:
    """Normalise a text field, treating blanks and Vinted's 'no brand' marker as absent."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or stripped.upper() == "NO LABEL":
        return None
    return stripped


# A display key Vinted failed to translate, e.g. 'size.776.title'. Seen on sites whose
# locale it does not support; worse than nothing as a size or condition.
_UNTRANSLATED: Final = re.compile(r"^[a-z_]+\.\d+\.[a-z_]+$")
_BOX_SEPARATOR: Final = " · "


def _box_fields(payload: dict[str, Any], title: str | None) -> tuple[str | None, ...]:
    """Brand, size and condition read back out of `item_box`'s display lines.

    `first_line` is the brand, or the title when the listing has none. `second_line` is
    "size · condition", or just the condition for things that have no size. Which of
    the two `first_line` holds is settled by the accessibility label, which spells out
    "<Brand label>: <brand>," in whatever language the site uses.
    """
    box = payload.get("item_box")
    if not isinstance(box, dict):
        return None, None, None

    first = clean_text(box.get("first_line"))
    label = box.get("accessibility_label")
    if not first:
        brand = None
    elif isinstance(label, str) and label:
        brand = first if f": {first}," in label else None
    else:
        brand = first if first != title else None

    parts = [part.strip() for part in str(box.get("second_line") or "").split(_BOX_SEPARATOR)]
    parts = [part for part in parts if part and not _UNTRANSLATED.match(part)]
    condition = parts[-1] if parts else None
    size = parts[0] if len(parts) >= 2 else None  # noqa: PLR2004 - "size · condition"
    return brand, size, condition


def absolute_url(tld: str, url: Any) -> str | None:
    """Make a site-relative path ('/items/1-x') absolute on the right country site."""
    if not isinstance(url, str) or not url:
        return None
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("/"):
        return f"https://www.vinted.{tld}{url}"
    return None


def parse_item(payload: dict[str, Any], tld: str, *, keep_raw: bool = False) -> Item:
    """Build an Item from one entry of a search or wardrobe response."""
    raw_id = first_of(payload, "id", "item_id")
    try:
        item_id = int(raw_id)
    except (TypeError, ValueError) as exc:
        raise ParseError(f"listing has no usable id: {raw_id!r}") from exc

    price, currency = money(first_of(payload, "price"))
    total_price, total_currency = money(first_of(payload, "total_item_price"))

    photo = first_of(payload, "photo") or {}
    if not isinstance(photo, dict):
        photo = {}
    photos = payload.get("photos")
    if not photo and isinstance(photos, list) and photos and isinstance(photos[0], dict):
        # Wardrobe listings have no separate cover; the first photo is it.
        photo = photos[0]

    photo_url = first_of(photo, "full_size_url", "url")
    photo_urls = photo_urls_of(photos, photo_url)

    user = first_of(payload, "user") or {}
    if not isinstance(user, dict):
        user = {}

    title = clean_text(first_of(payload, "title"))
    box_brand, box_size, box_condition = _box_fields(payload, title)

    return Item(
        item_id=item_id,
        tld=tld,
        title=title or f"Listing {item_id}",
        url=absolute_url(tld, first_of(payload, "url", "path")) or urls.item_url(tld, item_id),
        brand=clean_text(first_of(payload, "brand_title", "brand.title", "brand")) or box_brand,
        size=clean_text(first_of(payload, "size_title", "size.title", "size")) or box_size,
        condition=clean_text(first_of(payload, "status", "condition")) or box_condition,
        price=price,
        total_price=total_price,
        currency=currency or total_currency,
        photo_url=photo_url,
        photo_urls=photo_urls,
        photo_ts=coerce_int(first_of(photo, "high_resolution.timestamp")),
        seller_login=clean_text(first_of(user, "login")),
        seller_id=coerce_int(first_of(user, "id")) or coerce_int(first_of(payload, "user_id")),
        seller_rating=coerce_float(first_of(user, "feedback_reputation")),
        seller_feedback_count=coerce_int(first_of(user, "feedback_count")),
        promoted=bool(first_of(payload, "promoted") or False),
        favourite_count=coerce_int(first_of(payload, "favourite_count")) or 0,
        view_count=coerce_int(first_of(payload, "view_count")) or 0,
        summary=clean_text(first_of(payload, "item_box.accessibility_label")),
        raw=payload if keep_raw else None,
    )


def parse_seller(payload: dict[str, Any], tld: str) -> SellerProfile:
    """Build a SellerProfile from `/api/v2/users/{id}`'s `user` object."""
    seller_id = coerce_int(payload.get("id"))
    if seller_id is None:
        raise ParseError(f"member has no usable id: {payload.get('id')!r}")

    country = clean_text(first_of(payload, "country_iso_code", "country_code"))
    reputation = coerce_float(payload.get("feedback_reputation"))
    reviews = coerce_int(payload.get("feedback_count"))
    # A member with no reviews reports a reputation of 0, which is not the same as being
    # rated zero stars.
    rating = round(reputation * 5, 2) if reputation is not None and reviews else None

    return SellerProfile(
        seller_id=seller_id,
        tld=tld,
        login=clean_text(payload.get("login")),
        country_code=country.upper() if country else None,
        rating=rating,
        feedback_count=reviews,
        business=bool(payload.get("business") or False),
    )


def photo_urls_of(photos: Any, cover: str | None) -> tuple[str, ...]:
    """Collect every photo URL in order, falling back to the lone cover photo."""
    urls_in_order: list[str] = []
    if isinstance(photos, list):
        for entry in photos:
            if not isinstance(entry, dict):
                continue
            url = first_of(entry, "full_size_url", "url")
            if isinstance(url, str) and url:
                urls_in_order.append(url)
    if not urls_in_order and cover:
        urls_in_order.append(cover)
    return tuple(urls_in_order)


def coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
