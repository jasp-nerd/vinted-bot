"""Everything else, through Apprise.

Apprise speaks to over a hundred services, each configured by one URL: email (`mailtos://`),
Slack, Pushover, Gotify, Matrix, Signal, Home Assistant and so on. Building each of those
natively would be a lot of code for channels a few people use, and Apprise already knows
how each one wants its formatting: we hand it markdown and it converts to HTML or plain
text per service. The native Discord, Telegram and ntfy senders stay, because they can do
far more than a title and a body.

Email is the reason it is a core dependency rather than an extra: it is the one channel
everybody already has, and "install an extra first" is where a dashboard setup stops.
"""

from __future__ import annotations

import re
from typing import Any

import apprise

from vinted_bot.db.repo import PendingNotification
from vinted_bot.deliver.base import SenderConfigError, SendResult
from vinted_bot.deliver.render import BOT_NAME, ListingView, escape_markdown, view

# Apprise calls services one after another, so this caps each service, not the whole send.
TIMEOUT_S = 20.0

# For quiet hours' silent mode: the option that makes a service deliver without a sound,
# for the services that have one. Apprise reads these from each address rather than per
# message, so a silent alert goes out through a copy of the addresses with it added.
# Email and the rest have no such option, and arrive as usual.
_QUIET_OPTION = {
    "tgram": ("silent", "yes"),
    "pover": ("priority", "low"),
    "ntfy": ("priority", "low"),
    "ntfys": ("priority", "low"),
    "gotify": ("priority", "low"),
    "gotifys": ("priority", "low"),
}


def message(listing: ListingView) -> tuple[str, str]:
    """A title and a markdown body for one listing."""
    labels = listing.labels
    title = listing.first_line_text

    seller = escape_markdown(listing.seller_login) if listing.seller_login else None
    lines = [
        f"**[{escape_markdown(listing.title)}]({listing.url})**",
        " · ".join(
            part
            for part in (
                f"**{listing.price}**" if listing.price else None,
                f"~~{listing.previous_price}~~" if listing.previous_price else None,
                listing.badge,
                listing.margin_text,
            )
            if part
        ),
        listing.price_note,
        " · ".join(escape_markdown(value) for _, value in listing.facts),
        " · ".join(p for p in (seller, listing.rating) if p),
        f"{listing.flag} {listing.site} · {escape_markdown(listing.search_name)}".strip(),
    ]
    links = [f"[{labels.open}]({listing.url})"]
    if listing.can_buy:
        links[:0] = [
            f"[{labels.buy}]({listing.buy_url})",
            f"[{labels.message}]({listing.message_url})",
        ]
    lines.append(" · ".join(links))
    return title[:250], "\n\n".join(line for line in lines if line)


def quiet_url(url: str) -> str:
    """An Apprise address made to deliver without a sound, where its service can."""
    scheme = url.split("://", 1)[0].lower()
    if scheme not in _QUIET_OPTION:
        return url
    key, value = _QUIET_OPTION[scheme]
    url = re.sub(rf"([?&]){key}=[^&#]*&?", r"\1", url).rstrip("?&")
    return f"{url}{'&' if '?' in url else '?'}{key}={value}"


def _urls(config: dict[str, Any]) -> list[str]:
    raw = config.get("urls")
    if isinstance(raw, str):
        raw = [raw]
    urls = [str(url).strip() for url in raw or [] if str(url).strip()]
    if not urls:
        raise SenderConfigError("apprise destination needs 'urls': one or more Apprise URLs")
    return urls


class AppriseSender:
    """Sends one notification per listing to every Apprise URL configured."""

    kind = "apprise"

    def __init__(self, config: dict[str, Any], *, dashboard_url: str | None = None) -> None:
        urls = _urls(config)
        self._apprise = apprise.Apprise()
        self._quiet = apprise.Apprise()
        for position, url in enumerate(urls, start=1):
            # The URL itself stays out of the message: it usually holds a password or token.
            if not self._apprise.add(url) or not self._quiet.add(quiet_url(url)):
                raise SenderConfigError(f"Apprise does not recognise URL number {position}")
        self._dashboard_url = dashboard_url

    @property
    def max_batch(self) -> int:
        return 5

    async def send(self, batch: list[PendingNotification]) -> SendResult:
        delivered: list[int] = []
        for notification in batch:
            listing = view(notification, dashboard_url=self._dashboard_url)
            title, body = message(listing)
            services = self._quiet if listing.silent else self._apprise
            outcome = await services.async_notify(
                body=body,
                title=title,
                body_format=apprise.NotifyFormat.MARKDOWN,
                attach=listing.photos[0] if listing.photos else None,
                timeout=TIMEOUT_S,
            )
            if not outcome:
                remaining = [n.outbox_id for n in batch if n.outbox_id not in delivered]
                return SendResult(
                    delivered=delivered,
                    retry=remaining,
                    error=f"Apprise could not deliver to {outcome.failed_count} service(s)",
                )
            delivered.append(notification.outbox_id)
        return SendResult.ok(delivered)

    async def send_status(self, message_text: str) -> None:
        await self._apprise.async_notify(
            body=message_text,
            title=BOT_NAME,
            notify_type=apprise.NotifyType.WARNING,
            timeout=TIMEOUT_S,
        )

    async def aclose(self) -> None:
        """Nothing to close: Apprise opens and closes a connection per notification."""
