# vinted-bot

A free, open-source, self-hosted Vinted bot: it watches your Vinted searches and sends new
listings to Telegram, Discord or your phone, with a web dashboard. The goal is to be the best
free alternative to paid Vinted bots (€5–€300 a month), and easy enough for someone who has
never opened a terminal.

## What it stands for

- **Free and self-hosted.** No subscription, no ads, no account with us. It runs on the
  user's own computer, NAS or server.
- **Never logs in to Vinted.** It reads public listings anonymously, so there is no account to
  ban. That also means no autobuy, auto-message or auto-offer, on purpose.
- **Honest.** Prices include the buyer-protection fee. It says plainly when something stops
  working (a search goes quiet, Vinted blocks the connection) instead of failing silently, and
  it never claims to be faster than Vinted itself allows.
- **Reliable.** An alert is written before it is sent, so a crash never loses or duplicates one.
- **Anyone can set it up.** One-line installers and a setup wizard; everything a normal user
  needs is done in the dashboard, never by editing files.
- **Looks like it belongs next to Vinted.** Vinted's colours and calm layout, with Mags the
  magpie as mascot. Copy is plain and friendly: no emoji, no hype.

## How the code is organised

`src/vinted_bot/`: `vinted/` talks to Vinted, `engine/` decides what is new and what to
send, `deliver/` sends alerts, `db/` holds all SQL, `web/` is the dashboard, `botctl/` is the
Telegram bot. `site/` is the landing site, `docs/` the user and contributor docs
(`docs/architecture.md` explains the design, `docs/REVIEW.md` the review checklist).

## How we work

- Every change keeps CI green: `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run mypy`, `uv run deptry src`, `uv run vulture`.
- New behaviour comes with a test that fails without it. Check UI changes in a real browser.
- No backward-compatibility shims or dead code; prefer a clean change.
- Commit messages are plain imperative sentences without prefixes or AI attribution.
- Releases are manual: bump the version and the CHANGELOG in a PR, merge, then run
  Actions → Release (see CONTRIBUTING.md).
