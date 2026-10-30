"""Turning stored rows into what the templates show.

Everything a person reads is settled here: prices arrive in the site's currency
("€23.80"), times as words ("2 min ago", "every minute"), a search's state as a plain
sentence. The templates then only lay things out, and a wording change is one edit.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from vinted_bot.db.repo import Destination, FeedItem, Query
from vinted_bot.engine.health import SearchHealth

# The seven search colours the design validated for telling series apart, light theme
# values. A stored colour that matches one is drawn through its CSS token, so it shifts
# with dark mode; anything else (searches made in the CLI) is drawn as stored.
SLOT_COLORS = ("#2A78D6", "#EB6834", "#EDA100", "#E87BA4", "#008300", "#6250D6", "#1BAF7A")

# Below this a "deal" badge is noise: when a third of the feed carries one, it stops
# meaning anything. The same line as the Deals tier, so badge and alert agree.
DEAL_BADGE_MIN_PCT = 20

# A search that has matched nothing for this long is called quiet rather than watching.
QUIET_AFTER_S = 3 * 3600

CURRENCY_BY_TLD = {
    "co.uk": "GBP",
    "pl": "PLN",
    "cz": "CZK",
    "se": "SEK",
    "dk": "DKK",
    "hu": "HUF",
    "ro": "RON",
    "com": "USD",
}
_PREFIX_SYMBOLS = {"EUR": "€", "GBP": "£", "USD": "$"}
_SUFFIX_SYMBOLS = {"PLN": "zł", "CZK": "Kč", "SEK": "kr", "DKK": "kr", "HUF": "Ft", "RON": "lei"}

# Country sites in the order the setup offers them first, then everything else.
COUNTRIES: tuple[tuple[str, str, str], ...] = (
    ("nl", "NL", "Netherlands"),
    ("fr", "FR", "France"),
    ("de", "DE", "Germany"),
    ("be", "BE", "Belgium"),
    ("es", "ES", "Spain"),
    ("it", "IT", "Italy"),
    ("co.uk", "GB", "United Kingdom"),
    ("pl", "PL", "Poland"),
    ("at", "AT", "Austria"),
    ("cz", "CZ", "Czechia"),
    ("dk", "DK", "Denmark"),
    ("fi", "FI", "Finland"),
    ("gr", "GR", "Greece"),
    ("hr", "HR", "Croatia"),
    ("hu", "HU", "Hungary"),
    ("ie", "IE", "Ireland"),
    ("lt", "LT", "Lithuania"),
    ("lu", "LU", "Luxembourg"),
    ("lv", "LV", "Latvia"),
    ("ee", "EE", "Estonia"),
    ("pt", "PT", "Portugal"),
    ("ro", "RO", "Romania"),
    ("se", "SE", "Sweden"),
    ("sk", "SK", "Slovakia"),
    ("si", "SI", "Slovenia"),
    ("bg", "BG", "Bulgaria"),
    ("com", "US", "United States"),
)
COUNTRY_NAMES = {tld: name for tld, _, name in COUNTRIES}

# Browser languages to the site people most likely shop on. A guess, labelled as one.
_TLD_BY_LANGUAGE = {
    "nl": "nl",
    "fr": "fr",
    "de": "de",
    "es": "es",
    "it": "it",
    "pl": "pl",
    "cs": "cz",
    "sk": "sk",
    "lt": "lt",
    "pt": "pt",
    "sv": "se",
    "ro": "ro",
    "hu": "hu",
    "el": "gr",
    "fi": "fi",
    "da": "dk",
    "hr": "hr",
    "sl": "si",
    "et": "ee",
    "lv": "lv",
    "bg": "bg",
}
_TLD_BY_REGION = {"GB": "co.uk", "UK": "co.uk", "US": "com", "IE": "ie", "BE": "be", "AT": "at"}

# Why a listing was not sent, in words, with the icon the "Not sent" tab shows.
REJECTION_WORDS: dict[str, tuple[str, str]] = {
    "over_budget": ("Too expensive", "badge-percent"),
    "under_minimum": ("Cheaper than your minimum", "badge-percent"),
    "no_price": ("No price on the listing", "badge-percent"),
    "banned_keyword": ("Has a word you skip", "ban"),
    "missing_keyword": ("Missing a word you want", "search"),
    "regex": ("Title pattern did not match", "search"),
    "condition": ("Condition you didn't pick", "tag"),
    "promoted": ("Old listing pushed to the top", "trending-down"),
    "blocked_seller": ("Seller you blocked", "user-x"),
    "seller_country": ("Seller in another country", "globe"),
    "few_reviews": ("Seller has few reviews", "user-x"),
    "low_rating": ("Seller rating too low", "star"),
    "unrated_seller": ("Brand-new seller", "user-x"),
    "seller_unknown": ("Couldn't check the seller yet", "hourglass"),
    "not_a_deal": ("Not cheap enough to be a deal", "trending-down"),
    "quiet_hours": ("Quiet hours", "clock"),
    "low_margin": ("Not enough left after reselling", "badge-percent"),
    "muted": ("Search was muted", "bell-off"),
}


def currency_for(tld: str) -> str:
    return CURRENCY_BY_TLD.get(tld, "EUR")


def money(amount: Decimal | float | None, currency: str | None) -> str:
    """A price the way the site writes it: €23.80, £9.00, 23.80 zł."""
    if amount is None:
        return ""
    value = f"{Decimal(str(amount)):,.2f}"
    code = (currency or "EUR").upper()
    if code in _PREFIX_SYMBOLS:
        return f"{_PREFIX_SYMBOLS[code]}{value}"
    return f"{value} {_SUFFIX_SYMBOLS.get(code, code)}"


def symbol(currency: str) -> str:
    return _PREFIX_SYMBOLS.get(currency) or _SUFFIX_SYMBOLS.get(currency, currency)


def ago(seconds: float) -> str:
    """How long ago, in the words a person uses."""
    seconds = max(int(seconds), 0)
    if seconds < 45:  # noqa: PLR2004
        return "just now"
    if seconds < 3600:  # noqa: PLR2004
        return f"{max(round(seconds / 60), 1)} min ago"
    if seconds < 86_400:  # noqa: PLR2004
        return f"{seconds // 3600} h ago"
    days = seconds // 86_400
    if days == 1:
        return "yesterday"
    if days < 14:  # noqa: PLR2004
        return f"{days} days ago"
    return f"{days // 7} weeks ago"


def duration(seconds: float) -> str:
    """A span: "40 seconds", "5 hours", "2 min 40 s"."""
    seconds = max(int(seconds), 0)
    if seconds < 60:  # noqa: PLR2004
        return f"{seconds} seconds"
    if seconds < 3600:  # noqa: PLR2004
        minutes, rest = divmod(seconds, 60)
        return f"{minutes} min {rest} s" if rest and minutes < 10 else f"{minutes} min"  # noqa: PLR2004
    hours = seconds // 3600
    if hours < 48:  # noqa: PLR2004
        return "1 hour" if hours == 1 else f"{hours} hours"
    return f"{hours // 24} days"


def every(seconds: int) -> str:
    """A check interval: "every minute", "every 2 minutes", "every 90 seconds"."""
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return "every hour" if hours == 1 else f"every {hours} hours"
    if seconds % 60 == 0:
        minutes = seconds // 60
        return "every minute" if minutes == 1 else f"every {minutes} minutes"
    return f"every {seconds} seconds"


def color_css(color: str | None) -> str:
    """The CSS colour for a search's dot: its theme token if it is one of the slots."""
    if not color:
        return "var(--c-text-3)"
    upper = color.upper()
    if upper in SLOT_COLORS:
        return f"var(--s-{SLOT_COLORS.index(upper) + 1})"
    return upper


def guess_tld(accept_language: str | None) -> str:
    """The Vinted site a browser's language points to; the Netherlands if it says nothing."""
    for part in (accept_language or "").split(","):
        tag = part.split(";")[0].strip()
        if not tag:
            continue
        language, _, region = tag.partition("-")
        if region.upper() in _TLD_BY_REGION:
            return _TLD_BY_REGION[region.upper()]
        if region.lower() in COUNTRY_NAMES and region.lower() != "com":
            return region.lower()
        if language.lower() in _TLD_BY_LANGUAGE:
            return _TLD_BY_LANGUAGE[language.lower()]
    return "nl"


# --- Listings ----------------------------------------------------------------------


def search_chip(query_id: int | None, name: str | None, color: str | None) -> dict[str, Any]:
    return {"id": query_id or 0, "name": name or "Followed seller", "color": color_css(color)}


def item_view(entry: FeedItem, now: int) -> dict[str, Any]:
    """A listing card. Only id, title, prices, link, age and search are always there."""
    item = entry.item
    show_brand = item.brand if item.brand and item.brand.lower() not in item.title.lower() else None
    meta = " · ".join(part for part in (show_brand, item.size, item.condition) if part)
    deal = entry.deal_pct
    total = item.total_price if item.total_price is not None else item.price
    stars = round(item.seller_rating * 5, 1) if item.seller_rating is not None else None
    name = entry.query_name
    if entry.query_id is None and item.seller_login:
        name = f"Followed seller {item.seller_login}"
    return {
        "id": item.item_id,
        "seq": entry.seq,
        "url": item.url,
        "title": item.title,
        "photo": item.photo_url,
        "dominant": None,
        "price": money(item.price, item.currency),
        "total": money(total, item.currency),
        "total_num": float(total) if total is not None else None,
        "meta": meta,
        "deal_pct": deal if deal is not None and deal >= DEAL_BADGE_MIN_PCT else None,
        "typical": money(entry.typical_price, item.currency) if entry.typical_price else None,
        "rating": stars,
        "reviews": item.seller_feedback_count,
        "is_new": False,
        "saved": entry.mark == "saved",
        "age": ago(now - entry.first_seen_at),
        "found_at": entry.first_seen_at,
        "search": search_chip(entry.query_id, name, entry.query_color),
        "seller": item.seller_login,
        "seller_id": item.seller_id,
        "tld": item.tld,
    }


# --- Searches ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Status:
    """A search's state in one word (for the dot) and one sentence (for the reason)."""

    key: str
    label: str
    why: str


def search_status(
    query: Query,
    health: SearchHealth | None,
    *,
    now: int,
    newest_find: int | None,
    site_is_moving: bool,
    stale_after: int,
) -> Status:
    """Plain words for how a search is doing, chosen so trouble never reads as quiet.

    "Stuck" follows the watchdog's own rule: the catalog has not moved for many checks
    while another search on the same site still finds things.
    """
    site = f"vinted.{query.tld}"
    held = _held_status(query, health, now)
    if held is not None or health is None:
        return held or Status("quiet", "Starting", _STARTING)
    failing = _failing_status(health, site)
    if failing is not None:
        return failing
    if health.checks_without_new_listings >= stale_after and site_is_moving:
        # Vinted answers, so this is not "waiting on Vinted": the site is fine, this one
        # search's results just stopped changing.
        return Status(
            "stale",
            "Same results lately",
            f"{site} answers, but keeps showing this search the same listings. Nothing "
            "you need to do; it usually sorts itself out within the hour.",
        )
    if newest_find is None or now - newest_find > QUIET_AFTER_S:
        span = f" for {duration(now - newest_find)}" if newest_find else " yet"
        return Status(
            "quiet",
            "Quiet",
            f"Running fine, no new matches{span}. That's normal for a narrow search, or at night.",
        )
    checked = ago(now - health.last_success_at) if health.last_success_at else "recently"
    return Status("watching", "Running", f"Checked {checked}. All fine.")


_STARTING = "Getting ready. The first check runs within a minute."
_PAUSED = "Paused by you. No checks and no alerts until you resume."


def _held_status(query: Query, health: SearchHealth | None, now: int) -> Status | None:
    """Paused, muted, or not checked yet: states the person caused or just started."""
    if query.paused:
        return Status(
            "paused", "Paused", "Paused by you. No checks and no alerts until you resume."
        )
    if query.muted_until is not None and query.is_muted(now):
        return Status(
            "paused",
            "Muted",
            f"Muted for another {duration(query.muted_until - now)}. It keeps checking, "
            "but sends nothing until then.",
        )
    if health is None or (health.last_success_at is None and not health.last_status):
        return Status("quiet", "Starting", _STARTING)
    return None


def _failing_status(health: SearchHealth, site: str) -> Status | None:
    match health.last_status:
        case None | "ok" | "http_401":
            return None
        case "http_403":
            return Status(
                "blocked",
                "Slowed down by Vinted",
                f"{site} asked us to slow down. We wait a few minutes before trying again. "
                "Your Vinted account is not affected (we never use one).",
            )
        case "http_429":
            return Status(
                "stuck",
                "Slowed down by Vinted",
                f"{site} asked us to check less often. We wait as long as it says, then carry on.",
            )
        case "network":
            return Status(
                "stuck",
                "Can't reach Vinted",
                f"We couldn't reach {site} from this computer. Check the internet connection; "
                "we keep trying.",
            )
        case _:
            return Status(
                "stuck",
                "Waiting on Vinted",
                f"{site} answered with something we didn't expect. We keep trying. If it "
                "lasts a day, look for an update.",
            )


def search_summary(query: Query) -> str:
    """What a search looks for, in one line a person can scan."""
    params = query.params
    currency = currency_for(query.tld)
    parts: list[str] = []
    if text := params.get("search_text"):
        parts.append(f'"{text}"')
    for key, one, many in (
        ("catalog_ids", "1 category", "categories"),
        ("brand_ids", "1 brand", "brands"),
        ("size_ids", "1 size", "sizes"),
        ("status_ids", "1 condition", "conditions"),
        ("color_ids", "1 colour", "colours"),
    ):
        count = len([part for part in params.get(key, "").split(",") if part])
        if count:
            parts.append(one if count == 1 else f"{count} {many}")
    if price := _price_words(query, currency):
        parts.append(price)
    if item_price := link_price(params, currency):
        parts.append(item_price)
    parts.extend(_rule_words(query))
    return " · ".join(parts) or "Everything new on the site"


def _rule_words(query: Query) -> list[str]:
    words = ["title has " + " or ".join(term.split("|")) for term in query.include_terms]
    if query.banned_keywords:
        words.append("no " + ", ".join(query.banned_keywords[:4]))
    if query.deal_only_pct:
        words.append(f"deals only, {query.deal_only_pct}% under typical")
    if query.seller_min_rating:
        words.append(f"seller {query.seller_min_rating:g} stars or more")
    if query.countries:
        words.append("seller in " + ", ".join(query.countries))
    if query.resale_price is not None:
        currency = currency_for(query.tld)
        resale = f"resells for {money(query.resale_price, currency)}"
        if query.min_margin is not None:
            resale += f", at least {money(query.min_margin, currency)} left"
        words.append(resale)
    return words


def _amount(raw: str | None) -> Decimal | None:
    try:
        value = Decimal((raw or "").replace(",", "."))
    except ArithmeticError:
        return None
    return value if value.is_finite() and value >= 0 else None


def link_price(params: dict[str, str], currency: str) -> str | None:
    """The price limit a pasted Vinted link carries, which Vinted applies to the item price.

    Kept apart from our own limits, which include the buyer protection fee, so nobody
    reads one as the other and types the same limit in twice.
    """
    low, high = _amount(params.get("price_from")), _amount(params.get("price_to"))
    if low is not None and high is not None:
        return f"item price {money(low, currency)} to {money(high, currency)}"
    if high is not None:
        return f"item price up to {money(high, currency)}"
    if low is not None:
        return f"item price from {money(low, currency)}"
    return None


def _price_words(query: Query, currency: str) -> str | None:
    low, high = query.min_total_price, query.max_total_price
    if low is not None and high is not None:
        return f"{money(low, currency)} to {money(high, currency)} incl. fees"
    if high is not None:
        return f"up to {money(high, currency)} incl. fees"
    if low is not None:
        return f"from {money(low, currency)} incl. fees"
    return None


def quiet_summary(query: Query) -> str | None:
    if not query.quiet_start or not query.quiet_end:
        return None
    mode = {
        "hold": "saved for the morning",
        "silent": "sent without sound",
        "drop": "not sent",
    }.get(query.quiet_mode, "")
    return f"Quiet {query.quiet_start} to {query.quiet_end}, {mode}"


# --- Destinations ------------------------------------------------------------------

KIND_NAMES = {
    "discord": "Discord",
    "telegram": "Telegram",
    "ntfy": "Notification on your phone",
    "apprise": "Email and more",
    "webhook": "Your own app",
}


def destination_label(destination: Destination) -> str:
    """Where a destination sends, without spelling out its secret address."""
    config = destination.config
    match destination.kind:
        case "telegram":
            if not config.get("chat_id"):
                return "Waiting for you to connect a chat"
            return f"Chat {config.get('chat_id')}"
        case "ntfy":
            topic = str(config.get("topic") or config.get("url") or "").rstrip("/")
            return f"Topic: {topic.rpartition('/')[2]}"
        case "apprise":
            urls = config.get("urls") or []
            count = len(urls) if isinstance(urls, list) else 1
            return "1 service" if count == 1 else f"{count} services"
        case "webhook":
            url = str(config.get("url") or "")
            return url.split("/")[2] if url.count("/") >= 2 else url  # noqa: PLR2004
        case _:
            return "Discord channel"


def destination_view(
    destination: Destination,
    *,
    sent: int,
    failed: int,
    searches: list[dict[str, Any]],
    last_test: dict[str, Any] | None = None,
    telegram_ready: bool = True,
    tz: ZoneInfo | None = None,
) -> dict[str, Any]:
    """A destination's card. Green only when something actually arrived through it.

    `last_test` is the latest "Send a test" result ({"ok", "at", "message"}), and
    `telegram_ready` whether the bot token is set, without which Telegram cannot send.
    """
    config = destination.config
    status, status_label, detail = _destination_state(
        destination,
        sent=sent,
        failed=failed,
        last_test=last_test,
        telegram_ready=telegram_ready,
        tz=tz,
    )
    return {
        "id": destination.id,
        "kind": destination.kind,
        "name": destination.name,
        "label": destination_label(destination),
        "status": status,
        "status_label": status_label,
        "detail": detail,
        "searches": searches,
        "opts": {
            "tiers": _tiers(config, "tiers", ["steal", "deal", "normal"]),
            "silent_tiers": _tiers(config, "silent_tiers", []),
            "ping_tiers": _tiers(config, "ping_tiers", ["steal"]),
            "deals_only": bool(config.get("deals_only")),
            "silent": bool(config.get("silent")),
            "style": config.get("style") or ("card" if destination.kind == "discord" else "photo"),
            "mention": config.get("mention") or "",
            "priority": str(config.get("priority") or "3"),
            "min_deal_pct": config.get("min_deal_pct") or "",
        },
    }


def _destination_state(
    destination: Destination,
    *,
    sent: int,
    failed: int,
    last_test: dict[str, Any] | None,
    telegram_ready: bool,
    tz: ZoneInfo | None,
) -> tuple[str, str, str]:
    """(status key, badge, sentence), most serious first: off, cannot work, failing, unproven."""
    tested_at = ""
    if last_test and isinstance(last_test.get("at"), int):
        tested_at = f" at {clock(last_test['at'], tz or ZoneInfo('UTC'))}"
    broken = _cannot_send(destination, failed=failed, telegram_ready=telegram_ready)
    if broken is not None:
        return broken
    if last_test and not last_test.get("ok"):
        reason = str(last_test.get("message") or "").strip()
        return "failing", "Last test failed", f"The test{tested_at} didn't arrive. {reason}".strip()
    if sent:
        return "ok", "Working", f"{sent:,} alerts sent so far."
    if last_test and last_test.get("ok"):
        return "ok", "Test arrived", f"Test sent{tested_at}. Real alerts will show here."
    return "untested", "Not tested yet", "Nothing sent yet. Send a test to check it works."


def _cannot_send(
    destination: Destination, *, failed: int, telegram_ready: bool
) -> tuple[str, str, str] | None:
    """Why a destination can't deliver right now, if it can't."""
    if not destination.active:
        return (
            "failing",
            "Turned off",
            f"It stopped working and was switched off: {destination.deactivated_reason}.",
        )
    if destination.kind == "telegram" and not telegram_ready:
        return (
            "warn",
            "Needs the bot token",
            "Telegram can't send anything until it knows your bot. Paste the token "
            "BotFather gave you in the Telegram bot card below.",
        )
    if destination.kind == "telegram" and not destination.config.get("chat_id"):
        return (
            "waiting",
            "Not connected yet",
            "Send the code to your bot in Telegram to finish connecting.",
        )
    if destination.failure_count:
        return (
            "failing",
            "Not working",
            f"The last {destination.failure_count} tries failed ({failed} alerts in all). "
            "Send a test to see why.",
        )
    return None


def _tiers(config: dict[str, Any], key: str, default: list[str]) -> list[str]:
    raw = config.get(key)
    if raw is None:
        tiers = list(default)
        if key == "tiers" and config.get("deals_only"):
            tiers = ["steal", "deal"]
        return tiers
    if isinstance(raw, str):
        raw = raw.split(",")
    return [str(tier).strip().lower() for tier in raw] if isinstance(raw, list) else default


# --- Time --------------------------------------------------------------------------


def clock(epoch: int, tz: ZoneInfo) -> str:
    """A time of day on the reader's clock, with the day when it was not today."""
    moment = datetime.fromtimestamp(epoch, tz)
    today = datetime.fromtimestamp(time.time(), tz).date()
    if moment.date() == today:
        return moment.strftime("%H:%M")
    return moment.strftime("%-d %b %H:%M")
