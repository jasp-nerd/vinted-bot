"""Getting queued notifications out.

Nothing here talks to Vinted and nothing in the poller talks to a chat platform. The two
sides meet at the outbox table, which is what makes delivery survivable: a notification is
written in the same transaction that records the listing, so a crash cannot lose it, and it
is only marked sent once the far end has actually accepted it.

Each destination gets one worker sending one thing at a time. That is slower than firing
everything at once and it is the point — ordered, paced delivery is what keeps you inside
the platform limits instead of apologising to them afterwards.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
from dataclasses import dataclass
from typing import Any

import httpx

from vinted_bot import managed
from vinted_bot.config import Settings
from vinted_bot.db.repo import Destination, PendingNotification, Repo
from vinted_bot.deals import DEAL_PCT, STEAL_PCT, TIERS, Tier, deal_percent, tier_for
from vinted_bot.deliver.apprise import AppriseSender
from vinted_bot.deliver.base import Sender, SenderConfigError, parse_tiers
from vinted_bot.deliver.discord import DiscordSender
from vinted_bot.deliver.ntfy import NtfySender
from vinted_bot.deliver.ratelimit import Gate, TokenBucket
from vinted_bot.deliver.telegram import TelegramSender
from vinted_bot.deliver.webhook import WebhookSender
from vinted_bot.log import get_logger

log = get_logger(__name__)

# Give up on a notification after this many tries. Anything still failing is a
# configuration problem, not bad luck.
MAX_ATTEMPTS = 6

# Retries stay short on purpose. Notifications for one destination go out in order, so a
# long sleep at the front of the queue holds up every fresher listing behind it.
MAX_RETRY_DELAY_S = 5.0

# Telegram counts messages across the whole bot, not per chat, so every Telegram
# destination shares this.
TELEGRAM_GLOBAL_PER_S = 25.0


def awaiting_pairing(destination: Destination) -> bool:
    """True for a Telegram destination that no chat has claimed yet."""
    return destination.kind == "telegram" and not destination.config.get("chat_id")


@dataclass(frozen=True, slots=True)
class Routing:
    """Which listings a destination takes, and which of those arrive without a sound.

    Configured with `tiers` (the tiers to deliver, default all three) and `silent_tiers`
    (delivered without a sound, default none). The 1.x keys still work: `deals_only` is
    `tiers: [steal, deal]`, and `min_deal_pct` is a custom threshold on top of the tiers.
    """

    tiers: frozenset[Tier] = frozenset(TIERS)
    silent_tiers: frozenset[Tier] = frozenset()
    min_deal_pct: int | None = None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> Routing:
        tiers = parse_tiers(config, "tiers", TIERS)
        if config.get("deals_only"):
            tiers -= {"normal"}
        if not tiers:
            raise SenderConfigError("tiers must name at least one of steal, deal, normal")
        raw_pct = config.get("min_deal_pct")
        try:
            min_pct = int(raw_pct) if raw_pct is not None and raw_pct != "" else None
        except (TypeError, ValueError) as exc:
            raise SenderConfigError("min_deal_pct must be a whole percentage") from exc
        return cls(
            tiers=tiers,
            silent_tiers=parse_tiers(config, "silent_tiers", ()),
            min_deal_pct=min_pct,
        )


def _deal_pct(notification: PendingNotification) -> int | None:
    item = notification.item
    total = item.total_price if item.total_price is not None else item.price
    return deal_percent(total, notification.typical_price)


def skip_reason(notification: PendingNotification, config: dict[str, Any]) -> str | None:
    """Why this destination should not get this listing, if it should not.

    Decided here, at delivery, rather than when the listing is found: one listing goes to
    several destinations, and only some of them may be picky. Watch alerts (price drops,
    sales) and a followed seller's uploads were asked for one by one, so they always pass.
    """
    if notification.kind != "listing":
        return None
    routing = Routing.from_config(config)
    pct = _deal_pct(notification)
    tier = tier_for(pct)
    wants_threshold = routing.min_deal_pct is not None
    if pct is None and (tier not in routing.tiers or wants_threshold):
        return "skipped: this destination only wants deals and there is no typical price yet"
    if tier not in routing.tiers:
        wanted = " and ".join(_TIER_NAMES[t] for t in TIERS if t in routing.tiers)
        return (
            f"skipped: {_distance(pct)} makes it {_TIER_NAMES[tier]}; this destination "
            f"takes {wanted} only (a deal is {DEAL_PCT}% or more under, a steal {STEAL_PCT}%)"
        )
    if wants_threshold and pct is not None and pct < (routing.min_deal_pct or 0):
        return f"skipped: {_distance(pct)}, this destination wants {routing.min_deal_pct}%"
    return None


_TIER_NAMES: dict[Tier, str] = {"steal": "steals", "deal": "deals", "normal": "ordinary"}


def _distance(pct: int | None) -> str:
    if pct is not None and pct < 0:
        return f"{-pct}% above the typical price"
    return f"{pct}% under the typical price"


def deliver_silently(notification: PendingNotification, routing: Routing) -> bool:
    """Whether this destination wants this listing's tier without a sound."""
    return notification.kind == "listing" and tier_for(_deal_pct(notification)) in (
        routing.silent_tiers
    )


def build_sender(
    destination: Destination,
    settings: Settings,
    client: httpx.AsyncClient,
    *,
    telegram_token: str | None,
) -> Sender:
    """The sender for a destination, or SenderConfigError saying what is missing.

    `telegram_token` is the bot's token as it is now (managed.telegram_token): it can be
    set or changed from the dashboard while the app runs, so it is not read from settings.
    """
    config: dict[str, Any] = destination.config
    match destination.kind:
        case "discord":
            return DiscordSender(config, dashboard_url=settings.dashboard_url, client=client)
        case "telegram":
            if telegram_token is None:
                raise SenderConfigError(
                    "a Telegram destination exists but no bot token is set; add it on the "
                    "Alerts page"
                )
            return TelegramSender(
                config,
                bot_token=telegram_token,
                dashboard_url=settings.dashboard_url,
                client=client,
            )
        case "webhook":
            return WebhookSender(config, client=client)
        case "ntfy":
            return NtfySender(config, client=client)
        case "apprise":
            return AppriseSender(config, dashboard_url=settings.dashboard_url)
        case unknown:
            raise SenderConfigError(f"unknown destination type {unknown!r}")


class Dispatcher:
    """Runs one sending worker per destination."""

    def __init__(
        self,
        *,
        repo: Repo,
        settings: Settings,
        stop: asyncio.Event,
        work_available: asyncio.Event,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._repo = repo
        self._settings = settings
        self._stop = stop
        self._work = work_available
        self._client = client or httpx.AsyncClient(timeout=20.0)
        self._owns_client = client is None
        self._senders: dict[int, Sender] = {}
        self._signatures: dict[int, str] = {}
        self._discord_gate = Gate()
        self._telegram_budget = TokenBucket(TELEGRAM_GLOBAL_PER_S, capacity=TELEGRAM_GLOBAL_PER_S)

    async def run(self, idle_interval_s: float = 2.0) -> None:
        """Deliver whatever is queued, then wait to be told there is more."""
        recovered = await self._repo.recover_leases()
        if recovered:
            log.info("outbox.recovered", count=recovered)

        while not self._stop.is_set():
            try:
                await self.drain()
            except Exception as exc:  # keep the loop alive; one bad destination is not fatal
                log.exception("dispatcher.cycle_failed", error=str(exc))

            self._work.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._work.wait(), timeout=idle_interval_s)

        await self.aclose()

    async def drain(self) -> int:
        """Send everything currently due. Returns how many notifications went out."""
        expired = await self._repo.expire_stale_notifications(self._settings.outbox_expiry_minutes)
        if expired:
            log.info("outbox.expired", count=expired, reason="older than the delivery window")

        destination_ids = await self._repo.destinations_with_work()
        if not destination_ids:
            return 0

        results = await asyncio.gather(
            *(self._serve(destination_id) for destination_id in destination_ids),
            return_exceptions=True,
        )

        sent = 0
        for destination_id, result in zip(destination_ids, results, strict=True):
            if isinstance(result, BaseException):
                log.exception(
                    "dispatcher.destination_failed",
                    destination_id=destination_id,
                    error=str(result),
                )
                continue
            sent += result
        return sent

    async def _serve(self, destination_id: int) -> int:
        destination = await self._repo.get_destination(destination_id)
        if destination is None or not destination.active:
            return 0

        if awaiting_pairing(destination):
            # Created but nobody has tapped the link yet. Waiting is not a misconfiguration,
            # so this must not switch the destination off; notifications queue until it is
            # claimed, or expire on their own.
            return 0

        try:
            sender = await self._sender_for(destination)
            routing = Routing.from_config(destination.config)
        except SenderConfigError as exc:
            await self._repo.deactivate_destination(destination_id, str(exc))
            log.error("destination.misconfigured", destination_id=destination_id, error=str(exc))
            return 0

        if sender.kind == "discord" and self._discord_gate.is_closed:
            return 0

        claimed = await self._repo.claim_batch(destination_id, sender.max_batch)
        batch = await self._drop_unwanted(claimed, destination.config, routing)
        if not batch:
            return 0

        if sender.kind == "telegram":
            # One bot token serves every Telegram destination, so the shared budget is
            # spent here rather than inside the sender.
            await self._telegram_budget.acquire(len(batch))

        result = await sender.send(batch)

        if result.pause_all_for_s:
            self._discord_gate.close_for(result.pause_all_for_s)
            log.warning("discord.global_pause", seconds=round(result.pause_all_for_s, 1))

        await self._repo.mark_sent(result.delivered)
        if result.delivered:
            await self._repo.reset_destination_failures(destination_id)

        handled = set(result.delivered)

        if result.permanent_error:
            await self._repo.deactivate_destination(destination_id, result.permanent_error)
            await self._drop_sender(destination_id)
            log.warning(
                "destination.disabled",
                destination_id=destination_id,
                name=destination.name,
                reason=result.permanent_error,
            )
            return len(result.delivered)

        if result.retry:
            await self._repo.note_destination_failure(destination_id)
            retry_ids = [outbox_id for outbox_id in result.retry if outbox_id not in handled]
            over_budget = [n.outbox_id for n in batch if n.attempts + 1 >= MAX_ATTEMPTS]
            give_up = [outbox_id for outbox_id in retry_ids if outbox_id in over_budget]
            keep = [outbox_id for outbox_id in retry_ids if outbox_id not in over_budget]

            delay = min(result.retry_after_s or 1.0, MAX_RETRY_DELAY_S)
            await self._repo.mark_retry(keep, delay_s=delay, error=result.error or "send failed")
            await self._repo.mark_failed(give_up, result.error or "gave up after repeated failures")
            handled.update(retry_ids)

        # Anything the sender neither delivered nor asked to retry was rejected outright.
        abandoned = [n.outbox_id for n in batch if n.outbox_id not in handled]
        await self._repo.mark_failed(abandoned, result.error or "the destination rejected it")

        return len(result.delivered)

    async def notify_status(self, message: str) -> None:
        """Send an operational notice to whichever destinations asked for them."""
        for destination_id in await self._repo.status_destination_ids():
            destination = await self._repo.get_destination(destination_id)
            if destination is None:
                continue
            with contextlib.suppress(Exception):
                sender = await self._sender_for(destination)
                await sender.send_status(message)

    async def _sender_for(self, destination: Destination) -> Sender:
        # Keyed on the settings too: pairing a Telegram chat rewrites them, and a sender
        # built from the old ones would keep sending nowhere. And on the bot's token,
        # which the dashboard can replace while this runs.
        token = None
        if destination.kind == "telegram":
            token = await managed.telegram_token(self._settings, self._repo)
        signature = json.dumps([destination.config, token], sort_keys=True)
        cached = self._senders.get(destination.id)
        if cached is not None and self._signatures.get(destination.id) == signature:
            return cached
        if cached is not None:
            await self._drop_sender(destination.id)

        sender = build_sender(destination, self._settings, self._client, telegram_token=token)
        self._senders[destination.id] = sender
        self._signatures[destination.id] = signature
        return sender

    async def _drop_unwanted(
        self, batch: list[PendingNotification], config: dict[str, Any], routing: Routing
    ) -> list[PendingNotification]:
        """Set aside what this destination asked not to get, with the reason recorded,
        and mark what it wants to hear about quietly."""
        wanted = []
        for notification in batch:
            reason = skip_reason(notification, config)
            if reason is None:
                if deliver_silently(notification, routing):
                    notification = dataclasses.replace(notification, silent=True)  # noqa: PLW2901
                wanted.append(notification)
            else:
                # The destination's own choice, not a delivery error: cancelled, so it
                # does not count against the destination's delivery rate.
                await self._repo.mark_cancelled([notification.outbox_id], reason)
        return wanted

    async def _drop_sender(self, destination_id: int) -> None:
        self._signatures.pop(destination_id, None)
        sender = self._senders.pop(destination_id, None)
        if sender is not None:
            with contextlib.suppress(Exception):
                await sender.aclose()

    async def aclose(self) -> None:
        for destination_id in list(self._senders):
            await self._drop_sender(destination_id)
        if self._owns_client:
            await self._client.aclose()
