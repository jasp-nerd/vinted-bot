"""Showing an alert before there is a real one.

Two jobs for the dashboard. `send_test` pushes a made-up listing through a destination's
real sender, so "is my webhook right?" gets answered in a second instead of after the next
match. `preview_payload` returns exactly what would be sent, without sending it, so the
page can draw "this is what your alerts will look like".

The sample listing is invented and says so, in the language of the site the person
shops on. Its photo is the demo jeans on the project's own site, a stable public URL, so
the test does not depend on a Vinted photo that may have gone, and still shows what a
real alert's photo looks like.
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, ClassVar

import httpx

from vinted_bot.config import Settings
from vinted_bot.db.repo import Destination, PendingNotification
from vinted_bot.deliver import apprise, discord, ntfy, telegram, webhook
from vinted_bot.deliver.base import SenderConfigError
from vinted_bot.deliver.dispatcher import awaiting_pairing, build_sender
from vinted_bot.deliver.labels import labels_for
from vinted_bot.deliver.render import KINDS, view
from vinted_bot.vinted.models import Item

SAMPLE_PHOTO = "https://vinted-bot.jaspnerd.dev/assets/demo/straight-leg-jeans.jpg"
SAMPLE_ITEM_ID = 1_000_000_001

# The sample's words in each language the alert labels speak: "(test alert)", the
# condition, and the search name. A Dutch alert that says "Very good" reads as broken.
_SAMPLE_WORDS: dict[str, tuple[str, str, str]] = {
    "en": ("test alert", "Very good", "Test alert"),
    "fr": ("alerte test", "Très bon état", "Alerte test"),
    "de": ("Testalarm", "Sehr gut", "Testalarm"),
    "nl": ("testmelding", "Heel goed", "Testmelding"),
    "es": ("alerta de prueba", "Muy bueno", "Alerta de prueba"),
    "it": ("avviso di prova", "Ottime condizioni", "Avviso di prova"),
    "pl": ("alert testowy", "Bardzo dobry", "Alert testowy"),
    "lt": ("bandomasis pranešimas", "Labai gera", "Bandomasis pranešimas"),
    "cs": ("testovací upozornění", "Velmi dobrý", "Testovací upozornění"),
}

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
    kind: str = "listing", *, tld: str = DEFAULT_SAMPLE_TLD, index: int = 0, deal: bool = False
) -> PendingNotification:
    """A realistic, clearly invented listing, worded in the site's language.

    An ordinary listing by default, so a test arrives at the destination's normal
    priority and without reseller sums nobody asked for. `deal` prices it as a steal
    with a resale margin, for previews that show what those look like. No listing time,
    like every real search result now, and no seller id, so a test alert's "block
    seller" button cannot block anyone real.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown alert kind {kind!r}; expected one of {', '.join(KINDS)}")
    now = int(time.time())
    item_id = SAMPLE_ITEM_ID + index
    marker, condition, search_name = _SAMPLE_WORDS.get(labels_for(tld).locale, _SAMPLE_WORDS["en"])
    item = Item(
        item_id=item_id,
        tld=tld,
        title=f"Levi's 501 straight jeans ({marker})",
        url=f"https://www.vinted.{tld}/items/{item_id}",
        brand="Levi's",
        size="W31",
        condition=condition,
        price=Decimal("22.00"),
        total_price=Decimal("23.80"),
        currency=_CURRENCY_BY_TLD.get(tld, "EUR"),
        photo_url=SAMPLE_PHOTO,
        photo_urls=(SAMPLE_PHOTO,),
        seller_login="sample-seller",
        seller_rating=0.98,
        seller_feedback_count=213,
        favourite_count=7,
    )
    return PendingNotification(
        outbox_id=index,
        destination_id=0,
        # No search sent it, which is what null means in the webhook payload.
        query_id=None,
        query_name=search_name,
        attempts=0,
        item=item,
        detected_at=now - 60,
        typical_price=Decimal("45.00") if deal else None,
        margin=Decimal("18.60") if deal else None,
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
        sample_notification(kind, tld=tld, index=i, deal=True)
        for i in range(max(1, min(count, MAX_PREVIEW)))
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
    telegram_token: str | None,
    tld: str = DEFAULT_SAMPLE_TLD,
    client: httpx.AsyncClient | None = None,
) -> TestResult:
    """Send one sample listing through a destination and say plainly how it went.

    `telegram_token` is the bot's current token (managed.telegram_token). `tld` picks the
    site the sample pretends to be from, which sets its language and currency. `client`
    lets a caller that already holds a connection pool reuse it.
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
            sender = build_sender(destination, settings, client, telegram_token=telegram_token)
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
