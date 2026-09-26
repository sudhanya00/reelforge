"""Images the user uploads (a person's photos, product photos), held until they're used.

Every upload is decoded and re-encoded as PNG: that proves it's an image, drops metadata
(EXIF, including GPS location) and caps the size the image models get.
"""
from __future__ import annotations

import io
import re
import secrets
import shutil
import time
from pathlib import Path

from PIL import Image, ImageOps

MAX_BYTES = 25 * 1024 * 1024
MAX_SIDE = 2048


class UploadError(ValueError):
    pass


def clean_png(data: bytes) -> bytes:
    if len(data) > MAX_BYTES:
        raise UploadError("That image is over 25 MB.")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:  # noqa: BLE001
        raise UploadError("That isn't an image this app can read (use JPG, PNG or WebP).")
    img = ImageOps.exif_transpose(img)                 # phone photos: apply rotation, then drop EXIF
    img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


class Uploads:
    def __init__(self, library_root: Path):
        self.dir = Path(library_root) / "uploads"

    def add(self, data: bytes) -> str:
        png = clean_png(data)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.sweep()
        token = secrets.token_hex(8)
        (self.dir / f"{token}.png").write_bytes(png)
        return token

    def path(self, token: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{16}", token or ""):
            raise KeyError(token)
        p = self.dir / f"{token}.png"
        if not p.exists():
            raise KeyError(token)
        return p

    def take(self, token: str, dest: Path) -> Path:
        """Move an upload to where it's kept."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self.path(token)), dest)
        return dest

    def sweep(self, max_age_s: int = 86400) -> None:
        """Uploads nobody used within a day are removed."""
        for p in self.dir.glob("*.png"):
            if time.time() - p.stat().st_mtime > max_age_s:
                p.unlink(missing_ok=True)
