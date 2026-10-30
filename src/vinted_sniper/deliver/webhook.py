"""A plain JSON POST to a URL of your choosing.

The cheapest channel to support and the one that covers everything we did not build: n8n,
Home Assistant, Slack via an adapter, a shell script behind a tiny server. The payload is
documented in docs/configuration.md and treated as a contract — changing it breaks other
people's automations, so it changes only with a version bump.

Version 2 is a strict superset of version 1: every v1 field keeps its name and meaning,
and the new ones (kind, deal, photos, seller details) are added beside them. Each POST
carries listings from one search, or from one watch, only, so the top-level `search` is
always right: for watch alerts it is the watch's label and `search_id` is null.

With a `secret` configured, every request is signed so the receiver can tell it came from
here: `X-Vinted-Sniper-Signature: sha256=<hex>` is the HMAC-SHA256 of
`<X-Vinted-Sniper-Timestamp>.<raw body>` under the secret. Including the timestamp lets a
receiver refuse replays of an old request.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from vinted_sniper.db.repo import PendingNotification
from vinted_sniper.deals import deal_percent, tier_for
from vinted_sniper.deliver.base import SendResult, require
from vinted_sniper.deliver.labels import money_text
from vinted_sniper.deliver.ratelimit import TokenBucket
from vinted_sniper.deliver.render import absolute
from vinted_sniper.vinted.models import Item

PAYLOAD_VERSION = 2

SIGNATURE_HEADER = "X-Vinted-Sniper-Signature"
TIMESTAMP_HEADER = "X-Vinted-Sniper-Timestamp"


def item_json(notification: PendingNotification) -> dict[str, Any]:
    """One listing in the documented shape."""
    item = notification.item
    total = item.total_price if item.total_price is not None else item.price
    pct = deal_percent(total, notification.typical_price)
    return {
        "id": item.item_id,
        "site": f"vinted.{item.tld}",
        "title": item.title,
        "url": absolute(item.url, item.tld),
        "brand": item.brand,
        "size": item.size,
        "condition": item.condition,
        "price": _money(item.price),
        "total_price": _money(item.total_price),
        "currency": item.currency,
        "photo_url": absolute(item.photo_url, item.tld) if item.photo_url else None,
        "listed_at": item.listed_at.isoformat() if item.listed_at else None,
        "seller": item.seller_login,
        "seller_rating": item.seller_rating,
        "links": {"message_seller": item.message_url, "buy": item.buy_url},
        # --- added in version 2 ---
        "kind": notification.kind,
        "search_id": notification.query_id,
        "detected_at": notification.detected_at,
        "photos": [absolute(photo, item.tld) for photo in item.photo_urls],
        "previous_price": _money(notification.previous_price),
        "typical_price": _money(notification.typical_price),
        "deal_pct": pct,
        # "steal", "deal" or "normal": the tiers a destination's `tiers` setting names.
        "deal_tier": tier_for(pct),
        "margin": _money(notification.margin),
        "favourites": item.favourite_count,
        "seller_profile": _seller(item),
    }


def payload(batch: list[PendingNotification]) -> dict[str, Any]:
    """The body for listings that all came from one search."""
    return {
        "version": PAYLOAD_VERSION,
        "search": batch[0].query_name,
        "search_id": batch[0].query_id,
        "items": [item_json(notification) for notification in batch],
    }


def sign(body: bytes, secret: str, timestamp: int) -> str:
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _money(amount: Any) -> str | None:
    return money_text(amount) if amount is not None else None


def _seller(item: Item) -> dict[str, Any] | None:
    if item.seller_id is None and item.seller_login is None:
        return None
    return {
        "id": item.seller_id,
        "login": item.seller_login,
        "url": item.seller_url,
        # Out of five, as people read it; seller_rating above stays Vinted's 0..1.
        "stars": round(item.seller_rating * 5, 1) if item.seller_rating is not None else None,
        "reviews": item.seller_feedback_count,
    }


def _by_search(batch: list[PendingNotification]) -> list[list[PendingNotification]]:
    """Split a batch so each POST is one search's listings, or one watch's."""
    groups: dict[tuple[int | None, int | None], list[PendingNotification]] = {}
    for notification in batch:
        key = (notification.query_id, notification.watch_id)
        groups.setdefault(key, []).append(notification)
    return list(groups.values())


class WebhookSender:
    """Posts listings as JSON to an arbitrary endpoint."""

    kind = "webhook"

    def __init__(
        self,
        config: dict[str, Any],
        *,
        client: httpx.AsyncClient | None = None,
        bucket: TokenBucket | None = None,
    ) -> None:
        self._url = require(config, "url", self.kind)
        self._headers = dict(config.get("headers") or {})
        self._secret = str(config.get("secret") or "") or None
        self._client = client or httpx.AsyncClient(timeout=20.0)
        self._owns_client = client is None
        self._bucket = bucket or TokenBucket(2.0, capacity=4)

    @property
    def max_batch(self) -> int:
        return 20

    async def send(self, batch: list[PendingNotification]) -> SendResult:
        delivered: list[int] = []
        groups = _by_search(batch)
        for index, group in enumerate(groups):
            outbox_ids = [n.outbox_id for n in group]
            result = await self._post(payload(group), outbox_ids)
            if result.delivered:
                delivered.extend(result.delivered)
                continue
            if result.permanent_error:
                return SendResult(delivered=delivered, permanent_error=result.permanent_error)
            untried = [n.outbox_id for later in groups[index + 1 :] for n in later]
            return SendResult(
                delivered=delivered, retry=[*result.retry, *untried], error=result.error
            )
        return SendResult.ok(delivered)

    async def send_status(self, message: str) -> None:
        await self._post({"version": PAYLOAD_VERSION, "status": message}, [])

    async def _post(self, body: dict[str, Any], outbox_ids: list[int]) -> SendResult:
        raw = json.dumps(body, ensure_ascii=False).encode()
        headers = {"Content-Type": "application/json", **self._headers}
        if self._secret:
            timestamp = int(time.time())
            headers[TIMESTAMP_HEADER] = str(timestamp)
            headers[SIGNATURE_HEADER] = sign(raw, self._secret, timestamp)

        await self._bucket.acquire()
        try:
            response = await self._client.post(self._url, content=raw, headers=headers)
        except httpx.HTTPError as exc:
            return SendResult.transient(outbox_ids, f"could not reach the webhook: {exc}")

        if response.is_success:
            return SendResult.ok(outbox_ids)
        if response.status_code in (httpx.codes.NOT_FOUND, httpx.codes.GONE):
            return SendResult.gone(f"the endpoint answered {response.status_code}")
        return SendResult.transient(outbox_ids, f"the endpoint answered {response.status_code}")

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
