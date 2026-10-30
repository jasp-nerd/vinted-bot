"""Deciding which listings are actually new.

Vinted's catalog no longer says when a listing's photo was taken, so "new" rests on the
listing id, which Vinted hands out in upload order across the whole platform. Three gates:

* What this search has already decided about. Per search, not global: a listing another
  search found is still news to this one's destinations, and the outbox's one alert per
  destination rule stops anyone hearing it twice.
* A floor: the lowest id still worth considering. When the first page was full, anything
  below its lowest id was off the bottom of it, so if it appears later it is old stock
  pulled up by a deletion, not a new upload. A listing that turns up late but inside the
  range we have been watching is still announced — dropping those forever was the old
  mark's flaw.
* A freshness window, when a listing does carry a photo time, so a restart or a slow first
  check cannot replay yesterday's catalog.

A search's first ever check is special: it records the page and tells you about none of it
(or exactly one, in 'newest' mode). Being greeted by ninety-six notifications is how people
conclude a tool is broken.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from vinted_sniper.vinted.models import Item

FirstRunMode = Literal["silent", "newest"]


@dataclass(frozen=True, slots=True)
class Selection:
    """What a check concluded about its raw results, before any filter ran."""

    # Listings never judged before that are new enough to judge now, oldest first.
    new: list[Item]
    newest_raw_id: int | None
    newest_raw_ts: int | None
    # The floor to store for the next check.
    floor_item_id: int | None
    skipped_stale: int = 0


def newest_timestamp(items: list[Item]) -> int | None:
    """The most recent photo timestamp in a batch, whatever we do with the listings."""
    stamps = [item.photo_ts for item in items if item.photo_ts is not None]
    return max(stamps) if stamps else None


def select(
    *,
    items: list[Item],
    seen_ids: set[int],
    floor_item_id: int | None,
    now: int,
    freshness_window_s: int,
    is_first_run: bool,
    page_is_full: bool = False,
) -> Selection:
    """Work out which of a search's raw results are new enough to judge.

    `items` is everything the search returned, on every site it runs on. `page_is_full`
    says whether every site returned a whole page; only then is there anything "below the
    page" for the floor to keep out. On a first check
    `new` is the whole unseen page — the caller records it as seeded — and the floor jumps
    to the newest id, so nothing already on the shelf is ever judged as new later.
    """
    ids = [item.item_id for item in items]
    newest_raw_id = max(ids) if ids else None
    raw_ts = newest_timestamp(items)
    unseen = sorted(
        (item for item in items if item.item_id not in seen_ids), key=lambda item: item.item_id
    )

    if is_first_run:
        return Selection(
            new=unseen,
            newest_raw_id=newest_raw_id,
            newest_raw_ts=raw_ts,
            floor_item_id=newest_raw_id,
        )

    cutoff = now - freshness_window_s
    new: list[Item] = []
    stale = 0
    for item in unseen:
        if floor_item_id is not None and item.item_id <= floor_item_id:
            stale += 1
            continue
        if item.photo_ts is not None and item.photo_ts < cutoff:
            stale += 1
            continue
        new.append(item)

    # The floor only rises. Taking the page's lowest id each time would let it fall back
    # on a quiet search whose page reaches a month into the past. A page that was not full
    # held every result there is, so nothing was below it and the floor stays put.
    page_floor = min(ids) if ids and page_is_full else None
    candidates = [value for value in (floor_item_id, page_floor) if value is not None]
    return Selection(
        new=new,
        newest_raw_id=newest_raw_id,
        newest_raw_ts=raw_ts,
        floor_item_id=max(candidates) if candidates else None,
        skipped_stale=stale,
    )


def first_run_pick(candidates: list[Item], mode: FirstRunMode) -> list[Item]:
    """On a first check, the one listing worth announcing to prove delivery works, if any."""
    if mode != "newest" or not candidates:
        return []
    return [max(candidates, key=lambda item: item.item_id)]
