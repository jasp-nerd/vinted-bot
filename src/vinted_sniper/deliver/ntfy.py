"""Push notifications through ntfy.

Worth having because it needs no account and no bot: install the app, pick a topic name,
done. The public server allows a few hundred messages a day, which suits one person
watching a handful of searches; anyone busier should self-host ntfy or use Discord or
Telegram.

Published as JSON rather than with headers. Headers have to be ASCII, and Vinted titles are
full of accents and euro signs, so a header-based push of "Très bon état · 4,90 €" fails
before it leaves the machine.

Each push carries the price and title, a markdown body with the facts, the photo, the
project icon and up to three buttons (ntfy's maximum). Deals are sent at a higher priority
so a phone set to let only urgent pushes through still hears about them.
"""

from __future__ import annotations

from typing import Any

import httpx

from vinted_sniper.db.repo import PendingNotification
from vinted_sniper.deliver.base import SenderConfigError, SendResult
from vinted_sniper.deliver.ratelimit import TokenBucket
from vinted_sniper.deliver.render import BOT_NAME, ICON_URL, ListingView, escape_markdown, view

DEFAULT_SERVER = "https://ntfy.sh"

# ntfy's priorities run 1 (min) to 5 (max); 3 is the default.
STEAL_PRIORITY = 5
DEAL_PRIORITY = 4
DEFAULT_PRIORITY = 3
SILENT_PRIORITY = 2

MAX_ACTIONS = 3


def _server_and_topic(config: dict[str, Any]) -> tuple[str, str]:
    """Accept either a topic (plus optional server) or the full topic URL."""
    if url := str(config.get("url") or "").strip():
        server, _, topic = url.rstrip("/").rpartition("/")
        if server.startswith(("https://", "http://")) and topic:
            return server, topic
        raise SenderConfigError("ntfy url must look like https://ntfy.sh/your-topic")
    topic = str(config.get("topic") or "").strip()
    if not topic:
        raise SenderConfigError("ntfy destination needs a 'topic'")
    return str(config.get("server") or DEFAULT_SERVER).rstrip("/"), topic


def _priority(listing: ListingView, default: int) -> int:
    if listing.deal is not None:
        return STEAL_PRIORITY if listing.deal.tier == "steal" else DEAL_PRIORITY
    return SILENT_PRIORITY if listing.silent else default


def push(
    listing: ListingView, *, topic: str, default_priority: int = DEFAULT_PRIORITY
) -> dict[str, Any]:
    """The JSON body for one listing."""
    labels = listing.labels
    # The title is what the phone shows first, so it is the whole decision line.
    title = listing.first_line_text
    first = " · ".join(
        part
        for part in (
            f"~~{listing.previous_price}~~" if listing.previous_price else None,
            listing.price_note,
        )
        if part
    )
    seller = escape_markdown(listing.seller_login) if listing.seller_login else None
    lines = [
        first,
        " · ".join(escape_markdown(value) for _, value in listing.facts),
        " · ".join(p for p in (seller, listing.rating) if p),
        f"{listing.flag} {listing.site} · _{escape_markdown(listing.search_name)}_".strip(),
    ]

    actions = []
    if listing.can_buy:
        actions.append({"action": "view", "label": labels.buy, "url": listing.buy_url})
        actions.append({"action": "view", "label": labels.message, "url": listing.message_url})
    actions.append({"action": "view", "label": labels.open, "url": listing.url})

    tags = ["shopping_bags"]
    if listing.deal is not None:
        tags.append(labels.steal if listing.deal.tier == "steal" else labels.good_deal)

    body: dict[str, Any] = {
        "topic": topic,
        "title": title[:250],
        "message": "\n".join(line for line in lines if line),
        "markdown": True,
        "priority": _priority(listing, default_priority),
        "tags": tags,
        "click": listing.url,
        "icon": ICON_URL,
        "actions": actions[:MAX_ACTIONS],
    }
    if listing.photos:
        body["attach"] = listing.photos[0]
    return body


class NtfySender:
    """Sends one push per listing."""

    kind = "ntfy"

    def __init__(
        self,
        config: dict[str, Any],
        *,
        client: httpx.AsyncClient | None = None,
        bucket: TokenBucket | None = None,
    ) -> None:
        self._server, self._topic = _server_and_topic(config)
        self._token = config.get("token")
        try:
            self._priority = int(config.get("priority") or DEFAULT_PRIORITY)
        except (TypeError, ValueError) as exc:
            raise SenderConfigError("ntfy priority must be a number from 1 to 5") from exc
        self._client = client or httpx.AsyncClient(timeout=20.0)
        self._owns_client = client is None
        self._bucket = bucket or TokenBucket(1.0, capacity=3)

    @property
    def max_batch(self) -> int:
        # One push per listing, and a phone that buzzes five times in a row is already
        # pushing it.
        return 5

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    async def send(self, batch: list[PendingNotification]) -> SendResult:
        delivered: list[int] = []
        for notification in batch:
            # Three buttons is ntfy's limit and buy, message and open fill it, so the
            # dashboard link has nowhere to go.
            listing = view(notification, dashboard_url=None)
            body = push(listing, topic=self._topic, default_priority=self._priority)
            remaining = [n.outbox_id for n in batch if n.outbox_id not in delivered]

            await self._bucket.acquire()
            try:
                response = await self._client.post(self._server, json=body, headers=self._headers())
            except httpx.HTTPError as exc:
                return SendResult(
                    delivered=delivered, retry=remaining, error=f"could not reach ntfy: {exc}"
                )

            if response.is_success:
                delivered.append(notification.outbox_id)
                continue
            if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
                # A reserved topic or a revoked token; asking again gets the same answer.
                return SendResult(
                    delivered=delivered,
                    permanent_error=(
                        f"ntfy answered {response.status_code}: check the topic and token"
                    ),
                )
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                return SendResult(
                    delivered=delivered,
                    retry=remaining,
                    retry_after_s=60.0,
                    error="ntfy daily allowance reached",
                )
            return SendResult(
                delivered=delivered,
                retry=remaining,
                error=f"ntfy answered {response.status_code}",
            )
        return SendResult.ok(delivered)

    async def send_status(self, message: str) -> None:
        await self._bucket.acquire()
        try:
            await self._client.post(
                self._server,
                json={
                    "topic": self._topic,
                    "title": BOT_NAME,
                    "message": message,
                    "tags": ["warning"],
                    "priority": SILENT_PRIORITY,
                },
                headers=self._headers(),
            )
        except httpx.HTTPError:
            # A status notice is best effort; the same warning is already in the log.
            return

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
