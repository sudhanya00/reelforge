"""
ReelForge core pipeline.

  idea/story  --(Gemini 3.1 Pro)-->  production bible (plan.json)
  plan        --(Nano Banana Pro)-->  character / prop / environment reference images
  plan+refs   --(Gemini Omni Flash)--> one clip per scene, multiple takes
  takes       --(ffmpeg)-->           final.mp4

Every call is logged to <project>/log.jsonl so any clip can be traced back to
the exact prompt + references that produced it.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import google.auth
from dotenv import load_dotenv
from google import genai
from google.genai import types

# GEMINI_API_KEY etc. from a .env next to this file; real env vars take precedence
load_dotenv(Path(__file__).with_name(".env"))

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


@dataclass
class Settings:
    # Default model ids per backend (the same model can have a different id on each).
    # Vertex ids checked against models.list(query_base=True) on 2026-09-25; models.get
    # also "finds" catalog-only ids that 404 when called, so don't trust it for this.
    MODELS: ClassVar[dict[str, dict[str, str]]] = {
        "gemini": {"planner_model": "gemini-3.1-pro-preview",
                   "image_model": "gemini-3-pro-image-preview",      # Nano Banana Pro
                   "video_model": "gemini-omni-1.1-flash"},
        "vertex": {"planner_model": "gemini-3.1-pro-preview",
                   "image_model": "gemini-3-pro-image",              # GA id on Vertex
                   "video_model": "gemini-omni-1.1-flash-preview"},
    }
    planner_model: str = ""                              # "" = backend default
    image_model: str = ""
    video_model: str = ""
    orientation: str = "9:16"                            # "9:16" | "16:9"
    resolution: str = "720p"                             # 360p | 720p | 1080p | 4k
    image_size: str = "2K"                               # 1K | 2K | 4K
    video_timeout_s: int = 900
    # "gemini" = AI Studio key (GEMINI_API_KEY); "vertex" = bills a GCP project,
    # so GCP credits apply. Defaults come from the standard google-genai env vars.
    backend: str = field(default_factory=lambda: "vertex" if _env_bool("GOOGLE_GENAI_USE_VERTEXAI") else "gemini")
    gcp_project: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    gcp_location: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLOUD_LOCATION", "global"))

    def __post_init__(self):
        for k, v in self.MODELS[self.backend].items():
            if not getattr(self, k):
                setattr(self, k, v)


def make_client(s: Settings, api_key: str | None = None) -> genai.Client:
    """Explicit args everywhere so env vars for one backend never leak into the other."""
    if s.backend == "vertex":
        key = api_key or os.environ.get("VERTEX_API_KEY")
        if key:                                   # Vertex express mode (key bound to a project)
            return genai.Client(vertexai=True, api_key=key)
        if not s.gcp_project:
            raise ValueError("Vertex backend needs GOOGLE_CLOUD_PROJECT (or a VERTEX_API_KEY).")
        # Application Default Credentials (`gcloud auth application-default login`).
        # Pin the quota project to the billed project; otherwise google.auth falls back
        # to whatever project the gcloud CLI config happens to point at.
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"],
                                       quota_project_id=s.gcp_project)
        return genai.Client(vertexai=True, project=s.gcp_project, location=s.gcp_location,
                            credentials=creds)
    return genai.Client(vertexai=False, api_key=api_key or os.environ.get("GEMINI_API_KEY"))


# --------------------------------------------------------------------------
# Project folder helpers
# --------------------------------------------------------------------------

class Project:
    def __init__(self, root: Path):
        self.root = Path(root)
        for sub in ("assets", "scenes", "frames"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    @classmethod
    def new(cls, base: Path, title: str) -> "Project":
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "untitled"
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        return cls(Path(base) / f"{stamp}-{slug}")

    # plan
    @property
    def plan_path(self) -> Path:
        return self.root / "plan.json"

    def load_plan(self) -> dict:
        return json.loads(self.plan_path.read_text(encoding="utf-8"))

    def save_plan(self, plan: dict) -> None:
        self.plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")

    # paths
    def asset_path(self, asset_id: str) -> Path:
        return self.root / "assets" / f"{asset_id}.png"

    def scene_dir(self, scene_id: str) -> Path:
        d = self.root / "scenes" / scene_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def takes(self, scene_id: str) -> list[Path]:
        return sorted(self.scene_dir(scene_id).glob("take_*.mp4"))

    def next_take_path(self, scene_id: str) -> Path:
        return self.scene_dir(scene_id) / f"take_{len(self.takes(scene_id)) + 1:02d}.mp4"

    # log
    def log(self, **entry) -> None:
        entry["ts"] = datetime.now().isoformat(timespec="seconds")
        with open(self.root / "log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# 1. Planning  (Gemini 3.1 Pro -> production bible)
# --------------------------------------------------------------------------

PLAN_SCHEMA = {
    "type": "object",
    "required": ["title", "logline", "style", "characters", "props", "environments", "scenes"],
    "properties": {
        "title": {"type": "string"},
        "logline": {"type": "string"},
        "style": {
            "type": "object",
            "required": ["look", "color_grade", "lens", "avoid"],
            "properties": {
                "look": {"type": "string"},
                "color_grade": {"type": "string"},
                "lens": {"type": "string"},
                "avoid": {"type": "string"},
            },
        },
        "characters": {"type": "array", "items": {
            "type": "object",
            "required": ["id", "name", "appearance", "costume", "voice"],
            "properties": {
                "id": {"type": "string"}, "name": {"type": "string"},
                "appearance": {"type": "string"}, "costume": {"type": "string"},
                "voice": {"type": "string"},
            }}},
        "props": {"type": "array", "items": {
            "type": "object",
            "required": ["id", "name", "description"],
            "properties": {
                "id": {"type": "string"}, "name": {"type": "string"},
                "description": {"type": "string"},
            }}},
        "environments": {"type": "array", "items": {
            "type": "object",
            "required": ["id", "name", "description", "time_and_weather", "lighting"],
            "properties": {
                "id": {"type": "string"}, "name": {"type": "string"},
                "description": {"type": "string"},
                "time_and_weather": {"type": "string"},
                "lighting": {"type": "string"},
                "based_on": {"type": "string", "description": "id of another environment this is a variant of (same place, different time/weather), or empty"},
            }}},
        "scenes": {"type": "array", "items": {
            "type": "object",
            "required": ["id", "duration_s", "refs", "shot", "action", "camera", "lighting", "audio", "continuity"],
            "properties": {
                "id": {"type": "string"},
                "duration_s": {"type": "integer"},
                "refs": {"type": "array", "items": {"type": "string"},
                         "description": "ids of characters, props and ONE environment visible in this shot"},
                "shot": {"type": "string"},
                "action": {"type": "string"},
                "camera": {"type": "string"},
                "lighting": {"type": "string"},
                "dialogue": {"type": "array", "items": {
                    "type": "object", "required": ["speaker", "line"],
                    "properties": {"speaker": {"type": "string"}, "line": {"type": "string"}}}},
                "audio": {"type": "string"},
                "continuity": {"type": "string", "enum": ["cut", "continuous"],
                               "description": "continuous = starts on the last frame of the previous scene"},
            }}},
    },
}

PLANNER_SYSTEM = """You are a film director and AI-video production designer.
Turn the user's idea into a production bible for an AI video pipeline where:
- each scene is ONE clip of at most 10 seconds (prefer 6-8s);
- every character, recurring prop and location gets a reference image first;
- clips are generated separately and edited together.

Rules that make AI clips succeed:
- ONE clear action per scene. Never chain 3 actions in one clip.
- ONE simple camera move per scene (static, slow push-in, slow pan, gentle handheld).
- Avoid object hand-offs between characters, eating, pouring on camera, fast hand
  choreography. Start the shot with the object already in hand instead.
- Dialogue: at most 1-2 short lines per scene, and only where it matters.
- Use 'continuous' only when the next shot must physically continue the previous
  one (same framing, same moment). Otherwise 'cut'.
- Every scene's refs must list the ONE environment id plus every character/prop visible.
- Environment variants of the same place (night/morning) use based_on.
- Ids: short snake_case like char_tsering, env_pass_night, prop_bike, s01.
- Descriptions must be concrete and visual: age, build, face, hair, exact colours
  and materials of clothing, textures, light sources. No vague adjectives.
- Keep the whole story within the requested scene count."""


def plan_story(client: genai.Client, s: Settings, story: str, style: str,
               n_scenes: int = 6) -> dict:
    prompt = (
        f"STORY / IDEA:\n{story}\n\n"
        f"VISUAL STYLE:\n{style or 'director’s choice, cinematic and photorealistic'}\n\n"
        f"ORIENTATION: {s.orientation}\n"
        f"TARGET SCENE COUNT: about {n_scenes}\n"
    )
    resp = client.models.generate_content(
        model=s.planner_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=PLANNER_SYSTEM,
            response_mime_type="application/json",
            response_json_schema=PLAN_SCHEMA,
        ),
    )
    plan = json.loads(resp.text)
    plan["orientation"] = s.orientation
    return plan


# --------------------------------------------------------------------------
# 2. Prompt assembly (deterministic, so the look never drifts)
# --------------------------------------------------------------------------

def _dot(text: str) -> str:
    """Planner fields may or may not end with a period; end with exactly one."""
    return text.strip().rstrip(".") + "."


def style_line(plan: dict) -> str:
    st = plan["style"]
    return (f"Style: {_dot(st['look'])} Colour grade: {_dot(st['color_grade'])} "
            f"Lens: {_dot(st['lens'])} Avoid: {_dot(st['avoid'])}")


def character_sheet_prompt(plan: dict, c: dict) -> str:
    return (
        f"Character reference sheet of {c['name']}. {_dot(c['appearance'])} "
        f"Costume: {_dot(c['costume'])} "
        "Four views side by side on one canvas: front, three-quarter left, profile, "
        "three-quarter back. Full body, identical outfit and hair in every view. "
        "Plain neutral light-grey studio backdrop, soft even light, no shadows on backdrop. "
        "No text, no labels, no captions. "
        + style_line(plan)
    )


def prop_sheet_prompt(plan: dict, p: dict) -> str:
    return (
        f"Prop reference sheet: {p['name']}. {_dot(p['description'])} "
        "Side view and three-quarter front view on one canvas, plain neutral light-grey backdrop. "
        "No logos, no brand text, no labels. " + style_line(plan)
    )


def env_plate_prompt(plan: dict, e: dict, has_base: bool) -> str:
    base = ("Same location, same geography, same structures and camera framing as the "
            "reference image; change only time of day, weather and lighting as described. "
            if has_base else "")
    return (
        f"Environment plate, no people: {e['name']}. {_dot(e['description'])} "
        f"Time and weather: {_dot(e['time_and_weather'])} Lighting: {_dot(e['lighting'])} "
        f"Wide establishing view, eye level. {base}No text, no signs with words. "
        + style_line(plan)
    )


def _lookup(plan: dict) -> dict[str, tuple[str, dict]]:
    idx = {}
    for kind in ("characters", "props", "environments"):
        for item in plan.get(kind, []):
            idx[item["id"]] = (kind, item)
    return idx


def scene_prompt(plan: dict, scene: dict, ref_ids: list[str], first_frame: bool) -> str:
    """Build the Omni prompt. ref_ids are in the same order as the images we attach."""
    idx = _lookup(plan)
    header, bind = [], []

    img_n = 1
    if first_frame:
        header.append("[# Sources <FIRST_FRAME>@Image1]")
        img_n = 2
    refs_decl = []
    for i, rid in enumerate(ref_ids):
        refs_decl.append(f"<IMAGE_REF_{i}>@Image{img_n + i}")
        kind, item = idx[rid]
        if kind == "characters":
            bind.append(f"{item['name']} is the person shown in <IMAGE_REF_{i}> "
                        f"(match face, hair and costume exactly).")
        elif kind == "props":
            bind.append(f"The {item['name']} is the object in <IMAGE_REF_{i}>.")
        else:
            bind.append(f"The setting is the location in <IMAGE_REF_{i}> "
                        f"({item['time_and_weather']}).")
    if refs_decl:
        header.append("[# References " + " ".join(refs_decl) + "]")

    dialogue = scene.get("dialogue") or []
    if dialogue:
        voices = {c["name"]: c["voice"] for c in plan["characters"]}
        lines = " ".join(
            f'{d["speaker"]} ({voices.get(d["speaker"], "natural voice")}) says: "{d["line"]}"'
            for d in dialogue)
        dia = f"Dialogue: {lines}"
    else:
        dia = "No dialogue."

    body = [
        " ".join(header),
        " ".join(bind),
        f"Shot: {_dot(scene['shot'])}",
        f"Action: {_dot(scene['action'])}",
        f"Camera: {_dot(scene['camera'])}",
        f"Lighting: {_dot(scene['lighting'])}",
        dia,
        f"Sound design: {_dot(scene['audio'])} No background music unless described.",
        style_line(plan),
        f"Duration about {scene['duration_s']} seconds. Single continuous shot, no scene cuts.",
    ]
    tail = []
    if first_frame:
        tail.append("Use Image1 as the starting frame.")
    if refs_decl:
        tail.append("Use the reference images for identity and setting only; "
                    "they must not appear as literal frames.")
    return "\n".join([b for b in body if b] + tail)


# --------------------------------------------------------------------------
# 3. Reference images  (Nano Banana Pro)
# --------------------------------------------------------------------------

def _img_part(path: Path) -> types.Part:
    return types.Part.from_bytes(data=path.read_bytes(), mime_type="image/png")


def generate_image(client: genai.Client, s: Settings, prompt: str, out: Path,
                   refs: list[Path] | None = None, aspect: str | None = None) -> Path:
    contents = [_img_part(p) for p in (refs or [])] + [prompt]
    resp = client.models.generate_content(
        model=s.image_model,
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=aspect or s.orientation,
                                           image_size=s.image_size),
        ),
    )
    for part in resp.candidates[0].content.parts:
        if part.inline_data and part.inline_data.data:
            out.write_bytes(part.inline_data.data)
            return out
    raise RuntimeError(f"No image returned for {out.name}: {resp.text!r}")


def asset_jobs(plan: dict) -> list[dict]:
    """All reference images to make, with their prompts. Base environments first."""
    # sheets are wide (side-by-side views); plates match the film so Omni can frame from them
    sheet, plate = "16:9", plan.get("orientation", "16:9")
    jobs = []
    for c in plan["characters"]:
        jobs.append({"id": c["id"], "prompt": character_sheet_prompt(plan, c), "base": None,
                     "aspect": sheet})
    for p in plan.get("props", []):
        jobs.append({"id": p["id"], "prompt": prop_sheet_prompt(plan, p), "base": None,
                     "aspect": sheet})
    envs = plan["environments"]
    for e in sorted(envs, key=lambda e: bool(e.get("based_on"))):
        base = e.get("based_on") or None
        jobs.append({"id": e["id"], "prompt": env_plate_prompt(plan, e, bool(base)), "base": base,
                     "aspect": plate})
    # user overrides stored in plan win
    overrides = plan.get("prompt_overrides", {})
    for j in jobs:
        j["prompt"] = overrides.get(j["id"], j["prompt"])
    return jobs


def generate_assets(client, s: Settings, proj: Project, only: list[str] | None = None,
                    skip_existing: bool = True, on_progress=None) -> None:
    plan = proj.load_plan()
    jobs = [j for j in asset_jobs(plan) if not only or j["id"] in only]

    def run(job):
        out = proj.asset_path(job["id"])
        if skip_existing and out.exists() and not only:
            return job["id"], "skipped"
        refs = [proj.asset_path(job["base"])] if job["base"] else None
        generate_image(client, s, job["prompt"], out, refs=refs, aspect=job["aspect"])
        proj.log(kind="image", id=job["id"], model=s.image_model, prompt=job["prompt"],
                 refs=[job["base"]] if job["base"] else [])
        return job["id"], "done"

    independent = [j for j in jobs if not j["base"]]
    dependent = [j for j in jobs if j["base"]]
    with ThreadPoolExecutor(max_workers=4) as ex:
        for jid, status in ex.map(run, independent):
            on_progress and on_progress(jid, status)
    for j in dependent:                      # need their base plate first
        jid, status = run(j)
        on_progress and on_progress(jid, status)


# --------------------------------------------------------------------------
# 4. Video clips  (Gemini Omni Flash)
# --------------------------------------------------------------------------

def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def _await_interaction(client, interaction, timeout_s: int):
    """create() normally returns a finished interaction, but may hand back a queued one."""
    deadline = time.time() + timeout_s
    while interaction.status in ("queued", "in_progress"):
        if time.time() > deadline:
            raise TimeoutError(f"Interaction {interaction.id} still {interaction.status} "
                               f"after {timeout_s}s; fetch it later with interactions.get")
        time.sleep(5)
        interaction = client.interactions.get(interaction.id)
    return interaction


def _save_video(client, interaction, out: Path) -> None:
    vid = interaction.output_video
    if vid is None:
        raise RuntimeError(f"No video in response (status={interaction.status}, "
                           f"errors={getattr(interaction, 'errors', None)})")
    if getattr(vid, "data", None):
        out.write_bytes(base64.b64decode(vid.data))
        return
    if (vid.uri or "").startswith("gs://"):
        raise NotImplementedError(f"Video was delivered to Cloud Storage ({vid.uri}); "
                                  "GCS download isn't implemented yet. Use 360p/720p on Vertex.")
    m = re.search(r"files/([A-Za-z0-9_-]+)", vid.uri or "")
    if not m:
        raise RuntimeError("Video returned without data or a usable uri")
    name = f"files/{m.group(1)}"
    while True:
        state = client.files.get(name=name).state.name
        if state == "ACTIVE":
            break
        if state == "FAILED":
            raise RuntimeError("Video processing failed on the server")
        time.sleep(5)
    out.write_bytes(client.files.download(file=vid.uri))


def extract_last_frame(video: Path, out: Path) -> Path | None:
    if not shutil.which("ffmpeg"):
        return None
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.1", "-i", str(video),
                    "-frames:v", "1", str(out)], check=True)
    return out if out.exists() else None


def selected_take(plan: dict, proj: Project, scene_id: str) -> Path | None:
    sel = plan.get("selected_takes", {}).get(scene_id)
    if sel and (proj.scene_dir(scene_id) / sel).exists():
        return proj.scene_dir(scene_id) / sel
    takes = proj.takes(scene_id)
    return takes[-1] if takes else None


def build_scene_request(plan: dict, proj: Project, scene: dict) -> tuple[str, list[dict], list[str]]:
    """Returns (prompt, input_parts, ref_ids_used)."""
    idx = _lookup(plan)
    # environments first, then characters, then props; skip refs with no image yet
    order = {"environments": 0, "characters": 1, "props": 2}
    ref_ids = sorted([r for r in scene["refs"] if r in idx and proj.asset_path(r).exists()],
                     key=lambda r: order[idx[r][0]])

    first_frame_img = None
    if scene.get("continuity") == "continuous":
        ids = [sc["id"] for sc in plan["scenes"]]
        i = ids.index(scene["id"])
        if i > 0:
            prev = selected_take(plan, proj, ids[i - 1])
            if prev:
                first_frame_img = extract_last_frame(prev, proj.root / "frames" / f"{scene['id']}_first.png")

    prompt = plan.get("prompt_overrides", {}).get(scene["id"]) or \
        scene_prompt(plan, scene, ref_ids, first_frame=bool(first_frame_img))

    parts = []
    if first_frame_img:
        parts.append({"type": "image", "data": _b64(first_frame_img), "mime_type": "image/png"})
    for r in ref_ids:
        parts.append({"type": "image", "data": _b64(proj.asset_path(r)), "mime_type": "image/png"})
    parts.append({"type": "text", "text": prompt})
    return prompt, parts, ref_ids


def generate_take(client, s: Settings, proj: Project, scene_id: str) -> Path:
    plan = proj.load_plan()
    scene = next(sc for sc in plan["scenes"] if sc["id"] == scene_id)
    prompt, parts, ref_ids = build_scene_request(plan, proj, scene)

    fmt = {"type": "video", "aspect_ratio": plan.get("orientation", s.orientation),
           "resolution": s.resolution}
    if s.resolution in ("1080p", "4k"):
        fmt["delivery"] = "uri"

    interaction = client.interactions.create(
        model=s.video_model, input=parts, response_format=fmt, timeout=s.video_timeout_s)
    # record the id before anything else can fail, so a paid clip is always recoverable
    proj.log(kind="video_submitted", scene=scene_id, interaction_id=interaction.id,
             status=interaction.status)
    interaction = _await_interaction(client, interaction, s.video_timeout_s)
    out = proj.next_take_path(scene_id)
    _save_video(client, interaction, out)

    meta = {"scene": scene_id, "take": out.name, "interaction_id": interaction.id,
            "prompt": prompt, "refs": ref_ids, "model": s.video_model, "format": fmt}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    proj.log(kind="video", **meta)
    return out


def edit_take(client, s: Settings, proj: Project, scene_id: str, take: Path,
              instruction: str) -> Path:
    """Conversational edit on an existing take; keeps everything else the same."""
    meta = json.loads(take.with_suffix(".json").read_text(encoding="utf-8"))
    text = instruction.strip()
    if "keep everything else" not in text.lower():
        if not text.endswith((".", "!", "?")):
            text += "."
        text += " Keep everything else the same."
    # same format as the source take, so the edit comes back as video at its res/aspect
    interaction = client.interactions.create(
        model=s.video_model, previous_interaction_id=meta["interaction_id"],
        input=text, response_format=meta["format"], timeout=s.video_timeout_s)
    proj.log(kind="video_submitted", scene=scene_id, interaction_id=interaction.id,
             status=interaction.status, edited_from=take.name)
    interaction = _await_interaction(client, interaction, s.video_timeout_s)
    out = proj.next_take_path(scene_id)
    _save_video(client, interaction, out)
    new_meta = {**meta, "take": out.name, "interaction_id": interaction.id,
                "edited_from": take.name, "edit": text}
    out.with_suffix(".json").write_text(json.dumps(new_meta, indent=2, ensure_ascii=False), encoding="utf-8")
    proj.log(kind="video_edit", **new_meta)
    return out


# --------------------------------------------------------------------------
# 5. Stitch
# --------------------------------------------------------------------------

def stitch(proj: Project) -> Path:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found on PATH; install it to stitch clips.")
    plan = proj.load_plan()
    clips = [selected_take(plan, proj, sc["id"]) for sc in plan["scenes"]]
    clips = [c for c in clips if c]
    if not clips:
        raise RuntimeError("No clips to stitch yet.")
    lst = proj.root / "concat.txt"
    # forward slashes + ffmpeg's quote escaping so Windows paths / apostrophes are safe
    esc = lambda p: p.resolve().as_posix().replace("'", "'\\''")
    lst.write_text("".join(f"file '{esc(c)}'\n" for c in clips), encoding="utf-8")
    out = proj.root / "final.mp4"
    # re-encode so clips with slightly different params still join cleanly
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c:v", "libx264", "-crf", "18", "-c:a", "aac", str(out)],
                   check=True)
    return out


# --------------------------------------------------------------------------
# One-shot
# --------------------------------------------------------------------------

def run_all(story: str, style: str, s: Settings, base_dir: Path = Path("projects"),
            n_scenes: int = 6, api_key: str | None = None, log=print) -> Project:
    client = make_client(s, api_key)
    log("Planning…")
    plan = plan_story(client, s, story, style, n_scenes)
    proj = Project.new(base_dir, plan["title"])
    proj.save_plan(plan)
    log(f"Plan saved: {proj.plan_path}")
    log("Generating reference images…")
    generate_assets(client, s, proj, on_progress=lambda i, st: log(f"  {i}: {st}"))
    for sc in plan["scenes"]:
        log(f"Generating {sc['id']}…")
        generate_take(client, s, proj, sc["id"])
    try:
        log(f"Final cut: {stitch(proj)}")
    except RuntimeError as e:
        log(str(e))
    return proj
