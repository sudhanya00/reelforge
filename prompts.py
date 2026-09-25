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
    medium = f"Medium: {dot(st['medium'])} " if st.get("medium") else ""
    return (f"{medium}Style: {dot(st['look'])} Colour grade: {dot(st['color_grade'])} "
            f"Lens: {dot(st['lens'])} Avoid: {dot(st['avoid'])}")


def dialogue_line(plan: dict, scene: dict) -> str:
    dialogue = scene.get("dialogue") or []
    if not dialogue:
        return "No dialogue."
    voices = {c["name"]: c["voice"] for c in plan["characters"]}
    return "Dialogue: " + " ".join(
        f'{d["speaker"]} ({voices.get(d["speaker"], "natural voice")}) says: "{d["line"]}"'
        for d in dialogue)


def _t(x: float) -> str:
    return f"{x:g}"


def shots_of(scene: dict) -> list[list[dict]]:
    """Beats grouped into shots (a new shot starts at each beat with cut=true)."""
    shots: list[list[dict]] = []
    for b in scene.get("beats") or []:
        if not shots or (scene.get("multi_shot") and b.get("cut")):
            shots.append([])
        shots[-1].append(b)
    return shots


def beat_line(b: dict) -> str:
    hold = " (a deliberate hold)" if b.get("hold") else ""
    return f"{_t(b['t_start'])}-{_t(b['t_end'])}s: {dot(b['action'])}{hold} Camera: {dot(b['camera'])}"


def scene_lines(plan: dict, scene: dict, duration_s: int | None = None) -> list[str]:
    """The provider-independent description of one shot (or, for multi-shot scenes, of the
    shots inside one clip). Planner v2 scenes are compiled from their timed beats."""
    if scene.get("beats"):
        return _beat_lines(plan, scene, duration_s)
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


def _beat_lines(plan: dict, scene: dict, duration_s: int | None) -> list[str]:
    d = duration_s or scene["duration_s"]
    shots = shots_of(scene)
    lines = [f"Opening framing: {dot(scene['shot'])}"]
    if len(shots) > 1:
        for i, sh in enumerate(shots, start=1):
            lines.append(f"Shot {i} ({_t(sh[0]['t_start'])}-{_t(sh[-1]['t_end'])}s):")
            lines += [f"  {beat_line(b)}" for b in sh]
    else:
        lines.append("Timeline:")
        lines += [f"  {beat_line(b)}" for b in shots[0]]
    motion = plan["style"].get("motion")
    lines += [
        f"Lighting: {dot(scene['lighting'])}",
        dialogue_line(plan, scene),
        f"Sound design: {dot(scene['audio'])} No background music unless described.",
        style_line(plan),
    ]
    if motion:
        lines.append(f"Motion: {dot(motion)}")
    lines.append("The action is already underway in the first frame; follow the timeline closely and "
                 "end on the last beat.")
    if len(shots) > 1:
        lines.append(f"Duration {d} seconds, cut into {len(shots)} shots exactly as listed.")
    else:
        lines.append(f"Duration {d} seconds. Single continuous shot, no scene cuts.")
    return lines


def edit_instruction(instruction: str) -> str:
    """Edits are short and end with 'Keep everything else the same.'"""
    text = instruction.strip()
    if "keep everything else" not in text.lower():
        if not text.endswith((".", "!", "?")):
            text += "."
        text += " Keep everything else the same."
    return text
