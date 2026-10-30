"""Shared fixtures for the sender tests: a listing factory, a recording HTTP endpoint, and
independent checks of the platforms' documented limits.

The limit checks are written separately from the code under test on purpose. Reusing the
sender's own component counter would only prove the code agrees with itself.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx

from vinted_sniper.db.repo import PendingNotification
from vinted_sniper.deliver.ratelimit import TokenBucket
from vinted_sniper.vinted.models import Item


def notification(item_id: int, **kwargs: Any) -> PendingNotification:
    """A queued listing with every field filled in, as the old catalog endpoint gave."""
    outer = {
        key: kwargs.pop(key)
        for key in (
            "query_id",
            "query_name",
            "query_color",
            "typical_price",
            "silent",
            "kind",
            "previous_price",
            "margin",
            "watch_id",
        )
        if key in kwargs
    }
    fields: dict[str, Any] = {
        "item_id": item_id,
        "tld": "co.uk",
        "title": f"Item {item_id}",
        "url": f"https://www.vinted.co.uk/items/{item_id}",
        "price": Decimal("15.00"),
        "total_price": Decimal("16.45"),
        "currency": "GBP",
        "brand": "Nike",
        "size": "M",
        "condition": "Very good",
        "photo_url": f"https://images.vinted.net/{item_id}.jpeg",
        "photo_urls": tuple(f"https://images.vinted.net/{item_id}-{n}.jpeg" for n in range(6)),
        "photo_ts": 1_760_000_000,
        "seller_login": "sneakerfan",
        "seller_id": 12_345_678,
        "seller_rating": 0.96,
        "seller_feedback_count": 128,
    }
    fields.update(kwargs)
    return PendingNotification(
        outbox_id=item_id,
        destination_id=1,
        query_id=outer.get("query_id", 1),
        query_name=outer.get("query_name", "my search"),
        attempts=0,
        item=Item(**fields),
        detected_at=1_760_000_100,
        query_color=outer.get("query_color"),
        typical_price=outer.get("typical_price"),
        silent=outer.get("silent", False),
        kind=outer.get("kind", "listing"),
        previous_price=outer.get("previous_price"),
        margin=outer.get("margin"),
        watch_id=outer.get("watch_id"),
    )


def bare(item_id: int) -> PendingNotification:
    """What Vinted's newer catalog endpoint gives: title, price, one photo, a site."""
    return PendingNotification(
        outbox_id=item_id,
        destination_id=1,
        query_id=1,
        query_name="my search",
        attempts=0,
        item=Item(
            item_id=item_id,
            tld="fr",
            title=f"Item {item_id}",
            url=f"/items/{item_id}-slug",
            price=Decimal("15.0"),
            currency="EUR",
            photo_url=f"https://images.vinted.net/{item_id}.jpeg",
        ),
        detected_at=1_760_000_100,
    )


class Recorder:
    """Captures requests and replays scripted responses."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.requests: list[httpx.Request] = []
        self._responses = list(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._responses:
            return self._responses.pop(0)
        return httpx.Response(200, json={"ok": True})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def payload(self, index: int = 0) -> Any:
        return json.loads(self.requests[index].content)

    def method(self, index: int = 0) -> str:
        return self.requests[index].url.path.rsplit("/", 1)[-1]


def fast_bucket() -> TokenBucket:
    """A bucket that never actually waits, so tests do not either."""
    return TokenBucket(1000.0, capacity=1000.0)


# --- Discord's documented limits ------------------------------------------------------

_CONTAINER_CHILDREN = {1, 9, 10, 12, 13, 14}
_TOP_LEVEL = {*_CONTAINER_CHILDREN, 17}


def _button_problems(button: dict[str, Any]) -> list[str]:
    problems = []
    if button.get("style") != 5 or "custom_id" in button:
        problems.append("only link buttons work on a plain webhook")
    if len(button["url"]) > 512 or len(button["label"]) > 80:
        problems.append("button too long")
    return problems


def _section_problems(section: dict[str, Any]) -> list[str]:
    if not 1 <= len(section["components"]) <= 3:
        return ["section needs 1 to 3 texts"]
    return []


def _row_problems(row: dict[str, Any]) -> list[str]:
    return [] if 1 <= len(row["components"]) <= 5 else ["action row needs 1 to 5 buttons"]


def _gallery_problems(gallery: dict[str, Any]) -> list[str]:
    return [] if 1 <= len(gallery["items"]) <= 10 else ["gallery needs 1 to 10 items"]


def _no_problems(_: dict[str, Any]) -> list[str]:
    return []


_SHAPE_CHECKS: dict[int, Callable[[dict[str, Any]], list[str]]] = {
    1: _row_problems,
    2: _button_problems,
    9: _section_problems,
    12: _gallery_problems,
}


def _flatten(
    components: list[dict[str, Any]], parent: int | None
) -> list[tuple[dict[str, Any], int | None]]:
    """Every component with its parent's type, section accessories included."""
    found: list[tuple[dict[str, Any], int | None]] = []
    for component in components:
        found.append((component, parent))
        if "accessory" in component:
            found.append((component["accessory"], component["type"]))
        found.extend(_flatten(component.get("components", []), component["type"]))
    return found


def cv2_problems(payload: dict[str, Any]) -> list[str]:
    """Everything about a Components V2 webhook payload that Discord would refuse."""
    problems: list[str] = []
    if not payload.get("flags", 0) & (1 << 15):
        problems.append("IS_COMPONENTS_V2 flag missing")
    problems.extend(
        f"{forbidden} is not allowed with Components V2"
        for forbidden in ("content", "embeds", "poll")
        if forbidden in payload
    )
    every = _flatten(payload["components"], None)
    for component, parent in every:
        kind = component["type"]
        if parent is None and kind not in _TOP_LEVEL:
            problems.append(f"type {kind} cannot be top level")
        if parent == 17 and kind not in _CONTAINER_CHILDREN:
            problems.append(f"type {kind} cannot sit in a container")
        problems.extend(_SHAPE_CHECKS.get(kind, _no_problems)(component))
    if len(every) > 40:
        problems.append(f"{len(every)} components, over 40")
    text = sum(len(component["content"]) for component, _ in every if component["type"] == 10)
    if text > 4000:
        problems.append(f"{text} text characters, over 4000")
    return problems


def _embed_size(embed: dict[str, Any]) -> int:
    fields = embed.get("fields", [])
    return (
        len(embed.get("title", ""))
        + len(embed.get("description", ""))
        + len(embed.get("author", {}).get("name", ""))
        + len(embed.get("footer", {}).get("text", ""))
        + sum(len(field["name"]) + len(field["value"]) for field in fields)
    )


def _one_embed_problems(embed: dict[str, Any]) -> list[str]:
    problems = [
        f"{key} over {limit}"
        for key, limit in (("title", 256), ("description", 4096))
        if len(embed.get(key, "")) > limit
    ]
    fields = embed.get("fields", [])
    if len(fields) > 25:
        problems.append("more than 25 fields")
    problems.extend(
        f"field {field['name']!r} out of bounds"
        for field in fields
        if not 0 < len(field["value"]) <= 1024 or not 0 < len(field["name"]) <= 256
    )
    return problems


def embed_problems(payload: dict[str, Any]) -> list[str]:
    embeds = payload.get("embeds", [])
    problems = [problem for embed in embeds for problem in _one_embed_problems(embed)]
    if len(embeds) > 10:
        problems.append("more than 10 embeds")
    total = sum(_embed_size(embed) for embed in embeds)
    if total > 6000:
        problems.append(f"{total} embed characters, over 6000")
    if len(payload.get("content", "")) > 2000:
        problems.append("content over 2000")
    titled = [embed["url"] for embed in embeds if "title" in embed]
    if len(titled) != len(set(titled)):
        problems.append("two titled embeds share a URL, so one disappears")
    return problems


# --- Telegram -------------------------------------------------------------------------


def telegram_length(markup: str) -> int:
    """Characters after entity parsing, in UTF-16 units, as Telegram counts them."""
    text = html.unescape(re.sub(r"<[^>]*>", "", markup))
    return len(text.encode("utf-16-le")) // 2
