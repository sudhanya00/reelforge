"""ReelForge UI.  Run:  streamlit run app.py"""
import json
import os
from pathlib import Path

import streamlit as st

import pipeline as pl

BASE = Path("projects")
BASE.mkdir(exist_ok=True)
st.set_page_config(page_title="ReelForge", layout="wide")

# ---------------- sidebar: settings + project picker ----------------
with st.sidebar:
    st.header("Settings")
    api_key = st.text_input("Gemini API key", value=os.environ.get("GEMINI_API_KEY", ""),
                            type="password")
    s = pl.Settings(
        planner_model=st.text_input("Planner model", pl.Settings.planner_model),
        image_model=st.text_input("Image model", pl.Settings.image_model),
        video_model=st.text_input("Video model", pl.Settings.video_model),
        orientation=st.radio("Orientation", ["16:9", "9:16"], horizontal=True),
        resolution=st.selectbox("Video resolution", ["360p", "720p", "1080p", "4k"], index=1),
        image_size=st.selectbox("Image size", ["1K", "2K", "4K"], index=1),
    )
    st.divider()
    existing = sorted([p.name for p in BASE.iterdir() if (p / "plan.json").exists()], reverse=True)
    pick = st.selectbox("Open project", ["— new —"] + existing)

client = pl.make_client(api_key) if api_key else None
proj = None if pick == "— new —" else pl.Project(BASE / pick)


def need_client():
    if not client:
        st.error("Add your Gemini API key in the sidebar first.")
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
    if c1.button("Write the plan", type="primary"):
        need_client()
        with st.spinner("Directing…"):
            plan = pl.plan_story(client, s, story, style, n)
        p = pl.Project.new(BASE, plan["title"])
        p.save_plan(plan)
        st.success(f"Plan ready: {p.root.name}. Pick it in the sidebar to review.")
    if c2.button("Make the whole film (no checkpoints)"):
        need_client()
        box = st.empty()
        logs = []
        def log(msg):
            logs.append(msg); box.code("\n".join(logs))
        p = pl.run_all(story, style, s, BASE, n, api_key, log=log)
        st.success(f"Done: {p.root}")
    st.stop()

# ---------------- existing project ----------------
plan = proj.load_plan()
st.title(plan["title"])
st.caption(plan["logline"])
tab_plan, tab_assets, tab_scenes, tab_final = st.tabs(["Plan", "References", "Scenes", "Final cut"])

with tab_plan:
    st.write("Edit anything, then save. Asset and scene prompts are rebuilt from this plan.")
    txt = st.text_area("plan.json", json.dumps(plan, indent=2, ensure_ascii=False), height=600)
    if st.button("Save plan"):
        try:
            proj.save_plan(json.loads(txt)); st.success("Saved."); st.rerun()
        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {e}")

with tab_assets:
    if st.button("Generate missing references", type="primary"):
        need_client()
        with st.spinner("Painting reference sheets…"):
            pl.generate_assets(client, s, proj)
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
                if st.button("Regenerate", key=f"ar_{job['id']}"):
                    need_client()
                    if new != job["prompt"]:
                        overrides[job["id"]] = new
                        proj.save_plan(plan)
                    with st.spinner("Generating…"):
                        pl.generate_assets(client, s, proj, only=[job["id"]], skip_existing=False)
                    st.rerun()

with tab_scenes:
    missing = [j["id"] for j in pl.asset_jobs(plan) if not proj.asset_path(j["id"]).exists()]
    if missing:
        st.warning(f"Missing references: {', '.join(missing)}. Scenes will run without them.")
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
            if st.button("Shoot a take", key=f"st_{sc['id']}", type="primary"):
                need_client()
                if new != prompt:
                    overrides[sc["id"]] = new
                    proj.save_plan(plan)
                with st.spinner("Rolling… this can take a few minutes"):
                    out = pl.generate_take(client, s, proj, sc["id"])
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
                    sel[sc["id"]] = choice; proj.save_plan(plan)
                take = proj.scene_dir(sc["id"]) / choice
                st.video(str(take))
                fix = st.text_input("Fix this take (e.g. 'make the snowfall heavier')",
                                    key=f"fx_{sc['id']}")
                if st.button("Apply fix", key=f"fb_{sc['id']}") and fix:
                    need_client()
                    with st.spinner("Editing…"):
                        out = pl.edit_take(client, s, proj, sc["id"], take, fix)
                    sel[sc["id"]] = out.name; proj.save_plan(plan)
                    st.rerun()

with tab_final:
    if st.button("Stitch selected takes", type="primary"):
        try:
            out = pl.stitch(proj); st.video(str(out))
        except Exception as e:
            st.error(str(e))
    elif (proj.root / "final.mp4").exists():
        st.video(str(proj.root / "final.mp4"))
