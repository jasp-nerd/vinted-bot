# How it works

One process, one event loop, one SQLite file. There is no queue server, no second database
and no worker fleet, because a tool watching a handful of searches does not need any of that
and every extra moving part is another thing that can be broken at three in the morning.

```
                    ┌─ poller ─┐  one task per search, one or more country sites each
   Vinted ◀── HTTP ─┤ poller   │  fetch → decide what is new → filter → judge the price
                    └─ poller ─┘
                          │  one transaction: listings, verdicts, skipped reasons, outbox
                          ▼
                    ┌──────────┐
                    │  SQLite  │  searches, listings, query_items, rejections, outbox,
                    └──────────┘  watches, sessions, settings
                          │  claim in order, one worker per destination
                          ▼
                  dispatcher ──▶ Discord · Telegram · ntfy · Apprise · webhook

   watcher     re-reads watched listings and sellers on a slow shared budget
   watchdog    reads state across searches, spots a frozen catalog
   heartbeat   writes a timestamp the health check reads, pings an uptime URL if set
   web         the dashboard over the same database, on by default
   bot         optional Telegram commands for the paired chat
```

## The parts

**`vinted/`** is everything that touches Vinted. Since September 2026 a search goes to
`svc-catalogue` on the site's `api.` host (`api.vinted.fr/svc-catalogue/items`), with the
`Locale` and `X-Anon-Id` headers that pick the market. `transport.py` defines a small
protocol so the HTTP client is a swappable detail: plain httpx by default, curl_cffi with a
browser TLS fingerprint if you turn it on, or a replay-from-disk transport for tests and
offline development. `session.py` gets an anonymous session by loading the homepage the way
a browser would, one site at a time, keeps each session's cookies to itself, stores it so a
restart does not need a new handshake, and replaces it on a timer. `client.py` holds every
call: the search, a member's public profile (country, rating), a member's wardrobe, a
listing's public page (read by `item_page.py`, because the JSON item endpoints refuse
anything that is not a real browser), and the reachability check behind the dashboard's
diagnosis. It refuses to believe a 200 is what it asked for until it has checked.
`urls.py` turns a pasted address-bar URL (or Vinted's share text) into a canonical form, and
translates the stored filters into the names `svc-catalogue` expects on every request, so a
search saved before the rename still works and the next rename is one table.
`taxonomy.py` feeds the dashboard's search builder: the category tree comes out of the search
page's HTML and is cached for a week; filter options and brand search come live from
`svc-filters`. `canary.py` is the weekly live check that CI runs.

**`engine/`** decides what to do with the results. `dedup.py` works out what is genuinely
new, `filters.py` applies your rules and says why it skipped anything, `poller.py` runs the
loop for one search and maps failures to actions, `quiet.py` knows when a search should not
wake anyone, `watcher.py` runs item and seller watches, `watchdog.py` compares searches
against each other, `health.py` assembles the status view, `updates.py` notices a newer
release once a day, and `validation.py` turns what someone typed into values a search can
hold. The dashboard, the CLI and the Telegram bot all go through `validation.py`, and the
repository runs it again before writing, so a bad search cannot be stored whichever way it
arrives.

**`deliver/`** gets notifications out. `render.py` decides once how a listing reads (total
price first, the deal badge, stars, absolute links) in the language of the listing's site,
from the small table in `labels.py`, and each channel module only lays the result out.
`dispatcher.py` runs one worker per destination, claiming work from the outbox in order
through a token bucket in `ratelimit.py`. `preview.py` sends a made-up listing through a
destination's real sender for the dashboard's test button, or returns what would be sent
without sending it.

**`botctl/`** is the Telegram bot: pairing a chat through a one-time link, then `/list`,
`/pause`, `/resume`, `/add`, `/remove` and `/status` from that chat. Only paired chats get an
answer.

**`web/`** is the dashboard: FastAPI with server-rendered templates, a little JavaScript for
the live feed, and nothing that needs a build step. It reads and writes through the same
repository as everything else, so a search added there is picked up by the supervisor in
`app.py` without a restart.

**`db/`** holds every SQL statement in `repo.py`, so a schema change has one place to look.
`migrations.py` applies the numbered files in `db/migrations/` at startup, each in one
transaction with foreign keys checked before it commits, so a failed upgrade leaves the
database at the last version that fully applied. `export.py` writes found listings as CSV or
JSON for both `vinted-sniper export` and the dashboard's download button.

Process settings (where the database lives, intervals, the dashboard password) come from
the environment through `config.py`. Everything a person owns lives in the database:
searches, destinations, routes, watches, the seller blocklist, and the handful of settings
the dashboard changes (`timezone`, `healthcheck_url`, `update_check`, `theme`, whether
setup has run), which sit as keys in `app_state`. There is never a question of which copy of
a setting wins.

## Three decisions worth explaining

### Anonymous only

Vinted hands a session cookie to anyone who loads the site, and that cookie is all the
catalog needs. Logging in would unlock more, including buying, and would mean storing
someone's credentials, and would put a real account at risk of the restrictions Vinted has
been applying to suspected automation. Reading public pages as a logged-out visitor is both
safer and simpler, and it makes "we cannot buy for you" an honest statement rather than a
missing feature.

### Errors are not interchangeable

The single most common way tools in this space dig their own grave is retrying uniformly.
Each failure means something different:

| What happened | What it means | What we do |
|---|---|---|
| 401 | The anonymous token aged out | Get a new one and retry, quickly |
| 403 | This client is being refused | Back off hard, start a new session |
| 429 | Too fast | Wait exactly as long as we were told |
| 200 with the wrong shape | Something changed, or we got an interstitial | Log it loudly, do not retry, do not notify |
| Network error | Transient | Short backoff |

Retrying a 403 the way you would retry a timeout is how a temporary block becomes a long one.
A search that runs on several country sites fetches each in turn and judges the combined
results; if any site fails, the whole check counts as failed and backs off, and the listings
the other sites returned are still there next time.

### Notifications are written before they are sent

Finding a listing and queueing its notifications happens in one transaction. Nothing is
marked as sent until the far end has accepted it, and a process killed mid-send returns its
claimed rows to the queue at startup. The alternative, sending as you go, loses alerts on a
crash or sends them twice, and both happen often enough to matter on a machine that reboots.
A unique index on the outbox means one listing reaches each destination once, however many
searches matched it.

This is also where rate limits are respected. One worker per destination, sending one thing
at a time, in the order things were found. It is slower than firing everything at once, which
is the point: platforms remember who floods them. Quiet hours work here too: a held alert is
queued with a time before which it may not be claimed.

## Deciding what is new

Vinted's catalog stopped saying when a listing's photo was taken in September 2026, so "new"
rests on the listing id, which Vinted hands out in upload order across the whole platform.
Three gates:

1. **What this search has already judged.** Every listing a search has looked at gets a row
   in `query_items`: seeded (on the page at the first check), matched, or rejected. Per
   search rather than global: a listing another search found is still news to this one's
   destinations, and the outbox's once-per-destination rule stops anyone hearing it twice.
2. **A floor.** When the first page was full, anything below its lowest id was off the bottom
   of it, so if it appears later it is old stock pulled up by a deletion, not a new upload. A
   listing that turns up late but inside the range already watched is still announced;
   dropping those forever was the flaw of the old timestamp high-water mark.
3. **A freshness window**, when a listing does carry a photo time, so a restart or a slow
   first check cannot replay yesterday.

A search's first check is a special case: it records everything it finds as seeded and tells
you about none of it, unless you set `FIRST_RUN_MODE=newest`, which sends exactly one so you
can confirm delivery works.

## Deciding what is worth sending

The filters come in three tiers, by what they cost:

1. **The listing alone:** words that must or must not appear (whole words, ignoring accents
   and case), a title pattern, the total price with buyer protection, condition, the seller
   blocklist.
2. **The seller's public profile:** country, rating and number of reviews. That is a request,
   so it only runs for searches that ask for it and only for listings that passed everything
   cheaper, and each profile is cached for a week.
3. **The typical price:** a rolling median of what this search's matches cost. Deal-only
   searches record every match, which is how the median is learned, and only announce the
   ones far enough below it.

Every skipped listing is written to `rejections` with its reason and a sentence, kept for a
week and capped at a couple of thousand rows. That is what the dashboard's "Not sent" list
shows: a search that stays quiet should be able to say why.

## Watches

An item watch re-reads one listing's public page about every half hour and speaks up when the
price drops, or the listing is reserved, sold or removed. A seller watch reads a member's
wardrobe about every quarter of an hour and announces new uploads. Both share one small
budget of a few requests a minute across all watches, so they never become a second source
of blocks. Their alerts go through the same outbox as everything else.

## Testing

`tests/unit` covers the decisions: URL normalisation, filters, dedup, message building,
pacing. `tests/integration` runs the real poller, dispatcher and database against a scripted
transport, and covers the cases that decide whether this survives a week alone: empty
results, 403, 429, an expired token, a response that is not a catalog, a crash mid-delivery,
and a restart not resending anything.

Nothing in the suite reaches the network. A separate weekly job makes a few real requests
against the live site: that a filter still narrows the results, that the fields the app
shows are still there, and that the profile and listing page reads still parse. If Vinted
changes something, we hear about it from CI rather than from an issue.

Run it offline the way the tests do:

```bash
VINTED_SNIPER_FETCH_MODE=mock VINTED_SNIPER_MOCK_SCENARIO_DIR=./scenario uv run vinted-sniper run
```

A scenario directory holds `root.json` and `catalog.json` describing responses. Either can be
a list, in which case successive calls walk through it, which is how the failure drills work.
