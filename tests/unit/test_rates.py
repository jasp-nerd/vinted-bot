"""Exchange rates for searches whose sites price in more than one currency."""

from __future__ import annotations

from decimal import Decimal

import httpx

from vinted_bot.db.repo import Repo
from vinted_bot.engine import rates

ECB_FILE = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope><Cube><Cube time='2026-10-29'>
<Cube currency='USD' rate='1.0812'/><Cube currency='PLN' rate='4.3010'/>
<Cube currency='GBP' rate='0.8401'/></Cube></Cube></gesmes:Envelope>"""


def test_the_ecb_file_is_read_as_rates_per_euro() -> None:
    assert rates.parse(ECB_FILE) == {
        "USD": Decimal("1.0812"),
        "PLN": Decimal("4.3010"),
        "GBP": Decimal("0.8401"),
    }


def test_conversion_between_two_non_euro_currencies_goes_through_the_euro() -> None:
    table = {"PLN": Decimal("4"), "GBP": Decimal("0.8")}

    assert rates.convert(Decimal("100"), "PLN", "GBP", table) == Decimal("20.00")


def test_a_currency_without_a_rate_cannot_be_converted() -> None:
    assert rates.convert(Decimal("10"), "SEK", "EUR", {}) is None


def ecb(calls: list[str]) -> httpx.AsyncClient:
    def answer(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text=ECB_FILE)

    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


async def add_search(repo: Repo, *, extra: list[str]) -> None:
    await repo.add_query(
        name="nike",
        url="https://www.vinted.pl/catalog?search_text=nike",
        tld="pl",
        params={"search_text": "nike"},
        poll_interval_s=60,
        extra_tlds=extra,
    )


async def test_rates_are_fetched_and_stored_for_a_search_spanning_currencies(repo: Repo) -> None:
    await add_search(repo, extra=["lt"])
    calls: list[str] = []

    async with ecb(calls) as http:
        await rates.refresh(repo, http, await repo.list_queries())

    assert (await rates.load(repo))["PLN"] == Decimal("4.3010")


async def test_no_request_is_made_while_no_search_spans_currencies(repo: Repo) -> None:
    await add_search(repo, extra=[])
    calls: list[str] = []

    async with ecb(calls) as http:
        await rates.refresh(repo, http, await repo.list_queries())

    assert calls == []


async def test_rates_are_fetched_at_most_once_a_day(repo: Repo) -> None:
    await add_search(repo, extra=["lt"])
    calls: list[str] = []

    async with ecb(calls) as http:
        await rates.refresh(repo, http, await repo.list_queries(), now=1_000_000)
        await rates.refresh(repo, http, await repo.list_queries(), now=1_000_000 + 3600)

    assert len(calls) == 1
