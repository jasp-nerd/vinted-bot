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
* A freshness window. A listing is too old when it carries a photo time before the window,
  or when the app already saw a newer listing id before the window (`listed_by`): ids
  are handed out in upload order, so that listing was on Vinted by then. This is what
  skips a month-old listing that a price cut has just brought into a search's range.

A search's first ever check is special: it records the page and tells you about none of it
(or exactly one, in 'newest' mode). Being greeted by ninety-six notifications is how people
conclude a tool is broken.

So is the first check after a gap longer than the window: the app was off, asleep or
blocked. Whatever was uploaded in the meantime is above the floor and newer than anything
the app has seen, so nothing can tell a listing from five minutes ago from one from
yesterday. The check catches up: it records the page quietly, like a first check, and
moves the floor up to it, instead of announcing a page of old listings as new.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from vinted_bot.vinted.models import Item

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
    # Unseen listings above the floor that were on Vinted before the freshness window,
    # with the moment they are known to have been there by. Logged as "too old" so a
    # quiet search can say why, unlike old stock below the floor, which is not news.
    too_old: list[tuple[Item, int]] = field(default_factory=list)


def newest_timestamp(items: list[Item]) -> int | None:
    """The most recent photo timestamp in a batch, whatever we do with the listings."""
    stamps = [item.photo_ts for item in items if item.photo_ts is not None]
    return max(stamps) if stamps else None


def needs_catch_up(last_success_at: int | None, *, now: int, gap_s: int) -> bool:
    """Whether the last good check was so long ago that this one should record quietly."""
    return last_success_at is not None and now - last_success_at > gap_s


def select(
    *,
    items: list[Item],
    seen_ids: set[int],
    floor_item_id: int | None,
    now: int,
    freshness_window_s: int,
    is_first_run: bool,
    page_is_full: bool = False,
    listed_by: Mapping[int, int] | None = None,
) -> Selection:
    """Work out which of a search's raw results are new enough to judge.

    `items` is everything the search returned, on every site it runs on. `page_is_full`
    says whether every site returned a whole page; only then is there anything "below the
    page" for the floor to keep out. On a first check (or a catch-up after a gap)
    `new` is the whole unseen page — the caller records it as seeded — and the floor jumps
    to the newest id, so nothing already on the shelf is ever judged as new later.

    `listed_by` maps listing ids to the earliest moment each is known to have existed;
    see `Repo.listed_by`.
    """
    ids = [item.item_id for item in items]
    newest_raw_id = max(ids) if ids else None
    raw_ts = newest_timestamp(items)
    unseen = sorted(
        (item for item in items if item.item_id not in seen_ids), key=lambda item: item.item_id
    )

    if is_first_run:
        candidates = [value for value in (floor_item_id, newest_raw_id) if value is not None]
        return Selection(
            new=unseen,
            newest_raw_id=newest_raw_id,
            newest_raw_ts=raw_ts,
            floor_item_id=max(candidates) if candidates else None,
        )

    cutoff = now - freshness_window_s
    known = listed_by or {}
    new: list[Item] = []
    too_old: list[tuple[Item, int]] = []
    stale = 0
    for item in unseen:
        if floor_item_id is not None and item.item_id <= floor_item_id:
            stale += 1
            continue
        listed = item.photo_ts if item.photo_ts is not None else known.get(item.item_id)
        if listed is not None and listed < cutoff:
            stale += 1
            too_old.append((item, listed))
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
        too_old=too_old,
    )


def first_run_pick(candidates: list[Item], mode: FirstRunMode) -> list[Item]:
    """On a first check, the one listing worth announcing to prove delivery works, if any."""
    if mode != "newest" or not candidates:
        return []
    return [max(candidates, key=lambda item: item.item_id)]
