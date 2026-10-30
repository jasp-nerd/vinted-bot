"""Everything else, through Apprise.

Apprise speaks to over a hundred services, each configured by one URL: email (`mailtos://`),
Slack, Pushover, Gotify, Matrix, Signal, Home Assistant and so on. Building each of those
natively would be a lot of code for channels a few people use, and Apprise already knows
how each one wants its formatting: we hand it markdown and it converts to HTML or plain
text per service. The native Discord, Telegram and ntfy senders stay, because they can do
far more than a title and a body.

Optional, because it brings `requests` and a handful of other packages along: install with
`pip install 'vinted-sniper[apprise]'`. The import happens only when such a destination
exists, so nobody else pays for it.
"""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING, Any

from vinted_sniper.db.repo import PendingNotification
from vinted_sniper.deliver.base import SenderConfigError, SendResult
from vinted_sniper.deliver.render import BOT_NAME, ListingView, view

if TYPE_CHECKING:
    import apprise as apprise_lib

# Apprise calls services one after another, so this caps each service, not the whole send.
TIMEOUT_S = 20.0

MISSING_EXTRA = "Apprise destinations need the optional extra: pip install 'vinted-sniper[apprise]'"


def is_available() -> bool:
    """Whether the extra is installed, so the dashboard can say so before anyone tries."""
    return importlib.util.find_spec("apprise") is not None


def message(listing: ListingView) -> tuple[str, str]:
    """A title and a markdown body for one listing."""
    labels = listing.labels
    title = f"{listing.price} · {listing.title}" if listing.price else listing.title
    if listing.kind != "listing":
        title = f"{listing.headline}: {title}"

    lines = [
        f"**[{listing.title}]({listing.url})**",
        " · ".join(
            part
            for part in (
                f"**{listing.price}**" if listing.price else None,
                f"~~{listing.previous_price}~~" if listing.previous_price else None,
                listing.badge,
            )
            if part
        ),
        listing.price_note,
        " · ".join(value for _, value in listing.facts),
        " · ".join(p for p in (listing.seller_login, listing.rating) if p),
        f"{listing.flag} {listing.site} · {listing.search_name}".strip(),
    ]
    links = [f"[{labels.open}]({listing.url})"]
    if listing.can_buy:
        links[:0] = [
            f"[{labels.buy}]({listing.buy_url})",
            f"[{labels.message}]({listing.message_url})",
        ]
    lines.append(" · ".join(links))
    return title[:250], "\n\n".join(line for line in lines if line)


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
        try:
            import apprise  # noqa: PLC0415 - optional extra, imported only when used
        except ImportError as exc:
            raise SenderConfigError(MISSING_EXTRA) from exc

        self._lib = apprise
        self._apprise: apprise_lib.Apprise = apprise.Apprise()
        for position, url in enumerate(urls, start=1):
            # The URL itself stays out of the message: it usually holds a password or token.
            if not self._apprise.add(url):
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
            outcome = await self._apprise.async_notify(
                body=body,
                title=title,
                body_format=self._lib.NotifyFormat.MARKDOWN,
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
            notify_type=self._lib.NotifyType.WARNING,
            timeout=TIMEOUT_S,
        )

    async def aclose(self) -> None:
        """Nothing to close: Apprise opens and closes a connection per notification."""
