"""Check that every internal link, image, script, hreflang and canonical in site/dist resolves
to a built file, and that #fragments point at an element that exists. Run after building:

    python3 site/check_links.py
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from siteconfig import BASE_URL as BASE

DIST = Path(__file__).resolve().parent / "dist"


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        for key in ("href", "src"):
            if a.get(key):
                self.refs.append(a[key])
        if a.get("srcset"):
            self.refs += [part.strip().split()[0] for part in a["srcset"].split(",")]
        if tag == "meta" and a.get("property") in ("og:image", "og:url"):
            self.refs.append(a["content"])


def target_file(path: str) -> Path:
    p = DIST / unquote(path).lstrip("/")
    return p / "index.html" if path.endswith("/") else p


def main() -> int:
    pages = {}
    for f in DIST.rglob("*.html"):
        parser = Page()
        parser.feed(f.read_text("utf-8"))
        url = "/" + str(f.relative_to(DIST)).removesuffix("index.html")
        pages[url] = parser
    problems = []
    checked = 0
    for url, page in sorted(pages.items()):
        for ref in page.refs:
            absolute = urljoin(BASE + url, ref)
            u = urlparse(absolute)
            if f"{u.scheme}://{u.netloc}" != BASE:
                continue
            checked += 1
            f = target_file(u.path)
            if not f.exists():
                problems.append(f"{url}: {ref} -> missing")
                continue
            if u.fragment and f.suffix == ".html":
                key = "/" + str(f.relative_to(DIST)).removesuffix("index.html")
                if key in pages and u.fragment not in pages[key].ids:
                    problems.append(f"{url}: {ref} -> no element with id '{u.fragment}'")
    # The sitemap too.
    sitemap = (DIST / "sitemap.xml").read_text("utf-8")
    for loc in re.findall(r'(?:<loc>|href=")(https://[^<"]+)', sitemap):
        checked += 1
        if not target_file(urlparse(loc).path).exists():
            problems.append(f"sitemap.xml: {loc} -> missing")
    for p in problems:
        print(p)
    print(f"{checked} internal references in {len(pages)} pages checked, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
