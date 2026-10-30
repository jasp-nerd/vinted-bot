# Contributing

Bug reports with logs attached are the most useful thing anyone can send. For code, read on.

## Setting up

You need [uv](https://docs.astral.sh/uv/). It installs the right Python by itself.

```bash
git clone https://github.com/jasp-nerd/vinted-sniper && cd vinted-sniper
uv sync --all-extras
uv run vinted-sniper run --open
```

The test suite never contacts Vinted, so it runs anywhere.
[docs/architecture.md](docs/architecture.md) explains how the pieces fit together.

### A dashboard with something in it

For screenshots, the public demo or working on the dashboard, `scripts/seed_demo.py` fills
a fresh database with invented searches, a month of finds, destinations and delivery
history. Its photos are the AI-generated ones hosted with the project site
(`scripts/demo/catalog.json` lists them), so nothing points at a real listing.

```bash
uv run python scripts/seed_demo.py /tmp/demo.db
VINTED_SNIPER_DB_PATH=/tmp/demo.db VINTED_SNIPER_FETCH_MODE=mock \
  VINTED_SNIPER_MOCK_SCENARIO_DIR=scripts/demo/mock uv run vinted-sniper run --open
```

The mock scenario answers every search with an empty page, so this never talks to Vinted
and never sends an alert. Leave out the two mock variables and the demo searches check
Vinted for real, adding real finds next to the invented ones. Even then nothing already
on Vinted is announced, and the demo's places for alerts reach nobody (a random ntfy
name, a switched-off Discord webhook, a Telegram chat that doesn't exist). Run it from a
folder without your own `.env`, or it picks up your real bot token and settings.

The dashboard's templates live in `src/vinted_sniper/web/templates` and its CSS and
script in `web/static`; they need no build step. Static files are served with a content
hash in the URL, so a reload always picks up a change.

## Before you push

CI runs exactly these, and a pull request needs all of them green:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run deptry src
uv run vulture
uv run --with zizmor zizmor .github/workflows   # only if you touched a workflow
```

If you changed `install.sh` or `docker/entrypoint.sh`, also run
`uvx --from shellcheck-py shellcheck -s sh install.sh docker/entrypoint.sh`. If you changed
the Dockerfile, `docker build .` and start the result once.

## What a change is held to

[docs/REVIEW.md](docs/REVIEW.md) is the checklist every change is reviewed against, yours and
the maintainer's alike. The short version:

- Every new behaviour gets a test that would fail without it. Don't loosen a test to make it
  pass.
- Match the code around you: docstrings that explain *why*, plain asyncio, SQL only in
  `db/repo.py`, structlog events named like `poller.started`.
- No retry or fallback whose only job is to make a symptom go away.
- The README and docs never claim something the code doesn't do.
- Never log in to Vinted, and no features that need a Vinted account (buying, messaging,
  offers). That is a deliberate line, not a missing feature.

## Commit messages

One plain sentence in the imperative, saying what the change does for someone using or
reading the code:

```
Retry Telegram sends that hit a rate limit after the delay Telegram asks for
```

No prefixes (`feat:`, `fix(web):`), no ticket numbers in the subject, no trailers crediting
tools. Add a body when the *why* isn't obvious from the subject.

## Pull requests

Keep each one about one thing. Say what changed and how you checked it. A new abstraction
(a base class, a registry, a new layer) needs one line explaining why the simpler version
wasn't enough.

User-facing changes get a line in `CHANGELOG.md` under `[Unreleased]`, written for the
people running the app.

## Cutting a release

For the maintainer. Releases are made by pushing a tag; the workflows do the rest.

1. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`, add a fresh empty
   `## [Unreleased]` above it, and update the compare links at the bottom.
2. Set `version = "X.Y.Z"` in `pyproject.toml` and run `uv lock`.
3. Commit (`Release X.Y.Z`), merge to main, then tag that commit and push the tag:

   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

Pushing the tag starts two workflows:

- **Publish image** builds the Docker image for amd64 and arm64 and tags it `X.Y.Z`, `X.Y`,
  `X` and `latest`.
- **Release** checks the tag matches `pyproject.toml`, builds the package, publishes it to
  PyPI and creates the GitHub release with this version's changelog section as its text. The
  dashboard's update notice reads that release.

Builds of main keep going out as the `edge` image in between.

### One-time PyPI setup

The Release workflow publishes with PyPI trusted publishing, so no token is stored anywhere.
Before the first release:

1. On pypi.org, under Your projects, Publishing, add a pending publisher: project
   `vinted-sniper`, owner `jasp-nerd`, repository `vinted-sniper`, workflow `release.yml`,
   environment `pypi`.
2. In the GitHub repository settings, create an environment named `pypi`. Adding yourself as
   a required reviewer there means each PyPI upload waits for a click.

Once the package is on PyPI, the installers can switch to it: change `PACKAGE` in
`install.sh` and `$spec` in `install.ps1` to `vinted-sniper`, and update the rollback example
in `docs/troubleshooting.md`.
