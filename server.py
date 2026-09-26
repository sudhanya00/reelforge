"""ReelForge local web server: a JSON API over pipeline.py plus the built web UI.

Generation runs as background jobs (a clip takes minutes); the UI polls /api/jobs.
Start it with launch.py (or ReelForge.bat), not directly.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import hashlib

import re

import captions as cap
import products as prod
import uploads as up
import fontbook as fb
import director
from providers import gcs
import editor
import influencers as infl
import library as lib
import pipeline as pl
import styles
import review as rv
import providers

ROOT = Path(__file__).resolve().parent
WEB_DIST = ROOT / "web" / "out"
PREFS_PATH = ROOT / "reelforge.settings.json"          # UI settings; gitignored
STATS_PATH = ROOT / "reelforge.stats.json"             # measured step durations; gitignored

# configured by launch.py (or tests) before the app serves requests
CONFIG = {"projects": ROOT / "projects", "library": ROOT / "library", "fake": False}

app = FastAPI(title="ReelForge")
# the Next dev server (npm run dev) runs on another port
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["*"], allow_headers=["*"])


def the_library() -> lib.Library:
    return lib.Library(CONFIG["library"])


def library_view(c: dict) -> dict:
    sheet = Path(c["sheet_path"]) if c.get("sheet_path") else None
    return {**{k: v for k, v in c.items() if k != "sheet_path"},
            "image": f"/library-files/characters/{c['id']}/sheet.png?v={int(sheet.stat().st_mtime)}" if sheet else None}


def projects_dir() -> Path:
    d = Path(CONFIG["projects"])
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------
# Settings (env defaults from pipeline.Settings, overridden by the UI's saved prefs)
# --------------------------------------------------------------------------

PREF_KEYS = ("backend", "gcp_project", "gcp_location", "resolution", "image_size", "orientation",
             "video_provider", "gcs_bucket")
BOOL_PREFS = ("kling_audio",)
MODEL_KEYS = ("planner_model", "image_model", "video_model")


def load_prefs() -> dict:
    try:
        return json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def current_settings(prefs: dict | None = None) -> pl.Settings:
    p = load_prefs() if prefs is None else prefs
    kw = {k: p[k] for k in PREF_KEYS if p.get(k)}
    kw.update({k: bool(p[k]) for k in BOOL_PREFS if k in p})
    backend = kw.get("backend") or pl.Settings().backend
    kw.update({k: v for k, v in p.get("models", {}).get(backend, {}).items() if k in MODEL_KEYS and v})
    return pl.Settings(**kw)


def settings_view(s: pl.Settings) -> dict:
    image_price = pl.Settings.PRICES.get(s.image_model, {}).get("per_image", {})
    video_rate = pl.Settings.PRICES.get(s.video_model, {}).get("output", 0)
    return {
        "backend": s.backend, "gcp_project": s.gcp_project, "gcp_location": s.gcp_location,
        "planner_model": s.planner_model, "image_model": s.image_model, "video_model": s.video_model,
        "resolution": s.resolution, "image_size": s.image_size, "orientation": s.orientation,
        "video_provider": s.video_provider, "kling_audio": s.kling_audio,
        "gcs_bucket": s.gcs_bucket,
        # Omni 1080p/4k on Vertex needs the bucket; the Gemini API delivers them directly
        "high_res_ready": s.backend != "vertex" or bool(s.gcs_bucket),
        "providers": providers.catalog(s),
        "default_models": pl.Settings.MODELS,
        # what the UI needs to show estimates on every button that spends money
        "prices": {
            "image": image_price.get(s.image_size, 0),
            "video_per_s": {r: round(t * video_rate / 1e6, 4)
                            for r, t in pl.Settings.VIDEO_TOKENS_PER_S.items()},
        },
    }


_clients: dict[tuple, object] = {}
_clients_lock = threading.Lock()


def code_version() -> str:
    """Hash of the app's Python code. If it changes while the server runs, the server is stale."""
    h = hashlib.sha1()
    for f in sorted([*ROOT.glob("*.py"), *(ROOT / "providers").glob("*.py")]):
        h.update(f.name.encode() + f.read_bytes())
    return h.hexdigest()[:12]


STARTED_VERSION = code_version()


def client_for(s: pl.Settings):
    if CONFIG["fake"]:
        return _fake_client()
    key = (s.backend, s.gcp_project, s.gcp_location)
    with _clients_lock:
        if key not in _clients:
            _clients[key] = pl.make_client(s)
        return _clients[key]


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------

# How long each kind of step usually takes (seconds), until we've measured our own.
DEFAULT_TYPICAL_S = {"plan": 35, "image": 22, "video_360p": 140, "video_720p": 180,
                     "video_1080p": 240, "video_4k": 300, "stitch": 6,
                     "video_kling_720p": 180, "video_kling_1080p": 240, "video_kling_4k": 360,
                     "video_veo-fast_720p": 60, "video_veo-fast_1080p": 90,
                     "video_veo_720p": 90, "video_veo_1080p": 120,
                     "review": 40, "direct": 60, "design": 30, "script": 30, "export": 15, "sync": 30, "describe": 25}


def video_key(provider: str, resolution: str) -> str:
    """Timing-stats key for a clip; the default provider keeps its original keys."""
    return f"video_{resolution}" if provider == providers.DEFAULT_VIDEO else f"video_{provider}_{resolution}"
_stats_lock = threading.Lock()


def record_duration(key: str, seconds: float) -> None:
    with _stats_lock:
        try:
            stats = json.loads(STATS_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            stats = {}
        stats[key] = (stats.get(key, []) + [round(seconds, 1)])[-20:]
        STATS_PATH.write_text(json.dumps(stats), encoding="utf-8")


def typical_s() -> dict[str, float]:
    """Median of the last 20 measured runs per step kind, else a default."""
    try:
        stats = json.loads(STATS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        stats = {}
    out = dict(DEFAULT_TYPICAL_S)
    for k, v in stats.items():
        if v:
            out[k] = sorted(v)[len(v) // 2]
    return out


@dataclass
class Job:
    id: str
    kind: str                      # plan | film | assets | take | edit | produce | stitch
    label: str
    project: str | None
    claims: set[str]               # scene/asset ids this job writes; "*" = whole project
    status: str = "running"        # running | done | failed
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    result: dict | None = None
    started: float = field(default_factory=time.time)
    finished: float | None = None
    # {kind, key, label, done, total, step_started, expected_s}: drives the UI's progress bars
    progress: dict | None = None
    _record: bool = False

    def log(self, msg: str) -> None:
        self.logs.append(msg)

    def step(self, kind: str, label: str, done: int = 0, total: int = 1,
             key: str | None = None, record: bool = True) -> None:
        """Start a step. The previous one's duration feeds future estimates."""
        now = time.time()
        self.close_step(now)
        key = key or kind
        self.progress = {"kind": kind, "key": key, "label": label, "done": done, "total": total,
                         "step_started": now, "expected_s": typical_s().get(key, 60)}
        self._record = record

    def close_step(self, now: float) -> None:
        if self.progress and self._record and self.status == "running":
            record_duration(self.progress["key"], now - self.progress["step_started"])
        self._record = False

    def view(self) -> dict:
        return {"id": self.id, "kind": self.kind, "label": self.label, "project": self.project,
                "claims": sorted(self.claims), "status": self.status, "logs": self.logs[-200:],
                "error": self.error, "result": self.result, "started": self.started,
                "finished": self.finished, "progress": self.progress}


JOBS: dict[str, Job] = {}
_jobs_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=8)


def running_claims(project: str) -> set[str]:
    return {c for j in JOBS.values() if j.project == project and j.status == "running" for c in j.claims}


def submit(kind: str, label: str, project: str | None, claims: set[str], fn) -> Job:
    with _jobs_lock:
        if project:
            busy = running_claims(project)
            if busy and ("*" in busy or "*" in claims or busy & claims):
                raise HTTPException(409, "Something in this project is already being generated. "
                                         "Wait for it to finish.")
        job = Job(id=uuid.uuid4().hex[:10], kind=kind, label=label, project=project, claims=claims)
        JOBS[job.id] = job

    def run():
        try:
            job.result = fn(job) or {}
            job.close_step(time.time())
            if job.progress:
                job.progress["done"] = job.progress["total"]
            job.status = "done"
        except Exception as e:                      # noqa: BLE001 - reported to the UI
            job.error = pl.friendly_error(e)
            job.status = "failed"
            traceback.print_exc()
        finally:
            job.finished = time.time()
    _executor.submit(run)
    return job


# --------------------------------------------------------------------------
# Project views
# --------------------------------------------------------------------------

def open_project(pid: str) -> pl.Project:
    root = (projects_dir() / pid).resolve()
    if root.parent != projects_dir().resolve():
        raise HTTPException(400, "Bad project id")
    try:
        return pl.Project.open(root)
    except FileNotFoundError:
        raise HTTPException(404, f"No project named {pid}")


def file_url(proj: pl.Project, path: Path) -> str:
    rel = path.relative_to(proj.root).as_posix()
    return f"/files/{proj.root.name}/{rel}?v={int(path.stat().st_mtime)}"


def poster_url(proj: pl.Project, video: Path) -> str:
    rel = video.relative_to(proj.root).as_posix()
    return f"/api/projects/{proj.root.name}/poster?path={rel}&v={int(video.stat().st_mtime)}"


def take_view(proj: pl.Project, take: Path) -> dict:
    meta_path = take.with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return {"name": take.name, "url": file_url(proj, take), "poster": poster_url(proj, take),
            "duration_s": meta.get("duration_s"), "cost_usd": meta.get("cost_usd"),
            "resolution": meta.get("format", {}).get("resolution"),
            "edited_from": meta.get("edited_from"), "edit": meta.get("edit"),
            "prompt": meta.get("prompt"), "created": take.stat().st_mtime,
            "provider": meta.get("provider", providers.DEFAULT_VIDEO), "model": meta.get("model"),
            "review": meta.get("review"),
            "motion": {k: meta["motion"][k] for k in ("dead", "dead_s", "cuts")} if meta.get("motion") else None}


def item_errors(proj: pl.Project) -> dict[str, str]:
    """Latest failure per scene/reference from log.jsonl, cleared by a later success."""
    errs: dict[str, str] = {}
    path = proj.root / "log.jsonl"
    if not path.exists():
        return errs
    for line in path.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e.get("kind") == "error":
            errs[e["item"]] = e["error"]
        elif e.get("kind") == "image":
            errs.pop(e.get("id"), None)
        elif e.get("kind") in ("video", "video_edit"):
            errs.pop(e.get("scene"), None)
    return errs


def record_failures(proj: pl.Project, failed: dict[str, str]) -> None:
    for item, why in failed.items():
        proj.log(kind="error", item=item, error=why)


KIND_SINGULAR = {"characters": "character", "props": "prop", "environments": "environment"}


def project_view(proj: pl.Project) -> dict:
    s = current_settings()
    plan = proj.load_plan()
    pid = proj.root.name
    idx = pl._lookup(plan)
    busy = running_claims(pid)
    overrides = plan.get("prompt_overrides", {})
    defaults = {j["id"]: j["prompt"] for j in pl.asset_jobs({**plan, "prompt_overrides": {}})}
    errors = item_errors(proj)
    saved = {c["source"]["id"]: c["id"] for c in the_library().characters()
             if c.get("source", {}).get("project") == pid}
    cast = {c["id"] for c in plan.get("cast", [])}

    assets = []
    for j in pl.asset_jobs(plan):
        kind, item = idx[j["id"]]
        path = proj.asset_path(j["id"])
        generating = j["id"] in busy or "*" in busy and not path.exists()
        assets.append({
            "id": j["id"], "kind": KIND_SINGULAR[kind], "name": item["name"],
            "description": item.get("description") or item.get("appearance", ""),
            "prompt": j["prompt"], "default_prompt": defaults[j["id"]],
            "overridden": j["id"] in overrides, "base": j["base"], "aspect": j["aspect"],
            "image": file_url(proj, path) if path.exists() else None,
            "status": "generating" if generating else ("done" if path.exists() else "missing"),
            "error": errors.get(j["id"]),
            "library_id": saved.get(j["id"]) or (j["id"] if j["id"] in cast else None),
        })

    scenes = []
    for sc in plan["scenes"]:
        vp, shot, prompt = pl.build_shot(plan, proj, sc, s, extract=False)
        refs_used = [r.id for r in shot.refs]
        default_prompt = vp.build_prompt(shot)
        pkey = pl.prompt_key(sc["id"], vp.id)
        takes = proj.takes(sc["id"])
        sel = pl.selected_take(plan, proj, sc["id"])
        generating = sc["id"] in busy or ("*" in busy and not takes)
        scenes.append({
            **{k: v for k, v in sc.items()},
            "prompt": prompt, "default_prompt": default_prompt,
            "overridden": pkey in overrides, "refs_used": refs_used,
            "provider": vp.id, "provider_chosen": sc["id"] in plan.get("video_providers", {}),
            "render": {"resolution": shot.resolution, "duration_s": shot.duration_s},
            "refs_missing": [r for r in sc["refs"] if r in idx and r not in refs_used],
            "takes": [take_view(proj, t) for t in takes],
            "selected": sel.name if sel else None,
            "status": "generating" if generating else ("done" if takes else "missing"),
            "error": errors.get(sc["id"]),
        })

    final = proj.root / "final.mp4"
    return {
        "id": pid, "plan": plan, "orientation": plan.get("orientation", "16:9"),
        "assets": assets, "scenes": scenes,
        "final": {"url": file_url(proj, final), "poster": poster_url(proj, final),
                  "duration_s": pl.video_duration(final), "updated": final.stat().st_mtime}
        if final.exists() else None,
        "edit": edit_view(proj, lambda path: file_url(proj, path)),
        "costs": pl.project_costs(proj),
        "busy": sorted(busy),
    }


def project_summary(proj: pl.Project) -> dict:
    plan = proj.load_plan()
    jobs = pl.asset_jobs(plan)
    refs_done = sum(proj.asset_path(j["id"]).exists() for j in jobs)
    scenes_done = sum(bool(proj.takes(sc["id"])) for sc in plan["scenes"])
    poster = None
    for sc in plan["scenes"]:
        t = pl.selected_take(plan, proj, sc["id"])
        if t:
            poster = poster_url(proj, t)
            break
    if not poster:
        envs = [j["id"] for j in jobs if j["id"] in {e["id"] for e in plan["environments"]}]
        for aid in envs + [j["id"] for j in jobs]:
            if proj.asset_path(aid).exists():
                poster = file_url(proj, proj.asset_path(aid))
                break
    mtimes = [p.stat().st_mtime for p in (proj.plan_path, proj.root / "log.jsonl") if p.exists()]
    return {
        "id": proj.root.name, "title": plan["title"], "logline": plan.get("logline", ""),
        "orientation": plan.get("orientation", "16:9"), "poster": poster,
        "refs": [refs_done, len(jobs)], "scenes": [scenes_done, len(plan["scenes"])],
        "final": (proj.root / "final.mp4").exists(),
        "cost_usd": pl.project_costs(proj)["usd"], "updated": max(mtimes),
        "busy": bool(running_claims(proj.root.name)),
    }


_plan_locks: dict[str, threading.Lock] = {}


def plan_lock(pid: str) -> threading.Lock:
    return _plan_locks.setdefault(pid, threading.Lock())


def update_plan(proj: pl.Project, fn) -> dict:
    """Read-modify-write plan.json under a per-project lock."""
    with plan_lock(proj.root.name):
        plan = proj.load_plan()
        fn(plan)
        proj.save_plan(plan)
        return plan


# --------------------------------------------------------------------------
# API: app state and settings
# --------------------------------------------------------------------------

@app.get("/api/state")
def get_state():
    s = current_settings()
    return {"settings": settings_view(s), "ffmpeg": bool(shutil.which("ffmpeg")),
            "fake": CONFIG["fake"], "projects_dir": str(projects_dir()), "typical_s": typical_s(),
            "styles": [{"id": k, "label": v["label"], "pacing": v["pacing"]} for k, v in styles.STYLE_PRESETS.items()],
            "pacing": [{"id": k, "label": v["label"], "brief": styles.pacing_brief(k)} for k, v in styles.PACING.items()],
            "planner_version": s.planner_version,
            "stale": code_version() != STARTED_VERSION}


class SettingsIn(BaseModel):
    backend: str | None = None
    gcp_project: str | None = None
    gcp_location: str | None = None
    resolution: str | None = None
    image_size: str | None = None
    orientation: str | None = None
    video_provider: str | None = None
    kling_audio: bool | None = None
    models: dict[str, dict[str, str]] | None = None


@app.put("/api/settings")
def put_settings(body: SettingsIn):
    prefs = load_prefs()
    for k, v in body.model_dump(exclude_none=True).items():
        if k == "models":
            for b, m in v.items():
                prefs.setdefault("models", {}).setdefault(b, {}).update(
                    {k2: v2 for k2, v2 in m.items() if k2 in MODEL_KEYS})
        else:
            prefs[k] = v
    try:
        s = current_settings(prefs)
        providers.video_provider(s.video_provider, s)
    except (KeyError, TypeError, ValueError, providers.ProviderError) as e:
        raise HTTPException(400, f"Invalid settings: {e}")
    PREFS_PATH.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    return get_state()


@app.post("/api/settings/check")
def check_connection():
    """Free call (lists models) to confirm credentials and that the chosen models exist."""
    s = current_settings()
    if CONFIG["fake"]:
        return {"ok": True, "message": "Demo mode: using a fake client, nothing is billed.",
                "models": {m: True for m in MODEL_KEYS}}
    try:
        client = client_for(s)
        cfg = {"query_base": True, "page_size": 100} if s.backend == "vertex" else {"page_size": 100}
        names = {m.name.split("/")[-1] for m in client.models.list(config=cfg)}
    except Exception as e:                           # noqa: BLE001
        with _clients_lock:
            _clients.clear()                         # e.g. credentials refreshed: rebuild next time
        return {"ok": False, "message": pl.friendly_error(e), "models": {}}
    found = {k: getattr(s, k) in names for k in MODEL_KEYS}
    missing = [getattr(s, k) for k, ok in found.items() if not ok]
    where = f"Vertex AI · {s.gcp_project} · {s.gcp_location}" if s.backend == "vertex" else "Gemini API"
    return {"ok": not missing, "models": found,
            "message": f"Connected to {where}." + (f" Not available here: {', '.join(missing)}."
                                                   if missing else " All three models are available.")}


class BucketIn(BaseModel):
    name: str | None = None


@app.post("/api/settings/bucket")
def create_bucket(body: BucketIn):
    """Create (or adopt) the Cloud Storage bucket Vertex delivers 1080p/4k videos to.
    Private, in the app's project; anything left in it is deleted after a day."""
    s = current_settings()
    if s.backend != "vertex" or not s.gcp_project:
        raise HTTPException(400, "Only needed on Vertex AI, with a project set")
    name = (body.name or f"{s.gcp_project}-reelforge").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{1,61}[a-z0-9]", name):
        raise HTTPException(400, "Bucket names are 3-63 lowercase letters, digits, - _ .")
    if not CONFIG["fake"]:
        try:
            created = gcs.ensure_bucket(name, s.gcp_project)
        except Exception as e:                       # noqa: BLE001
            raise HTTPException(400, pl.friendly_error(e))
    else:
        created = True
    prefs = load_prefs()
    prefs["gcs_bucket"] = name
    PREFS_PATH.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    return {**get_state(), "bucket": {"name": name, "created": created}}


# --------------------------------------------------------------------------
# API: projects
# --------------------------------------------------------------------------

@app.get("/api/projects")
def list_projects():
    out = []
    for d in projects_dir().iterdir():
        if (d / "plan.json").exists():
            try:
                out.append(project_summary(pl.Project(d)))
            except Exception:                        # noqa: BLE001 - skip a broken folder
                traceback.print_exc()
    return sorted(out, key=lambda p: p["updated"], reverse=True)


class NewFilm(BaseModel):
    story: str
    style: str = ""
    scenes: int = 6
    orientation: str | None = None
    preset: str | None = None                        # a styles.STYLE_PRESETS id
    cast: list[str] = []                             # library character ids to use as saved
    pacing: str | None = None                        # calm | balanced | kinetic
    auto: bool = False                               # plan, then make everything


@app.post("/api/projects")
def create_project(body: NewFilm):
    if not body.story.strip():
        raise HTTPException(400, "Write a story or idea first.")
    s = current_settings()
    if body.orientation:
        s.orientation = body.orientation
    try:
        cast = [the_library().get(cid) for cid in body.cast]
    except KeyError as e:
        raise HTTPException(404, f"No library character {e}")

    def run(job: Job):
        client = client_for(s)
        job.log("Writing the production plan…")
        job.step("plan", "Writing and directing the plan" if s.planner_version == "v2" else "Writing the plan")
        proj = pl.new_project(client, s, body.story.strip(), body.style.strip(),
                              max(1, min(body.scenes, 20)), projects_dir(),
                              preset=body.preset if body.preset in styles.STYLE_PRESETS else None,
                              pacing=body.pacing if body.pacing in styles.PACING else None,
                              cast=cast)
        job.project = proj.root.name
        job.claims = {"*"}
        job.log(f"Plan ready: {proj.load_plan()['title']}")
        if body.auto:
            result = pl.produce(client, s, proj, log=job.log, step=produce_steps(job, s))
            record_failures(proj, result["failed"])
        return {"project": proj.root.name}

    job = submit("film" if body.auto else "plan",
                 "Making the film" if body.auto else "Writing the plan", None, set(), run)
    return job.view()


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return project_view(open_project(pid))


class PlanIn(BaseModel):
    plan: dict


@app.put("/api/projects/{pid}/plan")
def put_plan(pid: str, body: PlanIn):
    proj = open_project(pid)
    missing = [k for k in pl.PLAN_SCHEMA["required"] if k not in body.plan]
    if missing:
        raise HTTPException(400, f"Plan is missing: {', '.join(missing)}")
    ids = {i for k in ("characters", "props", "environments") for i in
           (x.get("id") for x in body.plan.get(k, []))}
    for sc in body.plan["scenes"]:
        unknown = [r for r in sc.get("refs", []) if r not in ids]
        if unknown:
            raise HTTPException(400, f"{sc.get('id')}: unknown refs {', '.join(unknown)}")

    def apply(plan):
        keep = {k: plan[k] for k in ("prompt_overrides", "selected_takes", "orientation", "video_providers")
                if k in plan}
        plan.clear()
        plan.update({**director.normalize(body.plan), **keep})
    update_plan(proj, apply)
    return project_view(proj)


class PromptIn(BaseModel):
    id: str
    prompt: str | None = None                        # None = back to the generated prompt
    provider: str | None = None                      # scene prompts are per video provider


@app.put("/api/projects/{pid}/prompt")
def put_prompt(pid: str, body: PromptIn):
    proj = open_project(pid)

    key = pl.prompt_key(body.id, body.provider) if body.provider else body.id

    def apply(plan):
        ov = plan.setdefault("prompt_overrides", {})
        if body.prompt and body.prompt.strip():
            ov[key] = body.prompt.strip()
        else:
            ov.pop(key, None)
    update_plan(proj, apply)
    return project_view(proj)


class ProviderIn(BaseModel):
    provider: str | None = None                      # None = use the settings default


@app.put("/api/projects/{pid}/scenes/{sid}/provider")
def put_scene_provider(pid: str, sid: str, body: ProviderIn):
    proj = open_project(pid)
    if body.provider and body.provider not in providers.VIDEO:
        raise HTTPException(400, f"Unknown provider {body.provider}")
    if sid not in {sc["id"] for sc in proj.load_plan()["scenes"]}:
        raise HTTPException(404, "No such scene")

    def apply(plan):
        chosen = plan.setdefault("video_providers", {})
        if body.provider:
            chosen[sid] = body.provider
        else:
            chosen.pop(sid, None)
    update_plan(proj, apply)
    return project_view(proj)


class SelectIn(BaseModel):
    take: str


@app.put("/api/projects/{pid}/scenes/{sid}/selected")
def put_selected(pid: str, sid: str, body: SelectIn):
    proj = open_project(pid)
    if not (proj.scene_dir(sid) / body.take).exists():
        raise HTTPException(404, "No such take")
    update_plan(proj, lambda plan: plan.setdefault("selected_takes", {}).__setitem__(sid, body.take))
    return project_view(proj)


class AssetsIn(BaseModel):
    ids: list[str] | None = None                     # None = all missing
    force: bool = False


@app.post("/api/projects/{pid}/assets")
def make_assets(pid: str, body: AssetsIn):
    proj = open_project(pid)
    plan = proj.load_plan()
    all_ids = [j["id"] for j in pl.asset_jobs(plan)]
    ids = body.ids or [i for i in all_ids if not proj.asset_path(i).exists()]
    unknown = [i for i in ids if i not in all_ids]
    if unknown:
        raise HTTPException(404, f"Unknown reference: {', '.join(unknown)}")
    if not ids:
        raise HTTPException(400, "Every reference image already exists.")
    s = current_settings()

    def run(job: Job):
        n = len(ids)
        # images run in parallel, so only a single image measures a clean duration
        job.step("image", f"Painting {n} reference{'s' * (n != 1)}", 0, n, record=n == 1)

        def on_progress(i, st):
            job.log(f"{i}: {st}")
            done = job.progress["done"] + 1
            if done < n:
                job.step("image", f"Painting references · {done} of {n} done", done, n, record=False)
        res = pl.generate_assets(client_for(s), s, proj, only=ids if (body.ids or body.force) else None,
                                 skip_existing=not body.force, on_progress=on_progress)
        bad = {i: st for i, st in res.items() if st.startswith(("failed", "fatal"))}
        record_failures(proj, {i: st.split(": ", 1)[1] for i, st in bad.items()})
        if bad and len(bad) == len(res):
            raise RuntimeError(next(iter(bad.values())).split(": ", 1)[1])
        return {"statuses": res}

    label = f"Painting {ids[0]}" if len(ids) == 1 else f"Painting {len(ids)} references"
    return submit("assets", label, pid, set(ids), run).view()


@app.post("/api/projects/{pid}/scenes/{sid}/takes")
def make_take(pid: str, sid: str):
    proj = open_project(pid)
    if sid not in {sc["id"] for sc in proj.load_plan()["scenes"]}:
        raise HTTPException(404, "No such scene")
    s = current_settings()

    plan = proj.load_plan()
    vp = providers.video_provider(pl.scene_provider(plan, sid, s), s)
    res = vp.resolution_for(s.resolution)

    def run(job: Job):
        job.log(f"Shooting {sid} with {vp.label} at {res}…")
        job.step("video", f"Shooting {sid}", key=video_key(vp.id, res))
        try:
            out = pl.generate_take(client_for(s), s, proj, sid)
        except Exception as e:
            record_failures(proj, {sid: pl.friendly_error(e)})
            raise
        update_plan(proj, lambda plan: plan.setdefault("selected_takes", {}).__setitem__(sid, out.name))
        return {"take": out.name}

    return submit("take", f"Shooting {sid}", pid, {sid}, run).view()


class EditIn(BaseModel):
    instruction: str


@app.post("/api/projects/{pid}/scenes/{sid}/takes/{take}/edit")
def edit_take(pid: str, sid: str, take: str, body: EditIn):
    proj = open_project(pid)
    src = proj.scene_dir(sid) / take
    if not src.exists():
        raise HTTPException(404, "No such take")
    if not body.instruction.strip():
        raise HTTPException(400, "Describe the fix first.")
    s = current_settings()

    meta = json.loads(src.with_suffix(".json").read_text(encoding="utf-8"))
    res = meta.get("format", {}).get("resolution") or s.resolution    # an edit keeps its take's res
    edit_provider = meta.get("provider", providers.DEFAULT_VIDEO)

    def run(job: Job):
        job.log(f"Editing {sid}/{take}: {body.instruction.strip()}")
        job.step("video", f"Fixing {sid}", key=video_key(edit_provider, res))
        try:
            out = pl.edit_take(client_for(s), s, proj, sid, src, body.instruction)
        except Exception as e:
            record_failures(proj, {sid: pl.friendly_error(e)})
            raise
        update_plan(proj, lambda plan: plan.setdefault("selected_takes", {}).__setitem__(sid, out.name))
        return {"take": out.name}

    return submit("edit", f"Fixing {sid}", pid, {sid}, run).view()


@app.post("/api/projects/{pid}/scenes/{sid}/takes/{take}/review")
def review_take(pid: str, sid: str, take: str):
    """Gemini watches the take beside its brief and references: scorecard, issues, suggested fix."""
    proj = open_project(pid)
    src = proj.scene_dir(sid) / take
    if not src.exists():
        raise HTTPException(404, "No such take")
    s = current_settings()

    def run(job: Job):
        job.step("review", f"Reviewing {sid}")
        r = rv.review_take(client_for(s), s, proj, sid, src)
        return {"verdict": r["verdict"], "overall": r["overall"]}

    return submit("review", f"Reviewing {sid}", pid, {f"review:{sid}"}, run).view()


@app.post("/api/projects/{pid}/direct")
def direct(pid: str):
    """Run the director pass again on the current plan (e.g. after your edits)."""
    proj = open_project(pid)
    s = current_settings()

    def run(job: Job):
        job.step("direct", "Directing the plan")
        with plan_lock(pid):
            plan = proj.load_plan()
        revised, notes, usage = pl.direct_plan(client_for(s), s, plan)
        with plan_lock(pid):
            proj.save_plan(revised)
        proj.log(kind="plan", model=s.planner_model, planner="director", usage=usage,
                 cost_usd=pl.call_cost(s.planner_model, usage), director_notes=len(notes))
        return {"notes": len(notes)}

    return submit("direct", "Directing the plan", pid, {"*"}, run).view()


@app.post("/api/projects/{pid}/produce")
def produce(pid: str):
    proj = open_project(pid)
    s = current_settings()

    def run(job: Job):
        result = pl.produce(client_for(s), s, proj, log=job.log, step=produce_steps(job, s))
        record_failures(proj, result["failed"])
        if result["failed"] and not result["final"]:
            done = [k for k in result["failed"]]
            job.result = {"failed": result["failed"]}
            raise RuntimeError(f"Unfinished: {', '.join(done)}. See each card for why.")
        return {"failed": result["failed"], "final": bool(result["final"])}

    return submit("produce", "Making everything missing", pid, {"*"}, run).view()


@app.post("/api/projects/{pid}/stitch")
def stitch(pid: str):
    proj = open_project(pid)

    def run(job: Job):
        job.step("stitch", "Stitching the final cut")
        out = pl.stitch(proj)
        job.log(f"Final cut: {out.name}")
        return {"final": out.name}

    return submit("stitch", "Stitching the final cut", pid, {"stitch"}, run).view()


def produce_steps(job: Job, s: pl.Settings):
    """Adapter from pipeline.produce's step() callback to the job's progress."""
    def step(kind, label, done, total, provider=None):
        key = kind
        if kind == "video":
            vp = providers.video_provider(provider, s)
            key = video_key(vp.id, vp.resolution_for(s.resolution))
        job.step(kind, label, done, total, key=key, record=kind != "image")
    return step


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    """Move a film to the Recycle Bin (restorable) — never a hard delete."""
    proj = open_project(pid)
    if running_claims(pid):
        raise HTTPException(409, "Something in this film is still generating. Wait for it to finish.")
    with plan_lock(pid):
        try:
            from send2trash import send2trash
            send2trash(str(proj.root))
            where = "the Recycle Bin"
        except Exception:                            # noqa: BLE001 - no trash available: keep a copy
            trash = projects_dir() / ".trash"
            trash.mkdir(exist_ok=True)
            dest = trash / f"{pid}-{int(time.time())}"
            shutil.move(str(proj.root), dest)
            where = str(dest)
    _plan_locks.pop(pid, None)
    return {"ok": True, "moved_to": where}


@app.post("/api/projects/{pid}/reveal")
def reveal(pid: str):
    """Open the project folder in the file manager (it's a local app)."""
    proj = open_project(pid)
    if os.name == "nt":
        os.startfile(proj.root)                      # noqa: S606 - local folder we own
    else:
        subprocess.Popen(["open" if shutil.which("open") else "xdg-open", str(proj.root)])
    return {"ok": True}


@app.get("/api/projects/{pid}/poster")
def poster(pid: str, path: str):
    """A still from a clip (cached), for thumbnails and video posters."""
    proj = open_project(pid)
    video = (proj.root / path).resolve()
    if proj.root.resolve() not in video.parents or video.suffix != ".mp4" or not video.exists():
        raise HTTPException(404, "No such video")
    return poster_file(video, proj.root / "frames" / "posters" / (path.replace("/", "_").removesuffix(".mp4") + ".jpg"))


def poster_file(video: Path, out: Path) -> FileResponse:
    if not out.exists() or out.stat().st_mtime < video.stat().st_mtime:
        if not shutil.which("ffmpeg"):
            raise HTTPException(404, "ffmpeg is needed for posters")
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.4", "-i", str(video), "-frames:v", "1",
                        "-vf", "scale=640:-2", "-q:v", "3", str(out)], check=False)
        if not out.exists():                         # clip shorter than 0.4s
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-frames:v", "1",
                            "-vf", "scale=640:-2", str(out)], check=False)
    if not out.exists():
        raise HTTPException(404, "Could not extract a frame")
    return FileResponse(out, headers={"Cache-Control": "max-age=31536000, immutable"})


# --------------------------------------------------------------------------
# API: jobs
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# API: character library
# --------------------------------------------------------------------------

@app.get("/api/library")
def get_library():
    return {"characters": [library_view(c) for c in the_library().characters()]}


class SaveCharacterIn(BaseModel):
    project: str
    id: str


@app.post("/api/library/characters")
def save_character(body: SaveCharacterIn):
    proj = open_project(body.project)
    try:
        c = the_library().save_from_project(proj.root, proj.load_plan(), body.id)
    except KeyError:
        raise HTTPException(404, f"No character {body.id} in this film")
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    return library_view(c)


@app.delete("/api/library/characters/{cid}")
def delete_character(cid: str):
    try:
        the_library().delete(cid)
    except KeyError:
        raise HTTPException(404, f"No library character {cid}")
    return {"ok": True}


# --------------------------------------------------------------------------
# API: influencers
# --------------------------------------------------------------------------

def the_influencers() -> infl.Influencers:
    return infl.Influencers(CONFIG["library"])


def inf_key(iid: str) -> str:
    """Jobs for an influencer are grouped under this pseudo-project."""
    return f"inf:{iid}"


def open_influencer(iid: str) -> dict:
    try:
        return the_influencers().get(iid)
    except KeyError:
        raise HTTPException(404, f"No influencer {iid}")


def open_video(iid: str, vid: str) -> pl.Project:
    open_influencer(iid)
    try:
        return the_influencers().video(iid, vid)
    except (KeyError, FileNotFoundError):
        raise HTTPException(404, f"No video {vid}")


def lib_url(path: Path) -> str:
    rel = path.relative_to(the_influencers().root.parent).as_posix()
    return f"/library-files/{rel}?v={int(path.stat().st_mtime)}"


def reel_poster_url(iid: str, video: Path) -> str:
    rel = video.relative_to(the_influencers().dir(iid)).as_posix()
    return f"/api/influencers/{iid}/poster?path={rel}&v={int(video.stat().st_mtime)}"


def log_usd(path: Path) -> float:
    if not path.exists():
        return 0.0
    return round(sum(json.loads(l).get("cost_usd") or 0 for l in path.read_text(encoding="utf-8").splitlines()), 2)


def formats_view() -> list[dict]:
    return [{"id": k, "label": v["label"], "blurb": v["blurb"], "empty_open": bool(v.get("empty_open"))}
            for k, v in infl.FORMATS.items()]


def video_view(iid: str, proj: pl.Project, full: bool = False) -> dict:
    plan = proj.load_plan()
    final = proj.root / "final.mp4"
    takes = proj.takes("reel")
    shown = final if final.exists() else (takes[-1] if takes else None)
    out = {"id": proj.root.name, "title": plan["title"], "hook": plan.get("hook", ""),
           "format": plan.get("format"), "seconds": sum(sg["seconds"] for sg in plan["segments"]),
           "final": lib_url(final) if final.exists() else None,
           "poster": reel_poster_url(iid, shown) if shown else None,
           "cost_usd": pl.project_costs(proj)["usd"],
           "busy": proj.root.name in running_claims(inf_key(iid)),
           "updated": max(p.stat().st_mtime for p in (proj.plan_path, proj.root / "log.jsonl") if p.exists())}
    if full:
        inf = the_influencers().get(iid)
        opening_ok = infl.opening_ok(the_influencers(), iid, proj)
        openings = {}
        for view in infl.opening_views(plan):
            path = infl.opening_path(proj, view)
            openings[view] = lib_url(path) if path.exists() else None
        turns = []
        for t in takes:
            mp = t.with_suffix(".json")
            meta = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
            turns.append({"name": t.name, "url": lib_url(t), "segment": meta.get("segment"),
                          "duration_s": meta.get("duration_s"), "cost_usd": meta.get("cost_usd"),
                          "prompt": meta.get("prompt"), "extends": meta.get("extends")})
        out.update({"caption": plan.get("caption", ""), "brief": plan.get("brief", {}),
                    "segments": plan["segments"], "turns": turns,
                    "extension_mode": plan.get("extension_mode"), "error": item_errors(proj).get("reel"),
                    "costs": pl.project_costs(proj),
                    "setup": infl.setup_of(plan, inf["profile"]),
                    "featured": [{"id": x["id"], "name": x["name"], "brand": x.get("brand", ""), "use": x["use"],
                                  "image": lib_url(x["refs"][0])}
                                 for x in the_influencers().featured(infl.setup_of(plan, inf["profile"]))],
                    "edit": edit_view(proj, lib_url),
                    "captions": cap.state(plan, pl.video_duration(proj.root / "final.mp4")
                                          if (proj.root / "final.mp4").exists() else None, font_book().ids()),
                    "opening": openings, "opening_ok": opening_ok,
                    "opening_error": item_errors(proj).get("opening"),
                    "estimate": infl.estimate_usd(current_settings(), plan, needs_opening=not opening_ok)})
    return out


def influencer_view(inf: dict, full: bool = False) -> dict:
    lib_ = the_influencers()
    iid = inf["id"]
    face = lib_.image(iid, "face")
    videos = lib_.videos(iid)
    identity_usd = log_usd(lib_.dir(iid) / "log.jsonl")
    busy = running_claims(inf_key(iid))
    out = {"id": iid, "profile": inf["profile"], "created": inf.get("created"),
           "face": lib_url(face) if face.exists() else None,
           "identity_done": sum(lib_.image(iid, v).exists() for v in infl.VIEW_IDS),
           "identity_total": len(infl.VIEW_IDS), "videos_count": len(videos),
           "cost_usd": round(identity_usd + sum(pl.project_costs(v)["usd"] for v in videos), 2),
           "busy": bool(busy)}
    if full:
        errors = inf.get("identity_errors", {})
        overrides = inf.get("prompt_overrides", {})
        sources = lib_.sources(iid)
        out["sources"] = [{"name": x.name, "url": lib_url(x)} for x in sources]
        out["consent"] = inf.get("consent")
        out["identity"] = [{
            "view": v, "aspect": aspect, "from_face": from_face,
            "image": lib_url(lib_.image(iid, v)) if lib_.image(iid, v).exists() else None,
            "status": "generating" if v in busy else ("done" if lib_.image(iid, v).exists() else "missing"),
            "error": errors.get(v),
            "prompt": overrides.get(v) or infl.identity_prompt(inf["profile"], v, from_sources=bool(sources)),
            "overridden": v in overrides,
        } for v, aspect, from_face, _ in infl.IDENTITY]
        out["identity_usd"] = identity_usd
        out["places"] = [{
            "id": x["id"], "name": x["name"], "description": x["description"],
            "image": lib_url(x["image"]) if x["image"].exists() else None,
            "status": "generating" if f"place:{x['id']}" in busy or (x["id"] == "home" and "setting" in busy)
                      else ("done" if x["image"].exists() else "missing"),
            "error": inf.get("place_errors", {}).get(x["id"]),
        } for x in lib_.places(inf)]
        out["videos"] = [video_view(iid, v) for v in videos]
    return out


@app.get("/api/influencers")
def list_influencers():
    lib_ = the_influencers()
    return {"influencers": [influencer_view(i) for i in lib_.all()],
            "design_usd": log_usd(lib_.root / "design_log.jsonl"),
            "fields": [{"id": k, "label": label} for k, label in infl.PROFILE_FIELDS],
            "formats": formats_view()}


class DesignIn(BaseModel):
    profile: dict[str, str] = {}
    concept: str = ""


@app.post("/api/influencers/design")
def design_influencer(body: DesignIn):
    """AI fills the fields left empty (a job: the planner takes ~30 s)."""
    s = current_settings()

    def run(job: Job):
        job.step("design", "Designing the influencer")
        out, usage = infl.fill_profile(client_for(s), s, body.profile, body.concept)
        cost = pl.call_cost(s.planner_model, usage)
        the_influencers().log_design(model=s.planner_model, usage=usage, cost_usd=cost)
        return {"profile": out, "cost_usd": cost}

    return submit("design", "Designing an influencer", None, set(), run).view()


class InfluencerIn(BaseModel):
    profile: dict[str, str]
    sources: list[str] = []                          # upload tokens: photos of a real person
    consent: str = ""                                # required with sources


def clean_profile(p: dict) -> dict:
    out = {k: str(p.get(k, "")).strip() for k in infl.KEYS}
    if not out["name"]:
        raise HTTPException(400, "Give the influencer a name")
    if out["handle"] and not out["handle"].startswith("@"):
        out["handle"] = "@" + out["handle"]
    return out


@app.post("/api/influencers")
def create_influencer(body: InfluencerIn):
    ups = the_uploads()
    try:
        photos = [ups.path(tok) for tok in body.sources]
    except KeyError:
        raise HTTPException(400, "A photo upload expired; add the photos again")
    try:
        inf = the_influencers().create(clean_profile(body.profile), sources=photos, consent=body.consent.strip())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return influencer_view(inf, full=True)


class TokensIn(BaseModel):
    tokens: list[str]


@app.post("/api/influencers/{iid}/sources")
def add_sources(iid: str, body: TokensIn):
    inf = open_influencer(iid)
    if not inf.get("consent"):
        raise HTTPException(400, "This influencer wasn't made from photos")
    try:
        the_influencers().add_sources(iid, [the_uploads().path(t) for t in body.tokens])
    except KeyError:
        raise HTTPException(400, "A photo upload expired; add it again")
    return influencer_view(open_influencer(iid), full=True)


@app.delete("/api/influencers/{iid}/sources/{name}")
def delete_source(iid: str, name: str):
    open_influencer(iid)
    try:
        the_influencers().remove_source(iid, name)
    except KeyError:
        raise HTTPException(404, "No such photo")
    return influencer_view(open_influencer(iid), full=True)


# --------------------------------------------------------------------------
# API: uploads and "describe from photos"
# --------------------------------------------------------------------------

def the_uploads() -> up.Uploads:
    return up.Uploads(CONFIG["library"])


@app.post("/api/uploads")
async def upload_image(request: Request):
    """An image as the raw request body; cleaned (EXIF and location removed) and held for a day."""
    try:
        token = the_uploads().add(await request.body())
    except up.UploadError as e:
        raise HTTPException(400, str(e))
    return {"token": token}


class DescribeIn(BaseModel):
    tokens: list[str] = []
    product: str | None = None                       # describe a saved product's photos instead
    what: str                                        # person | product | inspiration


@app.post("/api/describe")
def describe_photos(body: DescribeIn):
    """AI reads photos into fields: a person's look (never who they are), or a product."""
    if body.what not in ("person", "product", "inspiration"):
        raise HTTPException(400, "Describe a person, a product or a mood board")
    try:
        photos = (the_products().photos(body.product) if body.product
                  else [the_uploads().path(t) for t in body.tokens])
    except KeyError:
        raise HTTPException(400, "A photo upload expired; add it again")
    if not photos:
        raise HTTPException(400, "Add a photo first")
    s = current_settings()

    def run(job: Job):
        job.step("describe", "Looking at the photos")
        fn = {"person": infl.describe_person, "product": prod.describe,
              "inspiration": infl.describe_inspiration}[body.what]
        out, usage = fn(client_for(s), s, photos)
        the_influencers().log_design(model=s.planner_model, usage=usage, cost_usd=pl.call_cost(s.planner_model, usage))
        return {"fields": out}

    return submit("describe", "Describing the photos", None, set(), run).view()


# --------------------------------------------------------------------------
# API: products (worn or held in influencer videos)
# --------------------------------------------------------------------------

def the_products() -> prod.Products:
    return the_influencers().products


def product_view(x: dict) -> dict:
    lib_ = the_products()
    shot = lib_.packshot(x["id"])
    busy = running_claims("products")
    return {**x, "use": prod.KINDS.get(x.get("kind"), "hold"),
            "packshot": lib_url(shot) if shot.exists() else None,
            "photos": [lib_url(ph) for ph in lib_.photos(x["id"])],
            "status": "generating" if f"product:{x['id']}" in busy else ("done" if shot.exists() else "missing"),
            "error": x.get("error")}


@app.get("/api/products")
def list_products():
    return {"products": [product_view(x) for x in the_products().all()], "kinds": list(prod.KINDS)}


class ProductIn(BaseModel):
    name: str = ""
    brand: str = ""
    kind: str = "object"
    description: str = ""
    notes: str = ""
    photos: list[str] = []                           # upload tokens (create only)


def packshot_job(pid: str) -> dict:
    s = current_settings()
    lib_ = the_products()

    def run(job: Job):
        job.step("image", "Painting a clean product shot", record=False)
        try:
            prod.paint_packshot(client_for(s), s, lib_, pid)
            err = None
        except Exception as e:
            err = pl.friendly_error(e)
            raise
        finally:
            x = lib_.get(pid)
            x["error"] = err
            lib_.save(x)
        return {"product": pid}

    return submit("product", f"Product shot: {lib_.get(pid)['name']}", "products", {f"product:{pid}"}, run).view()


@app.post("/api/products")
def create_product(body: ProductIn):
    try:
        photos = [the_uploads().path(t) for t in body.photos]
    except KeyError:
        raise HTTPException(400, "A photo upload expired; add the photos again")
    if not body.name.strip():
        raise HTTPException(400, "Name the product")
    try:
        x = the_products().create(body.model_dump(exclude={"photos"}), photos)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"product": product_view(x), "job": packshot_job(x["id"])}


@app.put("/api/products/{pid}")
def update_product(pid: str, body: ProductIn):
    try:
        x = the_products().update(pid, body.model_dump(exclude={"photos"}))
    except KeyError:
        raise HTTPException(404, "No such product")
    return product_view(x)


@app.post("/api/products/{pid}/packshot")
def repaint_packshot(pid: str):
    try:
        the_products().get(pid)
    except KeyError:
        raise HTTPException(404, "No such product")
    return packshot_job(pid)


@app.delete("/api/products/{pid}")
def delete_product(pid: str):
    try:
        d = the_products().dir(pid)
        the_products().get(pid)
    except KeyError:
        raise HTTPException(404, "No such product")
    if f"product:{pid}" in running_claims("products"):
        raise HTTPException(409, "Its product shot is being painted. Wait for it to finish.")
    from send2trash import send2trash
    send2trash(str(d))
    return {"ok": True}


@app.get("/api/influencers/{iid}")
def get_influencer(iid: str):
    return influencer_view(open_influencer(iid), full=True)


@app.put("/api/influencers/{iid}")
def put_influencer(iid: str, body: InfluencerIn):
    with plan_lock(inf_key(iid)):
        inf = open_influencer(iid)
        inf["profile"] = clean_profile(body.profile)
        the_influencers().save(inf)
    return influencer_view(inf, full=True)


class IdentityPromptIn(BaseModel):
    view: str
    prompt: str | None = None                        # empty resets to the generated prompt


@app.put("/api/influencers/{iid}/identity/prompt")
def put_identity_prompt(iid: str, body: IdentityPromptIn):
    if body.view not in infl.VIEW_IDS:
        raise HTTPException(404, "No such view")
    with plan_lock(inf_key(iid)):
        inf = open_influencer(iid)
        ov = inf.setdefault("prompt_overrides", {})
        if body.prompt and body.prompt.strip():
            ov[body.view] = body.prompt.strip()
        else:
            ov.pop(body.view, None)
        the_influencers().save(inf)
    return influencer_view(inf, full=True)


class IdentityIn(BaseModel):
    views: list[str] | None = None
    force: bool = False


@app.post("/api/influencers/{iid}/identity")
def paint_identity(iid: str, body: IdentityIn):
    inf = open_influencer(iid)
    lib_ = the_influencers()
    views = [v for v in (body.views or infl.VIEW_IDS) if v in infl.VIEW_IDS]
    todo = [v for v in views if body.force or not lib_.image(iid, v).exists()]
    if not todo:
        raise HTTPException(400, "Those images already exist")
    needs_face = any(from_face for v, _, from_face, _ in infl.IDENTITY if v in todo)
    if needs_face and "face" not in todo and not lib_.image(iid, "face").exists():
        raise HTTPException(400, "Paint the face first: the other views are painted from it")
    s = current_settings()
    name = inf["profile"]["name"]

    def run(job: Job):
        done = 0
        job.step("image", f"Painting {name}", 0, len(todo), record=False)

        def progress(view, status):
            nonlocal done
            done += 1
            job.log(f"{view}: {status}")
            job.step("image", f"Painting {name}", done, len(todo), record=False)
        res = infl.paint_identity(client_for(s), s, lib_, iid, views=todo, force=body.force,
                                  on_progress=progress)
        failed = {v: r.split(": ", 1)[1] for v, r in res.items() if r.startswith(("failed", "fatal"))}
        with plan_lock(inf_key(iid)):
            cur = lib_.get(iid)
            errs = {v: e for v, e in cur.get("identity_errors", {}).items() if v not in res}
            cur["identity_errors"] = {**errs, **failed}
            lib_.save(cur)
        if failed and len(failed) == len(todo):
            raise RuntimeError(next(iter(failed.values())))
        return {"results": res}

    return submit("identity", f"Painting {name}", inf_key(iid), set(todo), run).view()


class PlaceIn(BaseModel):
    name: str
    description: str


def paint_place_job(iid: str, pid: str, name: str) -> dict:
    s = current_settings()
    lib_ = the_influencers()

    def run(job: Job):
        job.step("image", f"Painting {name}", record=False)
        try:
            infl.paint_place(client_for(s), s, lib_, iid, pid)
            err = None
        except Exception as e:
            err = pl.friendly_error(e)
            raise
        finally:
            with plan_lock(inf_key(iid)):
                cur = lib_.get(iid)
                errs = cur.setdefault("place_errors", {})
                errs.pop(pid, None)
                if err:
                    errs[pid] = err
                lib_.save(cur)
        return {"place": pid}

    claims = {f"place:{pid}"} | ({"setting"} if pid == "home" else set())
    return submit("place", f"Painting {name}", inf_key(iid), claims, run).view()


@app.post("/api/influencers/{iid}/places")
def add_place(iid: str, body: PlaceIn):
    """Save a place they film in, and paint it (an empty plate reused by every video there)."""
    open_influencer(iid)
    if not body.name.strip() or not body.description.strip():
        raise HTTPException(400, "Give the place a name and describe it")
    with plan_lock(inf_key(iid)):
        place = the_influencers().add_place(iid, body.name, body.description)
    return paint_place_job(iid, place["id"], place["name"])


@app.post("/api/influencers/{iid}/places/{pid}/paint")
def repaint_place(iid: str, pid: str):
    inf = open_influencer(iid)
    try:
        place = the_influencers().place(inf, pid)
    except KeyError:
        raise HTTPException(404, f"No place {pid}")
    return paint_place_job(iid, pid, place["name"])


@app.delete("/api/influencers/{iid}/places/{pid}")
def delete_place(iid: str, pid: str):
    open_influencer(iid)
    if f"place:{pid}" in running_claims(inf_key(iid)):
        raise HTTPException(409, "This place is being painted. Wait for it to finish.")
    try:
        with plan_lock(inf_key(iid)):
            the_influencers().remove_place(iid, pid)
    except KeyError:
        raise HTTPException(400 if pid == "home" else 404, "Home can't be removed" if pid == "home" else f"No place {pid}")
    return {"ok": True}


@app.delete("/api/influencers/{iid}")
def delete_influencer(iid: str):
    """To the Recycle Bin, identity pack and videos included."""
    open_influencer(iid)
    if running_claims(inf_key(iid)):
        raise HTTPException(409, "Something for this influencer is still generating. Wait for it to finish.")
    from send2trash import send2trash
    send2trash(str(the_influencers().dir(iid)))
    return {"ok": True}


class NewVideoIn(BaseModel):
    format: str = "talking_head"
    topic: str
    points: str = ""
    length_s: int = 30
    place: str = ""                                  # a saved place id, or ""
    location: str = ""                               # somewhere else, described
    outfit: str = ""
    products: list[dict] = []                        # [{id, use: wear|hold}] worn or held in it


@app.post("/api/influencers/{iid}/videos")
def new_video(iid: str, body: NewVideoIn):
    inf = open_influencer(iid)
    if body.format not in infl.FORMATS:
        raise HTTPException(400, f"Unknown format {body.format}")
    if not body.topic.strip():
        raise HTTPException(400, "What's the video about?")
    if body.place and body.place not in {x["id"] for x in the_influencers().places(inf)}:
        raise HTTPException(404, f"No place {body.place}")
    s = current_settings()

    def run(job: Job):
        job.step("script", f"Writing in {inf['profile']['name']}'s voice")
        proj = infl.write_script(client_for(s), s, the_influencers(), iid, body.format, body.topic.strip(),
                                 body.points.strip(), body.length_s, place=body.place,
                                 location=body.location, outfit=body.outfit, products=body.products)
        job.log(f"Script: {proj.load_plan()['title']}")
        return {"video": proj.root.name}

    return submit("script", "Writing a script", inf_key(iid), {"script"}, run).view()


@app.get("/api/influencers/{iid}/videos/{vid}")
def get_video(iid: str, vid: str):
    return video_view(iid, open_video(iid, vid), full=True)


class ScriptIn(BaseModel):
    title: str | None = None
    caption: str | None = None
    segments: list[dict] | None = None
    format: str | None = None
    setup: dict | None = None


@app.put("/api/influencers/{iid}/videos/{vid}")
def put_script(iid: str, vid: str, body: ScriptIn):
    proj = open_video(iid, vid)
    if vid in running_claims(inf_key(iid)):
        raise HTTPException(409, "This video is being shot. Wait for it to finish.")
    if body.segments is not None and not 1 <= len(body.segments) <= 4:
        raise HTTPException(400, "A reel has 1 to 4 segments (10-40 s)")
    if body.format is not None and body.format not in infl.FORMATS:
        raise HTTPException(400, f"Unknown format {body.format}")
    inf = open_influencer(iid)
    if body.setup and body.setup.get("place") and body.setup["place"] not in {x["id"] for x in the_influencers().places(inf)}:
        raise HTTPException(404, f"No place {body.setup['place']}")

    def apply(plan):
        if body.title is not None:
            plan["title"] = body.title.strip() or plan["title"]
        if body.caption is not None:
            plan["caption"] = body.caption
        if body.segments is not None:
            segs = [{"id": "", "seconds": 10,
                     "lines": [str(x).strip() for x in sg.get("lines", []) if str(x).strip()],
                     "delivery": str(sg.get("delivery", "")).strip(),
                     "action": str(sg.get("action", "")).strip()} for sg in body.segments]
            plan["segments"] = infl.normalize_segments(segs, len(segs) * 10)
            if segs[0]["lines"]:
                plan["hook"] = segs[0]["lines"][0]
            plan.pop("prompt_overrides", None)       # prompts follow the new script
        if body.format is not None:
            plan["format"] = body.format
        if body.setup is not None:
            cur = infl.setup_of(plan, inf["profile"])
            new = {k: str(body.setup.get(k, cur.get(k, ""))).strip() for k in (*infl.SETUP_KEYS, "place")}
            if new["place"] and new["place"] != cur.get("place"):
                new["location"] = the_influencers().place(inf, new["place"])["description"]
            items = body.setup.get("products", cur.get("products", [])) or []
            known = {x["id"] for x in the_products().all()}
            new["products"] = [{"id": str(x.get("id")), "use": x.get("use") if x.get("use") in prod.USES else "hold"}
                               for x in items if isinstance(x, dict) and x.get("id") in known][:2]
            plan["setup"] = new

    update_plan(proj, apply)
    return video_view(iid, proj, full=True)


@app.post("/api/influencers/{iid}/videos/{vid}/opening")
def paint_opening(iid: str, vid: str):
    """(Re)paint the still(s) this video starts from, to check the setup before shooting."""
    open_influencer(iid)
    proj = open_video(iid, vid)
    if not the_influencers().image(iid, "face").exists():
        raise HTTPException(400, "Paint the identity pack first (at least the face)")
    s = current_settings()

    def run(job: Job):
        job.step("image", "Painting the opening frame", record=False)
        try:
            infl.paint_opening(client_for(s), s, the_influencers(), iid, proj)
        except Exception as e:
            record_failures(proj, {"opening": pl.friendly_error(e)})
            raise
        return {"video": vid}

    return submit("opening", "Painting the opening frame", inf_key(iid), {vid}, run).view()


@app.post("/api/influencers/{iid}/videos/{vid}/shoot")
def shoot_video(iid: str, vid: str):
    inf = open_influencer(iid)
    proj = open_video(iid, vid)
    if not the_influencers().image(iid, "face").exists():
        raise HTTPException(400, "Paint the identity pack first (at least the face)")
    s = current_settings()
    vp = providers.video_provider("gemini-omni", s)
    key = video_key(vp.id, vp.resolution_for(s.resolution))

    def run(job: Job):
        def step(kind, label, done, total):
            job.step(kind, label, done, total, key=key if kind == "video" else kind, record=kind != "image")
        try:
            final = infl.shoot_reel(client_for(s), s, the_influencers(), iid, proj, log=job.log, step=step)
        except Exception as e:
            record_failures(proj, {"reel": pl.friendly_error(e)})
            raise
        return {"final": final.name}

    return submit("reel", f"Shooting {inf['profile']['name']}'s video", inf_key(iid), {vid}, run).view()


@app.delete("/api/influencers/{iid}/videos/{vid}")
def delete_video(iid: str, vid: str):
    proj = open_video(iid, vid)
    if vid in running_claims(inf_key(iid)):
        raise HTTPException(409, "This video is being shot. Wait for it to finish.")
    from send2trash import send2trash
    send2trash(str(proj.root))
    return {"ok": True}


@app.get("/api/influencers/{iid}/poster")
def influencer_poster(iid: str, path: str):
    open_influencer(iid)
    root = the_influencers().dir(iid)
    video = (root / path).resolve()
    if root.resolve() not in video.parents or video.suffix != ".mp4" or not video.exists():
        raise HTTPException(404, "No such video")
    return poster_file(video, video.parent / "posters" / f"{video.stem}.jpg")


# --------------------------------------------------------------------------
# API: the small editor (trim, colour, audio) for a finished film or video
# --------------------------------------------------------------------------

def edit_view(proj: pl.Project, url_of) -> dict | None:
    final = proj.root / "final.mp4"
    if not final.exists():
        return None
    edited = proj.root / "edited.mp4"
    plan = proj.load_plan()
    return {"params": {**editor.DEFAULTS, **plan.get("edit", {})},
            "url": url_of(edited) if edited.exists() else None,
            "stale": edited.exists() and edited.stat().st_mtime < final.stat().st_mtime,
            "duration_s": pl.video_duration(final)}


class EditIn(BaseModel):
    params: dict


def export_job(proj: pl.Project, project_key: str, claims: set[str], params: dict,
               with_captions: bool = False) -> dict:
    final = proj.root / "final.mp4"
    if not final.exists():
        raise HTTPException(400, "There's no finished video to edit yet")
    duration = pl.video_duration(final)
    try:
        e = editor.clean(params, duration)
    except ValueError as err:
        raise HTTPException(400, str(err))
    caps = cap.state(proj.load_plan(), duration, font_book().ids()) if with_captions else None
    burn = bool(caps and caps["enabled"] and caps["words"])

    def run(job: Job):
        edited = proj.root / "edited.mp4"
        subtitles = None
        if burn:
            w, h = video_size(final)
            font = font_book().get(caps["style"]["font"])
            fonts_dir = proj.root / "_fonts"                 # just the one font, bundled or imported
            shutil.rmtree(fonts_dir, ignore_errors=True)
            fonts_dir.mkdir()
            shutil.copy2(font["path"], fonts_dir / font["path"].name)
            ass_file = proj.root / "captions.ass"
            ass_file.write_text(cap.ass(caps["words"], caps["style"], w, h, e["start"], e["end"] or duration, font=font),
                                encoding="utf-8")
            subtitles = cap.subtitles_filter(ass_file, fonts_dir)
        if editor.is_identity(e) and not burn:
            edited.unlink(missing_ok=True)
            with plan_lock(proj.root.name):
                plan = proj.load_plan()
                plan.pop("edit", None)
                proj.save_plan(plan)
            job.log("Edit cleared: the original is the video again")
            return {"edited": False}
        job.step("export", "Exporting the edit" + (" with captions" if burn else ""))
        editor.render(final, edited, e, subtitles=subtitles)
        with plan_lock(proj.root.name):
            plan = proj.load_plan()
            plan["edit"] = e
            proj.save_plan(plan)
        job.log(f"Exported {edited.name}")
        return {"edited": True}

    return submit("export", "Exporting the edit", project_key, claims, run).view()


@app.put("/api/projects/{pid}/edit")
def edit_film(pid: str, body: EditIn):
    return export_job(open_project(pid), pid, {"export"}, body.params)


@app.put("/api/influencers/{iid}/videos/{vid}/edit")
def edit_video(iid: str, vid: str, body: EditIn):
    proj = open_video(iid, vid)
    return export_job(proj, inf_key(iid), {vid}, body.params, with_captions=True)


def video_size(path: Path) -> tuple[int, int]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        w, h = (int(x) for x in r.stdout.strip().split(",")[:2])
        return w, h
    except ValueError:
        return 720, 1280


# --------------------------------------------------------------------------
# API: captions (the script's words, burned in on export)
# --------------------------------------------------------------------------

def presets_path() -> Path:
    return Path(CONFIG["library"]) / "caption_presets.json"


def user_presets() -> list[dict]:
    try:
        return json.loads(presets_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def font_book() -> fb.FontBook:
    return fb.FontBook(CONFIG["library"])


@app.get("/api/captions")
def captions_catalog():
    ids = font_book().ids()
    return {"fonts": font_book().view(), "animations": [{"id": k, "label": v} for k, v in cap.ANIMATIONS.items()],
            "defaults": cap.STYLE_DEFAULTS,
            "presets": [{**p, "style": cap.clean_style(p["style"], ids), "builtin": True} for p in cap.PRESETS]
                       + [{**p, "style": cap.clean_style(p["style"], ids), "builtin": False} for p in user_presets()],
            "popular": [{"family": f, "weight": w, "label": f"{f} {fb.WEIGHTS[w]}" if w != 400 else f}
                        for f, w in fb.POPULAR]}


@app.post("/api/captions/fonts/upload")
async def upload_font(request: Request, filename: str = "font.ttf"):
    """A .ttf/.otf, sent as the raw request body."""
    data = await request.body()
    try:
        font = font_book().add(data, filename)
    except fb.FontError as e:
        raise HTTPException(400, str(e))
    return {**captions_catalog(), "added": {k: v for k, v in font.items() if k != "path"}}


@app.get("/api/captions/fonts/google")
def search_google_fonts(q: str = ""):
    try:
        return {"results": font_book().search_google(q)}
    except Exception as e:                           # noqa: BLE001 - offline, blocked, ...
        raise HTTPException(502, f"Couldn't reach Google Fonts: {e}")


class GoogleFontIn(BaseModel):
    family: str
    weight: int = 400


@app.post("/api/captions/fonts/google")
def import_google_font(body: GoogleFontIn):
    if not body.family.strip():
        raise HTTPException(400, "Which font?")
    try:
        font = font_book().add_google(body.family, body.weight)
    except fb.FontError as e:
        raise HTTPException(400, str(e))
    return {**captions_catalog(), "added": {k: v for k, v in font.items() if k != "path"}}


@app.delete("/api/captions/fonts/{fid}")
def delete_font(fid: str):
    try:
        font_book().remove(fid)
    except KeyError:
        raise HTTPException(404, "No such font (bundled fonts can't be removed)")
    return captions_catalog()


class PresetIn(BaseModel):
    name: str
    style: dict


@app.post("/api/captions/presets")
def save_preset(body: PresetIn):
    name = body.name.strip()[:40]
    if not name:
        raise HTTPException(400, "Name the preset")
    presets = [p for p in user_presets() if p["name"].lower() != name.lower()]
    pid = "user-" + (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "preset")
    presets.append({"id": pid, "name": name, "style": cap.clean_style(body.style, font_book().ids())})
    presets_path().parent.mkdir(parents=True, exist_ok=True)
    presets_path().write_text(json.dumps(presets, indent=2), encoding="utf-8")
    return captions_catalog()


@app.delete("/api/captions/presets/{pid}")
def delete_preset(pid: str):
    presets = user_presets()
    if pid not in {p["id"] for p in presets}:
        raise HTTPException(404, "No such preset (built-in presets can't be deleted)")
    presets_path().write_text(json.dumps([p for p in presets if p["id"] != pid], indent=2), encoding="utf-8")
    return captions_catalog()


class CaptionsIn(BaseModel):
    enabled: bool | None = None
    style: dict | None = None
    words: list[dict] | None = None                  # edited text/timing
    reset: bool = False                              # back to the script, estimated timing


@app.put("/api/influencers/{iid}/videos/{vid}/captions")
def put_captions(iid: str, vid: str, body: CaptionsIn):
    proj = open_video(iid, vid)
    final = proj.root / "final.mp4"
    duration = pl.video_duration(final) if final.exists() else None

    def apply(plan):
        ids = font_book().ids()
        st = cap.state(plan, duration, ids)
        if body.reset:
            plan.pop("captions", None)
            st = {**cap.state(plan, duration, ids), "enabled": st["enabled"], "style": st["style"]}
        if body.enabled is not None:
            st["enabled"] = body.enabled
        if body.style is not None:
            st["style"] = cap.clean_style(body.style, ids)
        if body.words is not None:
            words = [{"text": str(w.get("text", "")).strip(), "start": w.get("start"), "end": w.get("end"),
                      "seg": int(w.get("seg", 0)), "br": bool(w.get("br", False))} for w in body.words]
            words = [w for w in words if w["text"]]
            if not words:
                raise HTTPException(400, "Captions need at least one word")
            st["words"] = cap.fix_times(words, duration or max(w["end"] or 0 for w in words))
        plan["captions"] = st

    update_plan(proj, apply)
    return video_view(iid, proj, full=True)


@app.post("/api/influencers/{iid}/videos/{vid}/captions/sync")
def sync_captions(iid: str, vid: str):
    """Time the caption words to the voice. The words stay exactly as they are."""
    proj = open_video(iid, vid)
    final = proj.root / "final.mp4"
    if not final.exists():
        raise HTTPException(400, "Shoot the video first")
    s = current_settings()

    def run(job: Job):
        job.step("sync", "Syncing captions to the voice")
        duration = pl.video_duration(final)
        st = cap.state(proj.load_plan(), duration)
        words, diffs, usage = cap.align(client_for(s), s, final, st["words"], duration)
        proj.log(kind="captions", model=s.planner_model, usage=usage, cost_usd=pl.call_cost(s.planner_model, usage))

        def apply(plan):
            cur = cap.state(plan, duration)
            if cur["script_key"] != st["script_key"]:
                raise RuntimeError("The script changed while syncing; sync again.")
            plan["captions"] = {**cur, "words": words, "synced": "voice", "differences": diffs, "synced_at": time.time()}
        update_plan(proj, apply)
        job.log(f"Synced {len(words)} words" + (f"; {len(diffs)} places differ from the script" if diffs else ""))
        return {"differences": len(diffs)}

    return submit("sync", "Syncing captions", inf_key(iid), {vid}, run).view()


@app.get("/api/jobs")
def list_jobs(project: str | None = None):
    jobs = [j for j in JOBS.values() if project is None or j.project == project]
    jobs.sort(key=lambda j: j.started, reverse=True)
    return [j.view() for j in jobs[:50]]


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    if jid not in JOBS:
        raise HTTPException(404, "No such job")
    return JOBS[jid].view()


# --------------------------------------------------------------------------
# Files + web UI
# --------------------------------------------------------------------------

class _ProjectFiles(StaticFiles):
    """Project folder files; resolved per request so tests/launch can change the folder."""

    def __init__(self):
        super().__init__(directory=str(ROOT), check_dir=False)

    def get_path(self, scope):                       # noqa: D401
        self.directory = str(projects_dir())
        self.all_directories = [self.directory]
        return super().get_path(scope)


app.mount("/files", _ProjectFiles(), name="files")


class _LibraryFiles(StaticFiles):
    def __init__(self):
        super().__init__(directory=str(ROOT), check_dir=False)

    def get_path(self, scope):                       # noqa: D401
        self.directory = str(the_library().root)
        self.all_directories = [self.directory]
        return super().get_path(scope)


app.mount("/library-files", _LibraryFiles(), name="library-files")
app.mount("/fonts", StaticFiles(directory=str(cap.FONTS_DIR), check_dir=False), name="fonts")


class _UserFonts(StaticFiles):
    def __init__(self):
        super().__init__(directory=str(ROOT), check_dir=False)

    def get_path(self, scope):                       # noqa: D401
        self.directory = str(font_book().dir)
        self.all_directories = [self.directory]
        return super().get_path(scope)


app.mount("/user-fonts", _UserFonts(), name="user-fonts")


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def unknown_api(path: str):
    """Registered last: an API call this server doesn't know, e.g. from a newer UI."""
    raise HTTPException(404, f"This ReelForge server doesn't know /api/{path}. If ReelForge was just "
                             "updated, restart it (close its window and run ReelForge.bat again).")


def mount_web() -> None:
    """Serve the exported Next.js UI at / (called by launch.py once it's built)."""
    if (WEB_DIST / "index.html").exists() and not any(getattr(r, "name", "") == "web" for r in app.routes):
        app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="web")


# --------------------------------------------------------------------------
# Demo mode: a fake client so the UI can be tried without spending anything
# --------------------------------------------------------------------------

_fake = None


def _fake_client():
    global _fake
    if _fake is None:
        import sys
        sys.path.insert(0, str(ROOT / "tests"))
        from fakes import FakeClient, demo_clip
        _fake = FakeClient(demo_clip(projects_dir() / ".demo_clip.mp4"), delay=True)
    return _fake


def enable_demo() -> None:
    """Fake Gemini and a fake Kling API: every screen works and nothing is billed."""
    import sys
    import providers.kling as kling
    sys.path.insert(0, str(ROOT / "tests"))
    from fakes import FakeKling, demo_clip
    CONFIG["fake"] = True
    kling.TRANSPORT = FakeKling(demo_clip(projects_dir() / ".demo_clip.mp4"), delay=True).transport
    os.environ.setdefault("KLING_API_KEY", "demo")
