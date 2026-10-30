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
  listings.

## [0.1.0] - 2026-08-16

First version, never tagged as a release: polling with a stale-catalog watchdog, filters on
the total price including buyer protection, Discord, Telegram, ntfy, RSS and webhook
delivery through a reliable outbox, and a web dashboard.

[Unreleased]: https://github.com/jasp-nerd/vinted-sniper/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jasp-nerd/vinted-sniper/commits/v0.1.0
