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
KO_FI = "https://ko-fi.com/jaspnerd"
SPONSORS = "https://github.com/sponsors/jasp-nerd"


def tracked(url: str, campaign: str) -> str:
    """A link that says where on the site it was clicked, so Ko-fi's and GitHub's traffic
    stats show what works. The same tag for everyone; it says nothing about who clicked."""
    return f"{url}?utm_source={HOST}&utm_medium=site&utm_campaign={campaign}"


# Google Search Console ownership check (HTML tag method).
GOOGLE_SITE_VERIFICATION = "yChsP16tHi1XLf1-EY9hMxyY4OE3GFXmSheJnLbx9TE"
# Visit counts on the owner's self-hosted Umami: cookieless, no personal data. The script
# only reports from HOST, so local builds and previews stay out of the numbers.
UMAMI_SCRIPT = "https://stats.jaspnerd.dev/script.js"
UMAMI_WEBSITE_ID = "fce710a9-c778-4686-8f07-f0c8f60fe570"
