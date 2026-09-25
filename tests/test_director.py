"""Planner v2 compilation: beats -> prompts, multi-shot, normalisation, style profiles."""
import copy

import director
import pipeline as pl
from fakes import PLAN_V2
from prompts import scene_lines
from providers import Ref, Shot
from providers.kling import KlingOmniVideo


def scene(multi=False):
    p = copy.deepcopy(PLAN_V2)
    sc = p["scenes"][0]
    sc["beats"] = [
        {"t_start": 0, "t_end": 2, "action": "Asha is already striding up the road", "camera": "tracks alongside"},
        {"t_start": 2, "t_end": 4, "action": "she stops and looks up", "camera": "holds medium", "hold": True},
        {"t_start": 4, "t_end": 6, "action": "the lighthouse beam sweeps over her", "camera": "cuts to low angle",
         "cut": multi},
    ]
    sc["multi_shot"] = multi
    return p, sc


def test_single_shot_prompt_is_a_timeline():
    p, sc = scene()
    text = "\n".join(scene_lines(p, sc))
    assert "Timeline:" in text and "0-2s: Asha is already striding up the road." in text
    assert "(a deliberate hold)" in text and "already underway in the first frame" in text
    assert "Single continuous shot" in text and "Medium: live-action film." in text
    assert "Motion: natural weight." in text


def test_multi_shot_prompt_lists_shots():
    p, sc = scene(multi=True)
    text = "\n".join(scene_lines(p, sc))
    assert "Shot 1 (0-4s):" in text and "Shot 2 (4-6s):" in text and "cut into 2 shots" in text


def test_kling_uses_its_own_multi_shot_syntax(s):
    p, sc = scene(multi=True)
    shot = Shot(plan=p, scene=sc, refs=[], first_frame=None, aspect="16:9", resolution="720p", duration_s=6)
    text = KlingOmniVideo(s).build_prompt(shot)
    assert text.startswith("shot 1, 4, ") and "; shot 2, 2, " in text


def test_normalize_orders_closes_gaps_and_sets_duration():
    p = {"scenes": [{"id": "s1", "multi_shot": False, "beats": [
        {"t_start": 2.3, "t_end": 5.1, "action": "b", "camera": "c", "cut": True},
        {"t_start": 0.3, "t_end": 2.0, "action": "a", "camera": "c"}]}]}
    sc = director.normalize(p)["scenes"][0]
    assert [(b["t_start"], b["t_end"]) for b in sc["beats"]] == [(0.0, 2.0), (2.0, 5.1)]
    assert sc["duration_s"] == 6 and "cut" not in sc["beats"][1]


def test_sheets_follow_the_style_profile():
    p = copy.deepcopy(PLAN_V2)
    p["style"]["sheet_look"] = "anime character model sheet"
    assert "Rendered as: anime character model sheet." in pl.character_sheet_prompt(p, p["characters"][0])


def test_v1_plans_still_compile_the_old_way():
    from fakes import PLAN
    text = "\n".join(scene_lines(PLAN, PLAN["scenes"][0]))
    assert text.startswith("Shot: wide.") and "Timeline" not in text


def test_planner_v1_is_still_selectable(tmp_path, client, s):
    s.planner_version = "v1"
    proj = pl.new_project(client, s, "x", "y", 3, base_dir=tmp_path)
    plan = proj.load_plan()
    assert "beats" not in plan["scenes"][0] and "director_notes" not in plan
