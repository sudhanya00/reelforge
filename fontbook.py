"""Fonts for captions: the bundled ones (fonts/) plus the user's own (library/fonts/), either
uploaded (.ttf/.otf) or imported from Google Fonts at a chosen weight.

Everything a caption needs about a font is read from the file itself: the full name libass
matches on, and the vertical metrics that make the web preview the same size as the export.
"""
from __future__ import annotations

import json
import re
import struct
import time
import urllib.parse
import urllib.request
from pathlib import Path

BUNDLED_DIR = Path(__file__).resolve().parent / "fonts"

# id, label, file (names and metrics come from the file)
BUNDLED = [
    ("poppins-black", "Poppins Black", "Poppins-Black.ttf"),
    ("poppins-extrabold", "Poppins ExtraBold", "Poppins-ExtraBold.ttf"),
    ("poppins-semibold", "Poppins SemiBold", "Poppins-SemiBold.ttf"),
    ("kanit-bold", "Kanit Bold", "Kanit-Bold.ttf"),
    ("anton", "Anton", "Anton-Regular.ttf"),
    ("bebas", "Bebas Neue", "BebasNeue-Regular.ttf"),
    ("archivo-black", "Archivo Black", "ArchivoBlack-Regular.ttf"),
    ("luckiest-guy", "Luckiest Guy", "LuckiestGuy-Regular.ttf"),
    ("permanent-marker", "Permanent Marker", "PermanentMarker-Regular.ttf"),
    ("dm-serif", "DM Serif Display", "DMSerifDisplay-Regular.ttf"),
]
DEFAULT_FONT = "poppins-extrabold"

WEIGHTS = {100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular", 500: "Medium",
           600: "SemiBold", 700: "Bold", 800: "ExtraBold", 900: "Black"}

# One-click imports: popular caption fonts on Google Fonts (family, weight)
POPULAR = [("Montserrat", 900), ("Montserrat", 800), ("Inter", 800), ("Bangers", 400),
           ("Oswald", 700), ("Roboto", 900), ("Rubik", 800), ("Nunito", 900), ("Lilita One", 400),
           ("Titan One", 400), ("Fredoka", 700), ("Barlow Condensed", 800), ("Bricolage Grotesque", 800),
           ("Caveat", 700), ("Playfair Display", 900)]

MAX_BYTES = 15 * 1024 * 1024
GOOGLE_UA = "Wget/1.21"          # the CSS API answers old user agents with TrueType files
FETCH = None                     # tests: fn(url, headers) -> bytes


class FontError(ValueError):
    pass


def _fetch(url: str, headers: dict | None = None) -> bytes:
    if FETCH:
        return FETCH(url, headers or {})
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:        # noqa: S310 - fixed Google hosts
        return r.read()


# ---------------------------------------------------------------- reading font files

def _tables(d: bytes) -> dict[bytes, tuple[int, int]]:
    out = {}
    for i in range(struct.unpack(">H", d[4:6])[0]):
        tag, _, off, ln = struct.unpack(">4sIII", d[12 + 16 * i:28 + 16 * i])
        out[tag] = (off, ln)
    return out


def check(data: bytes) -> None:
    """A single TrueType/OpenType font, or a FontError saying what it is instead."""
    head = data[:4]
    if head in (b"wOFF", b"wOF2"):
        raise FontError("That's a web font (WOFF). Use the .ttf or .otf version.")
    if head == b"ttcf":
        raise FontError("That's a font collection (.ttc). Use a single .ttf or .otf.")
    if head not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        raise FontError("Not a font file. Use a .ttf or .otf.")
    if len(data) > MAX_BYTES:
        raise FontError("That font file is over 15 MB.")
    try:
        t = _tables(data)
    except struct.error:
        raise FontError("That font file is damaged.")
    for need in (b"name", b"head", b"cmap"):
        if need not in t:
            raise FontError("That font file is missing parts it needs.")


def info(data: bytes) -> dict:
    """Names (Windows, English) and the scale that matches libass sizing in a browser."""
    t = _tables(data)
    off, _ = t[b"name"]
    _, count, storage = struct.unpack(">HHH", data[off:off + 6])
    names = {}
    for j in range(count):
        pid, _, lid, nid, ln, o = struct.unpack(">HHHHHH", data[off + 6 + 12 * j:off + 18 + 12 * j])
        if pid == 3 and lid in (0x409, 0) and nid in (1, 2, 4, 16, 17) and nid not in names:
            names[nid] = data[off + storage + o:off + storage + o + ln].decode("utf-16-be", "replace")
    head = t[b"head"][0]
    upem = struct.unpack(">H", data[head + 18:head + 20])[0]
    asc = desc = 0
    if b"OS/2" in t:
        os2 = t[b"OS/2"][0]
        asc, desc = struct.unpack(">HH", data[os2 + 74:os2 + 78])
    if not asc and b"hhea" in t:
        hh = t[b"hhea"][0]
        asc, d = struct.unpack(">hh", data[hh + 4:hh + 8])
        desc = -d
    full = names.get(4) or " ".join(x for x in (names.get(1), names.get(2)) if x and x != "Regular") or "Font"
    return {"full": full, "family": names.get(1, full), "style": names.get(2, "Regular"),
            "em_scale": round(upem / (asc + desc), 4) if asc + desc > 0 else 0.75,
            "variable": b"fvar" in t}


# ---------------------------------------------------------------- the book

class FontBook:
    def __init__(self, library_root: Path):
        self.dir = Path(library_root) / "fonts"
        self.index = self.dir / "fonts.json"

    def _user(self) -> list[dict]:
        try:
            return json.loads(self.index.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save(self, fonts: list[dict]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index.write_text(json.dumps(fonts, indent=2, ensure_ascii=False), encoding="utf-8")

    def all(self) -> list[dict]:
        out = bundled_fonts()
        for f in self._user():
            p = self.dir / f["file"]
            if p.exists():
                out.append({**f, "path": p, "url": f"/user-fonts/{f['file']}", "user": True})
        return out

    def ids(self) -> list[str]:
        return [f["id"] for f in self.all()]

    def get(self, fid: str) -> dict:
        fonts = self.all()
        return next((f for f in fonts if f["id"] == fid), None) or next(f for f in fonts if f["id"] == DEFAULT_FONT)

    def view(self) -> list[dict]:
        return [{k: v for k, v in f.items() if k != "path"} for f in self.all()]

    def add(self, data: bytes, filename: str = "", source: str = "upload", label: str | None = None) -> dict:
        check(data)
        i = info(data)
        fid = "user-" + (re.sub(r"[^a-z0-9]+", "-", i["full"].lower()).strip("-") or "font")
        ext = ".otf" if data[:4] == b"OTTO" or filename.lower().endswith(".otf") else ".ttf"
        entry = {"id": fid, "label": label or i["full"], "file": fid + ext, "ass_name": i["full"],
                 "em_scale": i["em_scale"], "variable": i["variable"], "source": source, "added": time.time()}
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / entry["file"]).write_bytes(data)
        self._save([f for f in self._user() if f["id"] != fid] + [entry])
        return {**entry, "url": f"/user-fonts/{entry['file']}", "user": True}

    def remove(self, fid: str) -> None:
        fonts = self._user()
        f = next((x for x in fonts if x["id"] == fid), None)
        if not f:
            raise KeyError(fid)
        (self.dir / f["file"]).unlink(missing_ok=True)
        self._save([x for x in fonts if x["id"] != fid])

    # Google Fonts
    def add_google(self, family: str, weight: int) -> dict:
        if weight not in WEIGHTS:
            raise FontError("Pick a weight from 100 to 900.")
        q = urllib.parse.quote(family.strip()).replace("%20", "+")
        try:
            css = _fetch(f"https://fonts.googleapis.com/css2?family={q}:wght@{weight}",
                         {"User-Agent": GOOGLE_UA}).decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            raise FontError(f"Google Fonts has no {family} at weight {weight} ({e}).")
        m = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+\.ttf)\)", css)
        if not m:
            raise FontError(f"Google Fonts didn't offer {family} {WEIGHTS[weight]} as a TrueType file.")
        data = _fetch(m.group(1), {"User-Agent": GOOGLE_UA})
        label = f"{family.strip()} {WEIGHTS[weight]}" if weight != 400 else family.strip()
        return self.add(data, f"{family}.ttf", source="google", label=label)

    def google_catalog(self, max_age_s: int = 7 * 86400) -> list[dict]:
        """Every Google Fonts family with its upright weights, cached for a week."""
        cache = self.dir / "google_fonts_v2.json"
        if cache.exists() and time.time() - cache.stat().st_mtime < max_age_s:
            return json.loads(cache.read_text(encoding="utf-8"))
        raw = _fetch("https://fonts.google.com/metadata/fonts").decode("utf-8")
        meta = json.loads(raw[raw.index("{"):])
        fams = [{"family": f["family"], "category": f.get("category", ""), "popularity": f.get("popularity", 9999),
                 "weights": sorted(int(k) for k in f.get("fonts", {}) if k.isdigit())}
                for f in meta.get("familyMetadataList", [])
                # open-licence families only: brand fonts (e.g. Google Sans) aren't free to reuse
                if not f.get("isNoto") and not f.get("isBrandFont") and f.get("isOpenSource", True)]
        fams = [f for f in fams if f["weights"]]
        self.dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(fams), encoding="utf-8")
        return fams

    def search_google(self, q: str, limit: int = 24) -> list[dict]:
        fams = self.google_catalog()
        q = q.strip().lower()
        if q:
            hits = [f for f in fams if q in f["family"].lower()]
            hits.sort(key=lambda f: (not f["family"].lower().startswith(q), f["popularity"]))
        else:
            hits = sorted((f for f in fams if f["category"] in ("Sans Serif", "Display", "Handwriting")),
                          key=lambda f: f["popularity"])
        return hits[:limit]


def bundled_fonts() -> list[dict]:
    out = []
    for fid, label, file in BUNDLED:
        p = BUNDLED_DIR / file
        if p.exists():
            i = _cached_info(p)
            out.append({"id": fid, "label": label, "path": p, "url": f"/fonts/{file}", "ass_name": i["full"],
                        "em_scale": i["em_scale"], "user": False, "variable": False, "source": "bundled"})
    return out


_info: dict[tuple[str, float], dict] = {}


def _cached_info(p: Path) -> dict:
    key = (str(p), p.stat().st_mtime)
    if key not in _info:
        _info[key] = info(p.read_bytes())
    return _info[key]
