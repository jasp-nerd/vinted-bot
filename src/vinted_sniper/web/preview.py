"""The "preview what this finds" panel: one real search, answered from a short cache.

The editor and the setup both show what a search would match right now. That is a real
request to Vinted, so it is spent carefully: identical parameters within a minute are
answered from memory, and live requests are spaced out across the whole dashboard, so
someone typing quickly cannot turn the preview into a burst that gets the address slowed
down. The page is told how long to wait instead.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass
from decimal import Decimal

from vinted_sniper.db.repo import Query
from vinted_sniper.engine import filters
from vinted_sniper.vinted.client import VintedClient
from vinted_sniper.vinted.models import Item

CACHE_TTL_S = 60.0
CACHE_SIZE = 32
# Live preview requests are at least this far apart, dashboard-wide.
MIN_GAP_S = 4.0


_Key = tuple[str, tuple[tuple[str, str], ...]]


class TooSoonError(Exception):
    """A live request was asked for before the gap since the last one had passed."""

    def __init__(self, wait_s: float) -> None:
        super().__init__(f"try again in {wait_s:.1f}s")
        self.wait_s = wait_s


@dataclass(frozen=True, slots=True)
class Outcome:
    """What a search would do with the listings on Vinted right now."""

    seen: int
    matched: list[Item]
    removed: list[tuple[str, int]]


class PreviewService:
    def __init__(self, client: VintedClient) -> None:
        self._client = client
        self._cache: OrderedDict[_Key, tuple[float, list[Item]]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._last_live = 0.0

    async def listings(self, tld: str, params: dict[str, str]) -> list[Item]:
        """The first page of a search, from the cache or one live request.

        Raises `TooSoonError` rather than queueing, so the page can say "one moment"
        and the person is never left looking at a spinner they did not ask for.
        """
        key = (tld, tuple(sorted(params.items())))
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached is not None and now - cached[0] < CACHE_TTL_S:
            return cached[1]
        async with self._lock:
            wait = self._last_live + MIN_GAP_S - time.monotonic()
            if wait > 0:
                raise TooSoonError(wait)
            self._last_live = time.monotonic()
            items = await self._client.search(tld, params)
        self._cache[key] = (time.monotonic(), items)
        self._cache.move_to_end(key)
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return items


def judge(items: list[Item], query: Query, typical: dict[str, Decimal]) -> Outcome:
    """Run the search's cheap rules over a page of listings and count what each removed.

    Seller checks are left out: they cost a request per seller, which a preview should
    not spend. The page says so next to the receipt.
    """
    rules = filters.Rules(query)
    matched: list[Item] = []
    reasons: Counter[str] = Counter()
    for item in items:
        rejection = rules.check(item) or filters.check_deal(
            item, query, typical.get(item.currency or "")
        )
        if rejection is None:
            matched.append(item)
        else:
            reasons[rejection.reason] += 1
    return Outcome(seen=len(items), matched=matched, removed=reasons.most_common())
