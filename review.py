"""Instruments for judging takes (R&D): a free motion meter and an AI reviewer.

  motion_profile(video)   ffmpeg frame differences -> frozen stretches ("dead time") and cuts
  review_take(...)        Gemini watches the take beside its brief and references and returns
                          a scorecard, timestamped issues, a verdict and a suggested fix

Both are stored on the take (take_NN.json -> "motion", "review") so experiments can compare
prompt/planner versions on numbers instead of taste.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from google.genai import types

import pipeline as pl
from prompts import dialogue_line, dot, style_line

# ---------------------------------------------------------------- motion meter

W, H, FPS = 64, 36, 8
STILL_BELOW = 1.2         # mean abs frame difference (0-255) under which a moment reads as frozen
CUT_ABOVE = 28.0          # a jump this big between two frames is a cut
MIN_DEAD_S = 1.0          # frozen stretches shorter than this don't count


def motion_profile(video: Path) -> dict | None:
    """Per-frame change at 8 fps on a 64x36 greyscale copy. No API calls, milliseconds of CPU.
    Returns {fps, diffs, dead: [[start, end]], dead_s, cuts: [t], mean} or None without ffmpeg."""
    if not shutil.which("ffmpeg"):
        return None
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video),
                        "-vf", f"fps={FPS},scale={W}:{H}:flags=area,format=gray",
                        "-f", "rawvideo", "-"], capture_output=True, check=True)
    px = W * H
    frames = [r.stdout[i:i + px] for i in range(0, len(r.stdout) - px + 1, px)]
    diffs = [sum(abs(a - b) for a, b in zip(f0, f1)) / px for f0, f1 in zip(frames, frames[1:])]
    dead, start = [], None
    for i, d in enumerate(diffs + [99.0]):            # sentinel closes a trailing stretch
        if d < STILL_BELOW and start is None:
            start = i
        elif d >= STILL_BELOW and start is not None:
            if (i - start) / FPS >= MIN_DEAD_S:
                dead.append([round(start / FPS, 2), round(i / FPS, 2)])
            start = None
    cuts = [round((i + 1) / FPS, 2) for i, d in enumerate(diffs) if d >= CUT_ABOVE]
    return {"fps": FPS, "diffs": [round(d, 2) for d in diffs], "dead": dead,
            "dead_s": round(sum(e - s for s, e in dead), 2), "cuts": cuts,
            "mean": round(sum(diffs) / len(diffs), 2) if diffs else 0.0}


# ---------------------------------------------------------------- AI reviewer

CRITERIA = ("identity", "costume", "environment", "action", "camera", "pacing", "physics",
            "artifacts", "style", "continuity")

_score = {"type": "object", "required": ["score", "note"], "properties": {
    "score": {"type": "integer", "minimum": 1, "maximum": 5, "description": "5 = as briefed, 1 = unusable"},
    "note": {"type": "string"}}}

REVIEW_SCHEMA = {
    "type": "object",
    "required": ["summary", "beats_observed", "scores", "issues", "dead_time_s", "verdict",
                 "fix_instruction", "prompt_advice"],
    "properties": {
        "summary": {"type": "string", "description": "two sentences: what the shot is and how well it lands"},
        "beats_observed": {"type": "array", "items": {
            "type": "object", "required": ["t_start", "t_end", "what"],
            "properties": {"t_start": {"type": "number"}, "t_end": {"type": "number"}, "what": {"type": "string"}}}},
        "scores": {"type": "object", "required": list(CRITERIA),
                   "properties": {c: _score for c in CRITERIA}},
        "issues": {"type": "array", "items": {
            "type": "object", "required": ["t_start", "t_end", "category", "severity", "description"],
            "properties": {
                "t_start": {"type": "number"}, "t_end": {"type": "number"},
                "category": {"type": "string", "enum": list(CRITERIA)},
                "severity": {"type": "string", "enum": ["minor", "major", "fatal"]},
                "description": {"type": "string"}}}},
        "dead_time_s": {"type": "number", "description": "seconds where nothing meaningful happens"},
        "verdict": {"type": "string", "enum": ["keep", "fix", "reshoot"]},
        "fix_instruction": {"type": "string", "description": "one short edit instruction for the video model, or empty"},
        "prompt_advice": {"type": "string", "description": "how to change the prompt if reshooting"},
    },
}

REVIEW_SYSTEM = """You are a demanding film editor and VFX supervisor reviewing one AI-generated
shot against its brief. You watch the clip frame by frame and judge only what is on screen.

Score each criterion 1-5 (5 = exactly as briefed, 3 = usable with flaws, 1 = unusable):
- identity: faces and hair match the character reference sheets.
- costume: clothing, colours and props match the references.
- environment: the location matches its plate; lighting and time of day as briefed.
- action: the briefed action happens, in order, completely.
- camera: the briefed framing and movement; moves are smooth and motivated, no aimless
  drifting, no unrequested cuts.
- pacing: something meaningful happens throughout; penalise stalling, characters idling,
  actions stretched to fill time, and rushed beats.
- physics: bodies, vehicles and objects move plausibly; penalise sudden flips of direction,
  morphing, teleporting, limbs through objects, impossible motion.
- artifacts: flicker, warping, melting details, garbled text, duplicated body parts.
- style: matches the style block (look, grade, lens) consistently.
- continuity: if a previous frame is given, the shot starts consistently with it; else 5.

List every issue with its time range and severity (fatal = the take cannot be used).
Verdict: keep (no major issues), fix (one or two issues a short edit could fix), reshoot.
fix_instruction: one short instruction a video editing model could apply to this take, in the
imperative, describing only the change (e.g. "Make the rider keep facing forward through
the whole shot."). Empty if the verdict is keep or reshoot.
prompt_advice: concrete changes to the shot's prompt that would avoid the issues next time.
Be specific and terse. Timestamps are seconds from the start of the clip."""


def _brief(plan: dict, scene: dict, take_meta: dict) -> str:
    lines = [
        f"SCENE {scene['id']} of '{plan['title']}' - {take_meta.get('duration_s') or scene['duration_s']}s,"
        f" {plan.get('orientation', '16:9')}, continuity: {scene.get('continuity', 'cut')}",
        f"Shot: {dot(scene['shot'])}",
        f"Action: {dot(scene['action'])}",
        f"Camera: {dot(scene['camera'])}",
        f"Lighting: {dot(scene['lighting'])}",
        dialogue_line(plan, scene),
        f"Sound: {dot(scene['audio'])}",
        style_line(plan),
    ]
    if take_meta.get("edit"):
        lines.append(f"This take is an edit of an earlier take with the instruction: {take_meta['edit']}")
    return "\n".join(lines)


def review_take(client, s: pl.Settings, proj: pl.Project, scene_id: str, take: Path,
                fps: int = 4) -> dict:
    """Have the planner model review a take. Stores the review on the take and logs its cost."""
    plan = proj.load_plan()
    scene = next(sc for sc in plan["scenes"] if sc["id"] == scene_id)
    meta_path = take.with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    idx = pl._lookup(plan)

    motion = motion_profile(take)
    contents: list = [f"BRIEF\n{_brief(plan, scene, meta)}"]
    for i, rid in enumerate(meta.get("refs", []), start=1):
        if rid in idx and proj.asset_path(rid).exists():
            kind, item = idx[rid]
            contents += [f"Reference {i}: {kind[:-1]} '{item['name']}' ({rid})",
                         types.Part.from_bytes(data=proj.asset_path(rid).read_bytes(), mime_type="image/png")]
    prev = pl.previous_take(plan, proj, scene)
    first = proj.root / "frames" / f"{scene_id}_first.png"
    if prev and first.exists():
        contents += ["The shot was meant to start from this frame (last frame of the previous shot):",
                     types.Part.from_bytes(data=first.read_bytes(), mime_type="image/png")]
    if motion:
        contents.append(f"Measured motion: frozen stretches {motion['dead'] or 'none'}; "
                        f"hard cuts at {motion['cuts'] or 'none'} (seconds).")
    contents += ["THE TAKE",
                 types.Part(inline_data=types.Blob(data=take.read_bytes(), mime_type="video/mp4"),
                            video_metadata=types.VideoMetadata(fps=fps))]

    resp = pl._with_retry(lambda: client.models.generate_content(
        model=s.planner_model, contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=REVIEW_SYSTEM,
            response_mime_type="application/json",
            response_json_schema=REVIEW_SCHEMA,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )), s, f"review {scene_id}", proj)
    review = json.loads(resp.text)
    usage = pl._usage_gc(resp)
    cost = pl.call_cost(s.planner_model, usage)
    review["model"], review["fps"], review["cost_usd"] = s.planner_model, fps, cost
    review["overall"] = round(sum(v["score"] for v in review["scores"].values()) / len(review["scores"]), 2)

    meta["review"], meta["motion"] = review, motion
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    proj.log(kind="review", scene=scene_id, take=take.name, model=s.planner_model, usage=usage,
             cost_usd=cost, verdict=review["verdict"], overall=review["overall"])
    return review
