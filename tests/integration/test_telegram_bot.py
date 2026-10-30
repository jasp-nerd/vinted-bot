"""The paired chat as a remote control: /list, /pause, /resume, /remove, /add."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, GetMe, SendMessage
from aiogram.methods.base import TelegramMethod, TelegramType
from aiogram.types import CallbackQuery, Chat, Message, MessageEntity, Update, User

from vinted_sniper.botctl.telegram_bot import (
    add_search_text,
    build_dispatcher,
    chat_destination_ids,
    confirm_remove_text,
    list_text,
    remove_prompt,
    set_paused_text,
)
from vinted_sniper.db.repo import Repo

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
            return User(id=1, is_bot=True, first_name="sniper", username="sniper_bot")
        self.calls.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            return _message(PAIRED_CHAT, str(method.text))
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
