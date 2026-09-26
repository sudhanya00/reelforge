"""Influencer mode: a designed, fictional person with a consistent identity who makes short
phone-camera videos in many settings.

  library/influencers/<id>/influencer.json       profile (look, persona, voice, home) + saved places
  library/influencers/<id>/identity/<view>.png   the identity pack: face first, the rest painted from it
  library/influencers/<id>/places/<place>.png    saved places beyond home (an empty plate each)
  library/influencers/<id>/videos/<video>/       one folder per video (a Project: plan, log, takes)

Identity is the person (face, hair, body, voice). Everything else changes per video: its
*setup* says the format (selfie, walk and talk, mirror, ...), where, what they wear, their
position and the light. An *opening frame* is painted for each setup from the identity pack
(cheap, reviewable), and the video starts from it; Omni then *extends* the same take ~10 s at
a time (up to 40 s), keeping face, voice, place and camera continuous.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pipeline as pl
import products as prod
import providers
from providers import ProviderError, Ref, Shot
from prompts import dot, edit_instruction

# ---------------------------------------------------------------- profile

PROFILE_FIELDS = [
    ("name", "Name"), ("handle", "Handle"), ("gender", "Gender"), ("age", "Age"),
    ("ethnicity", "Ethnicity"), ("skin", "Skin"), ("hair", "Hair"), ("body", "Body type"),
    ("features", "Distinctive features"), ("style", "Fashion style"), ("outfit", "Go-to outfit"),
    ("niche", "Niche"), ("persona", "Personality"), ("speech", "How they talk"),
    ("voice", "Voice"), ("setting", "Home"),
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
- style: their fashion sense in general (they wear different things every day).
- outfit: their go-to everyday outfit, by garment, colour and fabric.
- persona and speech: how they come across and how they actually talk (pace, slang, filler words,
  a catchphrase or two).
- voice: timbre, pitch, accent, energy.
- setting: their home, the room they film in most, described with specific objects.
- handle starts with @. Keep chosen fields exactly as given."""


def look_text(p: dict) -> str:
    """Only what's filled in (a character from photos may leave age, background or gender blank)."""
    who = " ".join(x for x in (f"{p['age']}-year-old" if p.get("age") else "", p.get("ethnicity", ""),
                               p.get("gender", "")) if x)
    parts = [f"{who}." if who else ""] + [f"{label}: {dot(p[k])}" for k, label in
                                          (("skin", "Skin"), ("hair", "Hair"), ("body", "Build"), ("features", "Distinctive"))
                                          if p.get(k)]
    return " ".join(x for x in parts if x)


# ---------------------------------------------------------------- realism

# Photos: unretouched, natural light, real texture.
PHOTO_REALISM = (
    "Unretouched candid photo. Real skin texture: visible pores, fine facial hair, subtle "
    "blemishes, natural variation in skin tone, slight under-eye texture; no smoothing, no beauty "
    "filter, no makeup unless described. Natural flyaway hairs. Natural light with slightly uneven "
    "exposure. Ordinary lived-in surroundings. Looks like a real person, not a model shoot. "
    "No text, no watermark.")

# Every video, whatever the camera set-up.
VIDEO_REALISM = (
    "Looks like a real phone video, not a film: real skin texture and flyaway hair, unretouched; "
    "natural, unposed posture; auto-exposure and auto-white-balance shifting slightly with the "
    "light; no studio lighting, no colour grade. Audio from the phone microphone with the "
    "place's real ambient sound; no background music, no captions or text on screen.")

NATURAL_DELIVERY = (
    "Talks like a real person, not an actor: natural rhythm with small pauses, blinks, brief "
    "glances away and back, eyebrows and hands moving with the words, relaxed micro-expressions.")

# ---------------------------------------------------------------- formats

# Each format is a camera set-up. `camera` goes into every first-turn video prompt, `frame` into
# the opening-frame photo, `to` says who they talk to, `business` guides the script's actions.
# `empty_open`: the opening frame is the empty place (they walk in), so a separate full-body
# "look" photo carries the outfit.
FORMATS: dict[str, dict] = {
    "talking_head": {
        "label": "Selfie talking head",
        "blurb": "Phone at arm's length, straight to camera",
        "brief": "Straight to camera, selfie-style, like a FaceTime with a friend.",
        "camera": ("Filmed on the front camera of a phone held at arm's length by the person "
                   "themselves; the phone is never visible. Wide-angle close perspective, face in "
                   "the upper third, eyes on the lens. Handheld: subtle constant micro-shake, small "
                   "reframes as the arm moves, occasional slight tilt. Deep focus like a phone camera."),
        "frame": ("A still from a front-camera selfie video at arm's length: head and shoulders, "
                  "looking into the lens mid-sentence. The phone is not visible."),
        "to": "straight into the lens",
        "business": "gestures, leaning in, a glance off-camera and back, adjusting the phone, a laugh",
        "continue": "same person, place, outfit, selfie camera and light",
    },
    "propped": {
        "label": "Propped-up phone",
        "blurb": "Sit-down chat, phone leaning on something",
        "brief": "A relaxed sit-down chat to a phone propped up in front of them.",
        "camera": ("The phone is propped up on a surface or a small tripod at chest-to-eye height, "
                   "an arm and a half away; the phone is never visible. Static frame, waist-up, "
                   "slightly off-centre, with a tiny wobble if they bump the surface. Wide phone "
                   "lens, deep focus."),
        "frame": ("A still from a video shot on a propped-up phone: waist-up, seated, slightly "
                  "off-centre, looking into the lens mid-sentence."),
        "to": "into the lens",
        "business": "hand gestures, shifting in the seat, sipping a drink, pulling a knee up, reaching toward the phone",
        "continue": "same person, place, outfit, static propped-up phone frame and light",
    },
    "walk_and_talk": {
        "label": "Walk and talk",
        "blurb": "Selfie camera while walking somewhere",
        "brief": "Filmed on the move, selfie camera in hand, walking somewhere real.",
        "camera": ("Front camera held at arm's length while they walk; the phone is never visible. "
                   "Steady walking bounce and sway, the background moving past behind them, the arm "
                   "drifting and reframing, an occasional glance ahead to where they're going. Wide "
                   "phone lens, deep focus. Wind and street sound on the phone mic."),
        "frame": ("A still from a front-camera selfie video taken while walking: head and "
                  "shoulders, arm's length, the place behind them, looking into the lens mid-stride."),
        "to": "into the lens while walking",
        "business": "glancing ahead, stepping around someone, pointing at something they pass, adjusting their grip",
        "continue": "same person, outfit and walking selfie camera, still walking through the same place",
    },
    "mirror": {
        "label": "Mirror video",
        "blurb": "Filmed in a mirror, phone in hand: outfits, GRWM",
        "brief": "Filmed in a mirror, phone in hand, showing the outfit or getting ready.",
        "camera": ("Filmed as a reflection in a mirror: the person holds the phone at chest height and "
                   "the phone is visible in the reflection, sometimes covering part of the lower "
                   "face. They look between the phone screen and their reflection. Three-quarter or "
                   "full body in frame so the outfit shows. Handheld, small movements; the room's "
                   "own light."),
        "frame": ("A mirror selfie still: the person's reflection in a mirror, phone held at chest "
                  "height and visible, three-quarter to full body, the room around them."),
        "to": "to their reflection in the mirror",
        "business": "turning to show the outfit, adjusting clothes or hair, stepping closer to the mirror, a pose then breaking it",
        "continue": "same person, outfit, mirror, room and handheld phone",
    },
    "walk_in": {
        "label": "Walk into frame",
        "blurb": "Phone propped up; they walk in and start talking",
        "brief": "The phone is set down first; they walk into frame and start talking.",
        "camera": ("The phone is propped up at eye height on a static, locked-off frame; it is never "
                   "visible. The frame begins empty for about one second, then the person walks into "
                   "frame from the side, stops at a natural spot facing the lens, and starts talking. "
                   "Static camera throughout, wide phone lens, deep focus."),
        "frame": ("An empty frame from a phone propped up at eye height: the place with nobody in "
                  "it yet, room for a person to walk in and stand in the middle."),
        "to": "into the lens",
        "business": "walking in and settling, putting something down, gesturing, stepping closer",
        "continue": "same person, place, outfit, static propped-up phone frame and light",
        "empty_open": True,
    },
    "podcast": {
        "label": "Podcast",
        "blurb": "Seated at a mic, like a podcast clip",
        "brief": "A podcast clip: seated at a mic, talking half to a co-host, half to camera.",
        "camera": ("A podcast set-up: seated at a table with a broadcast microphone on a boom arm in "
                   "front of them, maybe headphones; camera on a tripod at eye level, medium "
                   "close-up, slightly off-axis, static. Soft practical lights, a lived-in background "
                   "a little out of focus. Clean close-mic audio with a little room tone."),
        "frame": ("A still from a podcast video: seated at a table, broadcast microphone on a boom "
                  "arm in front of them, medium close-up from a tripod slightly off-axis."),
        "to": "half to an off-screen co-host, half to the camera",
        "business": "leaning into the mic, a hand gesture, a glance to the co-host, a laugh, sitting back",
        "continue": "same person, podcast set, outfit, static camera and light",
    },
}


def fmt_of(plan: dict) -> dict:
    return FORMATS.get(plan.get("format"), FORMATS["talking_head"])


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
    ("full_body", "9:16", True, "Full-length, standing naturally, photographed by a friend at eye "
                                "level, so their build and proportions are clear."),
    ("setting", "9:16", False, "An empty room: a plain eye-level photo of the place where they usually "
                               "film, with no people, no hands and no phone in the frame."),
]
VIEW_IDS = [v[0] for v in IDENTITY]


def identity_prompt(p: dict, view: str, from_sources: bool = False) -> str:
    """`from_sources`: the character was made from photos of a real person (with consent);
    every view is painted from those photos."""
    _, _, from_face, framing = next(v for v in IDENTITY if v[0] == view)
    if view == "setting":
        return f"{framing} The place: {dot(p['setting'])} {PHOTO_REALISM}"
    if from_sources:
        same = ("The same person as in the reference photos: identical face, face shape, hair, skin, "
                "features and build; keep their real look, don't beautify. ")
    else:
        same = ("The same person as in the reference photo: identical face, hair, skin and features. "
                if from_face else "")
    wearing = f"Wearing {dot(p['outfit'])}"
    return f"{same}{framing} {look_text(p)} {wearing} Setting: {dot(p['setting'])} {PHOTO_REALISM}"


DESCRIBE_PERSON_SYSTEM = """You describe how a person looks in photos so an image model can paint them
again consistently. Describe only what is visible; never identify the person or guess their name,
age, ethnicity or gender.
- hair: colour, length, texture, usual style.
- skin: tone and texture, freckles, marks.
- body: build and proportions.
- features: one to three distinctive, recognisable details (glasses, a mole, piercings, brows).
- style: their fashion sense from what they wear.
- outfit: the outfit in the clearest photo: garments, colours, fabrics."""

DESCRIBE_PERSON_KEYS = ("hair", "skin", "body", "features", "style", "outfit")
DESCRIBE_PERSON_SCHEMA = {"type": "object", "required": list(DESCRIBE_PERSON_KEYS),
                          "properties": {k: {"type": "string"} for k in DESCRIBE_PERSON_KEYS}}


INSPIRATION_SYSTEM = """You read a mood board for designing a NEW, original social-media creator. The
images show looks, styles and vibes the user likes (people, outfits, makeup, settings). Describe
the TYPE they share, in words, so a new person can be designed with that feel.
- Never identify or name anyone, and never describe facial structure (face shape, eyes, nose,
  lips, jaw, brows): the new person gets their own face.
- hair: colour, length, texture and styling.
- skin: tone and finish (e.g. fair with a warm flush, sun-kissed).
- body: build and silhouette.
- style: fashion sense and makeup style.
- outfit: one signature outfit in that style: garments, colours, fabrics.
- persona: the energy and vibe the images project, as a personality to start from (warm,
  bubbly, playful...), without claims about anyone real.
If the images don't agree, describe the common thread."""

INSPIRATION_KEYS = ("hair", "skin", "body", "style", "outfit", "persona")
INSPIRATION_SCHEMA = {"type": "object", "required": list(INSPIRATION_KEYS),
                      "properties": {k: {"type": "string"} for k in INSPIRATION_KEYS}}


def describe_inspiration(client, s: pl.Settings, photos: list[Path]) -> tuple[dict, dict]:
    """A mood board read into words. The images are only read here: they never go to the
    image or video models and aren't kept with the creator."""
    return pl.json_call_with_images(client, s, INSPIRATION_SYSTEM, "Describe the type these images share.",
                                    photos[:8], INSPIRATION_SCHEMA, "describe inspiration")


def describe_person(client, s: pl.Settings, photos: list[Path]) -> tuple[dict, dict]:
    return pl.json_call_with_images(client, s, DESCRIBE_PERSON_SYSTEM, "Describe how this person looks.",
                                    photos[:4], DESCRIBE_PERSON_SCHEMA, "describe person")


def place_prompt(description: str) -> str:
    return (f"An empty place: a plain eye-level photo with no people, no hands and no phone in the frame. "
            f"{dot(description)} {PHOTO_REALISM}")


# ---------------------------------------------------------------- scripts

SETUP_KEYS = ("location", "outfit", "position", "light")

REEL_SCHEMA = {
    "type": "object", "required": ["title", "hook", "caption", "setup", "segments"],
    "properties": {
        "title": {"type": "string"},
        "hook": {"type": "string", "description": "the first line, spoken in the first 2 seconds"},
        "caption": {"type": "string", "description": "post caption with a few hashtags"},
        "setup": {"type": "object", "required": list(SETUP_KEYS), "properties": {
            "location": {"type": "string", "description": "the specific real place, with a few concrete details"},
            "outfit": {"type": "string", "description": "what they wear today: garments, colours, fabrics"},
            "position": {"type": "string", "description": "posture and where they are, e.g. sitting cross-legged on the sofa"},
            "light": {"type": "string", "description": "time of day and the light, e.g. late afternoon window light"},
        }},
        "segments": {"type": "array", "items": {
            "type": "object", "required": ["id", "seconds", "lines", "delivery", "action"],
            "properties": {
                "id": {"type": "string"},
                "seconds": {"type": "integer"},
                "lines": {"type": "array", "items": {"type": "string"}},
                "delivery": {"type": "string", "description": "tone and expression while saying it"},
                "action": {"type": "string", "description": "small physical business that fits the format"},
            }}},
    },
}

SCRIPT_SYSTEM = """You write short-form video scripts for a fictional social-media creator, in their
own voice, and set up the shot. The video is one continuous phone-camera take in the given
FORMAT, generated in segments of exactly 10 seconds (the first may be 8-10 s).

SETUP (where, what they wear, position, light):
- Real people don't film everything at home in the same clothes. Pick a specific place, an
  outfit and a light that fit the topic, the format and the occasion. Their home and go-to
  outfit are options, not defaults.
- Anything given under SETUP HINTS is kept exactly; fill the rest to match it.
- Be concrete and visual: garments with colours and fabrics; the place with a few real details.

SCRIPT:
- The first words are the hook: a strong reason to keep watching, inside 2 seconds.
- Write how this person actually talks (their speech notes): contractions, their slang, a
  filler word now and then, an occasional small self-correction. Never stage directions in
  the lines.
- About 2.3 spoken words per second: roughly 20-23 words per 10-second segment (fewer in a
  segment where they walk in or do something). End each segment at a natural pause.
- Each segment has physical business that fits the format, so the shot is never static.
- Keep claims generic and honest: no medical, legal or financial promises, no fake statistics.
- Products under FEATURING: use their name and brand exactly as written, and only the facts
  given there or what's visible; never invent claims about a product. Anything worn is part of
  the outfit; anything held is in hand and shown to the camera.
- End with a natural sign-off or light call to action that fits them.
- Segment ids: p1, p2, ... Total seconds must equal the requested length."""


def script_prompt(p: dict, fmt: str, topic: str, points: str, length_s: int, hints: dict,
                  featured: list[dict] | None = None) -> str:
    f = FORMATS[fmt]
    persona = "\n".join(f"- {label}: {p[k]}" for k, label in PROFILE_FIELDS if k not in ("name", "handle"))
    given = "\n".join(f"- {k}: {v}" for k, v in hints.items() if v) or "- none: choose everything"
    feat = ""
    if featured:
        feat = "FEATURING:\n" + "\n".join(
            f"- {x['name']}{' by ' + x['brand'] if x.get('brand') else ''} "
            f"({'they wear it' if x['use'] == 'wear' else 'they hold it and show it'}): {x.get('description', '')} "
            f"Facts they may say: {x.get('notes') or 'only what is visible'}" for x in featured) + "\n"
    return (f"CREATOR: {p['name']} ({p['handle']})\n{persona}\n\n"
            f"FORMAT: {f['label']}. {f['brief']} Physical business that fits: {f['business']}.\n"
            f"{feat}"
            f"SETUP HINTS:\n{given}\n"
            f"TOPIC: {topic}\n"
            f"TALKING POINTS: {points or 'their choice'}\n"
            f"LENGTH: {length_s} seconds ({max(1, length_s // 10)} segments)")


def default_setup(p: dict) -> dict:
    """Videos made before setups existed: home, go-to outfit."""
    return {"place": "home", "location": p["setting"], "outfit": p["outfit"], "position": "", "light": "",
            "products": []}


def setup_of(plan: dict, p: dict) -> dict:
    return {**default_setup(p), **plan.get("setup", {})} if "setup" in plan else default_setup(p)


def setup_line(setup: dict) -> str:
    bits = [f"Location: {dot(setup['location'])}", f"Wearing {dot(setup['outfit'])}"]
    if setup.get("position"):
        bits.append(f"Position: {dot(setup['position'])}")
    if setup.get("light"):
        bits.append(f"Light: {dot(setup['light'])}")
    return " ".join(bits)


# ---------------------------------------------------------------- opening frame

def opening_views(plan: dict) -> list[str]:
    """The stills a video starts from: 'opening' (its first frame), plus 'look' (the outfit
    on the person) when the opening frame is the empty place."""
    return ["opening", "look"] if fmt_of(plan).get("empty_open") else ["opening"]


def ref_intro(groups: list[tuple[str, int]]) -> str:
    """'Reference images, in order: image 1-3: the person; image 4: the place.'"""
    parts, i = [], 1
    for label, n in groups:
        if n > 0:
            parts.append(f"image {i if n == 1 else f'{i}-{i + n - 1}'}: {label}")
            i += n
    return ("Reference images, in order: " + "; ".join(parts) + ". ") if parts else ""


def product_line(x: dict, where: str) -> str:
    label = prod.ref_label(x)
    if x["use"] == "wear":
        return f"They are wearing {label} exactly as {where}: same colour, fabric, print, cut and fit."
    return (f"They hold {label} in one hand exactly as {where}: same shape, colours, label and logo, "
            f"raised into the frame near their face, the label towards the camera, a natural grip.")


def opening_prompt(p: dict, plan: dict, view: str, groups: list[tuple[str, int]] | None = None,
                   featured: list[dict] | None = None) -> str:
    """`groups`: the reference images in order, as (what, how many)."""
    f, setup = fmt_of(plan), setup_of(plan, p)
    groups = groups or []
    intro = ref_intro(groups)
    place_ref = " The place is the one in its reference image." if any(g[0] == "the place" for g in groups) else ""
    if view == "opening" and f.get("empty_open"):
        return (f"{intro}{f['frame']} Location: {dot(setup['location'])}{place_ref} "
                f"{'Light: ' + dot(setup['light']) if setup.get('light') else ''} {PHOTO_REALISM}")
    same = ("The person is the one in the person's reference images: identical face, hair, skin, features "
            "and build. Ignore the clothes in those images; they wear the outfit described here. ")
    framing = ("A full-length photo of them standing naturally in this outfit, at eye level."
               if view == "look" else f['frame'])
    items = " ".join(product_line(x, "in its reference images") for x in (featured or []))
    return f"{intro}{same}{framing} {look_text(p)} {setup_line(setup)}{place_ref} {items} {PHOTO_REALISM}"


def setup_hash(plan: dict, p: dict) -> str:
    """What the opening frame was painted for; a different hash means it's out of date."""
    key = json.dumps([plan.get("format"), setup_of(plan, p)], sort_keys=True)
    return hashlib.sha1(key.encode()).hexdigest()[:10]


# ---------------------------------------------------------------- video prompts

def segment_prompt(p: dict, plan: dict, seg: dict, refs: list[str], first: bool,
                   has_opening: bool = True, featured: list[dict] | None = None) -> str:
    """The Omni prompt for one segment. First turn: the opening frame is Image1 and the
    identity photos follow as references. Later turns extend the same take."""
    f, setup = fmt_of(plan), setup_of(plan, p)
    said = " ".join(seg["lines"])
    speak = (f'{p["name"]} ({dot(p["voice"])}) says, {f["to"]}: "{said}" '
             f"Delivery: {dot(seg['delivery'])} Action: {dot(seg['action'])}")
    keep = "".join(f"; {prod.ref_label(x)} exactly as before" for x in (featured or []))
    if not first:
        return edit_instruction(
            f"Continue the same continuous take for {seg['seconds']} more seconds: {f['continue']}{keep}, "
            f"no cut. {speak} {NATURAL_DELIVERY}")
    n0 = 2 if has_opening else 1
    decl = " ".join(f"<IMAGE_REF_{i}>@Image{n0 + i}" for i in range(len(refs)))
    header = (f"[# Sources <FIRST_FRAME>@Image1] [# References {decl}]" if has_opening
              else f"[# References {decl}]")
    person = ", ".join(f"<IMAGE_REF_{i}>" for i, r in enumerate(refs) if r in ("face", "three_quarter", "profile", "full_body"))
    lines = [header,
             f"{p['name']} is the person in {person}: match face, hair, skin texture, features and build exactly."]
    if "look" in refs:
        lines.append(f"They wear exactly the outfit in <IMAGE_REF_{refs.index('look')}>.")
    if "place" in refs:
        lines.append(f"The place is the one in <IMAGE_REF_{refs.index('place')}>.")
    for x in featured or []:
        rid = f"product:{x['id']}"
        if rid in refs:
            tag = f"<IMAGE_REF_{refs.index(rid)}>"
            lines.append(f"They wear {prod.ref_label(x)} from {tag}: keep its exact colour, fabric and print."
                         if x["use"] == "wear" else
                         f"{prod.ref_label(x)[0].upper() + prod.ref_label(x)[1:]} is the object in {tag}: keep its "
                         f"exact shape, colours, label and logo whenever it's on screen.")
    if has_opening:
        lines.append("Start from Image1: " + (
            "the empty place; after about a second they walk into frame." if f.get("empty_open")
            else "same person, outfit, place, framing and light."))
    lines += [setup_line(setup), speak, NATURAL_DELIVERY, f["camera"], VIDEO_REALISM,
              "Use the reference images for identity and products only; they must not appear as literal frames.",
              f"Duration {seg['seconds']} seconds. One continuous take, no cuts."]
    return "\n".join(lines)


# ---------------------------------------------------------------- storage

class Influencers:
    def __init__(self, library_root: Path):
        self.root = Path(library_root) / "influencers"
        self.root.mkdir(parents=True, exist_ok=True)
        self.products = prod.Products(library_root)

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

    def create(self, profile: dict, sources: list[Path] | None = None, consent: str = "") -> dict:
        """`sources`: photos of a real person the character is made from; needs `consent`."""
        if sources and not consent:
            raise ValueError("Confirm you have the right to use this person's likeness.")
        base = re.sub(r"[^a-z0-9]+", "_", (profile.get("name") or "creator").lower()).strip("_") or "creator"
        iid, n = base, 2
        while self.dir(iid).exists():
            iid, n = f"{base}_{n}", n + 1
        inf = {"id": iid, "profile": {k: profile.get(k, "") for k in KEYS}, "created": time.time()}
        (self.dir(iid) / "identity").mkdir(parents=True)
        (self.dir(iid) / "videos").mkdir()
        if sources:
            self.add_sources(iid, sources)
            inf["consent"] = {"text": consent, "at": time.time()}
        self.save(inf)
        return inf

    def sources(self, iid: str) -> list[Path]:
        return sorted((self.dir(iid) / "identity" / "sources").glob("*.png"))

    def add_sources(self, iid: str, photos: list[Path]) -> None:
        d = self.dir(iid) / "identity" / "sources"
        d.mkdir(parents=True, exist_ok=True)
        n = max((int(x.stem) for x in d.glob("*.png") if x.stem.isdigit()), default=0)
        for i, src in enumerate(photos, start=n + 1):
            shutil.move(str(src), d / f"{i:02d}.png")

    def remove_source(self, iid: str, name: str) -> None:
        if not re.fullmatch(r"\d+\.png", name):
            raise KeyError(name)
        (self.dir(iid) / "identity" / "sources" / name).unlink(missing_ok=True)

    def featured(self, setup: dict) -> list[dict]:
        """The setup's products that still exist, with how they're used and their images."""
        out = []
        for item in setup.get("products") or []:
            try:
                x = self.products.get(item["id"])
            except KeyError:
                continue
            refs = self.products.refs(x["id"])
            if refs:
                out.append({**x, "use": item.get("use") if item.get("use") in prod.USES else prod.KINDS[x["kind"]],
                            "refs": refs})
        return out

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

    # places: home (the identity pack's setting) plus saved ones
    def places(self, inf: dict) -> list[dict]:
        home = {"id": "home", "name": "Home", "description": inf["profile"]["setting"],
                "image": self.image(inf["id"], "setting")}
        return [home] + [{**pl_, "image": self.dir(inf["id"]) / "places" / f"{pl_['id']}.png"}
                         for pl_ in inf.get("places", [])]

    def place(self, inf: dict, pid: str) -> dict:
        found = next((x for x in self.places(inf) if x["id"] == pid), None)
        if not found:
            raise KeyError(pid)
        return found

    def add_place(self, iid: str, name: str, description: str) -> dict:
        inf = self.get(iid)
        base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "place"
        taken = {x["id"] for x in self.places(inf)}
        pid, n = base, 2
        while pid in taken:
            pid, n = f"{base}_{n}", n + 1
        place = {"id": pid, "name": name.strip(), "description": description.strip()}
        inf.setdefault("places", []).append(place)
        (self.dir(iid) / "places").mkdir(exist_ok=True)
        self.save(inf)
        return place

    def remove_place(self, iid: str, pid: str) -> None:
        inf = self.get(iid)
        if pid == "home" or pid not in {x["id"] for x in inf.get("places", [])}:
            raise KeyError(pid)
        inf["places"] = [x for x in inf["places"] if x["id"] != pid]
        self.save(inf)
        (self.dir(iid) / "places" / f"{pid}.png").unlink(missing_ok=True)

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


def _paint(client, s, lib: Influencers, iid: str, prompt: str, out: Path, refs, aspect: str, what: str,
           proj: pl.Project | None = None) -> None:
    usage = pl.generate_image(client, s, prompt, out, refs=refs, aspect=aspect)
    entry = dict(kind="image", id=what, model=s.image_model, prompt=prompt, image_size=s.image_size,
                 aspect=aspect, usage=usage, cost_usd=pl.call_cost(s.image_model, usage, s.image_size))
    proj.log(**entry) if proj else lib.log(iid, **entry)


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
        sources = lib.sources(iid) if view != "setting" else []
        prompt = inf.get("prompt_overrides", {}).get(view) or identity_prompt(p, view, from_sources=bool(sources))
        refs = ([face] if from_face else []) + sources[:4 if view == "face" else 3]
        try:
            _paint(client, s, lib, iid, prompt, out, refs or None, aspect, f"identity:{view}")
            results[view] = "done"
        except Exception as e:  # noqa: BLE001
            results[view] = ("fatal: " if pl._is_fatal(e) else "failed: ") + pl.friendly_error(e)
        on_progress and on_progress(view, results[view])
        if results[view].startswith("fatal"):
            break
    return results


# ---------------------------------------------------------------- casting

# Each option is nudged to be its own person; all stay within the description.
CAST_NOTES = [
    "",
    "A distinct individual: vary the face shape and jawline within the description.",
    "A distinct individual: vary the eyes, brows and nose within the description.",
    "A distinct individual: vary the lips, smile and cheekbones within the description.",
    "A distinct individual: vary the proportions and overall impression within the description.",
    "A distinct individual: a less conventional, more characterful face within the description.",
]
MAX_CANDIDATES = 24


def casting_dir(lib: Influencers, iid: str) -> Path:
    return lib.dir(iid) / "identity" / "casting"


def casting_prompt(p: dict, k: int, direction: str = "") -> str:
    base = identity_prompt(p, "face")
    note = CAST_NOTES[k % len(CAST_NOTES)]
    extra = f" Direction for this casting: {dot(direction)}" if direction.strip() else ""
    return f"{base} {note}{extra}".strip()


def refine_prompt(p: dict, notes: str) -> str:
    _, _, _, framing = IDENTITY[0]
    return (f"The same person as in the reference photo, with only these changes: {dot(notes)} Keep everything "
            f"else about their face, hair, skin and features identical. {framing} {PHOTO_REALISM}")


def _new_candidate(lib: Influencers, iid: str, entry: dict) -> dict:
    inf = lib.get(iid)
    cast = inf.setdefault("casting", {"candidates": [], "locked": None})
    if len(cast["candidates"]) >= MAX_CANDIDATES:
        raise ProviderError(400, f"Up to {MAX_CANDIDATES} options: delete some first.")
    n = max((int(c["name"].split(".")[0]) for c in cast["candidates"]), default=0) + 1
    return {"name": f"{n:02d}.png", "created": time.time(), **entry}


def _add_candidate(lib: Influencers, iid: str, cand: dict) -> None:
    inf = lib.get(iid)
    inf.setdefault("casting", {"candidates": [], "locked": None})["candidates"].append(cand)
    lib.save(inf)


def cast_faces(client, s: pl.Settings, lib: Influencers, iid: str, count: int, direction: str = "",
               on_progress=None) -> list[str]:
    """Paint `count` face options from the profile. Returns the new candidate names."""
    inf = lib.get(iid)
    if lib.sources(iid):
        raise ProviderError(400, "This character's face comes from their photos.")
    p = inf["profile"]
    casting_dir(lib, iid).mkdir(parents=True, exist_ok=True)
    start = len(inf.get("casting", {}).get("candidates", []))
    made = []
    for i in range(count):
        cand = _new_candidate(lib, iid, {"notes": direction.strip(), "from": None})
        prompt = casting_prompt(p, start + i, direction)
        _paint(client, s, lib, iid, prompt, casting_dir(lib, iid) / cand["name"], None, "3:4", f"casting:{cand['name']}")
        _add_candidate(lib, iid, cand)
        made.append(cand["name"])
        on_progress and on_progress(cand["name"])
    return made


def refine_face(client, s: pl.Settings, lib: Influencers, iid: str, name: str, notes: str) -> str:
    """A variation of one option with the user's notes; the original stays."""
    src = casting_dir(lib, iid) / name
    if not re.fullmatch(r"\d+\.png", name) or not src.exists():
        raise KeyError(name)
    if not notes.strip():
        raise ValueError("Say what to change.")
    cand = _new_candidate(lib, iid, {"notes": notes.strip(), "from": name})
    _paint(client, s, lib, iid, refine_prompt(lib.get(iid)["profile"], notes), casting_dir(lib, iid) / cand["name"],
           [src], "3:4", f"casting:{cand['name']}")
    _add_candidate(lib, iid, cand)
    return cand["name"]


def lock_face(lib: Influencers, iid: str, name: str) -> None:
    """Make an option their face. Views painted from an earlier face become out of date."""
    src = casting_dir(lib, iid) / name
    if not re.fullmatch(r"\d+\.png", name) or not src.exists():
        raise KeyError(name)
    shutil.copy2(src, lib.image(iid, "face"))
    lib.image(iid, "face").touch()                     # newer than the views painted from the old face
    inf = lib.get(iid)
    inf.setdefault("casting", {"candidates": [], "locked": None})["locked"] = name
    inf.get("identity_errors", {}).pop("face", None)
    lib.save(inf)


def remove_candidate(lib: Influencers, iid: str, name: str) -> None:
    inf = lib.get(iid)
    cast = inf.get("casting", {"candidates": [], "locked": None})
    if name not in {c["name"] for c in cast["candidates"]}:
        raise KeyError(name)
    cast["candidates"] = [c for c in cast["candidates"] if c["name"] != name]
    if cast.get("locked") == name:
        cast["locked"] = None
    inf["casting"] = cast
    lib.save(inf)
    (casting_dir(lib, iid) / name).unlink(missing_ok=True)


def stale_views(lib: Influencers, iid: str) -> list[str]:
    """Views painted from the face that are older than the current face."""
    face = lib.image(iid, "face")
    if not face.exists():
        return []
    t = face.stat().st_mtime
    return [v for v, _, from_face, _ in IDENTITY
            if from_face and lib.image(iid, v).exists() and lib.image(iid, v).stat().st_mtime < t]


def paint_place(client, s: pl.Settings, lib: Influencers, iid: str, pid: str) -> None:
    place = lib.place(lib.get(iid), pid)
    if pid == "home":
        paint_identity(client, s, lib, iid, views=["setting"], force=True)
        return
    _paint(client, s, lib, iid, place_prompt(place["description"]), place["image"], None, "9:16", f"place:{pid}")


def write_script(client, s: pl.Settings, lib: Influencers, iid: str, fmt: str, topic: str,
                 points: str, length_s: int, place: str = "", location: str = "", outfit: str = "",
                 products: list[dict] | None = None) -> pl.Project:
    """Draft a video: its setup and the script in the creator's voice, as a new video folder.
    `place` (a saved place id), `location` and `outfit` are hints the AI keeps; `products`
    ([{id, use}]) are worn or held in it."""
    inf = lib.get(iid)
    p = inf["profile"]
    if fmt not in FORMATS:
        raise ValueError(f"Unknown format {fmt}")
    length_s = max(10, min(40, round(length_s / 10) * 10))
    hints = {"outfit": outfit.strip()}
    if place:
        pl_ = lib.place(inf, place)
        hints["location"] = f"{pl_['name']}: {pl_['description']}"
    elif location.strip():
        hints["location"] = location.strip()
    items = [{"id": x["id"], "use": x.get("use", "")} for x in (products or [])][:2]
    featured = lib.featured({"products": items})
    worn = [prod.ref_label(x) for x in featured if x["use"] == "wear"]
    if worn:
        hints["must wear"] = ", ".join(worn)
    reel, usage = pl._json_call(client, s, SCRIPT_SYSTEM,
                                script_prompt(p, fmt, topic, points, length_s, hints, featured),
                                REEL_SCHEMA, "script")
    reel["segments"] = normalize_segments(reel["segments"], length_s)
    setup = {k: str(reel.get("setup", {}).get(k, "")).strip() for k in SETUP_KEYS}
    setup.update({k: v for k, v in hints.items() if v and k in SETUP_KEYS and k != "location"})
    missing = [w for w in worn if w.lower() not in setup["outfit"].lower()]
    if missing:
        setup["outfit"] = ", ".join(missing) + (f", with {setup['outfit']}" if setup["outfit"] else "")
    setup["products"] = [{"id": x["id"], "use": x["use"]} for x in featured]
    if place:
        setup["location"] = lib.place(inf, place)["description"]
    elif hints.get("location"):
        setup["location"] = hints["location"]
    setup["place"] = place or ""
    reel["setup"] = setup
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


# ---------------------------------------------------------------- opening frames

def opening_path(proj: pl.Project, view: str = "opening") -> Path:
    return proj.asset_path(view)


def opening_ok(lib: Influencers, iid: str, proj: pl.Project) -> bool:
    """Every still this video starts from exists and matches its current setup."""
    plan, p = proj.load_plan(), lib.get(iid)["profile"]
    return (plan.get("opening_for") == setup_hash(plan, p)
            and all(opening_path(proj, v).exists() for v in opening_views(plan)))


def paint_opening(client, s: pl.Settings, lib: Influencers, iid: str, proj: pl.Project,
                  on_progress=None) -> None:
    """Paint the still(s) a video starts from, from the identity pack and the saved place."""
    inf, plan = lib.get(iid), proj.load_plan()
    p = inf["profile"]
    if not lib.image(iid, "face").exists():
        raise ProviderError(400, "Paint the influencer's identity pack first (at least the face).")
    setup = setup_of(plan, p)
    place_img = None
    if setup.get("place"):
        try:
            img = lib.place(inf, setup["place"])["image"]
            place_img = img if img.exists() else None
        except KeyError:
            pass
    person = [lib.image(iid, v) for v in ("face", "three_quarter", "full_body") if lib.image(iid, v).exists()]
    featured = lib.featured(setup)
    overrides = plan.get("prompt_overrides", {})
    for view in opening_views(plan):
        empty = view == "opening" and fmt_of(plan).get("empty_open")
        groups, refs = [], []
        if not empty:
            groups.append(("the person", len(person)))
            refs += person
        if place_img and view == "opening":
            groups.append(("the place", 1))
            refs.append(place_img)
        items = [] if empty else featured
        for x in items:
            groups.append((prod.ref_label(x), len(x["refs"])))
            refs += x["refs"]
        prompt = overrides.get(view) or opening_prompt(p, plan, view, groups, items)
        on_progress and on_progress(view)
        _paint(client, s, lib, iid, prompt, opening_path(proj, view), refs or None, "9:16", view, proj=proj)
    plan = proj.load_plan()
    plan["opening_for"] = setup_hash(plan, p)
    proj.save_plan(plan)


# ---------------------------------------------------------------- shooting

def reel_shot(lib: Influencers, iid: str, proj: pl.Project, plan: dict, seg: dict, resolution: str) -> Shot:
    """First turn: the opening frame as Image1, then identity photos (+ the outfit look for
    walk-ins). Videos without an opening frame fall back to the identity pack and home."""
    has_opening = opening_path(proj).exists()
    views = ["face", "three_quarter", "profile"] + ([] if has_opening else ["setting"])
    refs = [Ref(id="place" if v == "setting" else v, kind="environment" if v == "setting" else "character",
                name=v, path=lib.image(iid, v)) for v in views if lib.image(iid, v).exists()]
    if has_opening and fmt_of(plan).get("empty_open") and opening_path(proj, "look").exists():
        refs.append(Ref(id="look", kind="character", name="look", path=opening_path(proj, "look")))
    for x in lib.featured(setup_of(plan, lib.get(iid)["profile"])):
        refs.append(Ref(id=f"product:{x['id']}", kind="prop", name=x["name"], path=x["refs"][0]))
    return Shot(plan=plan, scene=seg, refs=refs, first_frame=opening_path(proj) if has_opening else None,
                aspect="9:16", resolution=resolution, duration_s=seg["seconds"])


def shoot_reel(client, s: pl.Settings, lib: Influencers, iid: str, proj: pl.Project,
               log=print, step=None) -> Path:
    """Paint the opening frame if it's missing or out of date, then one continuous take:
    generate the first segment, extend it segment by segment, save it as final.mp4.
    Every turn is kept as a take with its prompt and cost."""
    step = step or (lambda *a: None)
    inf, plan = lib.get(iid), proj.load_plan()
    p, segs = inf["profile"], plan["segments"]
    vp = providers.video_provider("gemini-omni", s, client)
    if not lib.image(iid, "face").exists():
        raise ProviderError(400, "Paint the influencer's identity pack first (at least the face).")
    if sum(sg["seconds"] for sg in segs) > vp.MAX_EXTENDED_S:
        raise ProviderError(400, f"Reels can be at most {vp.MAX_EXTENDED_S} s.")
    if not opening_ok(lib, iid, proj):
        step("image", "Painting the opening frame", 0, len(segs))
        paint_opening(client, s, lib, iid, proj)
        log("Opening frame painted")
        plan = proj.load_plan()
    overrides = plan.get("prompt_overrides", {})
    featured = lib.featured(setup_of(plan, p))
    meta, turns = None, []
    for i, seg in enumerate(segs, start=1):
        step("video", f"{'Shooting' if i == 1 else 'Extending'} · segment {i} of {len(segs)}", i - 1, len(segs))
        if i == 1:
            shot = reel_shot(lib, iid, proj, plan, seg, vp.resolution_for(s.resolution))
            prompt = overrides.get(seg["id"]) or segment_prompt(
                p, plan, seg, [r.id for r in shot.refs], first=True, has_opening=bool(shot.first_frame),
                featured=featured)
            submit = (lambda sh, pr: lambda: vp.submit(sh, pr))(shot, prompt)
            info = {"refs": [r.id for r in shot.refs], "first_frame": bool(shot.first_frame),
                    "format": {"type": "video", "aspect_ratio": "9:16", "resolution": shot.resolution}}
        else:
            prompt = overrides.get(seg["id"]) or segment_prompt(p, plan, seg, [], first=False, featured=featured)
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


def estimate_usd(s: pl.Settings, plan: dict, needs_opening: bool) -> dict:
    """Omni returns the whole take on each extension but bills output only for the new
    seconds (measured 2026-09-26); each extension also re-reads the take so far as input."""
    secs = [sg["seconds"] for sg in plan["segments"]]
    vp = providers.video_provider("gemini-omni", s)
    res = vp.resolution_for(s.resolution)
    video = vp.price_per_s(res) * sum(secs)
    tok_s = s.VIDEO_TOKENS_PER_S.get(res, 0)
    in_rate = s.PRICES.get(vp.model, {}).get("input", 0)
    reread = sum(sum(secs[:i]) for i in range(1, len(secs))) * tok_s * in_rate / 1e6
    images = pl.estimate_image_usd(s, len(opening_views(plan))) if needs_opening else 0.0
    return {"seconds": sum(secs), "turns": len(secs), "resolution": res,
            "video_usd": round(video + reread, 2), "images_usd": round(images, 2),
            "usd": round(video + reread + images, 2)}


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
