"""Products a creator wears or holds in videos: a top from a photo, a specific lipstick.

  library/products/<id>/product.json   name, brand, kind, description, talking points
  library/products/<id>/photos/NN.png  the user's photos (cleaned: see uploads.py)
  library/products/<id>/packshot.png   a clean studio shot painted from them (the main reference)

The image model turns the photos into a packshot; the planner reads them into a description
(colours, materials, printed text). Videos then put the product in the opening frame and pass
it to Omni as a reference, so the exact item stays on screen through the take.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

import pipeline as pl

# kind -> how it appears by default
KINDS = {"clothing": "wear", "accessory": "wear", "beauty": "hold", "tech": "hold", "food": "hold",
         "object": "hold"}
USES = ("wear", "hold")
FIELDS = ("name", "brand", "kind", "description", "notes")

DESCRIBE_SYSTEM = """You describe a product from photos so an image and video model can reproduce it
exactly. Be concrete and visual; never guess what isn't visible.
- name: what it is, short (e.g. "satin lipstick", "cropped cable-knit top").
- brand: only if printed on it, else "".
- kind: one of clothing, accessory, beauty, tech, food, object.
- description: colours (precise), materials and finish, shape and proportions, size cues, every
  printed word or logo copied exactly (in quotes), packaging details. 2-4 sentences."""

DESCRIBE_SCHEMA = {"type": "object", "required": ["name", "brand", "kind", "description"],
                   "properties": {"name": {"type": "string"}, "brand": {"type": "string"},
                                  "kind": {"type": "string", "enum": list(KINDS)},
                                  "description": {"type": "string"}}}


def packshot_prompt(p: dict) -> str:
    what = f"{p['name']}" + (f" by {p['brand']}" if p.get("brand") else "")
    return (f"A clean studio product photo of exactly the item in the reference photos: {what}. "
            f"{p.get('description', '')} Same colours, materials, proportions and details; every printed "
            f"word and logo exactly as in the photos, sharp and legible. The whole item visible and centred "
            f"on a plain light-grey background, soft even light, no hands, no people, no props, no added text.")


def ref_label(p: dict) -> str:
    """How prompts name the product."""
    return f"the {p['name']}" + (f" by {p['brand']}" if p.get("brand") else "")


class Products:
    def __init__(self, library_root: Path):
        self.root = Path(library_root) / "products"

    def dir(self, pid: str) -> Path:
        if not re.fullmatch(r"[a-z0-9_]+", pid or ""):
            raise KeyError(pid)
        return self.root / pid

    def get(self, pid: str) -> dict:
        f = self.dir(pid) / "product.json"
        if not f.exists():
            raise KeyError(pid)
        return json.loads(f.read_text(encoding="utf-8"))

    def all(self) -> list[dict]:
        if not self.root.exists():
            return []
        out = [self.get(d.name) for d in self.root.iterdir() if (d / "product.json").exists()]
        return sorted(out, key=lambda p: p.get("created", 0), reverse=True)

    def save(self, p: dict) -> None:
        (self.dir(p["id"]) / "product.json").write_text(json.dumps(p, indent=2, ensure_ascii=False), encoding="utf-8")

    def create(self, fields: dict, photos: list[Path]) -> dict:
        if not photos:
            raise ValueError("Add at least one photo of the product.")
        name = (fields.get("name") or "").strip() or "product"
        base = re.sub(r"[^a-z0-9]+", "_", f"{fields.get('brand', '')} {name}".lower()).strip("_") or "product"
        pid, n = base[:40], 2
        while self.dir(pid).exists():
            pid, n = f"{base[:36]}_{n}", n + 1
        p = {"id": pid, **{k: str(fields.get(k, "") or "").strip() for k in FIELDS}, "created": time.time()}
        p["name"] = name
        if p["kind"] not in KINDS:
            p["kind"] = "object"
        (self.dir(pid) / "photos").mkdir(parents=True)
        for i, src in enumerate(photos, start=1):
            shutil.move(str(src), self.dir(pid) / "photos" / f"{i:02d}.png")
        self.save(p)
        return p

    def update(self, pid: str, fields: dict) -> dict:
        p = self.get(pid)
        p.update({k: str(v).strip() for k, v in fields.items() if k in FIELDS and v is not None})
        if p["kind"] not in KINDS:
            p["kind"] = "object"
        self.save(p)
        return p

    def photos(self, pid: str) -> list[Path]:
        return sorted((self.dir(pid) / "photos").glob("*.png"))

    def packshot(self, pid: str) -> Path:
        return self.dir(pid) / "packshot.png"

    def refs(self, pid: str) -> list[Path]:
        """What the models see: the packshot (if painted) and the first photo."""
        shot = self.packshot(pid)
        return ([shot] if shot.exists() else []) + self.photos(pid)[:1]

    def log(self, pid: str, **entry) -> None:
        entry["ts"] = datetime.now().isoformat(timespec="seconds")
        with pl.Project._log_lock, open(self.dir(pid) / "log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def describe(client, s: pl.Settings, photos: list[Path]) -> tuple[dict, dict]:
    out, usage = pl.json_call_with_images(client, s, DESCRIBE_SYSTEM, "Describe this product.", photos[:4],
                                          DESCRIBE_SCHEMA, "describe product")
    if out.get("kind") not in KINDS:
        out["kind"] = "object"
    return out, usage


def paint_packshot(client, s: pl.Settings, lib: Products, pid: str) -> None:
    p = lib.get(pid)
    prompt = packshot_prompt(p)
    usage = pl.generate_image(client, s, prompt, lib.packshot(pid), refs=lib.photos(pid)[:4], aspect="1:1")
    lib.log(pid, kind="image", id="packshot", model=s.image_model, prompt=prompt, image_size=s.image_size,
            usage=usage, cost_usd=pl.call_cost(s.image_model, usage, s.image_size))
