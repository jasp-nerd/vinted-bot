"""Converting prices between the currencies Vinted's country sites use.

A search on vinted.pl that also runs on vinted.lt sees zloty and euro listings side by
side, and its 80 zł limit says nothing about a 39 € listing until one of them is
converted. Comparing the bare numbers let that listing through as "39, under 80".

The rates are the European Central Bank's daily reference rates: free, keyless, one small
anonymous request a day, and only made while some search spans more than one currency.
They are stored in app_state, so a restart does not ask again.

Whether some search needs them is looked at every few minutes, and at once when a search
starts: a new vinted.pl + vinted.lt search used to wait up to five minutes for its rates.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation

import httpx

from vinted_bot.db.repo import Query, Repo
from vinted_bot.deals import site_currency
from vinted_bot.engine.wakeups import wait_for_any
from vinted_bot.log import get_logger

log = get_logger(__name__)

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

# The ECB publishes once a working day; a day-old rate is close enough for a price limit.
REFRESH_EVERY_S = 86_400
# After a failed fetch, try again this much later rather than on every pass.
RETRY_AFTER_S = 3600

# How often to look whether a search needs rates. Looking costs one read of the database;
# the request itself is made at most once a day.
LOOK_EVERY_S = 300.0

_RATES_KEY = "exchange_rates"
_TRIED_KEY = "exchange_rates_tried_at"

# <Cube currency='USD' rate='1.0812'/>: the only part of the file that matters, read with
# a pattern rather than an XML parser so nothing in the file is ever interpreted.
_CUBE = re.compile(r"""currency=['"]([A-Z]{3})['"]\s+rate=['"]([0-9.]+)['"]""")

_CENT = Decimal("0.01")
_EURO = "EUR"


def convert(
    amount: Decimal, source: str, target: str, rates: Mapping[str, Decimal]
) -> Decimal | None:
    """`amount` in `source` currency, expressed in `target`. None without both rates.

    The ECB quotes everything against the euro, so a conversion goes through it.
    """
    if source == target:
        return amount
    per_euro_source = Decimal(1) if source == _EURO else rates.get(source)
    per_euro_target = Decimal(1) if target == _EURO else rates.get(target)
    if not per_euro_source or not per_euro_target:
        return None
    return (amount / per_euro_source * per_euro_target).quantize(_CENT)


def spans_currencies(query: Query) -> bool:
    """Whether a search's sites price in more than one currency."""
    return len({site_currency(site) for site in query.sites}) > 1


def parse(text: str) -> dict[str, Decimal]:
    """The euro reference rates in the ECB's daily file."""
    rates: dict[str, Decimal] = {}
    for currency, raw in _CUBE.findall(text):
        try:
            value = Decimal(raw)
        except InvalidOperation:
            # A number the pattern let through but Decimal cannot read ("1.2.3"): that
            # one currency is left out, and limits in it say so when they are checked.
            continue
        if value > 0:
            rates[currency] = value
    return rates


async def load(repo: Repo) -> dict[str, Decimal]:
    """The stored rates, or nothing if none were ever fetched."""
    raw = await repo.get_state_value(_RATES_KEY)
    if not raw:
        return {}
    stored = json.loads(raw)
    return {currency: Decimal(value) for currency, value in stored["rates"].items()}


async def refresh(
    repo: Repo, http: httpx.AsyncClient, queries: Iterable[Query], *, now: int | None = None
) -> None:
    """Fetch today's rates if an active search needs them and the stored ones are old."""
    if not any(spans_currencies(query) for query in queries if not query.paused):
        return
    moment = now or int(time.time())
    if (raw := await repo.get_state_value(_RATES_KEY)) and (
        moment - int(json.loads(raw)["fetched_at"]) < REFRESH_EVERY_S
    ):
        return
    tried = await repo.get_state_value(_TRIED_KEY)
    if tried is not None and moment - int(tried) < RETRY_AFTER_S:
        return
    await repo.set_state_value(_TRIED_KEY, str(moment))
    try:
        response = await http.get(ECB_URL, timeout=10.0)
    except httpx.HTTPError as exc:
        log.info("rates.fetch_failed", error=type(exc).__name__)
        return
    if response.is_error:
        log.info("rates.fetch_failed", status=response.status_code)
        return
    rates = parse(response.text)
    if not rates:
        log.warning("rates.fetch_failed", error="no rates in the ECB file")
        return
    await repo.set_state_value(
        _RATES_KEY,
        json.dumps({"fetched_at": moment, "rates": {c: str(v) for c, v in rates.items()}}),
    )
    log.info("rates.updated", currencies=len(rates))


async def keep_fresh(
    repo: Repo, http: httpx.AsyncClient, stop: asyncio.Event, search_started: asyncio.Event
) -> None:
    """Refresh the rates whenever needed, until `stop`; `search_started` looks at once."""
    while not stop.is_set():
        try:
            await refresh(repo, http, await repo.list_queries(include_paused=False))
        except sqlite3.OperationalError as exc:
            # A locked database; the next pass catches up.
            log.warning("rates.db_unavailable", error=str(exc))
        search_started.clear()
        await wait_for_any(LOOK_EVERY_S, stop, search_started)
