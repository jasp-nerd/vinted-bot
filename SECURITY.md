# Security

## Reporting a problem

Please report security problems privately, through
[GitHub's private vulnerability reporting](https://github.com/jasp-nerd/vinted-sniper/security/advisories/new),
not in a public issue. Include what you found, how to reproduce it, and which version
(`vinted-sniper --version`) or image tag you ran.

You should get a first reply within a week. Fixes go out as a new release, with the advisory
published once people have had a chance to update.

## Supported versions

Only the newest release gets fixes. Vinted changes its site often enough that older versions
stop working anyway; updating is the fix for most problems.

## What counts

Things worth reporting, for example:

- a way to read or change the dashboard, its webhook links or tokens without the dashboard
  password when one is set;
- secrets (webhook links, bot tokens, the dashboard password) ending up in logs, alerts or
  anywhere else they shouldn't;
- the Docker image or the install scripts doing more than they say, or doing it unsafely.

Not a vulnerability here: the dashboard having no password while it only listens on
`localhost`, which is the documented default. Anyone who can already run programs on your
computer can read its data either way.

## How the app limits what can go wrong

- It never logs in to Vinted and never handles Vinted credentials.
- The dashboard listens on `localhost` only unless you change it, and warns in its log when
  it is reachable from elsewhere without a password.
- It only answers to host names it was told about (localhost, IP addresses,
  `VINTED_SNIPER_WEB_PUBLIC_URL` and `VINTED_SNIPER_WEB_ALLOWED_HOSTS`), and only accepts
  changes from its own pages, so another website cannot use it through your browser, by DNS
  rebinding or otherwise.
- Sign-in sessions are random tokens kept on the server: signing out revokes them, and
  changing the password signs every browser out. RSS feeds use a separate random key, never
  the password.

## What the server fetches on your behalf

Whoever can change the dashboard's settings can make the server send requests: test sends
and alerts go to any webhook, ntfy server or Apprise address you enter, and the health check
pings the URL you give it, every 30 seconds. Their answers are not shown back, only
whether it worked or the status code. That is the intended feature for a self-hosted app,
and it is why the dashboard needs a password before it is reachable by anyone you would not
hand your server to.
- The Docker image runs the app as a non-root user and works with a read-only filesystem.
- Release images carry signed build provenance: `gh attestation verify
  oci://ghcr.io/jasp-nerd/vinted-sniper:latest --owner jasp-nerd`. Python packages on PyPI
  are published with trusted publishing and attestations.
