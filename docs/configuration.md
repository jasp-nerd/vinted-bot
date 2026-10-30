# Configuration

Two kinds of settings, kept apart deliberately.

**Environment variables** control the process: where the database is, how often to check,
how to log. They are read once at startup and are listed below.

**Searches and destinations** live in the database and are managed with the CLI or the
dashboard. There is no config file listing them, so there is nothing to keep in sync and no
question about which copy wins.

## Environment variables

Every variable is prefixed `VINTED_BOT_`. All of them are optional except where noted.
[`.env.example`](../.env.example) has the same list with comments, ready to copy. With
Docker, set them in the `environment:` block of `docker-compose.yml` and run
`docker compose up -d` afterwards.

A `VINTED_` name the app doesn't know, such as a typo or a `VINTED_SNIPER_` line from an
older version, is ignored, and the log lists it at startup. Other programs' variables in a
shared `.env` (`PUID` and the like) are ignored without a word. A value it can't use stops it with a
one-paragraph message naming the setting and what is wrong with it.

Besides the environment, the app reads a file called `.env` **in the folder you start it
from** (the current directory, not the folder the app is installed in). Variables set in
the environment win over the file. So start it from the folder that holds your own `.env`,
and be aware that starting it inside another checkout of this project picks up that
checkout's `.env`, Telegram token and all.

### Storage

| Variable | Default | What it does |
|---|---|---|
| `DB_PATH` | see below | Where the SQLite file lives. Already set to `/data/app.db` in the container. |
| `ITEM_RETENTION_DAYS` | `30` | Delete stored listings older than this. Does not cause anything to be re-sent: what each search and each seller watch has already seen is kept separately, in a much smaller form. |
| `KEEP_RAW_JSON` | `false` | Keep each listing's full API payload. Handy when debugging a parsing problem; stores more seller data than notifications need. |

Unset outside a container, the database goes in `./data/app.db` **if that file already
exists**, so upgrading from 1.x keeps your searches where they are. Otherwise it goes in
your user data folder: `~/.local/share/vinted-bot/app.db` on Linux,
`~/Library/Application Support/vinted-bot/app.db` on macOS,
`%LOCALAPPDATA%\vinted-bot\app.db` on Windows. That way it no longer matters which
folder you start the app from. `vinted-bot migrate` prints the path it used.

### Time

| Variable | Default | What it does |
|---|---|---|
| `TIMEZONE` | this computer's time zone | IANA time zone such as `Europe/Paris`, used for quiet hours, the stats page and the time stamps in the log (with their UTC offset). Falls back to the standard `TZ` variable, then to the computer's own zone (UTC if it can't be told). A `TZ` it can't read, such as the POSIX forms `:/etc/localtime` or `CET-1CEST,M3.5.0,M10.5.0/3`, is logged as a warning and the computer's own zone used instead. The dashboard's settings page can override it. |

### Checking

| Variable | Default | What it does |
|---|---|---|
| `POLL_DEFAULT_INTERVAL_S` | `60` | Seconds between checks for a newly added search. Per-search values override it. Anything under 10 is refused. |
| `FRESHNESS_WINDOW_MIN` | `20` | How old a listing can be and still count as new. Two things use it. A listing the app can tell was already on Vinted longer ago than this is skipped (see below). And when a search has not completed a check for longer than this (or three of its intervals, if that is longer), because the app was off, the computer asleep or Vinted refusing, the first check back records what is there **without announcing it**, then carries on as normal. A search's own "ignore listings older than" setting overrides it. |
| `FIRST_RUN_MODE` | `silent` | What a brand-new search does first time: `silent` notifies nothing, `newest` sends exactly one listing so you can confirm delivery works. |
| `REQUEST_TIMEOUT_S` | `15` | How long to wait for Vinted before giving up on one request. |

How "already on Vinted" is known: Vinted's search results no longer say when a listing was
posted, but listing ids are handed out in upload order across the whole site. Every check
remembers the newest id it saw and when, so any lower id was provably online by then. That
is enough to skip, say, a month-old listing whose price was just cut into a search's range.
It cannot date a listing newer than anything the app has seen, which is why a gap in
checking is caught up quietly rather than guessed at: anything uploaded while the app was
not looking is recorded, not announced.

The 10-second floor is not caution for its own sake: Vinted's own API lags minutes behind
what people upload, sometimes longer, so checking faster finds nothing sooner and does get
you blocked. Vinted's search no longer says when a listing went up, so notifications show
when the app found it, labelled "found" rather than "listed", and nothing in the app
measures the delay between the two.

### Staying unblocked

| Variable | Default | What it does |
|---|---|---|
| `SESSION_ROTATE_MINUTES` | `60` | Start a fresh anonymous session after this long. Blocks track session age more than request rate. |
| `HTTP_IMPERSONATE` | `false` | Make requests present a real browser's TLS fingerprint. Needs the `impersonate` extra. Only worth turning on if you are being blocked while the same search loads fine in a browser. |
| `PROXY_FILE` | unset | Path to a text file of proxy URLs, one per line (blank lines and `#` comments ignored). Used in turn; one that gets refused sits out for ten minutes. If all of them are sitting out, requests go direct rather than not at all. Rarely needed. |

### Noticing problems

| Variable | Default | What it does |
|---|---|---|
| `WATCHDOG_STALE_CYCLES` | `10` | Checks with no new listing before a search is treated as stuck — but only if other searches on the same site are still finding things. |
| `WATCHDOG_ACTION` | `rotate` | `warn` logs it; `rotate` also starts a fresh session. |
| `OUTBOX_EXPIRY_MINUTES` | `60` | Discard notifications that could not be delivered within this window. |

The watchdog also watches whole sites. When every search on a Vinted site has failed for 15
minutes (refused with a 403, rate limited, or unreachable), destinations with status
notices on get one message about it, and one more when checks work again. It doesn't repeat
in between.

### Telegram

| Variable | Default | What it does |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | unset | From [@BotFather](https://t.me/BotFather). Enables Telegram delivery and the pairing bot. |

### Dashboard

| Variable | Default | What it does |
|---|---|---|
| `WEB_ENABLED` | `true` | The dashboard. Turn it off if you only use the CLI. |
| `WEB_AUTH_TOKEN` | unset | Optional. With no token the dashboard has no sign-in, which is fine while it listens on localhost. **Set one before exposing it further**: anyone who can open the dashboard can add, remove and reroute your alerts. Generate with `openssl rand -hex 32`. Signing in gives that browser a random session (30 days) that signing out revokes; changing the token signs every browser out. After five wrong passwords from one address, sign-in waits 15 minutes. |
| `WEB_HOST` | `127.0.0.1` | Loopback by default. Only widen behind a reverse proxy you trust. |
| `WEB_PORT` | `8000` | |
| `WEB_PUBLIC_URL` | unset | The address the dashboard is reachable at from wherever you read your alerts — set it when the dashboard sits behind a reverse proxy or a tunnel. It becomes the Dashboard link in Discord, Telegram and Apprise alerts. Unset, the link would be `http://<WEB_HOST>:<WEB_PORT>` (`127.0.0.1` for a `0.0.0.0` bind), and an address that only works on the computer itself (`localhost`, `127.0.0.1`) is left out of alerts altogether, since it would do nothing on a phone. So with the defaults, and in Docker, alerts carry no Dashboard link until this is set. Its host name is also one the dashboard answers to (see `WEB_ALLOWED_HOSTS`). |
| `WEB_ALLOWED_HOSTS` | unset | Extra host names the dashboard answers to, comma-separated, such as `finds.example.org`. The dashboard always answers to `localhost`, `127.0.0.1`, `[::1]`, any IP address (so `http://192.168.1.20:8000` from a phone works), names ending in `.local` (`nas.local`, `umbrel.local`), one-word names (`nas`, `umbrel`) and the host of `WEB_PUBLIC_URL`. The `.local` and one-word names only resolve on your own network, so no outside website can take them over. Any other name gets a 400 page that names this setting. That is what stops another website from pointing its own name at your computer and using the dashboard through your browser (DNS rebinding), and it applies however the dashboard is bound, the Docker image's `0.0.0.0` included. Add the name your reverse proxy forwards, if it does not pass the original one on. |

### Updating

How the dashboard's update button and automatic updates behave for each kind of install is
in [Running it somewhere: Updating](self-hosting.md#updating).

| Variable | Default | What it does |
|---|---|---|
| `SUPERVISED` | unset | `launchd`, `systemd` or `windows-launcher`. Says that something starts the app again whenever it exits. The installers set it in the start-at-login entry they write; you only set it yourself if you wrote your own service that restarts the app after any exit (exit code 75 means "updated, start me again"). With it, **Update now** in the dashboard restarts into the new version by itself, and automatic updates can be switched on. |

### Logging and development

| Variable | Default | What it does |
|---|---|---|
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `LOG_FORMAT` | `console` | `json` when something else is collecting the logs. |
| `FETCH_MODE` | `live` | `mock` replays recorded responses from disk instead of calling Vinted. |
| `MOCK_SCENARIO_DIR` | unset | Required when `FETCH_MODE=mock`. |

## Commands

```
vinted-bot run [--open]             start watching (what the container runs);
                                       --open also opens the dashboard in your browser
vinted-bot check --url <url>        fetch one search once and print the result
                                       (through PROXY_FILE's proxies, if set)
vinted-bot watch <url> [options]    add a search
vinted-bot searches                 list searches
vinted-bot unwatch <id>             remove one
vinted-bot destination <kind> <target> [--name N] [--status]
                                       add somewhere to send: discord, telegram,
                                       webhook, ntfy or apprise
vinted-bot destinations             list them
vinted-bot export [--format csv|json] [--search ID] [--output FILE]
                                       write found listings for a spreadsheet
vinted-bot backup <file>            write a complete copy of the database to <file>,
                                       safe while the app is running
vinted-bot pair-telegram            print a link that connects a Telegram chat
vinted-bot status                   how each search is doing
vinted-bot migrate                  create or update the database, then exit
vinted-bot heartbeat                exit 0 if the app is alive (the health check)
```

`export` writes one row per listing a search matched and still keeps, newest first,
leaving out sellers you blocked. The CSV starts with a UTF-8 byte order mark so Excel shows
accents and currency signs properly. `seller_country` is filled in when a seller lookup knew
it. There is no `listed_at` column: Vinted's search no longer says when a listing went up,
and `found_at` is when the app found it.

Options for `watch`:

| Option | Meaning |
|---|---|
| `--name` | What to call it. Defaults to the search text. |
| `--every N` | Seconds between checks for this search. |
| `--max-price N` | Skip anything above this **including buyer protection**. `12,50` works. In the currency of the search's own site; see below for searches on several sites. |
| `--min-price N` | Skip anything below this total. |
| `--exclude a,b,c` | Skip listings whose title or brand contains any of these words. Whole words, ignoring case and accents; end one with `*` to match any ending (`part*`). |
| `--include a,b\|c` | The title or brand must contain every one of these. `b\|c` accepts either. Ignores case and accents, and matches the beginning of a word: `jean` matches `jeans` and `Jeans`. Put a word in double quotes (`'"jean"'` in a shell) to require exactly that word. A trailing `*` is no longer needed, and still accepted. |
| `--regex PATTERN` | The title must match this regular expression (case-insensitive). Checked when you save it. |
| `--min-rating N` | Skip sellers rated under N stars (0 to 5). |
| `--min-reviews N` | Skip sellers with fewer than N reviews. |
| `--skip-unrated` | Skip sellers with no reviews yet. |
| `--countries FR,BE` | Only sellers in these countries. |
| `--deal N` | Only alert when the total is at least N% under what this search usually finds. Everything is still recorded, which is how "usually" is learned; it needs 15 finds in two weeks before it alerts at all. |
| `--max-age N` | Ignore listings the app can tell were already on Vinted N minutes ago, and catch up quietly after a gap longer than that (overrides `FRESHNESS_WINDOW_MIN` for this search; see above for how age is known). |
| `--quiet 23:00-07:00` | Quiet hours, in `TIMEZONE`. Windows through midnight work. |
| `--quiet-mode hold\|drop\|silent` | During quiet hours: hold alerts until the window ends (default), drop them (they still show in the dashboard), or send them without a sound. |
| `--also-on de,be` | Run the same search on other country sites too. A listing seen on two sites is announced once. |
| `--color`, `--notes`, `--tags` | For your own bookkeeping; the colour tints this search's alerts and chips. |
| `--to 1,2` | Destination ids to notify. Without it, the search goes to **every active destination, including ones you add later**. |

Seller country and rating filters read the seller's public member page, once a week per
seller, and only for listings that passed every other filter. Those lookups are paced so
Vinted doesn't refuse them, so on a busy search a listing whose seller hasn't been looked
up yet waits for a later check, for up to the search's freshness window; a seller seen
before comes from the cache straight away. If Vinted refuses lookups, they pause, and the
waiting listings stay waiting rather than being judged without the seller. When a seller
was looked up, its rating, review count and country also appear in the alert.

Listings a search skipped are logged with the reason in the search's **Not sent** list, so
the dashboard can answer "why did I not get this one?": prices with their currency, a
listing the app could tell was too old (`too_old`), a seller still waiting to be looked
up and why, and the rest.

**Price limits on several sites.** The minimum and maximum price are in the currency of the
search's own site (zł for a vinted.pl search). With `--also-on` sites that use another
currency, those listings are converted with the European Central Bank's daily reference
rates before comparing. The rates are fetched at most once a day, and only while some
search spans more than one currency. A listing in a currency with no known rate is skipped,
and Not sent says so.

## Adding a search

Search on Vinted, set your filters, copy the address bar, and paste that URL into the
dashboard or `vinted-bot watch`. The dashboard can also build the URL for you, from
Vinted's own categories, brand autocomplete and filters.

Any country site works: `vinted.fr`, `.de`, `.nl`, `.co.uk`, `.com`, and the rest. The site
you copied from is the site it watches, and the links you get back point there too. Tracking
parameters are stripped, so pasting the same search twice counts as one search.

**The same link twice.** Adding a link that is already watched is refused, in the
dashboard, with `vinted-bot watch` and with Telegram's `/add` alike, and the message names
the search that already watches it. To watch the same link with different filters or
destinations, use **Duplicate** on that search and change the copy. Editing a search
without changing what it fetches (its link, filters in the link, or sites) keeps what it has
already seen and its typical price; only a real change to the search starts it afresh.

## Destinations

Where to get each kind of target:

| Kind | Setup |
|---|---|
| `telegram` | Create a bot with [@BotFather](https://t.me/BotFather), set `TELEGRAM_BOT_TOKEN`, then run `vinted-bot pair-telegram` and tap the link it prints. It finds your chat id for you. |
| `discord` | In your server: Settings → Integrations → Webhooks → New Webhook → Copy URL. Nothing to invite, nothing to host. `vinted-bot destination discord` checks that it is a webhook link, like the dashboard does. |
| `apprise` | Email, Slack, Pushover, Gotify, Matrix and more: one [Apprise URL](https://github.com/caronc/apprise/wiki) per service, such as `mailtos://user:app-password@gmail.com`. Needs the `apprise` extra. |
| `ntfy` | A topic name, or the full topic address (`https://ntfy.example.org/my-topic`) for your own server. Install the ntfy app; no account. The public ntfy.sh server allows about 250 messages a day per internet address, so it suits focused searches; use Telegram or Discord for busy ones. |
| `webhook` | Any URL you control: n8n, Home Assistant, a script. Payload below. |

`--status` also sends status notices there: the watchdog's warnings, a whole site failing
and recovering, and "updated itself". The first destination you create gets them on by
default, from the dashboard, setup, Telegram pairing or the command line.

Each search can go to its own set of destinations, so a Discord channel for one thing and
your phone for another is normal. A search you have not routed anywhere goes to every
active destination, including ones added later, so the order you set things up in does not
matter. Watches follow the same rule: a watch can be sent to chosen destinations, and
otherwise goes to every active one. When two searches match the same listing, each
destination still hears about it once.

What is stored per destination — the dashboard and `vinted-bot destination` fill these in
for you:

| Kind | Fields |
|---|---|
| `discord` | `url` (destinations made by 1.x stored it as `webhook_url`, which still works), optionally `style` (`card`, `compact` or `classic`), `mention` (`<@&role id>` for a role, `<@user id>` for a person, `@everyone` or `@here`), `ping_tiers` (which tiers ping the mention; `[steal]` by default, so only steals ping), `silent` (never make a sound), `thread_id`, `username`, `avatar_url` |
| `telegram` | `chat_id`, optionally `thread_id` for a forum topic (1.x's `message_thread_id` still works), `style` (`photo` or `gallery`), `silent` |
| `ntfy` | `topic` (or a full topic `url`), optionally `server`, `token` and `priority` (1 to 5). While the server's daily limit is reached, the destination is paused and the Alerts page shows why. |
| `webhook` | `url`, optionally `secret` (signs every request, see below) and `headers` |
| `apprise` | `urls`: a list of [Apprise](https://github.com/caronc/apprise/wiki) addresses, for email, Slack, Pushover, Gotify, Matrix and the rest. Needs the `apprise` extra. |

Every kind also takes `tiers`, the kinds of listing it wants (`steal`, `deal`, `normal`; all
three by default), and `silent_tiers`, the ones to deliver without a sound. A listing a
destination did not want is set aside as skipped, with the reason, and not counted as a
failed delivery. 1.x's `deals_only` (the same as `tiers: [steal, deal]`) still works, and
so does `min_deal_pct`, a custom bar for how far under the typical price a listing must be,
except on a destination whose `tiers` include `normal`: that one takes everything, so the
bar has nothing to filter.

Those apply to **search listings only**. Watch alerts (a price drop, a sale, a reservation,
a removal, a followed seller's new upload) were asked for one by one, so tiers never filter
them out. Whether a destination gets them at all is its own key, `watch_alerts`: `true` by
default, `false` keeps them away from, say, a steals-only channel.

When several ntfy alerts are waiting at once, they go out as one push listing them, which
keeps a busy search inside ntfy.sh's daily allowance. In quiet hours' `silent` mode, Apprise
sends without a sound where the service has such a setting, and webhook items say
`"silent": true`.

## The webhook payload

A plain webhook destination receives a POST like this. The shape is treated as a contract:
it changes only with a version bump, because other people's automations depend on it.

Each POST carries the listings of **one search**, or of **one watch**, so `search` always
names where they came from. For watch alerts (price drops, sales, a followed seller's new
uploads) `search` is the watch's label and `search_id` is `null`, as it is for the sample
listing a test sends. A status notice, for destinations that asked for them, is
`{"version": 2, "status": "<message>"}` with no items.

```json
{
  "version": 2,
  "search": "nike air max",
  "search_id": 3,
  "items": [
    {
      "id": 9683334896,
      "site": "vinted.fr",
      "title": "Nike Air Max 90",
      "url": "https://www.vinted.fr/items/9683334896-nike-air-max-90",
      "brand": "Nike",
      "size": "42",
      "condition": "Very good",
      "price": "15.00",
      "total_price": "16.45",
      "currency": "EUR",
      "photo_url": "https://images.vinted.net/...",
      "listed_at": null,
      "seller": "someone",
      "seller_rating": 0.93,
      "links": {
        "message_seller": "https://www.vinted.fr/items/9683334896/want_it/new",
        "buy": "https://www.vinted.fr/transaction/buy/new?..."
      },
      "kind": "listing",
      "search_id": 3,
      "detected_at": 1792000000,
      "photos": ["https://images.vinted.net/...", "https://images.vinted.net/..."],
      "previous_price": null,
      "typical_price": "27.50",
      "deal_pct": 40,
      "deal_tier": "steal",
      "margin": null,
      "favourites": 12,
      "seller_profile": {
        "id": 12345678,
        "login": "someone",
        "url": "https://www.vinted.fr/member/12345678",
        "stars": 4.7,
        "reviews": 128,
        "country": "FR"
      },
      "silent": false
    }
  ]
}
```

Version 2 keeps every version 1 field with the same name and meaning, and adds the rest:

| Field | Meaning |
|---|---|
| `kind` | `listing` (a search found it), `price_drop`, `sold`, `reserved`, `removed` (a watched listing changed) or `seller_upload` (a followed seller listed it). |
| `search_id` | The search's id, or `null` for watch alerts. Also at the top level. |
| `detected_at` | When this search found the listing, as Unix seconds. |
| `photos` | Every photo, largest size. |
| `previous_price` | For `price_drop`: the price before the drop, as the listing's own page shows it. That page carries no buyer-protection figure, so this is the asking price, and `total_price` is `null` on watch alerts. |
| `typical_price` | This search's median total price for what it finds, when the listing was found. `null` until it has 15 finds in two weeks. |
| `deal_pct` | How far under `typical_price` the total is, in percent (negative when over). |
| `deal_tier` | `steal`, `deal` or `normal`: the tiers a destination's `tiers` setting names. |
| `margin` | What reselling would leave, from the search's resale price, fee and shipping. `null` without one. |
| `favourites` | How many people favourited the listing. |
| `seller_profile` | The seller's id, login, profile link, rating out of five, review count and country (an ISO code such as `FR`), as far as known: rating, reviews and country come from the seller lookup that country and rating filters do. |
| `silent` | `true` when the alert should make no sound: quiet hours in `silent` mode, or a tier in the destination's `silent_tiers`. |

`price` is what the seller asks. `total_price` is what you pay. Filters and displays use the
second one. `listed_at` is the photo time, which Vinted's search results no longer give, so
it is usually `null`; `detected_at` is the honest "found it" time.

### Signed requests

With a `secret` set on the destination, every request carries two headers:

```
X-Vinted-Bot-Timestamp: 1792000000
X-Vinted-Bot-Signature: sha256=<hex>
```

The signature is the HMAC-SHA256, under the secret, of the timestamp, a full stop, and the
raw request body: `"<timestamp>." + body`. Recompute it over the body exactly as received
(before parsing the JSON) and compare in constant time. Refusing timestamps more than a few
minutes old stops someone replaying a request they captured. In Python:

```python
import hashlib, hmac


def genuine(secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return hmac.compare_digest(f"sha256={expected.hexdigest()}", signature)
```

## RSS

Each search has a feed at `/rss/<search id>.xml`, so with the defaults:

```
http://localhost:8000/rss/1.xml
```

If `WEB_AUTH_TOKEN` is set, feed readers cannot sign in, so the feed address carries a key
instead: `/rss/1.xml?key=<feed key>`. The key is a random value of its own, not your
password, made the first time it is needed. Copy the whole address from the "RSS feed of
this search" link on the search's page in the dashboard. Anyone with that address can read
the feed, so keep it to yourself.
