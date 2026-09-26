"""A small, non-destructive video editor: trim, colour and audio, rendered with ffmpeg.

The original (final.mp4) is never touched; an export writes edited.mp4 next to it and the
settings are kept in the plan under "edit", so they can be changed and re-exported.

Colour is one 3x3 RGB matrix (saturation, then brightness, then warmth) followed by RGB
contrast around mid-grey. The web preview applies the same matrix as an SVG feColorMatrix
(web/lib/edit.ts), so what you see is what you export.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

DEFAULTS = {
    "start": 0.0,           # seconds cut from the start
    "end": None,            # keep up to here (None: the end)
    "brightness": 1.0,      # multiplier
    "contrast": 1.0,        # around mid-grey
    "saturation": 1.0,
    "warmth": 0.0,          # -1 cool ... +1 warm
    "volume": 1.0,          # multiplier, 0-2
    "denoise": False,       # reduce background hiss / room noise
    "normalize": False,     # even out loudness for social (-14 LUFS)
    "mute": False,
}
LIMITS = {"brightness": (0.5, 1.5), "contrast": (0.5, 1.5), "saturation": (0.0, 2.0),
          "warmth": (-1.0, 1.0), "volume": (0.0, 2.0)}


def clean(params: dict, duration: float | None = None) -> dict:
    """Defaults for what's missing, numbers clamped, a trim that makes sense."""
    e = {**DEFAULTS, **{k: v for k, v in (params or {}).items() if k in DEFAULTS}}
    for k, (lo, hi) in LIMITS.items():
        e[k] = min(hi, max(lo, float(e[k])))
    for k in ("denoise", "normalize", "mute"):
        e[k] = bool(e[k])
    e["start"] = max(0.0, float(e["start"] or 0))
    if e["end"] is not None:
        e["end"] = float(e["end"])
        if duration is not None and e["end"] >= duration - 0.05:
            e["end"] = None
    if duration is not None:
        e["start"] = min(e["start"], max(0.0, duration - 0.5))
    if e["end"] is not None and e["end"] - e["start"] < 0.5:
        raise ValueError("Keep at least half a second.")
    return e


def is_identity(e: dict) -> bool:
    return all(e[k] == DEFAULTS[k] for k in DEFAULTS)


def color_matrix(e: dict) -> list[list[float]]:
    """Warmth x brightness x saturation (W3C saturate), as rows of an RGB matrix."""
    s, b, w = e["saturation"], e["brightness"], e["warmth"]
    sat = [[0.213 + 0.787 * s, 0.715 - 0.715 * s, 0.072 - 0.072 * s],
           [0.213 - 0.213 * s, 0.715 + 0.285 * s, 0.072 - 0.072 * s],
           [0.213 - 0.213 * s, 0.715 - 0.715 * s, 0.072 + 0.928 * s]]
    warm = [1 + 0.12 * w, 1 + 0.02 * w, 1 - 0.12 * w]
    return [[warm[i] * b * sat[i][j] for j in range(3)] for i in range(3)]


def video_filter(e: dict) -> str | None:
    parts = []
    if (e["saturation"], e["brightness"], e["warmth"]) != (1.0, 1.0, 0.0):
        m = color_matrix(e)
        names = [["rr", "rg", "rb"], ["gr", "gg", "gb"], ["br", "bg", "bb"]]
        parts.append("colorchannelmixer=" + ":".join(
            f"{names[i][j]}={m[i][j]:.5f}" for i in range(3) for j in range(3)))
    if e["contrast"] != 1.0:
        c = e["contrast"]
        f = f"clip((val-128)*{c:.4f}+128\\,0\\,255)"
        parts.append(f"lutrgb=r='{f}':g='{f}':b='{f}'")
    return ",".join(parts) or None


def audio_filter(e: dict) -> str | None:
    parts = []
    if e["denoise"]:
        parts.append("afftdn=nf=-25")
    if e["volume"] != 1.0:
        parts.append(f"volume={e['volume']:.3f}")
    if e["normalize"]:
        parts.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    return ",".join(parts) or None


def command(src: Path, out: Path, e: dict) -> list[str]:
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if e["start"]:
        cmd += ["-ss", f"{e['start']:.3f}"]
    cmd += ["-i", str(src)]
    if e["end"] is not None:
        cmd += ["-t", f"{e['end'] - e['start']:.3f}"]
    vf, af = video_filter(e), audio_filter(e)
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p"]
    if e["mute"]:
        cmd += ["-an"]
    else:
        if af:
            cmd += ["-af", af]
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    return cmd + ["-movflags", "+faststart", str(out)]


def render(src: Path, out: Path, params: dict, duration: float | None = None) -> dict:
    """Export `src` with the edit to `out`. Returns the cleaned edit that was applied."""
    e = clean(params, duration)
    tmp = out.with_name(out.stem + ".part.mp4")
    r = subprocess.run(command(src, tmp, e), capture_output=True, text=True)
    if r.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg couldn't export the edit: {r.stderr.strip()[-300:]}")
    tmp.replace(out)
    return e
