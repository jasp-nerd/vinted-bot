"""The weekly live check: does Vinted still answer the way this app reads it?

`vinted-bot check` proves a search returns something. That would not have caught
September 2026, where the old filter names kept answering 200 with the filter silently
ignored, and brand, size and seller rating quietly vanished from every listing. This
checks the things that broke then: that a filter narrows the results, that the fields the
app shows are there, and that the member and item page lookups still parse.

Run with `python -m vinted_bot.vinted.canary [tld]`. Exits non-zero, listing each
problem, when anything drifted.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Final

from vinted_bot.db import Database, apply_pending
from vinted_bot.vinted.client import VintedClient
from vinted_bot.vinted.errors import VintedError
from vinted_bot.vinted.models import Item
from vinted_bot.vinted.session import SessionManager
from vinted_bot.vinted.transport import HttpxTransport

# Nike: the biggest brand on every site, so a filtered search is never empty.
_BRAND_ID: Final = "53"
_BRAND_NAME: Final = "Nike"
_CURRENCY: Final[dict[str, str]] = {"com": "USD", "co.uk": "GBP", "pl": "PLN"}
# Polite spacing between the handful of requests a run makes.
_GAP_S: Final = 3.0


async def check_site(client: VintedClient, tld: str, *, gap_s: float = _GAP_S) -> list[str]:
    """Every way the site's answers have drifted from what the app expects. Empty is good."""
    diagnosis = await client.diagnose(tld)
    if not diagnosis.catalog_ok:
        return [f"diagnosis: {diagnosis.message}"]

    await asyncio.sleep(gap_s)
    items = await client.search(tld, {"brand_ids": _BRAND_ID, "order": "newest_first"})
    if not items:
        return ["a brand search returned no listings"]

    problems = listing_problems(items, tld)

    first = items[0]
    if first.seller_id is None:
        return [*problems, "listings no longer name their seller"]
    await asyncio.sleep(gap_s)
    if await client.seller(tld, first.seller_id) is None:
        problems.append(f"member {first.seller_id} of a live listing could not be looked up")
    await asyncio.sleep(gap_s)
    snapshot = await client.item_snapshot(tld, first.item_id)
    if snapshot.price is None or not snapshot.photo_urls:
        problems.append(f"the page of item {first.item_id} no longer parses")
    return problems


def listing_problems(items: list[Item], tld: str) -> list[str]:
    """What is missing or wrong in a page of results filtered to one brand."""
    problems: list[str] = []
    if other := {item.brand for item in items if item.brand != _BRAND_NAME}:
        problems.append(f"the brand filter did not apply; also got {sorted(map(str, other))[:5]}")
    if any(not item.url.startswith("https://") for item in items):
        problems.append("listing links are not absolute")
    if any(item.price is None or item.total_price is None for item in items):
        problems.append("some listings have no price or total price")
    expected = _CURRENCY.get(tld, "EUR")
    if currencies := {item.currency for item in items} - {expected}:
        problems.append(f"expected {expected} prices, also got {sorted(map(str, currencies))}")
    if all(item.condition is None for item in items):
        problems.append("no listing has a condition any more")
    return problems


async def _run(tld: str) -> int:
    with tempfile.TemporaryDirectory() as scratch:
        async with Database(Path(scratch) / "canary.db") as db:
            await apply_pending(db)
            transport = HttpxTransport()
            try:
                client = VintedClient(transport, SessionManager(db, transport))
                problems = await check_site(client, tld)
            except VintedError as exc:
                problems = [f"{type(exc).__name__}: {exc}"]
            finally:
                await transport.aclose()

    for problem in problems:
        print(f"vinted.{tld}: {problem}", file=sys.stderr)
    if not problems:
        print(f"vinted.{tld}: search, filters, listings, members and item pages all read fine")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run(sys.argv[1] if len(sys.argv) > 1 else "com")))
