"""The Telegram bot, which exists mostly to solve one annoying problem.

Telegram bots cannot message someone first, so before we can send you anything we need your
chat id — and asking people to find their own numeric chat id is where most setup guides
lose them. Instead the app prints a link, you tap it, the bot receives `/start` with a
one-time code, and it records the chat itself. Works the same for a group or a forum topic.

Once paired, the chat doubles as a remote control: /list, /pause, /resume, /remove (with a
confirmation button) and /add with a pasted search link, plus /status to ask whether
everything is still running without opening the web UI. Only chats that were paired get
answers, because anyone can find a bot by name and message it.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    TelegramObject,
)

from vinted_sniper.config import MIN_POLL_INTERVAL_S
from vinted_sniper.db.repo import Repo
from vinted_sniper.engine import health
from vinted_sniper.log import get_logger
from vinted_sniper.vinted import urls

log = get_logger(__name__)

# Long enough that a code cannot be guessed, short enough to paste into a URL.
_CODE_BYTES = 8

# A pairing code that goes unused expires, so a link left in a chat log is not a way in.
PAIRING_TTL_S = 1800

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def new_pairing_code() -> str:
    return secrets.token_urlsafe(_CODE_BYTES)


async def create_pairing(repo: Repo, name: str) -> tuple[int, str]:
    """Set up a Telegram destination waiting for someone to claim it.

    Asking for a link twice — because the first one expired, or went to the wrong chat —
    refreshes the code on the destination already waiting rather than leaving a second one
    behind. Otherwise the searches stay routed to the abandoned one and the new link
    connects you to a destination nothing feeds.
    """
    code = new_pairing_code()
    config = {"pairing_code": code, "created_at": int(time.time())}

    for destination in await repo.list_destinations():
        if destination.kind == "telegram" and destination.config.get("pairing_code"):
            await repo.update_destination_config(destination.id, config)
            return destination.id, code

    destination_id = await repo.add_destination(kind="telegram", name=name, config=config)
    return destination_id, code


async def claim_pairing(repo: Repo, code: str, chat_id: int, thread_id: int | None) -> int | None:
    """Bind a waiting destination to the chat that presented the code."""
    for destination in await repo.list_destinations():
        config: dict[str, Any] = destination.config
        if destination.kind != "telegram" or config.get("pairing_code") != code:
            continue
        if int(time.time()) - int(config.get("created_at", 0)) > PAIRING_TTL_S:
            return None
        new_config = {"chat_id": str(chat_id)}
        if thread_id is not None:
            new_config["message_thread_id"] = str(thread_id)
        await repo.update_destination_config(destination.id, new_config)

        # Anything queued while this chat did not exist yet is not news to whoever just
        # connected — it is a wall of alerts for listings they never asked about. They want
        # what turns up from now on.
        dropped = await repo.discard_pending_for(
            destination.id, "queued before the chat was connected"
        )
        if dropped:
            log.info("telegram.backlog_dropped", destination_id=destination.id, count=dropped)
        return destination.id
    return None


async def _pending_pairing_exists(repo: Repo) -> bool:
    return any(
        destination.kind == "telegram" and destination.config.get("pairing_code")
        for destination in await repo.list_destinations()
    )


# --- Commands -------------------------------------------------------------------------
# Each command's work is a plain function of the repo and its argument, returning the
# reply. The aiogram handlers below only route to them, which keeps the behaviour testable
# against a real database without a fake Telegram.

HELP_TEXT = (
    "/list: your searches and how each is doing\n"
    "/pause 3, /resume 3: stop or restart search 3\n"
    "/remove 3: delete search 3 (asks first)\n"
    "/add <Vinted search link>: watch it, with alerts in this chat\n"
    "/status: is everything still running\n"
    "/start <code>: connect this chat to vinted-sniper"
)

_REMOVE_PREFIX = "remove:"
_KEEP = "remove:keep"


async def chat_destination_ids(repo: Repo, chat_id: int) -> list[int]:
    """The active Telegram destinations delivering to this chat."""
    return [
        destination.id
        for destination in await repo.list_destinations(active_only=True)
        if destination.kind == "telegram" and destination.config.get("chat_id") == str(chat_id)
    ]


def _search_id(argument: str | None) -> int | None:
    text = (argument or "").strip().lstrip("#")
    return int(text) if text.isdigit() else None


async def list_text(repo: Repo) -> str:
    snapshot = await health.snapshot(repo)
    if not snapshot.searches:
        return "No searches yet. Send /add with a Vinted search link to start one."
    lines = ["<b>Your searches</b>"]
    lines.extend(
        f"<b>{search.query_id}</b> · {html.escape(search.name)} · vinted.{search.tld} · "
        f"<i>{search.state}</i>"
        for search in snapshot.searches
    )
    lines.append("\n/pause 2 or /resume 2 to switch one off or on.")
    return "\n".join(lines)


async def set_paused_text(repo: Repo, argument: str | None, *, paused: bool) -> str:
    verb = "pause" if paused else "resume"
    query_id = _search_id(argument)
    if query_id is None:
        return f"Which one? Send /{verb} with the number from /list, like /{verb} 2."
    query = await repo.get_query(query_id)
    if query is None:
        return f"There is no search {query_id}. /list shows the numbers."
    await repo.set_paused(query_id, paused)
    state = "Paused" if paused else "Resumed"
    return f"{state} “{html.escape(query.name)}”."


async def remove_prompt(
    repo: Repo, argument: str | None
) -> tuple[str, InlineKeyboardMarkup | None]:
    """Ask before deleting: a search's history goes with it, and a typo picks the wrong one."""
    query_id = _search_id(argument)
    if query_id is None:
        return "Which one? Send /remove with the number from /list, like /remove 2.", None
    query = await repo.get_query(query_id)
    if query is None:
        return f"There is no search {query_id}. /list shows the numbers.", None
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Remove", callback_data=f"{_REMOVE_PREFIX}{query_id}", style="danger"
                ),
                InlineKeyboardButton(text="Keep it", callback_data=_KEEP),
            ]
        ]
    )
    return f"Remove “{html.escape(query.name)}”? This cannot be undone.", keyboard


async def confirm_remove_text(repo: Repo, callback_data: str) -> str:
    if callback_data == _KEEP:
        return "Kept."
    query_id = _search_id(callback_data.removeprefix(_REMOVE_PREFIX))
    query = await repo.get_query(query_id) if query_id is not None else None
    if query is None:
        return "That search is already gone."
    await repo.delete_query(query.id)
    return f"Removed “{html.escape(query.name)}”."


async def add_search_text(
    repo: Repo, argument: str | None, *, chat_id: int, interval_s: int
) -> str:
    """Watch a pasted search, with its alerts routed to the chat that asked."""
    if not (argument or "").strip():
        return "Send /add followed by a Vinted search link, copied from the address bar."
    try:
        normalised = urls.normalise_search_url(argument or "")
        tld = urls.extract_tld(normalised)
        params = urls.parse_search_params(normalised)
    except urls.InvalidSearchURLError as exc:
        return f"That link will not work: {html.escape(str(exc))}"
    if await repo.find_query_by_url(normalised) is not None:
        return "That search is already being watched."

    name = params.get("search_text") or f"vinted.{tld}"
    query_id = await repo.add_query(
        name=name,
        url=normalised,
        tld=tld,
        params=params,
        poll_interval_s=max(interval_s, MIN_POLL_INTERVAL_S),
    )
    for destination_id in await chat_destination_ids(repo, chat_id):
        await repo.route(query_id, destination_id)
    log.info("telegram.search_added", query_id=query_id, chat_id=chat_id)
    return (
        f"Watching “{html.escape(name)}” on vinted.{tld} (search {query_id}). "
        "New listings will arrive in this chat."
    )


async def _status_text(repo: Repo) -> str:
    snapshot = await health.snapshot(repo)
    if not snapshot.searches:
        return "No searches set up yet."

    lines = ["<b>vinted-sniper</b>", "Running." if snapshot.alive else "Not responding."]
    for search in snapshot.searches:
        last = (
            f"{int(time.time() - search.last_success_at)}s ago"
            if search.last_success_at
            else "never"
        )
        line = f"• {html.escape(search.name)} — {search.state}, last checked {last}"
        if search.state == "failing" and search.last_error:
            line += f"\n  {html.escape(search.last_error[:120])}"
        lines.append(line)

    if snapshot.queued_notifications:
        lines.append(f"{snapshot.queued_notifications} notification(s) waiting to send.")
    return "\n".join(lines)


def _is_start(event: TelegramObject) -> bool:
    return isinstance(event, Message) and (event.text or "").startswith("/start")


def _chat_id(event: TelegramObject) -> int | None:
    if isinstance(event, Message):
        return event.chat.id
    if isinstance(event, CallbackQuery) and event.message is not None:
        return event.message.chat.id
    return None


async def _only_paired_chats(
    handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
    event: TelegramObject,
    data: dict[str, Any],
) -> Any:
    """Anyone can find a bot and message it. Only a chat that was paired through a link
    vinted-sniper printed gets answers; everyone else hears nothing, apart from /start,
    which is how pairing happens."""
    chat_id = _chat_id(event)
    repo: Repo = data["repo"]
    if _is_start(event) or (chat_id is not None and await chat_destination_ids(repo, chat_id)):
        return await handler(event, data)
    return None


async def _handle_start(message: Message, command: CommandObject, repo: Repo) -> None:
    code = (command.args or "").strip()
    if not code:
        # Typing /start by hand is the common way to arrive here: the code travels in
        # the link, so a typed command carries nothing to match against.
        waiting = await _pending_pairing_exists(repo)
        extra = (
            "\n\nThere is a connection waiting. Tap the link vinted-sniper printed, "
            "or send:\n/start <the code from that link>"
            if waiting
            else "\n\nTo connect it, run `vinted-sniper pair-telegram` and tap the link "
            "it prints, in the chat you want alerts in."
        )
        await message.answer(f"Hello. This bot delivers Vinted alerts.{extra}")
        return

    thread_id = message.message_thread_id
    destination_id = await claim_pairing(repo, code, message.chat.id, thread_id)
    if destination_id is None:
        await message.answer(
            "That link has expired or was already used. Generate a new one in "
            "vinted-sniper and try again."
        )
        return

    log.info("telegram.paired", destination_id=destination_id, chat_id=message.chat.id)
    await message.answer(
        "Connected. Matching listings will arrive here.\n"
        "Send /help to see what else this chat can do."
    )


async def _handle_help(message: Message) -> None:
    await message.answer(HELP_TEXT, parse_mode=None)


async def _handle_status(message: Message, repo: Repo) -> None:
    await message.answer(await _status_text(repo), parse_mode="HTML")


async def _handle_list(message: Message, repo: Repo) -> None:
    await message.answer(await list_text(repo), parse_mode="HTML")


async def _handle_pause(message: Message, command: CommandObject, repo: Repo) -> None:
    await message.answer(await set_paused_text(repo, command.args, paused=True), parse_mode="HTML")


async def _handle_resume(message: Message, command: CommandObject, repo: Repo) -> None:
    await message.answer(await set_paused_text(repo, command.args, paused=False), parse_mode="HTML")


async def _handle_remove(message: Message, command: CommandObject, repo: Repo) -> None:
    text, keyboard = await remove_prompt(repo, command.args)
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


async def _handle_remove_choice(callback: CallbackQuery, repo: Repo) -> None:
    reply = await confirm_remove_text(repo, callback.data or "")
    await callback.answer()
    if isinstance(callback.message, Message):
        # Replacing the question stops the button being pressed twice.
        await callback.message.edit_text(reply, parse_mode="HTML")


async def _handle_add(
    message: Message, command: CommandObject, repo: Repo, default_interval_s: int
) -> None:
    reply = await add_search_text(
        repo, command.args, chat_id=message.chat.id, interval_s=default_interval_s
    )
    await message.answer(reply, parse_mode="HTML", link_preview_options=_NO_PREVIEW)


async def _handle_anything_else(message: Message) -> None:
    await message.answer(f"I did not catch that. This is what I understand:\n{HELP_TEXT}")


def build_dispatcher(repo: Repo, *, default_interval_s: int = 60) -> Dispatcher:
    # Keyword arguments become workflow data, which aiogram hands to any handler that
    # names them as parameters.
    dispatcher = Dispatcher(repo=repo, default_interval_s=default_interval_s)
    dispatcher.message.outer_middleware.register(_only_paired_chats)
    dispatcher.callback_query.outer_middleware.register(_only_paired_chats)

    message = dispatcher.message
    message.register(_handle_start, Command("start"))
    message.register(_handle_help, Command("help"))
    message.register(_handle_status, Command("status"))
    message.register(_handle_list, Command("list"))
    message.register(_handle_pause, Command("pause"))
    message.register(_handle_resume, Command("resume"))
    message.register(_handle_remove, Command("remove"))
    message.register(_handle_add, Command("add"))
    message.register(_handle_anything_else, F.text)
    dispatcher.callback_query.register(_handle_remove_choice, F.data.startswith(_REMOVE_PREFIX))
    return dispatcher


async def run_bot(
    token: str, *, repo: Repo, stop: asyncio.Event, default_interval_s: int = 60
) -> None:
    """Poll Telegram for commands until the app shuts down.

    `default_interval_s` is how often a search added with /add is checked; pass the
    configured VINTED_SNIPER_POLL_DEFAULT_INTERVAL_S.
    """
    bot = Bot(token=token)
    dispatcher = build_dispatcher(repo, default_interval_s=default_interval_s)

    polling = asyncio.create_task(dispatcher.start_polling(bot, handle_signals=False))
    try:
        await stop.wait()
    finally:
        await dispatcher.stop_polling()
        polling.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await polling
        await bot.session.close()
