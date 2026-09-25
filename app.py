"""ReelForge UI.  Run:  streamlit run app.py"""
import json
import os
import shutil
from pathlib import Path

import streamlit as st

import pipeline as pl

BASE = Path("projects")
BASE.mkdir(exist_ok=True)
st.set_page_config(page_title="ReelForge", layout="wide")
state = st.session_state


def flash(kind: str, msg: str) -> None:
    """Queue a message that survives the next st.rerun()."""
    state.setdefault("flash", []).append((kind, msg))


def attempt(spinner: str, fn):
    """Run a generation step; on failure show one readable line instead of a traceback."""
    try:
        with st.spinner(spinner):
            return fn()
    except Exception as e:
        st.error(pl.friendly_error(e))
        return None


def report_assets(results: dict) -> None:
    bad = {i: st_ for i, st_ in results.items() if st_.startswith(("failed", "fatal"))}
    for i, why in bad.items():
        flash("error", f"{i}: {why}")
    done = sum(v == "done" for v in results.values())
    if done:
        flash("success", f"Generated {done} reference image{'s' * (done != 1)}.")


# ---------------- sidebar: settings + project picker ----------------
with st.sidebar:
    st.header("Settings")
    defaults = pl.Settings()
    backend = st.radio("Backend", ["gemini", "vertex"], horizontal=True,
                       index=["gemini", "vertex"].index(defaults.backend),
                       help="gemini = AI Studio API key. vertex = bills a GCP project (GCP credits apply).")
    if backend == "vertex":
        gcp_project = st.text_input("GCP project", defaults.gcp_project)
        gcp_location = st.text_input("GCP location", defaults.gcp_location)
        api_key = st.text_input("Vertex API key (optional, else gcloud ADC)",
                                value=os.environ.get("VERTEX_API_KEY", ""), type="password")
    else:
        gcp_project, gcp_location = defaults.gcp_project, defaults.gcp_location
        api_key = st.text_input("Gemini API key", value=os.environ.get("GEMINI_API_KEY", ""),
                                type="password")
    s = pl.Settings(
        backend=backend, gcp_project=gcp_project, gcp_location=gcp_location,
        # keyed by backend so switching backend resets these to that backend's ids
        planner_model=st.text_input("Planner model", pl.Settings.MODELS[backend]["planner_model"],
                                    key=f"pm_{backend}"),
        image_model=st.text_input("Image model", pl.Settings.MODELS[backend]["image_model"],
                                  key=f"im_{backend}"),
        video_model=st.text_input("Video model", pl.Settings.MODELS[backend]["video_model"],
                                  key=f"vm_{backend}"),
        orientation=st.radio("Orientation (new films)", ["9:16", "16:9"], horizontal=True),
        resolution=st.selectbox("Video resolution", ["360p", "720p", "1080p", "4k"], index=1,
                                help="720p for real films, 360p for cheap tests"),
        image_size=st.selectbox("Image size", ["1K", "2K", "4K"], index=1,
                                help="1K and 2K cost the same; 4K costs more"),
    )
    if not shutil.which("ffmpeg"):
        st.warning("ffmpeg not found: continuous scenes and stitching won't work. "
                   "Install it, then restart the app.")
    st.divider()
    existing = sorted([p.name for p in BASE.iterdir() if (p / "plan.json").exists()], reverse=True)
    if "open_next" in state:                  # a project just created: open it
        state["pick"] = state.pop("open_next")
    pick = st.selectbox("Open project", ["— new —"] + existing, key="pick")

client_error = None
try:
    client = pl.make_client(s, api_key) if (api_key or backend == "vertex") else None
except Exception as e:
    client, client_error = None, pl.friendly_error(e)
proj = None if pick == "— new —" else pl.Project.open(BASE / pick)

for kind, msg in state.pop("flash", []):
    getattr(st, kind)(msg)


def need_client():
    if not client:
        st.error(client_error or "Add your Gemini API key in the sidebar first.")
        st.stop()


# ---------------- new project ----------------
if proj is None:
    st.title("New film")
    story = st.text_area("Story or idea", height=180,
                         placeholder="A solo rider caught in snow on a Himalayan pass shelters in an old woman's tent dhaba…")
    style = st.text_area("Style", height=80,
                         placeholder="Photoreal, 35mm film grain, cool blue exteriors, warm amber interiors")
    n = st.slider("Scenes", 3, 12, 6)
    c1, c2 = st.columns(2)
    if c1.button("Write the plan", type="primary", disabled=not story.strip()):
        need_client()
        p = attempt("Directing…", lambda: pl.new_project(client, s, story, style, n, BASE))
        if p:
            flash("success", f"Plan ready ({pl.format_costs(pl.project_costs(p))}). "
                             "Review it before generating anything.")
            state["open_next"] = p.root.name
            st.rerun()
    if c2.button("Make the whole film (no checkpoints)", disabled=not story.strip(),
                 help="Plans, then makes every reference and scene at the sidebar settings. "
                      "Spend is shown as it goes; an unfinished film can be resumed."):
        need_client()
        box, logs = st.empty(), []

        def log(msg):
            logs.append(msg)
            box.code("\n".join(logs))
        res = attempt("Making the film… this takes a while",
                      lambda: pl.run_all(story, style, s, BASE, n, api_key, log=log))
        if res:
            p, result = res
            if result["failed"]:
                st.warning(f"Unfinished: {', '.join(result['failed'])}. Open the project to "
                           "fix those, or use 'Make everything missing' in its Final cut tab.")
            else:
                st.success(f"Done: {p.root}")
    st.stop()

# ---------------- existing project ----------------
plan = proj.load_plan()
st.title(plan["title"])
st.caption(plan["logline"])
st.caption(f"{plan.get('orientation', '?')} · spent so far: {pl.format_costs(pl.project_costs(proj))}")
tab_plan, tab_assets, tab_scenes, tab_final = st.tabs(["Plan", "References", "Scenes", "Final cut"])

with tab_plan:
    st.write("Edit anything, then save. Asset and scene prompts are rebuilt from this plan.")
    txt = st.text_area("plan.json", json.dumps(plan, indent=2, ensure_ascii=False), height=600)
    if st.button("Save plan"):
        try:
            proj.save_plan(json.loads(txt))
            flash("success", "Saved.")
            st.rerun()
        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {e}")

with tab_assets:
    n_missing = sum(not proj.asset_path(j["id"]).exists() for j in pl.asset_jobs(plan))
    if st.button(f"Generate missing references ({n_missing}, ≈${pl.estimate_image_usd(s, n_missing):.2f})",
                 type="primary", disabled=not n_missing):
        need_client()
        res = attempt("Painting reference sheets…", lambda: pl.generate_assets(client, s, proj))
        if res is not None:
            report_assets(res)
            st.rerun()
    overrides = plan.setdefault("prompt_overrides", {})
    for job in pl.asset_jobs(plan):
        with st.container(border=True):
            left, right = st.columns([1, 1])
            path = proj.asset_path(job["id"])
            with left:
                st.subheader(job["id"])
                if path.exists():
                    st.image(str(path))
                else:
                    st.info("Not generated yet.")
            with right:
                new = st.text_area("Prompt", job["prompt"], key=f"ap_{job['id']}", height=220)
                if st.button(f"Regenerate (≈${pl.estimate_image_usd(s):.2f})", key=f"ar_{job['id']}"):
                    need_client()
                    if new != job["prompt"]:
                        overrides[job["id"]] = new
                        proj.save_plan(plan)
                    res = attempt("Generating…", lambda: pl.generate_assets(
                        client, s, proj, only=[job["id"]], skip_existing=False))
                    if res is not None:
                        report_assets(res)
                        st.rerun()

with tab_scenes:
    missing = [j["id"] for j in pl.asset_jobs(plan) if not proj.asset_path(j["id"]).exists()]
    if missing:
        st.warning(f"Missing references: {', '.join(missing)}. Scenes shot now will run without them.")
    overrides = plan.setdefault("prompt_overrides", {})
    sel = plan.setdefault("selected_takes", {})
    for sc in plan["scenes"]:
        with st.container(border=True):
            st.subheader(f"{sc['id']} · {sc['duration_s']}s · {sc['continuity']}")
            st.write(sc["action"])
            prompt, _, refs = pl.build_scene_request(plan, proj, sc)
            cols = st.columns(max(len(refs), 1))
            for c, r in zip(cols, refs):
                c.image(str(proj.asset_path(r)), caption=r)
            new = st.text_area("Prompt sent to Omni", prompt, key=f"sp_{sc['id']}", height=220)
            est = pl.estimate_video_usd(s, sc["duration_s"])
            if st.button(f"Shoot a take ({s.resolution}, ≈${est:.2f})", key=f"st_{sc['id']}", type="primary"):
                need_client()
                if new != prompt:
                    overrides[sc["id"]] = new
                    proj.save_plan(plan)
                out = attempt("Rolling… this can take a few minutes",
                              lambda: pl.generate_take(client, s, proj, sc["id"]))
                if out:
                    sel[sc["id"]] = out.name
                    proj.save_plan(plan)
                    st.rerun()

            takes = proj.takes(sc["id"])
            if takes:
                names = [t.name for t in takes]
                cur = sel.get(sc["id"], names[-1])
                choice = st.radio("Takes", names, index=names.index(cur) if cur in names else len(names) - 1,
                                  horizontal=True, key=f"tk_{sc['id']}")
                if choice != sel.get(sc["id"]):
                    sel[sc["id"]] = choice
                    proj.save_plan(plan)
                take = proj.scene_dir(sc["id"]) / choice
                st.video(str(take))
                fix = st.text_input("Fix this take (e.g. 'make the snowfall heavier')",
                                    key=f"fx_{sc['id']}")
                # an edit comes back at the source take's resolution
                tmeta = json.loads(take.with_suffix(".json").read_text(encoding="utf-8"))
                tres = pl.Settings(backend=backend, video_model=s.video_model,
                                   resolution=tmeta["format"]["resolution"])
                est = pl.estimate_video_usd(tres, tmeta.get("duration_s") or sc["duration_s"])
                st.caption(f"This take: {tmeta.get('duration_s', '?')}s, {tmeta['format']['resolution']}, "
                           f"cost ${tmeta['cost_usd']:.2f}" if tmeta.get("cost_usd") is not None else
                           f"This take: {tmeta['format']['resolution']}, cost not recorded")
                if st.button(f"Apply fix (≈${est:.2f})", key=f"fb_{sc['id']}", disabled=not fix.strip()):
                    need_client()
                    out = attempt("Editing…", lambda: pl.edit_take(client, s, proj, sc["id"], take, fix))
                    if out:
                        sel[sc["id"]] = out.name
                        proj.save_plan(plan)
                        st.rerun()

with tab_final:
    rem = pl.estimate_remaining(proj, s)
    if rem["refs"] or rem["scenes"]:
        st.write(f"Still to make: {len(rem['refs'])} references, {len(rem['scenes'])} scenes "
                 f"({rem['video_s']}s at {s.resolution}).")
        if st.button(f"Make everything missing, then stitch (≈${rem['usd']:.2f})", type="primary"):
            need_client()
            box, logs = st.empty(), []

            def log(msg):
                logs.append(msg)
                box.code("\n".join(logs))
            result = attempt("Producing… this takes a while", lambda: pl.produce(client, s, proj, log=log))
            if result and result["failed"]:
                st.warning("Unfinished: " + "; ".join(f"{k}: {v}" for k, v in result["failed"].items()))
            elif result:
                st.success("All scenes shot and stitched.")
    if st.button("Stitch selected takes", type="primary" if not rem["scenes"] else "secondary"):
        out = attempt("Stitching…", lambda: pl.stitch(proj))
        if out:
            st.video(str(out))
    elif (proj.root / "final.mp4").exists():
        st.video(str(proj.root / "final.mp4"))
