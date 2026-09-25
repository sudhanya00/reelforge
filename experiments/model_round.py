"""Model round: the same scenes, plans and references shot by different video providers.

  python experiments/model_round.py shoot  --res 720p --takes 2 --models gemini-omni veo-fast \\
         --scene PROJECT:SCENE [--scene PROJECT:SCENE ...]
  python experiments/model_round.py review
  python experiments/model_round.py report

Takes of one scene alternate between models and run one at a time (take numbers can't
collide); different scenes run in parallel. The list of new takes is kept in
experiments/model_takes.json; the report goes to experiments/model_report.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8", errors="replace")

import pipeline as pl  # noqa: E402
import review  # noqa: E402

PROJECTS = ROOT / "projects"
TAKES = ROOT / "experiments" / "model_takes.json"


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def shoot(scenes: list[str], models: list[str], takes: int, res: str) -> None:
    s = pl.Settings(resolution=res)
    c = pl.make_client(s)

    def lane(spec):
        pid, sid = spec.split(":")
        proj = pl.Project.open(PROJECTS / pid)
        done = []
        for n in range(takes):
            for m in models:
                t = time.time()
                try:
                    take = pl.generate_take(c, s, proj, sid, provider=m)
                    done.append({"project": pid, "scene": sid, "model": m, "take": take.name})
                    log(f"{m:12s} {pid[-12:]} {sid}: {take.name} in {time.time() - t:.0f}s")
                except Exception as e:  # noqa: BLE001
                    log(f"{m:12s} {pid[-12:]} {sid}: FAILED {pl.friendly_error(e)}")
                    done.append({"project": pid, "scene": sid, "model": m, "take": None,
                                 "error": pl.friendly_error(e)})
        return done

    with ThreadPoolExecutor(len(scenes)) as ex:
        rows = [r for lane_rows in ex.map(lane, scenes) for r in lane_rows]
    # add to earlier runs (e.g. re-running one model after a fix), dropping their failed attempts
    old = json.loads(TAKES.read_text(encoding="utf-8")) if TAKES.exists() else []
    old = [r for r in old if r["take"] or r["model"] not in models]
    TAKES.write_text(json.dumps(old + rows, indent=1, ensure_ascii=False), encoding="utf-8")


def do_review() -> None:
    s = pl.Settings()
    c = pl.make_client(s)
    rows = [r for r in json.loads(TAKES.read_text(encoding="utf-8")) if r["take"]]

    def one(r):
        proj = pl.Project.open(PROJECTS / r["project"])
        rv = review.review_take(c, s, proj, r["scene"], proj.scene_dir(r["scene"]) / r["take"])
        log(f"reviewed {r['model']:12s} {r['scene']} {r['take']}: {rv['verdict']} {rv['overall']}")

    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, rows))


def report() -> None:
    rows = json.loads(TAKES.read_text(encoding="utf-8"))
    out, by_model = [], defaultdict(list)
    for r in rows:
        if not r["take"]:
            out.append({**r, "verdict": "failed"})
            continue
        proj = pl.Project.open(PROJECTS / r["project"])
        meta = json.loads((proj.scene_dir(r["scene"]) / r["take"]).with_suffix(".json").read_text(encoding="utf-8"))
        rv = meta.get("review") or {}
        row = {**r, "clip_s": meta.get("duration_s"), "resolution": meta["format"]["resolution"],
               "cost": meta.get("cost_usd"), "refs": meta.get("refs"), "refs_dropped": meta.get("refs_dropped"),
               "verdict": rv.get("verdict"), "overall": rv.get("overall"),
               "scores": {k: v["score"] for k, v in (rv.get("scores") or {}).items()},
               "issues": [f"[{i['t_start']}-{i['t_end']}s] {i['severity']} {i['category']}: {i['description']}"
                          for i in rv.get("issues", [])]}
        out.append(row)
        by_model[r["model"]].append(row)
    (ROOT / "experiments" / "model_report.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    for m, rs in by_model.items():
        rs = [r for r in rs if r["overall"] is not None]
        n = len(rs)
        crit = {c: round(sum(r["scores"].get(c, 0) for r in rs) / n, 2) for c in review.CRITERIA}
        print(f"\n{m}: {n} takes | overall {sum(r['overall'] for r in rs) / n:.2f} | "
              f"keep {sum(r['verdict'] == 'keep' for r in rs)} fix {sum(r['verdict'] == 'fix' for r in rs)} | "
              f"video ${sum(r['cost'] or 0 for r in rs):.2f}")
        print("   by criterion:", crit)
    for r in out:
        print(f"\n{r['model']:12s} {r['project'][-12:]} {r['scene']} {r.get('take')} | {r['verdict']} {r.get('overall')}"
              f" | {r.get('clip_s')}s {r.get('resolution')} refs={r.get('refs')}"
              + (f" | REFS DROPPED: {r['refs_dropped'][:120]}" if r.get("refs_dropped") else "")
              + (f" | {r['error']}" if r.get("error") else ""))
        for i in r.get("issues", []):
            print("     ", i)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["shoot", "review", "report"])
    ap.add_argument("--scene", action="append", default=[])
    ap.add_argument("--models", nargs="+", default=["gemini-omni", "veo-fast"])
    ap.add_argument("--takes", type=int, default=2)
    ap.add_argument("--res", default="720p")
    a = ap.parse_args()
    {"shoot": lambda: shoot(a.scene, a.models, a.takes, a.res), "review": do_review, "report": report}[a.cmd]()
