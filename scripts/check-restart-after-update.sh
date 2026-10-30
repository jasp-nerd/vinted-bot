#!/bin/sh
# Checks that the start-at-login entry install.sh writes starts the app again after the
# exit an update ends with (code 75), and tells the app it will (VINTED_BOT_SUPERVISED).
#
# Uses install.sh's own write_plist / write_unit, under a different name so a real
# install on the same machine is never touched, with a stand-in for the app: it exits 75
# the first time and stays up the second. Run by .github/workflows/installers.yml; safe to
# run by hand on macOS or on Linux with a systemd user session.

set -eu

here=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
name=vinted-bot-restart-check

# install.sh, minus its last line (`main "$@"`), is just the functions.
sed '$d' "$here/install.sh" >"$work/install-functions.sh"
# shellcheck disable=SC1091
. "$work/install-functions.sh"

cat >"$work/app" <<EOF
#!/bin/sh
echo "\${VINTED_BOT_SUPERVISED:-unset}" >>"$work/starts"
if [ "\$(wc -l <"$work/starts")" -eq 1 ]; then
    exit 75
fi
exec sleep 600
EOF
chmod +x "$work/app"

cleanup() {
    if [ "$(uname -s)" = Darwin ]; then
        launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    else
        systemctl --user stop "$name.service" 2>/dev/null || true
        rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$name.service"
        systemctl --user daemon-reload 2>/dev/null || true
    fi
    rm -rf "$work"
}
trap cleanup EXIT

if [ "$(uname -s)" = Darwin ]; then
    LABEL="io.github.jasp-nerd.$name"
    write_plist "$work/app" "$work" no >"$work/$name.plist"
    plutil -lint "$work/$name.plist"
    launchctl bootstrap "gui/$(id -u)" "$work/$name.plist"
    supervisor=launchd
else
    unit="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$name.service"
    mkdir -p "$(dirname "$unit")"
    write_unit "$work/app" "$work" >"$unit"
    systemctl --user daemon-reload
    systemctl --user start "$name.service"
    supervisor=systemd
fi

# launchd waits out its 30-second ThrottleInterval after an exit that quick; systemd 3 s.
i=0
touch "$work/starts"
while [ "$(wc -l <"$work/starts")" -lt 2 ]; do
    i=$((i + 1))
    if [ $i -gt 60 ]; then
        echo "It was not started again within a minute of exiting with code 75."
        exit 1
    fi
    sleep 1
done

if [ "$(sort -u "$work/starts")" != "$supervisor" ]; then
    echo "The app was not told it is supervised: got $(sort -u "$work/starts" | tr '\n' ' ')"
    exit 1
fi
echo "Started again after exit code 75, with VINTED_BOT_SUPERVISED=$supervisor."
