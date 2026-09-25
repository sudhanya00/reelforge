"""Influencer mode: a designed, fictional person with a consistent identity who makes short
selfie-camera videos.

  library/influencers/<id>/influencer.json       the profile (look, persona, voice, setting)
  library/influencers/<id>/identity/<view>.png   the identity pack: face first, the rest painted from it
  library/influencers/<id>/videos/<video>/       one folder per video (a Project: plan, log, takes)

A talking-head reel is one continuous take: the first ~10 s is generated with the identity pack
attached, then Omni *extends* the same take ~10 s at a time (up to 40 s), which keeps the face,
voice, room and camera continuous. Realism language lives in the constants below.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pipeline as pl
import providers
from providers import ProviderError, Ref, Shot
from prompts import dot, edit_instruction

# ---------------------------------------------------------------- profile

PROFILE_FIELDS = [
    ("name", "Name"), ("handle", "Handle"), ("gender", "Gender"), ("age", "Age"),
    ("ethnicity", "Ethnicity"), ("skin", "Skin"), ("hair", "Hair"), ("body", "Body type"),
    ("features", "Distinctive features"), ("style", "Fashion style"), ("outfit", "Signature outfit"),
    ("niche", "Niche"), ("persona", "Personality"), ("speech", "How they talk"),
    ("voice", "Voice"), ("setting", "Where they film"),
]
KEYS = [k for k, _ in PROFILE_FIELDS]

PROFILE_SCHEMA = {"type": "object", "required": KEYS,
                  "properties": {k: {"type": "string"} for k in KEYS}}

DESIGN_SYSTEM = """You design fictional social-media creators for an AI video pipeline. Given a concept
and any fields already chosen, fill every field so the person is specific, believable and
consistent. Never base them on a real person or celebrity.
- Look fields are concrete and visual: exact hair colour, length and texture; skin tone with real
  texture (pores, freckles, marks); build; one or two distinctive features that make them
  recognisable (a mole, a gap tooth, glasses, a nose ring).
- outfit: one signature outfit described by garment, colour and fabric.
- persona and speech: how they come across and how they actually talk (pace, slang, filler words,
  a catchphrase or two).
- voice: timbre, pitch, accent, energy.
- setting: the one real, lived-in place they usually film in, described with specific objects.
- handle starts with @. Keep chosen fields exactly as given."""


def look_text(p: dict) -> str:
    return (f"{p['age']}-year-old {p['ethnicity']} {p['gender']}. Skin: {dot(p['skin'])} "
            f"Hair: {dot(p['hair'])} Build: {dot(p['body'])} Distinctive: {dot(p['features'])}")


# ---------------------------------------------------------------- realism

# Photos for the identity pack: unretouched, natural light, real texture.
PHOTO_REALISM = (
    "Unretouched candid photo. Real skin texture: visible pores, fine facial hair, subtle "
    "blemishes, natural variation in skin tone, slight under-eye texture; no smoothing, no beauty "
    "filter, no makeup unless described. Natural flyaway hairs. Soft natural window light with "
    "slightly uneven exposure. Ordinary lived-in surroundings. Looks like a real person, not a "
    "model shoot. No text, no watermark.")

# Every reel shot: what a front-facing phone camera held by the person looks like.
SELFIE_CAMERA = (
    "Filmed on the front camera of a phone held at arm's length by the person themselves; the "
    "phone is never visible. Wide-angle close perspective, face in the upper third, eyes on the "
    "lens. Handheld: subtle constant micro-shake, small reframes as the arm moves, occasional "
    "slight tilt. Phone auto-exposure adjusting to the light; natural practical and window light, "
    "no studio lighting. Deep focus like a phone camera, no cinematic bokeh. Real skin texture "
    "and flyaway hair, unretouched. Natural posture, not posed. Phone-microphone audio with "
    "room tone, no background music.")

NATURAL_DELIVERY = (
    "Talks like a real person, not an actor: natural rhythm with small pauses, blinks, brief "
    "glances away and back to the lens, eyebrows and hands moving with the words, relaxed "
    "micro-expressions.")

# ---------------------------------------------------------------- identity pack

IDENTITY = [
    # view id, aspect, painted from the face?, framing
    ("face", "3:4", False,
     "A front-camera selfie at arm's length: head and shoulders, looking straight into the lens "
     "with a relaxed, natural expression."),
    ("three_quarter", "3:4", True, "Head and shoulders turned three-quarters to the left, "
                                   "photographed by a friend, mid-conversation."),
    ("profile", "3:4", True, "Head and shoulders in side profile, looking off to the right, "
                             "photographed by a friend."),
    ("full_body", "9:16", True, "Full-length, standing naturally in the signature outfit, "
                                "photographed by a friend at eye level."),
    ("setting", "9:16", False, "The place with nobody in it, seen from where the person usually "
                               "holds the phone to film themselves: eye level, arm's length from "
                               "their usual spot."),
]
VIEW_IDS = [v[0] for v in IDENTITY]


def identity_prompt(p: dict, view: str) -> str:
    _, _, from_face, framing = next(v for v in IDENTITY if v[0] == view)
    if view == "setting":
        return f"{framing} The place: {dot(p['setting'])} {PHOTO_REALISM}"
    same = ("The same person as in the reference photo: identical face, hair, skin and features. "
            if from_face else "")
    wearing = f"Wearing {dot(p['outfit'])}"
    return f"{same}{framing} {look_text(p)} {wearing} Setting: {dot(p['setting'])} {PHOTO_REALISM}"


# ---------------------------------------------------------------- scripts

FORMATS = {
    "talking_head": {
        "label": "Talking-head vlog",
        "brief": ("Straight to camera, selfie-style: a hook in the first two seconds, then the "
                  "point, delivered like they're talking to a friend."),
    },
}

REEL_SCHEMA = {
    "type": "object", "required": ["title", "hook", "caption", "segments"],
    "properties": {
        "title": {"type": "string"},
        "hook": {"type": "string", "description": "the first line, spoken in the first 2 seconds"},
        "caption": {"type": "string", "description": "post caption with a few hashtags"},
        "segments": {"type": "array", "items": {
            "type": "object", "required": ["id", "seconds", "lines", "delivery", "action"],
            "properties": {
                "id": {"type": "string"},
                "seconds": {"type": "integer"},
                "lines": {"type": "array", "items": {"type": "string"}},
                "delivery": {"type": "string", "description": "tone and expression while saying it"},
                "action": {"type": "string", "description": "small physical business: gestures, leaning in, adjusting the phone"},
            }}},
    },
}

SCRIPT_SYSTEM = """You write short-form video scripts for a fictional social-media creator, in their
own voice. The video is one continuous selfie-camera take, generated in segments of exactly 10
seconds (the first may be 8-10 s), so the script is split into segments.

- The first words are the hook: a strong reason to keep watching, inside 2 seconds.
- Write how this person actually talks (their speech notes): contractions, their slang, a
  filler word now and then, an occasional small self-correction. Never stage directions in
  the lines.
- About 2.3 spoken words per second: roughly 20-23 words per 10-second segment. End each
  segment at a natural pause so the next can pick up.
- Each segment has small physical business so the shot is never static: a gesture, leaning in,
  a glance off-camera and back, adjusting the phone, a laugh.
- Keep claims generic and honest: no medical, legal or financial promises, no fake statistics.
- End with a natural sign-off or light call to action that fits them.
- Segment ids: p1, p2, ... Total seconds must equal the requested length."""


def script_prompt(p: dict, fmt: str, topic: str, points: str, length_s: int) -> str:
    f = FORMATS[fmt]
    persona = "\n".join(f"- {label}: {p[k]}" for k, label in PROFILE_FIELDS if k not in ("name", "handle"))
    return (f"CREATOR: {p['name']} ({p['handle']})\n{persona}\n\n"
            f"FORMAT: {f['label']}. {f['brief']}\n"
            f"TOPIC: {topic}\n"
            f"TALKING POINTS: {points or 'their choice'}\n"
            f"LENGTH: {length_s} seconds ({max(1, length_s // 10)} segments)")


def segment_prompt(p: dict, seg: dict, refs: list[str], first: bool) -> str:
    """The Omni prompt for one segment of a talking-head take."""
    said = " ".join(seg["lines"])
    speak = (f'{p["name"]} ({dot(p["voice"])}) says, straight into the lens: "{said}" '
             f"Delivery: {dot(seg['delivery'])} Action: {dot(seg['action'])}")
    if not first:
        return edit_instruction(
            f"Continue the same continuous selfie take for {seg['seconds']} more seconds: same "
            f"person, same room, same camera and light, no cut. {speak} {NATURAL_DELIVERY}")
    tags = " ".join(f"<IMAGE_REF_{i}>@Image{i + 1}" for i in range(len(refs)))
    person = [i for i, r in enumerate(refs) if r != "setting"]
    who = ", ".join(f"<IMAGE_REF_{i}>" for i in person)
    room = f" The room is the place in <IMAGE_REF_{refs.index('setting')}>." if "setting" in refs else ""
    return "\n".join([
        f"[# References {tags}]",
        f"{p['name']} is the person in {who}: match face, hair, skin texture and features exactly.{room}",
        f"Wearing {dot(p['outfit'])}",
        speak,
        NATURAL_DELIVERY,
        SELFIE_CAMERA,
        f"Duration {seg['seconds']} seconds. One continuous take, no cuts.",
    ])


# ---------------------------------------------------------------- storage

class Influencers:
    def __init__(self, library_root: Path):
        self.root = Path(library_root) / "influencers"
        self.root.mkdir(parents=True, exist_ok=True)

    def all(self) -> list[dict]:
        out = [self.get(d.name) for d in self.root.iterdir() if (d / "influencer.json").exists()]
        return sorted(out, key=lambda x: x.get("created", 0), reverse=True)

    def dir(self, iid: str) -> Path:
        if not re.fullmatch(r"[a-z0-9_]+", iid):
            raise KeyError(iid)
        return self.root / iid

    def get(self, iid: str) -> dict:
        f = self.dir(iid) / "influencer.json"
        if not f.exists():
            raise KeyError(iid)
        return json.loads(f.read_text(encoding="utf-8"))

    def create(self, profile: dict) -> dict:
        base = re.sub(r"[^a-z0-9]+", "_", (profile.get("name") or "creator").lower()).strip("_") or "creator"
        iid, n = base, 2
        while self.dir(iid).exists():
            iid, n = f"{base}_{n}", n + 1
        inf = {"id": iid, "profile": {k: profile.get(k, "") for k in KEYS}, "created": time.time()}
        (self.dir(iid) / "identity").mkdir(parents=True)
        (self.dir(iid) / "videos").mkdir()
        self.save(inf)
        return inf

    def save(self, inf: dict) -> None:
        (self.dir(inf["id"]) / "influencer.json").write_text(json.dumps(inf, indent=2, ensure_ascii=False), encoding="utf-8")

    def log(self, iid: str, **entry) -> None:
        entry["ts"] = datetime.now().isoformat(timespec="seconds")
        with pl.Project._log_lock, open(self.dir(iid) / "log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def log_design(self, **entry) -> None:
        """Designer calls happen before the influencer exists; their cost goes here."""
        entry.update(kind="plan", planner="design", ts=datetime.now().isoformat(timespec="seconds"))
        with pl.Project._log_lock, open(self.root / "design_log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def image(self, iid: str, view: str) -> Path:
        return self.dir(iid) / "identity" / f"{view}.png"

    def videos(self, iid: str) -> list[pl.Project]:
        vd = self.dir(iid) / "videos"
        return sorted((pl.Project(d) for d in vd.iterdir() if (d / "plan.json").exists()),
                      key=lambda p: p.root.name, reverse=True)

    def video(self, iid: str, vid: str) -> pl.Project:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", vid):
            raise KeyError(vid)
        return pl.Project.open(self.dir(iid) / "videos" / vid)


# ---------------------------------------------------------------- AI calls

def fill_profile(client, s: pl.Settings, partial: dict, concept: str) -> tuple[dict, dict]:
    """Complete a half-filled profile from a one-line concept. Returns (profile, usage)."""
    chosen = {k: v for k, v in partial.items() if k in KEYS and v}
    prompt = f"CONCEPT: {concept or 'a relatable everyday creator'}\nALREADY CHOSEN (keep exactly):\n" + \
        json.dumps(chosen, indent=1, ensure_ascii=False)
    out, usage = pl._json_call(client, s, DESIGN_SYSTEM, prompt, PROFILE_SCHEMA, "design")
    out.update(chosen)
    if out.get("handle") and not out["handle"].startswith("@"):
        out["handle"] = "@" + out["handle"]
    return out, usage


def paint_identity(client, s: pl.Settings, lib: Influencers, iid: str, views: list[str] | None = None,
                   force: bool = False, on_progress=None) -> dict[str, str]:
    """Paint the identity pack: the face first, then the views that are painted from it."""
    inf = lib.get(iid)
    p = inf["profile"]
    wanted = views or VIEW_IDS
    results = {}
    for view, aspect, from_face, _ in sorted(IDENTITY, key=lambda v: v[2]):      # face (and setting) first
        if view not in wanted:
            continue
        out = lib.image(iid, view)
        if out.exists() and not force:
            results[view] = "skipped"
            continue
        face = lib.image(iid, "face")
        if from_face and not face.exists():
            results[view] = "failed: paint the face first"
            continue
        prompt = inf.get("prompt_overrides", {}).get(view) or identity_prompt(p, view)
        try:
            usage = pl.generate_image(client, s, prompt, out, refs=[face] if from_face else None,
                                      aspect=aspect)
            lib.log(iid, kind="image", id=f"identity:{view}", model=s.image_model, prompt=prompt,
                     image_size=s.image_size, aspect=aspect, usage=usage,
                     cost_usd=pl.call_cost(s.image_model, usage, s.image_size))
            results[view] = "done"
        except Exception as e:  # noqa: BLE001
            results[view] = ("fatal: " if pl._is_fatal(e) else "failed: ") + pl.friendly_error(e)
        on_progress and on_progress(view, results[view])
        if results[view].startswith("fatal"):
            break
    return results


def write_script(client, s: pl.Settings, lib: Influencers, iid: str, fmt: str, topic: str,
                 points: str, length_s: int) -> pl.Project:
    """Draft a video: the script in the creator's voice, as a new video folder."""
    inf = lib.get(iid)
    length_s = max(10, min(40, round(length_s / 10) * 10))
    reel, usage = pl._json_call(client, s, SCRIPT_SYSTEM, script_prompt(inf["profile"], fmt, topic, points, length_s),
                                REEL_SCHEMA, "script")
    reel["segments"] = normalize_segments(reel["segments"], length_s)
    proj = pl.Project.new(lib.dir(iid) / "videos", reel["title"])
    plan = {"kind": "reel", "influencer": iid, "format": fmt, "orientation": "9:16",
            "brief": {"topic": topic, "points": points, "length_s": length_s}, **reel}
    proj.save_plan(plan)
    proj.log(kind="plan", model=s.planner_model, planner="script", usage=usage,
             cost_usd=pl.call_cost(s.planner_model, usage))
    return proj


def normalize_segments(segs: list[dict], length_s: int) -> list[dict]:
    """Segments of 10 s (the first 8-10 s) adding up to the requested length."""
    n = max(1, length_s // 10)
    segs = (segs or [])[:n]
    while len(segs) < n:
        segs.append({"id": "", "seconds": 10, "lines": [], "delivery": "natural", "action": "small gestures"})
    for i, sg in enumerate(segs, start=1):
        sg["id"] = f"p{i}"
        sg["seconds"] = 10 if i > 1 else max(8, min(10, int(sg.get("seconds") or 10)))
    return segs


# ---------------------------------------------------------------- shooting

REFS_FOR_TALKING_HEAD = ["face", "three_quarter", "profile", "setting"]


def reel_shot(lib: Influencers, iid: str, plan: dict, seg: dict, resolution: str) -> Shot:
    refs = [Ref(id=v, kind="environment" if v == "setting" else "character", name=v,
                path=lib.image(iid, v))
            for v in REFS_FOR_TALKING_HEAD if lib.image(iid, v).exists()]
    return Shot(plan=plan, scene=seg, refs=refs, first_frame=None, aspect="9:16",
                resolution=resolution, duration_s=seg["seconds"])


def shoot_reel(client, s: pl.Settings, lib: Influencers, iid: str, proj: pl.Project,
               log=print, step=None) -> Path:
    """One continuous take: generate the first segment, extend it segment by segment, then
    save the result as final.mp4. Every turn is kept as a take with its prompt and cost."""
    step = step or (lambda *a: None)
    inf, plan = lib.get(iid), proj.load_plan()
    p, segs = inf["profile"], plan["segments"]
    vp = providers.video_provider("gemini-omni", s, client)
    if not lib.image(iid, "face").exists():
        raise ProviderError(400, "Paint the influencer's identity pack first (at least the face).")
    if sum(sg["seconds"] for sg in segs) > vp.MAX_EXTENDED_S:
        raise ProviderError(400, f"Reels can be at most {vp.MAX_EXTENDED_S} s.")
    overrides = plan.get("prompt_overrides", {})
    shot, meta, turns = None, None, []
    for i, seg in enumerate(segs, start=1):
        step("video", f"{'Shooting' if i == 1 else 'Extending'} · segment {i} of {len(segs)}", i - 1, len(segs))
        if i == 1:
            shot = reel_shot(lib, iid, plan, seg, vp.resolution_for(s.resolution))
            prompt = overrides.get(seg["id"]) or segment_prompt(p, seg, [r.id for r in shot.refs], first=True)
            submit = (lambda sh, pr: lambda: vp.submit(sh, pr))(shot, prompt)
            info = {"refs": [r.id for r in shot.refs],
                    "format": {"type": "video", "aspect_ratio": "9:16", "resolution": shot.resolution}}
        else:
            prompt = overrides.get(seg["id"]) or segment_prompt(p, seg, [], first=False)
            submit = (lambda m, pr: lambda: vp.submit_extend(m, pr))(meta, prompt)
            info = {"extends": turns[-1].name}
        out = pl._shoot(vp, s, proj, "reel", submit,
                        {"scene": "reel", "segment": seg["id"], "prompt": prompt, **info},
                        kind="video" if i == 1 else "video_edit")
        meta = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
        turns.append(out)
        log(f"{seg['id']}: {out.name}, {meta['duration_s']}s, ${meta['cost_usd']}")
    step("stitch", "Finishing", len(segs), len(segs) + 1)
    final = _finish(proj, turns, sum(sg["seconds"] for sg in segs))
    log(f"Final: {final.name}")
    return final


def _finish(proj: pl.Project, turns: list[Path], planned_s: int) -> Path:
    """If extensions return the whole video so far, the last turn is the reel; if each returns
    only its new seconds, the turns are joined. Which one happened is recorded in the plan."""
    last = turns[-1]
    d = pl.video_duration(last) or 0
    final = proj.root / "final.mp4"
    plan = proj.load_plan()
    plan["turns"] = [t.name for t in turns]
    if len(turns) == 1 or d >= 0.75 * planned_s:
        shutil.copy2(last, final)
        plan["extension_mode"] = "cumulative"
    else:
        lst = proj.root / "concat.txt"
        lst.write_text("".join(f"file '{t.resolve().as_posix()}'\n" for t in turns), encoding="utf-8")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c:v", "libx264", "-crf", "18", "-c:a", "aac", str(final)], check=True)
        plan["extension_mode"] = "segments"
    proj.save_plan(plan)
    return final
