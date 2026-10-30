"""Where the site lives and what it links to, in one place. build.py, check_links.py,
indexnow.py and make_og.py all read from here, so a move to another host or repo is one edit."""

from urllib.parse import urlparse

NAME = "vinted-bot"
BASE_URL = "https://vinted-bot.jaspnerd.dev"
HOST = urlparse(BASE_URL).netloc
REPO = "https://github.com/jasp-nerd/vinted-bot"
REPO_BLOB = f"{REPO}/blob/main"
REPO_RAW = "https://raw.githubusercontent.com/jasp-nerd/vinted-bot/main"
PYPI = "https://pypi.org/project/vinted-bot/"
