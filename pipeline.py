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

import json
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import google.auth
import google.auth.exceptions
from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from google.genai._gaos.errors import GenAiError   # raised by client.interactions.*

import providers
from prompts import dot as _dot, edit_instruction, style_line
from providers import ProviderError, Ref, Shot

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
    # USD list prices from ai.google.dev/gemini-api/docs/pricing (2026-09-25); Vertex assumed
    # the same. Token prices are per 1M; thinking tokens bill at the "thoughts" rate if given,
    # else the output rate. Image models bill per generated image by size.
    PRICES: ClassVar[dict[str, dict]] = {
        "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
        "gemini-3-pro-image-preview": {"input": 2.00, "thoughts": 12.00,
                                       "per_image": {"1K": 0.134, "2K": 0.134, "4K": 0.24}},
        "gemini-3-pro-image": {"input": 2.00, "thoughts": 12.00,
                               "per_image": {"1K": 0.134, "2K": 0.134, "4K": 0.24}},
        "gemini-omni-1.1-flash": {"input": 1.50, "output": 17.50},
        "gemini-omni-1.1-flash-preview": {"input": 1.50, "output": 17.50},
        # kling.ai/document-api/pricing/base/video (2026-09-25); per second of video
        "kling-3.0-omni": {"usd_per_unit": 0.14,
                           "per_s": {"720p": 0.084, "1080p": 0.112, "4k": 0.42},
                           "per_s_audio": {"720p": 0.112, "1080p": 0.14, "4k": 0.42},
                           "per_s_edit": {"720p": 0.126, "1080p": 0.168, "4k": 0.42}},
    }
    # Omni output tokens per second of video. 720p is Google's figure; 360p matched a real
    # take exactly (11,586 tokens / 6 s); 1080p and 4k are from third-party write-ups.
    VIDEO_TOKENS_PER_S: ClassVar[dict[str, int]] = {"360p": 1931, "720p": 5792,
                                                    "1080p": 8688, "4k": 17376}
    planner_model: str = ""                              # "" = backend default
    image_model: str = ""
    video_model: str = ""
    orientation: str = "9:16"                            # "9:16" | "16:9"
    resolution: str = "720p"                             # 360p | 720p | 1080p | 4k
    image_size: str = "2K"                               # 1K | 2K | 4K
    video_timeout_s: int = 900
    # which model shoots scenes by default (a scene can override it); see providers/
    video_provider: str = "gemini-omni"                  # gemini-omni | kling
    image_provider: str = "nano-banana"
    kling_model: str = "kling-3.0-omni"
    kling_audio: bool = True                             # native audio (costs more on Kling)
    max_retries: int = 3                                 # on 429 / 5xx only
    retry_base_s: float = 10.0                           # waits 10s, 30s, 90s
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
# Cost tracking  (usage comes from the API; prices from Settings.PRICES)
# --------------------------------------------------------------------------

def _usage_gc(resp) -> dict:
    u = getattr(resp, "usage_metadata", None)
    return {"input": u.prompt_token_count or 0, "output": u.candidates_token_count or 0,
            "thoughts": u.thoughts_token_count or 0} if u else {}


def call_cost(model: str, usage: dict, image_size: str | None = None) -> float | None:
    """Estimated USD for one call; None if the model has no price or usage is missing."""
    p = Settings.PRICES.get(model)
    if not p or not usage:
        return None
    usd = usage.get("input", 0) * p["input"] / 1e6
    usd += usage.get("thoughts", 0) * p.get("thoughts", p.get("output", 0)) / 1e6
    if "per_image" in p:
        usd += p["per_image"].get(image_size or "2K", 0)
    else:
        usd += usage.get("output", 0) * p["output"] / 1e6
    return round(usd, 4)


def estimate_video_usd(s: Settings, seconds: float, provider: str | None = None,
                       resolution: str | None = None, edit: bool = False) -> float:
    """List price for `seconds` of video from a provider (default: the settings' one).
    For Gemini this is output tokens only; input and thinking add roughly 5-10%."""
    vp = providers.video_provider(provider, s)
    res = vp.resolution_for(resolution or s.resolution)
    return round(vp.price_per_s(res, edit=edit) * seconds, 2)


def estimate_image_usd(s: Settings, n: int = 1) -> float:
    per = Settings.PRICES.get(s.image_model, {}).get("per_image", {})
    return round(n * per.get(s.image_size, 0), 2)


COSTED_KINDS = ("plan", "image", "video", "video_edit", "video_unsaved")


def project_costs(proj: "Project") -> dict:
    """Totals from log.jsonl: {usd, calls, unpriced, video_s, by_kind: {kind: {calls, usd}}}."""
    tot = {"usd": 0.0, "calls": 0, "unpriced": 0, "video_s": 0.0, "by_kind": {}}
    path = proj.root / "log.jsonl"
    if not path.exists():
        return tot
    for line in path.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e.get("kind") not in COSTED_KINDS:
            continue
        k = tot["by_kind"].setdefault(e["kind"], {"calls": 0, "usd": 0.0})
        k["calls"] += 1
        tot["calls"] += 1
        tot["video_s"] += e.get("duration_s") or 0
        if e.get("cost_usd") is None:
            tot["unpriced"] += 1
        else:
            k["usd"] += e["cost_usd"]
            tot["usd"] += e["cost_usd"]
    tot["usd"] = round(tot["usd"], 2)
    return tot


def _http_status(e: Exception) -> int | None:
    if isinstance(e, genai_errors.APIError):          # models.* calls
        return e.code
    if isinstance(e, (GenAiError, ProviderError)):    # interactions.* calls, other providers
        return e.status_code
    return None


# The server rejected these before generating anything, so retrying never pays twice.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _with_retry(fn, s: "Settings", what: str, proj: "Project | None" = None):
    """Call fn(), retrying rate limits / overloads with exponential backoff."""
    for attempt in range(s.max_retries + 1):
        try:
            return fn()
        except Exception as e:
            status = _http_status(e)
            if status not in RETRYABLE_STATUS or attempt == s.max_retries:
                raise
            wait = s.retry_base_s * 3 ** attempt
            if proj:
                proj.log(kind="retry", what=what, status=status, attempt=attempt + 1, wait_s=wait)
            time.sleep(wait)


def _is_fatal(e: Exception) -> bool:
    """Errors that will hit every call (billing, auth, permissions, unknown model): stop the run."""
    return isinstance(e, google.auth.exceptions.GoogleAuthError) or         _http_status(e) in (401, 402, 403, 404)


SAFETY_HINTS = ("safety", "sexual", "violen", "harass", "hate speech", "dangerous content",
                "prohibited", "responsible ai", "usage polic", "content polic", "minor",
                "risk control", "content security")


def _looks_like_safety_block(msg: str) -> bool:
    m = msg.lower()
    return any(h in m for h in SAFETY_HINTS)


def friendly_error(e: Exception) -> str:
    """One-line explanation of a failure, with what to do about it."""
    status = _http_status(e)
    msg = (getattr(e, "message", None) or str(e)).strip()[:300]
    if isinstance(e, google.auth.exceptions.GoogleAuthError):
        return ("Google Cloud credentials are missing or expired. "
                "Run: gcloud auth application-default login")
    if _looks_like_safety_block(msg):
        return f"Blocked by the model's safety filter: {msg}"
    if status == 402 and isinstance(e, ProviderError):
        return f"Out of credits: {msg}"
    if status == 402:
        return ("Billing: this API key's prepaid credits are used up. Top up in AI Studio, "
                "or switch the backend to vertex.")
    if status in (401, 403):
        return (f"Permission denied: {msg} On Vertex, check that the Vertex AI API is enabled "
                "on the project and your account can use it.")
    if status == 404:
        return f"Model or resource not found: {msg} Check the model ids in Settings for this backend."
    if status == 429:
        return "Rate limit or quota exceeded, even after retries. Wait a few minutes and resume."
    if status == 400:
        return f"The request was rejected: {msg}"
    if status and status >= 500:
        return f"Google's servers failed (HTTP {status}) even after retries. Try again shortly."
    return f"{type(e).__name__}: {msg}"


def format_costs(c: dict) -> str:
    pl = lambda n, w: f"{n} {w}" + ("" if n == 1 else "s")
    s = f"${c['usd']:.2f} over {pl(c['calls'], 'call')}, {c['video_s']:.0f}s of video"
    return s + (f" ({pl(c['unpriced'], 'call')} without usage data)" if c["unpriced"] else "")


# --------------------------------------------------------------------------
# Project folder helpers
# --------------------------------------------------------------------------

class Project:
    def __init__(self, root: Path):
        self.root = Path(root)
        for sub in ("assets", "scenes", "frames"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    @classmethod
    def open(cls, root: Path) -> "Project":
        """An existing project; raises instead of creating an empty folder."""
        if not (Path(root) / "plan.json").exists():
            raise FileNotFoundError(f"No plan.json in {root}; not a ReelForge project folder.")
        return cls(root)

    @classmethod
    def new(cls, base: Path, title: str) -> "Project":
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "untitled"
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        root, n = Path(base) / f"{stamp}-{slug}", 2
        while (root / "plan.json").exists():
            root, n = Path(base) / f"{stamp}-{slug}-{n}", n + 1
        return cls(root)

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
    _log_lock = threading.Lock()        # jobs may log from several threads at once

    def log(self, **entry) -> None:
        entry["ts"] = datetime.now().isoformat(timespec="seconds")
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with self._log_lock, open(self.root / "log.jsonl", "a", encoding="utf-8") as f:
            f.write(line)


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
               n_scenes: int = 6) -> tuple[dict, dict]:
    """Returns (plan, usage)."""
    prompt = (
        f"STORY / IDEA:\n{story}\n\n"
        f"VISUAL STYLE:\n{style or 'director’s choice, cinematic and photorealistic'}\n\n"
        f"ORIENTATION: {s.orientation}\n"
        f"TARGET SCENE COUNT: about {n_scenes}\n"
    )
    resp = _with_retry(lambda: client.models.generate_content(
        model=s.planner_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=PLANNER_SYSTEM,
            response_mime_type="application/json",
            response_json_schema=PLAN_SCHEMA,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    ), s, "plan")
    plan = json.loads(resp.text)
    plan["orientation"] = s.orientation
    return plan, _usage_gc(resp)


def new_project(client, s: Settings, story: str, style: str, n_scenes: int = 6,
                base_dir: Path = Path("projects")) -> "Project":
    """Plan the film, create its folder, and log the planning call with its cost."""
    plan, usage = plan_story(client, s, story, style, n_scenes)
    proj = Project.new(base_dir, plan["title"])
    proj.save_plan(plan)
    proj.log(kind="plan", model=s.planner_model, story=story, style=style, n_scenes=n_scenes,
             usage=usage, cost_usd=call_cost(s.planner_model, usage))
    return proj


# --------------------------------------------------------------------------
# 2. Prompt assembly (deterministic, so the look never drifts)
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# 3. Reference images  (Nano Banana Pro)
# --------------------------------------------------------------------------

def generate_image(client: genai.Client, s: Settings, prompt: str, out: Path,
                   refs: list[Path] | None = None, aspect: str | None = None,
                   proj: Project | None = None) -> dict:
    """Writes the image to `out` (always PNG) and returns the call's usage."""
    ip = providers.image_provider(None, s, client)
    try:
        res = _with_retry(lambda: ip.generate(prompt, refs or [], aspect or s.orientation, s.image_size),
                          s, f"image {out.stem}", proj)
    except RuntimeError as e:
        raise RuntimeError(f"{out.stem}: {e}") from e
    out.write_bytes(res.png)
    return res.usage


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
                    skip_existing: bool = True, on_progress=None) -> dict[str, str]:
    """Make reference images. Returns {asset_id: status}, status being one of
    done | skipped | failed: <why> | fatal: <why>. One failure doesn't stop the rest."""
    plan = proj.load_plan()
    jobs = [j for j in asset_jobs(plan) if not only or j["id"] in only]

    def run(job):
        out = proj.asset_path(job["id"])
        if skip_existing and out.exists() and not only:
            return job["id"], "skipped"
        if job["base"] and not proj.asset_path(job["base"]).exists():
            return job["id"], f"failed: its base plate {job['base']} is missing"
        refs = [proj.asset_path(job["base"])] if job["base"] else None
        try:
            usage = generate_image(client, s, job["prompt"], out, refs=refs, aspect=job["aspect"],
                                   proj=proj)
        except Exception as e:
            return job["id"], ("fatal: " if _is_fatal(e) else "failed: ") + friendly_error(e)
        proj.log(kind="image", id=job["id"], model=s.image_model, prompt=job["prompt"],
                 refs=[job["base"]] if job["base"] else [], image_size=s.image_size,
                 aspect=job["aspect"], usage=usage,
                 cost_usd=call_cost(s.image_model, usage, s.image_size))
        return job["id"], "done"

    results = {}
    independent = [j for j in jobs if not j["base"]]
    dependent = [j for j in jobs if j["base"]]
    with ThreadPoolExecutor(max_workers=4) as ex:
        for jid, status in ex.map(run, independent):
            results[jid] = status
            on_progress and on_progress(jid, status)
    for j in dependent:                      # need their base plate first
        jid, status = run(j)
        results[jid] = status
        on_progress and on_progress(jid, status)
    return results


# --------------------------------------------------------------------------
# 4. Video clips  (Gemini Omni Flash)
# --------------------------------------------------------------------------

def video_duration(path: Path) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return round(float(r.stdout.strip()), 2)
    except ValueError:
        return None


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


def previous_take(plan: dict, proj: Project, scene: dict) -> Path | None:
    """For a continuous scene: the previous scene's selected take, whose last frame starts it."""
    if scene.get("continuity") != "continuous":
        return None
    ids = [sc["id"] for sc in plan["scenes"]]
    i = ids.index(scene["id"])
    return selected_take(plan, proj, ids[i - 1]) if i > 0 else None


def scene_provider(plan: dict, scene_id: str, s: Settings) -> str:
    """Which video model shoots this scene: its own choice, else the settings default."""
    return plan.get("video_providers", {}).get(scene_id) or s.video_provider


def prompt_key(scene_id: str, provider_id: str) -> str:
    """Prompt overrides are per provider (each model has its own prompt syntax).
    The default provider keeps the plain scene id, as before providers existed."""
    return scene_id if provider_id == providers.DEFAULT_VIDEO else f"{scene_id}@{provider_id}"


def build_shot(plan: dict, proj: Project, scene: dict, s: Settings, client=None,
               extract: bool = True, provider: str | None = None):
    """Returns (video_provider, shot, prompt). extract=False is a cheap preview for UIs:
    no ffmpeg frame extraction (the first frame is assumed if one would be used)."""
    vp = providers.video_provider(provider or scene_provider(plan, scene["id"], s), s, client)
    idx = _lookup(plan)
    # environments first, then characters, then props; skip refs with no image yet
    order = {"environments": 0, "characters": 1, "props": 2}
    ref_ids = sorted([r for r in scene["refs"] if r in idx and proj.asset_path(r).exists()],
                     key=lambda r: order[idx[r][0]])[: vp.caps.max_refs]
    refs = [Ref(id=r, kind=idx[r][0][:-1], name=idx[r][1]["name"],
                path=proj.asset_path(r), note=idx[r][1].get("time_and_weather", ""))
            for r in ref_ids]

    prev = previous_take(plan, proj, scene) if vp.caps.first_frame else None
    first = None
    if prev and extract:
        first = extract_last_frame(prev, proj.root / "frames" / f"{scene['id']}_first.png")
    elif prev and shutil.which("ffmpeg"):
        first = proj.root / "frames" / f"{scene['id']}_first.png"   # preview: assume it will exist

    shot = Shot(plan=plan, scene=scene, refs=refs, first_frame=first,
                aspect=plan.get("orientation", s.orientation),
                resolution=vp.resolution_for(s.resolution), duration_s=vp.duration_for(scene["duration_s"]))
    prompt = plan.get("prompt_overrides", {}).get(prompt_key(scene["id"], vp.id)) or vp.build_prompt(shot)
    return vp, shot, prompt


def build_scene_request(plan: dict, proj: Project, scene: dict, s: Settings | None = None,
                        extract: bool = False) -> tuple[str, list[dict], list[str]]:
    """Preview of what would be sent: (prompt, [], ref_ids)."""
    _, shot, prompt = build_shot(plan, proj, scene, s or Settings(), extract=extract)
    return prompt, [], [r.id for r in shot.refs]


def _shoot(vp, s: Settings, proj: Project, scene_id: str, submit, meta: dict, kind: str) -> Path:
    """Submit (with retries), log the job id at once, wait, save the next take, log its cost."""
    sub = _with_retry(submit, s, f"{kind} {scene_id}", proj)
    # record the id before anything else can fail, so a paid clip is always recoverable
    proj.log(kind="video_submitted", scene=scene_id, provider=vp.id, **sub.ids,
             **({"edited_from": meta["edited_from"]} if "edited_from" in meta else {}))
    out = proj.next_take_path(scene_id)
    try:
        res = vp.collect(sub)
        out.write_bytes(res.video)
    except Exception as e:
        # the generation may still have been billed; keep it in the cost log
        usage = getattr(e, "usage", {})
        cost = getattr(e, "cost_usd", None)
        proj.log(kind="video_unsaved", scene=scene_id, provider=vp.id, model=vp.model, **sub.ids,
                 usage=usage, cost_usd=cost if cost is not None else call_cost(vp.model, usage))
        raise
    cost = res.cost_usd if res.cost_usd is not None else call_cost(vp.model, res.usage)
    meta = {**meta, **res.meta, "take": out.name, "provider": vp.id, "model": vp.model,
            "duration_s": video_duration(out), "usage": res.usage, "cost_usd": cost,
            "created": time.time()}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    proj.log(kind=kind, **meta)
    return out


def generate_take(client, s: Settings, proj: Project, scene_id: str, provider: str | None = None) -> Path:
    plan = proj.load_plan()
    scene = next(sc for sc in plan["scenes"] if sc["id"] == scene_id)
    vp, shot, prompt = build_shot(plan, proj, scene, s, client, provider=provider)
    ok, why = vp.configured()
    if not ok:
        raise ProviderError(401, f"{vp.label} isn't set up. {why}")
    fmt = {"type": "video", "aspect_ratio": shot.aspect, "resolution": shot.resolution}
    return _shoot(vp, s, proj, scene_id, lambda: vp.submit(shot, prompt),
                  {"scene": scene_id, "prompt": prompt, "refs": [r.id for r in shot.refs],
                   "format": fmt, "first_frame": bool(shot.first_frame)}, kind="video")


def edit_take(client, s: Settings, proj: Project, scene_id: str, take: Path,
              instruction: str) -> Path:
    """Conversational edit on an existing take, by the model that made it."""
    meta = json.loads(take.with_suffix(".json").read_text(encoding="utf-8"))
    meta.setdefault("provider", providers.DEFAULT_VIDEO)   # takes from before providers existed
    meta.setdefault("created", take.stat().st_mtime)
    vp = providers.video_provider(meta["provider"], s, client)
    text = edit_instruction(instruction)
    base = {k: v for k, v in meta.items()
            if k not in ("usage", "cost_usd", "duration_s", "interaction_id", "task_id", "output_url", "created")}
    return _shoot(vp, s, proj, scene_id, lambda: vp.submit_edit(meta, text),
                  {**base, "edited_from": take.name, "edit": text}, kind="video_edit")


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

def estimate_remaining(proj: Project, s: Settings) -> dict:
    """What produce() would still make, and roughly what it costs."""
    plan = proj.load_plan()
    refs = [j["id"] for j in asset_jobs(plan) if not proj.asset_path(j["id"]).exists()]
    scenes = [sc for sc in plan["scenes"] if not proj.takes(sc["id"])]
    seconds = sum(sc["duration_s"] for sc in scenes)
    usd = estimate_image_usd(s, len(refs)) + sum(   # each scene at its own model's price
        estimate_video_usd(s, sc["duration_s"], scene_provider(plan, sc["id"], s)) for sc in scenes)
    return {"refs": refs, "scenes": [sc["id"] for sc in scenes], "video_s": seconds,
            "usd": round(usd, 2)}


def produce(client, s: Settings, proj: Project, log=print, step=None) -> dict:
    """Make everything the film still needs: missing references, one take for each scene
    that has none, then the final cut. Finished work is skipped, so re-running resumes an
    interrupted or failed run. Returns {"failed": {id: why}, "final": Path | None}.
    step(kind, label, done, total) is called as each step starts (kind: image | video |
    stitch), for progress bars."""
    step = step or (lambda *a: None)
    plan = proj.load_plan()
    est = estimate_remaining(proj, s)
    log(f"To make: {len(est['refs'])} references, {len(est['scenes'])} scenes "
        f"({est['video_s']}s at {s.resolution}), about ${est['usd']:.2f}")
    failed: dict[str, str] = {}
    total, done = len(est["refs"]) + len(est["scenes"]) + 1, 0

    if est["refs"]:
        log("Reference images…")
        n_refs = len(est["refs"])
        step("image", f"Painting {n_refs} references", 0, total)

        def on_asset(i, st):
            nonlocal done
            log(f"  {i}: {st}")
            done += 1
            if done < n_refs:
                step("image", f"Painting references · {done} of {n_refs} done", done, total)
        res = generate_assets(client, s, proj, on_progress=on_asset)
        done = n_refs
        failed.update({i: st for i, st in res.items() if st.startswith(("failed", "fatal"))})
        if any(st.startswith("fatal") for st in res.values()):
            log("Stopping: this error will affect every call.")
            return {"failed": failed, "final": None}

    ids = [sc["id"] for sc in plan["scenes"]]
    for i, sc in enumerate(plan["scenes"]):
        if proj.takes(sc["id"]):
            continue
        done += 1                                 # counts this scene whether shot, skipped or failed
        no_img = [r for r in sc["refs"] if r in _lookup(plan) and not proj.asset_path(r).exists()]
        if no_img:                                # don't pay for a shot without its identity refs
            failed[sc["id"]] = f"skipped: missing references {', '.join(no_img)}"
            log(f"  {sc['id']}: {failed[sc['id']]}")
            continue
        if sc.get("continuity") == "continuous" and i > 0 and not proj.takes(ids[i - 1]):
            failed[sc["id"]] = f"skipped: continues from {ids[i - 1]}, which has no take"
            log(f"  {sc['id']}: {failed[sc['id']]}")
            continue
        step("video", f"Shooting {sc['id']}", done - 1, total)
        log(f"Shooting {sc['id']} ({sc['duration_s']}s, {s.resolution})…")
        try:
            out = generate_take(client, s, proj, sc["id"])
        except Exception as e:
            failed[sc["id"]] = friendly_error(e)
            log(f"  {sc['id']} failed: {failed[sc['id']]}")
            if _is_fatal(e):
                log("Stopping: this error will affect every call.")
                break
            continue
        meta = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
        cost = f"${meta['cost_usd']:.2f}" if meta.get("cost_usd") is not None else "cost unknown"
        log(f"  {sc['id']}: {out.name}, {meta.get('duration_s')}s, {cost}")

    final = None
    missing = [sc_id for sc_id in ids if not proj.takes(sc_id)]
    if missing:
        log(f"Not stitching yet; scenes without a take: {', '.join(missing)}. "
            "Fix the cause, then resume.")
    else:
        step("stitch", "Stitching the final cut", total - 1, total)
        try:
            final = stitch(proj)
            log(f"Final cut: {final}")
        except Exception as e:
            failed["stitch"] = friendly_error(e)
            log(f"Stitch failed: {failed['stitch']}")
    log(f"Spent so far: {format_costs(project_costs(proj))}")
    return {"failed": failed, "final": final}


def run_all(story: str, style: str, s: Settings, base_dir: Path = Path("projects"),
            n_scenes: int = 6, api_key: str | None = None, log=print) -> tuple[Project, dict]:
    """Full auto: plan, then produce(). Returns (project, produce result)."""
    client = make_client(s, api_key)
    log("Planning…")
    proj = new_project(client, s, story, style, n_scenes, base_dir)
    log(f"Plan saved: {proj.plan_path} ({format_costs(project_costs(proj))})")
    return proj, produce(client, s, proj, log)
