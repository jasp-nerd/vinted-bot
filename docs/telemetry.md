# Usage statistics and error reports

vinted-bot sends usage statistics and error reports to the project, so we can see which
setups and features people use and fix problems before they are reported. They go to
`ingest.jaspnerd.dev`, a small server run by the maintainer, which passes them on to
PostHog (in the EU) without your internet address. Each install is told apart by a random
id kept in its own database. There is no account, and nothing ties the id to you.

## What is sent

- **When the app starts, and once a day while it runs:** the version, how it was installed
  (installer, pipx, uv, Docker), the operating system and its version, the processor type,
  the Python version, the kind of device (a Raspberry Pi, a NAS), the number of processors,
  the amount of memory and the size of the database as a range, the time zone, the
  dashboard theme, and which of the app's own settings are on (automatic updates, phone
  access, a password, the Telegram bot).
- **How it is set up, as counts:** how many searches there are and how often they are
  checked, which Vinted sites they use, which kinds of filter they use (a price limit, a
  brand, a seller rating: the filter's name, not its value), and how many destinations,
  watches and blocked sellers there are of each kind.
- **How it went that day, as totals:** checks that worked or failed and why (a block, a
  rate limit, a network error), listings seen, new and alerted, alerts sent, retried and
  failed per channel, how long Vinted took to answer, how long an alert took to arrive,
  and how many warnings of each kind the log had.
- **What was used:** which dashboard pages were opened and which actions were used, by the
  page's name (`/searches/{query_id}/edit`, never the search itself), whether on a phone or
  a computer, and the browser's language; which Telegram bot commands were used; whether a
  test alert arrived; which kind of outside link was opened (Ko-fi, GitHub, a listing on
  Vinted, never the address); and when setup was finished and the first search and first
  alert happened.
- **Errors:** the type of error, its message, and the steps that led to it: for
  vinted-bot's own code the file, function, line number and that line of code (the code is
  public); for the libraries it uses only the module, function and line number. Before
  anything is kept, vinted-bot replaces web addresses (keeping only well-known hosts such
  as vinted.fr or api.telegram.org), tokens and keys, user names and passwords,
  email addresses, internet addresses, host names with a port, folder names in file paths,
  your user name, and quoted text in the message. The same error is sent at most once an
  hour, and no more than 50 a day.

## What is never sent

Your search terms, search names, the listings you find, prices, sellers, Telegram, Discord
or other destination details, bot tokens, webhook links, passwords, proxy addresses, file
contents or the text of your alerts. Your internet address is not passed on to PostHog,
and PostHog does not look up a location.

## How often

Events wait in memory and go out together about once a minute while the app runs, and once
more when it stops. A typical install sends a handful a day. When sending fails, vinted-bot
tries again with growing pauses for half an hour, then drops the batch.

Usage statistics are off when vinted-bot runs from a copy of the source code, in mock mode,
in CI and in its own tests.

## Turning it off

In the dashboard: **Settings**, **Advanced**, **Share usage statistics**. Anything not sent
yet is dropped at once.

Or set `VINTED_BOT_TELEMETRY=false` in the environment or the `.env` file (see
[configuration](configuration.md)). Set either way, it wins over the switch in the
dashboard.
