"""Command line entry points."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import os
import sqlite3
import subprocess
import sys
import time
import traceback
import webbrowser
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

import httpx
import segno
from pydantic import ValidationError

from vinted_bot import __version__, app, config, control, instance, log, managed, network, shortcuts
from vinted_bot.config import Settings, in_container
from vinted_bot.db import Database, apply_pending
from vinted_bot.db import export as exporter
from vinted_bot.db.repo import DuplicateSearchError, Repo
from vinted_bot.engine import health, self_update, validation
from vinted_bot.vinted import urls
from vinted_bot.vinted.client import VintedClient
from vinted_bot.vinted.errors import BlockedError, VintedError
from vinted_bot.vinted.proxies import ProxyRotation
from vinted_bot.vinted.session import SessionManager
from vinted_bot.vinted.transport import TransportSession
from vinted_bot.web import destinations as web_destinations

_log = log.get_logger(__name__)

TROUBLESHOOTING = "https://github.com/jasp-nerd/vinted-bot/blob/main/docs/troubleshooting.md"


class _Version(argparse.Action):
    """`--version`, plus a line when a newer release is out and how to get it.

    The line is what tells a script or an AI agent looking after the app that it is behind;
    without a database to read (not set up yet), the version alone is printed.
    """

    def __call__(self, parser: argparse.ArgumentParser, *_: Any, **__: Any) -> None:
        print(f"vinted-bot {__version__}")
        with contextlib.suppress(ValidationError, OSError, sqlite3.Error):
            settings = Settings()
            if settings.db_path.exists():
                facts = asyncio.run(_update_facts(settings))
                if facts["update_available"]:
                    print(f"Version {facts['latest_version']} is out. {facts['how_to_update']}")
        parser.exit()


async def _update_facts(settings: Settings) -> dict[str, Any]:
    async with Database(settings.db_path) as db:
        return await self_update.update_facts(Repo(db), _install(settings), settings)


def _install(settings: Settings) -> self_update.Install:
    """How this copy was installed, as the running service sees it: typed in a terminal,
    VINTED_BOT_SUPERVISED isn't set, but the installer's service still restarts it."""
    install = self_update.detect(settings)
    if install.supervisor is None and (service := control.installed_service(settings)):
        return dataclasses.replace(install, supervisor=service.value)
    return install


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vinted-bot",
        description="Watch Vinted searches and get notified when something matches.",
    )
    parser.add_argument(
        "--version",
        action=_Version,
        nargs=0,
        help="Print the version, and whether a newer one is out, then exit.",
    )
    # No command at all opens the dashboard, starting vinted-bot first if needed: the one
    # thing someone typing `vinted-bot` after closing the browser tab wants.
    parser.set_defaults(no_browser=False, gui=False, windowless=False)
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.default = "open"

    _control_parsers(sub)

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
        help="Comma-separated words the title must all contain; 'a|b' accepts either. "
        'A word matches longer words starting with it (jean finds jeans); "jean" in '
        "double quotes means that exact word.",
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

    _destination_parser(sub)

    sub.add_parser("destinations", help="List destinations.")

    backup = sub.add_parser(
        "backup",
        help="Copy the database to a file, safely, even while the app is running.",
    )
    backup.add_argument("file", help="Where to write the copy, such as vinted-bot-backup.db.")

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

    sub.add_parser(
        "reset-password",
        help="Give the dashboard a new password and print it, for when the old one is lost.",
    )

    return parser


def _control_parsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Opening, starting and stopping, and where to find the dashboard."""
    opener = sub.add_parser(
        "open",
        help="Open the dashboard, starting vinted-bot first if it isn't running. What "
        "`vinted-bot` on its own does, and what the app icon runs.",
    )
    opener.add_argument(
        "--no-browser", action="store_true", help="Print the address instead of opening it."
    )
    opener.add_argument("--gui", action="store_true", help=argparse.SUPPRESS)
    starter = sub.add_parser(
        "start", help="Start vinted-bot in the background if it isn't running."
    )
    # What the Windows Startup shortcut runs: see control.start_at_login.
    starter.add_argument("--login", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser(
        "stop", help="Stop vinted-bot. It stays stopped, even at the next login, until started."
    )
    sub.add_parser("restart", help="Stop vinted-bot and start it again.")
    logs = sub.add_parser("logs", help="Show the end of vinted-bot's log.")
    logs.add_argument("-n", "--lines", type=int, default=40, help="How many lines (default 40).")
    logs.add_argument("-f", "--follow", action="store_true", help="Keep showing new lines.")
    shortcuts_ = sub.add_parser(
        "shortcuts",
        help="Make the vinted-bot icon in Applications, the Start menu or the apps menu "
        "(the installers do this).",
    )
    shortcuts_.add_argument("--remove", action="store_true", help="Take the icon away again.")
    address = sub.add_parser(
        "address",
        help="Show where to open the dashboard, with a QR code for your phone when other "
        "devices on your network may connect.",
    )
    address.add_argument(
        "--allow-network",
        action="store_true",
        help="Let other devices on your network open the dashboard (sets a password if "
        "there is none, and prints it).",
    )


def _destination_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    destination = sub.add_parser("destination", help="Add somewhere to send notifications.")
    destination.add_argument("kind", choices=["telegram", "discord", "ntfy", "webhook", "apprise"])
    destination.add_argument(
        "target",
        help="Telegram chat id, Discord webhook link, ntfy topic or topic URL, your "
        "endpoint's URL, or an Apprise address (as Apprise writes it).",
    )
    destination.add_argument("--name", default="", help="What to call it.")
    destination.add_argument(
        "--status",
        action="store_true",
        default=None,
        help="Also send status notices here (stale searches, a site that keeps failing, "
        "updates). The first destination gets them without asking.",
    )


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
        # Through a proxy from VINTED_BOT_PROXY_FILE if there is one, like a search: a
        # check that goes out directly proves nothing about how the app connects.
        async with TransportSession.build(
            impersonate=settings.http_impersonate,
            timeout=settings.request_timeout_s,
            proxy=ProxyRotation.from_file(settings.proxy_file).acquire(),
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
        except DuplicateSearchError as exc:
            print(f"{exc.message} It is search {exc.existing.id}.", file=sys.stderr)
            return 1
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
        print("\nNo destinations yet — add one with: vinted-bot destination discord <url>")
        print("New destinations receive this search's alerts automatically.")
    return 0


async def _cmd_export(settings: Settings, args: argparse.Namespace) -> int:
    async with Database(settings.db_path) as db:
        await apply_pending(db)
        entries = await Repo(db).all_found(query_id=args.search)
    rendered = exporter.render(entries, args.format)
    if args.output == "-":
        sys.stdout.write(rendered)
        # Flushed here, so a reader that went away is a BrokenPipeError main() can handle,
        # not one at interpreter exit, which nothing can.
        sys.stdout.flush()
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
        sites = ", ".join(f"vinted.{site}" for site in query.sites)
        print(f"{query.id}: {query.name}{flags} — {sites}, every {query.poll_interval_s}s{limit}")
        print(f"    {query.url}")
        if query.include_terms:
            print(f"    must include: {', '.join(query.include_terms)}")
        if query.banned_keywords:
            print(f"    leaves out: {', '.join(query.banned_keywords)}")
        if query.countries:
            print(f"    sellers in: {', '.join(query.countries)}")
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


def _destination_config(kind: str, target: str) -> dict[str, Any]:
    """What a destination stores, checked the way the dashboard checks it."""
    match kind:
        case "discord":
            return {"url": web_destinations.discord_url(target)}
        case "telegram":
            if not target.strip().lstrip("-").isdigit():
                raise validation.InvalidInputError(
                    "target",
                    "A Telegram chat id is a number, like 123456789 or -1001234567890. "
                    "Or skip it: vinted-bot pair-telegram prints a link that connects a chat.",
                )
            return {"chat_id": target.strip()}
        case "ntfy":
            return web_destinations.ntfy_config(target)
        case "webhook":
            if not target.strip().startswith(("https://", "http://")):
                raise validation.InvalidInputError(
                    "target", "The address must start with https://."
                )
            return {"url": target.strip()}
        case _:
            return {"urls": [target.strip()]}


async def _cmd_destination(settings: Settings, args: argparse.Namespace) -> int:
    try:
        config = _destination_config(args.kind, args.target)
        async with httpx.AsyncClient(timeout=settings.request_timeout_s) as http:
            web_destinations.check(args.kind, config, http)
    except validation.InvalidInputError as exc:
        print(exc.message, file=sys.stderr)
        return 2

    async with Database(settings.db_path) as db:
        await apply_pending(db)
        destination_id = await Repo(db).add_destination(
            kind=args.kind,
            name=args.name.strip() or args.kind,
            config=config,
            notify_status=args.status,
        )
    print(f"Added {args.kind} destination (id {destination_id}).")
    print("Route a search to it with: vinted-bot watch <url> --to " + str(destination_id))
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
    from vinted_bot.botctl.telegram_bot import create_pairing  # noqa: PLC0415

    async with Database(settings.db_path) as db:
        await apply_pending(db)
        repo = Repo(db)
        if await managed.telegram_token(settings, repo) is None:
            print(
                "Add your bot's token first: in the dashboard, Alerts, Add a place, Telegram "
                "(or set VINTED_BOT_TELEGRAM_BOT_TOKEN). Talk to @BotFather on Telegram to "
                "create a bot and get one.",
                file=sys.stderr,
            )
            return 2
        _, code = await create_pairing(repo, args.name)

    username = args.bot_username.lstrip("@")
    print("Open this link in Telegram, in the chat or group you want alerts in:\n")
    if username:
        print(f"  https://t.me/{username}?start={code}\n")
    else:
        print(f"  https://t.me/<your bot's username>?start={code}\n")
        print("Pass --bot-username to have that filled in for you.\n")
    print("The app must be running for the link to work. It expires in 30 minutes.")
    return 0


async def _cmd_reset_password(settings: Settings) -> int:
    """A new dashboard password, printed once, every browser signed out.

    A new password rather than none: phone access may be on, and the dashboard must never
    be open to the network without one. Takes effect in a running app at once, since the
    dashboard reads its password on every request.
    """
    from vinted_bot.web import security  # noqa: PLC0415 - loads FastAPI, which most commands skip

    if security.password_from_env(settings):
        print(
            "The dashboard's password is VINTED_BOT_WEB_AUTH_TOKEN, set in this copy's "
            "environment or .env file. Look it up or change it there, then restart.",
            file=sys.stderr,
        )
        return 2
    password = security.suggest_password()
    async with Database(settings.db_path) as db:
        await apply_pending(db)
        await security.set_password(Repo(db), password)
    print(f"The dashboard's new password is:\n\n  {password}\n")
    print("Every browser and phone has been signed out and asks for it once.")
    print("Change it to one of your own in Settings, Password.")
    return 0


async def _cmd_status(settings: Settings) -> int:
    async with Database(settings.db_path) as db:
        await apply_pending(db)
        snapshot = await health.snapshot(Repo(db))
        facts = await self_update.update_facts(Repo(db), _install(settings), settings)

    print("Running." if snapshot.alive else "Not running (or the heartbeat is stale).")
    version = f"Version {__version__}."
    if facts["update_available"]:
        version += f" Version {facts['latest_version']} is out. {facts['how_to_update']}"
    print(version)
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


async def _cmd_backup(settings: Settings, target: str) -> int:
    """A consistent copy of the database, taken through SQLite's own backup.

    Copying app.db by hand while the app runs copies a file whose recent changes still
    sit in app.db-wal beside it, which is how a documented backup came out empty.
    """
    path = Path(target)
    if await asyncio.to_thread(path.exists):
        print(f"{target} already exists; pick a new file name.", file=sys.stderr)
        return 2
    if not await asyncio.to_thread(settings.db_path.exists):
        print(f"There is no database at {settings.db_path} yet.", file=sys.stderr)
        return 1
    async with Database(settings.db_path) as db:
        try:
            await db.backup_to(path)
        except sqlite3.OperationalError as exc:
            print(
                f"Couldn't write the backup to {target} ({exc}). Pick a folder you can write "
                "to, such as your home folder.",
                file=sys.stderr,
            )
            return 1
    print(f"Backed up {settings.db_path} to {target}.")
    return 0


# --- Opening, starting and stopping ---------------------------------------------------

_DOCKER = {
    "open": "Inside a container: open http://<this computer's address>:8000 in a browser.",
    "start": "In Docker, start it with: docker compose up -d",
    "stop": "In Docker, stop it with: docker compose stop",
    "restart": "In Docker, restart it with: docker compose restart",
    "logs": "In Docker, see the log with: docker compose logs -f",
}


def _cmd_control(settings: Settings, args: argparse.Namespace) -> int:
    command: str = args.command
    if in_container() and command != "logs":
        print(_DOCKER[command])
        return 0 if command == "open" else 2
    try:
        match command:
            case "open":
                return _open(settings, browser=not args.no_browser, gui=args.gui)
            case "start" if args.login:
                control.start_at_login(settings)
            case "start":
                running = control.start(settings)
                print(f"vinted-bot is running. Dashboard: {running.url}")
            case "stop":
                if control.stop(settings):
                    print("vinted-bot has stopped. No alerts until you start it again.")
                else:
                    print("vinted-bot wasn't running.")
                print("Start it again with: vinted-bot")
            case "restart":
                control.stop(settings)
                running = control.start(settings)
                print(f"vinted-bot is running again. Dashboard: {running.url}")
            case _:
                return _logs(settings, lines=args.lines, follow=args.follow)
    except control.ControlError as exc:
        print(str(exc), file=sys.stderr)
        if args.windowless:
            control.show_message(str(exc))
        return 1
    return 0


def _open(settings: Settings, *, browser: bool, gui: bool) -> int:
    """The dashboard, starting vinted-bot first if needed. `gui` is the app icon, which has
    no terminal: problems show as a dialog instead."""
    try:
        was_running = instance.running(settings) is not None
        if not was_running:
            print("Starting vinted-bot…")
            if gui:
                control.notify("Starting vinted-bot…", "Your dashboard opens in a moment.")
        running = control.start(settings)
    except control.ControlError as exc:
        if gui:
            control.show_message(str(exc))
        print(str(exc), file=sys.stderr)
        return 1
    if not settings.web_enabled:
        print("vinted-bot is running. Its dashboard is switched off (VINTED_BOT_WEB_ENABLED).")
        return 0
    if browser and control.can_open_browser():
        webbrowser.open(running.url)
        print(f"Opened the dashboard: {running.url}")
    else:
        print(f"vinted-bot is running. Dashboard: {running.url}")
        if os.environ.get("SSH_CONNECTION"):
            print(
                "On another computer, open it through SSH with:\n"
                f"  ssh -L {running.port}:localhost:{running.port} <you>@<this computer>\n"
                "or let devices on your network open it: vinted-bot address --allow-network"
            )
    if not was_running:
        print(_keeps_running_hint(settings))
    return 0


def _keeps_running_hint(settings: Settings) -> str:
    if control.installed_service(settings):
        return "It keeps running in the background, and starts by itself when you log in."
    return (
        "It keeps running in the background until you stop it (vinted-bot stop) or restart "
        "the computer."
    )


def _logs(settings: Settings, *, lines: int, follow: bool) -> int:
    path = instance.log_file(settings)
    if in_container():
        print(_DOCKER["logs"])
        return 0
    if not path.exists() and control.installed_service(settings) is control.Service.SYSTEMD:
        # The systemd service writes to the journal rather than to a file.
        command = ["journalctl", "--user", "-u", control.SYSTEMD_UNIT, "-n", str(lines)]
        return subprocess.call([*command, "-f"] if follow else command)
    if not path.exists():
        print(
            "There is no log file yet. Started with `vinted-bot run`, vinted-bot writes to "
            "the window it runs in."
        )
        return 0
    with path.open(encoding="utf-8", errors="replace") as handle:
        tail = handle.readlines()[-lines:]
        sys.stdout.writelines(tail)
        sys.stdout.flush()
        while follow:
            line = handle.readline()
            if line:
                sys.stdout.write(line)
                sys.stdout.flush()
            else:
                time.sleep(0.5)
    return 0


async def _cmd_address(settings: Settings, *, allow_network: bool) -> int:
    """Where to open the dashboard: this computer, and other devices when allowed."""
    from vinted_bot.web import security  # noqa: PLC0415 - loads FastAPI, which most commands skip

    local = f"http://localhost:{settings.web_port}"
    if in_container():
        print(
            "In Docker, open it at http://<this computer's address>:<the published port>, "
            "the address you use for anything else on this machine."
        )
        return 0
    async with Database(settings.db_path) as db:
        await apply_pending(db)
        repo = Repo(db)
        if allow_network:
            if managed.web_host_from_env(settings):
                print("VINTED_BOT_WEB_HOST is set, so it decides who can connect. Change it there.")
                return 2
            if not await security.password_required(settings, repo):
                password = security.suggest_password()
                await security.set_password(repo, password)
                print(f"The dashboard now has a password:\n\n  {password}\n")
                print("Write it down. Change it any time in Settings, Password.\n")
            await managed.set_phone_access(repo, True)
        host = await managed.web_host(settings, repo)
    if allow_network and instance.running(settings):
        print("Restarting vinted-bot so other devices can connect…")
        try:
            control.stop(settings)
            control.start(settings)
        except control.ControlError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print(f"On this computer:  {local}")
    if host in {"127.0.0.1", "localhost", "::1"}:
        print(
            "\nOnly this computer can open it. To open it from your phone or another "
            "computer on your Wi-Fi too, run:\n  vinted-bot address --allow-network"
        )
        return 0
    addresses = [f"http://{ip}:{settings.web_port}" for ip in network.lan_addresses()]
    name = network.local_name()
    if name:
        print(f"On your network:   http://{name}:{settings.web_port}")
    for address in addresses:
        print(f"                   {address}")
    if addresses:
        print("\nScan this with your phone's camera (on the same Wi-Fi):\n")
        segno.make(addresses[0]).terminal(compact=True)
    else:
        print("\nThis computer isn't connected to a network a phone could reach.")
    return 0


def _cmd_shortcuts(settings: Settings, *, remove: bool) -> int:
    if in_container():
        print("Inside a container there is no desktop to put an icon on.")
        return 2
    try:
        paths = shortcuts.remove(settings) if remove else shortcuts.make(settings)
    except OSError as exc:
        print(
            f"Couldn't {'remove' if remove else 'make'} the vinted-bot icon: {exc}", file=sys.stderr
        )
        return 1
    for path in paths:
        print(f"{'Removed' if remove else 'Made'} {path}")
    return 0


async def _cmd_heartbeat(settings: Settings) -> int:
    async with Database(settings.db_path) as db:
        return 0 if await health.is_alive(Repo(db)) else 1


async def _run(args: argparse.Namespace) -> int:
    try:
        settings = Settings()
    except ValidationError as exc:
        print(config.explain(exc), file=sys.stderr)
        if args.windowless:
            control.show_message(config.explain(exc))
        return 2
    log.configure(level=settings.log_level, fmt=settings.log_format, timezone=settings.timezone)
    for warning in settings.warnings:
        _log.warning("config.not_used", problem=warning)
    if unknown := Settings.unknown_keys():
        _log.warning(
            "config.unknown_keys",
            keys=unknown,
            hint="no setting has these names, so they do nothing; check for typos or "
            "keys left over from an older version",
        )

    match args.command:
        case "open" | "start" | "stop" | "restart" | "logs":
            return _cmd_control(settings, args)
        case "address":
            return await _cmd_address(settings, allow_network=args.allow_network)
        case "shortcuts":
            return _cmd_shortcuts(settings, remove=args.remove)
        case "run":
            return await app.run(settings, open_browser=args.open)
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
        case "backup":
            return await _cmd_backup(settings, args.file)
        case "export":
            return await _cmd_export(settings, args)
        case "pair-telegram":
            return await _cmd_pair_telegram(settings, args)
        case "reset-password":
            return await _cmd_reset_password(settings)
        case "status":
            return await _cmd_status(settings)
        case "heartbeat":
            return await _cmd_heartbeat(settings)
        case unknown:
            raise AssertionError(f"unhandled command {unknown!r}")


# The Windows icon and Startup shortcut run vinted-bot under pythonw, which has no console.
# What it would print goes to this file instead, in the folder those shortcuts start in
# (the data folder), so a failure there leaves something to read.
WINDOWLESS_LOG = "vinted-bot-icon.log"


def _windowless_output() -> TextIO:
    try:
        return open(WINDOWLESS_LOG, "w", encoding="utf-8")
    except OSError:
        return open(os.devnull, "w", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    windowless = sys.stdout is None or sys.stderr is None
    if windowless:
        output = _windowless_output()
        sys.stdout = sys.stdout or output
        sys.stderr = sys.stderr or output
    args = build_parser().parse_args(argv)
    args.windowless = windowless
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        # The reader went away early, as `vinted-bot export | head` does on purpose. The
        # rest of the output has nowhere to go; point stdout at nothing so the flush at
        # exit does not raise the same error again as a traceback.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 0
    except Exception:
        if not windowless:
            raise
        # Nobody would ever see the traceback: write it down and say where.
        traceback.print_exc()
        sys.stderr.flush()
        control.show_message(
            "vinted-bot ran into a problem and couldn't start. What went wrong is in "
            f"{Path(WINDOWLESS_LOG).resolve()}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
