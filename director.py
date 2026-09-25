"""Planner v2 and the director pass (R&D: see docs/RND.md).

v1 planned one action per clip, which is exactly what makes AI clips stall. v2 plans each
scene as timed beats, with pacing and a full style profile, then a second call (the
director) reviews the whole plan against known failure modes before any footage is paid
for. The director's rule: restage a risky element only when the story doesn't need it;
when it does, keep it and make it precise. Never flatten the film to avoid risk.

This module is data and text only; pipeline.py makes the calls.
"""
from __future__ import annotations

import copy
import json
import math

from styles import DEFAULT_PACING, PACING, pacing_brief, preset_brief

# ---------------------------------------------------------------- schema

_beat = {
    "type": "object", "required": ["t_start", "t_end", "action", "camera"],
    "properties": {
        "t_start": {"type": "number"},
        "t_end": {"type": "number"},
        "action": {"type": "string", "description": "what visibly changes during this beat"},
        "camera": {"type": "string", "description": "framing and any move, with its motivation"},
        "cut": {"type": "boolean", "description": "a new shot starts here (only when the scene is multi_shot)"},
        "hold": {"type": "boolean", "description": "a deliberate held moment that carries emotion"},
    },
}

PLAN_SCHEMA_V2 = {
    "type": "object",
    "required": ["title", "logline", "pacing", "style", "characters", "props", "environments", "scenes"],
    "properties": {
        "title": {"type": "string"},
        "logline": {"type": "string"},
        "pacing": {"type": "string", "enum": list(PACING)},
        "style": {
            "type": "object",
            "required": ["medium", "look", "color_grade", "lens", "motion", "camera_grammar", "sheet_look", "avoid"],
            "properties": {k: {"type": "string"} for k in
                           ("medium", "look", "color_grade", "lens", "motion", "camera_grammar", "sheet_look", "avoid")},
        },
        "characters": {"type": "array", "items": {
            "type": "object", "required": ["id", "name", "appearance", "costume", "voice"],
            "properties": {k: {"type": "string"} for k in ("id", "name", "appearance", "costume", "voice")}}},
        "props": {"type": "array", "items": {
            "type": "object", "required": ["id", "name", "description"],
            "properties": {k: {"type": "string"} for k in ("id", "name", "description")}}},
        "environments": {"type": "array", "items": {
            "type": "object", "required": ["id", "name", "description", "time_and_weather", "lighting"],
            "properties": {
                **{k: {"type": "string"} for k in ("id", "name", "description", "time_and_weather", "lighting")},
                "based_on": {"type": "string", "description": "id of the environment this is a variant of, or empty"},
            }}},
        "scenes": {"type": "array", "items": {
            "type": "object",
            "required": ["id", "duration_s", "refs", "shot", "action", "camera", "lighting", "audio",
                         "continuity", "beats", "multi_shot"],
            "properties": {
                "id": {"type": "string"},
                "duration_s": {"type": "integer", "description": "end of the last beat, rounded up"},
                "refs": {"type": "array", "items": {"type": "string"},
                         "description": "ids of ONE environment and every character and prop visible"},
                "shot": {"type": "string", "description": "opening framing"},
                "action": {"type": "string", "description": "one-line summary of the scene"},
                "camera": {"type": "string", "description": "the overall camera plan"},
                "lighting": {"type": "string"},
                "dialogue": {"type": "array", "items": {
                    "type": "object", "required": ["speaker", "line"],
                    "properties": {"speaker": {"type": "string"}, "line": {"type": "string"}}}},
                "audio": {"type": "string"},
                "continuity": {"type": "string", "enum": ["cut", "continuous"]},
                "beats": {"type": "array", "items": _beat},
                "multi_shot": {"type": "boolean"},
                "risks": {"type": "array", "items": {
                    "type": "object", "required": ["what", "handling"],
                    "properties": {"what": {"type": "string"}, "handling": {"type": "string"}}}},
            }}},
    },
}

DIRECTOR_SCHEMA = {
    "type": "object", "required": ["plan", "notes"],
    "properties": {
        "plan": PLAN_SCHEMA_V2,
        "notes": {"type": "array", "items": {
            "type": "object", "required": ["scene", "change", "reason"],
            "properties": {"scene": {"type": "string", "description": "scene id, or empty for the whole film"},
                           "change": {"type": "string"}, "reason": {"type": "string"}}}},
    },
}

# ---------------------------------------------------------------- prompts

PLANNER_V2_SYSTEM = """You are a film director and AI-video production designer. Turn the idea into a
production plan for an AI video pipeline where each scene is one generated clip of 3-10 seconds,
every character, recurring prop and location gets a reference image first, and clips are
generated separately and cut together.

Write every scene as timed BEATS. This is the heart of the plan:
- A beat is a visible change: an action, a reaction, a reveal, or a purposeful camera move.
  Follow the pacing brief for how often something changes.
- The action is already underway at 0 s: no idle lead-in, nobody waiting to start. The clip ends
  on its last meaningful beat, not on idling.
- A beat may be a deliberate hold only when the moment carries emotion; mark it hold=true.
- The scene's duration is the end of its last beat. Fit the content: don't stretch one action
  over the clip, and don't cram more than the time allows. Speech runs about 2.5 words a second.
  If a scene has little to show, make it shorter (3-4 s) rather than padding it; every beat
  keeps something moving until the clip ends.
- Show what drives every movement: wheels turning, feet pushing off, spray thrown up by tyres,
  suspension compressing, cloth pulled by wind, a body leaning into a turn. Motion without a
  visible physical cause comes out as gliding.
- For every beat, give the framing and any camera move with its motivation (e.g. "slow push from
  medium to close-up as she reads"). No unmotivated pans or drifts.
- One continuous shot per clip: multi_shot=false. Cuts inside a clip make current models redraw
  costumes and props at the cut. Get coverage from separate scenes instead.
- scene.action is a one-line summary; scene.shot the opening framing; scene.camera the overall plan.

Staging that current video models render well, without losing any story:
- Prefer staging that reads clearly: movement across the frame, clear silhouettes, one centre of
  attention at a time, objects already in hand rather than handed over.
- When the story needs something hard (a vehicle turning toward camera, a crowd, hands on
  clothing), keep it and describe it precisely: path, speed, start and end framing, what the
  hands do.
- Hand-offs and fingers working small objects fail even when described precisely. Let the edit
  carry them: one scene ends as the object is offered, the next opens with it already held.
  The story keeps the moment; the model never has to render the exchange.
- Keep camera moves within one beat moderate (medium to close-up, not wide to extreme close-up);
  a very large push-in can come out as a cross-dissolve.
- Don't make a scene depend on reading text; the story must survive if text is illegible.

Rules:
- Use 'continuous' only when a shot physically continues the previous one (same moment,
  matching framing). Otherwise 'cut'.
- Every scene's refs list the ONE environment id plus every character and prop visible.
- Environment variants of the same place (night/morning) use based_on.
- Ids: short snake_case like char_tsering, env_pass_night, prop_bike, s01.
- Descriptions are concrete and visual: age, build, face, hair, exact colours and materials,
  textures, light sources. No vague adjectives.
- Style: fill every style field from the style brief with concrete visual traits, never studio or
  artist names. Describe what the image looks like, not the hardware that made it: say "fine film
  grain", not "35mm film"; "wide framing", not "anamorphic"; no film stock, camera or lens brand
  names, no lens flares or heavy bokeh unless the look truly needs them. Hardware words get
  rendered literally (film-strip borders, stuck flares).
- Set plan.pacing to the requested pacing.
- Keep the whole story within the requested scene count."""

DIRECTOR_SYSTEM = """You are the director reviewing a production plan before any footage is generated.
Every generated second costs money, so fix problems now. Return the complete revised plan (same
schema, same ids) and one note per change.

Check every scene for:
1. Dead time: each beat visibly changes something; no idle lead-in (the action is underway at
   0 s), no idle ending, no single action stretched across the clip. Fit beats and duration to
   the content and the pacing brief: a thin scene gets richer beats or a shorter duration
   (3-4 s), never padding. Something must still be moving in the last second.
2. Camera: every move motivated, with start and end framing, consistent with the style's camera
   grammar. No aimless pans or drifts.
3. Failure modes of today's video models:
   - complex 3D rotation of bodies or vehicles toward or around the camera (morphing)
   - hands handling fabric, small objects or other people in close-up; objects handed over.
     Precise description is not enough for a hand-off (both round-2 takes merged fingers into the
     envelope): imply it across a scene boundary instead: offered at the end of one scene,
     already held at the start of the next. That keeps the story beat.
   - cuts inside a clip (costumes and props get redrawn at the cut): use one continuous shot per
     clip unless multi_shot cuts are explicitly allowed
   - very large camera moves within one beat (can render as a cross-dissolve): keep them moderate
   - legible text on props, signs or screens (comes out garbled)
   - crowds where individuals matter; fast intricate choreography; liquids being poured
   - vehicles and bodies that move without a visible cause (wheels not turning, gliding): say
     what drives the motion (wheels spinning, tyre spray, suspension, feet, a lean into the turn)
   - faces in extreme close-up during big head movements (melting): keep close-up motion small
   - hardware words in the style that get rendered literally: "35mm film" (film-strip borders),
     "anamorphic" (stuck flares), film stock, camera or lens names; describe the look instead
   The rule: if the story doesn't need the risky element, restage it (a profile pass instead of
   a turn toward camera, the object already in hand, text kept off-screen). If the story needs
   it, keep it and make it precise: path, speed, framing, what the hands do. Never flatten the
   film to avoid risk. Record each risk you keep, and how it's handled, in scene.risks.
4. Continuity between scenes: screen direction, eyelines, costume and prop state, time of day;
   'continuous' only when a shot physically continues the previous one.
5. Refs: exactly one environment plus every character and prop visible.
6. Style profile: concrete traits, no studio or artist names, consistent with the medium.

Don't change the story, the characters' identities or any id. Keep what already works; a good
plan may need few notes. Each note says what changed and why."""


def planner_prompt(story: str, style: str, n_scenes: int, orientation: str,
                   preset: str | None, pacing: str | None) -> str:
    pacing = pacing if pacing in PACING else DEFAULT_PACING
    parts = [f"STORY / IDEA:\n{story}"]
    brief = preset_brief(preset)
    if brief:
        parts.append(f"STYLE PRESET (starting point):\n{brief}")
    parts.append(f"STYLE REQUEST:\n{style or ('as the preset' if brief else 'director’s choice, cinematic')}")
    parts.append(f"PACING: {pacing}. {pacing_brief(pacing)}")
    parts.append(f"ORIENTATION: {orientation}\nTARGET SCENE COUNT: about {n_scenes}")
    return "\n\n".join(parts)


# fields that belong to the project, not the story; the director never sees or changes them
PROJECT_KEYS = ("orientation", "prompt_overrides", "selected_takes", "video_providers",
                "director_notes", "brief", "planner")


def director_prompt(plan: dict) -> str:
    brief = plan.get("brief", {})
    pacing = plan.get("pacing") or brief.get("pacing") or DEFAULT_PACING
    story_plan = {k: v for k, v in plan.items() if k not in PROJECT_KEYS}
    parts = []
    if brief.get("story"):
        parts.append(f"ORIGINAL IDEA:\n{brief['story']}")
    if brief.get("style"):
        parts.append(f"STYLE REQUEST:\n{brief['style']}")
    parts.append(f"PACING: {pacing}. {pacing_brief(pacing)}")
    parts.append(f"ORIENTATION: {plan.get('orientation', '16:9')}")
    parts.append("PLAN:\n" + json.dumps(story_plan, indent=1, ensure_ascii=False))
    return "\n\n".join(parts)


# ---------------------------------------------------------------- normalise

def normalize(plan: dict, allow_multi_shot: bool = True) -> dict:
    """Make beat timings consistent: sorted, starting at 0, contiguous-ish, and each scene's
    duration equal to the end of its last beat. Cuts only in multi-shot scenes.
    allow_multi_shot=False turns in-clip cuts off (planner/director output, see RND round 2);
    a person editing the plan can still turn them on per scene."""
    plan = copy.deepcopy(plan)
    for sc in plan.get("scenes", []):
        if not allow_multi_shot:
            sc["multi_shot"] = False
        beats = sorted(sc.get("beats") or [], key=lambda b: b.get("t_start", 0))
        if not beats:
            continue
        t = 0.0
        for b in beats:
            start = max(t, float(b.get("t_start", t)))
            if start - t < 0.5:            # close small gaps so nothing is left undescribed
                start = t
            end = max(start + 0.5, float(b.get("t_end", start + 1)))
            b["t_start"], b["t_end"] = round(start, 2), round(end, 2)
            t = end
            if not sc.get("multi_shot"):
                b.pop("cut", None)
        beats[0]["t_start"] = 0.0
        beats[0].pop("cut", None)          # the first shot doesn't start with a cut
        sc["beats"] = beats
        sc["duration_s"] = max(2, math.ceil(beats[-1]["t_end"] - 1e-6))
        sc.setdefault("multi_shot", False)
    return plan
