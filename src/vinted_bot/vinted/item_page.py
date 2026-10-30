"""Reading a listing back from its public page.

The JSON item endpoints refuse anything that is not a real browser, so a listing's
current state comes from the page a person would open. That page is a Next.js document:
the data sits in `self.__next_f.push([1, "..."])` script chunks, as JSON inside JS string
literals. Three things in there are stable enough to rely on, and they are read in order
of how much they say:

* the sidebar item object (`{"value": {"id": "<item id>", "can_buy": ..., ...}}`), which
  is what the page's own buy button reads;
* the page "plugins" (`{"data": {...}, "name": "gallery" | "attributes" | ...}`), one per
  block on the page;
* the schema.org JSON-LD and OpenGraph tags, which outlive most redesigns because search
  engines read them.

Availability gets no guessing: if none of these says whether the listing can still be
bought, that is reported as a malformed page rather than assumed either way, since a
watcher acts on it.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final

from vinted_bot.vinted.errors import MalformedResponseError
from vinted_bot.vinted.models import (
    ItemSnapshot,
    ItemStatus,
    clean_text,
    coerce_float,
    coerce_int,
    first_of,
    money,
    photo_urls_of,
)

_FLIGHT_CHUNK: Final = re.compile(r'self\.__next_f\.push\(\[1,(".*?")\]\)</script>', re.S)
_JSON_LD: Final = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_OG_TAG: Final = re.compile(r'<meta property="og:(\w+)" content="([^"]*)"')
_PLUGIN_START: Final = '{"data":{'
_REFERENCE: Final = re.compile(r"^\$[0-9a-zA-Z@]+(:[\w:]+)?$")

# Shown on a listing that sold, in the site's language ("Verkocht", "Vendu"...). Its
# presence is the signal; the wording is not.
_SOLD_PLUGIN: Final = "buyer_item_status"
_ATTRIBUTE_FIELDS: Final = {
    "brand": "brand",
    "size": "size",
    "status": "condition",
    "color": "color",
}


def flight_text(html: str) -> str:
    """Decode and join the page's flight chunks into the text React reads."""
    chunks: list[str] = []
    for match in _FLIGHT_CHUNK.finditer(html):
        try:
            chunk = json.loads(match.group(1))
        except ValueError:
            # A chunk that is not a plain string literal is a framework detail we do not
            # need; the data chunks are always plain strings.
            continue
        if isinstance(chunk, str):
            chunks.append(chunk)
    return "".join(chunks)


def _is_reference(value: Any) -> bool:
    """A flight pointer such as "$15d" or "$14e:props:value:price", not a value."""
    return isinstance(value, str) and bool(_REFERENCE.match(value))


def _resolve_text(text: str, value: Any) -> Any:
    """Follow a pointer to a long text row ("15d:T4fd,<text>"), where React keeps them.

    The row's length is a hex count of UTF-8 bytes, so the cut is made on bytes.
    """
    if not _is_reference(value):
        return value
    row_id = str(value)[1:].split(":", 1)[0]
    match = re.search(rf"(?:^|\n){re.escape(row_id)}:T([0-9a-f]+),", text)
    if match is None:
        return None
    raw = text[match.end() :].encode("utf-8")[: int(match.group(1), 16)]
    return raw.decode("utf-8", errors="ignore")


def _plugins(text: str) -> dict[str, dict[str, Any]]:
    """Every named page block, by name.

    A block can appear more than once, and a copy may hold a pointer ("$15d") where
    another holds the value. Copies are merged so a real value always beats a pointer.
    """
    decoder = json.JSONDecoder()
    found: dict[str, dict[str, Any]] = {}
    index = text.find(_PLUGIN_START)
    while index != -1:
        try:
            value, _ = decoder.raw_decode(text, index)
        except ValueError:
            value = None
        if isinstance(value, dict) and isinstance(name := value.get("name"), str):
            data = value.get("data")
            if isinstance(data, dict):
                merged = found.setdefault(name, {})
                for key, field in data.items():
                    if key not in merged or (
                        _is_reference(merged[key]) and not _is_reference(field)
                    ):
                        merged[key] = field
        index = text.find(_PLUGIN_START, index + 1)
    return found


def _sidebar_item(text: str, item_id: int) -> dict[str, Any]:
    marker = f'{{"value":{{"id":"{item_id}"'
    index = text.find(marker)
    if index == -1:
        return {}
    try:
        value, _ = json.JSONDecoder().raw_decode(text, index)
    except ValueError:
        return {}
    inner = value.get("value") if isinstance(value, dict) else None
    return inner if isinstance(inner, dict) else {}


def _json_ld(html: str) -> dict[str, Any]:
    for match in _JSON_LD.finditer(html):
        try:
            payload = json.loads(match.group(1))
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("@type") == "Product":
            return payload
    return {}


def parse_item_page(html: str, tld: str, item_id: int) -> ItemSnapshot:
    """Build a snapshot from an item page that loaded (HTTP 200)."""
    text = flight_text(html)
    plugins = _plugins(text)
    sidebar = _sidebar_item(text, item_id)
    ld = _json_ld(html)
    raw_offers = ld.get("offers")
    offers: dict[str, Any] = raw_offers if isinstance(raw_offers, dict) else {}
    og = dict(_OG_TAG.findall(html))

    if not sidebar and not plugins and not ld:
        raise MalformedResponseError(
            f"the vinted.{tld} page for item {item_id} carried none of the data we read"
        )

    price, currency = money(sidebar.get("price"))
    if price is None:
        price, currency = money(offers.get("price"))
    currency = currency or clean_text(offers.get("priceCurrency"))
    cover = clean_text(ld.get("image")) or clean_text(og.get("image"))
    photos = photo_urls_of(plugins.get("gallery", {}).get("photos") or sidebar.get("photos"), cover)
    attributes = _attributes(plugins.get("attributes", {}))
    seller = plugins.get("user_info_header", {})
    description = _resolve_text(text, plugins.get("description", {}).get("description"))
    description = description or ld.get("description")
    og_title = og.get("title", "").removesuffix(" | Vinted") or None
    reviews = coerce_int(seller.get("feedback_count"))

    return ItemSnapshot(
        item_id=item_id,
        tld=tld,
        title=clean_text(sidebar.get("title")) or clean_text(ld.get("name")) or og_title,
        price=price,
        currency=currency,
        status=_status(sidebar, plugins, offers, tld, item_id),
        photo_url=photos[0] if photos else None,
        photo_urls=tuple(photos),
        brand=attributes.get("brand") or clean_text(first_of(ld, "brand.name")),
        size=attributes.get("size"),
        condition=attributes.get("condition"),
        color=attributes.get("color") or clean_text(ld.get("color")),
        description=clean_text(description),
        seller_id=coerce_int(sidebar.get("seller_id") or seller.get("seller_id")),
        seller_login=clean_text(seller.get("name")),
        # A member without reviews reports 0, which is not the same as rated zero.
        seller_rating=coerce_float(seller.get("feedback_reputation")) if reviews else None,
        seller_feedback_count=reviews,
    )


def _status(
    sidebar: dict[str, Any],
    plugins: dict[str, dict[str, Any]],
    offers: dict[str, Any],
    tld: str,
    item_id: int,
) -> ItemStatus:
    ask = plugins.get("ask_seller", {})
    if sidebar.get("is_reserved") or ask.get("is_reserved"):
        return "reserved"
    if sidebar.get("can_buy") or ask.get("can_buy"):
        return "available"
    if _SOLD_PLUGIN in plugins:
        return "sold"
    availability = str(offers.get("availability") or "")
    if availability.endswith("InStock"):
        return "available"
    if availability.endswith(("OutOfStock", "SoldOut")):
        return "sold"
    if sidebar.get("is_hidden"):
        return "gone"
    raise MalformedResponseError(
        f"the vinted.{tld} page for item {item_id} did not say whether it can be bought"
    )


def _attributes(block: dict[str, Any]) -> dict[str, str]:
    """Brand, size, condition and colour from the page's "details" block."""
    found: dict[str, str] = {}
    for entry in block.get("attributes") or []:
        if not isinstance(entry, dict):
            continue
        field = _ATTRIBUTE_FIELDS.get(str(entry.get("code")))
        value = clean_text(first_of(entry, "data.value"))
        if field and value:
            found[field] = value
    return found
