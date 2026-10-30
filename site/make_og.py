"""Draw the 1200x630 social image for each language: the headline from i18n meta.og_headline,
a listing card with its price including fees, and Mags with a new alert.

build.py calls ensure(), which only redraws an image when its words (or this script) changed,
and keeps the results in site/assets/og/ so they are committed and reviewable. Run it directly
to force a redraw:

    python3 site/build.py            # redraws what changed
    uv run --with pillow --with fonttools --with brotli python site/make_og.py   # redraws all
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SITE = Path(__file__).resolve().parent
FONTS = SITE / "assets/fonts"
SC = 2  # draw at 2x, then downsample
W, H = 1200 * SC, 630 * SC
TEAL = (0, 119, 130)
LIGHT = (201, 240, 238)
AMBER = (249, 187, 66)
INK = (21, 25, 26)


def s(v: float) -> int:
    return int(v * SC)


class Face:
    """A family split over latin and latin-ext subsets: draws each character with the first
    subset that has it."""

    def __init__(self, files: list[str], axes: list[float]):
        self.parts = []
        for name in files:
            tt = TTFont(FONTS / name)
            tt.flavor = None
            buf = io.BytesIO()
            tt.save(buf)
            self.parts.append((buf.getvalue(), set(tt.getBestCmap())))
        self.axes = axes
        self._cache: dict[tuple[int, int], ImageFont.FreeTypeFont] = {}

    def font(self, i: int, size: int, weight: float):
        key = (i, size, weight)
        if key not in self._cache:
            f = ImageFont.truetype(io.BytesIO(self.parts[i][0]), size)
            f.set_variation_by_axes([weight])
            self._cache[key] = f
        return self._cache[key]

    def runs(self, text: str):
        out: list[list] = []
        for ch in text:
            idx = next((i for i, (_, cmap) in enumerate(self.parts) if ord(ch) in cmap), 0)
            if out and out[-1][0] == idx:
                out[-1][1] += ch
            else:
                out.append([idx, ch])
        return out

    def width(self, d: ImageDraw.ImageDraw, text: str, size: int, weight: float) -> float:
        return sum(d.textlength(t, font=self.font(i, size, weight)) for i, t in self.runs(text))

    def draw(self, d, xy, text, size, weight, fill, anchor="la"):
        x, y = xy
        for i, t in self.runs(text):
            f = self.font(i, size, weight)
            d.text((x, y), t, font=f, fill=fill, anchor=anchor)
            x += d.textlength(t, font=f)
        return x


GAB = None
INTER = None


def faces():
    global GAB, INTER
    if GAB is None:
        GAB = Face(["Gabarito-latin.woff2", "Gabarito-latin-ext.woff2"], [800])
        INTER = Face(["Inter-latin.woff2", "Inter-latin-ext.woff2"], [500])
    return GAB, INTER


def draw(meta: dict, out: Path):
    gab, inter = faces()
    im = Image.new("RGB", (W, H), TEAL)
    d = ImageDraw.Draw(im)

    icon = (
        Image.open(SITE / "assets/mags/mags-icon-512.png")
        .convert("RGBA")
        .resize((s(52), s(52)), Image.LANCZOS)
    )
    im.paste(icon, (s(64), s(58)), icon)
    gab.draw(d, (s(128), s(84)), "vinted-sniper", s(32), 800, "white", anchor="lm")

    # Headline: up to four lines; the later ones must clear Mags in the lower middle.
    lines = meta["og_headline"][:4]
    limits = [s(770), s(770), s(700), s(520)]
    if len(lines) < 4:
        limits = limits[: len(lines) - 1] + [s(520)]
    size = s(62)
    while size > s(40) and any(gab.width(d, ln, size, 860) > lim for ln, lim in zip(lines, limits)):
        size -= s(1)
    step = int(size * 1.065)
    y = s(150) + (4 - len(lines)) * step // 2
    for i, line in enumerate(lines):
        gab.draw(d, (s(64), y), line, size, 860, AMBER if i == 0 else "white")
        y += step

    sub = meta["og_sub"][:2]
    sub_size = s(26)
    while sub_size > s(18) and any(inter.width(d, ln, sub_size, 450) > s(520) for ln in sub):
        sub_size -= s(1)
    for i, line in enumerate(sub):
        inter.draw(
            d, (s(64), s(448) + i * int(sub_size * 1.3)), line, sub_size, 450, (230, 250, 250)
        )

    # Listing card on the right.
    card_meta = meta["og_card"]
    cx, cy, cw = s(862), s(56), s(286)
    ph = int(cw * 1.33)
    card_h = ph + s(118)
    mask = Image.new("L", (cw, card_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw - 1, card_h - 1), radius=s(18), fill=255)
    card = Image.new("RGB", (cw, card_h), "white")
    cd = ImageDraw.Draw(card)
    photo = Image.open(SITE / "assets/demo/straight-leg-jeans.webp").convert("RGB")
    pw, phh = photo.size
    ratio = cw / ph
    top = int((phh - pw / ratio) / 2)
    card.paste(
        photo.crop((0, top, pw, int(top + pw / ratio))).resize((cw, ph), Image.LANCZOS), (0, 0)
    )

    def pill(x, y, text, bg, fg):
        size = s(15)
        tw = inter.width(cd, text, size, 600)
        h = s(30)
        cd.rounded_rectangle((x, y, x + tw + s(22), y + h), radius=h // 2, fill=bg)
        inter.draw(cd, (x + s(11), y + h / 2), text, size, 600, fg, anchor="lm")
        return x + tw + s(22)

    x = pill(s(12), s(12), card_meta["new"], TEAL, "white")
    if inter.width(cd, card_meta["deal"], s(15), 600) + x + s(40) <= cw:
        pill(x + s(6), s(12), card_meta["deal"], AMBER, INK)
    else:
        pill(s(12), s(48), card_meta["deal"], AMBER, INK)
    ty = ph + s(16)
    title_size = s(19)
    while title_size > s(14) and inter.width(cd, card_meta["title"], title_size, 560) > cw - s(28):
        title_size -= s(1)
    inter.draw(cd, (s(16), ty), card_meta["title"], title_size, 560, INK)
    inter.draw(cd, (s(16), ty + s(28)), card_meta["meta"], s(16), 420, (90, 101, 102))
    end = inter.draw(cd, (s(16), ty + s(56)), card_meta["price"], s(25), 650, TEAL)
    inter.draw(cd, (end + s(8), ty + s(63)), card_meta["fees"], s(16), 420, TEAL)

    shadow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shadow).rounded_rectangle(
        (cx, cy + s(14), cx + cw, cy + card_h + s(14)), radius=s(18), fill=90
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(s(18)))
    im.paste((0, 60, 66), (0, 0), shadow)
    im.paste(card, (cx, cy), mask)

    mags = Image.open(SITE / "assets/mags/mags-alert.webp").convert("RGBA")
    mh = s(300)
    mags = mags.resize((int(mags.size[0] * mh / mags.size[1]), mh), Image.LANCZOS)
    im.paste(mags, (s(596), H - mh + s(6)), mags)

    im = im.resize((1200, 630), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, quality=86, optimize=True, progressive=True)


def fingerprint(meta: dict) -> str:
    words = {k: meta[k] for k in ("og_headline", "og_sub", "og_card")}
    blob = json.dumps(words, ensure_ascii=False, sort_keys=True) + Path(__file__).read_text("utf-8")
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def ensure(i18n: dict[str, dict], src_dir: Path, dist_dir: Path | None = None, force: bool = False):
    manifest_path = src_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    changed = False
    for lang, t in i18n.items():
        fp = fingerprint(t["meta"])
        out = src_dir / f"{lang}.jpg"
        if force or manifest.get(lang) != fp or not out.exists():
            draw(t["meta"], out)
            manifest[lang] = fp
            changed = True
            print(f"  drew social image for {lang}")
        if dist_dir is not None:
            dist_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(out, dist_dir / out.name)
    if changed:
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    data = {
        f.stem: json.loads(f.read_text("utf-8")) for f in sorted((SITE / "i18n").glob("*.json"))
    }
    ensure(data, SITE / "assets/og", force=True)
