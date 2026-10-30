# Contributing

Bug reports with logs attached are the most useful thing anyone can send. For code, read on.

## Setting up

You need [uv](https://docs.astral.sh/uv/). It installs the right Python by itself.

```bash
git clone https://github.com/jasp-nerd/vinted-bot && cd vinted-bot
uv sync --all-extras
uv run vinted-bot run --open
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
VINTED_BOT_DB_PATH=/tmp/demo.db VINTED_BOT_FETCH_MODE=mock \
  VINTED_BOT_MOCK_SCENARIO_DIR=scripts/demo/mock uv run vinted-bot run --open
```

The mock scenario answers every search with an empty page, so this never talks to Vinted
and never sends an alert. Leave out the two mock variables and the demo searches check
Vinted for real, adding real finds next to the invented ones. Even then nothing already
on Vinted is announced, and the demo's places for alerts reach nobody (a random ntfy
name, a switched-off Discord webhook, a Telegram chat that doesn't exist). Run it from a
folder without your own `.env`, or it picks up your real bot token and settings.

The dashboard's templates live in `src/vinted_bot/web/templates` and its CSS and
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

For the maintainer. A release is one button; the workflows do the rest.

1. In a pull request: in `CHANGELOG.md`, rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`,
   add a fresh empty `## [Unreleased]` above it, and update the compare links at the bottom.
   Set `version = "X.Y.Z"` in `pyproject.toml` and `__version__` in
   `src/vinted_bot/__init__.py`, run `uv lock`, and merge it to main.
2. On GitHub, open **Actions**, choose **Release** on the left, click **Run workflow**, leave
   the branch on `main`, and click the green **Run workflow** button. There is nothing to
   fill in.

The Release workflow then:

- reads the version from `pyproject.toml`, and stops without changing anything if
  `CHANGELOG.md` has no `## [X.Y.Z]` section, if the tag `vX.Y.Z` already exists, or if it
  was started on a branch other than main;
- creates the tag `vX.Y.Z` on that commit;
- builds the package and publishes it to PyPI;
- builds the Docker image for amd64 and arm64 and tags it `X.Y.Z`, `X.Y`, `X` and `latest`
  (by calling **Publish image**);
- last, creates the GitHub release with this version's changelog section as its text and the
  package files attached. The dashboard's update notice reads that release, so it only
  appears once the package and the image are out.

If a check fails before the tag is made, fix it and click Run workflow again. If a later job
fails (PyPI or the registry having a bad moment), open that run and use **Re-run failed
jobs**: a new run would refuse, because the tag exists by then. If the fix needs a code
change, release it as the next version instead.

Pushing a tag by hand (`git tag -a vX.Y.Z -m vX.Y.Z && git push origin vX.Y.Z`) still works
and does the same, with the image built by **Publish image** on that push. Builds of main
keep going out as the `edge` image in between.

### One-time PyPI setup

The Release workflow publishes with PyPI trusted publishing, so no token is stored anywhere.
Before the first release:

1. On pypi.org, open Your account, **Publishing**, and under "Add a new pending publisher"
   choose GitHub and fill in:

   | Field | Value |
   |---|---|
   | PyPI Project Name | `vinted-bot` |
   | Owner | `jasp-nerd` |
   | Repository name | `vinted-bot` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

   The first release creates the project and turns the pending publisher into a normal one.
2. In the GitHub repository's **Settings**, **Environments**, create an environment named
   `pypi`. Adding yourself as a required reviewer there means each PyPI upload waits for a
   click.
