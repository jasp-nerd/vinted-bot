"""Process settings the dashboard manages: the Telegram bot's token and phone access.

Both used to be environment variables only, which meant finding a `.env` file, editing it
and restarting: the point where most people setting this up gave up. Now the dashboard
stores them in `app_state`, and the running app picks a change up without a restart (the
Telegram bot is restarted on the new token, the web server listens again on the new
address). The dashboard password, the third of these, lives in web/security.py beside
the sessions it guards.

**The environment still wins.** When VINTED_BOT_TELEGRAM_BOT_TOKEN or VINTED_BOT_WEB_HOST
is set (in the environment or the `.env` file), that value is used and the dashboard
shows it as set by the environment, with no control to change it. The other way round, a
dashboard switch quietly overriding a compose file or a service unit, would come back
wrong at the next deploy, and the person who wrote that file would have no way to tell.
"""

from __future__ import annotations

import re

from vinted_bot.config import Settings
from vinted_bot.db.repo import Repo

_TELEGRAM_TOKEN_KEY = "telegram_bot_token"

# What BotFather hands out: the bot's numeric id, a colon, then a 35-character secret.
_TELEGRAM_TOKEN = re.compile(r"(?<![\w:])\d{5,20}:[A-Za-z0-9_-]{30,64}(?![\w-])")


# --- The Telegram bot's token ---------------------------------------------------------


def telegram_token_from_env(settings: Settings) -> bool:
    return settings.telegram_bot_token is not None


async def telegram_token(settings: Settings, repo: Repo) -> str | None:
    """The token the bot and the Telegram sender use, or None while there is none."""
    if settings.telegram_bot_token is not None:
        return settings.telegram_bot_token.get_secret_value()
    return await repo.get_state_value(_TELEGRAM_TOKEN_KEY)


def find_telegram_token(text: str) -> str | None:
    """The token in what was pasted, which may be BotFather's whole message."""
    match = _TELEGRAM_TOKEN.search(text)
    return match.group(0) if match else None


async def set_telegram_token(repo: Repo, token: str | None) -> None:
    """Store a token from the dashboard, or forget it with None."""
    if token is None:
        await repo.delete_state_value(_TELEGRAM_TOKEN_KEY)
    else:
        await repo.set_state_value(_TELEGRAM_TOKEN_KEY, token)


def mask_token(token: str) -> str:
    """A token as the dashboard shows it: the bot's id and the last four characters.

    Enough to tell two bots apart, not enough to use one.
    """
    bot_id, _, secret = token.partition(":")
    return f"{bot_id}:•••••{secret[-4:]}"
