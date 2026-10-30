"""Watching single listings and single sellers.

Two kinds of watch, both slow on purpose. An item watch re-reads one listing's page every
half hour or so and speaks up when the price drops, or it is reserved, sold or removed. A
seller watch reads a member's listings and announces new uploads. Neither is a race: they
exist for the thing you were already thinking about, so a request every few minutes across
all of them is plenty, and it keeps this from becoming a second source of blocks.

The listing and seller reads are injected, because they live in the Vinted layer and a
build without them should still run everything else. A missing reader leaves those watches
parked rather than failing.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import re
import sqlite3
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal

from vinted_bot.db.repo import NotificationKind, Repo, Watch
from vinted_bot.log import get_logger
from vinted_bot.vinted import urls
from vinted_bot.vinted.errors import VintedError
from vinted_bot.vinted.models import Item, ItemSnapshot

log = get_logger(__name__)

ItemSnapshotReader = Callable[[str, int], Awaitable[ItemSnapshot]]
SellerItemsReader = Callable[[str, int], Awaitable[list[Item]]]

ITEM_INTERVAL_S = 30 * 60
SELLER_INTERVAL_S = 15 * 60
# Each watch's next check lands somewhere in [interval, interval * (1 + this)], so watches
# added together drift apart instead of firing in step forever.
_JITTER_FRACTION = 0.2
# The global budget: at most this many watch requests per pass, a pass at most this often.
CHECKS_PER_PASS = 4
PASS_INTERVAL_S = 60.0
# A seller who lists twenty things at once gets one alert per listing up to this many;
# past it, the rest are recorded quietly. Nobody wants forty pings.
_MAX_UPLOADS_ANNOUNCED = 10

# The labels a watch gets when nothing better is known: the dashboard's "Listing 123", the
# Telegram bot's "listing 123" or "seller 123", the repository's own "item 123".
_PLACEHOLDER = re.compile(r"(?i)(listing|item|seller) \d+")

# A listing that is gone or sold has nothing left to watch.
_FINAL_STATUSES = {"sold", "gone"}


class Watcher:
    """Runs every item and seller watch on a slow, shared budget."""

    def __init__(
        self,
        *,
        repo: Repo,
        stop: asyncio.Event,
        work_available: asyncio.Event | None = None,
        item_snapshot: ItemSnapshotReader | None = None,
        seller_items: SellerItemsReader | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._repo = repo
        self._stop = stop
        self._work_available = work_available
        self._item_snapshot = item_snapshot
        self._seller_items = seller_items
        self._rng = rng or random.Random()

    @property
    def available_kinds(self) -> frozenset[str]:
        """Which kinds of watch this build can actually run."""
        kinds = set()
        if self._item_snapshot is not None:
            kinds.add("item")
        if self._seller_items is not None:
            kinds.add("seller")
        return frozenset(kinds)

    async def run(self) -> None:
        if not self.available_kinds:
            log.info("watcher.unavailable", hint="this build cannot read listing or member pages")
            return
        while not self._stop.is_set():
            try:
                await self.run_pass()
            except sqlite3.OperationalError as exc:
                log.warning("watcher.db_unavailable", error=str(exc))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=PASS_INTERVAL_S)

    async def run_pass(self, *, now: int | None = None) -> int:
        """Check the watches that are due, up to the budget. Returns how many were checked."""
        moment = now or int(time.time())
        due = [
            watch
            for watch in await self._repo.due_watches(now=moment, limit=CHECKS_PER_PASS * 4)
            if watch.kind in self.available_kinds
        ][:CHECKS_PER_PASS]
        for watch in due:
            if self._stop.is_set():
                break
            await self.check(watch)
        return len(due)

    async def check(self, watch: Watch) -> None:
        """Check one watch now and schedule its next check."""
        try:
            if watch.kind == "item":
                await self._check_item(watch)
            else:
                await self._check_seller(watch)
        except VintedError as exc:
            # Transient by nature (a block, a rate limit, a network blip): keep the last
            # good state, note the error for the dashboard, and try again next interval.
            log.info("watcher.check_failed", watch_id=watch.id, error=str(exc))
            await self._repo.record_watch_check(
                watch.id, next_check_at=self._next_check(watch), error=str(exc)
            )

    async def _check_item(self, watch: Watch) -> None:
        if self._item_snapshot is None:  # pragma: no cover - filtered out by run_pass
            return
        snapshot = await self._item_snapshot(watch.tld, watch.target_id)
        await self._name(watch, snapshot.title)
        price = snapshot.total_price or snapshot.price
        event = None if watch.is_first_check else _item_event(watch, snapshot.status, price)
        if event is not None:
            item = Item(
                item_id=snapshot.item_id,
                tld=snapshot.tld,
                title=snapshot.title or watch.label,
                url=urls.item_url(snapshot.tld, snapshot.item_id),
                price=snapshot.price,
                total_price=snapshot.total_price,
                currency=snapshot.currency,
                photo_url=snapshot.photo_url,
                photo_urls=(snapshot.photo_url,) if snapshot.photo_url else (),
            )
            await self._repo.queue_watch_event(
                watch,
                item,
                kind=event,
                destination_ids=await self._repo.destination_ids_for_watch(watch.id),
                previous_price=watch.last_price if event == "price_drop" else None,
            )
            self._announce()
            log.info("watcher.item_event", watch_id=watch.id, item_id=watch.target_id, change=event)

        await self._repo.record_watch_check(
            watch.id,
            next_check_at=self._next_check(watch),
            price=price,
            currency=snapshot.currency,
            status=snapshot.status,
            active=snapshot.status not in _FINAL_STATUSES,
        )

    async def _check_seller(self, watch: Watch) -> None:
        if self._seller_items is None:  # pragma: no cover - filtered out by run_pass
            return
        listings = await self._seller_items(watch.tld, watch.target_id)
        await self._name(watch, next((i.seller_login for i in listings if i.seller_login), None))
        known = await self._repo.known_item_ids([item.item_id for item in listings])
        # Above the watch's high-water id and not stored for another reason. The stored
        # copies are pruned after a while; the high-water id is not, so a listing that
        # stays for sale for months is still only announced once.
        floor = watch.seen_up_to or 0
        new = sorted(
            (item for item in listings if item.item_id not in known and item.item_id > floor),
            key=lambda item: item.item_id,
        )
        # The first look records what the seller already has, like a search's first check.
        # So does a watch with no high-water id yet (one from before it existed).
        first_look = watch.is_first_check or watch.seen_up_to is None
        notify = [] if first_look else new[-_MAX_UPLOADS_ANNOUNCED:]
        await self._repo.record_seller_uploads(
            watch,
            new,
            notify=notify,
            destination_ids=await self._repo.destination_ids_for_watch(watch.id),
            # Zero for an empty wardrobe, so its first upload is not taken for a first look.
            seen_up_to=max((item.item_id for item in listings), default=0),
        )
        if notify:
            self._announce()
            log.info("watcher.seller_uploads", watch_id=watch.id, count=len(notify))
        await self._repo.record_watch_check(watch.id, next_check_at=self._next_check(watch))

    async def _name(self, watch: Watch, name: str | None) -> None:
        """Replace a stand-in label ("Listing 123") with the real title or seller name.

        A watch added from a bare link only knows the id, and its alerts were titled
        "Listing 10595427692" for as long as it ran.
        """
        if (
            name
            and _PLACEHOLDER.fullmatch(watch.label.strip())
            and str(watch.target_id) in (watch.label)
        ):
            await self._repo.update_watch(watch.id, label=name, active=watch.active)

    def _announce(self) -> None:
        if self._work_available is not None:
            self._work_available.set()

    def _next_check(self, watch: Watch) -> int:
        interval = ITEM_INTERVAL_S if watch.kind == "item" else SELLER_INTERVAL_S
        return int(time.time() + interval + self._rng.uniform(0, interval * _JITTER_FRACTION))


def _item_event(watch: Watch, status: str, price: Decimal | None) -> NotificationKind | None:
    """What, if anything, changed about a watched listing worth telling someone."""
    if status != watch.last_status:
        match status:
            case "sold":
                return "sold"
            case "reserved":
                return "reserved"
            case "gone":
                return "removed"
    if (
        status == "available"
        and watch.last_price is not None
        and price is not None
        and price < watch.last_price
    ):
        return "price_drop"
    return None
