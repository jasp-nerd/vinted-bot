"""Discord delivery, through webhooks.

A webhook is the whole integration: paste a URL, get notifications. No bot to invite, no
gateway connection to keep alive, and when someone deletes the webhook we get a clean 404
instead of a bot that silently stops working.

Listings go out as Components V2 cards, laid out for a phone: an accent bar in the
search's colour (green for a deal), then one line with the total price, the deal badge,
the margin and the title, then the photo, then the buttons, then the small print. The first
line is also what the phone's notification shows, so it is the whole buy-or-skip decision;
the buttons sit right under the photo so nothing needs scrolling. Plain webhooks may carry
non-interactive components, and link buttons are non-interactive, so this needs nothing
beyond the URL. Cards pack several to a message up to Discord's 40-component limit; bigger
bursts become a digest of thumbnail rows, which reads far better than a wall of cards.

If Discord ever answers a card with a 400 about components, the same listings are resent as
classic embeds and this destination stays on embeds until the app restarts. That costs one
rejected request, and 400s do not count against the invalid-request allowance (only 401,
403 and 429 do), so it is safe to learn this way rather than guess.

Two details are doing real work. Every mention is opt-in: `allowed_mentions` is always sent
empty unless the destination names a role or user to ping, so a listing titled "@everyone"
pings nobody. The ping goes in front of the first line, and by default only for steals
(`ping_tiers`): a role pinged for every listing is a role everyone mutes within a day. And
rejected requests count against an allowance that, once spent, gets the
whole address blocked — so a webhook that answers 404 is switched off rather than retried.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from http import HTTPStatus
from typing import Any, Literal

import httpx

from vinted_bot.db.repo import PendingNotification
from vinted_bot.deals import Tier
from vinted_bot.deliver.base import SenderConfigError, SendResult, parse_tiers, require
from vinted_bot.deliver.ratelimit import TokenBucket
from vinted_bot.deliver.render import BOT_NAME, ICON_URL, STATUS_COLOUR, ListingView, view
from vinted_bot.log import get_logger

log = get_logger(__name__)

# Discord's limits for one message.
MAX_COMPONENTS = 40
MAX_TEXT_CHARS = 4000
MAX_EMBEDS = 10
MAX_EMBED_CHARS = 6000

# Up to this many listings go out as full cards; past it they become a digest.
CARD_BATCH = 3
# Nine thumbnail rows with separators is 37 components; ten would be 41.
DIGEST_BATCH = 9

# Photos in a card's gallery, when a listing has more than one. Four make a balanced
# mosaic; Vinted's portrait photos make anything longer taller than a phone screen. The
# search results carry a single photo now, so most cards show just that one.
GALLERY_PHOTOS = 4

# Which tiers a configured mention pings for when the destination does not say.
DEFAULT_PING_TIERS: tuple[Tier, ...] = ("steal",)

# The documented per-webhook limit is around five requests every two seconds, but webhooks
# in the same server have been observed sharing one allowance. One request every half
# second stays clear of both.
REQUESTS_PER_S = 2.0

# Message flags.
SUPPRESS_NOTIFICATIONS = 1 << 12
IS_COMPONENTS_V2 = 1 << 15

# Component types.
ACTION_ROW, BUTTON, SECTION, TEXT, THUMBNAIL, GALLERY, SEPARATOR, CONTAINER = (
    1,
    2,
    9,
    10,
    11,
    12,
    14,
    17,
)
LINK_STYLE = 5

Style = Literal["card", "compact", "classic"]
_STYLES: dict[str, Style] = {"card": "card", "compact": "compact", "classic": "classic"}

_ROLE = re.compile(r"^<@&(\d+)>$")
_USER = re.compile(r"^<@!?(\d+)>$")

# Characters Discord markdown would act on inside a title or a login.
_MARKDOWN = re.compile(r"([\\*_~|`>#\-\[\]()<:])")


@dataclass(frozen=True, slots=True)
class DiscordOptions:
    """What a destination's settings ask of the messages."""

    style: Style = "card"
    mention: str | None = None
    allowed_mentions: dict[str, list[str]] | None = None
    ping_tiers: frozenset[Tier] = frozenset(DEFAULT_PING_TIERS)
    silent: bool = False
    username: str = BOT_NAME
    avatar_url: str = ICON_URL
    photos: int = GALLERY_PHOTOS

    def pings_for(self, listings: list[ListingView]) -> bool:
        """Whether a message carrying these listings should ping the configured mention."""
        return (
            self.mention is not None
            and not self.silent
            and any(listing.tier in self.ping_tiers and not listing.silent for listing in listings)
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> DiscordOptions:
        raw_style = config.get("style") or "card"
        style = _STYLES.get(raw_style)
        if style is None:
            raise SenderConfigError(
                f"Discord style must be card, compact or classic, not {raw_style!r}"
            )
        mention, allowed = _parse_mention(config.get("mention"))
        return cls(
            style=style,
            mention=mention,
            allowed_mentions=allowed,
            ping_tiers=parse_tiers(config, "ping_tiers", DEFAULT_PING_TIERS),
            silent=bool(config.get("silent")),
            username=str(config.get("username") or BOT_NAME)[:80],
            avatar_url=str(config.get("avatar_url") or ICON_URL),
        )


@dataclass(frozen=True, slots=True)
class Message:
    """One request's body and the notifications it carries."""

    payload: dict[str, Any]
    outbox_ids: list[int]


def _parse_mention(raw: Any) -> tuple[str | None, dict[str, list[str]] | None]:
    """Turn the configured ping into its text and the allowance that lets it through.

    Only the exact role or user named may ping. Anything else in the message, a title
    included, stays inert.
    """
    if not raw:
        return None, None
    text = str(raw).strip()
    if role := _ROLE.match(text):
        return text, {"parse": [], "roles": [role.group(1)]}
    if user := _USER.match(text):
        return text, {"parse": [], "users": [user.group(1)]}
    if text in {"@everyone", "@here"}:
        return text, {"parse": ["everyone"]}
    raise SenderConfigError(
        "Discord mention must look like <@&role id>, <@user id>, @everyone or @here"
    )


def escape(text: str) -> str:
    """Make user text render literally: no markdown, no mentions, no timestamps."""
    escaped = _MARKDOWN.sub(r"\\\1", text)
    # A zero-width space after @ keeps "@everyone" readable and unpingable even where
    # allowed_mentions would not apply.
    return escaped.replace("@", "@\u200b")


# Inside a masked link's text Discord shows backslash escapes literally, and a mention
# stops the link rendering at all (both checked against the live client). So link text
# swaps formatting characters for lookalikes instead of escaping them.
_LINK_TEXT = str.maketrans(
    {
        "[": "(",
        "]": ")",
        "*": "\u2217",
        "_": "\uff3f",
        "~": "\u223c",
        "`": "\u02cb",
        "|": "\u01c0",
        "@": "\uff20",
        "<": "\u2039",
        ">": "\u203a",
    }
)


def link_text(text: str) -> str:
    """Make user text safe as the visible part of a markdown link."""
    return text.translate(_LINK_TEXT)


def _link(url: str) -> str:
    """A URL safe inside a markdown link's parentheses."""
    return url.replace("(", "%28").replace(")", "%29").replace(" ", "%20")


# --- Components V2 ------------------------------------------------------------------


def _text(content: str) -> dict[str, Any]:
    return {"type": TEXT, "content": content}


def _separator(*, divider: bool = True) -> dict[str, Any]:
    return {"type": SEPARATOR, "divider": divider, "spacing": 1}


def _button(label: str, url: str) -> dict[str, Any]:
    return {"type": BUTTON, "style": LINK_STYLE, "label": label[:80], "url": url}


def _buttons(listing: ListingView) -> dict[str, Any]:
    """Buy, message, open, and the dashboard, or eBay's sold prices when the dashboard
    cannot be opened from a phone."""
    labels = listing.labels
    buttons = []
    if listing.can_buy:
        buttons.append(_button(labels.buy, listing.buy_url))
        buttons.append(_button(labels.message, listing.message_url))
    buttons.append(_button(labels.open, listing.url))
    if listing.dashboard_url:
        buttons.append(_button(labels.dashboard, listing.search_url or listing.dashboard_url))
    else:
        buttons.append(_button(labels.price_check, listing.price_check_url))
    return {"type": ACTION_ROW, "components": buttons}


def first_line(listing: ListingView, *, link_title: bool = False) -> str:
    """Total, badge, margin, title: the line a phone shows on the lock screen.

    The title goes through `link_text` rather than `escape`: backslashes would show in
    the notification, which renders the text without Discord's markdown.
    """
    price = ""
    if listing.price:
        price = f"**{listing.price}**"
        if listing.previous_price:
            price += f" ~~{listing.previous_price}~~"
    title = link_text(listing.title)
    if link_title:
        title = f"[{title}]({_link(listing.url)})"
    parts = [price, *listing.summary, title]
    line = " · ".join(part for part in parts if part)
    if listing.kind != "listing":
        line = f"{link_text(listing.headline)}: {line}"
    return line


def _when(listing: ListingView) -> str:
    return f"{listing.time_label} <t:{listing.listed_at}:R>"


def _seller_line(listing: ListingView) -> str | None:
    parts = []
    if listing.seller_login:
        login = escape(listing.seller_login)
        if listing.seller_url:
            login = f"[{login}]({_link(listing.seller_url)})"
        parts.append(f"{listing.labels.seller} {login}")
    if listing.rating:
        parts.append(listing.rating)
    if listing.favourites:
        parts.append(f"♥ {listing.favourites}")
    return " · ".join(parts) or None


def _small_print(listing: ListingView) -> str:
    """Everything under the buttons, as subtext: the price basis, the facts, where from."""
    search = escape(listing.search_name)
    if listing.search_url:
        search = f"[{search}]({_link(listing.search_url)})"
    site = f"{listing.flag} {listing.site}".strip()
    lines = [
        listing.price_note,
        " · ".join(
            part
            for part in (
                " · ".join(escape(value) for _, value in listing.facts) or None,
                _seller_line(listing),
            )
            if part
        ),
        f"{site} · {_when(listing)} · {search}",
    ]
    return "\n".join(f"-# {line}" for line in lines if line)


def card(listing: ListingView, *, photos: int = GALLERY_PHOTOS) -> dict[str, Any]:
    """The full listing card: one container, built from top to bottom."""
    children: list[dict[str, Any]] = [_text(first_line(listing))]
    if listing.photos:
        shown = listing.photos[:photos] if len(listing.photos) > 1 else listing.photos[:1]
        children.append(
            {
                "type": GALLERY,
                "items": [
                    {"media": {"url": url}, "description": listing.title[:1024]} for url in shown
                ],
            }
        )
    children.append(_buttons(listing))
    children.append(_text(_small_print(listing)))
    return {"type": CONTAINER, "accent_color": listing.accent, "components": children}


def _row_text(listing: ListingView, *, link_title: bool) -> str:
    """One listing as three lines: the decision, the facts, then when and the links."""
    second = [
        *(escape(value) for _, value in listing.facts),
        listing.rating,
        f"♥ {listing.favourites}" if listing.favourites else None,
    ]
    third = [
        f"{listing.flag} {listing.site}".strip(),
        _when(listing),
        escape(listing.search_name),
    ]
    if link_title and listing.can_buy:
        third.append(f"[{listing.labels.buy}]({_link(listing.buy_url)})")
        third.append(f"[{listing.labels.message}]({_link(listing.message_url)})")
    lines = [
        first_line(listing, link_title=link_title),
        " · ".join(part for part in second if part),
        f"-# {' · '.join(part for part in third if part)}",
    ]
    return "\n".join(line for line in lines if line)


def _row(listing: ListingView, *, link_title: bool = True) -> dict[str, Any]:
    text = _text(_row_text(listing, link_title=link_title))
    if not listing.photos:
        return text
    return {
        "type": SECTION,
        "components": [text],
        "accessory": {
            "type": THUMBNAIL,
            "media": {"url": listing.photos[0]},
            "description": listing.title[:1024],
        },
    }


def compact(listing: ListingView) -> dict[str, Any]:
    """One listing as a thumbnail row with its buttons: a third of a phone screen."""
    return {
        "type": CONTAINER,
        "accent_color": listing.accent,
        "components": [_row(listing, link_title=False), _buttons(listing)],
    }


def digest(listings: list[ListingView]) -> dict[str, Any]:
    """Several listings as thumbnail rows in one container."""
    first = listings[0]
    searches = {listing.search_name for listing in listings}
    heading = f"**{first.labels.new_matches.format(n=len(listings))}**"
    if len(searches) == 1:
        heading += f" · {escape(first.search_name)}"
    children: list[dict[str, Any]] = [_text(heading)]
    for index, listing in enumerate(listings):
        if index:
            children.append(_separator())
        children.append(_row(listing))
    accent = next((listing.accent for listing in listings if listing.deal), first.accent)
    return {"type": CONTAINER, "accent_color": accent, "components": children}


def count_components(components: list[dict[str, Any]]) -> int:
    """Every component, nested ones and section accessories included, as Discord counts."""
    total = 0
    for component in components:
        total += 1
        total += count_components(component.get("components", []))
        if "accessory" in component:
            total += 1
    return total


def text_chars(components: list[dict[str, Any]]) -> int:
    """Characters across every text display, which Discord caps per message."""
    total = 0
    for component in components:
        if component.get("type") == TEXT:
            total += len(component["content"])
        total += text_chars(component.get("components", []))
    return total


def _envelope(options: DiscordOptions, *, ping: bool) -> dict[str, Any]:
    return {
        "username": options.username,
        "avatar_url": options.avatar_url,
        "allowed_mentions": (options.allowed_mentions if ping else None) or {"parse": []},
    }


def _prefix_first_text(component: dict[str, Any], prefix: str) -> tuple[dict[str, Any], bool]:
    """A copy of `component` with `prefix` put in front of its first text display."""
    if component.get("type") == TEXT:
        return {**component, "content": f"{prefix} {component['content']}"}, True
    children = component.get("components", [])
    for index, child in enumerate(children):
        changed, done = _prefix_first_text(child, prefix)
        if done:
            return {
                **component,
                "components": [*children[:index], changed, *children[index + 1 :]],
            }, True
    return component, False


def _v2_message(
    containers: list[dict[str, Any]], listings: list[ListingView], options: DiscordOptions
) -> Message:
    silent = options.silent or all(listing.silent for listing in listings)
    ping = options.pings_for(listings)
    components = list(containers)
    if ping and options.mention:
        # In front of the first line, so the notification reads "@steals €16.45 · ..."
        # rather than a bare role name.
        components[0], _ = _prefix_first_text(components[0], options.mention)
    flags = IS_COMPONENTS_V2 | (SUPPRESS_NOTIFICATIONS if silent else 0)
    payload = _envelope(options, ping=ping) | {"flags": flags, "components": components}
    return Message(payload, [listing.outbox_id for listing in listings])


def _fits(containers: list[dict[str, Any]], options: DiscordOptions) -> bool:
    return (
        count_components(containers) <= MAX_COMPONENTS
        and text_chars(containers) + len(options.mention or "") + 1 <= MAX_TEXT_CHARS
    )


def v2_messages(listings: list[ListingView], options: DiscordOptions) -> list[Message]:
    """Lay a batch out as Components V2 messages, as few as the limits allow."""
    if not listings:
        return []
    if options.style == "compact" and len(listings) > 1:
        return _digests(listings, options)
    if len(listings) > CARD_BATCH:
        return _digests(listings, options)

    build: Callable[[ListingView], dict[str, Any]] = (
        compact if options.style == "compact" else partial(card, photos=options.photos)
    )
    messages: list[Message] = []
    pending: list[ListingView] = []
    containers: list[dict[str, Any]] = []
    for listing in listings:
        built = build(listing)
        if containers and not _fits([*containers, built], options):
            messages.append(_v2_message(containers, pending, options))
            pending, containers = [], []
        pending.append(listing)
        containers.append(built)
    messages.append(_v2_message(containers, pending, options))
    return messages


def _digests(listings: list[ListingView], options: DiscordOptions) -> list[Message]:
    return [
        _v2_message([digest(chunk)], chunk, options)
        for chunk in (
            listings[start : start + DIGEST_BATCH]
            for start in range(0, len(listings), DIGEST_BATCH)
        )
    ]


def status_v2(message: str, options: DiscordOptions) -> dict[str, Any]:
    """A notice about the app itself: a plain grey card, no ping."""
    container = {
        "type": CONTAINER,
        "accent_color": STATUS_COLOUR,
        "components": [_text(f"-# {BOT_NAME}"), _text(escape(message)[: MAX_TEXT_CHARS - 50])],
    }
    return _envelope(options, ping=False) | {"flags": IS_COMPONENTS_V2, "components": [container]}


# --- Classic embeds -------------------------------------------------------------------


def _embed_fields(listing: ListingView) -> list[dict[str, Any]]:
    labels = listing.labels
    fields = [
        {"name": label, "value": escape(value), "inline": True} for label, value in listing.facts
    ]
    if listing.seller_login:
        seller = escape(listing.seller_login)
        if listing.seller_url:
            seller = f"[{seller}]({_link(listing.seller_url)})"
        if listing.rating:
            seller += f"\n{listing.rating}"
        fields.append({"name": labels.seller, "value": seller[:1024], "inline": True})
    fields.append(
        {"name": "Vinted", "value": f"{listing.flag} {listing.site}".strip(), "inline": True}
    )
    fields.append(
        {
            "name": listing.time_label.capitalize(),
            "value": f"<t:{listing.listed_at}:R>",
            "inline": True,
        }
    )
    return fields


def _embed_card(listing: ListingView, options: DiscordOptions) -> list[dict[str, Any]]:
    """One listing as a rich embed, plus image-only embeds that fold into a photo mosaic.

    The price, badge and margin are in the message text above it (that is what a phone
    notification shows for an embed), so the embed itself carries the rest. The extra
    embeds share the listing's URL on purpose: clients merge same-URL images into the
    first embed. Only the first carries a title, so no listing ever disappears.
    """
    embed: dict[str, Any] = {
        "author": {
            "name": f"{listing.headline} · {listing.search_name}"[:256],
            "icon_url": options.avatar_url,
        },
        "title": listing.title[:256],
        "url": listing.url,
        "color": listing.accent,
        "fields": _embed_fields(listing),
        "footer": {"text": BOT_NAME, "icon_url": options.avatar_url},
        "timestamp": datetime.fromtimestamp(listing.listed_at, tz=UTC).isoformat(),
    }
    if listing.search_url:
        embed["author"]["url"] = listing.search_url
    if listing.price_note:
        embed["description"] = f"-# {listing.price_note}"
    if listing.photos:
        embed["image"] = {"url": listing.photos[0]}
    extras = [
        {"url": listing.url, "image": {"url": photo}}
        for photo in listing.photos[1 : options.photos]
    ]
    return [embed, *extras]


def _embed_row(listing: ListingView) -> dict[str, Any]:
    """One listing as a compact embed for a stacked batch."""
    lines = [" · ".join(escape(value) for _, value in listing.facts)]
    lines.append(
        " · ".join(
            p
            for p in (
                listing.rating,
                f"{listing.flag} {listing.site}".strip(),
                f"{listing.time_label} <t:{listing.listed_at}:R>",
            )
            if p
        )
    )
    if listing.can_buy:
        lines.append(
            f"[{listing.labels.buy}]({_link(listing.buy_url)}) · "
            f"[{listing.labels.message}]({_link(listing.message_url)})"
        )
    if listing.summary:
        lines.append(f"**{' · '.join(listing.summary)}**")
    title = f"{listing.price} · {listing.title}" if listing.price else listing.title
    embed: dict[str, Any] = {
        "title": title[:256],
        # Distinct per listing on purpose: Discord folds together embeds that share a URL.
        "url": listing.url,
        "color": listing.accent,
        "description": "\n".join(line for line in lines if line)[:4096],
    }
    if listing.photos:
        embed["thumbnail"] = {"url": listing.photos[0]}
    return embed


def _classic_payload(
    listings: list[ListingView], options: DiscordOptions, content: str
) -> dict[str, Any]:
    silent = options.silent or all(listing.silent for listing in listings)
    ping = options.pings_for(listings)
    if ping and options.mention:
        content = f"{options.mention} {content}"
    payload = _envelope(options, ping=ping) | {"content": content[:2000]}
    if silent:
        payload["flags"] = SUPPRESS_NOTIFICATIONS
    return payload


def classic_messages(listings: list[ListingView], options: DiscordOptions) -> list[Message]:
    """Lay a batch out as embeds: one card per message, or a stack for bigger bursts.

    Buttons belong to a message rather than an embed, so cards go one per message to keep
    each listing's buttons next to it.
    """
    if not listings:
        return []
    if len(listings) <= CARD_BATCH:
        return [
            Message(
                _classic_payload([listing], options, first_line(listing))
                | {"embeds": _embed_card(listing, options), "components": [_buttons(listing)]},
                [listing.outbox_id],
            )
            for listing in listings
        ]

    messages = []
    for start in range(0, len(listings), MAX_EMBEDS):
        chunk = listings[start : start + MAX_EMBEDS]
        heading = chunk[0].labels.new_matches.format(n=len(chunk))
        if len({listing.search_name for listing in chunk}) == 1:
            heading += f" · {escape(chunk[0].search_name)}"
        payload = _classic_payload(chunk, options, f"**{heading}**") | {
            "embeds": [_embed_row(listing) for listing in chunk],
        }
        messages.append(Message(payload, [listing.outbox_id for listing in chunk]))
    return messages


def status_classic(message: str, options: DiscordOptions) -> dict[str, Any]:
    return _envelope(options, ping=False) | {"content": escape(message)[:2000]}


# --- Sending --------------------------------------------------------------------------


class DiscordSender:
    """Posts listings to one Discord webhook."""

    kind = "discord"

    def __init__(
        self,
        config: dict[str, Any],
        *,
        dashboard_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        bucket: TokenBucket | None = None,
    ) -> None:
        # Destinations made before 2.0 store the address as webhook_url.
        key = "webhook_url" if config.get("webhook_url") else "url"
        self._url = require(config, key, self.kind)
        self._params = {"with_components": "true"}
        if thread_id := config.get("thread_id"):
            self._params["thread_id"] = str(thread_id)
        self._options = DiscordOptions.from_config(config)
        self._v2 = self._options.style != "classic"
        self._dashboard_url = dashboard_url
        self._client = client or httpx.AsyncClient(timeout=20.0)
        self._owns_client = client is None
        self._bucket = bucket or TokenBucket(REQUESTS_PER_S, capacity=3)

    @property
    def max_batch(self) -> int:
        return DIGEST_BATCH

    async def send(self, batch: list[PendingNotification]) -> SendResult:
        if not batch:
            return SendResult.ok([])
        listings = [view(n, dashboard_url=self._dashboard_url) for n in batch]
        if not self._v2:
            result, _ = await self._send_all(classic_messages(listings, self._options))
            return result

        result, rejected = await self._send_all(v2_messages(listings, self._options))
        if not rejected:
            return result

        self._v2 = False
        log.warning("discord.components_rejected", error=result.error, fallback="embeds")
        rest = [listing for listing in listings if listing.outbox_id not in result.delivered]
        retried, _ = await self._send_all(classic_messages(rest, self._options))
        return SendResult(
            delivered=result.delivered + retried.delivered,
            retry=retried.retry,
            retry_after_s=retried.retry_after_s,
            permanent_error=retried.permanent_error,
            error=retried.error,
            pause_all_for_s=retried.pause_all_for_s,
        )

    async def _send_all(self, messages: list[Message]) -> tuple[SendResult, bool]:
        """Post messages in order, stopping at the first problem.

        Stopping keeps the queue in order and sends nothing twice: whatever was not
        attempted goes back for a retry. Returns whether the stop was Discord refusing
        Components V2 specifically.
        """
        delivered: list[int] = []
        for index, message in enumerate(messages):
            result, rejected = await self._post(message.payload, message.outbox_ids)
            if result.delivered:
                delivered.extend(result.delivered)
                continue
            untried = [i for later in messages[index + 1 :] for i in later.outbox_ids]
            if rejected:
                untried = [*message.outbox_ids, *untried]
            return (
                SendResult(
                    delivered=delivered,
                    retry=[] if result.permanent_error else [*result.retry, *untried],
                    retry_after_s=result.retry_after_s,
                    permanent_error=result.permanent_error,
                    error=result.error,
                    pause_all_for_s=result.pause_all_for_s,
                ),
                rejected,
            )
        return SendResult.ok(delivered), False

    async def send_status(self, message: str) -> None:
        if self._v2:
            _, rejected = await self._post(status_v2(message, self._options), [])
            if not rejected:
                return
            self._v2 = False
        await self._post(status_classic(message, self._options), [])

    async def _post(
        self, payload: dict[str, Any], outbox_ids: list[int]
    ) -> tuple[SendResult, bool]:
        await self._bucket.acquire()
        try:
            response = await self._client.post(self._url, params=self._params, json=payload)
        except httpx.HTTPError as exc:
            return SendResult.transient(outbox_ids, f"could not reach Discord: {exc}"), False

        if response.is_success:
            return SendResult.ok(outbox_ids), False

        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            retry_after = _retry_after(response)
            # A global limit means every webhook on this connection has to wait, not just
            # this one.
            is_global = response.headers.get("x-ratelimit-scope") == "global" or _body_flag(
                response, "global"
            )
            log.warning("discord.rate_limited", retry_after_s=retry_after, is_global=is_global)
            return (
                SendResult(
                    delivered=[],
                    retry=outbox_ids,
                    retry_after_s=retry_after,
                    error="rate limited by Discord",
                    pause_all_for_s=retry_after if is_global else None,
                ),
                False,
            )

        if response.status_code in (
            HTTPStatus.UNAUTHORIZED,
            HTTPStatus.FORBIDDEN,
            HTTPStatus.NOT_FOUND,
        ):
            return (
                SendResult.gone(
                    f"Discord answered {response.status_code}; the webhook looks deleted or "
                    "its permissions were removed"
                ),
                False,
            )

        if response.status_code == HTTPStatus.BAD_REQUEST:
            # Our payload is wrong. Retrying an identical payload will fail identically,
            # and each attempt spends the allowance that protects everything else.
            body = response.text[:400]
            log.error("discord.rejected_payload", body=body)
            rejected_v2 = bool(payload.get("flags", 0) & IS_COMPONENTS_V2) and (
                "components" in body or "flags" in body
            )
            return (
                SendResult(
                    delivered=[], retry=[], error=f"Discord rejected the message: {body[:200]}"
                ),
                rejected_v2,
            )

        return SendResult.transient(outbox_ids, f"Discord answered {response.status_code}"), False

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _retry_after(response: httpx.Response) -> float:
    for header in ("retry-after", "x-ratelimit-reset-after"):
        if raw := response.headers.get(header):
            try:
                return float(raw)
            except ValueError:
                continue
    try:
        body = response.json()
    except ValueError:
        return 2.0
    if not isinstance(body, dict):
        return 2.0
    try:
        return float(body["retry_after"])
    except (KeyError, TypeError, ValueError):
        return 2.0


def _body_flag(response: httpx.Response, key: str) -> bool:
    try:
        body = response.json()
    except ValueError:
        return False
    return bool(body.get(key)) if isinstance(body, dict) else False
