# Changelog

Every release, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versions follow [Semantic Versioning](https://semver.org/). Each version's section here
becomes the text of its GitHub release, so write it for the people running the app.

## [Unreleased]

<!-- Planned as 2.0.0. Rename this heading to `## [2.0.0] - YYYY-MM-DD` when cutting the
     release; see "Cutting a release" in CONTRIBUTING.md. -->

Vinted moved its search to a new address in September 2026, and every earlier version stopped
finding listings. This release works again, and comes with a rebuilt dashboard, many more
filters, new-look alerts and one-line installers for Windows, macOS and Linux. Your searches
and destinations carry over: the database upgrades itself on the first start.

### Fixed

- Searches work again after Vinted's September 2026 move to a new search address
  ([#9](https://github.com/jasp-nerd/vinted-sniper/issues/9),
  [#12](https://github.com/jasp-nerd/vinted-sniper/issues/12),
  [#14](https://github.com/jasp-nerd/vinted-sniper/issues/14)). Filters saved before the move
  keep working, and brand, size and condition show up in alerts again.
- The search builder's filter options load again.
- A listing that turns up in the results after a newer one was announced is no longer
  skipped forever. New listings are now recognised by their id, since Vinted's search stopped
  saying when a photo was taken.
- Excluding a word only matches whole words, ignoring accents and capitals: excluding "art"
  no longer drops "smartphone".
- ntfy alerts with accents or a euro sign in the title no longer fail to send.
- A listing title containing brackets or HTML can no longer turn into a link in ntfy, or load
  an image in an Apprise email.
- Prices read back as "15.00" instead of "15.0", and "12,50" means the same thing in the
  dashboard, the command line and the Telegram bot.
- A database upgrade that fails part-way no longer leaves the database half changed.
- A locked database no longer stops the whole app from its heartbeat.
- A search that has failed since it was added shows as failing, not as starting.
- Restarting no longer fires every search in the same second.
- Starting again after the app was off, the computer asleep or Vinted refusing for a while no
  longer announces a whole page of old listings as new. The first check back records what it
  missed quietly. The same goes for the first check after upgrading from 1.x, which now
  carries on from the newest listing 1.x had seen.
- "Ignore listings older than" (and `watch --max-age`, and `FRESHNESS_WINDOW_MIN`) works
  again: it skips listings the app can tell were already on Vinted that long ago, such as an
  old listing whose price was just cut into range.
- Changing a search's link or sites starts it over quietly, instead of announcing everything
  above where the old search had got to, and its typical price starts again too.
- A listing still for sale after the retention period (30 days) is no longer announced again,
  by a search or by a seller watch.
- A listing two searches match is judged by each search's own typical price, so a narrow
  search's steal is no longer reported as overpriced because a broader search found it
  first.
- When Vinted refuses the homepage itself, a search backs off like for any other refusal
  instead of retrying every 15 seconds. A search that crashes is restarted with growing
  pauses, and tokens that keep being rejected are no longer retried every five seconds.
- When Vinted refuses or rate-limits seller lookups, the app stops asking for a while
  (honouring `Retry-After`), and the listings waiting on one are listed in "Not sent" as
  "seller unknown".
- Alerts a destination did not want (for example a normal listing for a steals-only
  channel) no longer count as failed deliveries on the alerts and stats pages.
- An open dashboard tab no longer misses finds after a quiet month emptied the stored
  listings.
- Watch alerts sent to a webhook are posted one watch at a time, so `search` names the right
  watch.
- **Security:** the dashboard only answers to localhost, IP addresses, the `WEB_PUBLIC_URL`
  host and the new `WEB_ALLOWED_HOSTS`, however it is bound. Before, the Docker image's
  `0.0.0.0` bind switched that check off, which let a web page use a password-less
  dashboard through your browser (DNS rebinding). If you reach the dashboard by a name, add
  it to `VINTED_SNIPER_WEB_ALLOWED_HOSTS`; the error page says so too.
- **Security:** a search name can no longer run script in the stats page's chart tooltips.
- **Security:** in a CSV export, a cell that would start a spreadsheet formula (a title such
  as `=HYPERLINK(...)`) is prefixed with an apostrophe so it shows as text.
- **Security:** signing in to the dashboard gives each browser its own random session, which
  signing out revokes, and changing the password signs everyone out. After five wrong
  passwords from one address, sign-in waits 15 minutes.

### Added

- **A rebuilt dashboard**: a guided setup on first run that ends with a test alert, a live
  feed of finds laid out like Vinted's own grid (save, hide, block the seller), a plain-words
  status for every search, a "Not sent" list showing why each skipped listing was skipped, a
  watchlist, stats, settings, dark mode and a phone layout.
- **More filters**: words the title must contain (with alternatives such as `501|505`), a title
  pattern, a minimum price, seller rating, number of reviews and country, and a seller
  blocklist.
- **Deals**: each search learns its typical price, alerts show how far under it a listing is,
  and a search or a destination can be set to deals only.
- **Quiet hours** per search, in your time zone: hold alerts until the end, drop them, or send
  them without a sound.
- One search can cover several country sites.
- **Watches**: hear when a listing's price drops or it is reserved, sold or removed, and when
  a seller uploads something new.
- **Discord alerts** as cards with a photo gallery, the total price, a deal badge and Buy,
  Message and Open buttons, in the search's colour. Up to three share a message, and bigger bursts become a
  compact digest. Mentions are opt-in.
- **Telegram alerts** as photo cards with buttons, an optional gallery style, and a digest in
  busy groups. A paired chat can `/list`, `/pause`, `/resume`, `/add` and `/remove` searches
  and ask for `/status`.
- Alerts are written in the language of the listing's site (English, French, German, Dutch,
  Spanish, Italian, Polish, Lithuanian and Czech) with prices formatted to match.
- ntfy alerts gain the photo, action buttons and a higher priority for deals.
- **Apprise**, an optional extra, for email, Slack, Pushover, Gotify, Matrix and many more.
- Webhook payloads can be signed with a shared secret (HMAC-SHA256).
- A test button for every destination, and a preview of what its alerts will look like.
- Export found listings as CSV or JSON, from the dashboard or `vinted-sniper export`.
- A notice in the dashboard when a newer version is out (one request to GitHub a day, can be
  turned off), and an optional uptime ping to a service such as healthchecks.io.
- **Update from the dashboard.** Where the installer set vinted-sniper up to start by itself,
  "Update now" installs the new version and restarts into it, and "Install updates by
  itself" (off unless you turn it on) does that between 4 and 5 at night, never while an
  alert is on its way out, then says so in your status alerts. Installed with uv or pipx but
  started by hand, the button installs it and tells you how to restart. Docker and source
  installs are shown the command to run. Updates only ever come from PyPI through uv or
  pipx, and only when GitHub has a newer release; a failed update leaves the running version
  alone and says what went wrong.
- `vinted-sniper run --open` opens the dashboard once it is ready.
- One-line installers for Windows (`install.ps1`) and macOS and Linux (`install.sh`), with
  optional start at login, no Docker and no admin rights.
- Docker: `PUID` and `PGID` to choose who owns the data folder, so NAS shares and cloud
  volumes owned by root work without manual fixes, a `TZ` setting, and an opt-in automatic
  updater.
- Templates for Unraid, Umbrel, CasaOS, Render and Coolify in `deploy/`.
- `llms.txt`, a setup guide an AI assistant can follow to walk someone through installing,
  and a ready-made prompt in the README.
- Issue forms that ask for the version, the status output and the log.

### Changed

- The `latest` image tag now means the newest release. Builds of the main branch are tagged
  `edge`.
- The installers' start-at-login entries now tell the app they restart it
  (`VINTED_SNIPER_SUPERVISED`), and the Windows launcher stays running in the background so it
  can install an update while the app is closed. Run the installer once more to get this.
- The dashboard is part of every install. `vinted-sniper[web]` still works but is no longer
  needed.
- Outside a container, the database lives in your user data folder (unless `./data/app.db`
  already exists, which keeps being used).
- A search you haven't routed anywhere goes to every active destination, including ones added
  later.
- The same Vinted link can be added twice with different filters, for example to send a
  stricter copy somewhere else.
- The webhook payload is version 2: every version 1 field is still there, with the alert
  kind, deal, photos and seller details added beside them. Each POST holds one search's
  listings, or one watch's. The fields and the signature headers are documented in
  docs/configuration.md.
- **RSS feeds of a password-protected dashboard need the new feed key** instead of the
  password: `?key=<your password>` no longer works, because feed addresses end up in reader
  settings and proxy logs. Copy the new address from the "RSS feed of this search" link on
  the search's page.

## [0.1.0] - 2026-08-16

First version, never tagged as a release: polling with a stale-catalog watchdog, filters on
the total price including buyer protection, Discord, Telegram, ntfy, RSS and webhook
delivery through a reliable outbox, and a web dashboard.

[Unreleased]: https://github.com/jasp-nerd/vinted-sniper/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jasp-nerd/vinted-sniper/commits/v0.1.0
