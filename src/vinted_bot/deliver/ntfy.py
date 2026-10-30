"""Push notifications through ntfy.

Worth having because it needs no account and no bot: install the app, pick a topic name,
done. The public server allows a few hundred messages a day, which suits one person
watching a handful of searches; anyone busier should self-host ntfy or use Discord or
Telegram.

Published as JSON rather than with headers. Headers have to be ASCII, and Vinted titles are
full of accents and euro signs, so a header-based push of "Très bon état · 4,90 €" fails
before it leaves the machine.

Each push carries the price and title, a plain-text body with the facts, the photo, the
project icon and up to three buttons (ntfy's maximum). Plain text because the iOS app shows
markdown as raw asterisks and tildes. Deals are sent at a higher priority so a phone set to
let only urgent pushes through still hears about them.

The public server allows about 250 messages a day per address. So several listings waiting
at once go out as one push listing them all, and when the server says the day's allowance
is used up, the destination pauses until it resets at midnight UTC instead of asking again
every minute all day.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from vinted_bot.db.repo import PendingNotification
from vinted_bot.deliver.base import SenderConfigError, SendResult
from vinted_bot.deliver.ratelimit import TokenBucket
from vinted_bot.deliver.render import BOT_NAME, ICON_URL, ListingView, view

DEFAULT_SERVER = "https://ntfy.sh"

# ntfy's priorities run 1 (min) to 5 (max); 3 is the default.
STEAL_PRIORITY = 5
DEAL_PRIORITY = 4
DEFAULT_PRIORITY = 3
SILENT_PRIORITY = 2

MAX_ACTIONS = 3

# This many search listings waiting at once go out as one push. One push per listing
# would spend the public server's daily allowance in an afternoon on a busy search.
DIGEST_FROM = 3
# ntfy's answer when the day's message allowance is used up; see server/errors.go.
_DAILY_QUOTA_CODE = 42908


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
    """Deals louder, quiet hours and silent tiers quieter, the destination's choice otherwise.

    Silence wins over a deal: a destination that asked for its deals without a sound
    should not get a top-priority buzz for one.
    """
    if listing.silent:
        return SILENT_PRIORITY
    if listing.deal is not None:
        return STEAL_PRIORITY if listing.deal.tier == "steal" else DEAL_PRIORITY
    return default


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
            f"{listing.previous_price} → {listing.price}" if listing.previous_price else None,
            listing.price_note,
        )
        if part
    )
    lines = [
        first,
        " · ".join(value for _, value in listing.facts),
        " · ".join(p for p in (listing.seller_login, listing.rating) if p),
        f"{listing.flag} {listing.site} · {listing.search_name}".strip(),
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
        "priority": _priority(listing, default_priority),
        "tags": tags,
        "click": listing.url,
        "icon": ICON_URL,
        "actions": actions[:MAX_ACTIONS],
    }
    if listing.photos:
        body["attach"] = listing.photos[0]
    return body


def digest(
    listings: list[ListingView], *, topic: str, default_priority: int = DEFAULT_PRIORITY
) -> dict[str, Any]:
    """One push for several listings: a line each, the loudest priority among them."""
    labels = listings[0].labels
    searches = sorted({listing.search_name for listing in listings})
    lines = [
        " · ".join(part for part in (listing.price, *listing.summary, listing.title) if part)
        for listing in listings
    ]
    return {
        "topic": topic,
        "title": f"{labels.new_matches.format(n=len(listings))} · {', '.join(searches)}"[:250],
        "message": "\n".join(lines),
        "priority": max(_priority(listing, default_priority) for listing in listings),
        "tags": ["shopping_bags"],
        "click": listings[0].url,
        "icon": ICON_URL,
        "actions": [
            {"action": "view", "label": f"{n}. {listing.price or labels.open}", "url": listing.url}
            for n, listing in enumerate(listings[:MAX_ACTIONS], start=1)
        ],
    }


def _next_midnight_utc(now: datetime) -> int:
    tomorrow = (now + timedelta(days=1)).date()
    return int(datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=UTC).timestamp())


def _is_daily_quota(response: httpx.Response) -> bool:
    try:
        answer = response.json()
    except ValueError:
        return False
    return isinstance(answer, dict) and answer.get("code") == _DAILY_QUOTA_CODE


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
        # Enough to make a digest worth it; a phone that buzzes five times in a row for
        # watch alerts is already pushing it.
        return 10

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def _pushes(self, batch: list[PendingNotification]) -> list[tuple[dict[str, Any], list[int]]]:
        """The pushes for a batch, each with the outbox ids it carries.

        Search listings waiting together become one digest; watch alerts, each about one
        thing someone chose to follow, keep a push of their own.
        """
        # Three buttons is ntfy's limit and buy, message and open fill it, so the
        # dashboard link has nowhere to go.
        views = [(n, view(n, dashboard_url=None)) for n in batch]
        listings = [(n, v) for n, v in views if n.kind == "listing"]
        single = [(n, v) for n, v in views if n.kind != "listing"]
        pushes = []
        if len(listings) >= DIGEST_FROM:
            pushes.append(
                (
                    digest(
                        [v for _, v in listings], topic=self._topic, default_priority=self._priority
                    ),
                    [n.outbox_id for n, _ in listings],
                )
            )
        else:
            single = views
        pushes += [
            (push(v, topic=self._topic, default_priority=self._priority), [n.outbox_id])
            for n, v in single
        ]
        return pushes

    async def send(self, batch: list[PendingNotification]) -> SendResult:
        delivered: list[int] = []
        for body, outbox_ids in self._pushes(batch):
            remaining = [n.outbox_id for n in batch if n.outbox_id not in delivered]

            await self._bucket.acquire()
            try:
                response = await self._client.post(self._server, json=body, headers=self._headers())
            except httpx.HTTPError as exc:
                return SendResult(
                    delivered=delivered, retry=remaining, error=f"could not reach ntfy: {exc}"
                )

            if response.is_success:
                delivered.extend(outbox_ids)
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
                return self._too_many(response, delivered, remaining)
            return SendResult(
                delivered=delivered,
                retry=remaining,
                error=f"ntfy answered {response.status_code}",
            )
        return SendResult.ok(delivered)

    @staticmethod
    def _too_many(
        response: httpx.Response, delivered: list[int], remaining: list[int]
    ) -> SendResult:
        """A 429: the day's allowance (pause until it resets) or just a burst (retry soon)."""
        if _is_daily_quota(response):
            return SendResult(
                delivered=delivered,
                retry=remaining,
                pause_until=_next_midnight_utc(datetime.now(UTC)),
                error=(
                    "ntfy's daily message limit is used up; alerts resume at midnight UTC. "
                    "Narrow the search, or send its alerts to Telegram or Discord"
                ),
            )
        return SendResult(
            delivered=delivered,
            retry=remaining,
            retry_after_s=60.0,
            error="ntfy asked to slow down",
        )

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
