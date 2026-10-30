"""The paired chat as a remote control: /list, /pause, /resume, /remove, /add, pasted
links, and the buttons on every alert."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageReplyMarkup,
    EditMessageText,
    GetMe,
    SendMessage,
)
from aiogram.methods.base import TelegramMethod, TelegramType
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MessageEntity,
    Update,
    User,
)

from vinted_bot import managed
from vinted_bot.botctl.telegram_bot import (
    add_link_text,
    add_search_text,
    apply_action,
    build_dispatcher,
    chat_destination_ids,
    confirm_remove_text,
    done_markup,
    keep_running,
    list_text,
    remove_prompt,
    set_paused_text,
)
from vinted_bot.config import Settings
from vinted_bot.db.repo import Repo
from vinted_bot.vinted.models import Item

SEARCH_URL = "https://www.vinted.fr/catalog?search_text=nike%20air&price_to=40"
PAIRED_CHAT = 4242


async def paired_chat(repo: Repo, chat_id: int = PAIRED_CHAT) -> int:
    return await repo.add_destination(
        kind="telegram", name="phone", config={"chat_id": str(chat_id)}
    )


async def a_search(repo: Repo, name: str = "nike") -> int:
    return await repo.add_query(
        name=name,
        url=f"https://www.vinted.fr/catalog?search_text={name}",
        tld="fr",
        params={"search_text": name},
        poll_interval_s=60,
    )


# --- The commands ----------------------------------------------------------------------


async def test_list_numbers_each_search_with_its_state(repo: Repo) -> None:
    query_id = await a_search(repo, "levis <501>")
    await repo.set_paused(query_id, True)

    text = await list_text(repo)

    assert f"<b>{query_id}</b> · levis &lt;501&gt; · vinted.fr · <i>paused</i>" in text


async def test_list_with_no_searches_says_how_to_start(repo: Repo) -> None:
    assert "/add" in await list_text(repo)


async def test_pause_pauses_the_numbered_search(repo: Repo) -> None:
    query_id = await a_search(repo)

    await set_paused_text(repo, str(query_id), paused=True)

    query = await repo.get_query(query_id)
    assert query is not None and query.paused is True


async def test_resume_unpauses_it(repo: Repo) -> None:
    query_id = await a_search(repo)
    await repo.set_paused(query_id, True)

    await set_paused_text(repo, f"#{query_id}", paused=False)

    query = await repo.get_query(query_id)
    assert query is not None and query.paused is False


async def test_pause_without_a_number_explains_itself(repo: Repo) -> None:
    assert "/pause 2" in await set_paused_text(repo, "", paused=True)


async def test_pause_of_an_unknown_search_says_so(repo: Repo) -> None:
    assert "no search 99" in await set_paused_text(repo, "99", paused=True)


async def test_remove_asks_before_deleting(repo: Repo) -> None:
    query_id = await a_search(repo)

    _, keyboard = await remove_prompt(repo, str(query_id))

    assert await repo.get_query(query_id) is not None
    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].style == "danger"


async def test_confirming_removes_the_search(repo: Repo) -> None:
    query_id = await a_search(repo)

    await confirm_remove_text(repo, f"remove:{query_id}")

    assert await repo.get_query(query_id) is None


async def test_keeping_leaves_it_alone(repo: Repo) -> None:
    query_id = await a_search(repo)

    assert await confirm_remove_text(repo, "remove:keep") == "Kept."
    assert await repo.get_query(query_id) is not None


async def test_add_watches_the_link_and_routes_it_to_this_chat(repo: Repo) -> None:
    destination_id = await paired_chat(repo)

    await add_search_text(repo, SEARCH_URL, chat_id=PAIRED_CHAT, interval_s=60)

    (query,) = await repo.list_queries()
    assert await repo.destination_ids_for_query(query.id) == [destination_id]


async def test_add_names_the_search_after_its_text(repo: Repo) -> None:
    await paired_chat(repo)

    await add_search_text(repo, SEARCH_URL, chat_id=PAIRED_CHAT, interval_s=60)

    (query,) = await repo.list_queries()
    assert query.name == "nike air"


async def test_add_never_polls_faster_than_the_floor(repo: Repo) -> None:
    await add_search_text(repo, SEARCH_URL, chat_id=PAIRED_CHAT, interval_s=1)

    (query,) = await repo.list_queries()
    assert query.poll_interval_s >= 10


async def test_add_refuses_a_duplicate(repo: Repo) -> None:
    await add_search_text(repo, SEARCH_URL, chat_id=PAIRED_CHAT, interval_s=60)

    reply = await add_search_text(repo, SEARCH_URL, chat_id=PAIRED_CHAT, interval_s=60)

    assert "already" in reply and len(await repo.list_queries()) == 1


async def test_add_explains_a_link_that_is_not_a_search(repo: Repo) -> None:
    reply = await add_search_text(repo, "https://example.com/", chat_id=1, interval_s=60)

    assert reply.startswith("That link will not work")


async def test_only_this_chat_s_destinations_count(repo: Repo) -> None:
    mine = await paired_chat(repo, 1)
    await paired_chat(repo, 2)

    assert await chat_destination_ids(repo, 1) == [mine]


# --- Pasted links -----------------------------------------------------------------------


async def test_a_pasted_search_link_is_watched(repo: Repo) -> None:
    await paired_chat(repo)

    await add_link_text(repo, f"look {SEARCH_URL}", chat_id=PAIRED_CHAT, interval_s=60)

    assert [query.url for query in await repo.list_queries()] == [
        "https://www.vinted.fr/catalog?order=newest_first&price_to=40&search_text=nike+air"
    ]


async def test_a_pasted_listing_link_is_followed_for_its_price(repo: Repo) -> None:
    await paired_chat(repo)

    await add_link_text(
        repo,
        "https://www.vinted.fr/items/4242424242-carhartt-detroit-jacket",
        chat_id=PAIRED_CHAT,
        interval_s=60,
    )

    (watch,) = await repo.list_watches()
    assert (watch.kind, watch.tld, watch.target_id, watch.label) == (
        "item",
        "fr",
        4242424242,
        "carhartt detroit jacket",
    )


async def test_a_pasted_profile_link_follows_the_seller(repo: Repo) -> None:
    await paired_chat(repo)

    await add_link_text(repo, "vinted.de/member/777-jo_vint", chat_id=PAIRED_CHAT, interval_s=60)

    (watch,) = await repo.list_watches()
    assert (watch.kind, watch.tld, watch.target_id, watch.label) == ("seller", "de", 777, "jo_vint")


async def test_a_pasted_watch_sends_its_alerts_to_this_chat(repo: Repo) -> None:
    destination_id = await paired_chat(repo)
    await repo.add_destination(kind="ntfy", name="elsewhere", config={"topic": "t"})

    await add_link_text(repo, "https://www.vinted.fr/items/42", chat_id=PAIRED_CHAT, interval_s=60)

    (watch,) = await repo.list_watches()
    assert await repo.destination_ids_for_watch(watch.id) == [destination_id]


async def test_a_listing_already_followed_says_so(repo: Repo) -> None:
    await paired_chat(repo)
    link = "https://www.vinted.fr/items/42"
    await add_link_text(repo, link, chat_id=PAIRED_CHAT, interval_s=60)

    reply = await add_link_text(repo, link, chat_id=PAIRED_CHAT, interval_s=60)

    assert reply == "That is already being watched."


async def test_text_without_a_link_is_not_a_link(repo: Repo) -> None:
    assert await add_link_text(repo, "hello", chat_id=PAIRED_CHAT, interval_s=60) is None


# --- Alert buttons ----------------------------------------------------------------------


async def stored_listing(repo: Repo, item_id: int = 7) -> int:
    query_id = await a_search(repo)
    query = await repo.get_query(query_id)
    assert query is not None
    item = Item(item_id=item_id, tld="fr", title="x", url=f"https://www.vinted.fr/items/{item_id}")
    await repo.record_new_items(query, [item], [])
    return query_id


async def test_block_seller_adds_the_seller_to_the_blocklist(repo: Repo) -> None:
    await apply_action(repo, "a:b:555:fr:jo_vint")

    (blocked,) = await repo.list_blocked_sellers()
    assert (blocked.seller_id, blocked.login, blocked.tld) == (555, "jo_vint", "fr")


async def test_a_pressed_block_button_says_so_in_the_site_language(repo: Repo) -> None:
    result = await apply_action(repo, "a:b:555:fr")

    assert result.done_label == "Vendeur bloqué"


async def test_mute_silences_the_search_for_an_hour(repo: Repo) -> None:
    query_id = await a_search(repo)

    await apply_action(repo, f"a:m:{query_id}:fr")

    query = await repo.get_query(query_id)
    assert query is not None and query.muted_until is not None
    assert 3590 <= query.muted_until - int(time.time()) <= 3600


async def test_muting_a_deleted_search_changes_nothing(repo: Repo) -> None:
    result = await apply_action(repo, "a:m:99:fr")

    assert (result.toast, result.done_label) == ("That search no longer exists.", None)


async def test_hide_hides_the_listing_from_the_dashboard(repo: Repo) -> None:
    await stored_listing(repo)

    await apply_action(repo, "a:h:7:fr")

    assert [entry.item.item_id for entry in await repo.items_feed(mark="hidden")] == [7]


async def test_hiding_a_listing_no_longer_stored_says_so(repo: Repo) -> None:
    result = await apply_action(repo, "a:h:7:fr")

    assert result.toast == "That listing is no longer stored."


@pytest.mark.parametrize("data", ["a:x:1:fr", "a:b:notanumber:fr", "a:b:1"])
async def test_a_button_this_version_does_not_know_changes_nothing(repo: Repo, data: str) -> None:
    result = await apply_action(repo, data)

    assert result.done_label is None


def test_the_pressed_button_alone_turns_into_its_done_state() -> None:
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Open", url="https://www.vinted.fr/items/7")],
            [
                InlineKeyboardButton(text="Block seller", callback_data="a:b:5:fr"),
                InlineKeyboardButton(text="Hide", callback_data="a:h:7:fr"),
            ],
        ]
    )

    changed = done_markup(markup, "a:h:7:fr", "Hidden")

    assert [[button.text for button in row] for row in changed.inline_keyboard] == [
        ["Open"],
        ["Block seller", "Hidden"],
    ]


# --- Through aiogram -------------------------------------------------------------------


class RecordingSession(BaseSession):
    """Stands in for Telegram's servers: records each API call and answers it minimally."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []

    async def close(self) -> None:
        return None

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,  # noqa: ASYNC109 - the signature aiogram defines
    ) -> Any:
        if isinstance(method, GetMe):
            return User(id=1, is_bot=True, first_name="vinted-bot", username="vinted_alerts_bot")
        self.calls.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            return _message(PAIRED_CHAT, str(method.text))
        if isinstance(method, EditMessageReplyMarkup):
            return _message(PAIRED_CHAT, "alert")
        if isinstance(method, AnswerCallbackQuery):
            return True
        raise AssertionError(f"unexpected call {type(method).__name__}")

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,  # noqa: ASYNC109 - the signature aiogram defines
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes]:
        yield b""


def _message(chat_id: int, text: str) -> Message:
    command_length = len(text.split(maxsplit=1)[0]) if text.startswith("/") else 0
    return Message(
        message_id=1,
        date=datetime.now(tz=UTC),
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=chat_id, is_bot=False, first_name="me"),
        text=text,
        entities=(
            [MessageEntity(type="bot_command", offset=0, length=command_length)]
            if command_length
            else None
        ),
    )


@pytest.fixture
async def bot() -> AsyncGenerator[Bot]:
    instance = Bot(token="42:test", session=RecordingSession())
    yield instance
    await instance.session.close()


def sent(bot: Bot) -> list[TelegramMethod[Any]]:
    session = bot.session
    assert isinstance(session, RecordingSession)
    return session.calls


async def test_a_paired_chat_gets_answers(repo: Repo, bot: Bot) -> None:
    await paired_chat(repo)
    dispatcher = build_dispatcher(repo)

    await dispatcher.feed_update(bot, Update(update_id=1, message=_message(PAIRED_CHAT, "/list")))

    (reply,) = sent(bot)
    assert isinstance(reply, SendMessage) and "No searches yet" in reply.text


async def test_a_stranger_gets_silence(repo: Repo, bot: Bot) -> None:
    await paired_chat(repo)
    await a_search(repo)
    dispatcher = build_dispatcher(repo)

    await dispatcher.feed_update(bot, Update(update_id=1, message=_message(999, "/list")))

    assert sent(bot) == []


async def test_a_stranger_cannot_pause_anything(repo: Repo, bot: Bot) -> None:
    query_id = await a_search(repo)
    dispatcher = build_dispatcher(repo)

    await dispatcher.feed_update(
        bot, Update(update_id=1, message=_message(999, f"/pause {query_id}"))
    )

    query = await repo.get_query(query_id)
    assert query is not None and query.paused is False


async def test_anyone_can_still_start_pairing(repo: Repo, bot: Bot) -> None:
    dispatcher = build_dispatcher(repo)

    await dispatcher.feed_update(bot, Update(update_id=1, message=_message(999, "/start")))

    assert len(sent(bot)) == 1


async def test_add_uses_the_configured_interval(repo: Repo, bot: Bot) -> None:
    await paired_chat(repo)
    dispatcher = build_dispatcher(repo, default_interval_s=300)

    await dispatcher.feed_update(
        bot, Update(update_id=1, message=_message(PAIRED_CHAT, f"/add {SEARCH_URL}"))
    )

    (query,) = await repo.list_queries()
    assert query.poll_interval_s == 300


async def test_the_remove_button_deletes_and_replaces_the_question(repo: Repo, bot: Bot) -> None:
    await paired_chat(repo)
    query_id = await a_search(repo)
    dispatcher = build_dispatcher(repo)
    press = CallbackQuery(
        id="1",
        from_user=User(id=PAIRED_CHAT, is_bot=False, first_name="me"),
        chat_instance="x",
        message=_message(PAIRED_CHAT, "Remove “nike”?"),
        data=f"remove:{query_id}",
    )

    await dispatcher.feed_update(bot, Update(update_id=1, callback_query=press))

    assert await repo.get_query(query_id) is None
    assert any(isinstance(call, EditMessageText) for call in sent(bot))


def _alert(chat_id: int, query_id: int) -> Message:
    """A listing alert as the bot sent it, with its action buttons."""
    return _message(chat_id, "alert").model_copy(
        update={
            "reply_markup": InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Mute 1 h", callback_data=f"a:m:{query_id}:fr"),
                        InlineKeyboardButton(text="Hide", callback_data="a:h:7:fr"),
                    ]
                ]
            )
        }
    )


def _press(chat_id: int, query_id: int) -> CallbackQuery:
    return CallbackQuery(
        id="1",
        from_user=User(id=chat_id, is_bot=False, first_name="me"),
        chat_instance="x",
        message=_alert(chat_id, query_id),
        data=f"a:m:{query_id}:fr",
    )


async def test_pressing_mute_answers_with_a_toast(repo: Repo, bot: Bot) -> None:
    await paired_chat(repo)
    query_id = await a_search(repo)
    dispatcher = build_dispatcher(repo)

    await dispatcher.feed_update(
        bot, Update(update_id=1, callback_query=_press(PAIRED_CHAT, query_id))
    )

    toast = next(call for call in sent(bot) if isinstance(call, AnswerCallbackQuery))
    assert toast.text == "“nike” is muted for an hour."


async def test_pressing_mute_redraws_the_button_as_done(repo: Repo, bot: Bot) -> None:
    await paired_chat(repo)
    query_id = await a_search(repo)
    dispatcher = build_dispatcher(repo)

    await dispatcher.feed_update(
        bot, Update(update_id=1, callback_query=_press(PAIRED_CHAT, query_id))
    )

    edit = next(call for call in sent(bot) if isinstance(call, EditMessageReplyMarkup))
    assert edit.reply_markup is not None
    assert [b.text for b in edit.reply_markup.inline_keyboard[0]] == ["En silence 1 h", "Hide"]


async def test_a_stranger_s_button_press_does_nothing(repo: Repo, bot: Bot) -> None:
    """A forwarded alert's buttons only work in a paired chat."""
    await paired_chat(repo)
    query_id = await a_search(repo)
    dispatcher = build_dispatcher(repo)

    await dispatcher.feed_update(bot, Update(update_id=1, callback_query=_press(999, query_id)))

    query = await repo.get_query(query_id)
    assert query is not None and query.muted_until is None


async def test_pasting_a_link_in_the_chat_watches_it(repo: Repo, bot: Bot) -> None:
    await paired_chat(repo)
    dispatcher = build_dispatcher(repo)

    await dispatcher.feed_update(
        bot, Update(update_id=1, message=_message(PAIRED_CHAT, f"this one {SEARCH_URL}"))
    )

    assert len(await repo.list_queries()) == 1


async def test_add_with_a_listing_link_follows_the_listing(repo: Repo, bot: Bot) -> None:
    await paired_chat(repo)
    dispatcher = build_dispatcher(repo)

    await dispatcher.feed_update(
        bot,
        Update(update_id=1, message=_message(PAIRED_CHAT, "/add https://www.vinted.fr/items/42")),
    )

    assert [watch.target_id for watch in await repo.list_watches()] == [42]


# --- Following the token the dashboard sets -----------------------------------------------

TOKEN_A = "111111:" + "a" * 35
TOKEN_B = "222222:" + "b" * 35


class Bots:
    """Stands in for run_bot: records which tokens a bot ran on and which are still up."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.running: set[str] = set()
        self.changed = asyncio.Event()

    async def run(self, token: str, stop: asyncio.Event) -> None:
        self.started.append(token)
        self.running.add(token)
        self.changed.set()
        try:
            await stop.wait()
        finally:
            self.running.discard(token)
            self.changed.set()


@pytest.fixture
async def following(repo: Repo, settings: Settings) -> AsyncGenerator[tuple[Bots, asyncio.Event]]:
    bots = Bots()
    stop, token_changed = asyncio.Event(), asyncio.Event()
    task = asyncio.create_task(
        keep_running(settings, repo, stop=stop, token_changed=token_changed, run=bots.run)
    )
    yield bots, token_changed
    stop.set()
    await task


async def _settle(bots: Bots, until: Callable[[], bool]) -> None:
    async with asyncio.timeout(2):
        while not until():
            bots.changed.clear()
            await bots.changed.wait()


async def test_no_token_means_no_bot(following: tuple[Bots, asyncio.Event]) -> None:
    bots, _ = following
    await asyncio.sleep(0.05)

    assert bots.started == []


async def test_a_token_saved_in_the_dashboard_starts_the_bot(
    repo: Repo, following: tuple[Bots, asyncio.Event]
) -> None:
    bots, token_changed = following
    await managed.set_telegram_token(repo, TOKEN_A)
    token_changed.set()

    await _settle(bots, lambda: TOKEN_A in bots.running)

    assert bots.started == [TOKEN_A]


async def test_a_new_token_replaces_the_running_bot(
    repo: Repo, following: tuple[Bots, asyncio.Event]
) -> None:
    bots, token_changed = following
    await managed.set_telegram_token(repo, TOKEN_A)
    token_changed.set()
    await _settle(bots, lambda: TOKEN_A in bots.running)

    await managed.set_telegram_token(repo, TOKEN_B)
    token_changed.set()
    await _settle(bots, lambda: bots.running == {TOKEN_B})

    assert bots.started == [TOKEN_A, TOKEN_B]


async def test_removing_the_token_stops_the_bot(
    repo: Repo, following: tuple[Bots, asyncio.Event]
) -> None:
    bots, token_changed = following
    await managed.set_telegram_token(repo, TOKEN_A)
    token_changed.set()
    await _settle(bots, lambda: TOKEN_A in bots.running)

    await managed.set_telegram_token(repo, None)
    token_changed.set()
    await _settle(bots, lambda: not bots.running)

    assert bots.started == [TOKEN_A]


async def test_shutting_down_stops_the_bot(repo: Repo, settings: Settings) -> None:
    bots = Bots()
    stop, token_changed = asyncio.Event(), asyncio.Event()
    await managed.set_telegram_token(repo, TOKEN_A)
    task = asyncio.create_task(
        keep_running(settings, repo, stop=stop, token_changed=token_changed, run=bots.run)
    )
    await _settle(bots, lambda: TOKEN_A in bots.running)

    stop.set()
    await asyncio.wait_for(task, 2)

    assert bots.running == set()


async def test_add_points_at_the_search_already_watching_the_link(repo: Repo) -> None:
    await add_search_text(repo, SEARCH_URL, chat_id=PAIRED_CHAT, interval_s=60)

    reply = await add_search_text(repo, SEARCH_URL, chat_id=PAIRED_CHAT, interval_s=60)

    assert reply.startswith("You already watch this search: “nike air”.")
    assert len(await repo.list_queries()) == 1
