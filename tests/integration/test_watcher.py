"""Item and seller watches, with stand-ins for the transport's page readers."""

from __future__ import annotations

import asyncio
import random
from decimal import Decimal

import pytest

from vinted_sniper.db.repo import Repo
from vinted_sniper.engine.watcher import Watcher
from vinted_sniper.vinted.errors import BlockedError
from vinted_sniper.vinted.models import Item, ItemSnapshot


class Pages:
    """Answers item and seller reads from queues the test fills."""

    def __init__(self) -> None:
        self.snapshots: list[ItemSnapshot | Exception] = []
        self.seller_pages: list[list[Item]] = []

    async def item_snapshot(self, tld: str, item_id: int) -> ItemSnapshot:
        answer = self.snapshots.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def seller_items(self, tld: str, seller_id: int) -> list[Item]:
        return self.seller_pages.pop(0)


def snapshot(price: str, status: str = "available") -> ItemSnapshot:
    return ItemSnapshot(
        item_id=10,
        tld="fr",
        title="Barbour jacket",
        price=Decimal(price),
        total_price=Decimal(price) + 1,
        currency="EUR",
        status=status,
    )


def upload(item_id: int) -> Item:
    return Item(item_id=item_id, tld="fr", title=f"Upload {item_id}", url=f"https://x/{item_id}")


@pytest.fixture
def pages() -> Pages:
    return Pages()


def watcher(repo: Repo, pages: Pages) -> Watcher:
    return Watcher(
        repo=repo,
        stop=asyncio.Event(),
        item_snapshot=pages.item_snapshot,
        seller_items=pages.seller_items,
        rng=random.Random(3),
    )


async def check(repo: Repo, pages: Pages, watch_id: int) -> None:
    watch = await repo.get_watch(watch_id)
    assert watch is not None
    await watcher(repo, pages).check(watch)


async def item_watch(repo: Repo) -> tuple[int, int]:
    destination_id = await repo.add_destination(kind="ntfy", name="n", config={"topic": "t"})
    watch_id = await repo.add_watch(kind="item", tld="fr", target_id=10, label="Barbour")
    return watch_id, destination_id


async def test_the_first_look_at_a_listing_only_records_its_price(repo: Repo, pages: Pages) -> None:
    watch_id, _ = await item_watch(repo)
    pages.snapshots.append(snapshot("50"))

    await check(repo, pages, watch_id)

    watch = await repo.get_watch(watch_id)
    assert watch is not None and watch.last_price == Decimal("51.00")
    assert await repo.outbox_depth() == 0


async def test_a_price_drop_is_announced_with_the_old_price(repo: Repo, pages: Pages) -> None:
    watch_id, destination_id = await item_watch(repo)
    pages.snapshots += [snapshot("50"), snapshot("40")]
    await check(repo, pages, watch_id)

    await check(repo, pages, watch_id)

    (notification,) = await repo.claim_batch(destination_id, 10)
    assert (notification.kind, notification.previous_price) == ("price_drop", Decimal("51.00"))
    assert notification.item.total_price == Decimal("41.00")
    assert notification.query_name == "Barbour"


async def test_a_price_rise_is_noted_quietly(repo: Repo, pages: Pages) -> None:
    watch_id, _ = await item_watch(repo)
    pages.snapshots += [snapshot("50"), snapshot("60")]
    await check(repo, pages, watch_id)

    await check(repo, pages, watch_id)

    assert await repo.outbox_depth() == 0


async def test_a_sale_is_announced_and_ends_the_watch(repo: Repo, pages: Pages) -> None:
    watch_id, destination_id = await item_watch(repo)
    pages.snapshots += [snapshot("50"), snapshot("50", status="sold")]
    await check(repo, pages, watch_id)

    await check(repo, pages, watch_id)

    (notification,) = await repo.claim_batch(destination_id, 10)
    assert notification.kind == "sold"
    watch = await repo.get_watch(watch_id)
    assert watch is not None and watch.active is False


async def test_a_reservation_is_announced_once(repo: Repo, pages: Pages) -> None:
    watch_id, _ = await item_watch(repo)
    pages.snapshots += [
        snapshot("50"),
        snapshot("50", status="reserved"),
        snapshot("50", status="reserved"),
    ]
    for _ in range(3):
        await check(repo, pages, watch_id)

    assert await repo.outbox_depth() == 1


async def test_a_failed_check_keeps_the_last_good_state(repo: Repo, pages: Pages) -> None:
    watch_id, _ = await item_watch(repo)
    pages.snapshots += [snapshot("50"), BlockedError("refused")]
    await check(repo, pages, watch_id)

    await check(repo, pages, watch_id)

    watch = await repo.get_watch(watch_id)
    assert watch is not None
    assert (watch.last_price, watch.last_error) == (Decimal("51.00"), "refused")


async def test_a_seller_watch_announces_only_uploads_after_the_first_look(
    repo: Repo, pages: Pages
) -> None:
    destination_id = await repo.add_destination(kind="ntfy", name="n", config={"topic": "t"})
    watch_id = await repo.add_watch(kind="seller", tld="fr", target_id=77, label="Good seller")
    pages.seller_pages += [[upload(1), upload(2)], [upload(3), upload(1), upload(2)]]
    await check(repo, pages, watch_id)

    await check(repo, pages, watch_id)

    notifications = await repo.claim_batch(destination_id, 10)
    assert [(n.kind, n.item.item_id) for n in notifications] == [("seller_upload", 3)]
    assert [e.item.item_id for e in await repo.items_feed()] == [3, 2, 1]


async def test_watches_are_spread_out_after_a_check(repo: Repo, pages: Pages) -> None:
    first, _ = await item_watch(repo)
    second = await repo.add_watch(kind="item", tld="fr", target_id=11, label="Other")
    pages.snapshots += [snapshot("50"), snapshot("50")]

    assert await watcher(repo, pages).run_pass() == 2

    a, b = await repo.get_watch(first), await repo.get_watch(second)
    assert a is not None and b is not None
    assert a.next_check_at != b.next_check_at


async def test_watching_the_same_thing_twice_is_refused(repo: Repo) -> None:
    await repo.add_watch(kind="item", tld="fr", target_id=10, label="one")

    with pytest.raises(ValueError, match="already"):
        await repo.add_watch(kind="item", tld="fr", target_id=10, label="two")


async def test_without_page_readers_watches_are_parked_not_failed(repo: Repo) -> None:
    await repo.add_watch(kind="item", tld="fr", target_id=10, label="parked")
    parked = Watcher(repo=repo, stop=asyncio.Event())

    assert parked.available_kinds == frozenset()
    assert await parked.run_pass() == 0


async def test_a_watch_routed_nowhere_goes_to_every_destination(repo: Repo) -> None:
    watch_id, destination_id = await item_watch(repo)

    assert await repo.destination_ids_for_watch(watch_id) == [destination_id]
