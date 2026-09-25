"""Deterministic prompt text shared by the pipeline and every provider.

The planner writes content; these functions turn it into prompt text the same way every
time, so the style block and scene description never drift between clips or providers.
Providers add their own reference-image syntax around scene_lines().
"""
from __future__ import annotations


def dot(text: str) -> str:
    """Planner fields may or may not end with a period; end with exactly one."""
    return text.strip().rstrip(".") + "."


def style_line(plan: dict) -> str:
    st = plan["style"]
    return (f"Style: {dot(st['look'])} Colour grade: {dot(st['color_grade'])} "
            f"Lens: {dot(st['lens'])} Avoid: {dot(st['avoid'])}")


def dialogue_line(plan: dict, scene: dict) -> str:
    dialogue = scene.get("dialogue") or []
    if not dialogue:
        return "No dialogue."
    voices = {c["name"]: c["voice"] for c in plan["characters"]}
    return "Dialogue: " + " ".join(
        f'{d["speaker"]} ({voices.get(d["speaker"], "natural voice")}) says: "{d["line"]}"'
        for d in dialogue)


def scene_lines(plan: dict, scene: dict, duration_s: int | None = None) -> list[str]:
    """The provider-independent description of one shot."""
    return [
        f"Shot: {dot(scene['shot'])}",
        f"Action: {dot(scene['action'])}",
        f"Camera: {dot(scene['camera'])}",
        f"Lighting: {dot(scene['lighting'])}",
        dialogue_line(plan, scene),
        f"Sound design: {dot(scene['audio'])} No background music unless described.",
        style_line(plan),
        f"Duration about {duration_s or scene['duration_s']} seconds. Single continuous shot, no scene cuts.",
    ]


def edit_instruction(instruction: str) -> str:
    """Edits are short and end with 'Keep everything else the same.'"""
    text = instruction.strip()
    if "keep everything else" not in text.lower():
        if not text.endswith((".", "!", "?")):
            text += "."
        text += " Keep everything else the same."
    return text
