"""Anonymous sessions: how many homepage loads things cost, and what gets replaced when."""

from __future__ import annotations

import asyncio

from tests.conftest import ScriptedTransport
from vinted_sniper.db import Database
from vinted_sniper.vinted.session import SessionManager
from vinted_sniper.vinted.transport import Response


def homepage_loads(transport: ScriptedTransport) -> int:
    return sum(1 for request in transport.requests if request["url"].endswith(".fr/"))


async def test_searches_starting_together_share_one_homepage_load(
    db: Database, transport: ScriptedTransport
) -> None:
    sessions = SessionManager(db, transport)

    await asyncio.gather(*(sessions.get("fr") for _ in range(5)))

    assert homepage_loads(transport) == 1


async def test_a_session_just_replaced_by_another_search_is_kept(
    db: Database, transport: ScriptedTransport
) -> None:
    sessions = SessionManager(db, transport)
    await sessions.get("fr")

    # A second search reports the same refusal after the first already rotated.
    await sessions.rotate("fr", blocked=True)

    assert homepage_loads(transport) == 1


async def test_a_session_refused_right_after_it_was_made_is_still_replaced(
    db: Database, transport: ScriptedTransport
) -> None:
    sessions = SessionManager(db, transport)
    session = await sessions.get("fr")
    session.failed = True

    await sessions.invalidate("fr")
    await sessions.get("fr")

    assert homepage_loads(transport) == 2


async def test_the_market_comes_from_the_cookie_the_site_set(
    db: Database, transport: ScriptedTransport
) -> None:
    transport.queue_root(
        Response(
            status_code=200,
            text="",
            headers={},
            cookies={"access_token_web": "t", "anonymous-iso-locale": "nl-NL"},
        )
    )

    session = await SessionManager(db, transport).get("bg")

    assert session.locale == "nl-NL"


async def test_without_that_cookie_the_market_follows_the_site(
    db: Database, transport: ScriptedTransport
) -> None:
    session = await SessionManager(db, transport).get("pl")

    assert session.locale == "pl-PL"
