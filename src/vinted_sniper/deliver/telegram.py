"""Telegram delivery.

Sent as HTML rather than MarkdownV2 on purpose. MarkdownV2 requires eighteen characters to
be escaped anywhere they appear, and Vinted titles are full of them — a stray `.` or `!`
turns into a hard send failure rather than a formatting wobble. HTML needs three.

Three ways to show one listing, picked per destination with `style`:

- `photo` (default): `sendPhoto` with an HTML caption and coloured buttons. A real photo,
  tap to zoom, one message per listing.
- `gallery`: `sendRichMessage` (Bot API 10.1) with a slideshow of every photo, a facts
  table and the same buttons. The only way to put a gallery and buttons in one Telegram
  message, and new enough that older apps may not show it, hence opt-in. If the server
  refuses it, this destination falls back to `photo` until the app restarts.
- `compact`: a text message with the photo as a link preview. Also what a `photo` alert
  becomes when Telegram cannot fetch the image, since an alert without its photo is still
  worth more than no alert.

Every listing leads with one line: the total, the deal badge, the margin and the title.
That is the line the phone's notification shows, so it is the whole buy-or-skip decision.
Under the links sit three action buttons the paired bot answers (block the seller, mute
the search for an hour, hide the listing), which is what makes Telegram the place to
manage alerts from a phone; see botctl.telegram_bot for the other end.

Bursts fold into one digest message. Groups get that sooner than private chats, because
Telegram allows a group only twenty messages a minute.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from vinted_sniper.db.repo import PendingNotification
from vinted_sniper.deliver.base import SenderConfigError, SendResult, require
from vinted_sniper.deliver.labels import MINUS
from vinted_sniper.deliver.ratelimit import TokenBucket
from vinted_sniper.deliver.render import BOT_NAME, ListingView, view
from vinted_sniper.log import get_logger

log = get_logger(__name__)

API_ROOT = "https://api.telegram.org"

# Telegram asks for no more than one message a second in a single chat, and twenty a
# minute in a group.
PRIVATE_PER_S = 1.0
GROUP_PER_S = 20 / 60

# Past this many listings at once, the rest are folded into one digest. A chat that gets
# twenty separate alerts in a minute is unreadable, and it is also how you get throttled.
DIGEST_AFTER_PRIVATE = 5
DIGEST_AFTER_GROUP = 3

MAX_MESSAGE_CHARS = 4096
MAX_CAPTION_CHARS = 1024
MAX_GALLERY_PHOTOS = 10

Style = Literal["photo", "gallery", "compact"]
_STYLES: dict[str, Style] = {"photo": "photo", "gallery": "gallery", "compact": "compact"}

# Telegram states these plainly, so they are worth acting on rather than retrying.
_PERMANENT_MARKERS = (
    "bot was blocked by the user",
    "chat not found",
    "user is deactivated",
    "bot was kicked",
    "have no rights to send",
)

# What Telegram says when it could not fetch or use the photo URL we gave it.
_PHOTO_MARKERS = (
    "wrong file identifier",
    "failed to get http url content",
    "wrong type of the web page content",
    "photo_invalid_dimensions",
    "image_process_failed",
    "wrong remote file",
)

_TAG = re.compile(r"<[^>]+>")

ApiCall = tuple[str, dict[str, Any]]

# Action buttons carry "a:<verb>:<id>:<site>[:<login>]" as their callback data, which
# Telegram caps at 64 bytes. The site picks the language of the "done" label.
ACTION_PREFIX = "a:"
BLOCK, MUTE, HIDE = "b", "m", "h"
MAX_CALLBACK_BYTES = 64


def action_data(verb: str, target: int, tld: str, login: str | None = None) -> str:
    """The callback data for one action button, with the seller's login if it fits."""
    data = f"{ACTION_PREFIX}{verb}:{target}:{tld}"
    if login and len(f"{data}:{login}".encode()) <= MAX_CALLBACK_BYTES:
        data += f":{login}"
    return data


@dataclass(frozen=True, slots=True)
class TelegramOptions:
    chat_id: str
    thread_id: str | None = None
    style: Style = "photo"
    silent: bool = False

    @property
    def is_group(self) -> bool:
        """Group and channel ids are negative; private chats are positive."""
        return self.chat_id.startswith("-")

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> TelegramOptions:
        chat_id = str(config.get("chat_id") or "").strip()
        if not chat_id:
            require(config, "chat_id", "telegram")
        raw_style = config.get("style") or "photo"
        style = _STYLES.get(raw_style)
        if style is None:
            raise SenderConfigError(
                f"Telegram style must be photo, gallery or compact, not {raw_style!r}"
            )
        # The pairing bot stores message_thread_id; thread_id is the documented name.
        thread_id = config.get("thread_id") or config.get("message_thread_id")
        return cls(
            chat_id=chat_id,
            thread_id=str(thread_id) if thread_id else None,
            style=style,
            silent=bool(config.get("silent")),
        )


def visible_length(markup: str) -> int:
    """Characters Telegram counts once the HTML is parsed: UTF-16 units of the text."""
    text = html.unescape(_TAG.sub("", markup))
    return len(text.encode("utf-16-le")) // 2


def _e(text: str) -> str:
    return html.escape(text, quote=False)


def _attr(text: str) -> str:
    return html.escape(text, quote=True)


def _time(listing: ListingView) -> str:
    """A relative time the reader's app renders ("2 minutes ago"), with a UTC fallback
    for apps too old to know the tag."""
    fallback = datetime.fromtimestamp(listing.listed_at, tz=UTC).strftime("%H:%M UTC")
    return f'<tg-time unix="{listing.listed_at}" format="r">{fallback}</tg-time>'


def first_line(listing: ListingView) -> str:
    """Total, badge, margin and the linked title: what the notification shows."""
    price = ""
    if listing.price:
        price = f"<b>{_e(listing.price)}</b>"
        if listing.previous_price:
            price += f" <s>{_e(listing.previous_price)}</s>"
    parts = [
        price,
        *(f"<i>{_e(part)}</i>" for part in listing.summary),
        f'<a href="{_attr(listing.url)}">{_e(listing.title)}</a>',
    ]
    line = " · ".join(part for part in parts if part)
    if listing.kind != "listing":
        line = f"<b>{_e(listing.headline)}</b>: {line}"
    return line


def _seller_line(listing: ListingView) -> str | None:
    parts = []
    if listing.seller_login:
        login = _e(listing.seller_login)
        if listing.seller_url:
            login = f'<a href="{_attr(listing.seller_url)}">{login}</a>'
        parts.append(login)
    if listing.rating:
        parts.append(_e(listing.rating))
    if listing.favourites:
        parts.append(f"♥ {listing.favourites}")
    return " · ".join(parts) or None


def caption(listing: ListingView, *, limit: int = MAX_CAPTION_CHARS) -> str:
    """The HTML under a listing photo, kept inside Telegram's caption limit."""
    lines = [
        first_line(listing),
        " · ".join(_e(value) for _, value in listing.facts) or None,
        _seller_line(listing),
        f"{listing.flag} {_e(listing.site)} · {_e(listing.time_label)} {_time(listing)}".strip(),
    ]
    detail = (
        f"<blockquote expandable>{_e(listing.price_note)}</blockquote>"
        if listing.price_note
        else None
    )
    footer = f"<i>{_e(listing.search_name)}</i>"

    text = "\n".join(line for line in [*lines, detail, footer] if line)
    if visible_length(text) > limit:
        # The small print goes first; everything else is already length-capped upstream.
        text = "\n".join(line for line in [*lines, footer] if line)
    return text


def keyboard(listing: ListingView, *, actions: bool = True) -> dict[str, Any]:
    """Buy and message, then open and the dashboard, then the price checks, then the
    actions the bot answers. Telegram colours the first of the top two rows (Bot API 9.4
    `style`).

    Without a dashboard a phone can open, eBay's sold prices take its place, and the
    photo search shares its row; with one, both price checks share the third row.
    """
    labels = listing.labels
    rows: list[list[dict[str, Any]]] = []
    if listing.can_buy:
        rows.append(
            [
                {"text": labels.buy, "url": listing.buy_url, "style": "success"},
                {"text": labels.message, "url": listing.message_url},
            ]
        )
    price_check = {"text": labels.price_check, "url": listing.price_check_url}
    second: list[dict[str, Any]] = [{"text": labels.open, "url": listing.url, "style": "primary"}]
    tools: list[dict[str, Any]] = []
    if listing.dashboard_url:
        second.append(
            {"text": labels.dashboard, "url": listing.search_url or listing.dashboard_url}
        )
        tools.append(price_check)
    else:
        second.append(price_check)
    if listing.photo_search_url:
        tools.append({"text": labels.photo_search, "url": listing.photo_search_url})
    rows.append(second)
    if tools:
        rows.append(tools)
    if actions and listing.can_buy:
        rows.append(_actions(listing))
    return {"inline_keyboard": rows}


def _actions(listing: ListingView) -> list[dict[str, Any]]:
    """Block the seller, mute the search for an hour, hide the listing."""
    labels = listing.labels
    tld = listing.site.removeprefix("vinted.")
    row = []
    if listing.seller_id is not None:
        data = action_data(BLOCK, listing.seller_id, tld, listing.seller_login)
        row.append({"text": labels.block_seller, "callback_data": data})
    if listing.query_id is not None:
        row.append({"text": labels.mute, "callback_data": action_data(MUTE, listing.query_id, tld)})
    row.append({"text": labels.hide, "callback_data": action_data(HIDE, listing.item_id, tld)})
    return row


def _base(options: TelegramOptions, *, silent: bool) -> dict[str, Any]:
    params: dict[str, Any] = {"chat_id": options.chat_id}
    if options.thread_id:
        params["message_thread_id"] = options.thread_id
    if silent or options.silent:
        params["disable_notification"] = True
    return params


def photo_call(listing: ListingView, options: TelegramOptions) -> ApiCall:
    return "sendPhoto", _base(options, silent=listing.silent) | {
        "photo": listing.photos[0],
        "caption": caption(listing),
        "parse_mode": "HTML",
        "reply_markup": keyboard(listing),
    }


def compact_call(listing: ListingView, options: TelegramOptions) -> ApiCall:
    """The listing as text with its photo as a big link preview above it."""
    preview: dict[str, Any] = (
        {"url": listing.photos[0], "prefer_large_media": True, "show_above_text": True}
        if listing.photos
        else {"is_disabled": True}
    )
    return "sendMessage", _base(options, silent=listing.silent) | {
        "text": caption(listing, limit=MAX_MESSAGE_CHARS),
        "parse_mode": "HTML",
        "link_preview_options": preview,
        "reply_markup": keyboard(listing),
    }


def gallery_call(listing: ListingView, options: TelegramOptions) -> ApiCall:
    """A rich message: slideshow, linked title, price, a facts table and the buttons."""
    images = "".join(
        f'<img src="{_attr(photo)}"/>' for photo in listing.photos[:MAX_GALLERY_PHOTOS]
    )
    media = f"<tg-slideshow>{images}</tg-slideshow>" if len(listing.photos) > 1 else images

    price = ""
    if listing.price:
        price = f"<b>{_e(listing.price)}</b>"
        if listing.previous_price:
            price += f" <s>{_e(listing.previous_price)}</s>"
        if listing.short_badge:
            price += f" <mark>{_e(listing.short_badge)}</mark>"
        if listing.margin_text:
            price += f" · {_e(listing.margin_text)}"
        if listing.price_note:
            price += f"<br/><i>{_e(listing.price_note)}</i>"
        price = f"<p>{price}</p>"

    rows = [*listing.facts]
    if listing.seller_login:
        rows.append((listing.labels.seller, listing.seller_login))
    table = "".join(
        f"<tr><td>{_e(label)}</td><td><b>{_e(value)}</b></td></tr>" for label, value in rows
    )
    if listing.rating:
        table += f"<tr><td></td><td>{_e(listing.rating)}</td></tr>"

    headline = f"<p><b>{_e(listing.headline)}</b></p>" if listing.kind != "listing" else ""
    body = (
        f"{media}{headline}"
        f'<h3><a href="{_attr(listing.url)}">{_e(listing.title)}</a></h3>'
        f"{price}"
        f"{f'<table>{table}</table>' if table else ''}"
        f"<footer>{_e(listing.search_name)} · {listing.flag} {_e(listing.site)} · "
        f"{_e(listing.time_label)} {_time(listing)}</footer>"
    )
    return "sendRichMessage", _base(options, silent=listing.silent) | {
        # Without this, a "#tag" in a title turns into a hashtag link.
        "rich_message": {"html": body, "skip_entity_detection": True},
        "reply_markup": keyboard(listing),
    }


def digest_call(listings: list[ListingView], options: TelegramOptions) -> ApiCall:
    """Several listings as one message, price first, with the best deal's photo on top."""
    first = listings[0]
    heading = f"<b>{_e(first.labels.new_matches.format(n=len(listings)))}</b>"
    if len({listing.search_name for listing in listings}) == 1:
        heading += f" · {_e(first.search_name)}"
    lines = [heading, ""]
    for listing in listings:
        parts = [f"<b>{_e(listing.price)}</b>" if listing.price else None]
        if listing.deal:
            parts.append(f"<i>{MINUS}{listing.deal.pct}%</i>")
        if listing.margin:
            parts.append(_e(listing.margin))
        parts.append(f'<a href="{_attr(listing.url)}">{_e(listing.title[:80])}</a>')
        parts.extend(_e(value) for label, value in listing.facts if label == listing.labels.size)
        if listing.rating:
            parts.append(_e(listing.rating))
        lines.append(" · ".join(part for part in parts if part))

    best = max(listings, key=lambda listing: listing.deal.pct if listing.deal else -1)
    preview: dict[str, Any] = (
        {"url": best.photos[0], "prefer_large_media": True, "show_above_text": True}
        if best.photos
        else {"is_disabled": True}
    )
    params = _base(options, silent=all(listing.silent for listing in listings)) | {
        "text": "\n".join(lines)[:MAX_MESSAGE_CHARS],
        "parse_mode": "HTML",
        "link_preview_options": preview,
    }
    if first.dashboard_url:
        params["reply_markup"] = {
            "inline_keyboard": [[{"text": first.labels.dashboard, "url": first.dashboard_url}]]
        }
    return "sendMessage", params


def status_call(message: str, options: TelegramOptions) -> ApiCall:
    # Not silenced: a warning that a search is blocked is worth hearing.
    return "sendMessage", _base(options, silent=False) | {
        "text": f"<b>{BOT_NAME}</b>\n{_e(message)}"[:MAX_MESSAGE_CHARS],
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }


def listing_call(listing: ListingView, options: TelegramOptions, *, rich: bool = True) -> ApiCall:
    """The request for one listing in the destination's chosen style."""
    if not listing.photos or options.style == "compact":
        return compact_call(listing, options)
    if options.style == "gallery" and rich:
        return gallery_call(listing, options)
    return photo_call(listing, options)


class TelegramSender:
    """Posts listings to one Telegram chat, group, or forum topic."""

    kind = "telegram"

    def __init__(
        self,
        config: dict[str, Any],
        *,
        bot_token: str,
        dashboard_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        bucket: TokenBucket | None = None,
    ) -> None:
        self._options = TelegramOptions.from_config(config)
        self._token = bot_token
        self._dashboard_url = dashboard_url
        self._rich = True
        self._client = client or httpx.AsyncClient(timeout=20.0)
        self._owns_client = client is None
        rate = GROUP_PER_S if self._options.is_group else PRIVATE_PER_S
        self._bucket = bucket or TokenBucket(rate, capacity=3 if self._options.is_group else 2)

    @property
    def max_batch(self) -> int:
        return 10

    async def send(self, batch: list[PendingNotification]) -> SendResult:
        if not batch:
            return SendResult.ok([])

        listings = [view(n, dashboard_url=self._dashboard_url) for n in batch]
        threshold = DIGEST_AFTER_GROUP if self._options.is_group else DIGEST_AFTER_PRIVATE
        individually, overflow = listings[:threshold], listings[threshold:]
        delivered: list[int] = []

        for index, listing in enumerate(individually):
            result = await self._send_listing(listing)
            if not result.delivered:
                # Whatever was not attempted goes back in the queue; the listing that
                # failed goes back only if the failure was the retryable kind.
                untried = [later.outbox_id for later in listings[index + 1 :]]
                return SendResult(
                    delivered=delivered,
                    retry=[] if result.permanent_error else [*result.retry, *untried],
                    retry_after_s=result.retry_after_s,
                    permanent_error=result.permanent_error,
                    error=result.error,
                )
            delivered.extend(result.delivered)

        if overflow:
            method, params = digest_call(overflow, self._options)
            result = await self._post(method, params, [listing.outbox_id for listing in overflow])
            if not result.delivered:
                return SendResult(
                    delivered=delivered,
                    retry=[] if result.permanent_error else result.retry,
                    retry_after_s=result.retry_after_s,
                    permanent_error=result.permanent_error,
                    error=result.error,
                )
            delivered.extend(result.delivered)

        return SendResult.ok(delivered)

    async def _send_listing(self, listing: ListingView) -> SendResult:
        """Send one listing, stepping down a style when Telegram cannot do the richer one."""
        ids = [listing.outbox_id]
        method, params = listing_call(listing, self._options, rich=self._rich)
        result, description = await self._call(method, params, ids)

        if method == "sendRichMessage" and _rejected(result):
            # Not a retry: the request was refused, so we ask for something different.
            self._rich = False
            log.warning("telegram.rich_message_rejected", description=description)
            method, params = photo_call(listing, self._options)
            result, description = await self._call(method, params, ids)

        if method == "sendPhoto" and _rejected(result) and _is_photo_problem(description):
            log.warning("telegram.photo_unusable", description=description)
            method, params = compact_call(listing, self._options)
            result, _ = await self._call(method, params, ids)
        return result

    async def send_status(self, message: str) -> None:
        method, params = status_call(message, self._options)
        await self._post(method, params, [])

    async def _post(self, method: str, params: dict[str, Any], outbox_ids: list[int]) -> SendResult:
        result, _ = await self._call(method, params, outbox_ids)
        return result

    async def _call(
        self, method: str, params: dict[str, Any], outbox_ids: list[int]
    ) -> tuple[SendResult, str]:
        await self._bucket.acquire()
        try:
            response = await self._client.post(f"{API_ROOT}/bot{self._token}/{method}", json=params)
        except httpx.HTTPError as exc:
            return SendResult.transient(outbox_ids, f"could not reach Telegram: {exc}"), ""

        try:
            body = response.json()
        except ValueError:
            return SendResult.transient(outbox_ids, "Telegram sent a reply we could not read"), ""

        if response.is_success and body.get("ok"):
            return SendResult.ok(outbox_ids), ""

        description = str(body.get("description", response.text))[:300]
        retry_after = (body.get("parameters") or {}).get("retry_after")

        if retry_after is not None:
            log.warning("telegram.rate_limited", retry_after_s=retry_after)
            return (
                SendResult(
                    delivered=[],
                    retry=outbox_ids,
                    retry_after_s=float(retry_after),
                    error="rate limited by Telegram",
                ),
                description,
            )

        return _classify(description, response.status_code, outbox_ids), description

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _rejected(result: SendResult) -> bool:
    """Refused outright: not delivered, not worth retrying, and the destination is fine."""
    return not result.delivered and not result.retry and result.permanent_error is None


def _is_photo_problem(description: str) -> bool:
    lowered = description.lower()
    return any(marker in lowered for marker in _PHOTO_MARKERS)


def _classify(description: str, status_code: int, outbox_ids: list[int]) -> SendResult:
    """Decide what a Telegram error means for the queue."""
    lowered = description.lower()
    if any(marker in lowered for marker in _PERMANENT_MARKERS):
        return SendResult.gone(f"Telegram says: {description}")

    if status_code in (httpx.codes.BAD_REQUEST, httpx.codes.NOT_FOUND):
        # Malformed request, or a method this server does not have; sending it again
        # changes nothing.
        log.error("telegram.rejected_payload", description=description)
        return SendResult(delivered=[], retry=[], error=f"Telegram rejected it: {description}")

    return SendResult.transient(outbox_ids, f"Telegram error: {description}")
