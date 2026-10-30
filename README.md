<div align="center">

**English** · [Français](https://github.com/jasp-nerd/vinted-bot/blob/main/README.fr.md)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docs/media/banner-dark.png">
  <img src="https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docs/media/banner.png" alt="vinted-bot: alerts for your Vinted searches" width="820">
</picture>

# vinted-bot: free Vinted bot for new listing alerts

**Vinted doesn't tell you when your saved search gets something new. This does.**

Paste a Vinted search, choose where alerts go, and get a message with the photos and the price<br>
you'll actually pay as soon as a new listing turns up. Free forever, open source, on your own computer,<br>
no Vinted account and no monthly fee, where paid Vinted bots charge €5 to €300 a month.

[![CI](https://github.com/jasp-nerd/vinted-bot/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/jasp-nerd/vinted-bot/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/jasp-nerd/vinted-bot?color=007782)](https://github.com/jasp-nerd/vinted-bot/releases)
[![PyPI](https://img.shields.io/pypi/v/vinted-bot?color=007782&label=pypi)](https://pypi.org/project/vinted-bot/)
[![Container image](https://img.shields.io/badge/ghcr.io-vinted--bot-2496ED?logo=docker&logoColor=white)](https://github.com/jasp-nerd/vinted-bot/pkgs/container/vinted-bot)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![MIT](https://img.shields.io/badge/license-MIT-green)](https://github.com/jasp-nerd/vinted-bot/blob/main/LICENSE)

**[Install](#install)** · **[Let an AI help](#let-an-ai-walk-you-through-it)** · [Website](https://vinted-bot.jaspnerd.dev) · [Docs](#docs) · [Report a problem](https://github.com/jasp-nerd/vinted-bot/issues/new/choose)

<img src="https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docs/media/dashboard.png" width="820" alt="The dashboard: a band showing which searches are being watched and how each is doing, then new finds as photo cards with the price including fees, deal badges and the search that found them">

</div>

## How it works

1. **Search on Vinted** the way you always do and copy the link. Or build the search in the dashboard.
2. **Paste it into vinted-bot** and pick where alerts go: Discord, Telegram, your phone, email.
3. **Get a message** for each new listing, with photos, the total price including buyer protection, size, condition and seller rating.

It checks every minute. The first check is silent on purpose, so you only hear about listings that appear after you added the search.

> [!IMPORTANT]
> Vinted moved its search to a new address in September 2026, and versions before 2.0 have found nothing since. If you installed earlier, [update](#updating).

## Install

| You have | Use | Keeps working when you walk away? |
|---|---|---|
| A Windows PC | [Windows](#windows) | While it's on and awake |
| A Mac | [macOS](#macos) | While it's on and awake |
| A Raspberry Pi or a Linux machine | [Linux and Raspberry Pi](#linux-and-raspberry-pi) | Yes |
| Docker already installed | [Docker](#docker) | Yes, if the machine stays on |
| Python already installed | `uvx vinted-bot run` or `pipx install vinted-bot` | While it's on and awake |
| Unraid, Synology, Umbrel or CasaOS | [NAS](#nas) | Yes |
| Nothing that stays on | [Cloud](#cloud), a few euros a month | Yes |

The installers need no admin rights and no Docker, and open the dashboard at http://localhost:8000 when they finish. Run the same command again to update.

### Windows

Open **PowerShell** (Start menu, type `PowerShell`, press Enter), paste this and press Enter:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/install.ps1 | iex"
```

### macOS

Open **Terminal** (press Cmd+Space, type `Terminal`, press Enter), paste this and press Enter:

```bash
curl -LsSf https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/install.sh | sh
```

### Linux and Raspberry Pi

The same command works on any Linux and on a Raspberry Pi with 64-bit Raspberry Pi OS:

```bash
curl -LsSf https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/install.sh | sh
```

Prefer to read a script before running it? Download [install.sh](https://github.com/jasp-nerd/vinted-bot/blob/main/install.sh) or [install.ps1](https://github.com/jasp-nerd/vinted-bot/blob/main/install.ps1) first; each explains its steps at the top.

### Docker

```bash
mkdir vinted-bot && cd vinted-bot
curl -fsSLO https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docker-compose.yml
docker compose up -d
```

Then open http://localhost:8000. Images run on x86 and ARM. In Windows PowerShell, download the file with `Invoke-WebRequest <link> -OutFile docker-compose.yml` instead of `curl`.

### NAS

Unraid, Umbrel, CasaOS, Synology and Portainer each take a ready-made template or the compose file: see [On a NAS](https://github.com/jasp-nerd/vinted-bot/blob/main/docs/self-hosting.md#on-a-nas).

### Cloud

A small rented server or a platform such as Render or Railway works, but none is free once it has to stay on. Vinted refuses some datacenter addresses, so [read this first](https://github.com/jasp-nerd/vinted-bot/blob/main/docs/self-hosting.md#on-a-vps-or-a-cloud-host).

## Let an AI walk you through it

Not sure where to start? Copy this into ChatGPT, Claude or Gemini and it will guide you one step at a time:

```text
Please help me install and set up vinted-bot, a free open-source app that watches my Vinted searches and sends me a message on Discord or Telegram when a new listing matches.

First read its setup guide: https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/llms.txt
If you can't open links, tell me and I'll paste it in.

How I'd like you to help:
- I'm not technical. Start by asking what computer I have and whether it stays switched on.
- Give me one small step at a time. Tell me exactly where to click or what to paste, and what I should see afterwards. Wait for me to say it worked before the next step.
- Only use the commands from the guide. Don't invent commands or settings.
- Never ask me to paste my Discord webhook link, Telegram token or any password into this chat. Tell me where to put them in the app instead.
- If something goes wrong, ask me for the exact error message, then help using the troubleshooting part of the guide.

Once it's installed, help me add my first Vinted search and check that a test alert arrives.
```

Or open it directly: **[Open in Claude](https://claude.ai/new?q=Please%20help%20me%20install%20and%20set%20up%20vinted-bot%2C%20a%20free%20open-source%20app%20that%20watches%20my%20Vinted%20searches%20and%20sends%20me%20a%20message%20on%20Discord%20or%20Telegram%20when%20a%20new%20listing%20matches.%0A%0AFirst%20read%20its%20setup%20guide%3A%20https%3A%2F%2Fraw.githubusercontent.com%2Fjasp-nerd%2Fvinted-bot%2Fmain%2Fllms.txt%0AIf%20you%20can%27t%20open%20links%2C%20tell%20me%20and%20I%27ll%20paste%20it%20in.%0A%0AHow%20I%27d%20like%20you%20to%20help%3A%0A-%20I%27m%20not%20technical.%20Start%20by%20asking%20what%20computer%20I%20have%20and%20whether%20it%20stays%20switched%20on.%0A-%20Give%20me%20one%20small%20step%20at%20a%20time.%20Tell%20me%20exactly%20where%20to%20click%20or%20what%20to%20paste%2C%20and%20what%20I%20should%20see%20afterwards.%20Wait%20for%20me%20to%20say%20it%20worked%20before%20the%20next%20step.%0A-%20Only%20use%20the%20commands%20from%20the%20guide.%20Don%27t%20invent%20commands%20or%20settings.%0A-%20Never%20ask%20me%20to%20paste%20my%20Discord%20webhook%20link%2C%20Telegram%20token%20or%20any%20password%20into%20this%20chat.%20Tell%20me%20where%20to%20put%20them%20in%20the%20app%20instead.%0A-%20If%20something%20goes%20wrong%2C%20ask%20me%20for%20the%20exact%20error%20message%2C%20then%20help%20using%20the%20troubleshooting%20part%20of%20the%20guide.%0A%0AOnce%20it%27s%20installed%2C%20help%20me%20add%20my%20first%20Vinted%20search%20and%20check%20that%20a%20test%20alert%20arrives.)** · **[Open in ChatGPT](https://chatgpt.com/?q=Please%20help%20me%20install%20and%20set%20up%20vinted-bot%2C%20a%20free%20open-source%20app%20that%20watches%20my%20Vinted%20searches%20and%20sends%20me%20a%20message%20on%20Discord%20or%20Telegram%20when%20a%20new%20listing%20matches.%0A%0AFirst%20read%20its%20setup%20guide%3A%20https%3A%2F%2Fraw.githubusercontent.com%2Fjasp-nerd%2Fvinted-bot%2Fmain%2Fllms.txt%0AIf%20you%20can%27t%20open%20links%2C%20tell%20me%20and%20I%27ll%20paste%20it%20in.%0A%0AHow%20I%27d%20like%20you%20to%20help%3A%0A-%20I%27m%20not%20technical.%20Start%20by%20asking%20what%20computer%20I%20have%20and%20whether%20it%20stays%20switched%20on.%0A-%20Give%20me%20one%20small%20step%20at%20a%20time.%20Tell%20me%20exactly%20where%20to%20click%20or%20what%20to%20paste%2C%20and%20what%20I%20should%20see%20afterwards.%20Wait%20for%20me%20to%20say%20it%20worked%20before%20the%20next%20step.%0A-%20Only%20use%20the%20commands%20from%20the%20guide.%20Don%27t%20invent%20commands%20or%20settings.%0A-%20Never%20ask%20me%20to%20paste%20my%20Discord%20webhook%20link%2C%20Telegram%20token%20or%20any%20password%20into%20this%20chat.%20Tell%20me%20where%20to%20put%20them%20in%20the%20app%20instead.%0A-%20If%20something%20goes%20wrong%2C%20ask%20me%20for%20the%20exact%20error%20message%2C%20then%20help%20using%20the%20troubleshooting%20part%20of%20the%20guide.%0A%0AOnce%20it%27s%20installed%2C%20help%20me%20add%20my%20first%20Vinted%20search%20and%20check%20that%20a%20test%20alert%20arrives.)**

## What you get

<table>
<tr>
<td width="50%" valign="top">

**Finding the right listings**

- Price limits on what you actually pay, buyer protection included. Vinted's own filter ignores the fee.
- Words a title must have (with alternatives such as `501|505`) and words to skip.
- A deal badge when a listing is well under the search's typical price, and a deals-only option.
- Seller rating, number of reviews and country. Block a seller for good.
- One search across several country sites, and quiet hours that hold alerts until morning.

</td>
<td width="50%" valign="top">

**Getting told**

- Discord cards with the photo gallery, the total price and Buy, Message and Open buttons.
- Telegram photo cards, plus `/list`, `/pause` and `/add` to manage searches from the chat.
- ntfy push notifications to your phone, no account needed.
- Email, Slack, Pushover, Gotify, Matrix and more through [Apprise](https://github.com/caronc/apprise).
- RSS feeds and signed JSON webhooks for your own automations.

</td>
</tr>
<tr>
<td valign="top">

**The dashboard**

- A live feed of finds that looks like Vinted's own grid: save, hide, block the seller.
- Setup on first run: paste a link or build the search, then send a test alert.
- "Not sent": every skipped listing with the reason it was skipped.
- A watchlist for price drops and sold items, and for new uploads from a seller.
- Stats: finds per day, the busiest hours, how quickly alerts arrive.

</td>
<td valign="top">

**Staying reliable**

- **It tells you when it stops working.** Each search says in plain words how it's doing, and a watchdog notices when Vinted goes quiet and renews the session itself.
- No lost or doubled alerts: each one is saved before it's sent and sent once.
- No Vinted account and no login, so there is no account to lose.
- No flood of old listings when you add a search.

</td>
</tr>
</table>

## Alerts

<table>
<tr>
<td align="center" valign="top"><img src="https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docs/media/alert-discord.png" height="420" alt="A Discord alert for Levi's 501 jeans: three photos, the total price €23.80 with a 'good deal, 24% under typical' badge, the asking price plus buyer protection, size, condition, brand, seller rating, and Buy, Message seller, Open on Vinted and eBay sold buttons"><br><sub><b>Discord</b></sub></td>
<td align="center" valign="top"><img src="https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docs/media/alert-telegram.png" height="420" alt="The same alert in Telegram: the photo, the total price with the deal note, title, size, condition, brand, seller rating, site and time, green Buy and blue Open on Vinted buttons, and Mute and Hide buttons"><br><sub><b>Telegram</b></sub></td>
<td align="center" valign="top"><img src="https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docs/media/phone.png" height="420" alt="The dashboard on a phone: the searches being watched, filter chips and the newest finds as photo cards, with a tab bar at the bottom"><br><sub><b>Dashboard on a phone</b></sub></td>
</tr>
</table>

<details>
<summary>More screenshots</summary>
<br>
<img src="https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docs/media/setup.png" width="820" alt="Setup: building a first search with words, category, brand, sizes, condition and a top price, beside a live count of 23 matching listings and how many each filter removed">
<br><sub>Setting up a first search, with a live count of what it would find</sub>
<br><br>
<img src="https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docs/media/stats.png" width="820" alt="The stats page: finds, alerts sent, median time from listing to alert, delivery rate, finds per day, a weekday by hour heatmap and a chart of how fast alerts arrive">
<br><sub>Stats</sub>
</details>

## Updating

- **Installer:** click **Update now** when the dashboard says a new version is out, or run the install command again. Settings, Updates can also install new versions by itself at night.
- **Docker:** `docker compose pull && docker compose up -d`
- **NAS app stores:** the store's update button.

Your searches are kept, and database changes apply by themselves at startup. What changed is in the [changelog](https://github.com/jasp-nerd/vinted-bot/blob/main/CHANGELOG.md).

## FAQ

**Can my Vinted account get banned?** It never logs in, so no account is involved. What Vinted can do is stop answering your internet address for a while if it's asked too often. The app slows down by itself when that happens, and the dashboard tells you.

**Is it really free?** Yes. MIT licence, no paid tier, no sign-up. Paid Vinted alert services cost from about €5 a month, and some charge up to €300.

**Does my computer have to stay on?** Yes. Alerts come from the machine it runs on, so they stop while it sleeps. A Raspberry Pi, a NAS or an old laptop left plugged in fixes that: see [Running it somewhere](https://github.com/jasp-nerd/vinted-bot/blob/main/docs/self-hosting.md).

**Why isn't it instant?** Vinted adds new listings to its search a few minutes after they're uploaded, so every tool that reads the search, paid or free, sees them then. Checking more often doesn't change that. It's fast enough for collectors and size hunters, not for racing bots that buy automatically.

**Is this allowed?** Vinted's terms prohibit automated access, so running it is your own call. It reads public listings as a logged-out visitor, slowly. More in [docs/legal.md](https://github.com/jasp-nerd/vinted-bot/blob/main/docs/legal.md).

## Docs

- [Running it somewhere](https://github.com/jasp-nerd/vinted-bot/blob/main/docs/self-hosting.md): your own computer, a Raspberry Pi, Docker, a NAS, a cloud server, backups and updates.
- [Configuration](https://github.com/jasp-nerd/vinted-bot/blob/main/docs/configuration.md): every setting, the command line, each kind of destination and the dashboard password. Nothing is required to start.
- [Troubleshooting](https://github.com/jasp-nerd/vinted-bot/blob/main/docs/troubleshooting.md): nothing arrives, "stale", 403s, and the one-line test that shows whether Vinted answers your connection.
- [How it works](https://github.com/jasp-nerd/vinted-bot/blob/main/docs/architecture.md) and [the rules](https://github.com/jasp-nerd/vinted-bot/blob/main/docs/legal.md), for the curious.
- [llms.txt](https://github.com/jasp-nerd/vinted-bot/blob/main/llms.txt): the setup guide an AI assistant reads.

## Contributing

Bug reports with the log attached help most: the [issue form](https://github.com/jasp-nerd/vinted-bot/issues/new/choose) asks for what's needed. For code, see [CONTRIBUTING.md](https://github.com/jasp-nerd/vinted-bot/blob/main/CONTRIBUTING.md). Security problems go through [SECURITY.md](https://github.com/jasp-nerd/vinted-bot/blob/main/SECURITY.md).

## Support

It's free, without ads, and it stays that way. If it got you a good find, you can buy me a coffee or [sponsor it on GitHub](https://github.com/sponsors/jasp-nerd). A star helps other people find it.

[![Support me on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/jaspnerd)

---

<sub>Independent open-source tool. Not affiliated with Vinted. It reads public listings anonymously and never logs in, buys, or lists anything; buying for you is deliberately not a feature. MIT licensed.</sub>
