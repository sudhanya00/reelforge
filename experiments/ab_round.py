"""A/B round: planner v1 vs v2 on the same story, references and scenes (see docs/RND.md).

  python experiments/ab_round.py prepare  SRC_PROJECT      # paint missing refs, make the v2 copy
  python experiments/ab_round.py fresh    STORY STYLE N --preset P --orientation 9:16
                                           # plan the same story with v1 and with v2, paint both
  python experiments/ab_round.py shoot    V1 V2 s01 s03 s06 --takes 2
  python experiments/ab_round.py review   V1 V2 s01 s03 s06
  python experiments/ab_round.py report   V1 V2 s01 s03 s06

Only the plan differs between the two projects: same ids, same reference images, same video
model and resolution. Results land in each take's json (review + motion) and in the report.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8", errors="replace")

import pipeline as pl  # noqa: E402
import review  # noqa: E402

PROJECTS = ROOT / "projects"


def settings() -> pl.Settings:
    return pl.Settings(resolution="360p", image_size="2K")


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def prepare(src_id: str) -> None:
    s, c = settings(), None
    c = pl.make_client(s)
    src = pl.Project.open(PROJECTS / src_id)
    log(f"painting missing references in {src_id}")
    res = pl.generate_assets(c, s, src, on_progress=lambda i, st: log(f"  {i}: {st}"))
    bad = {k: v for k, v in res.items() if v.startswith(("failed", "fatal"))}
    if bad:
        sys.exit(f"reference failures: {bad}")

    dst = PROJECTS / f"{src_id}-v2ab"
    if dst.exists():
        sys.exit(f"{dst} already exists")
    (dst / "assets").mkdir(parents=True)
    for f in (src.root / "assets").glob("*.png"):
        shutil.copy2(f, dst / "assets" / f.name)
    plan = src.load_plan()
    for k in ("selected_takes", "prompt_overrides", "video_providers"):
        plan.pop(k, None)
    plan["title"] += " (v2 A/B)"
    plan["brief"] = {"story": plan.get("logline", ""), "style": "", "preset": None, "pacing": "balanced"}
    v2 = pl.Project(dst)
    v2.save_plan(plan)
    log("directing the copy (v1 plan -> v2)")
    revised, notes, usage = pl.direct_plan(c, s, plan)
    revised["planner"] = "v2"
    v2.save_plan(revised)
    v2.log(kind="plan", model=s.planner_model, planner="director", usage=usage,
           cost_usd=pl.call_cost(s.planner_model, usage), director_notes=len(notes))
    ids_before = {sc["id"] for sc in plan["scenes"]}
    ids_after = {sc["id"] for sc in revised["scenes"]}
    log(f"v2 copy: {dst.name}  notes={len(notes)}  scene ids kept={ids_before == ids_after}")
    for n in notes:
        log(f"  [{n['scene'] or 'film'}] {n['change']}")


def fresh(story: str, style: str, n: int, preset: str | None, orientation: str) -> None:
    """Round 2+: plan the same story from scratch with each planner (no conversion)."""
    out = {}
    for version in ("v1", "v2"):
        s = settings()
        s.planner_version, s.orientation = version, orientation
        c = pl.make_client(s)
        t = time.time()
        proj = pl.new_project(c, s, story, style, n, PROJECTS, preset=preset if version == "v2" else None)
        log(f"{version}: planned {proj.root.name} in {time.time() - t:.0f}s")
        res = pl.generate_assets(c, s, proj, on_progress=lambda i, st: log(f"  {i}: {st}"))
        bad = {k: v for k, v in res.items() if v.startswith(("failed", "fatal"))}
        if bad:
            sys.exit(f"reference failures in {version}: {bad}")
        out[version] = proj.root.name
        plan = proj.load_plan()
        for sc in plan["scenes"]:
            log(f"  {sc['id']} {sc['duration_s']}s {sc.get('continuity')}: {sc['action']}")
    log(f"V1={out['v1']} V2={out['v2']}")


def shoot(v1: str, v2: str, scenes: list[str], takes: int) -> None:
    s = settings()
    c = pl.make_client(s)
    lanes = [(pid, sid) for pid in (v1, v2) for sid in scenes]

    def lane(pid_sid):
        pid, sid = pid_sid
        proj = pl.Project.open(PROJECTS / pid)
        out = []
        for n in range(takes):                    # sequential within a scene: take numbers can't collide
            t = time.time()
            try:
                take = pl.generate_take(c, s, proj, sid)
                log(f"{'v1' if pid == v1 else 'v2'} {sid}: {take.name} in {time.time() - t:.0f}s")
                out.append(take.name)
            except Exception as e:                # noqa: BLE001
                log(f"{'v1' if pid == v1 else 'v2'} {sid}: FAILED {pl.friendly_error(e)}")
        return pid, sid, out

    with ThreadPoolExecutor(len(lanes)) as ex:
        results = list(ex.map(lane, lanes))
    (ROOT / "experiments" / "ab_takes.json").write_text(json.dumps(results, indent=1), encoding="utf-8")


def new_takes() -> list:
    return json.loads((ROOT / "experiments" / "ab_takes.json").read_text(encoding="utf-8"))


def do_review(v1: str, v2: str, scenes: list[str]) -> None:
    s = settings()
    c = pl.make_client(s)
    jobs = [(pid, sid, t) for pid, sid, ts in new_takes() for t in ts]

    def one(job):
        pid, sid, t = job
        proj = pl.Project.open(PROJECTS / pid)
        r = review.review_take(c, s, proj, sid, proj.scene_dir(sid) / t)
        log(f"reviewed {'v1' if pid == v1 else 'v2'} {sid}/{t}: {r['verdict']} {r['overall']}")

    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, jobs))


def report(v1: str, v2: str, scenes: list[str]) -> None:
    rows = []
    for pid, sid, ts in new_takes():
        proj = pl.Project.open(PROJECTS / pid)
        plan = proj.load_plan()
        sc = next(x for x in plan["scenes"] if x["id"] == sid)
        for t in ts:
            meta = json.loads((proj.scene_dir(sid) / t).with_suffix(".json").read_text(encoding="utf-8"))
            r, m = meta.get("review") or {}, meta.get("motion") or {}
            rows.append({
                "version": "v1" if pid == v1 else "v2", "scene": sid, "take": t,
                "planned_s": sc["duration_s"], "clip_s": meta.get("duration_s"), "cost": meta.get("cost_usd"),
                "verdict": r.get("verdict"), "overall": r.get("overall"),
                "scores": {k: v["score"] for k, v in (r.get("scores") or {}).items()},
                "dead_meter": m.get("dead_s"), "dead_review": r.get("dead_time_s"), "cuts": m.get("cuts"),
                "issues": [f"[{i['t_start']}-{i['t_end']}s] {i['severity']} {i['category']}: {i['description']}"
                           for i in r.get("issues", [])],
            })
    out = ROOT / "experiments" / "ab_report.json"
    out.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    for version in ("v1", "v2"):
        rs = [r for r in rows if r["version"] == version and r["overall"] is not None]
        if not rs:
            continue
        avg = lambda k: sum(r[k] or 0 for r in rs) / len(rs)
        crit = {c: round(sum(r["scores"].get(c, 0) for r in rs) / len(rs), 2) for c in review.CRITERIA}
        keeps = sum(r["verdict"] == "keep" for r in rs)
        print(f"\n{version}: {len(rs)} takes | overall {avg('overall'):.2f} | keep {keeps}/{len(rs)} | "
              f"dead (meter) {avg('dead_meter'):.2f}s | cost ${sum(r['cost'] or 0 for r in rs):.2f}")
        print("   by criterion:", crit)
    for r in rows:
        print(f"\n{r['version']} {r['scene']} {r['take']} planned {r['planned_s']}s clip {r['clip_s']}s | "
              f"{r['verdict']} {r['overall']} | dead {r['dead_meter']}s | cuts {r['cuts']}")
        for i in r["issues"]:
            print("    ", i)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prepare", "fresh", "shoot", "review", "report"])
    ap.add_argument("projects", nargs="+", help="prepare: SRC; others: V1 V2 then scene ids")
    ap.add_argument("--takes", type=int, default=2)
    ap.add_argument("--preset")
    ap.add_argument("--orientation", default="9:16")
    a = ap.parse_args()
    if a.cmd == "prepare":
        prepare(a.projects[0])
    elif a.cmd == "fresh":
        story, style, n = a.projects
        fresh(story, style, int(n), a.preset, a.orientation)
    else:
        v1, v2, *scenes = a.projects
        {"shoot": lambda: shoot(v1, v2, scenes, a.takes), "review": lambda: do_review(v1, v2, scenes),
         "report": lambda: report(v1, v2, scenes)}[a.cmd]()
