"""Tell Bing, Yandex, Seznam, Naver and Yep (via IndexNow) that the site's pages changed.
Google doesn't use IndexNow; it reads the sitemap. Run after a deploy:

    python3 site/indexnow.py            # every URL in the built sitemap
    python3 site/indexnow.py --dry-run  # print what would be sent

The key is the file site/static/<key>.txt, served at https://vinted-bot.jaspnerd.dev/<key>.txt
(the host comes from site/siteconfig.py).
Make sure that URL answers with the key before pinging, or the ping is ignored.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SITE = Path(__file__).resolve().parent
sys.path.insert(0, str(SITE))
from siteconfig import HOST

ENDPOINT = "https://api.indexnow.org/IndexNow"


def main() -> int:
    keys = [p for p in (SITE / "static").glob("*.txt") if re.fullmatch(r"[0-9a-f]{32}", p.stem)]
    if len(keys) != 1:
        print("expected exactly one IndexNow key file (32 hex characters) in site/static/")
        return 1
    key = keys[0].stem
    sitemap = SITE / "dist" / "sitemap.xml"
    if not sitemap.exists():
        print("no site/dist/sitemap.xml; run python3 site/build.py first")
        return 1
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [loc.text for loc in ET.parse(sitemap).getroot().findall("s:url/s:loc", ns)]
    payload = {
        "host": HOST,
        "key": key,
        "keyLocation": f"https://{HOST}/{key}.txt",
        "urlList": urls,
    }
    if "--dry-run" in sys.argv:
        print(json.dumps(payload, indent=2))
        return 0
    try:
        live = urllib.request.urlopen(payload["keyLocation"], timeout=15).read().decode().strip()
    except urllib.error.URLError as e:
        print(f"can't read {payload['keyLocation']} ({e}); deploy first")
        return 1
    if live != key:
        print(f"{payload['keyLocation']} doesn't contain the key; deploy first")
        return 1
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(
                f"IndexNow answered {resp.status} for {len(urls)} URLs (200 or 202 means accepted)"
            )
            return 0
    except urllib.error.HTTPError as e:
        print(f"IndexNow answered {e.code}: {e.read().decode(errors='replace')[:300]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
