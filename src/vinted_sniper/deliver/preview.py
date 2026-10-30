"""Showing an alert before there is a real one.

Two jobs for the dashboard. `send_test` pushes a made-up listing through a destination's
real sender, so "is my webhook right?" gets answered in a second instead of after the next
match. `preview_payload` returns exactly what would be sent, without sending it, so the
page can draw "this is what your alerts will look like".

The sample listing is invented and says so. Its photo is the project icon, a stable public
URL, so the test does not depend on a Vinted photo that may have gone.
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, ClassVar

import httpx

from vinted_sniper.config import Settings
from vinted_sniper.db.repo import Destination, PendingNotification
from vinted_sniper.deliver import apprise, discord, ntfy, telegram, webhook
from vinted_sniper.deliver.base import SenderConfigError
from vinted_sniper.deliver.dispatcher import awaiting_pairing, build_sender
from vinted_sniper.deliver.render import ICON_URL, KINDS, view
from vinted_sniper.vinted.models import Item

SAMPLE_PHOTO = ICON_URL
SAMPLE_ITEM_ID = 1_000_000_001

_CURRENCY_BY_TLD = {"co.uk": "GBP", "pl": "PLN", "cz": "CZK", "com": "USD"}

# Ireland: English labels with euro prices, the closest thing to a neutral default. The
# dashboard can pass the site the user actually searches.
DEFAULT_SAMPLE_TLD = "ie"

# The most listings a preview lays out: one full Discord digest.
MAX_PREVIEW = 9


@dataclass(frozen=True, slots=True)
class TestResult:
    """How a test send went, worded for the person who pressed the button."""

    # Not a test case, whatever pytest's name-based collection thinks.
    __test__: ClassVar[bool] = False

    ok: bool
    message: str
    detail: str | None = None


def sample_notification(
    kind: str = "listing", *, tld: str = DEFAULT_SAMPLE_TLD, index: int = 0
) -> PendingNotification:
    """A realistic, clearly invented listing. Priced as a steal so the deal badge shows."""
    if kind not in KINDS:
        raise ValueError(f"unknown alert kind {kind!r}; expected one of {', '.join(KINDS)}")
    now = int(time.time())
    item_id = SAMPLE_ITEM_ID + index
    item = Item(
        item_id=item_id,
        tld=tld,
        title="Nike Air Max 90, white and grey (test alert)",
        url=f"https://www.vinted.{tld}/items/{item_id}",
        brand="Nike",
        size="42",
        condition="Very good",
        price=Decimal("24.00"),
        total_price=Decimal("25.90"),
        currency=_CURRENCY_BY_TLD.get(tld, "EUR"),
        photo_url=SAMPLE_PHOTO,
        photo_urls=(SAMPLE_PHOTO,),
        photo_ts=now - 120,
        seller_login="sample-seller",
        seller_rating=0.98,
        seller_feedback_count=213,
        favourite_count=7,
    )
    return PendingNotification(
        outbox_id=index,
        destination_id=0,
        query_id=0,
        query_name="Test alert",
        attempts=0,
        item=item,
        detected_at=now - 60,
        typical_price=Decimal("45.00"),
        kind=kind,
        previous_price=Decimal("32.00") if kind == "price_drop" else None,
    )


def preview_payload(
    destination_kind: str,
    *,
    config: dict[str, Any] | None = None,
    kind: str = "listing",
    count: int = 1,
    tld: str = DEFAULT_SAMPLE_TLD,
    dashboard_url: str | None = None,
) -> dict[str, Any]:
    """The JSON a destination of this kind and config would receive for sample listings.

    `count` above one shows the batch layout (several cards, or a digest). Only display
    settings are read from `config`; addresses and secrets are never needed or echoed.
    Discord answers with the message body; Telegram with {"method", "params"}.
    """
    config = config or {}
    batch = [
        sample_notification(kind, tld=tld, index=i) for i in range(max(1, min(count, MAX_PREVIEW)))
    ]
    listings = [view(n, dashboard_url=dashboard_url) for n in batch]
    match destination_kind:
        case "discord":
            options = discord.DiscordOptions.from_config(config)
            build = discord.classic_messages if options.style == "classic" else discord.v2_messages
            return build(listings, options)[0].payload
        case "telegram":
            options_tg = telegram.TelegramOptions.from_config(
                {**config, "chat_id": config.get("chat_id") or "CHAT_ID"}
            )
            if len(listings) == 1:
                method, params = telegram.listing_call(listings[0], options_tg)
            else:
                method, params = telegram.digest_call(listings, options_tg)
            return {"method": method, "params": params}
        case "ntfy":
            return ntfy.push(listings[0], topic=str(config.get("topic") or "your-topic"))
        case "webhook":
            return webhook.payload(batch)
        case "apprise":
            title, body = apprise.message(listings[0])
            return {"title": title, "body": body, "body_format": "markdown", "attach": SAMPLE_PHOTO}
        case unknown:
            raise ValueError(f"unknown destination type {unknown!r}")


async def send_test(
    destination: Destination,
    *,
    settings: Settings,
    tld: str = DEFAULT_SAMPLE_TLD,
    client: httpx.AsyncClient | None = None,
) -> TestResult:
    """Send one sample listing through a destination and say plainly how it went.

    `tld` picks the site the sample pretends to be from, which sets its language and
    currency. `client` lets a caller that already holds a connection pool reuse it.
    """
    if awaiting_pairing(destination):
        return TestResult(
            ok=False,
            message="This Telegram chat is not connected yet. Open the pairing link in the "
            "chat first, then test again.",
        )

    async with contextlib.AsyncExitStack() as stack:
        if client is None:
            client = await stack.enter_async_context(httpx.AsyncClient(timeout=20.0))
        try:
            sender = build_sender(destination, settings, client)
        except SenderConfigError as exc:
            return TestResult(
                ok=False, message="This destination is not set up correctly.", detail=str(exc)
            )
        try:
            result = await sender.send([sample_notification(tld=tld)])
        finally:
            await sender.aclose()

    if result.delivered:
        return TestResult(
            ok=True, message=f"Sent. A sample alert should be in {destination.name} now."
        )
    if result.permanent_error:
        return TestResult(
            ok=False,
            message="The destination refused it and looks gone or locked. Check the address.",
            detail=result.permanent_error,
        )
    if result.retry:
        return TestResult(
            ok=False,
            message="Could not get through right now. Try again in a minute.",
            detail=result.error,
        )
    return TestResult(
        ok=False, message="The destination rejected the message.", detail=result.error
    )
