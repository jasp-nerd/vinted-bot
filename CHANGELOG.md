# Changelog

Every release, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and versions follow [Semantic Versioning](https://semver.org/). Each version's section here
becomes the text of its GitHub release, so write it for the people running the app.

## [Unreleased]

<!-- Planned as 2.0.0. Rename this heading to `## [2.0.0] - YYYY-MM-DD` when cutting the
     release; see "Cutting a release" in CONTRIBUTING.md. -->

Vinted moved its search to a new address in September 2026, and every earlier version stopped
finding listings. This release works again, and comes with a rebuilt dashboard, many more
filters and a one-line installer for Windows, macOS and Linux.

### Fixed

- Searches work again after Vinted's September 2026 move to a new search address.

### Added

- One-line installers for Windows (`install.ps1`) and macOS and Linux (`install.sh`), with
  optional start at login, no Docker and no admin rights.
- Docker: `PUID` and `PGID` to choose who owns the data folder, so NAS shares and cloud
  volumes owned by root work without manual fixes.
- Templates for Unraid, Umbrel, CasaOS, Render and Coolify in `deploy/`.
- `llms.txt`, a setup guide an AI assistant can follow to walk someone through installing.

### Changed

- The `latest` image tag now means the newest release. Builds of the main branch are tagged
  `edge`.

<!-- Lead: add the dashboard, filter, notification and watchlist entries from the other
     workstreams here. -->

## [0.1.0] - 2026-08-16

First version, never tagged as a release: polling with a stale-catalog watchdog, filters on
the total price including buyer protection, Discord, Telegram, ntfy, RSS and webhook
delivery through a reliable outbox, and a web dashboard.

[Unreleased]: https://github.com/jasp-nerd/vinted-sniper/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jasp-nerd/vinted-sniper/commits/v0.1.0
