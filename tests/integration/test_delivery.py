"""The outbox: what happens between finding a listing and it arriving."""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from vinted_bot import managed
from vinted_bot.botctl.telegram_bot import claim_pairing, create_pairing
from vinted_bot.config import Settings
from vinted_bot.db.repo import Query, Repo
from vinted_bot.deliver.dispatcher import MAX_ATTEMPTS, Dispatcher
from vinted_bot.vinted.models import Item


def listing(item_id: int) -> Item:
    return Item(
        item_id=item_id,
        tld="fr",
        title=f"Item {item_id}",
        url=f"https://www.vinted.fr/items/{item_id}",
        price=Decimal("10.00"),
        total_price=Decimal("11.70"),
        currency="EUR",
        photo_ts=int(time.time()),
    )


async def a_search(repo: Repo) -> Query:
    query_id = await repo.add_query(
        name="test",
        url="https://www.vinted.fr/catalog?search_text=x",
        tld="fr",
        params={},
        poll_interval_s=60,
    )
    query = await repo.get_query(query_id)
    assert query is not None
    return query


class FakeEndpoint:
    def __init__(self, *responses: httpx.Response) -> None:
        self.calls = 0
        self._responses = list(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self._responses:
            return self._responses.pop(0)
        return httpx.Response(200, json={"ok": True})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


def make_dispatcher(repo: Repo, settings: Settings, endpoint: FakeEndpoint) -> Dispatcher:
    return Dispatcher(
        repo=repo,
        settings=settings,
        stop=asyncio.Event(),
        work_available=asyncio.Event(),
        client=endpoint.client(),
    )


async def test_a_queued_notification_is_delivered_once(repo: Repo, settings: Settings) -> None:
    query = await a_search(repo)
    destination_id = await repo.add_destination(
        kind="webhook", name="test", config={"url": "https://example.test/hook"}
    )
    await repo.record_new_items(query, [listing(1)], [destination_id])

    endpoint = FakeEndpoint()
    sent = await make_dispatcher(repo, settings, endpoint).drain()

    assert sent == 1
    assert endpoint.calls == 1
    assert await repo.outbox_depth() == 0

    # A second pass has nothing left to do.
    assert await make_dispatcher(repo, settings, endpoint).drain() == 0
    assert endpoint.calls == 1


async def test_the_same_listing_is_never_queued_twice_for_one_destination(
    repo: Repo, settings: Settings
) -> None:
    query = await a_search(repo)
    destination_id = await repo.add_destination(
        kind="webhook", name="test", config={"url": "https://example.test/hook"}
    )

    await repo.record_new_items(query, [listing(1)], [destination_id])
    await repo.record_new_items(query, [listing(1)], [destination_id])

    assert await repo.outbox_depth() == 1


async def test_one_listing_reaches_every_destination_it_is_routed_to(
    repo: Repo, settings: Settings
) -> None:
    query = await a_search(repo)
    first = await repo.add_destination(
        kind="webhook", name="a", config={"url": "https://a.test/hook"}
    )
    second = await repo.add_destination(
        kind="webhook", name="b", config={"url": "https://b.test/hook"}
    )
    await repo.record_new_items(query, [listing(1)], [first, second])

    endpoint = FakeEndpoint()
    assert await make_dispatcher(repo, settings, endpoint).drain() == 2


async def test_a_failing_endpoint_is_retried_then_given_up_on(
    repo: Repo, settings: Settings
) -> None:
    query = await a_search(repo)
    destination_id = await repo.add_destination(
        kind="webhook", name="test", config={"url": "https://example.test/hook"}
    )
    await repo.record_new_items(query, [listing(1)], [destination_id])

    endpoint = FakeEndpoint(*[httpx.Response(500) for _ in range(MAX_ATTEMPTS + 2)])
    dispatcher = make_dispatcher(repo, settings, endpoint)

    for _ in range(MAX_ATTEMPTS + 1):
        await dispatcher.drain()
        # Retries are scheduled a little ahead; pretend that time has passed.
        await _make_everything_due(repo)

    assert await repo.outbox_depth() == 0, "it must not retry forever"
    row = await _outbox_row(repo)
    assert row["status"] == "failed"


async def test_a_dead_destination_is_switched_off(repo: Repo, settings: Settings) -> None:
    query = await a_search(repo)
    destination_id = await repo.add_destination(
        kind="discord", name="test", config={"webhook_url": "https://discord.test/hook"}
    )
    await repo.record_new_items(query, [listing(1)], [destination_id])

    endpoint = FakeEndpoint(httpx.Response(404, json={"message": "Unknown Webhook"}))
    await make_dispatcher(repo, settings, endpoint).drain()

    destination = await repo.get_destination(destination_id)
    assert destination is not None
    assert destination.active is False
    assert await repo.outbox_depth() == 0, "queued notifications for it are cleared out"


async def test_notifications_stranded_by_a_crash_are_picked_back_up(
    repo: Repo, settings: Settings
) -> None:
    query = await a_search(repo)
    destination_id = await repo.add_destination(
        kind="webhook", name="test", config={"url": "https://example.test/hook"}
    )
    await repo.record_new_items(query, [listing(1)], [destination_id])

    # Claim it, then vanish without acknowledging — what a kill -9 looks like.
    claimed = await repo.claim_batch(destination_id, 10)
    assert len(claimed) == 1
    assert await repo.outbox_depth() == 1

    recovered = await repo.recover_leases()
    assert recovered == 1

    endpoint = FakeEndpoint()
    assert await make_dispatcher(repo, settings, endpoint).drain() == 1


async def test_stale_notifications_are_dropped_rather_than_delivered_late(
    repo: Repo, settings: Settings
) -> None:
    query = await a_search(repo)
    destination_id = await repo.add_destination(
        kind="webhook", name="test", config={"url": "https://example.test/hook"}
    )
    await repo.record_new_items(query, [listing(1)], [destination_id])
    await _age_outbox(repo, minutes=settings.outbox_expiry_minutes + 10)

    endpoint = FakeEndpoint()
    sent = await make_dispatcher(repo, settings, endpoint).drain()

    assert sent == 0
    assert endpoint.calls == 0, "nobody wants an alert about a listing from two hours ago"
    assert await repo.outbox_depth() == 0


async def test_notifications_are_delivered_in_the_order_they_were_found(
    repo: Repo, settings: Settings
) -> None:
    query = await a_search(repo)
    destination_id = await repo.add_destination(
        kind="webhook", name="test", config={"url": "https://example.test/hook"}
    )
    for item_id in (1, 2, 3):
        await repo.record_new_items(query, [listing(item_id)], [destination_id])

    batch = await repo.claim_batch(destination_id, 10)

    assert [n.item.item_id for n in batch] == [1, 2, 3]


async def test_a_telegram_destination_without_a_token_is_reported_not_retried(
    repo: Repo, settings: Settings
) -> None:
    query = await a_search(repo)
    destination_id = await repo.add_destination(
        kind="telegram", name="test", config={"chat_id": "123"}
    )
    await repo.record_new_items(query, [listing(1)], [destination_id])

    endpoint = FakeEndpoint()
    await make_dispatcher(repo, settings, endpoint).drain()

    destination = await repo.get_destination(destination_id)
    assert destination is not None
    assert destination.active is False


async def _outbox_row(repo: Repo) -> Any:
    db = repo._db  # the test asserts on stored state on purpose
    row = await db.fetch_one("SELECT * FROM outbox LIMIT 1")
    assert row is not None
    return row


async def _make_everything_due(repo: Repo) -> None:
    db = repo._db
    await db.execute("UPDATE outbox SET next_attempt_at = 0 WHERE status = 'pending'")


async def _age_outbox(repo: Repo, *, minutes: int) -> None:
    db = repo._db
    await db.execute("UPDATE outbox SET created_at = ?", (int(time.time()) - minutes * 60,))


@pytest.mark.parametrize("kind", ["discord", "telegram", "webhook", "ntfy"])
async def test_every_destination_type_can_be_created(repo: Repo, kind: str) -> None:
    config = {
        "discord": {"webhook_url": "https://discord.test/hook"},
        "telegram": {"chat_id": "1"},
        "webhook": {"url": "https://example.test"},
        "ntfy": {"topic": "my-topic"},
    }[kind]

    destination_id = await repo.add_destination(kind=kind, name=kind, config=config)

    destination = await repo.get_destination(destination_id)
    assert destination is not None
    assert destination.kind == kind


async def test_a_telegram_destination_waiting_to_be_paired_is_left_alone(
    repo: Repo, settings: Settings
) -> None:
    """Tapping the pairing link can happen after the first listing turns up.

    A destination nobody has claimed yet is waiting, not misconfigured — switching it off
    would mean the link you are about to tap no longer works.
    """
    query = await a_search(repo)
    destination_id = await repo.add_destination(
        kind="telegram", name="waiting", config={"pairing_code": "abc", "created_at": 0}
    )
    await repo.record_new_items(query, [listing(1)], [destination_id])

    endpoint = FakeEndpoint()
    sent = await make_dispatcher(repo, settings, endpoint).drain()

    assert sent == 0
    destination = await repo.get_destination(destination_id)
    assert destination is not None
    assert destination.active is True, "waiting to be paired is not a failure"
    assert await repo.outbox_depth() == 1, "the notification waits for the chat to be bound"


async def test_connecting_a_chat_drops_the_backlog(repo: Repo) -> None:
    """Whoever just tapped the link wants what happens next, not a hundred old alerts."""
    query = await a_search(repo)
    destination_id, code = await create_pairing(repo, "Telegram")
    await repo.record_new_items(query, [listing(i) for i in range(1, 40)], [destination_id])
    assert await repo.outbox_depth() == 39

    assert await claim_pairing(repo, code, chat_id=4242, thread_id=None) == destination_id

    assert await repo.outbox_depth() == 0
    destination = await repo.get_destination(destination_id)
    assert destination is not None
    assert destination.config["chat_id"] == "4242"
    assert destination.active is True


async def test_asking_for_a_second_pairing_link_reuses_the_waiting_destination(
    repo: Repo,
) -> None:
    """Otherwise the searches stay pointed at the abandoned one and the new link is inert."""
    query = await a_search(repo)
    first_id, _ = await create_pairing(repo, "Telegram")
    await repo.route(query.id, first_id)

    second_id, code = await create_pairing(repo, "Telegram")

    assert second_id == first_id
    assert len(await repo.list_destinations()) == 1
    assert await claim_pairing(repo, code, chat_id=7, thread_id=None) == first_id
    assert await repo.destination_ids_for_query(query.id) == [first_id]


class RecordingEndpoint(FakeEndpoint):
    def __init__(self) -> None:
        super().__init__()
        self.paths: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        return super().handler(request)


async def test_telegram_sends_with_the_token_saved_in_the_dashboard(
    repo: Repo, settings: Settings
) -> None:
    query = await a_search(repo)
    destination_id = await repo.add_destination(
        kind="telegram", name="test", config={"chat_id": "123"}
    )
    await managed.set_telegram_token(repo, "111111:" + "a" * 35)
    await repo.record_new_items(query, [listing(1)], [destination_id])

    endpoint = RecordingEndpoint()
    await make_dispatcher(repo, settings, endpoint).drain()

    assert endpoint.paths[0].startswith("/bot111111:")


async def test_a_replaced_token_is_used_from_the_next_send(repo: Repo, settings: Settings) -> None:
    query = await a_search(repo)
    destination_id = await repo.add_destination(
        kind="telegram", name="test", config={"chat_id": "123"}
    )
    await managed.set_telegram_token(repo, "111111:" + "a" * 35)
    endpoint = RecordingEndpoint()
    dispatcher = make_dispatcher(repo, settings, endpoint)
    await repo.record_new_items(query, [listing(1)], [destination_id])
    await dispatcher.drain()

    await managed.set_telegram_token(repo, "222222:" + "b" * 35)
    await repo.record_new_items(query, [listing(2)], [destination_id])
    await dispatcher.drain()

    assert endpoint.paths[-1].startswith("/bot222222:")


async def test_the_environment_token_wins_over_the_dashboard_one(
    repo: Repo, settings: Settings
) -> None:
    pinned = settings.model_copy(update={"telegram_bot_token": SecretStr("333333:" + "c" * 35)})
    await managed.set_telegram_token(repo, "111111:" + "a" * 35)

    assert await managed.telegram_token(pinned, repo) == "333333:" + "c" * 35


async def test_ntfy_s_daily_limit_pauses_the_destination_with_a_reason(
    repo: Repo, settings: Settings
) -> None:
    query = await a_search(repo)
    destination_id = await repo.add_destination(kind="ntfy", name="p", config={"topic": "t"})
    await repo.record_new_items(query, [listing(1)], [destination_id])
    quota = httpx.Response(429, json={"code": 42908, "error": "daily message quota reached"})
    dispatcher = make_dispatcher(repo, settings, FakeEndpoint(quota))

    await dispatcher.drain()

    destination = await repo.get_destination(destination_id)
    assert destination is not None and destination.is_paused(int(time.time()))
    assert destination.paused_reason is not None and "daily" in destination.paused_reason


async def test_a_paused_destination_is_not_sent_to_until_the_pause_ends(
    repo: Repo, settings: Settings
) -> None:
    query = await a_search(repo)
    destination_id = await repo.add_destination(kind="ntfy", name="p", config={"topic": "t"})
    await repo.record_new_items(query, [listing(1)], [destination_id])
    quota = httpx.Response(429, json={"code": 42908, "error": "daily message quota reached"})
    endpoint = FakeEndpoint(quota)
    dispatcher = make_dispatcher(repo, settings, endpoint)
    await dispatcher.drain()
    await repo.record_new_items(query, [listing(2)], [destination_id])

    await dispatcher.drain()

    assert endpoint.calls == 1
