"""When the dashboard asks for support, and the links it asks with.

The rules come from Canvas Course Downloader, where they were researched. Most gifts
come on the first one or two times an ask is seen, each repeat brings in less, and a
look that changes keeps it from fading into the page (Wikimedia's banner data, field
experiments on repeated asks). So the card shows the first time someone opens Finds
after an alert has reached them, then at most once a week and only after another
alert, each time in the next of three looks. It sits on the page and never interrupts.
Only "Don't show again" stops it; giving or starring keeps it, with a thank-you.

Nor in the first hour after setup: the first alert arrives minutes after it, and someone
still finding their way around has not yet had anything to be glad about.

It is never shown when something is wrong. A search waiting on Vinted or nowhere to
send alerts is a moment for help, not for a coffee. Nothing asks in setup, before the
app has found anything, and nothing asks inside the alerts themselves: those land in
someone's Discord or Telegram, which is theirs.
"""

from __future__ import annotations

import time
from urllib.parse import urlencode

from vinted_bot.db.repo import Repo, SupportState

WEEK_S = 7 * 24 * 60 * 60
LOOKS = 3
SETTLE_S = 60 * 60

# When setup last stored a search (app_state), so the card can wait out the first hour.
SETUP_AT_KEY = "setup_at"

KO_FI = "https://ko-fi.com/jaspnerd"
SPONSORS = "https://github.com/sponsors/jasp-nerd"
REPO = "https://github.com/jasp-nerd/vinted-bot"
WEBSITE = "https://vinted-bot.jaspnerd.dev"


def card_for(state: SupportState, now: int) -> int | None:
    """Which look the card shows in now, or None for no card."""
    if state.opted_out or state.last_alert_at is None:
        return None
    # Only right after it was useful: an alert since the card last showed.
    if state.last_alert_at <= state.last_shown_at:
        return None
    if state.last_shown_at and now - state.last_shown_at < WEEK_S:
        return None
    return state.times_shown % LOOKS


async def card_on_visit(repo: Repo, now: int | None = None) -> int | None:
    """Decide once, at this visit, and remember that it showed.

    Recording it here means a reload or a second tab doesn't ask again the same week.
    """
    now = int(time.time()) if now is None else now
    setup_at = await repo.get_state_value(SETUP_AT_KEY)
    if setup_at and setup_at.isdigit() and now - int(setup_at) < SETTLE_S:
        return None
    state = await repo.support_state()
    look = card_for(state, now)
    if look is not None:
        await repo.record_support_card_shown(state.times_shown + 1, now)
    return look


async def note_setup(repo: Repo, now: int | None = None) -> None:
    await repo.set_state_value(SETUP_AT_KEY, str(int(time.time()) if now is None else now))


def tracked(url: str, place: str) -> str:
    """Tag a link with where it was clicked, so Ko-fi and GitHub's traffic stats show
    what works. The tag is the same for everyone; nothing is sent from the app."""
    return f"{url}?{urlencode({'utm_source': 'vinted-bot', 'utm_medium': place})}"


def links(place: str) -> dict[str, str]:
    return {
        "kofi": tracked(KO_FI, place),
        "sponsors": tracked(SPONSORS, place),
        "star": tracked(REPO, place),
        "issue": f"{REPO}/issues/new/choose",
        # The website, not the repository: it reads well on a phone and for someone who
        # has never seen GitHub.
        "website": WEBSITE,
    }
