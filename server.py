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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import pipeline as pl

ROOT = Path(__file__).resolve().parent
WEB_DIST = ROOT / "web" / "out"
PREFS_PATH = ROOT / "reelforge.settings.json"          # UI settings; gitignored

# configured by launch.py (or tests) before the app serves requests
CONFIG = {"projects": ROOT / "projects", "fake": False}

app = FastAPI(title="ReelForge")
# the Next dev server (npm run dev) runs on another port
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["*"], allow_headers=["*"])


def projects_dir() -> Path:
    d = Path(CONFIG["projects"])
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------
# Settings (env defaults from pipeline.Settings, overridden by the UI's saved prefs)
# --------------------------------------------------------------------------

PREF_KEYS = ("backend", "gcp_project", "gcp_location", "resolution", "image_size", "orientation")
MODEL_KEYS = ("planner_model", "image_model", "video_model")


def load_prefs() -> dict:
    try:
        return json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def current_settings(prefs: dict | None = None) -> pl.Settings:
    p = load_prefs() if prefs is None else prefs
    kw = {k: p[k] for k in PREF_KEYS if p.get(k)}
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

    def log(self, msg: str) -> None:
        self.logs.append(msg)

    def view(self) -> dict:
        return {"id": self.id, "kind": self.kind, "label": self.label, "project": self.project,
                "claims": sorted(self.claims), "status": self.status, "logs": self.logs[-200:],
                "error": self.error, "result": self.result, "started": self.started,
                "finished": self.finished}


JOBS: dict[str, Job] = {}
_jobs_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=8)
# last failure per (project, item) so a card can say why it has no image/take
LAST_ERRORS: dict[tuple[str, str], str] = {}


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
            "prompt": meta.get("prompt"), "created": take.stat().st_mtime}


KIND_SINGULAR = {"characters": "character", "props": "prop", "environments": "environment"}


def project_view(proj: pl.Project) -> dict:
    plan = proj.load_plan()
    pid = proj.root.name
    idx = pl._lookup(plan)
    busy = running_claims(pid)
    overrides = plan.get("prompt_overrides", {})
    defaults = {j["id"]: j["prompt"] for j in pl.asset_jobs({**plan, "prompt_overrides": {}})}

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
            "error": LAST_ERRORS.get((pid, j["id"])),
        })

    scenes = []
    for sc in plan["scenes"]:
        prompt, _, refs_used = pl.build_scene_request(plan, proj, sc, extract=False)
        default_prompt = pl.build_scene_request(
            {**plan, "prompt_overrides": {}}, proj, sc, extract=False)[0]
        takes = proj.takes(sc["id"])
        sel = pl.selected_take(plan, proj, sc["id"])
        generating = sc["id"] in busy or ("*" in busy and not takes)
        scenes.append({
            **{k: v for k, v in sc.items()},
            "prompt": prompt, "default_prompt": default_prompt,
            "overridden": sc["id"] in overrides, "refs_used": refs_used,
            "refs_missing": [r for r in sc["refs"] if r in idx and r not in refs_used],
            "takes": [take_view(proj, t) for t in takes],
            "selected": sel.name if sel else None,
            "status": "generating" if generating else ("done" if takes else "missing"),
            "error": LAST_ERRORS.get((pid, sc["id"])),
        })

    final = proj.root / "final.mp4"
    return {
        "id": pid, "plan": plan, "orientation": plan.get("orientation", "16:9"),
        "assets": assets, "scenes": scenes,
        "final": {"url": file_url(proj, final), "poster": poster_url(proj, final),
                  "duration_s": pl.video_duration(final), "updated": final.stat().st_mtime}
        if final.exists() else None,
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
            "fake": CONFIG["fake"], "projects_dir": str(projects_dir())}


class SettingsIn(BaseModel):
    backend: str | None = None
    gcp_project: str | None = None
    gcp_location: str | None = None
    resolution: str | None = None
    image_size: str | None = None
    orientation: str | None = None
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
        current_settings(prefs)
    except (KeyError, TypeError, ValueError) as e:
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
    auto: bool = False                               # plan, then make everything


@app.post("/api/projects")
def create_project(body: NewFilm):
    if not body.story.strip():
        raise HTTPException(400, "Write a story or idea first.")
    s = current_settings()
    if body.orientation:
        s.orientation = body.orientation

    def run(job: Job):
        client = client_for(s)
        job.log("Writing the production plan…")
        proj = pl.new_project(client, s, body.story.strip(), body.style.strip(),
                              max(1, min(body.scenes, 20)), projects_dir())
        job.project = proj.root.name
        job.claims = {"*"}
        job.log(f"Plan ready: {proj.load_plan()['title']}")
        if body.auto:
            result = pl.produce(client, s, proj, log=job.log)
            record_failures(proj.root.name, result["failed"])
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
        keep = {k: plan[k] for k in ("prompt_overrides", "selected_takes", "orientation") if k in plan}
        plan.clear()
        plan.update({**body.plan, **keep})
    update_plan(proj, apply)
    return project_view(proj)


class PromptIn(BaseModel):
    id: str
    prompt: str | None = None                        # None = back to the generated prompt


@app.put("/api/projects/{pid}/prompt")
def put_prompt(pid: str, body: PromptIn):
    proj = open_project(pid)

    def apply(plan):
        ov = plan.setdefault("prompt_overrides", {})
        if body.prompt and body.prompt.strip():
            ov[body.id] = body.prompt.strip()
        else:
            ov.pop(body.id, None)
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


def record_failures(pid: str, failed: dict) -> None:
    for item, why in failed.items():
        LAST_ERRORS[(pid, item)] = why


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
        for i in ids:
            LAST_ERRORS.pop((pid, i), None)
        res = pl.generate_assets(client_for(s), s, proj, only=ids if (body.ids or body.force) else None,
                                 skip_existing=not body.force,
                                 on_progress=lambda i, st: job.log(f"{i}: {st}"))
        bad = {i: st for i, st in res.items() if st.startswith(("failed", "fatal"))}
        record_failures(pid, {i: st.split(": ", 1)[1] for i, st in bad.items()})
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

    def run(job: Job):
        LAST_ERRORS.pop((pid, sid), None)
        job.log(f"Shooting {sid} at {s.resolution}…")
        try:
            out = pl.generate_take(client_for(s), s, proj, sid)
        except Exception as e:
            LAST_ERRORS[(pid, sid)] = pl.friendly_error(e)
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

    def run(job: Job):
        LAST_ERRORS.pop((pid, sid), None)
        job.log(f"Editing {sid}/{take}: {body.instruction.strip()}")
        try:
            out = pl.edit_take(client_for(s), s, proj, sid, src, body.instruction)
        except Exception as e:
            LAST_ERRORS[(pid, sid)] = pl.friendly_error(e)
            raise
        update_plan(proj, lambda plan: plan.setdefault("selected_takes", {}).__setitem__(sid, out.name))
        return {"take": out.name}

    return submit("edit", f"Fixing {sid}", pid, {sid}, run).view()


@app.post("/api/projects/{pid}/produce")
def produce(pid: str):
    proj = open_project(pid)
    s = current_settings()

    def run(job: Job):
        result = pl.produce(client_for(s), s, proj, log=job.log)
        record_failures(pid, result["failed"])
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
        out = pl.stitch(proj)
        job.log(f"Final cut: {out.name}")
        return {"final": out.name}

    return submit("stitch", "Stitching the final cut", pid, {"stitch"}, run).view()


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
    out = proj.root / "frames" / "posters" / (path.replace("/", "_").removesuffix(".mp4") + ".jpg")
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
