# Running it somewhere

vinted-bot runs on a computer you choose and sends alerts from there. Two things decide
which computer: it has to stay on, and the internet connection it uses matters more than how
fast it is. A Raspberry Pi on your home internet does better than a fast server on an address
Vinted refuses.

| You have | Use | Keeps working when you walk away? |
|---|---|---|
| A Windows PC or a Mac | [the one-line installer](#on-your-own-computer) | Only while it's on and awake |
| A Raspberry Pi, mini PC or old laptop | [the one-line installer](#on-a-raspberry-pi-or-any-linux-box) or [Docker](#with-docker) | Yes |
| A NAS (Unraid, Synology, Umbrel, CasaOS) | [its app store or a compose project](#on-a-nas) | Yes |
| Nothing that stays on | [a small server you rent](#on-a-vps-or-a-cloud-host), a few euros a month | Yes |

> [!IMPORTANT]
> Vinted moved its search to a new address in September 2026, and versions before 2.0.0
> find nothing since. If you installed earlier, [update](#updating) first.

## On your own computer

The installer needs no admin rights and no Docker. It installs
[uv](https://docs.astral.sh/uv/) (a small tool that downloads Python and vinted-bot into
your user folder), asks whether to start vinted-bot when you log in, starts it, and opens
the dashboard at http://localhost:8000.

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

| | Your searches and log | Starts at login through |
|---|---|---|
| Windows | `%LOCALAPPDATA%\vinted-bot` | a shortcut in your Startup folder |
| macOS | `~/Library/Application Support/vinted-bot` | a LaunchAgent (macOS shows a "Background Items Added" notice once) |
| Linux | `~/.local/share/vinted-bot` | a systemd user service |

**Keep it awake.** Alerts stop while the computer sleeps. On a Mac the installer offers to
keep it awake while it's plugged in, for as long as vinted-bot runs; a closed MacBook lid
still sends it to sleep. On Windows, set Settings, System, Power, "Make my device sleep" to
Never while plugged in.

**Stop it** for now:

- Windows: in PowerShell, `Get-Process vinted-bot | Stop-Process`
- macOS: `launchctl bootout gui/$(id -u)/io.github.jasp-nerd.vinted-bot`
- Linux: `systemctl --user stop vinted-bot`

If you said no to starting at login, stopping is `pkill -f 'vinted-bot run'` on macOS
and Linux, and running the install command again starts it again.

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

The dashboard only listens on the Pi itself. From your own computer, open a tunnel and then
visit http://localhost:8000 there:

```bash
ssh -L 8000:localhost:8000 pi@raspberrypi.local
```

Or use Docker, below. Images are built for both x86 and ARM, so the same commands work on a
Pi.

## With Docker

```bash
mkdir vinted-bot && cd vinted-bot
curl -O https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/docker-compose.yml
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

Optional settings, such as a Telegram bot token, go in a `.env` file next to the compose
file:

```bash
curl -o .env https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/.env.example
```

Check it started:

```bash
docker compose logs -f vinted-bot
docker compose exec vinted-bot vinted-bot status
```

## On a NAS

- **Unraid:** search "vinted-bot" in Community Applications. Until it is listed, add the
  template from [deploy/unraid](../deploy/unraid/vinted-bot.xml) by hand.
- **Umbrel:** add the community app store described in [deploy/](../deploy/README.md#umbrel).
- **CasaOS and ZimaOS:** Custom Install, then import
  [deploy/casaos/docker-compose.yml](../deploy/casaos/docker-compose.yml).
- **Synology (DSM 7.2+):** Container Manager, Project, Create, and paste the compose file
  with `./data:/data` and your DSM user's `PUID`/`PGID` (usually 1026 and 100).
- **Portainer:** Stacks, Add stack, Repository, pointing at this repository.

[deploy/README.md](../deploy/README.md) has the details for each. On a NAS the dashboard is
usually reachable from your whole network, so set `VINTED_BOT_WEB_AUTH_TOKEN` as a
password.

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

Then open http://localhost:8000 on your own machine. Anything else needs
`VINTED_BOT_WEB_AUTH_TOKEN` set *and* a reverse proxy with TLS in front, because the
dashboard shows your webhook links.

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

Everything lives in one SQLite file, `app.db`:

- Installer: in the folder listed under [On your own computer](#on-your-own-computer).
- Docker: in the `vinted-bot-data` volume. Copy it out with
  `docker compose cp vinted-bot:/data/app.db ./app-backup.db`

Losing it costs you your searches and destinations, not much else: listings are pruned after
thirty days anyway.

## Updating

The dashboard tells you when a new version is out (it asks GitHub once a day; Settings,
Updates turns that off). What it offers depends on how vinted-bot was installed:

| Installed with | What updating looks like |
|---|---|
| The installer, starting by itself at login | **Update now** in the banner or under Settings, Updates. It installs the new version, restarts into it and the page reloads, all in about a minute. |
| The installer, without starting at login | **Update now** installs it; then restart vinted-bot (`vinted-bot run`, or run the install command again). On Windows the installer's launcher always restarts it. |
| `uv tool install` or `pipx install` yourself | The same button; restart it yourself afterwards, unless your own service sets `VINTED_BOT_SUPERVISED` (see [configuration](configuration.md#updating)). |
| Docker | `docker compose pull && docker compose up -d`, or the nightly updater below. A container never updates itself: whatever it changed inside itself would be lost the next time it is recreated. |
| `uvx` | `uvx vinted-bot@latest run` |
| A copy of the source | `git pull && uv sync`, then restart. |
| A NAS app store | The store's update button. |

Running the install command again always works too: it stops vinted-bot, updates it
and starts it again.

**Updating by itself.** Where the button restarts the app, Settings, Updates also offers
"Install updates by itself". It is off unless you turn it on. When it is on, a new release
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

No `.env` needed here either; copy `.env.example` to `.env` later for Telegram or other
tuning. For a systemd service, point `ExecStart` at `/path/to/.venv/bin/vinted-bot run`,
set `WorkingDirectory`, and add `Restart=always`. The app handles SIGTERM itself, so the
default `KillSignal` is correct and there is no need for a long `TimeoutStopSec`.
