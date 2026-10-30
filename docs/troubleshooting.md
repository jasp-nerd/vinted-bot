# When it stops finding things

## First: are you on the newest version?

Vinted moved its search to a new address in September 2026. Versions before 2.0.0 still ask
the old one and find nothing, or report errors such as a 404 or "malformed" on every search.
No setting fixes that; [updating](self-hosting.md#updating) does.

Check the version you run with `vinted-bot --version` (Docker:
`docker compose exec vinted-bot vinted-bot --version`). The dashboard also says when a
newer version is out.

## Then: how is each search doing?

The dashboard's Searches tab shows the state of every search next to its name, with a
sentence saying why when you open it: **Running** or **Quiet** (working; quiet just means
nothing new matched for a while), **Starting**, **Paused** or **Muted** (your doing),
**Same results lately** (the watchdog's "stale", below), **Slowed down by Vinted** (403 or
429), **Can't reach Vinted** (a network problem on this side) and **Waiting on Vinted**
(an answer the app didn't expect). On the command line,
`vinted-bot status` prints the same: each search with a one-word state, when it last
succeeded, and what went wrong if anything did. With Docker, put
`docker compose exec vinted-bot` in front of any `vinted-bot` command.

```
Running.

nike air max [ok] — vinted.fr
  last successful check: 34s ago
  newest listing seen:   112s ago

carhartt jacket [failing] — vinted.co.uk
  last successful check: 1840s ago
  blocked 12 times, rate limited 0 times
  last error: vinted.co.uk refused the request with 403
```

The state tells you which of the following sections to read.

## Vinted reachable from this machine

Most "it finds nothing" reports come down to one question: does Vinted answer the computer
vinted-bot runs on? In the dashboard, a search showing **Slowed down by Vinted** or
**Can't reach Vinted** is the "no"; **Running** or **Quiet** is the "yes". When every
search on a site has failed for 15 minutes, destinations with status notices on also get a
message saying so, and another when it works again. To test it by hand, try one search
once:

```bash
vinted-bot check --url "https://www.vinted.fr/catalog?search_text=nike"
```

Listings printed means the connection works. "Blocked" means Vinted is refusing this
address. To confirm without vinted-bot at all, ask Vinted for a session cookie, using the
country site you watch:

```bash
# macOS, Linux, Raspberry Pi
curl -s -c - -L "https://www.vinted.fr/" | grep access_token_web

# Windows (PowerShell)
curl.exe -s -c - -L "https://www.vinted.fr/" | Select-String access_token_web

# Docker
docker compose exec vinted-bot sh -c 'curl -s -c - -L "https://www.vinted.fr/" | grep access_token_web'
```

**A line with `access_token_web` in it** means your address is fine. If searches still fail,
the problem is in the app: please [open an issue](https://github.com/jasp-nerd/vinted-bot/issues/new/choose)
with the output of `vinted-bot status` and the log.

**Nothing printed** means Vinted is challenging this address, and no setting inside
vinted-bot changes that. See [the 403 section](#failing-with-403) for what does.

## "ok" but nothing is arriving

The search is working; it just isn't matching anything. Start with the search's **Not
sent** list in the dashboard: every listing it skipped is there with the reason, such as
over the price limit (with both currencies when a search spans sites), a word it lacks, too
old, a seller filter, or a seller still waiting to be looked up. Common causes, in the order
worth checking:

**Your price limit includes buyer protection.** A limit of 20 rejects a listing priced at 18
that costs 20.50 to actually buy. That is the intended behaviour, but it surprises people.
Check what you set with `vinted-bot searches`.

**The search itself is narrow.** Open the URL in a browser. If Vinted shows nothing new
either, there is nothing wrong.

**Excluded words are catching more than you meant.** Excluding "new" also excludes "brand new
condition" and anything else containing it.

**Must-include words match word beginnings.** "jean" matches "jeans" and "Jeans". Put a
word in double quotes ("jean") when only that exact word will do.

**Seller filters on a busy search.** A country or rating filter needs one look at each new
seller's profile, and those lookups are paced. On a search with a lot of new listings, the
ones whose seller hasn't been looked up yet wait for later checks (up to the search's
freshness window); Not sent says when that is what's happening.

**Everything is a boosted listing.** Paid bumps are skipped, because they are old listings
resurfacing rather than new ones.

## "stale"

The search has stopped seeing new listings while your other searches on the same site are
still finding them. Vinted sometimes serves a catalog that has quietly stopped updating,
which looks like success from the outside.

The app starts a fresh session on its own when it notices. If it stays stale for more than
an hour, restart it: run the install command again if you used the installer, or
`docker compose restart vinted-bot` with Docker.

If it persists after that, the search may have genuinely dried up. Compare with the same URL
in a browser.

## "failing" with 403

Vinted is refusing the connection. Almost always this is about where the request comes from,
not what it asked for. Confirm it with the
[reachability check](#vinted-reachable-from-this-machine).

If the check passes, your address is fine and the problem is the app: please open an issue
with your logs. If it fails, your address is being challenged. Options, cheapest first:

1. **Wait.** These are usually temporary. The app backs off on its own.
2. **Slow down.** Raise `VINTED_BOT_POLL_DEFAULT_INTERVAL_S` to 120 or 300. Ten searches
   at once from one address is a lot more traffic than one search.
3. **Move it home.** Residential connections are challenged far less than datacenter ones. A
   Raspberry Pi is enough.
4. **Turn on TLS impersonation.** Set `VINTED_BOT_HTTP_IMPERSONATE=true`. This makes
   requests look like a real browser at the connection level rather than like Python. It
   needs the `impersonate` extra installed, and it is not a magic fix — if your address is
   blocked outright, it stays blocked.
5. **Use a proxy.** `VINTED_BOT_PROXY_FILE` points at a text file with one proxy URL per
   line. Free proxy lists are already blocked; if you go this route, use residential proxies
   in the same country as the site you are watching. Most people never need this.

## "failing" with 429

You are checking too often for how Vinted feels about your address right now. The app already
waits as long as Vinted asks it to. If it keeps happening, increase the interval — the
listings will still be there.

## "failing" with malformed

Vinted answered with something that is not a catalog. That usually means one of three
things: a version from before September 2026's API move ([update](self-hosting.md#updating)),
an anti-bot page instead of an answer (see the 403 section), or a new change on Vinted's
side, which needs a fix here. If you are on the newest version, please open an issue with the
logged error.

## Notifications stopped but searches are fine

Check the destination:

```bash
vinted-bot destinations
```

A destination marked `disabled` was switched off because the other end said it was gone — a
deleted Discord webhook, a blocked Telegram bot, a wrong chat id. This is deliberate:
repeatedly sending to a dead webhook is what gets your address rate-limited by Discord
itself. Remove it and add the new one.

An ntfy destination can also be **paused**: the public ntfy.sh server allows about 250
messages a day per internet address and answers "too many requests" after that. vinted-bot
then stops sending there until the limit resets, and the Alerts page says so. Narrow the
search, or use Telegram or Discord for busy searches.

Also worth knowing: undelivered notifications are discarded after an hour by default. If
Discord was down all night, you get the current listings when it comes back rather than a
flood of stale ones.

## It won't start and names a setting

A setting it can't use stops it at startup with a short message naming the setting and
what is wrong with it, for example a port that isn't a number. Fix that line where you set
it: the `.env` file in the data folder, or the `environment:` block of
`docker-compose.yml` (then `docker compose up -d`).

Two things only warn and carry on: a `VINTED_BOT_` name it doesn't know (a typo, or a
setting from an older version), which it lists and ignores; and a time zone it can't read,
such as the `TZ=:/etc/localtime` some systems set, for which it uses the computer's own
time zone instead.

## It says "Not running"

The heartbeat is stale, meaning the process is not coming round its loop, or it is not
running at all. The log says why; see [where the logs are](#where-the-logs-are). With Docker,
`docker compose ps` also shows whether the container keeps restarting.

Also worth grepping the logs for `web.no_password`: that warning means the dashboard is
listening on an address other than localhost with no sign-in, so anyone who can reach the
port can change your searches and where alerts go. Set a password in Settings (or
`VINTED_BOT_WEB_AUTH_TOKEN`), or check that the published port is not public.

## I forgot the dashboard password

On the computer running vinted-bot, run `vinted-bot reset-password` (with Docker:
`docker compose exec vinted-bot vinted-bot reset-password`). It prints a new password and
signs every browser out; change it to your own in Settings. If the password is
`VINTED_BOT_WEB_AUTH_TOKEN`, it is in the environment or `.env` file instead.

## The dashboard says "Unknown address"

It only answers to names it was told about, so that another website cannot point its own
name at your computer and use the dashboard through your browser. Localhost, any IP
address, names ending in `.local` (such as `nas.local` or `umbrel.local`) and one-word
names (such as `nas`) always work, since those only exist on your own network. If you
reach it by any other name (a reverse proxy, a tunnel), add that name to
`VINTED_BOT_WEB_ALLOWED_HOSTS`, or set `VINTED_BOT_WEB_PUBLIC_URL` to the full address,
and restart it (with Docker, `docker compose up -d`: a plain restart keeps the old
settings). Behind a reverse proxy that does not pass the original
`Host` on, add the name it forwards instead (often the container's name).

## Telegram never connects

The bot cannot message you first — that is a Telegram rule, not a limitation here. Run
`vinted-bot pair-telegram --bot-username yourbot`, then tap the link it prints, in the chat
or group you want alerts in. The app must be running for the link to work, and the link
expires after thirty minutes.

For a group, add the bot to the group first. For a forum topic, tap the link inside that
topic.

## The update button didn't work

The message under Settings, Updates says what happened, and uv's own output is underneath
it (on Windows it is in the log file instead). The two usual causes:

- **"Nothing newer was installed."** A release reaches GitHub a few minutes before PyPI, where
  updates are downloaded from. Try again later.
- **"uv stopped with an error."** Often no internet, or a full disk. vinted-bot keeps running
  the version it was on.

On Windows, if vinted-bot comes back still on the old version, the upgrade that runs
while it is closed failed, and the log file says why. Running the install command again does
the same update by hand, on any system.

## Everything is broken after an update

Go back to the previous release and open an issue. With Docker, pin its tag in
`docker-compose.yml`, then `docker compose up -d`:

```yaml
image: ghcr.io/jasp-nerd/vinted-bot:2.1.0
```

With the installer, run it with the release you want (macOS and Linux shown; on Windows set
the same variable with `$env:VINTED_BOT_PACKAGE = "..."` first):

```bash
curl -LsSf https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/install.sh | \
  VINTED_BOT_PACKAGE="vinted-bot==2.1.0" sh
```

Your searches carry over either way. The weekly canary tests against the live site, so an
outright break usually gets caught before it ships. If you hit one anyway, the log is the
useful thing to attach.

## Installing

**"vinted-bot: command not found"** (or "not recognized" on Windows) right after
installing: open a new terminal window. The installer adds its folder to your PATH, and
windows that were already open don't see that.

**The installer says port 8000 is taken.** Something else listens there, often an older copy
of vinted-bot running in Docker. Stop that, or install on another port: put
`VINTED_BOT_WEB_PORT=8001` before `sh` in the install command (Windows:
`$env:VINTED_BOT_WEB_PORT = 8001` first). The dashboard is then on
http://localhost:8001.

**"running scripts is disabled on this system"** on Windows: use the install command exactly
as written, including `-ExecutionPolicy ByPass`. That lifts the restriction for this one
command only.

**The download fails** at work or school: some networks block downloads from GitHub or from
astral.sh, where uv comes from. Try from home.

**"It installed, but didn't start".** The log says why: see below.

**Docker: "/data is not writable"** (the container stops straight after printing it): the
folder mounted at `/data` belongs to a user the container can't write as. Set `PUID` and `PGID` to the
folder's owner (`id` on the host prints yours) and start the container normally, without a
`user:` line, so it can fix the ownership itself.

## Where the logs are

| Installed with | Log |
|---|---|
| Installer, Windows | `%LOCALAPPDATA%\vinted-bot\vinted-bot.log` |
| Installer, macOS | `~/Library/Application Support/vinted-bot/vinted-bot.log` |
| Installer, Linux | `journalctl --user -u vinted-bot` (or `~/.local/share/vinted-bot/vinted-bot.log` if it isn't started at login) |
| Docker | `docker compose logs --tail 200 vinted-bot` |

When you open an issue, attach the last couple of hundred lines and the output of
`vinted-bot status`. The app keeps tokens and webhook links out of both, but glance over
them before posting anyway.
