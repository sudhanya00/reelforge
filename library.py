"""Character library: characters saved from films (and influencers), reusable in any project.

  library/characters/<id>/character.json   name, appearance, costume, voice, where it came from
  library/characters/<id>/sheet.png        its reference sheet

A cast character is fixed: the planner must use it as saved, and its sheet is copied into the
film instead of being painted again (same look everywhere, and no image cost).
"""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

FIELDS = ("name", "appearance", "costume", "voice")


class Library:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.chars = self.root / "characters"
        self.chars.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- read

    def characters(self) -> list[dict]:
        out = []
        for d in sorted(self.chars.iterdir()):
            f = d / "character.json"
            if f.exists():
                out.append(self._load(d))
        return sorted(out, key=lambda c: c.get("saved", 0), reverse=True)

    def get(self, cid: str) -> dict:
        d = self._dir(cid)
        if not (d / "character.json").exists():
            raise KeyError(cid)
        return self._load(d)

    def _load(self, d: Path) -> dict:
        c = json.loads((d / "character.json").read_text(encoding="utf-8"))
        c["sheet_path"] = str(d / "sheet.png") if (d / "sheet.png").exists() else None
        return c

    def _dir(self, cid: str) -> Path:
        if not re.fullmatch(r"[a-z0-9_]+", cid):
            raise KeyError(cid)
        return self.chars / cid

    # ---------------------------------------------------------------- write

    def save_from_project(self, project_root: Path, plan: dict, char_id: str) -> dict:
        """Save a film's character (with its painted sheet). Saving the same character from the
        same film again updates it rather than making a copy."""
        c = next((x for x in plan.get("characters", []) if x["id"] == char_id), None)
        if c is None:
            raise KeyError(char_id)
        sheet = Path(project_root) / "assets" / f"{char_id}.png"
        if not sheet.exists():
            raise FileNotFoundError(f"{char_id} has no reference sheet yet; paint it first.")
        source = {"project": Path(project_root).name, "id": char_id}
        existing = next((x for x in self.characters() if x.get("source") == source), None)
        cid = existing["id"] if existing else self._free_id(char_id)
        d = self._dir(cid)
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sheet, d / "sheet.png")
        data = {"id": cid, **{k: c.get(k, "") for k in FIELDS}, "source": source,
                "style": plan.get("style", {}).get("look", ""), "saved": time.time()}
        (d / "character.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return self._load(d)

    def delete(self, cid: str) -> None:
        d = self._dir(cid)
        if not d.exists():
            raise KeyError(cid)
        shutil.rmtree(d)

    def _free_id(self, base: str) -> str:
        base = re.sub(r"[^a-z0-9_]+", "_", base.lower()).strip("_") or "char"
        if not base.startswith("char_"):
            base = f"char_{base}"
        cid, n = base, 2
        while (self.chars / cid).exists():
            cid, n = f"{base}_{n}", n + 1
        return cid


def cast_brief(cast: list[dict]) -> str:
    """The cast as planner-readable text."""
    return "\n".join(f"- id: {c['id']} | name: {c['name']} | appearance: {c['appearance']} | "
                     f"costume: {c['costume']} | voice: {c['voice']}" for c in cast)
