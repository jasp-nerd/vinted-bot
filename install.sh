#!/bin/sh
# Installs vinted-sniper on macOS or Linux (including a Raspberry Pi). No Docker, no admin
# password, nothing outside your home folder.
#
#   curl -LsSf https://raw.githubusercontent.com/jasp-nerd/vinted-sniper/main/install.sh | sh
#
# What it does, in order:
#   1. installs uv (https://docs.astral.sh/uv/), the tool that fetches Python and
#      vinted-sniper, if you don't have it yet
#   2. installs vinted-sniper with its own private copy of Python
#   3. asks whether it should start by itself when you log in
#   4. starts it and opens the dashboard in your browser
#
# Run the same command again to update. To remove it (your searches are kept):
#
#   curl -LsSf https://raw.githubusercontent.com/jasp-nerd/vinted-sniper/main/install.sh | sh -s -- --uninstall
#
# Options (after `sh -s --` when piping):
#   --uninstall        remove vinted-sniper and its start-at-login entry
#   --autostart        start at login without asking
#   --no-autostart     don't start at login, and don't ask
#   --no-browser       don't open the dashboard at the end
#
# Environment variables, for anyone scripting this:
#   VINTED_SNIPER_AUTOSTART=yes|no    same as --autostart / --no-autostart
#   VINTED_SNIPER_KEEP_AWAKE=yes|no   macOS: keep the Mac awake while plugged in
#   VINTED_SNIPER_NO_BROWSER=1        same as --no-browser
#   VINTED_SNIPER_DATA_DIR=...        where the database and log live
#   VINTED_SNIPER_WEB_PORT=...        dashboard port, if 8000 is taken
#   VINTED_SNIPER_PACKAGE=...         what to install (see PACKAGE below)
#   UV_NO_MODIFY_PATH=1               leave your shell's PATH settings alone
#   VINTED_SNIPER_ALLOW_ROOT=1        install as root anyway (not recommended)

# Everything is inside functions and only `main "$@"` at the very end runs anything, so a
# download cut off halfway can never run half an install.

set -eu

# Where vinted-sniper comes from: the latest release on PyPI. Set VINTED_SNIPER_PACKAGE to
# install something else, such as a GitHub archive of an unreleased branch.
PACKAGE="${VINTED_SNIPER_PACKAGE:-vinted-sniper}"
PORT="${VINTED_SNIPER_WEB_PORT:-8000}"
URL="http://localhost:$PORT"
LABEL="io.github.jasp-nerd.vinted-sniper"
SCRIPT_URL="https://raw.githubusercontent.com/jasp-nerd/vinted-sniper/main/install.sh"

say() { printf '%s\n' "$*"; }
warn() { printf '%s\n' "$*" >&2; }
die() {
    warn ""
    warn "Sorry, that didn't work: $*"
    warn "If you're stuck, open an issue and paste everything above:"
    warn "  https://github.com/jasp-nerd/vinted-sniper/issues/new/choose"
    exit 1
}

os() { uname -s; }

data_dir() {
    if [ -n "${VINTED_SNIPER_DATA_DIR:-}" ]; then
        printf '%s\n' "$VINTED_SNIPER_DATA_DIR"
    elif [ "$(os)" = Darwin ]; then
        printf '%s\n' "$HOME/Library/Application Support/vinted-sniper"
    else
        printf '%s\n' "${XDG_DATA_HOME:-$HOME/.local/share}/vinted-sniper"
    fi
}

systemd_unit() {
    printf '%s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/vinted-sniper.service"
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
    warn "Installing uv, the helper that downloads Python and vinted-sniper for you..."
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
        yes | 1 | true) return 0 ;;
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
        systemctl --user stop vinted-sniper.service 2>/dev/null || true
    fi
    # A copy started in the background by an earlier run of this script.
    if command -v pkill >/dev/null 2>&1; then
        pkill -f "$bin/vinted-sniper run" 2>/dev/null || true
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
        rm -f "$(launchd_plist)"
    elif [ -f "$(systemd_unit)" ]; then
        systemctl --user disable --now vinted-sniper.service >/dev/null 2>&1 || true
        rm -f "$(systemd_unit)"
        systemctl --user daemon-reload >/dev/null 2>&1 || true
    fi
}

xml_escape() {
    printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

# Writes the LaunchAgent to stdout. caffeinate -s holds off sleep only while the Mac is on
# power and only while vinted-sniper runs; a closed MacBook lid still sleeps.
#
# KeepAlive=true starts it again after any exit, including the clean exit (code 75) that
# ends an update from the dashboard; VINTED_SNIPER_SUPERVISED tells the app it can count
# on that. ThrottleInterval only delays a restart when the app exits within 30 seconds of
# starting, which keeps a crash at startup from spinning.
write_plist() {
    exe=$(xml_escape "$1")
    dir=$(xml_escape "$2")
    keep_awake=$3
    cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
EOF
    if [ "$keep_awake" = yes ]; then
        printf '    <string>/usr/bin/caffeinate</string>\n    <string>-s</string>\n'
    fi
    cat <<EOF
    <string>$exe</string>
    <string>run</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$dir</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>VINTED_SNIPER_DB_PATH</key>
    <string>$dir/app.db</string>
    <key>VINTED_SNIPER_WEB_PORT</key>
    <string>$PORT</string>
    <key>VINTED_SNIPER_SUPERVISED</key>
    <string>launchd</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>30</integer>
  <key>StandardOutPath</key>
  <string>$dir/vinted-sniper.log</string>
  <key>StandardErrorPath</key>
  <string>$dir/vinted-sniper.log</string>
</dict>
</plist>
EOF
}

autostart_macos() {
    exe=$1
    dir=$2
    keep_awake=$3
    mkdir -p "$HOME/Library/LaunchAgents"
    write_plist "$exe" "$dir" "$keep_awake" >"$(launchd_plist)"
    # bootout finishes in the background, so the first bootstrap can race it.
    i=0
    until launchctl bootstrap "gui/$(id -u)" "$(launchd_plist)" 2>/dev/null; do
        i=$((i + 1))
        if [ $i -ge 5 ]; then
            # Typically: logged in over SSH, where there is no desktop session to start in.
            rm -f "$(launchd_plist)"
            return 1
        fi
        sleep 1
    done
    say "It will now start by itself whenever you log in."
    say "macOS may show a \"Background Items Added\" notice. That's this; it's expected."
}

# Restart=always starts it again after any exit, including the clean exit (code 75) that
# ends an update from the dashboard; VINTED_SNIPER_SUPERVISED tells the app it can count
# on that. `systemctl --user stop` is not an exit systemd restarts from. Three seconds
# between starts keeps a crash at startup under systemd's limit of five starts in ten
# seconds, so it keeps trying instead of giving up.
write_unit() {
    exe=$1
    dir=$2
    cat <<EOF
[Unit]
Description=vinted-sniper (alerts for new Vinted listings)

[Service]
ExecStart="$exe" run
WorkingDirectory=$dir
Environment="VINTED_SNIPER_DB_PATH=$dir/app.db"
Environment="VINTED_SNIPER_WEB_PORT=$PORT"
Environment="VINTED_SNIPER_SUPERVISED=systemd"
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF
}

autostart_linux() {
    exe=$1
    dir=$2
    if ! command -v systemctl >/dev/null 2>&1 || ! systemctl --user show-environment >/dev/null 2>&1; then
        return 1
    fi
    mkdir -p "$(dirname "$(systemd_unit)")"
    write_unit "$exe" "$dir" >"$(systemd_unit)"
    systemctl --user daemon-reload
    systemctl --user enable vinted-sniper.service >/dev/null 2>&1
    systemctl --user restart vinted-sniper.service
    say "It will now start by itself whenever you log in."
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
    keep_awake=$3
    set -- "$exe" run
    if [ "$keep_awake" = yes ]; then
        set -- /usr/bin/caffeinate -s "$@"
    fi
    (
        cd "$dir"
        VINTED_SNIPER_DB_PATH="$dir/app.db" VINTED_SNIPER_WEB_PORT="$PORT" \
            nohup "$@" >>"$dir/vinted-sniper.log" 2>&1 &
    )
}

port_answers() {
    curl -s -o /dev/null --max-time 2 "$URL/" 2>/dev/null
}

# Waits for vinted-sniper's own health endpoint, not just anything on the port, so another
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
    if [ -n "${VINTED_SNIPER_NO_BROWSER:-}" ]; then
        return 0
    fi
    if [ -n "${SSH_CONNECTION:-}" ]; then
        say ""
        say "You're connected over SSH, and the dashboard only listens on this machine."
        say "To see it from your own computer, run this there, then open $URL:"
        say "  ssh -L $PORT:localhost:$PORT $(id -un)@$(hostname)"
    elif [ "$(os)" = Darwin ]; then
        open "$URL" || true
    elif [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL" >/dev/null 2>&1 &
    fi
}

# --- The two things this script does --------------------------------------------------

uninstall() {
    say "Removing vinted-sniper..."
    remove_autostart
    if uv=$(find_uv); then
        bin=$("$uv" tool dir --bin 2>/dev/null || true)
        if [ -n "$bin" ]; then
            stop_everything "$bin"
        fi
        "$uv" tool uninstall vinted-sniper >/dev/null 2>&1 || true
    fi
    say ""
    say "vinted-sniper is removed."
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
    exe="$bin/vinted-sniper"

    already=no
    if [ -x "$exe" ]; then
        already=yes
        say "vinted-sniper is already installed. Updating it to the newest version..."
        stop_everything "$bin"
    else
        say "Installing vinted-sniper. The first time this also downloads Python (about 30 MB),"
        say "so give it a minute..."
    fi

    # --managed-python: a Python that uv looks after itself, so a system or Homebrew Python
    # update can never break the install. --reinstall-package: the archive URL never
    # changes, so without it a re-run would keep the old copy.
    "$uv" tool install --quiet --upgrade --reinstall-package vinted-sniper \
        --managed-python --python 3.13 "$PACKAGE" ||
        die "the download or install failed (see the messages above)."
    [ -x "$exe" ] || die "the install finished, but $exe is missing."

    # So that typing `vinted-sniper` in a new terminal works.
    if [ -z "${UV_NO_MODIFY_PATH:-}" ]; then
        "$uv" tool update-shell >/dev/null 2>&1 || true
    fi
    version=$("$exe" --version 2>/dev/null || echo "vinted-sniper")

    if port_answers; then
        warn ""
        warn "Something else is already using port $PORT on this computer (maybe an older copy"
        warn "running in Docker?). Stop it, or choose another port by running this again as:"
        warn "  curl -LsSf $SCRIPT_URL | VINTED_SNIPER_WEB_PORT=8001 sh"
        die "port $PORT is taken."
    fi

    keep_awake=no
    if [ "$(os)" = Darwin ]; then
        if [ "${VINTED_SNIPER_KEEP_AWAKE:-ask}" = ask ]; then
            say ""
            say "Alerts only arrive while this Mac is awake."
        fi
        if wants "${VINTED_SNIPER_KEEP_AWAKE:-ask}" "Keep the Mac from sleeping while it's plugged in and vinted-sniper runs?"; then
            keep_awake=yes
        fi
    fi

    autostarted=no
    if [ "$autostart_setting" = ask ]; then
        say ""
    fi
    if wants "$autostart_setting" "Start vinted-sniper by itself whenever you log in?"; then
        if [ "$(os)" = Darwin ]; then
            autostart_macos "$exe" "$dir" "$keep_awake" && autostarted=yes
        else
            autostart_linux "$exe" "$dir" && autostarted=yes
        fi
        if [ $autostarted = no ]; then
            say "Starting by itself isn't possible here (no desktop session or systemd), so it"
            say "will run until this computer restarts."
        fi
    else
        remove_autostart
    fi
    if [ $autostarted = no ]; then
        start_in_background "$exe" "$dir" "$keep_awake"
    fi

    say ""
    if ! wait_for_dashboard; then
        die "it installed, but didn't start. The log may say why: $dir/vinted-sniper.log"
    fi

    if [ $already = yes ]; then
        say "Updated and running: $version"
    else
        say "All done. $version is running."
    fi
    open_dashboard
    say ""
    say "  Dashboard:     $URL   (bookmark it)"
    say "  Your data:     $dir"
    say "  Log file:      $dir/vinted-sniper.log"
    say ""
    say "Next: in the dashboard, add where alerts should go (Discord or Telegram), then paste"
    say "a Vinted search. Alerts arrive while this computer is on, awake and online."
    say ""
    if [ $autostarted = no ]; then
        say "  Update:        the dashboard's Update button, then start it again; or run the"
        say "                 install command again"
    else
        say "  Update:        the dashboard's Update button, or run the install command again"
    fi
    if [ $autostarted = no ]; then
        say "  Start again:   run the install command again (after a restart, for example)"
        say "  Stop:          pkill -f 'vinted-sniper run'"
    elif [ "$(os)" = Darwin ]; then
        say "  Stop:          launchctl bootout gui/$(id -u)/$LABEL"
        say "                 (it starts again the next time you log in)"
    else
        say "  Stop:          systemctl --user stop vinted-sniper"
        say "                 (it starts again the next time you log in)"
    fi
    say "  Uninstall:     curl -LsSf $SCRIPT_URL | sh -s -- --uninstall"
}

usage() {
    sed -n '2,33p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//' || true
}

main() {
    autostart="${VINTED_SNIPER_AUTOSTART:-ask}"
    action=install
    for arg in "$@"; do
        case "$arg" in
            --uninstall) action=uninstall ;;
            --autostart) autostart=yes ;;
            --no-autostart) autostart=no ;;
            --no-browser) VINTED_SNIPER_NO_BROWSER=1 ;;
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
    if [ "$(id -u)" = 0 ] && [ -z "${VINTED_SNIPER_ALLOW_ROOT:-}" ]; then
        die "please run this as your normal user, without sudo. It installs into your home folder."
    fi

    if [ $action = uninstall ]; then
        uninstall
    else
        install "$autostart"
    fi
}

main "$@"
