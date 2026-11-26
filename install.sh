#!/bin/sh
# Installs vinted-bot on macOS or Linux (including a Raspberry Pi). No Docker, no admin
# password, nothing outside your home folder.
#
#   curl -LsSf https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/install.sh | sh
#
# What it does, in order:
#   1. installs uv (https://docs.astral.sh/uv/), the tool that fetches Python and
#      vinted-bot, if you don't have it yet
#   2. installs vinted-bot with its own private copy of Python
#   3. sets it to start by itself when you log in (a switch in its Settings)
#   4. starts it and opens the dashboard in your browser
#
# Run the same command again to update. To remove it (your searches are kept):
#
#   curl -LsSf https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/install.sh | sh -s -- --uninstall
#
# Options (after `sh -s --` when piping):
#   --uninstall        remove vinted-bot and its start-at-login entry
#   --autostart        start at login (the default)
#   --no-autostart     don't start at login
#   --no-browser       don't open the dashboard at the end
#
# Environment variables, for anyone scripting this:
#   VINTED_BOT_AUTOSTART=yes|no    same as --autostart / --no-autostart
#   VINTED_BOT_NO_BROWSER=1        same as --no-browser
#   VINTED_BOT_DATA_DIR=...        where the database and log live
#   VINTED_BOT_WEB_PORT=...        dashboard port, if 8000 is taken
#   VINTED_BOT_PACKAGE=...         what to install (see PACKAGE below)
#   UV_NO_MODIFY_PATH=1               leave your shell's PATH settings alone
#   VINTED_BOT_ALLOW_ROOT=1        install as root anyway (not recommended)

# Everything is inside functions and only `main "$@"` at the very end runs anything, so a
# download cut off halfway can never run half an install.

set -eu

# Where vinted-bot comes from: the latest release on PyPI. Set VINTED_BOT_PACKAGE to
# install something else, such as a GitHub archive of an unreleased branch.
PACKAGE="${VINTED_BOT_PACKAGE:-vinted-bot}"
PORT="${VINTED_BOT_WEB_PORT:-8000}"
URL="http://localhost:$PORT"
LABEL="io.github.jasp-nerd.vinted-bot"
SCRIPT_URL="https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main/install.sh"

say() { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*" >&2; }
die() {
    warn ""
    warn "Sorry, that didn't work: $*"
    warn "If you're stuck, open an issue and paste everything above:"
    warn "  https://github.com/jasp-nerd/vinted-bot/issues/new/choose"
    exit 1
}

os() { uname -s; }

data_dir() {
    if [ -n "${VINTED_BOT_DATA_DIR:-}" ]; then
        printf '%s\n' "$VINTED_BOT_DATA_DIR"
    elif [ "$(os)" = Darwin ]; then
        printf '%s\n' "$HOME/Library/Application Support/vinted-bot"
    else
        printf '%s\n' "${XDG_DATA_HOME:-$HOME/.local/share}/vinted-bot"
    fi
}

systemd_unit() {
    printf '%s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/vinted-bot.service"
}

launchd_plist() {
    printf '%s\n' "$HOME/Library/LaunchAgents/$LABEL.plist"
}

# --- uv ------------------------------------------------------------------------------

find_uv() {
    if command -v uv >/dev/null 2>&1; then
        command -v uv
        return 0
    fi
    for candidate in "${UV_INSTALL_DIR:-$HOME/.local/bin}/uv" "${XDG_BIN_HOME:-$HOME/.local/bin}/uv" "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
        if [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

# Prints only the path to uv on stdout; everything the uv installer says goes to stderr.
ensure_uv() {
    if find_uv; then
        return 0
    fi
    warn "Installing uv, the helper that downloads Python and vinted-bot for you..."
    curl -LsSf https://astral.sh/uv/install.sh | sh >&2 || die "uv could not be installed."
    find_uv || die "uv installed but can't be found. Open a new terminal and run this again."
}

# --- Questions -------------------------------------------------------------------------

# With `curl | sh` the script itself arrives on stdin, so answers have to be read from the
# terminal directly. With no terminal at all (a script, CI), the answer is the default.
ask() {
    question=$1
    default=$2
    if ! (: </dev/tty) 2>/dev/null; then
        [ "$default" = yes ]
        return
    fi
    if [ "$default" = yes ]; then hint="[Y/n]"; else hint="[y/N]"; fi
    printf '%s %s ' "$question" "$hint" >/dev/tty
    answer=""
    read -r answer </dev/tty || answer=""
    case "$answer" in
        [yY]*) return 0 ;;
        [nN]*) return 1 ;;
        *) [ "$default" = yes ] ;;
    esac
}

wants() {
    setting=$1
    question=$2
    case "$setting" in
        default | yes | 1 | true) return 0 ;;
        no | 0 | false) return 1 ;;
    esac
    ask "$question" yes
}

# --- Stopping and starting ------------------------------------------------------------

stop_everything() {
    bin=$1
    if [ "$(os)" = Darwin ]; then
        launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    elif command -v systemctl >/dev/null 2>&1 && [ -f "$(systemd_unit)" ]; then
        systemctl --user stop vinted-bot.service 2>/dev/null || true
    fi
    # A copy started in the background by an earlier run of this script.
    if command -v pkill >/dev/null 2>&1; then
        pkill -f "$bin/vinted-bot run" 2>/dev/null || true
        pkill -f "vinted_bot run" 2>/dev/null || true
    fi
    # Give it a moment to let go of the port.
    i=0
    while [ $i -lt 10 ] && port_answers; do
        sleep 1
        i=$((i + 1))
    done
}

remove_autostart() {
    if [ "$(os)" = Darwin ]; then
        launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
        rm -f "$(launchd_plist)" "$(data_dir)/$LABEL.plist"
    elif [ -f "$(systemd_unit)" ]; then
        systemctl --user disable --now vinted-bot.service >/dev/null 2>&1 || true
        rm -f "$(systemd_unit)"
        systemctl --user daemon-reload >/dev/null 2>&1 || true
    fi
}

xml_escape() {
    printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

# Writes the LaunchAgent to stdout.
#
# KeepAlive with SuccessfulExit=false starts it again after any exit except a clean one
# (code 0): a crash, and the exit with code 75 that ends an update from the dashboard;
# VINTED_BOT_SUPERVISED tells the app it can count on that. A clean exit is someone
# stopping it (Settings, or `vinted-bot stop`), and that has to stick. ThrottleInterval
# only delays a restart when the app exits within 30 seconds of starting, which keeps a
# crash at startup from spinning.
write_plist() {
    exe=$(xml_escape "$1")
    dir=$(xml_escape "$2")
    cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$exe</string>
    <string>run</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$dir</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>VINTED_BOT_DB_PATH</key>
    <string>$dir/app.db</string>
    <key>VINTED_BOT_WEB_PORT</key>
    <string>$PORT</string>
    <key>VINTED_BOT_SUPERVISED</key>
    <string>launchd</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>ThrottleInterval</key>
  <integer>30</integer>
  <key>StandardOutPath</key>
  <string>$dir/vinted-bot.log</string>
  <key>StandardErrorPath</key>
  <string>$dir/vinted-bot.log</string>
</dict>
</plist>
EOF
}

autostart_macos() {
    exe=$1
    dir=$2
    setting=$3
    # Starting at login switched off in Settings: the LaunchAgent waits in the data folder
    # instead of ~/Library/LaunchAgents (see control.py). An update keeps that choice;
    # --autostart switches it back on.
    plist=$(launchd_plist)
    at_login=yes
    if [ "$setting" = default ] && [ -f "$dir/$LABEL.plist" ] && [ ! -f "$plist" ]; then
        plist="$dir/$LABEL.plist"
        at_login=no
    else
        rm -f "$dir/$LABEL.plist"
    fi
    mkdir -p "$(dirname "$plist")"
    write_plist "$exe" "$dir" >"$plist"
    # bootout finishes in the background, so the first bootstrap can race it.
    i=0
    until launchctl bootstrap "gui/$(id -u)" "$plist" 2>/dev/null; do
        i=$((i + 1))
        if [ $i -ge 5 ]; then
            # Typically: logged in over SSH, where there is no desktop session to start in.
            rm -f "$plist"
            return 1
        fi
        sleep 1
    done
    if [ $at_login = yes ]; then
        say "It starts by itself whenever you log in (switch that off in Settings, General)."
        say "macOS may show a \"Background Items Added\" notice. That's this; it's expected."
    fi
}

# Restart=on-failure starts it again after any exit but a clean one: a crash, and the
# exit with code 75 that ends an update from the dashboard; VINTED_BOT_SUPERVISED tells
# the app it can count on that. A clean exit (code 0) is someone stopping it (Settings,
# or `vinted-bot stop`), and that has to stick. Three seconds
# between starts keeps a crash at startup under systemd's limit of five starts in ten
# seconds, so it keeps trying instead of giving up.
write_unit() {
    exe=$1
    dir=$2
    cat <<EOF
[Unit]
Description=vinted-bot (alerts for new Vinted listings)

[Service]
ExecStart="$exe" run
WorkingDirectory=$dir
Environment="VINTED_BOT_DB_PATH=$dir/app.db"
Environment="VINTED_BOT_WEB_PORT=$PORT"
Environment="VINTED_BOT_SUPERVISED=systemd"
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
}

autostart_linux() {
    exe=$1
    dir=$2
    setting=$3
    if ! command -v systemctl >/dev/null 2>&1 || ! systemctl --user show-environment >/dev/null 2>&1; then
        return 1
    fi
    # Starting at login switched off in Settings: an update keeps that choice.
    was_disabled=no
    if [ "$setting" = default ] && [ -f "$(systemd_unit)" ] &&
        [ "$(systemctl --user is-enabled vinted-bot.service 2>/dev/null)" = disabled ]; then
        was_disabled=yes
    fi
    mkdir -p "$(dirname "$(systemd_unit)")"
    write_unit "$exe" "$dir" >"$(systemd_unit)"
    systemctl --user daemon-reload
    if [ $was_disabled = no ]; then
        systemctl --user enable vinted-bot.service >/dev/null 2>&1
    fi
    systemctl --user restart vinted-bot.service
    if [ $was_disabled = no ]; then
        say "It starts by itself whenever you log in (switch that off in Settings, General)."
    fi
    # Without "lingering", a user service only runs while you are logged in, so a Raspberry
    # Pi with nobody logged in would never start it.
    if [ "$(loginctl show-user "$(id -un)" --property=Linger --value 2>/dev/null)" != yes ]; then
        if ! loginctl enable-linger --no-ask-password "$(id -un)" >/dev/null 2>&1; then
            say "To have it start when the computer boots, even before anyone logs in (handy on"
            say "a Raspberry Pi), run this once. It asks for your password:"
            say "  sudo loginctl enable-linger $(id -un)"
        fi
    fi
}

start_in_background() {
    exe=$1
    dir=$2
    set -- "$exe" run
    (
        cd "$dir"
        VINTED_BOT_DB_PATH="$dir/app.db" VINTED_BOT_WEB_PORT="$PORT" \
            nohup "$@" >>"$dir/vinted-bot.log" 2>&1 &
    )
}

port_answers() {
    curl -s -o /dev/null --max-time 2 "$URL/" 2>/dev/null
}

# Waits for vinted-bot's own health endpoint, not just anything on the port, so another
# program on 8000 isn't mistaken for a successful start. It answers 503 until the first
# check completes, which still counts as up.
wait_for_dashboard() {
    i=0
    while [ $i -lt 45 ]; do
        if curl -s --max-time 2 "$URL/healthz" 2>/dev/null | grep -q '"alive"'; then
            return 0
        fi
        sleep 1
        i=$((i + 1))
    done
    return 1
}

open_dashboard() {
    exe=$1
    dir=$2
    if [ -n "${VINTED_BOT_NO_BROWSER:-}" ]; then
        return 0
    fi
    if [ -n "${SSH_CONNECTION:-}" ]; then
        # A Raspberry Pi or server without a screen: the dashboard only listens on this
        # machine, so offer to open it to the home network (with a password), which beats
        # an SSH tunnel for anyone who isn't a developer.
        say ""
        say "You're connected over SSH, so the dashboard can only be opened on this machine"
        say "for now. It can also open on your phone and other computers on your Wi-Fi,"
        say "protected with a password this sets for you."
        say ""
        if ask "Allow that? Type y and press Enter for yes, or just press Enter to skip." no; then
            say ""
            VINTED_BOT_DB_PATH="$dir/app.db" "$exe" address --allow-network ||
                warn "That didn't work; run this later to try again: vinted-bot address --allow-network"
        else
            say "To see it from your own computer, run this there, then open $URL:"
            say "  ssh -L $PORT:localhost:$PORT $(id -un)@$(hostname)"
            say "Or later, to open it from your phone: vinted-bot address --allow-network"
        fi
    elif [ "$(os)" = Darwin ]; then
        open "$URL" || true
    elif [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL" >/dev/null 2>&1 &
    fi
}

# --- The two things this script does --------------------------------------------------

uninstall() {
    say "Removing vinted-bot..."
    remove_autostart
    if uv=$(find_uv); then
        bin=$("$uv" tool dir --bin 2>/dev/null || true)
        if [ -n "$bin" ]; then
            stop_everything "$bin"
            if [ -x "$bin/vinted-bot" ]; then
                VINTED_BOT_DB_PATH="$(data_dir)/app.db" "$bin/vinted-bot" shortcuts --remove >/dev/null 2>&1 || true
            fi
        fi
        "$uv" tool uninstall vinted-bot >/dev/null 2>&1 || true
    fi
    say ""
    say "vinted-bot is removed."
    say "Your searches and settings are still here, in case you come back:"
    say "  $(data_dir)"
    say "Delete that folder if you want them gone too."
    say "uv, the helper used to install it, is still there for other tools. To remove it as well:"
    say "  https://docs.astral.sh/uv/getting-started/installation/#uninstallation"
}

install() {
    autostart_setting=$1

    command -v curl >/dev/null 2>&1 || die "this needs curl. On Debian, Ubuntu or Raspberry Pi OS: sudo apt install curl"

    dir=$(data_dir)
    mkdir -p "$dir"
    uv=$(ensure_uv)
    bin=$("$uv" tool dir --bin)
    exe="$bin/vinted-bot"

    already=no
    if [ -x "$exe" ]; then
        already=yes
        say "vinted-bot is already installed. Updating it to the newest version..."
        stop_everything "$bin"
    else
        say "Installing vinted-bot. The first time this also downloads Python (about 30 MB),"
        say "so give it a minute..."
    fi

    # --managed-python: a Python that uv looks after itself, so a system or Homebrew Python
    # update can never break the install. --reinstall-package: the archive URL never
    # changes, so without it a re-run would keep the old copy.
    "$uv" tool install --quiet --upgrade --reinstall-package vinted-bot \
        --managed-python --python 3.13 "$PACKAGE" ||
        die "the download or install failed (see the messages above)."
    [ -x "$exe" ] || die "the install finished, but $exe is missing."

    # So that typing `vinted-bot` in a new terminal works.
    if [ -z "${UV_NO_MODIFY_PATH:-}" ]; then
        "$uv" tool update-shell >/dev/null 2>&1 || true
    fi
    version=$("$exe" --version 2>/dev/null || echo "vinted-bot")

    # Installing (or updating) is asking for it to run, even if it was stopped before.
    rm -f "$dir/vinted-bot.stopped"

    if port_answers; then
        warn ""
        warn "Something else is already using port $PORT on this computer (maybe an older copy"
        warn "running in Docker?). Stop it, or choose another port by running this again as:"
        warn "  curl -LsSf $SCRIPT_URL | VINTED_BOT_WEB_PORT=8001 sh"
        die "port $PORT is taken."
    fi

    # No questions: starting at login (and, on a Mac, staying awake while plugged in) is
    # what nearly everyone wants, and both are switches in the dashboard's Settings,
    # where there is room to explain them. --no-autostart still skips the first.
    autostarted=no
    if wants "$autostart_setting" "Start vinted-bot by itself whenever you log in?"; then
        if [ "$(os)" = Darwin ]; then
            autostart_macos "$exe" "$dir" "$autostart_setting" && autostarted=yes
        else
            autostart_linux "$exe" "$dir" "$autostart_setting" && autostarted=yes
        fi
        if [ $autostarted = no ]; then
            say "Starting by itself isn't possible here (no desktop session or systemd), so it"
            say "will run until this computer restarts."
        fi
    else
        remove_autostart
    fi
    if [ $autostarted = no ]; then
        start_in_background "$exe" "$dir"
    fi

    say ""
    if ! wait_for_dashboard; then
        die "it installed, but didn't start. The log may say why: $dir/vinted-bot.log"
    fi

    if [ $already = yes ]; then
        say "Updated and running: $version"
    else
        say "All done. $version is running."
    fi
    # The icon that opens it again later: Applications on a Mac, the apps menu on Linux.
    icon=no
    if VINTED_BOT_DB_PATH="$dir/app.db" "$exe" shortcuts >/dev/null 2>&1; then
        icon=yes
    fi
    open_dashboard "$exe" "$dir"
    say ""
    say "  Dashboard:     $URL"
    say "  Your data:     $dir"
    say "  Log file:      $dir/vinted-bot.log"
    say ""
    if [ $already = yes ]; then
        say "Your searches and alert settings are as you left them. Alerts arrive while this"
        say "computer is on, awake and online."
    else
        say "Next: in the dashboard, choose where alerts go (Telegram, Discord, or one of the"
        say "other options), then paste a Vinted search. Alerts arrive while this computer is"
        say "on, awake and online."
    fi
    say ""
    say "Closing the browser doesn't stop it. To get back to the dashboard later:"
    if [ $icon = yes ] && [ "$(os)" = Darwin ]; then
        say "  open vinted-bot from Applications or Launchpad (or ⌘ Space, type vinted),"
        say "  or type vinted-bot in a new Terminal window."
    elif [ $icon = yes ] && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
        say "  open vinted-bot from your apps menu, or type vinted-bot in a new terminal."
    else
        say "  type vinted-bot in a new terminal (it prints the address when there's no browser)."
    fi
    say ""
    say "  Stop:          vinted-bot stop   (it stays stopped until you open it again)"
    say "  Log:           vinted-bot logs"
    say "  Update:        the dashboard's Update button, or run the install command again"
    if [ $autostarted = no ]; then
        say "                 (not started at login: after a restart, open it again)"
    fi
    say "  Uninstall:     curl -LsSf $SCRIPT_URL | sh -s -- --uninstall"
}

usage() {
    sed -n '2,33p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//' || true
}

main() {
    autostart="${VINTED_BOT_AUTOSTART:-default}"
    action=install
    for arg in "$@"; do
        case "$arg" in
            --uninstall) action=uninstall ;;
            --autostart) autostart=yes ;;
            --no-autostart) autostart=no ;;
            --no-browser) VINTED_BOT_NO_BROWSER=1 ;;
            -h | --help)
                usage
                return 0
                ;;
            *) die "unknown option: $arg (try --help)" ;;
        esac
    done

    case "$(os)" in
        Darwin | Linux) ;;
        *) die "this installer is for macOS and Linux. On Windows, use install.ps1 (see the README)." ;;
    esac
    if [ "$(id -u)" = 0 ] && [ -z "${VINTED_BOT_ALLOW_ROOT:-}" ]; then
        die "please run this as your normal user, without sudo. It installs into your home folder."
    fi

    if [ $action = uninstall ]; then
        uninstall
    else
        install "$autostart"
    fi
}

main "$@"
