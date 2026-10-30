"""Build the landing site into site/dist/, which is what gets deployed.

    python3 site/build.py

Sources:
  site/templates/              Jinja layouts: base, home, guide, guides index, text page, 404
  site/i18n/<lang>.json        every UI string, one file per language (en is the source of truth)
  site/content/guides/<lang>/  guides as Markdown with YAML front matter
  site/assets/                 CSS, JS, fonts, images; CSS, JS, fonts and the icon sprite get a
                               content hash in their file name so they can be cached for a year
  site/static/                 files served from the root as they are (favicons, IndexNow key)
  ../install.sh, install.ps1, llms.txt, CHANGELOG.md, docs/*.md   copied or rendered from the repo

Needs jinja2, markdown and PyYAML (plus Pillow and fontTools when a social image needs redrawing).
If they aren't importable, the script re-runs itself with `uv run --with ...`, so a plain
`python3 site/build.py` works on any machine that has uv.
"""

from __future__ import annotations

import os
import sys

DEPS = ["jinja2", "markdown", "pyyaml", "pillow", "fonttools", "brotli"]
try:
    import jinja2  # noqa: F401
    import markdown  # noqa: F401
    import yaml  # noqa: F401
except ImportError:
    if os.environ.get("VS_SITE_BUILD_REEXEC"):
        raise
    os.environ["VS_SITE_BUILD_REEXEC"] = "1"
    cmd = ["uv", "run", "--quiet", "--no-project"]
    for dep in DEPS:
        cmd += ["--with", dep]
    os.execvp("uv", [*cmd, "python", os.path.abspath(__file__), *sys.argv[1:]])

import datetime as dt
import hashlib
import html
import json
import re
import shutil
import subprocess
import tomllib
import urllib.parse
from pathlib import Path

import markdown
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup, escape

SITE = Path(__file__).resolve().parent
ROOT = SITE.parent
DIST = SITE / "dist"
BASE_URL = "https://vinted-sniper.jaspnerd.dev"
REPO = "https://github.com/jasp-nerd/vinted-sniper"
REPO_BLOB = f"{REPO}/blob/main"
REPO_RAW = "https://raw.githubusercontent.com/jasp-nerd/vinted-sniper/main"

# Language order on the site: English is the root and x-default.
LANG_ORDER = ["en", "fr", "de", "it", "es", "pl", "nl"]

# Fixed facts about the hero demo listings; their words come from i18n demo.items.
DEMO = [
    ("straight-leg-jeans", 1, 24), ("wool-coat", 2, 33), ("vintage-windbreaker", 3, None),
    ("denim-jacket", 1, None), ("cable-knit-sweater", 2, 27), ("trench-coat", 2, None),
    ("kids-raincoat", 4, 31), ("knitted-beanie", 2, None), ("leather-jacket", 3, 24),
    ("puffer-jacket", 3, None), ("breton-top", 2, None), ("suede-boots", 3, None),
]

MONTHS = {
    "en": "January February March April May June July August September October November December",
    "fr": "janvier février mars avril mai juin juillet août septembre octobre novembre décembre",
    "de": "Januar Februar März April Mai Juni Juli August September Oktober November Dezember",
    "it": "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre",
    "es": "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre",
    "pl": "stycznia lutego marca kwietnia maja czerwca lipca sierpnia września października listopada grudnia",
    "nl": "januari februari maart april mei juni juli augustus september oktober november december",
}

# English-only pages rendered from the repo's Markdown.
DOCS = {
    "troubleshooting": {
        "src": "docs/troubleshooting.md",
        "title": "Troubleshooting: Vinted alerts not arriving | vinted-sniper",
        "description": "Fix vinted-sniper when it stops finding listings or sending alerts: search status, 403 and 429 errors, Telegram, Discord, updates and logs.",
    },
    "self-hosting": {
        "src": "docs/self-hosting.md",
        "title": "Run a free Vinted bot 24/7: Pi, NAS, Docker, VPS | vinted-sniper",
        "description": "Keep vinted-sniper running all day on your computer, a Raspberry Pi, Docker, a NAS (Unraid, Synology, Umbrel, CasaOS) or a small VPS. Backups and updates.",
    },
    "legal": {
        "src": "docs/legal.md",
        "title": "Are Vinted bots allowed? Rules and risks | vinted-sniper",
        "description": "What Vinted's terms say about bots, what that means in practice, how vinted-sniper stays a polite guest, and handling other people's data. Not legal advice.",
    },
}


# ───────────────────────── helpers ─────────────────────────

def prefix(lang: str) -> str:
    return "/" if lang == "en" else f"/{lang}/"


def absolute(path: str) -> str:
    return BASE_URL + path


def fmt_date(value: str, lang: str) -> str:
    d = dt.date.fromisoformat(value)
    month = MONTHS[lang].split()[d.month - 1]
    if lang == "en":
        return f"{d.day} {month} {d.year}"
    if lang == "de":
        return f"{d.day}. {month} {d.year}"
    if lang == "es":
        return f"{d.day} de {month} de {d.year}"
    return f"{d.day} {month} {d.year}"


_git_dates: dict[str, str | None] = {}


def last_changed(*paths: Path) -> str:
    """The real date a set of source files last changed: the git commit date, or today for
    files with uncommitted edits."""
    best = "2026-08-16"
    for p in paths:
        key = str(p)
        if key not in _git_dates:
            rel = p.relative_to(ROOT)
            dirty = subprocess.run(["git", "status", "--porcelain", "--", str(rel)], cwd=ROOT,
                                   capture_output=True, text=True).stdout.strip()
            if dirty:
                _git_dates[key] = dt.date.today().isoformat()
            else:
                out = subprocess.run(["git", "log", "-1", "--format=%cs", "--", str(rel)], cwd=ROOT,
                                     capture_output=True, text=True).stdout.strip()
                _git_dates[key] = out or dt.date.today().isoformat()
        best = max(best, _git_dates[key] or best)
    return best


def trusted(obj, plain=False):
    """i18n strings are ours and may hold inline HTML; mark them safe, except the ones that
    are plain text by nature (meta tags, the AI prompt)."""
    if isinstance(obj, dict):
        return {k: trusted(v, plain or k in {"meta", "prompt"}) for k, v in obj.items()}
    if isinstance(obj, list):
        return [trusted(v, plain) for v in obj]
    if isinstance(obj, str):
        return obj if plain else Markup(obj)
    return obj


def load_i18n() -> dict[str, dict]:
    out = {}
    for lang in LANG_ORDER:
        f = SITE / "i18n" / f"{lang}.json"
        if not f.exists():
            print(f"  ! no strings for {lang}, skipping that language")
            continue
        raw = f.read_text("utf-8").replace("{p}", prefix(lang))
        out[lang] = json.loads(raw)
    return out


# ───────────────────────── assets ─────────────────────────

class Assets:
    """Copies site/assets into dist and gives CSS, JS, fonts and the icon sprite a content
    hash in their names, so nginx can cache them for a year."""

    HASHED = ("css/site.css", "js/site.js", "icons.svg", "fonts/Gabarito-latin.woff2",
              "fonts/Gabarito-latin-ext.woff2", "fonts/Inter-latin.woff2", "fonts/Inter-latin-ext.woff2")

    def __init__(self):
        self.map: dict[str, str] = {}

    def build(self):
        src = SITE / "assets"
        dst = DIST / "assets"
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".DS_Store"))
        # Fonts first, so the CSS can point at their hashed names.
        for rel in sorted(self.HASHED, key=lambda r: not r.startswith("fonts/")):
            path = dst / rel
            data = path.read_bytes()
            if rel == "css/site.css":
                text = data.decode("utf-8")
                for frel, fhashed in self.map.items():
                    if frel.startswith("fonts/"):
                        text = text.replace(f"../{frel}", "../" + fhashed.removeprefix("/assets/"))
                data = text.encode("utf-8")
            digest = hashlib.sha256(data).hexdigest()[:10]
            hashed = path.with_name(f"{path.stem}.{digest}{path.suffix}")
            hashed.write_bytes(data)
            path.unlink()
            self.map[rel] = "/assets/" + str(hashed.relative_to(dst))

    def __call__(self, rel: str) -> str:
        return self.map.get(rel, "/assets/" + rel)


# ───────────────────────── Markdown ─────────────────────────

def md_renderer() -> markdown.Markdown:
    return markdown.Markdown(
        extensions=["extra", "toc", "sane_lists"],
        extension_configs={"toc": {"slugify": markdown.extensions.toc.slugify_unicode, "toc_depth": "2-3"}},
    )


def split_front_matter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m:
        raise ValueError("missing front matter")
    meta = yaml.safe_load(m.group(1)) or {}
    return meta, m.group(2)


# ───────────────────────── the site ─────────────────────────

class Site:
    def __init__(self):
        self.i18n = load_i18n()
        self.langs = list(self.i18n)
        self.t = {lang: trusted(d) for lang, d in self.i18n.items()}
        self.version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
        self.assets = Assets()
        self.pages: list[dict] = []
        self.guides: dict[str, list[dict]] = {}  # lang -> guides, newest first
        self.env = Environment(loader=FileSystemLoader(SITE / "templates"), autoescape=True,
                               undefined=StrictUndefined, trim_blocks=False, lstrip_blocks=False)
        self.env.filters["a"] = lambda s: escape(str(s))
        self.env.filters["q"] = lambda s: urllib.parse.quote(str(s), safe="")
        self.env.globals["zip"] = zip

    # ── content discovery ──

    def load_guides(self, content_dir: Path):
        by_lang: dict[str, list[dict]] = {}
        for lang in self.langs:
            folder = content_dir / lang
            if not folder.is_dir():
                continue
            for f in sorted(folder.glob("*.md")):
                meta, body = split_front_matter(f.read_text("utf-8"))
                for field in ("title", "description", "slug", "key", "date", "updated"):
                    if not meta.get(field):
                        raise SystemExit(f"{f}: front matter needs '{field}'")
                date, updated = str(meta["date"]), str(meta["updated"])
                g = {
                    "lang": lang, "file": f, "body": body,
                    "title": meta["title"], "description": meta["description"],
                    "slug": meta["slug"], "key": meta["key"],
                    "date": date, "updated": updated,
                    "date_h": fmt_date(date, lang), "updated_h": fmt_date(updated, lang),
                    "keywords": meta.get("keywords") or [], "faq": meta.get("faq") or [],
                    "path": f"{prefix(lang)}guides/{meta['slug']}/",
                }
                if len(g["description"]) > 160:
                    print(f"  ! {f.name}: description is {len(g['description'])} chars")
                by_lang.setdefault(lang, []).append(g)
        for lang, items in by_lang.items():
            items.sort(key=lambda g: (g["date"], g["updated"]), reverse=True)
        self.guides = by_lang
        self.by_key: dict[str, dict[str, dict]] = {}
        self.by_slug: dict[str, list[dict]] = {}
        for items in by_lang.values():
            for g in items:
                self.by_key.setdefault(g["key"], {})[g["lang"]] = g
                self.by_slug.setdefault(g["slug"], []).append(g)

    def guide_link(self, lang: str, slug: str) -> str | None:
        """Where /guides/<slug>/ should point on a page in `lang`: that language's version of
        the guide if there is one, else the guide as written."""
        candidates = self.by_slug.get(slug)
        if not candidates:
            return None
        for g in candidates:
            if g["lang"] == lang:
                return g["path"]
        key = candidates[0]["key"]
        versions = self.by_key[key]
        if lang in versions:
            return versions[lang]["path"]
        return (versions.get("en") or candidates[0])["path"]

    def rewrite_links(self, body_html: str, lang: str, source: str) -> str:
        pfx = prefix(lang)

        def fix(m: re.Match) -> str:
            href = html.unescape(m.group(2))
            new = href
            gm = re.match(r"^/(?:[a-z]{2}/)?guides/([^/#?]+)/?(#.*)?$", href)
            if gm:
                target = self.guide_link(lang, gm.group(1))
                if target is None:
                    print(f"  ! {source}: link to a guide that doesn't exist: {href}")
                else:
                    new = target + (gm.group(2) or "")
            elif re.match(r"^/(?:[a-z]{2}/)?guides/?$", href):
                new = f"{pfx}guides/" if self.guides.get(lang) else "/guides/"
            elif href in ("/", "") or href.startswith("/#"):
                new = pfx + href.lstrip("/")
            elif href.startswith("/about/"):
                new = pfx + href.lstrip("/")
            return f'{m.group(1)}="{escape(new)}"'

        return re.sub(r'(href)="([^"]*)"', fix, body_html)

    # ── page model ──

    def add(self, **page):
        page.setdefault("noindex", False)
        page.setdefault("alternates", {page["lang"]: page["path"]})
        self.pages.append(page)

    def collect(self):
        for lang in self.langs:
            t = self.i18n[lang]
            home_alts = {l: prefix(l) for l in self.langs}
            self.add(kind="home", lang=lang, path=prefix(lang), alternates=home_alts,
                     title=t["meta"]["title"], description=t["meta"]["description"],
                     og_title=t["meta"]["og_title"], og_description=t["meta"]["og_description"],
                     sources=[SITE / "templates/home.html", SITE / f"i18n/{lang}.json"], priority="1.0")
            self.add(kind="about", lang=lang, path=f"{prefix(lang)}about/",
                     alternates={l: f"{prefix(l)}about/" for l in self.langs},
                     title=t["about"]["title"], description=t["about"]["description"],
                     sources=[SITE / "templates/page.html", SITE / f"i18n/{lang}.json"])
            self.add(kind="404", lang=lang, path=f"{prefix(lang)}404.html", noindex=True,
                     title=t["notfound"]["title"], description=t["notfound"]["text"], sources=[])

        idx_alts = {l: f"{prefix(l)}guides/" for l in self.langs if self.guides.get(l)}
        for lang in self.langs:
            items = self.guides.get(lang)
            if not items:
                continue
            t = self.i18n[lang]
            self.add(kind="guides", lang=lang, path=f"{prefix(lang)}guides/", alternates=idx_alts,
                     title=t["guides"]["title"], description=t["guides"]["description"],
                     lastmod=max(g["updated"] for g in items), section="guides",
                     sources=[SITE / f"i18n/{lang}.json"])
            for g in items:
                alts = {l: v["path"] for l, v in self.by_key[g["key"]].items()}
                self.add(kind="guide", lang=lang, path=g["path"], alternates=alts, guide=g,
                         title=f"{g['title']} | vinted-sniper" if len(g["title"]) <= 44 else g["title"],
                         description=g["description"], og_type="article",
                         lastmod=g["updated"], section="guides", sources=[])

        for slug, d in DOCS.items():
            self.add(kind="doc", lang="en", path=f"/docs/{slug}/", doc_slug=slug,
                     title=d["title"], description=d["description"], sources=[ROOT / d["src"]])
        self.add(kind="changelog", lang="en", path="/changelog/",
                 title="What's new in vinted-sniper: changelog",
                 description="Every vinted-sniper release, newest first: what changed, what was fixed, and what to know before you update.",
                 sources=[ROOT / "CHANGELOG.md"])

    # ── JSON-LD ──

    def person(self):
        return {"@type": "Person", "@id": f"{BASE_URL}/#author", "name": "jasp-nerd",
                "url": absolute("/about/"), "sameAs": ["https://github.com/jasp-nerd"]}

    def jsonld(self, page, t, og_image):
        lang = page["lang"]
        url = absolute(page["path"])
        website = {"@type": "WebSite", "@id": f"{BASE_URL}/#website", "url": BASE_URL + "/",
                   "name": "vinted-sniper", "description": self.i18n["en"]["meta"]["site_description"],
                   "inLanguage": self.langs, "publisher": {"@id": f"{BASE_URL}/#author"}}
        graph = [website, self.person()]

        def crumbs_ld(crumbs):
            return {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": c["name"], "item": absolute(c["path"])}
                for i, c in enumerate(crumbs)]}

        if page["kind"] == "home":
            graph.append({
                "@type": "SoftwareApplication", "@id": f"{BASE_URL}/#app", "name": "vinted-sniper",
                "description": t["meta"]["app_description"], "url": url, "inLanguage": lang,
                "applicationCategory": "UtilitiesApplication", "operatingSystem": "Windows, macOS, Linux",
                "softwareVersion": self.version, "downloadUrl": "https://pypi.org/project/vinted-sniper/",
                "installUrl": url + "#install", "license": "https://opensource.org/licenses/MIT",
                "isAccessibleForFree": True,
                "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR"},
                "screenshot": absolute("/assets/shots/finds.webp"), "image": og_image,
                "author": {"@id": f"{BASE_URL}/#author"}, "publisher": {"@id": f"{BASE_URL}/#author"},
                "sameAs": [REPO, "https://pypi.org/project/vinted-sniper/"],
            })
            graph.append({"@type": "WebPage", "@id": url + "#webpage", "url": url, "name": page["title"],
                          "inLanguage": lang, "isPartOf": {"@id": f"{BASE_URL}/#website"},
                          "about": {"@id": f"{BASE_URL}/#app"}})
        elif page["kind"] == "guide":
            g = page["guide"]
            graph.append({
                "@type": "Article", "@id": url + "#article", "headline": g["title"],
                "description": g["description"], "inLanguage": lang, "url": url,
                "mainEntityOfPage": url, "datePublished": g["date"], "dateModified": g["updated"],
                "image": og_image, "keywords": ", ".join(g["keywords"]),
                "author": {"@id": f"{BASE_URL}/#author"}, "publisher": {"@id": f"{BASE_URL}/#author"},
                "about": {"@type": "SoftwareApplication", "@id": f"{BASE_URL}/#app", "name": "vinted-sniper"},
            })
            graph.append(crumbs_ld(page["crumbs"]))
        elif page["kind"] == "about":
            graph.append({"@type": "AboutPage", "url": url, "name": page["title"], "inLanguage": lang,
                          "mainEntity": {"@id": f"{BASE_URL}/#author"}})
            graph.append(crumbs_ld(page["crumbs"]))
        elif page["kind"] == "guides":
            graph.append({"@type": "CollectionPage", "url": url, "name": page["title"], "inLanguage": lang})
            graph.append(crumbs_ld(page["crumbs"]))
        else:
            graph.append({"@type": "WebPage", "url": url, "name": page["title"], "inLanguage": lang,
                          "dateModified": page.get("lastmod")})
            graph.append(crumbs_ld(page["crumbs"]))
        data = {"@context": "https://schema.org", "@graph": graph}
        # Safe inside <script>: no "</" can close the tag early.
        return Markup(json.dumps(data, ensure_ascii=False, indent=1).replace("</", "<\\/"))

    # ── rendering ──

    def hreflang(self, page):
        if page["noindex"]:
            return []
        alts = page["alternates"]
        out = [{"hreflang": l, "url": absolute(alts[l])} for l in self.langs if l in alts]
        default = alts.get("en") or page["path"]
        out.append({"hreflang": "x-default", "url": absolute(default)})
        return out

    def render(self, page):
        lang = page["lang"]
        t_raw, t = self.i18n[lang], self.t[lang]
        alts = page["alternates"]
        guides_url = f"{prefix(lang)}guides/" if self.guides.get(lang) else None
        switcher = [{"lang": l, "name": self.i18n[l]["meta"]["name"],
                     "href": alts.get(l) if (l in alts and page["kind"] != "404") else prefix(l),
                     "current": l == lang} for l in self.langs]
        og_lang = lang if (SITE / "assets/og" / f"{lang}.jpg").exists() else "en"
        og_image = absolute(f"/assets/og/{og_lang}.jpg")
        home = {"name": t_raw["common"]["home"], "path": prefix(lang)}
        ctx = {"t": t, "lang": lang, "prefix": prefix(lang), "icons": self.assets("icons.svg"),
               "asset": self.assets, "switcher": switcher, "guides_url": guides_url,
               "home_anchor": "" if page["kind"] == "home" else prefix(lang), "crumbs": None}
        kind = page["kind"]

        if kind == "home":
            items = [dict(it, img=img, s=s, deal=deal) for it, (img, s, deal) in zip(t["demo"]["items"], DEMO)]
            ctx["demo"] = items
            ctx["guides"] = self.guides.get(lang, [])
            js = {k: t_raw["demo"][k] for k in ("match", "fees", "new", "under", "ages", "pause", "play",
                                               "copied", "copy_fail", "copied_sr", "copy_fail_sr")}
            js["items"] = [dict(it, img=img, s=s, deal=deal)
                           for it, (img, s, deal) in zip(t_raw["demo"]["items"], DEMO)]
            page["i18n_json"] = Markup(json.dumps(js, ensure_ascii=False).replace("</", "<\\/"))
            template = "home.html"
        elif kind == "guide":
            g = page["guide"]
            ctx["crumbs"] = [home, {"name": t_raw["guides"]["h1"], "path": f"{prefix(lang)}guides/"},
                             {"name": g["title"], "path": g["path"]}]
            md = md_renderer()
            body = g["body"]
            has_cta = "{{install}}" in body
            body = body.replace("{{install}}", "\n\n<!--INSTALL-CTA-->\n\n")
            body_html = md.convert(body)
            body_html = self.rewrite_links(body_html, lang, g["file"].name)
            if has_cta:
                cta = self.env.get_template("_install_cta.html").render(ctx)
                body_html = body_html.replace("<!--INSTALL-CTA-->", cta)
            words = len(re.sub(r"<[^>]+>", " ", body_html).split())
            gctx = dict(g, html=Markup(body_html), has_cta=has_cta, minutes=max(1, round(words / 200)),
                        toc=[{"id": tok["id"], "name": Markup(tok["name"])} for tok in md.toc_tokens])
            gctx["faq"] = [{"q": f["q"], "a": Markup(self.rewrite_links(
                markdown.markdown(str(f["a"])).removeprefix("<p>").removesuffix("</p>"), lang, g["file"].name))}
                for f in g["faq"]]
            ctx["g"] = gctx
            others = [o for o in self.guides[lang] if o is not g]
            ctx["related"] = others[:3]
            template = "guide.html"
        elif kind == "guides":
            ctx["crumbs"] = [home, {"name": t_raw["guides"]["h1"], "path": page["path"]}]
            ctx["guides"] = self.guides[lang]
            template = "guides_index.html"
        elif kind == "about":
            ctx["crumbs"] = [home, {"name": t_raw["about"]["h1"], "path": page["path"]}]
            body = "".join(f"<h2>{s['h']}</h2>{s['body']}" for s in t_raw["about"]["sections"])
            ctx["doc"] = {"h1": t["about"]["h1"], "lead": t["about"]["lead"], "html": Markup(body), "cta": True,
                          "note": None, "meta": None}
            template = "page.html"
        elif kind in ("doc", "changelog"):
            ctx["crumbs"] = [home, {"name": page["title"].split(" | ")[0].split(":")[0], "path": page["path"]}]
            ctx["doc"] = self.render_markdown_page(page)
            ctx["crumbs"][-1]["name"] = ctx["doc"]["h1"]
            template = "page.html"
        else:  # 404
            template = "404.html"

        page["crumbs"] = ctx["crumbs"]
        page["hreflang"] = self.hreflang(page)
        page["url"] = absolute(page["path"])
        page["og_image"] = og_image
        page["og_locale_alternates"] = [self.i18n[l]["meta"]["locale"] for l in self.langs
                                        if l != lang and l in alts]
        if kind == "guide":
            page["article"] = {"date": page["guide"]["date"], "updated": page["guide"]["updated"]}
        page.setdefault("lastmod", last_changed(*page["sources"]) if page["sources"] else None)
        page["jsonld"] = None if page["noindex"] else self.jsonld(page, t_raw, og_image)
        ctx["page"] = page
        out = self.env.get_template(template).render(ctx)
        dest = DIST / page["path"].lstrip("/")
        if page["path"].endswith("/"):
            dest = dest / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(out, "utf-8")

    def render_markdown_page(self, page):
        if page["kind"] == "changelog":
            text = (ROOT / "CHANGELOG.md").read_text("utf-8")
            text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
            # Drop the title and the note to maintainers above the first release.
            text = text[text.index("\n## "):]
            md = md_renderer()
            body = md.convert(text)
            body = self.rewrite_doc_links(body, "CHANGELOG.md")
            return {"h1": "What's new", "lead": Markup(
                "Every release of vinted-sniper, newest first. To update, run the install command again "
                f'(see <a href="/#install">install</a>), or follow the <a href="/docs/self-hosting/#updating">update notes</a>.'),
                "html": Markup(body), "note": None, "cta": False,
                "meta": Markup(f'Current version: {self.version}. Also on <a href="{REPO}/releases">GitHub releases</a>.')}
        d = DOCS[page["doc_slug"]]
        text = (ROOT / d["src"]).read_text("utf-8")
        m = re.match(r"#\s+(.+)\n", text)
        h1 = m.group(1).strip() if m else page["title"]
        text = text[m.end():] if m else text
        md = md_renderer()
        body = self.rewrite_doc_links(md.convert(text), d["src"])
        meta = Markup(f'Last changed {fmt_date(page.get("lastmod") or last_changed(*page["sources"]), "en")}. '
                      f'<a href="{REPO_BLOB}/{d["src"]}">Source on GitHub</a>.')
        return {"h1": h1, "lead": None, "html": Markup(body), "cta": True, "meta": meta,
                "note": "This page is only available in English." if False else None}

    def rewrite_doc_links(self, body_html: str, src: str) -> str:
        base = Path(src).parent

        def fix(m: re.Match) -> str:
            attr, href = m.group(1), html.unescape(m.group(2))
            if re.match(r"^[a-z]+:|^#|^/", href):
                return m.group(0)
            path, _, frag = href.partition("#")
            target = os.path.normpath(base / path) if path else None
            frag = f"#{frag}" if frag else ""
            new = None
            if target:
                slug = Path(target).stem
                if target.startswith("docs/") and slug in DOCS:
                    new = f"/docs/{slug}/{frag}"
                elif target == "CHANGELOG.md":
                    new = f"/changelog/{frag}"
                elif target in ("install.sh", "install.ps1", "llms.txt"):
                    new = f"/{target}"
                elif attr == "src":
                    new = f"{REPO_RAW}/{target}"
                else:
                    new = f"{REPO_BLOB}/{target}{frag}"
            return f'{attr}="{escape(new or href)}"'

        return re.sub(r'(href|src)="([^"]*)"', fix, body_html)

    # ── root files ──

    def write_root_files(self):
        static = SITE / "static"
        if static.is_dir():
            for f in static.iterdir():
                if f.is_file() and f.name != ".DS_Store":
                    shutil.copyfile(f, DIST / f.name)
        for name in ("install.sh", "install.ps1"):
            shutil.copyfile(ROOT / name, DIST / name)
        llms = (ROOT / "llms.txt").read_text("utf-8").rstrip() + "\n"
        lines = ["", "## Guides on the website", ""]
        for lang in self.langs:
            for g in self.guides.get(lang, []):
                lines.append(f"- [{g['title']}]({absolute(g['path'])}) ({lang}): {g['description']}")
        lines += ["", "## Help pages on the website", ""]
        for slug, d in DOCS.items():
            lines.append(f"- [{d['title'].split(' | ')[0]}]({absolute(f'/docs/{slug}/')}): {d['description']}")
        (DIST / "llms.txt").write_text(llms + "\n".join(lines) + "\n", "utf-8")
        (DIST / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {BASE_URL}/sitemap.xml\n", "utf-8")

    def write_sitemap(self):
        out = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">']
        for page in self.pages:
            if page["noindex"]:
                continue
            out.append("  <url>")
            out.append(f"    <loc>{escape(page['url'])}</loc>")
            if page.get("lastmod"):
                out.append(f"    <lastmod>{page['lastmod']}</lastmod>")
            if len(page["hreflang"]) > 2:  # more than itself + x-default
                for alt in page["hreflang"]:
                    out.append(f'    <xhtml:link rel="alternate" hreflang="{alt["hreflang"]}" href="{escape(alt["url"])}"/>')
            out.append("  </url>")
        out.append("</urlset>")
        (DIST / "sitemap.xml").write_text("\n".join(out) + "\n", "utf-8")

    def build(self, content_dir: Path):
        if DIST.exists():
            shutil.rmtree(DIST)
        DIST.mkdir()
        self.load_guides(content_dir)
        self.assets.build()
        import make_og  # noqa: E402  (needs Pillow; only redraws images whose text changed)
        make_og.ensure(self.i18n, SITE / "assets/og", DIST / "assets/og")
        self.collect()
        for page in self.pages:
            self.render(page)
        self.write_root_files()
        self.write_sitemap()
        indexable = sum(not p["noindex"] for p in self.pages)
        print(f"built {len(self.pages)} pages ({indexable} indexable) in {len(self.langs)} languages "
              f"into {DIST.relative_to(ROOT)}/")


def main():
    content = SITE / "content" / "guides"
    if "--content" in sys.argv:  # build against another guides folder, e.g. for testing
        content = Path(sys.argv[sys.argv.index("--content") + 1]).resolve()
    sys.path.insert(0, str(SITE))
    Site().build(content)


if __name__ == "__main__":
    main()
