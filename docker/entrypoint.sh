#!/bin/sh
# Installed in the image as /app/bin/vinted-sniper, ahead of the real command on PATH, so
# every way of running the app goes through it: the container's own start, the health
# check, and `docker compose exec vinted-sniper vinted-sniper status`.
#
# Started as root (the default), it makes sure /data belongs to PUID:PGID and then drops to
# that user before anything opens the database. NAS shares and cloud volumes tend to arrive
# owned by root, which a fixed non-root user cannot write to; PUID/PGID is the convention
# NAS users already know from linuxserver.io images. Started as someone else already
# (compose `user:`, Kubernetes `runAsUser`), it just runs the command.
#
# Every path through here ends with the app running as non-root unless PUID=0 is asked for
# explicitly. Running even `status` as root could leave root-owned SQLite side files
# (-wal, -shm) that the app then cannot open.
set -eu

APP=/app/.venv/bin/vinted-sniper
DATA=/data

if [ "$(id -u)" != "0" ]; then
    if [ -d "$DATA" ] && [ ! -w "$DATA" ]; then
        echo "vinted-sniper: $DATA is not writable by user $(id -u):$(id -g)." >&2
        echo "  Make that folder writable by this user, or start the container as root and" >&2
        echo "  set PUID/PGID so it can fix the ownership itself." >&2
    fi
    exec "$APP" "$@"
fi

PUID="${PUID:-10001}"
PGID="${PGID:-10001}"
case "$PUID$PGID" in
    *[!0-9]*)
        echo "vinted-sniper: PUID and PGID must be numbers (got PUID=$PUID PGID=$PGID)." >&2
        exit 64
        ;;
esac

# Only touch ownership when something is actually wrong: a recursive chown on every start,
# and on every health check, would be slow on a big NAS share for no reason.
if [ -d "$DATA" ] && [ -n "$(find "$DATA" -xdev \( ! -user "$PUID" -o ! -group "$PGID" \) -print -quit)" ]; then
    if ! chown -R "$PUID:$PGID" "$DATA" 2>/dev/null; then
        echo "vinted-sniper: could not give $DATA to $PUID:$PGID." >&2
        echo "  Some network shares (NFS with root squash, for one) refuse this. Set PUID and" >&2
        echo "  PGID to the user that already owns the folder instead." >&2
    fi
fi

# HOME would otherwise stay /root, which the app's user cannot read. Nothing is meant to
# be written there; /tmp is the one other writable place in a read-only container.
export HOME=/tmp
exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups -- "$APP" "$@"
