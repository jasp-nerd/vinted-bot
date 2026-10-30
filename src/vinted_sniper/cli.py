"""Command line entry points."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from vinted_sniper import __version__, app, log
from vinted_sniper.config import Settings
from vinted_sniper.db import Database, apply_pending
from vinted_sniper.db import export as exporter
from vinted_sniper.db.repo import Repo
from vinted_sniper.engine import health, validation
from vinted_sniper.vinted import urls
from vinted_sniper.vinted.client import VintedClient
from vinted_sniper.vinted.errors import BlockedError, VintedError
from vinted_sniper.vinted.session import SessionManager
from vinted_sniper.vinted.transport import TransportSession

TROUBLESHOOTING = "https://github.com/jasp-nerd/vinted-sniper/blob/main/docs/troubleshooting.md"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vinted-sniper",
        description="Watch Vinted searches and get notified when something matches.",
    )
    parser.add_argument("--version", action="version", version=f"vinted-sniper {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Start watching. This is what the container runs.")
    run.add_argument(
        "--open", action="store_true", help="Open the dashboard in your browser once it is up."
    )
    sub.add_parser("migrate", help="Create or update the database, then exit.")
    sub.add_parser("status", help="Show how each search is doing.")
    sub.add_parser("heartbeat", help="Exit 0 if the app is alive. Used by the health check.")

    check = sub.add_parser(
        "check",
        help="Fetch one search once and print what came back. Use this to prove the "
        "connection works before setting anything up.",
    )
    check.add_argument(
        "--url", required=True, help="A Vinted search URL, copied from your browser."
    )

    watch = sub.add_parser("watch", help="Add a search.")
    watch.add_argument("url", help="A Vinted search URL, copied from your browser.")
    watch.add_argument("--name", default="", help="What to call it.")
    watch.add_argument(
        "--every", type=int, default=0, help="Seconds between checks (default from settings)."
    )
    watch.add_argument(
        "--max-price",
        default="",
        help="Skip anything above this, buyer protection included.",
    )
    watch.add_argument("--min-price", default="", help="Skip anything below this total.")
    watch.add_argument("--exclude", default="", help="Comma-separated words to skip in titles.")
    watch.add_argument(
        "--include",
        default="",
        help="Comma-separated words the title must all contain; 'a|b' accepts either.",
    )
    watch.add_argument("--regex", default="", help="A regular expression the title must match.")
    watch.add_argument("--min-rating", default="", help="Minimum seller rating, 0 to 5 stars.")
    watch.add_argument("--min-reviews", default="", help="Minimum number of seller reviews.")
    watch.add_argument(
        "--skip-unrated", action="store_true", help="Skip sellers with no reviews yet."
    )
    watch.add_argument(
        "--countries", default="", help="Only sellers in these countries, e.g. FR,BE."
    )
    watch.add_argument(
        "--deal", default="", help="Only alert at least this many percent under typical."
    )
    watch.add_argument(
        "--max-age",
        default="",
        help="Ignore listings the app can tell were on Vinted longer ago than this many minutes.",
    )
    watch.add_argument("--quiet", default="", help="Quiet hours, e.g. 23:00-07:00.")
    watch.add_argument(
        "--quiet-mode",
        default="hold",
        choices=validation.QUIET_MODES,
        help="During quiet hours: hold alerts until the end, drop them, or send silently.",
    )
    watch.add_argument(
        "--also-on", default="", help="Run the same search on other sites too, e.g. de,be."
    )
    watch.add_argument("--color", default="", help="A colour for this search, e.g. #007782.")
    watch.add_argument("--notes", default="", help="A note for yourself.")
    watch.add_argument("--tags", default="", help="Comma-separated tags.")
    watch.add_argument(
        "--to",
        default="",
        help="Comma-separated destination ids to notify. Without it, every active "
        "destination, including ones added later.",
    )

    sub.add_parser("searches", help="List saved searches.")

    unwatch = sub.add_parser("unwatch", help="Remove a search.")
    unwatch.add_argument("query_id", type=int)

    destination = sub.add_parser("destination", help="Add somewhere to send notifications.")
    destination.add_argument("kind", choices=["discord", "telegram", "webhook", "ntfy"])
    destination.add_argument(
        "target", help="Webhook URL, Telegram chat id, ntfy topic, or endpoint URL."
    )
    destination.add_argument("--name", default="", help="What to call it.")
    destination.add_argument(
        "--status", action="store_true", help="Also send health warnings here."
    )

    sub.add_parser("destinations", help="List destinations.")

    export = sub.add_parser("export", help="Write found listings as CSV or JSON.")
    export.add_argument("--format", choices=["csv", "json"], default="csv")
    export.add_argument("--search", type=int, default=None, help="Only this search's finds.")
    export.add_argument(
        "--output", default="-", help="File to write to. Defaults to standard output."
    )

    pair = sub.add_parser(
        "pair-telegram",
        help="Print a link that connects a Telegram chat without hunting for its chat id.",
    )
    pair.add_argument("--name", default="Telegram", help="What to call the destination.")
    pair.add_argument("--bot-username", default="", help="Your bot's @username, without the @.")

    return parser


# --- Commands ----------------------------------------------------------------------


async def _cmd_migrate(settings: Settings) -> int:
    async with Database(settings.db_path) as db:
        applied = await apply_pending(db)
    print(f"Database ready at {settings.db_path} ({applied} migration(s) applied).")
    return 0


async def _cmd_check(settings: Settings, url: str) -> int:
    try:
        normalised = urls.normalise_search_url(url)
        tld = urls.extract_tld(normalised)
        params = urls.parse_search_params(normalised)
    except urls.InvalidSearchURLError as exc:
        print(f"That URL will not work: {exc}", file=sys.stderr)
        return 2

    print(f"Site:   vinted.{tld}")
    print(f"Search: {normalised}")
    print(f"Params: {params}\n")

    async with Database(settings.db_path) as db:
        await apply_pending(db)
        async with TransportSession.build(
            impersonate=settings.http_impersonate,
            timeout=settings.request_timeout_s,
            mock_dir=settings.mock_scenario_dir if settings.fetch_mode == "mock" else None,
        ) as transport:
            sessions = SessionManager(
                db, transport, rotate_after_minutes=settings.session_rotate_minutes
            )
            client = VintedClient(transport, sessions)

            try:
                items = await client.search(tld, params)
            except BlockedError as exc:
                print(f"Blocked: {exc}\n", file=sys.stderr)
                print(
                    "This usually means the address you are connecting from is being "
                    "challenged rather than anything about your search. Confirm it with:\n"
                    f"  curl -v -c - -L https://www.vinted.{tld}/ 2>&1 | grep access_token_web\n"
                    f"If that prints nothing, see {TROUBLESHOOTING}",
                    file=sys.stderr,
                )
                return 1
            except VintedError as exc:
                print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
                return 1

    if not items:
        print("Connected fine, but the search returned no listings.")
        print("Try a broader search to confirm everything works.")
        return 0

    print(f"Got {len(items)} listing(s). The newest few:\n")
    for item in items[:5]:
        listed = item.listed_at.strftime("%Y-%m-%d %H:%M UTC") if item.listed_at else "unknown"
        details = " · ".join(filter(None, [item.brand, item.size, item.condition]))
        print(f"  {item.title}")
        print(f"    {item.price_line()}")
        if details:
            print(f"    {details}")
        print(f"    listed {listed}")
        print(f"    {item.url}\n")
    return 0


def _watch_filters(args: argparse.Namespace, tld: str) -> dict[str, Any]:
    """Turn `watch` options into search fields, refusing anything that will not work."""
    quiet_start = quiet_end = None
    if args.quiet.strip():
        start, separator, end = args.quiet.partition("-")
        if not separator:
            raise validation.InvalidInputError("quiet", "Write quiet hours like 23:00-07:00.")
        quiet_start, quiet_end = start, end
    return {
        "max_total_price": validation.parse_price(args.max_price, field="max_price"),
        "min_total_price": validation.parse_price(args.min_price, field="min_price"),
        "banned_keywords": validation.parse_words(args.exclude, field="exclude"),
        "include_terms": validation.parse_words(args.include, field="include"),
        "regex": validation.parse_regex(args.regex),
        "seller_min_rating": validation.parse_rating(args.min_rating),
        "seller_min_reviews": validation.parse_count(args.min_reviews, field="min_reviews"),
        "skip_unrated_sellers": args.skip_unrated,
        "countries": validation.parse_countries(args.countries) or None,
        "deal_only_pct": validation.parse_percent(args.deal, field="deal"),
        "max_age_min": validation.parse_minutes(args.max_age, field="max_age"),
        "quiet_start": quiet_start,
        "quiet_end": quiet_end,
        "quiet_mode": args.quiet_mode,
        "extra_tlds": validation.parse_tlds(args.also_on, primary=tld),
        "notes": validation.parse_notes(args.notes),
        "tags": validation.parse_words(args.tags, field="tags"),
        **({"color": validation.parse_color(args.color)} if args.color.strip() else {}),
    }


def _destination_ids(text: str) -> list[int]:
    try:
        return [int(part) for part in text.split(",") if part.strip()]
    except ValueError as exc:
        raise validation.InvalidInputError(
            "to", "--to takes destination ids, like --to 1,2."
        ) from exc


async def _cmd_watch(settings: Settings, args: argparse.Namespace) -> int:
    try:
        normalised = urls.normalise_search_url(args.url)
        tld = urls.extract_tld(normalised)
        params = urls.parse_search_params(normalised)
    except urls.InvalidSearchURLError as exc:
        print(f"That URL will not work: {exc}", file=sys.stderr)
        return 2

    try:
        fields = _watch_filters(args, tld)
        destination_ids = _destination_ids(args.to)
        interval = validation.parse_interval(
            args.every or None, default=settings.poll_default_interval_s
        )
        name = validation.parse_name(
            args.name, fallback=validation.default_search_name(params, tld)
        )
    except validation.InvalidInputError as exc:
        print(exc.message, file=sys.stderr)
        return 2

    async with Database(settings.db_path) as db:
        await apply_pending(db)
        repo = Repo(db)

        if await repo.find_query_by_url(normalised) is not None:
            print("That search is already being watched.", file=sys.stderr)
            return 1

        known = {destination.id for destination in await repo.list_destinations()}
        if unknown := [i for i in destination_ids if i not in known]:
            print(f"No destination with id {unknown[0]}.", file=sys.stderr)
            return 2

        try:
            query_id = await repo.add_query(
                name=name,
                url=normalised,
                tld=tld,
                params=params,
                poll_interval_s=interval,
                **fields,
            )
        except validation.InvalidInputError as exc:
            print(exc.message, file=sys.stderr)
            return 2
        for destination_id in destination_ids:
            await repo.route(query_id, destination_id)
        everywhere = await repo.destination_ids_for_query(query_id)

    sites = ", ".join(f"vinted.{site}" for site in [tld, *fields["extra_tlds"]])
    print(f"Watching “{name}” (id {query_id}).")
    print(f"Checking {sites} every {interval}s.")
    if not everywhere:
        print("\nNo destinations yet — add one with: vinted-sniper destination discord <url>")
        print("New destinations receive this search's alerts automatically.")
    return 0


async def _cmd_export(settings: Settings, args: argparse.Namespace) -> int:
    async with Database(settings.db_path) as db:
        await apply_pending(db)
        entries = await Repo(db).all_found(query_id=args.search)
    rendered = exporter.render(entries, args.format)
    if args.output == "-":
        sys.stdout.write(rendered)
    else:
        await asyncio.to_thread(Path(args.output).write_text, rendered, encoding="utf-8")
        print(f"Wrote {len(entries)} listing(s) to {args.output}.", file=sys.stderr)
    return 0


async def _cmd_searches(settings: Settings) -> int:
    async with Database(settings.db_path) as db:
        await apply_pending(db)
        queries = await Repo(db).list_queries()
    if not queries:
        print("No searches yet.")
        return 0
    for query in queries:
        flags = " (paused)" if query.paused else ""
        limit = f", max {query.max_total_price}" if query.max_total_price else ""
        print(
            f"{query.id}: {query.name}{flags} — vinted.{query.tld}, "
            f"every {query.poll_interval_s}s{limit}"
        )
        print(f"    {query.url}")
    return 0


async def _cmd_unwatch(settings: Settings, query_id: int) -> int:
    async with Database(settings.db_path) as db:
        await apply_pending(db)
        repo = Repo(db)
        if await repo.get_query(query_id) is None:
            print(f"No search with id {query_id}.", file=sys.stderr)
            return 1
        await repo.delete_query(query_id)
    print(f"Removed search {query_id}.")
    return 0


async def _cmd_destination(settings: Settings, args: argparse.Namespace) -> int:
    config: dict[str, str]
    match args.kind:
        case "discord":
            config = {"webhook_url": args.target}
        case "telegram":
            config = {"chat_id": args.target}
        case "webhook":
            config = {"url": args.target}
        case _:
            config = {"topic": args.target}

    async with Database(settings.db_path) as db:
        await apply_pending(db)
        destination_id = await Repo(db).add_destination(
            kind=args.kind,
            name=args.name.strip() or args.kind,
            config=config,
            notify_status=args.status,
        )
    print(f"Added {args.kind} destination (id {destination_id}).")
    print("Route a search to it with: vinted-sniper watch <url> --to " + str(destination_id))
    return 0


async def _cmd_destinations(settings: Settings) -> int:
    async with Database(settings.db_path) as db:
        await apply_pending(db)
        destinations = await Repo(db).list_destinations()
    if not destinations:
        print("No destinations yet.")
        return 0
    for destination in destinations:
        state = "active" if destination.active else "disabled"
        print(f"{destination.id}: {destination.name} ({destination.kind}, {state})")
    return 0


async def _cmd_pair_telegram(settings: Settings, args: argparse.Namespace) -> int:
    if settings.telegram_bot_token is None:
        print(
            "Set VINTED_SNIPER_TELEGRAM_BOT_TOKEN first. Talk to @BotFather on Telegram to "
            "create a bot and get one.",
            file=sys.stderr,
        )
        return 2

    from vinted_sniper.botctl.telegram_bot import create_pairing  # noqa: PLC0415

    async with Database(settings.db_path) as db:
        await apply_pending(db)
        _, code = await create_pairing(Repo(db), args.name)

    username = args.bot_username.lstrip("@")
    print("Open this link in Telegram, in the chat or group you want alerts in:\n")
    if username:
        print(f"  https://t.me/{username}?start={code}\n")
    else:
        print(f"  https://t.me/<your bot's username>?start={code}\n")
        print("Pass --bot-username to have that filled in for you.\n")
    print("The app must be running for the link to work. It expires in 30 minutes.")
    return 0


async def _cmd_status(settings: Settings) -> int:
    async with Database(settings.db_path) as db:
        await apply_pending(db)
        snapshot = await health.snapshot(Repo(db))

    print("Running." if snapshot.alive else "Not running (or the heartbeat is stale).")
    if not snapshot.searches:
        print("No searches set up yet.")
        return 0

    now = int(time.time())
    for search in snapshot.searches:
        last = f"{now - search.last_success_at}s ago" if search.last_success_at else "never"
        print(f"\n{search.name} [{search.state}] — vinted.{search.tld}")
        print(f"  last successful check: {last}")
        if search.newest_listing_at:
            print(f"  newest listing seen:   {now - search.newest_listing_at}s ago")
        if search.blocks or search.rate_limits:
            print(f"  blocked {search.blocks} times, rate limited {search.rate_limits} times")
        if search.last_error:
            print(f"  last error: {search.last_error}")
    if snapshot.queued_notifications:
        print(f"\n{snapshot.queued_notifications} notification(s) waiting to send.")
    return 0


async def _cmd_heartbeat(settings: Settings) -> int:
    async with Database(settings.db_path) as db:
        return 0 if await health.is_alive(Repo(db)) else 1


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    log.configure(level=settings.log_level, fmt=settings.log_format)

    match args.command:
        case "run":
            await app.run(settings, open_browser=args.open)
            return 0
        case "migrate":
            return await _cmd_migrate(settings)
        case "check":
            return await _cmd_check(settings, args.url)
        case "watch":
            return await _cmd_watch(settings, args)
        case "searches":
            return await _cmd_searches(settings)
        case "unwatch":
            return await _cmd_unwatch(settings, args.query_id)
        case "destination":
            return await _cmd_destination(settings, args)
        case "destinations":
            return await _cmd_destinations(settings)
        case "export":
            return await _cmd_export(settings, args)
        case "pair-telegram":
            return await _cmd_pair_telegram(settings, args)
        case "status":
            return await _cmd_status(settings)
        case "heartbeat":
            return await _cmd_heartbeat(settings)
        case unknown:
            raise AssertionError(f"unhandled command {unknown!r}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
