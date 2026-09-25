"""Offline tests: a fake Gemini client stands in for the API, so nothing is billed.

Run:  python -m pytest -q
"""
import json
from pathlib import Path

import pytest
from PIL import Image

import pipeline as pl
from fakes import HAS_FFMPEG, PLAN, FakeClient, api_error, interactions_error, log_entries


# ---------------------------------------------------------------- settings / costs

def test_backend_defaults_and_overrides():
    assert pl.Settings(backend="vertex", gcp_project="x").video_model == "gemini-omni-1.1-flash-preview"
    assert pl.Settings(backend="gemini").image_model == "gemini-3-pro-image-preview"
    assert pl.Settings(backend="vertex", video_model="custom").video_model == "custom"
    assert pl.Settings(backend="gemini").orientation == "9:16"
    assert pl.Settings(backend="gemini").resolution == "720p"


def test_call_cost_matches_real_smoke_take():
    # the real s01 take: 3,610 in / 11,586 video out / 772 thinking tokens
    usage = {"input": 3610, "output": 11586, "thoughts": 772}
    assert pl.call_cost("gemini-omni-1.1-flash-preview", usage) == pytest.approx(0.2217, abs=1e-4)
    assert pl.call_cost("unknown-model", usage) is None
    assert pl.call_cost("gemini-3-pro-image", {"input": 500, "output": 1120, "thoughts": 0}, "4K") == \
        pytest.approx(0.241, abs=1e-3)


def test_estimates(s):
    assert pl.estimate_video_usd(s, 6) == pytest.approx(0.20, abs=0.01)           # 360p
    assert pl.estimate_video_usd(pl.Settings(backend="gemini"), 6) == pytest.approx(0.61, abs=0.01)
    assert pl.estimate_image_usd(s, 3) == pytest.approx(0.40, abs=0.01)


# ---------------------------------------------------------------- plan

def test_new_project_logs_plan_cost(proj, s):
    e = log_entries(proj)[0]
    assert e["kind"] == "plan" and e["model"] == s.planner_model
    assert e["cost_usd"] == pytest.approx((1000 * 2 + 2500 * 12) / 1e6)
    assert proj.load_plan()["orientation"] == "16:9"


def test_same_title_same_minute_gets_new_folder(tmp_path, client, s):
    a = pl.new_project(client, s, "x", "y", 3, base_dir=tmp_path)
    b = pl.new_project(client, s, "x", "y", 3, base_dir=tmp_path)
    assert a.root != b.root


# ---------------------------------------------------------------- references

def test_generate_assets_order_aspect_cost_and_variant_ref(proj, client, s):
    pl.generate_assets(client, s, proj)
    for j in pl.asset_jobs(proj.load_plan()):
        assert proj.asset_path(j["id"]).exists()
    img_calls = [c for c in client.calls if c[0] == "generate_content" and c[3].response_modalities]
    by_prompt = {c[2][-1]: c for c in img_calls}
    variant = next(c for p, c in by_prompt.items() if "clear morning" in p)
    assert len(variant[2]) == 2, "variant plate must send its base plate as a reference image"
    aspects = {c[3].image_config.aspect_ratio for c in img_calls}
    assert aspects == {"16:9"}
    images = [e for e in log_entries(proj) if e["kind"] == "image"]
    assert len(images) == 4 and all(e["cost_usd"] > 0.134 for e in images)


def test_jpeg_output_is_stored_as_png(proj, mp4_bytes, s):
    c = FakeClient(mp4_bytes, image_mime="image/jpeg")
    pl.generate_assets(c, s, proj, only=["char_a"])
    assert Image.open(proj.asset_path("char_a")).format == "PNG"


def test_vertical_film_keeps_sheets_wide():
    plan = {**PLAN, "orientation": "9:16"}
    aspects = {j["id"]: j["aspect"] for j in pl.asset_jobs(plan)}
    assert aspects["char_a"] == aspects["prop_cup"] == "16:9"
    assert aspects["env_night"] == aspects["env_day"] == "9:16"


# ---------------------------------------------------------------- video

def test_generate_take_logs_usage_cost_duration(proj, client, s):
    pl.generate_assets(client, s, proj)
    out = pl.generate_take(client, s, proj, "s01")
    meta = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["cost_usd"] == pytest.approx(0.2217, abs=1e-4)
    assert meta["usage"]["output"] == 11586
    if HAS_FFMPEG:
        assert meta["duration_s"] == pytest.approx(2.0, abs=0.1)
    kinds = [e["kind"] for e in log_entries(proj)]
    assert kinds[-2:] == ["video_submitted", "video"]
    create = [c for c in client.calls if c[0] == "interactions.create"][-1][1]
    assert create["response_format"] == {"type": "video", "aspect_ratio": "16:9", "resolution": "360p"}
    assert "<IMAGE_REF_0>" in create["input"][-1]["text"]


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_continuous_scene_uses_previous_last_frame(proj, client, s):
    pl.generate_assets(client, s, proj)
    pl.generate_take(client, s, proj, "s01")
    pl.generate_take(client, s, proj, "s02")
    create = [c for c in client.calls if c[0] == "interactions.create"][-1][1]
    text = create["input"][-1]["text"]
    assert text.startswith("[# Sources <FIRST_FRAME>@Image1]")
    assert len(create["input"]) == 1 + 3 + 1          # first frame + 3 refs + text


def test_edit_take_reuses_format_and_chains(proj, client, s):
    pl.generate_assets(client, s, proj)
    take = pl.generate_take(client, s, proj, "s01")
    out = pl.edit_take(client, s, proj, "s01", take, "make the snow heavier")
    kw = [c for c in client.calls if c[0] == "interactions.create"][-1][1]
    assert kw["previous_interaction_id"] == "ix1"
    assert kw["input"] == "make the snow heavier. Keep everything else the same."
    assert kw["response_format"]["resolution"] == "360p"
    meta = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["edited_from"] == take.name and meta["interaction_id"] == "ix2"
    assert log_entries(proj)[-1]["kind"] == "video_edit"


def test_unsaved_video_is_still_cost_logged(proj, client, s):
    client.fail_save = True
    with pytest.raises(RuntimeError):
        pl.generate_take(client, s, proj, "s01")
    e = log_entries(proj)[-1]
    assert e["kind"] == "video_unsaved" and e["cost_usd"] is not None


def test_vertex_high_res_fails_before_paying(proj, client):
    s = pl.Settings(backend="vertex", gcp_project="p", resolution="1080p")
    with pytest.raises(NotImplementedError):
        pl.generate_take(client, s, proj, "s01")
    assert not [c for c in client.calls if c[0] == "interactions.create"]


def test_project_costs_totals(proj, client, s):
    pl.generate_assets(client, s, proj)
    pl.generate_take(client, s, proj, "s01")
    c = pl.project_costs(proj)
    assert c["calls"] == 1 + 4 + 1
    assert c["by_kind"]["video"]["usd"] == pytest.approx(0.2217, abs=1e-4)
    assert "over 6 calls" in pl.format_costs(c)


# ---------------------------------------------------------------- stitch

@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_stitch(proj, client, s):
    for sc in ("s01", "s02", "s03"):
        pl.generate_take(client, s, proj, sc)
    out = pl.stitch(proj)
    assert pl.video_duration(out) == pytest.approx(6.0, abs=0.2)


# ---------------------------------------------------------------- retries / errors

@pytest.fixture
def fast(s):
    s.retry_base_s = 0
    return s


def test_image_retries_on_503_then_succeeds(proj, client, fast):
    client.errors["image"] = [api_error(503)]
    pl.generate_assets(client, fast, proj, only=["char_a"])
    assert proj.asset_path("char_a").exists()
    retry = [e for e in log_entries(proj) if e["kind"] == "retry"]
    assert retry and retry[0]["status"] == 503


def test_video_retries_on_429_from_interactions(proj, client, fast):
    client.errors["video"] = [interactions_error(429), interactions_error(429)]
    out = pl.generate_take(client, fast, proj, "s01")
    assert out.exists()
    assert len([e for e in log_entries(proj) if e["kind"] == "retry"]) == 2


def test_client_errors_are_not_retried(proj, client, fast):
    client.errors["video"] = [interactions_error(400, "bad request")]
    with pytest.raises(Exception):
        pl.generate_take(client, fast, proj, "s01")
    assert len([c for c in client.calls if c[0] == "interactions.create"]) == 1


def test_gives_up_after_max_retries(proj, client, fast):
    client.errors["image"] = [api_error(503)] * (fast.max_retries + 1)
    res = pl.generate_assets(client, fast, proj, only=["char_a"])
    assert res["char_a"].startswith("failed:") and "servers failed" in res["char_a"]


@pytest.mark.parametrize("err, expect", [
    (api_error(402), "prepaid credits"),
    (api_error(404, "no such model"), "Check the model ids"),
    (interactions_error(403, "denied"), "Vertex AI API is enabled"),
    (interactions_error(429), "Rate limit"),
    (api_error(400, "blocked"), "safety filter"),
])
def test_friendly_error_messages(err, expect):
    assert expect in pl.friendly_error(err)


def test_friendly_error_for_expired_credentials():
    import google.auth.exceptions as gae
    assert "application-default login" in pl.friendly_error(gae.RefreshError("expired"))


# ---------------------------------------------------------------- produce / resume

def creates(client):
    return [c for c in client.calls if c[0] == "interactions.create"]


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_produce_makes_everything_then_resume_is_free(proj, client, s):
    logs = []
    r = pl.produce(client, s, proj, log=logs.append)
    assert r["failed"] == {} and r["final"].exists()
    assert all(proj.takes(sc) for sc in ("s01", "s02", "s03"))
    assert any(l.startswith("To make: 4 references, 3 scenes") for l in logs)
    n = len(client.calls)
    r2 = pl.produce(client, s, proj, log=lambda m: None)
    assert len(client.calls) == n, "a finished project must not spend anything on resume"
    assert r2["final"].exists()


def test_failed_reference_skips_only_scenes_that_need_it(proj, mp4_bytes, s):
    c = FakeClient(mp4_bytes)
    c.errors["image"] = [api_error(400, "blocked")]   # first image job (char_a) fails
    r = pl.produce(c, s, proj, log=lambda m: None)
    assert r["failed"]["char_a"].startswith("failed:")
    assert r["failed"]["s01"].startswith("skipped: missing references char_a")
    assert r["failed"]["s02"].startswith("skipped")
    assert proj.takes("s03"), "s03 doesn't use char_a, so it is still shot"
    assert r["final"] is None
    # resume after the cause is fixed: only the missing work is done
    before = len(creates(c))
    r = pl.produce(c, s, proj, log=lambda m: None)
    assert not r["failed"] and len(creates(c)) == before + 2


def test_fatal_error_stops_the_run(proj, client, s):
    client.errors["image"] = [api_error(402)] * 4   # every parallel image job hits billing
    r = pl.produce(client, s, proj, log=lambda m: None)
    assert any(v.startswith("fatal") for v in r["failed"].values())
    assert not creates(client), "no video should be attempted after a fatal error"


def test_fatal_error_during_scenes_stops_the_run(proj, client, s):
    pl.generate_assets(client, s, proj)
    client.errors["video"] = [interactions_error(403)]
    r = pl.produce(client, s, proj, log=lambda m: None)
    assert "Permission denied" in r["failed"]["s01"]
    assert len(creates(client)) == 1


def test_continuous_scene_waits_for_previous(proj, client, s, fast):
    pl.generate_assets(client, s, proj)
    client.errors["video"] = [interactions_error(400)]   # s01 fails (not fatal)
    r = pl.produce(client, fast, proj, log=lambda m: None)
    assert r["failed"]["s02"] == "skipped: continues from s01, which has no take"
    assert proj.takes("s03")


def test_estimate_remaining(proj, client, s):
    e = pl.estimate_remaining(proj, s)
    assert len(e["refs"]) == 4 and e["scenes"] == ["s01", "s02", "s03"] and e["video_s"] == 15
    assert e["usd"] == pytest.approx(pl.estimate_image_usd(s, 4) + pl.estimate_video_usd(s, 15), abs=0.01)


def test_project_open_rejects_non_projects(tmp_path):
    with pytest.raises(FileNotFoundError):
        pl.Project.open(tmp_path / "nope")
    assert not (tmp_path / "nope").exists()


# ---------------------------------------------------------------- CLI

def run_cli(monkeypatch, client, *args):
    import runpy, sys
    monkeypatch.setattr(pl, "make_client", lambda s, api_key=None: client)
    monkeypatch.setattr(sys, "argv", ["cli.py", *args])
    try:
        runpy.run_path(str(Path(pl.__file__).with_name("cli.py")), run_name="__main__")
    except SystemExit as e:
        return e.code
    return 0


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_cli_full_run_then_resume(tmp_path, monkeypatch, client, capsys):
    code = run_cli(monkeypatch, client, "--story", "x", "--resolution", "360p", "--image-size", "1K",
                   "--out", str(tmp_path), "--backend", "gemini")
    out = capsys.readouterr().out
    assert code == 0, out
    assert "Final cut:" in out and "Spent so far: $" in out
    folder = next(tmp_path.iterdir())
    code = run_cli(monkeypatch, client, "--resume", str(folder), "--backend", "gemini")
    assert code == 0 and "To make: 0 references, 0 scenes" in capsys.readouterr().out


def test_cli_reports_failures_with_resume_command(tmp_path, monkeypatch, client, capsys):
    client.errors["image"] = [api_error(400, "blocked")]   # char_a -> s01, s02 skipped
    code = run_cli(monkeypatch, client, "--story", "x", "--out", str(tmp_path), "--backend", "gemini")
    assert code == 2
    assert "--resume" in capsys.readouterr().out


def test_cli_friendly_error_and_exit_1(tmp_path, monkeypatch, client, capsys):
    client.errors["plan"] = [api_error(402)]
    assert run_cli(monkeypatch, client, "--story", "x", "--out", str(tmp_path), "--backend", "gemini") == 1
    assert "prepaid credits" in capsys.readouterr().err
