"""Burned-in captions from the script: the words are always the user's, never transcribed.

Timing comes from one of two places:
  - estimate: each 10 s segment's words spread across its window by length (free)
  - voice: an AI listens and returns only *when* each numbered script word is spoken; it can't
    change the text. It also reports where the speaker said something different, as warnings.

Words are grouped into captions by style (words per caption, sentence and line breaks) and
written as an ASS subtitle file that ffmpeg/libass burns in on export (editor.render). The web
preview (web/lib/captions.ts) mirrors the grouping and styling with the same fonts.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import subprocess
from pathlib import Path

from google.genai import types

import pipeline as pl

FONTS_DIR = Path(__file__).resolve().parent / "fonts"

# id, label, file, ASS family name, bold flag (libass matches family + bold)
FONTS = [
    ("poppins-black", "Poppins Black", "Poppins-Black.ttf", "Poppins Black", False),
    ("poppins-extrabold", "Poppins ExtraBold", "Poppins-ExtraBold.ttf", "Poppins ExtraBold", False),
    ("poppins-semibold", "Poppins SemiBold", "Poppins-SemiBold.ttf", "Poppins SemiBold", False),
    ("kanit-bold", "Kanit Bold", "Kanit-Bold.ttf", "Kanit", True),
    ("anton", "Anton", "Anton-Regular.ttf", "Anton", False),
    ("bebas", "Bebas Neue", "BebasNeue-Regular.ttf", "Bebas Neue", False),
    ("archivo-black", "Archivo Black", "ArchivoBlack-Regular.ttf", "Archivo Black", False),
    ("luckiest-guy", "Luckiest Guy", "LuckiestGuy-Regular.ttf", "Luckiest Guy", False),
    ("permanent-marker", "Permanent Marker", "PermanentMarker-Regular.ttf", "Permanent Marker", False),
    ("dm-serif", "DM Serif Display", "DMSerifDisplay-Regular.ttf", "DM Serif Display", False),
]
FONT_IDS = [f[0] for f in FONTS]


def _em_scale(path: Path) -> float:
    """libass sizes text so ascent+descent = the font size; browsers size the em square.
    Multiply a size by this to get the CSS font-size that looks the same."""
    d = path.read_bytes()
    tables = {}
    for i in range(struct.unpack(">H", d[4:6])[0]):
        tag, _, off, _ = struct.unpack(">4sIII", d[12 + 16 * i:28 + 16 * i])
        tables[tag] = off
    upem = struct.unpack(">H", d[tables[b"head"] + 18:tables[b"head"] + 20])[0]
    os2 = tables.get(b"OS/2")
    asc, desc = struct.unpack(">HH", d[os2 + 74:os2 + 78]) if os2 else (0, 0)
    if not asc:
        hhea = tables[b"hhea"]
        asc, desc = struct.unpack(">hh", d[hhea + 4:hhea + 8])
        desc = -desc
    return upem / (asc + desc)


def fonts_view() -> list[dict]:
    return [{"id": i, "label": label, "file": f, "em_scale": round(_em_scale(FONTS_DIR / f), 4)}
            for i, label, f, _, _ in FONTS if (FONTS_DIR / f).exists()]


ANIMATIONS = {
    "none": "Static",
    "fade": "Fade in and out",
    "pop": "Pop in",
    "highlight": "Highlight the spoken word",
    "highlight_pop": "Highlight and enlarge the spoken word",
    "word_by_word": "Reveal word by word",
}

STYLE_DEFAULTS = {
    "font": "poppins-extrabold",
    "size": 6.0,              # % of the video height
    "uppercase": False,
    "color": "#FFFFFF",
    "highlight": "#FFE14D",   # the spoken word, for highlight animations
    "outline_color": "#000000",
    "outline": 10,            # % of the font size
    "shadow": 0,              # % of the font size
    "box": False,             # a solid box behind the text instead of an outline
    "box_color": "#000000",
    "box_opacity": 0.65,
    "position": 70,           # vertical centre, % from the top
    "words": 3,               # most words per caption
    "lines": 1,               # 1 or 2 lines per caption
    "animation": "pop",
}

PRESETS = [
    {"id": "bold-pop", "name": "Bold pop", "style": {
        "font": "poppins-black", "size": 6.5, "uppercase": True, "highlight": "#FFE14D",
        "outline": 14, "words": 3, "animation": "highlight_pop", "position": 68}},
    {"id": "clean", "name": "Clean", "style": {
        "font": "poppins-semibold", "size": 5.0, "outline": 8, "words": 4, "animation": "fade",
        "position": 74}},
    {"id": "boxed", "name": "Boxed", "style": {
        "font": "poppins-semibold", "size": 4.6, "box": True, "box_opacity": 0.75, "outline": 0,
        "words": 6, "lines": 2, "animation": "none", "position": 76}},
    {"id": "one-word", "name": "One word", "style": {
        "font": "anton", "size": 9.0, "uppercase": True, "outline": 10, "words": 1,
        "animation": "pop", "position": 55}},
    {"id": "karaoke", "name": "Karaoke", "style": {
        "font": "kanit-bold", "size": 5.8, "highlight": "#39E75F", "outline": 12, "words": 4,
        "animation": "highlight", "position": 72}},
    {"id": "comic", "name": "Comic", "style": {
        "font": "luckiest-guy", "size": 6.2, "color": "#FFFFFF", "highlight": "#FF4FA3",
        "outline": 16, "shadow": 8, "words": 2, "animation": "highlight_pop", "position": 66}},
    {"id": "reveal", "name": "Word by word", "style": {
        "font": "archivo-black", "size": 5.4, "outline": 12, "words": 5, "lines": 2,
        "animation": "word_by_word", "position": 72}},
    {"id": "handwritten", "name": "Handwritten", "style": {
        "font": "permanent-marker", "size": 5.6, "outline": 0, "shadow": 10, "words": 4,
        "animation": "fade", "position": 74}},
]


def clean_style(style: dict | None) -> dict:
    s = {**STYLE_DEFAULTS, **{k: v for k, v in (style or {}).items() if k in STYLE_DEFAULTS}}
    if s["font"] not in FONT_IDS:
        s["font"] = STYLE_DEFAULTS["font"]
    if s["animation"] not in ANIMATIONS:
        s["animation"] = STYLE_DEFAULTS["animation"]
    for k in ("color", "highlight", "outline_color", "box_color"):
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(s[k])):
            s[k] = STYLE_DEFAULTS[k]
    clamp = {"size": (2.0, 14.0), "outline": (0, 30), "shadow": (0, 30), "box_opacity": (0.0, 1.0),
             "position": (8, 92), "words": (1, 8), "lines": (1, 2)}
    for k, (lo, hi) in clamp.items():
        s[k] = type(STYLE_DEFAULTS[k])(min(hi, max(lo, float(s[k]))))
    s["uppercase"], s["box"] = bool(s["uppercase"]), bool(s["box"])
    return s


# ---------------------------------------------------------------- words and timing

def script_key(plan: dict) -> str:
    lines = [sg.get("lines", []) for sg in plan.get("segments", [])]
    return hashlib.sha1(json.dumps(lines).encode()).hexdigest()[:10]


def _weight(word: str) -> float:
    w = len(re.sub(r"\W", "", word)) + 2.0
    if word.endswith((".", "!", "?")):
        w += 4
    elif word.endswith((",", ";", ":", "—", "-")):
        w += 2
    return w


def estimate_words(plan: dict, duration: float) -> list[dict]:
    """Script words spread over each segment's window by length (a pause after punctuation)."""
    segs = plan["segments"]
    planned = sum(sg["seconds"] for sg in segs) or 1
    scale = (duration or planned) / planned
    out, t0 = [], 0.0
    for i, sg in enumerate(segs):
        win = sg["seconds"] * scale
        a, b = t0 + min(0.3, win * 0.05), t0 + win - min(0.4, win * 0.05)
        words = [(w, j == len(ln.split()) - 1) for ln in sg.get("lines", []) for j, w in enumerate(ln.split())]
        total = sum(_weight(w) for w, _ in words) or 1
        t = a
        for w, line_end in words:
            d = (b - a) * _weight(w) / total
            speak = d * (0.75 if w.endswith((".", "!", "?", ",")) else 0.92)
            out.append({"text": w, "start": round(t, 2), "end": round(t + speak, 2), "seg": i, "br": line_end})
            t += d
        t0 += win
    return out


def fix_times(words: list[dict], duration: float) -> list[dict]:
    """Monotonic, inside the video, no overlaps, nothing shorter than 80 ms."""
    n = len(words)
    good = [i for i, w in enumerate(words)
            if w.get("start") is not None and w["start"] >= 0 and w.get("end") is not None and w["end"] > w["start"]]
    last = -1.0
    for i in list(good):                      # drop times that go backwards
        if words[i]["start"] < last:
            good.remove(i)
        else:
            last = words[i]["start"]
    for i in range(n):                        # interpolate the rest between known neighbours
        if i in good:
            continue
        prev = max((g for g in good if g < i), default=None)
        nxt = min((g for g in good if g > i), default=None)
        lo = words[prev]["end"] if prev is not None else 0.0
        hi = words[nxt]["start"] if nxt is not None else duration
        k0 = prev if prev is not None else -1
        k1 = nxt if nxt is not None else n
        span = (hi - lo) / (k1 - k0)
        words[i]["start"] = lo + span * (i - k0 - 1)
        words[i]["end"] = lo + span * (i - k0)
    for i, w in enumerate(words):
        w["start"] = round(min(max(0.0, w["start"]), duration), 2)
        w["end"] = round(min(max(w["start"] + 0.08, w["end"]), duration), 2)
        if i + 1 < n and w["end"] > words[i + 1]["start"] >= w["start"]:
            w["end"] = words[i + 1]["start"]
    return words


ALIGN_SYSTEM = """You time a transcript against audio. You get the audio and the exact words that
were meant to be spoken, numbered. For every number, return when that word starts and ends in the
audio, in seconds with two decimals. Never change, add, merge or split words: return exactly one
entry per number. If a word is not spoken, return -1 for its start and end.
Separately, list places where the speaker said something different from the words (a skipped,
swapped or added word): when, what the words say, and what was heard."""

ALIGN_SCHEMA = {
    "type": "object", "required": ["words", "differences"],
    "properties": {
        "words": {"type": "array", "items": {"type": "object", "required": ["i", "start", "end"], "properties": {
            "i": {"type": "integer"}, "start": {"type": "number"}, "end": {"type": "number"}}}},
        "differences": {"type": "array", "items": {"type": "object", "required": ["at", "expected", "heard"],
                                                   "properties": {"at": {"type": "number"},
                                                                  "expected": {"type": "string"},
                                                                  "heard": {"type": "string"}}}},
    },
}


def extract_audio(video: Path, out: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
                    "-b:a", "48k", str(out)], check=True)
    return out


def align(client, s: pl.Settings, video: Path, words: list[dict], duration: float) -> tuple[list[dict], list[dict], dict]:
    """Times for the given words from the audio. Returns (words with new times, differences, usage).
    The text of every word is kept exactly; only start/end come from the model."""
    audio = extract_audio(video, video.with_name("captions_audio.mp3"))
    numbered = "\n".join(f"{i}: {w['text']}" for i, w in enumerate(words))
    contents = [types.Part.from_bytes(data=audio.read_bytes(), mime_type="audio/mp3"),
                f"The audio is {duration:.2f} seconds long.\nWORDS:\n{numbered}"]
    resp = pl._with_retry(lambda: client.models.generate_content(
        model=s.planner_model, contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=ALIGN_SYSTEM, response_mime_type="application/json",
            response_json_schema=ALIGN_SCHEMA,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))), s, "caption sync")
    audio.unlink(missing_ok=True)
    got = json.loads(resp.text)
    times = {int(x["i"]): (x["start"], x["end"]) for x in got.get("words", []) if isinstance(x.get("i"), int)}
    out = []
    for i, w in enumerate(words):
        st, en = times.get(i, (-1, -1))
        out.append({**w, "start": st if st is not None and st >= 0 else None,
                    "end": en if en is not None and en >= 0 else None})
    diffs = [{"at": round(float(d["at"]), 2), "expected": str(d["expected"]), "heard": str(d["heard"])}
             for d in got.get("differences", [])][:20]
    return fix_times(out, duration), diffs, pl._usage_gc(resp)


# ---------------------------------------------------------------- captions

def chunk(words: list[dict], style: dict) -> list[dict]:
    """Words grouped into captions: at most N words, a new one after a sentence, at the end of
    a script line, or after a pause. Keep in sync with web/lib/captions.ts."""
    n = int(style["words"])
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(i)
        nxt = words[i + 1] if i + 1 < len(words) else None
        end_here = (len(cur) >= n or nxt is None or w.get("br")
                    or w["text"].endswith((".", "!", "?"))
                    or (n >= 3 and w["text"].endswith(",")))
        if nxt is not None and nxt["start"] - w["end"] > 0.6:
            end_here = True
        if end_here:
            out.append(cur)
            cur = []
    chunks = []
    for k, idx in enumerate(out):
        start, end = words[idx[0]]["start"], words[idx[-1]]["end"]
        nxt_start = words[out[k + 1][0]]["start"] if k + 1 < len(out) else None
        if nxt_start is not None and nxt_start - end < 0.35:
            end = nxt_start                   # no flicker between close captions
        chunks.append({"start": start, "end": max(end, start + 0.25), "words": idx})
    return chunks


def _ass_color(hex_: str, alpha: float = 1.0) -> str:
    r, g, b = hex_[1:3], hex_[3:5], hex_[5:7]
    a = round((1 - alpha) * 255)
    return f"&H{a:02X}{b}{g}{r}".upper()


def _ts(t: float) -> str:
    t = max(0.0, t)
    cs = round(t * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _esc(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")")


def ass(words: list[dict], style: dict, width: int, height: int, start: float = 0.0,
        end: float | None = None) -> str:
    """An ASS subtitle file for a video of width x height, for the part [start, end] of it."""
    st = clean_style(style)
    font = next(f for f in FONTS if f[0] == st["font"])
    size = st["size"] / 100 * height
    outline = size * st["outline"] / 100
    shadow = size * st["shadow"] / 100
    if st["box"]:
        border, outline_col, back_col, bord = 3, _ass_color(st["box_color"], st["box_opacity"]), \
            _ass_color(st["box_color"], st["box_opacity"]), max(size * 0.18, 4)
    else:
        border, outline_col, back_col, bord = 1, _ass_color(st["outline_color"]), _ass_color("#000000", 0.6), outline
    base, hl = _ass_color(st["color"]), _ass_color(st["highlight"])
    x, y = width / 2, st["position"] / 100 * height
    head = "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{font[3]},{size:.1f},{base},{base},{outline_col},{back_col},{-1 if font[4] else 0},0,0,0,"
        f"100,100,0,0,{border},{bord:.1f},{shadow:.1f},5,{int(width * 0.06)},{int(width * 0.06)},0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"])
    stop = end if end is not None else float("inf")

    def word_text(i: int) -> str:
        t = words[i]["text"]
        return _esc(t.upper() if st["uppercase"] else t)

    def join(idx: list[int], fmt) -> str:
        parts = [fmt(k, i) for k, i in enumerate(idx)]
        if st["lines"] == 2 and len(idx) >= 4:
            mid = (len(parts) + 1) // 2
            return " ".join(parts[:mid]) + "\\N" + " ".join(parts[mid:])
        return " ".join(parts)

    events = []

    def add(a: float, b: float, tags: str, text: str):
        a, b = max(a, start), min(b, stop)
        if b - a < 0.04:
            return
        events.append(f"Dialogue: 0,{_ts(a - start)},{_ts(b - start)},Cap,,0,0,0,,{{\\pos({x:.0f},{y:.0f}){tags}}}{text}")

    anim = st["animation"]
    for c in chunk(words, st):
        idx = c["words"]
        if anim in ("highlight", "highlight_pop", "word_by_word"):
            for k, i in enumerate(idx):
                a = c["start"] if k == 0 else words[i]["start"]
                b = words[idx[k + 1]]["start"] if k + 1 < len(idx) else c["end"]

                def fmt(kk, ii, k=k):
                    t = word_text(ii)
                    if anim == "word_by_word":
                        return t if kk <= k else f"{{\\alpha&HFF&}}{t}{{\\alpha&H00&}}"
                    if kk != k:
                        return t
                    pop = "\\fscx115\\fscy115" if anim == "highlight_pop" else ""
                    return f"{{\\c{hl}{pop}}}{t}{{\\c{base}\\fscx100\\fscy100}}"
                add(a, b, "", join(idx, fmt))
        else:
            tags = {"none": "", "fade": "\\fad(120,120)",
                    "pop": "\\fscx80\\fscy80\\t(0,90,\\fscx108\\fscy108)\\t(90,160,\\fscx100\\fscy100)"}[anim]
            add(c["start"], c["end"], tags, join(idx, lambda k, i: word_text(i)))
    return head + "\n" + "\n".join(events) + "\n"


def filter_path(p: Path) -> str:
    """A path as an ffmpeg filter argument (drive colons escaped, quoted)."""
    return "'" + p.resolve().as_posix().replace(":", "\\:") + "'"


def subtitles_filter(ass_file: Path) -> str:
    return f"subtitles=filename={filter_path(ass_file)}:fontsdir={filter_path(FONTS_DIR)}"


# ---------------------------------------------------------------- per-video state

def state(plan: dict, duration: float | None) -> dict:
    """The captions of a video: made from the script on first use, rebuilt (estimated) when the
    script changes; style and edits are kept otherwise."""
    cur = plan.get("captions") or {}
    style = clean_style(cur.get("style") or PRESETS[0]["style"])
    key = script_key(plan)
    if cur.get("script_key") == key and cur.get("words"):
        words, synced, diffs = cur["words"], cur.get("synced", "estimate"), cur.get("differences", [])
    else:
        words = estimate_words(plan, duration or sum(sg["seconds"] for sg in plan["segments"]))
        synced, diffs = "estimate", []
    return {"enabled": bool(cur.get("enabled", False)), "style": style, "words": words,
            "synced": synced, "differences": diffs, "script_key": key,
            "synced_at": cur.get("synced_at") if synced == "voice" else None}
