"""The weekly live check, run against recorded answers instead of the live site."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.conftest import ScriptedTransport
from vinted_bot.db import Database
from vinted_bot.vinted.canary import check_site, listing_problems
from vinted_bot.vinted.client import VintedClient
from vinted_bot.vinted.models import parse_item
from vinted_bot.vinted.session import SessionManager
from vinted_bot.vinted.transport import Response

FIXTURES = Path(__file__).parent.parent / "fixtures" / "vinted"


def recorded(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def catalogue(brand_only: bool) -> str:
    payload: dict[str, Any] = json.loads(recorded("catalogue_fr.json"))
    if brand_only:
        payload["items"] = [i for i in payload["items"] if i["item_box"]["first_line"] == "Nike"]
    return json.dumps(payload)


def ok(body: str) -> Response:
    return Response(status_code=200, text=body, headers={}, cookies={})


async def run_canary(db: Database, transport: ScriptedTransport, search_body: str) -> list[str]:
    transport.queue(ok(catalogue(brand_only=True)))  # the diagnosis
    transport.queue(ok(search_body))  # the brand search
    transport.queue(ok(recorded("user_fr.json")))  # the member lookup
    sessions = SessionManager(db, transport)
    await sessions.get("fr")
    transport.queue_root(ok(recorded("item_available_fr.html")))  # the item page
    return await check_site(VintedClient(transport, sessions), "fr", gap_s=0)


async def test_answers_shaped_as_expected_raise_no_problems(
    db: Database, transport: ScriptedTransport
) -> None:
    assert await run_canary(db, transport, catalogue(brand_only=True)) == []


async def test_a_silently_ignored_filter_is_caught(
    db: Database, transport: ScriptedTransport
) -> None:
    problems = await run_canary(db, transport, catalogue(brand_only=False))

    assert any("brand filter did not apply" in problem for problem in problems)


def test_relative_listing_links_are_caught() -> None:
    entry = json.loads(catalogue(brand_only=True))["items"][0]
    item = parse_item(entry, "fr").model_copy(update={"url": "/items/1"})

    assert listing_problems([item], "fr") == ["listing links are not absolute"]
