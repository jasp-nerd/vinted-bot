# Running it somewhere

vinted-bot runs on a computer you choose and sends alerts from there. Two things decide
which computer: it has to stay on, and the internet connection it uses matters more than how
fast it is. A Raspberry Pi on your home internet does better than a fast server on an address
Vinted refuses.

| You have | Use | Keeps working when you walk away? |
|---|---|---|
| A Windows PC or a Mac | [the one-line installer](#on-your-own-computer) | Only while it's on and awake |
| A Raspberry Pi, mini PC or old laptop | [the one-line installer](#on-a-raspberry-pi-or-any-linux-box) or [Docker](#with-docker) | Yes |
| A NAS (Unraid, Synology, Umbrel, CasaOS) | [a template or a compose project](#on-a-nas) | Yes |
| Nothing that stays on | [a small server you rent](#on-a-vps-or-a-cloud-host), a few euros a month | Yes |

> [!IMPORTANT]
> Vinted moved its search to a new address in September 2026, and versions before 2.0.0
> find nothing since. If you installed earlier, [update](#updating) first.

## On your own computer

The installer needs no admin rights and no Docker. It installs
[uv](https://docs.astral.sh/uv/) (a small tool that downloads Python and vinted-bot into
your user folder), sets vinted-bot to start by itself when you log in, starts it, and opens
the dashboard at http://localhost:8000. It asks nothing: the choices about this computer
are switches in the dashboard (Settings, General), where each is explained, and the last
screen of setup shows them too.

**Windows 10 or 11.** Open PowerShell (Start menu, type `PowerShell`, press Enter), paste
this and press Enter:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/install.ps1 | iex"
```

**macOS.** Open Terminal (Cmd+Space, type `Terminal`, press Enter), paste this and press
Enter:

```bash
curl -LsSf https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/install.sh | sh
```

**Linux.** The same command as macOS.

Prefer to read a script before running it? Download [install.sh](../install.sh) or
[install.ps1](../install.ps1), read it, then run it (`sh install.sh`, or
`powershell -ExecutionPolicy ByPass -File install.ps1`). Both explain each step at the top.

Where things end up:

| | Your searches and log | Starts at login through | The vinted-bot icon |
|---|---|---|---|
| Windows | `%LOCALAPPDATA%\vinted-bot` | a shortcut in your Startup folder | the Start menu and your desktop |
| macOS | `~/Library/Application Support/vinted-bot` | a LaunchAgent (macOS shows a "Background Items Added" notice once) | Applications and Launchpad (or ⌘ Space, type vinted) |
| Linux | `~/.local/share/vinted-bot` | a systemd user service | your apps menu |

**Getting back to the dashboard.** Closing the browser doesn't stop vinted-bot; it keeps
running in the background. To open the dashboard again, click the vinted-bot icon, or
type `vinted-bot` in a terminal. Either opens it in your browser, and starts vinted-bot
first if it isn't running. Over SSH, or on a machine without a screen, `vinted-bot`
prints the address instead. You can also give the dashboard its own window: Settings,
General, "Use it like an app".

**Keep it awake.** Alerts stop while the computer sleeps. On a Mac, vinted-bot keeps it
awake while it's plugged in, for as long as vinted-bot runs (Settings, General, "Keep this
Mac awake while it's plugged in"); a closed MacBook lid still sends it to sleep. On
Windows, set Windows Settings, System, Power, "Make my device sleep" to Never while
plugged in.

**Starting at login** is on after installing, so alerts keep coming after a restart.
Switch it off in Settings, General, "Start by itself when you log in"; vinted-bot then
runs until you stop it or restart, and the icon starts it again.

**Stop it** (on holiday, say): Settings, General, **Stop vinted-bot**, or type
`vinted-bot stop`. It stays stopped, even after a restart, until you open it again with
the icon or `vinted-bot`.

| To | Type |
|---|---|
| Open the dashboard (and start it if needed) | `vinted-bot` |
| Stop it, and keep it stopped | `vinted-bot stop` |
| Start it without opening the browser | `vinted-bot start` |
| Restart it | `vinted-bot restart` |
| See what it's doing | `vinted-bot logs` (add `-f` to keep watching) |
| See where to open it from a phone | `vinted-bot address` |

A terminal you opened before installing doesn't know the `vinted-bot` command yet; open a
new one.

**Remove it.** Your searches stay in the folder above until you delete it.

```powershell
powershell -ExecutionPolicy ByPass -c '$env:VINTED_BOT_UNINSTALL=1; irm https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/install.ps1 | iex'
```

```bash
curl -LsSf https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/install.sh | sh -s -- --uninstall
```

## On a Raspberry Pi or any Linux box

Any always-on machine works: a Raspberry Pi 4 or 5, an old laptop, a mini PC. vinted-bot
idles at a few percent of one core and a few dozen megabytes of memory.

Why home first:

- Home connections are challenged far less often than datacenter ones by anti-bot systems.
- Nothing to pay, and no free tier that can be withdrawn.
- The database, your webhook links and your Telegram token stay on hardware you own.

The one-line installer above works on a Pi (64-bit Raspberry Pi OS). Say yes to starting at
login, and it also offers the one command that makes it start at boot with nobody logged in:

```bash
sudo loginctl enable-linger $USER
```

The dashboard only listens on the Pi itself at first. Installing over SSH, the installer
asks whether your phone and other devices on your network may open it; say yes and it sets
a password, prints the address (such as `http://raspberrypi.local:8000`) and a QR code to
scan with your phone. To do that later, or to see the address and QR code again:

```bash
vinted-bot address --allow-network   # let the network in, with a password
vinted-bot address                   # where to open it, any time
```

Give the Pi a fixed address in your router (often called "DHCP reservation") so the
address doesn't change after the router restarts. `raspberrypi.local` works from iPhones,
Macs and most computers; some Android phones need the number instead.

Prefer to keep it on the Pi only? Open a tunnel from your own computer, then visit
http://localhost:8000 there:

```bash
ssh -L 8000:localhost:8000 pi@raspberrypi.local
```

Or use Docker, below. Images are built for both x86 and ARM, so the same commands work on a
Pi.

## With Docker

```bash
mkdir vinted-bot && cd vinted-bot
curl -fsSLO https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docker-compose.yml
docker compose up -d
```

Then open http://localhost:8000 on that machine. No configuration file is needed:
searches and alert destinations are set up in the dashboard. `restart: unless-stopped` brings
it back after a reboot or a power cut.

Worth a look in `docker-compose.yml`:

- **`TZ`**, your time zone, for times in the dashboard and quiet hours.
- **Image tags.** `latest` is the newest release. `edge` follows the main branch, with fixes
  before they are released. `2`, `2.1` or `2.1.0` pin a version.
- **A folder instead of a volume.** Swap `vinted-bot-data:/data` for `./data:/data` to
  keep the database next to the compose file, then set `PUID` and `PGID` to the folder's
  owner (`id` prints yours). The container hands `/data` to that user before starting and
  runs as it, never as root.
- **Automatic updates**, if you want them: `docker compose --profile autoupdate up -d` adds
  a maintained fork of Watchtower that updates vinted-bot once a night. It needs the
  Docker socket, so it is off unless you ask for it.

Everything else, the Telegram bot and the dashboard password included, is set up in the
dashboard. Optional process settings go in the `environment:` block of
`docker-compose.yml`, which lists the common ones commented out. Uncomment a line, then run
`docker compose up -d`: a plain `docker compose restart` keeps the old values. Every
setting is in [configuration](configuration.md).

Coming from an older compose file that read a `.env` file next to it? Either move those
lines into `environment:` (as `NAME: "value"`), or add `env_file: .env` under the service
yourself. The default no longer reads one, because the form that made the file optional
needs Docker Compose 2.24 or later, which Synology's Container Manager and older Linux
distributions don't have.

To open the dashboard from your phone, set a password in Settings first, then change the
port line in `docker-compose.yml` from `127.0.0.1:8000:8000` to `8000:8000` and run
`docker compose up -d`. Inside Docker the port mapping decides who can connect, so the
dashboard's phone access switch is not offered there.

Check it started:

```bash
docker compose logs -f vinted-bot
docker compose exec vinted-bot vinted-bot status
```

## On a NAS

- **Unraid:** it isn't in Community Applications yet. Add the template by hand: in the
  Unraid terminal, run

  ```bash
  curl -fsSL -o /boot/config/plugins/dockerMan/templates-user/my-vinted-bot.xml \
    https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/deploy/unraid/vinted-bot.xml
  ```

  then Docker, Add Container, and pick `vinted-bot` under Template.
- **Umbrel:** it isn't in an Umbrel app store yet. The files for one are ready in
  [deploy/umbrel](../deploy/README.md#umbrel); until a store is published, use the
  [Docker steps](#with-docker) over SSH (`ssh umbrel@umbrel.local`).
- **CasaOS and ZimaOS:** Custom Install, then import
  [deploy/casaos/docker-compose.yml](../deploy/casaos/docker-compose.yml).
- **Synology (DSM 7.2+):** Container Manager, Project, Create, and paste the compose file
  with `./data:/data` and your DSM user's `PUID`/`PGID` (usually 1026 and 100).
- **Portainer:** Stacks, Add stack, Repository, pointing at this repository.

[deploy/README.md](../deploy/README.md) has the details for each. On a NAS the dashboard is
usually reachable from your whole network, so set a password in the dashboard's Settings
(or `VINTED_BOT_WEB_AUTH_TOKEN` in the app's settings on the NAS) before anything else.

## On a VPS or a cloud host

Reasonable if you have no machine at home. Around €5 a month:

| Provider | Notes |
|---|---|
| Hetzner CX22 | Cheapest sensible option. Their address ranges have a mixed reputation with anti-bot systems, so test before committing. |
| DigitalOcean | Costs a little more, easiest control panel if this is your first server. |
| Contabo | Cheap, generous specs, variable performance. |

Setup is the same as on a Pi: the one-line installer or Docker. **Before you commit**, check
that Vinted answers that server (see
[Vinted reachable from this machine](troubleshooting.md#vinted-reachable-from-this-machine)).
If it doesn't, pick a different provider rather than fight it.

On a VPS, do not expose port 8000 to the internet directly. Keep the loopback binding and
reach the dashboard through an SSH tunnel:

```bash
ssh -L 8000:localhost:8000 you@your-server
```

Then open http://localhost:8000 on your own machine. Anything else needs a password (set
in Settings, or `VINTED_BOT_WEB_AUTH_TOKEN`) *and* a reverse proxy with TLS in front,
because the dashboard shows your webhook links. Tailscale, below, does both for you.

## From anywhere, with Tailscale

The dashboard opens on your home network. To open it on your phone anywhere, without
putting it on the internet, use [Tailscale](https://tailscale.com) (free for personal use):
a private network between your own devices.

1. Install Tailscale on the computer or Pi running vinted-bot and on your phone, and sign
   in to the same account on both.
2. On the machine running vinted-bot, give the dashboard a private https address:

   ```bash
   tailscale serve --bg 8000
   ```

   It prints an address like `https://raspberrypi.your-tailnet.ts.net`.
3. Tell vinted-bot that address, so the Dashboard button in your alerts and the Telegram
   `/dashboard` command use it: set `VINTED_BOT_WEB_PUBLIC_URL` to it (in the `.env` file
   or the container's environment) and restart (`vinted-bot restart`).

Only devices signed in to your Tailscale account can open that address. Don't use
`tailscale funnel`: that puts the dashboard on the public internet. On a VPS, Tailscale
replaces the SSH tunnel above.

**Platforms that run the image for you** (Render, Railway, Coolify) have templates in
[deploy/](../deploy/README.md). All are paid for an always-on app with storage, and they send
traffic from shared datacenter addresses, which Vinted challenges more often. Run the
reachability check from there before relying on one.

### Free tiers worth avoiding

**Oracle Cloud Always Free.** Their reclamation policy deletes instances that stay idle, and
a polling app idles at a few percent CPU by design. They also cut the free ARM allowance in
2026 with little notice. Your instance will eventually disappear.

**Render's free tier.** Free web services sleep after fifteen minutes without visits and
can't keep a disk, so searches would be lost and checks would stop.

**Railway and Fly.io.** Neither has a free tier that stays on with storage. Both work fine as
paid hosts, at roughly VPS prices.

## Backups

Everything lives in one SQLite database, `app.db`. Don't copy that file while vinted-bot
runs: recent changes sit in `app.db-wal` beside it until SQLite folds them in, so a plain
copy can be missing them, or be empty. `vinted-bot backup` writes a complete copy of the
database to one file, safely, while the app keeps running:

- Installer: `vinted-bot backup ~/vinted-bot-backup.db` (Windows:
  `vinted-bot backup $HOME\vinted-bot-backup.db`). The database itself is in the folder
  listed under [On your own computer](#on-your-own-computer).
- Docker: make the copy inside the container, then take it out:

  ```bash
  docker compose exec vinted-bot vinted-bot backup /data/backup.db
  docker compose cp vinted-bot:/data/backup.db ./vinted-bot-backup.db
  ```

  The data lives in a volume Docker names after the project folder, so with the shipped
  compose file in a folder called `vinted-bot` it is `vinted-bot_vinted-bot-data`
  (`docker volume ls` shows it).

To restore, stop vinted-bot, put the copy in place of `app.db` (and delete any `app.db-wal`
and `app.db-shm` beside it), then start it again.

Losing it costs you your searches and destinations, not much else: listings are pruned after
thirty days anyway.

## Updating

vinted-bot asks GitHub once a day whether a new version is out (Settings, Updates turns
that off). When one is, the dashboard shows a banner, and destinations that get status
alerts get one message saying so and how to install it. `vinted-bot --version`,
`vinted-bot status` and `/api/health` say it too. What updating looks like depends on how
vinted-bot was installed:

| Installed with | What updating looks like |
|---|---|
| The installer, starting by itself at login | **Update now** in the banner or under Settings, Updates. It installs the new version, restarts into it and the page reloads, all in about a minute. |
| The installer, without starting at login | **Update now** installs it; then restart vinted-bot (`vinted-bot run`, or run the install command again). On Windows the installer's launcher always restarts it. |
| `uv tool install` or `pipx install` yourself | The same button; restart it yourself afterwards, unless your own service sets `VINTED_BOT_SUPERVISED` (see [configuration](configuration.md#updating)). |
| Docker | `docker compose pull && docker compose up -d`, or the nightly updater below. A container never updates itself: whatever it changed inside itself would be lost the next time it is recreated. |
| `uvx` | `uvx vinted-bot@latest run` |
| A copy of the source | `git pull && uv sync`, then restart. |
| A NAS template or app store | Pull the new image: the NAS's own update button for the container (Unraid: Docker, Check for Updates; CasaOS: the app's update; Synology and Portainer: re-pull and redeploy the project). |

Running the install command again always works too: it stops vinted-bot, updates it
and starts it again.

**Updating by itself.** Where the button restarts the app, Settings, Updates also offers
"Install updates by itself". It starts out on for a new install from the installers;
copies set up before that became the default keep it off unless you turn it on. When it is
on, a new release
is installed between 4 and 5 at night (by the time zone in Settings), never while an alert is
on its way out, and destinations that get status alerts are told afterwards. If an update
fails, it tries again the next night. With Docker, the optional nightly updater in the
compose file does the same job (`docker compose --profile autoupdate up -d`).

**What it runs.** The button runs `uv tool upgrade vinted-bot` (or
`pipx upgrade vinted-bot`), the same command you would type, and only when GitHub's
latest release is newer than what is running. The new version comes from PyPI, like the
first install did. If the command fails, or installs nothing newer, the app keeps running
the version it was on and the page says why, with uv's own output underneath. On Windows a
running program cannot replace its own files, so the app closes and the installer's launcher
runs the upgrade, then starts it again; the log file has uv's output.

Database changes are applied automatically at startup. If an update misbehaves, see
[Everything is broken after an update](troubleshooting.md#everything-is-broken-after-an-update).

## Running from source

For working on the code, or if you'd rather manage Python yourself:

```bash
git clone https://github.com/jasp-nerd/vinted-bot && cd vinted-bot
uv sync
uv run vinted-bot run --open
```

No `.env` needed here either: the Telegram bot, the password and phone access are set in
the dashboard. Copy `.env.example` to `.env` only for tuning. For a systemd service, point `ExecStart` at `/path/to/.venv/bin/vinted-bot run`,
set `WorkingDirectory`, and add `Restart=always`. The app handles SIGTERM itself, so the
default `KillSignal` is correct and there is no need for a long `TimeoutStopSec`.
