"""The Telegram bot, which exists mostly to solve one annoying problem.

Telegram bots cannot message someone first, so before we can send you anything we need your
chat id — and asking people to find their own numeric chat id is where most setup guides
lose them. Instead the app prints a link, you tap it, the bot receives `/start` with a
one-time code, and it records the chat itself. Works the same for a group or a forum topic.

Once paired, the chat doubles as a remote control: /list, /pause, /resume, /remove (with a
confirmation button) and /add with a pasted search link, plus /status to ask whether
everything is still running without opening the web UI. Pasting any Vinted link does the
obvious thing with it: a search is watched, a listing is followed for price drops and its
sale, a member's profile for new uploads. And every alert carries three buttons this bot
answers: block the seller, mute the search for an hour, hide the listing.

Only chats that were paired get answers, because anyone can find a bot by name and message
it. That includes the alert buttons: a forwarded alert's buttons do nothing elsewhere.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import re
import secrets
import sqlite3
import time
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    TelegramObject,
)

from vinted_bot import managed
from vinted_bot.config import MIN_POLL_INTERVAL_S, Settings
from vinted_bot.db.repo import Repo
from vinted_bot.deliver.labels import labels_for
from vinted_bot.deliver.telegram import ACTION_PREFIX, BLOCK, HIDE, MUTE
from vinted_bot.engine import health
from vinted_bot.engine.validation import InvalidInputError
from vinted_bot.log import get_logger
from vinted_bot.vinted import urls

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
    "/start <code>: connect this chat to vinted-bot\n"
    "\n"
    "Or just paste a Vinted link: a search to watch it, a listing to follow its price and "
    "sale, a member's profile to follow their new uploads."
)

# How long the mute button on an alert silences its search.
MUTE_S = 3600

# Where a pasted Vinted address sits in a message, share text and all.
_VINTED_LINK = re.compile(r"(?i)\b(?:https?://)?(?:[a-z0-9-]+\.)*vinted\.[a-z.]+/\S*")
_ITEM = re.compile(r"^/items/(\d+)(?:-([^/?#]*))?")
_MEMBER = re.compile(r"^/member/(\d+)(?:-([^/?#]*))?")

# What a pressed action button turns into: inert, so a second press only gets a toast.
_DONE = f"{ACTION_PREFIX}done"

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


async def add_link_text(
    repo: Repo, text: str | None, *, chat_id: int, interval_s: int
) -> str | None:
    """Do the obvious thing with a pasted Vinted link. None if the text holds no link.

    A search is watched like /add; a listing is followed for price drops and its sale; a
    member's profile for new uploads. Alerts for any of them go to the chat that asked.
    """
    match = _VINTED_LINK.search(text or "")
    if match is None:
        return None
    link = match.group(0)
    if not re.match(r"(?i)^https?://", link):
        link = f"https://{link}"
    path = urlparse(link).path
    item, member = _ITEM.match(path), _MEMBER.match(path)
    if item is None and member is None:
        return await add_search_text(repo, link, chat_id=chat_id, interval_s=interval_s)
    try:
        tld = urls.extract_tld(link)
    except urls.InvalidSearchURLError as exc:
        return f"That link will not work: {html.escape(str(exc))}"

    kind: Literal["item", "seller"] = "item" if item is not None else "seller"
    found = item or member
    assert found is not None  # one of the two matched, or we returned above
    target_id = int(found.group(1))
    slug = (found.group(2) or "").strip()
    label = slug.replace("-", " ") if kind == "item" else slug
    try:
        watch_id = await repo.add_watch(
            kind=kind,
            tld=tld,
            target_id=target_id,
            label=label or f"{'listing' if kind == 'item' else 'seller'} {target_id}",
            destination_ids=await chat_destination_ids(repo, chat_id),
        )
    except InvalidInputError:
        return "That is already being watched."
    log.info("telegram.watch_added", watch_id=watch_id, kind=kind, chat_id=chat_id)
    if kind == "item":
        return (
            f"Following that listing on vinted.{tld} (watch {watch_id}). You will hear here "
            "if its price drops or it sells."
        )
    who = html.escape(slug) if slug else "that member"
    return f"Following {who} on vinted.{tld} (watch {watch_id}). New uploads will arrive here."


# --- Alert buttons ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActionResult:
    """What pressing an alert's button did: a toast, and what the button now says."""

    toast: str
    # None leaves the buttons as they are, for a press that changed nothing.
    done_label: str | None = None


_OUTDATED = ActionResult("That button is from an older version and no longer works.")


async def _block(repo: Repo, seller_id: int, tld: str, login: str | None) -> ActionResult:
    await repo.block_seller(seller_id, login=login, tld=tld, reason="blocked from a Telegram alert")
    log.info("telegram.seller_blocked", seller_id=seller_id)
    return ActionResult(
        f"{login or 'That seller'} is blocked in every search.", labels_for(tld).blocked
    )


async def _mute(repo: Repo, query_id: int, tld: str, _: str | None) -> ActionResult:
    query = await repo.get_query(query_id)
    if query is None:
        return ActionResult("That search no longer exists.")
    await repo.mute_query(query_id, int(time.time()) + MUTE_S)
    log.info("telegram.search_muted", query_id=query_id)
    return ActionResult(f"“{query.name}” is muted for an hour.", labels_for(tld).muted)


async def _hide(repo: Repo, item_id: int, tld: str, _: str | None) -> ActionResult:
    if not await repo.known_item_ids([item_id]):
        return ActionResult("That listing is no longer stored.")
    await repo.set_mark(item_id, "hidden")
    return ActionResult("Hidden from the dashboard.", labels_for(tld).hidden)


_ACTIONS: dict[str, Callable[[Repo, int, str, str | None], Awaitable[ActionResult]]] = {
    BLOCK: _block,
    MUTE: _mute,
    HIDE: _hide,
}


async def apply_action(repo: Repo, data: str) -> ActionResult:
    """Carry out an alert button: "a:<verb>:<id>:<site>[:<login>]"."""
    if data == _DONE:
        return ActionResult("Already done.")
    verb, _, rest = data.removeprefix(ACTION_PREFIX).partition(":")
    target, _, rest = rest.partition(":")
    tld, _, login = rest.partition(":")
    action = _ACTIONS.get(verb)
    if action is None or not target.isdigit() or not tld:
        return _OUTDATED
    return await action(repo, int(target), tld, login or None)


def done_markup(markup: InlineKeyboardMarkup, pressed: str, label: str) -> InlineKeyboardMarkup:
    """The same buttons, with the pressed one saying what it did and doing nothing more."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=label, callback_data=_DONE)
                if button.callback_data == pressed
                else button
                for button in row
            ]
            for row in markup.inline_keyboard
        ]
    )


async def _status_text(repo: Repo) -> str:
    snapshot = await health.snapshot(repo)
    if not snapshot.searches:
        return "No searches set up yet."

    lines = ["<b>vinted-bot</b>", "Running." if snapshot.alive else "Not responding."]
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
    vinted-bot printed gets answers; everyone else hears nothing, apart from /start,
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
            "\n\nThere is a connection waiting. Tap the link vinted-bot printed, "
            "or send:\n/start <the code from that link>"
            if waiting
            else "\n\nTo connect it, run `vinted-bot pair-telegram` and tap the link "
            "it prints, in the chat you want alerts in."
        )
        await message.answer(f"Hello. This bot delivers Vinted alerts.{extra}")
        return

    thread_id = message.message_thread_id
    destination_id = await claim_pairing(repo, code, message.chat.id, thread_id)
    if destination_id is None:
        await message.answer(
            "That link has expired or was already used. Generate a new one in "
            "vinted-bot and try again."
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
    reply = await add_link_text(
        repo, command.args, chat_id=message.chat.id, interval_s=default_interval_s
    )
    if reply is None:
        reply = await add_search_text(
            repo, command.args, chat_id=message.chat.id, interval_s=default_interval_s
        )
    await message.answer(reply, parse_mode="HTML", link_preview_options=_NO_PREVIEW)


async def _handle_link(message: Message, repo: Repo, default_interval_s: int) -> None:
    reply = await add_link_text(
        repo, message.text, chat_id=message.chat.id, interval_s=default_interval_s
    )
    if reply is None:  # pragma: no cover - the filter only routes messages with a link
        await _handle_anything_else(message)
        return
    await message.answer(reply, parse_mode="HTML", link_preview_options=_NO_PREVIEW)


async def _handle_action(callback: CallbackQuery, repo: Repo) -> None:
    data = callback.data or ""
    result = await apply_action(repo, data)
    await callback.answer(result.toast)
    message = callback.message
    if result.done_label is None or not isinstance(message, Message):
        return
    if message.reply_markup is None:
        return
    # The action is done whatever happens here; a button that cannot be redrawn (the
    # message was deleted, or pressed twice in a row) only costs the visual cue.
    with contextlib.suppress(TelegramBadRequest):
        await message.edit_reply_markup(
            reply_markup=done_markup(message.reply_markup, data, result.done_label)
        )


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
    message.register(_handle_link, F.text.regexp(_VINTED_LINK, mode="search"))
    message.register(_handle_anything_else, F.text)
    dispatcher.callback_query.register(_handle_remove_choice, F.data.startswith(_REMOVE_PREFIX))
    dispatcher.callback_query.register(_handle_action, F.data.startswith(ACTION_PREFIX))
    return dispatcher


async def run_bot(
    token: str, *, repo: Repo, stop: asyncio.Event, default_interval_s: int = 60
) -> None:
    """Poll Telegram for commands until `stop` is set, or polling itself gives up.

    `default_interval_s` is how often a search added with /add is checked; pass the
    configured VINTED_BOT_POLL_DEFAULT_INTERVAL_S. Polling gives up at once on a token
    Telegram refuses, and that error is raised here rather than at shutdown.
    """
    bot = Bot(token=token)
    dispatcher = build_dispatcher(repo, default_interval_s=default_interval_s)

    polling = asyncio.create_task(dispatcher.start_polling(bot, handle_signals=False))
    stopping = asyncio.create_task(stop.wait())
    try:
        await asyncio.wait({polling, stopping}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stopping.cancel()
        if not polling.done():
            await dispatcher.stop_polling()
        polling.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await polling
        await bot.session.close()


# Runs the bot on one token until the event is set: run_bot with the rest filled in.
BotRunner = Callable[[str, asyncio.Event], Coroutine[Any, Any, None]]

# How often to look at the token without being told it changed: only matters when the
# database was locked at the moment the dashboard announced a change.
RECHECK_TOKEN_S = 30.0


async def keep_running(
    settings: Settings,
    repo: Repo,
    *,
    stop: asyncio.Event,
    token_changed: asyncio.Event,
    run: BotRunner | None = None,
) -> None:
    """Run the bot on whichever token is set, following it as it changes.

    The token can be added, replaced or removed from the dashboard at any moment. The
    dashboard sets `token_changed`; this then stops the bot on the old token and starts
    it on the new one, so pairing works straight after the token is pasted. With no
    token there is no bot. A bot that stopped by itself (a token Telegram has since
    revoked) is not restarted on the same token: only a different one would help.
    """

    async def run_logged(token: str, bot_stop: asyncio.Event) -> None:
        try:
            await run_bot(
                token,
                repo=repo,
                stop=bot_stop,
                default_interval_s=settings.poll_default_interval_s,
            )
        except Exception as exc:
            # The message never holds the token: aiogram puts the method name in it.
            log.exception("telegram_bot.failed", error=str(exc))

    start = run or run_logged
    current: str | None = None
    bot: asyncio.Task[None] | None = None
    bot_stop = asyncio.Event()
    try:
        while not stop.is_set():
            token_changed.clear()
            try:
                token = await managed.telegram_token(settings, repo)
            except sqlite3.OperationalError as exc:
                log.warning("telegram_bot.token_unreadable", error=str(exc))
                token = current
            if token != current:
                if bot is not None:
                    bot_stop.set()
                    await bot
                    bot = None
                    log.info("telegram_bot.stopped")
                if token is not None:
                    bot_stop = asyncio.Event()
                    bot = asyncio.create_task(start(token, bot_stop), name="telegram-bot")
                    log.info("telegram_bot.started")
                current = token
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(RECHECK_TOKEN_S):
                    await _either(stop, token_changed)
    finally:
        if bot is not None:
            bot_stop.set()
            await bot


async def _either(first: asyncio.Event, second: asyncio.Event) -> None:
    """Return when either event is set."""
    waits = [asyncio.create_task(first.wait()), asyncio.create_task(second.wait())]
    try:
        await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for wait in waits:
            wait.cancel()
        await asyncio.gather(*waits, return_exceptions=True)
