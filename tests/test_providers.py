"""Provider layer: Kling via a fake HTTP API, provider choice per scene, prompts, errors, costs."""
import json

import pytest
from google.genai import types

import pipeline as pl
import providers
import providers.kling as kling_mod
from fakes import HAS_FFMPEG, FakeKling, log_entries


@pytest.fixture
def kling(monkeypatch, mp4_bytes):
    k = FakeKling(mp4_bytes)
    monkeypatch.setattr(kling_mod, "TRANSPORT", k.transport)
    monkeypatch.setattr(kling_mod.time, "sleep", lambda s: None)
    monkeypatch.setenv("KLING_API_KEY", "test-key")
    return k


def on_kling(proj, *scene_ids):
    plan = proj.load_plan()
    plan["video_providers"] = {sid: "kling" for sid in scene_ids}
    proj.save_plan(plan)


def posts(k):
    return [b for m, path, b in k.requests if m == "POST"]


def test_catalog_lists_providers_with_setup_state(s, monkeypatch):
    monkeypatch.delenv("KLING_API_KEY", raising=False)
    cat = {p["id"]: p for p in providers.catalog(s)}
    assert set(cat) == {"gemini-omni", "veo-fast", "veo", "kling"}
    assert cat["gemini-omni"]["configured"] and not cat["kling"]["configured"]
    assert "KLING_API_KEY" in cat["kling"]["setup"]
    assert cat["kling"]["price_per_s"]["720p"] == 0.112          # with native audio
    assert "360p" not in cat["kling"]["caps"]["resolutions"]


def test_scene_on_kling_request_prompt_and_cost(proj, client, s, kling):
    pl.generate_assets(client, s, proj)
    on_kling(proj, "s01")
    out = pl.generate_take(client, s, proj, "s01")

    body = posts(kling)[0]
    assert kling.requests[0][1] == "/omni-video/kling-3.0-omni"
    types_ = [c["type"] for c in body["contents"]]
    assert types_ == ["prompt", "refer_image", "refer_image"]         # env + character
    assert [c["id"] for c in body["contents"][1:]] == ["image_1", "image_2"]
    prompt = body["contents"][0]["text"]
    assert "@image_1" in prompt and "@image_2" in prompt and "<IMAGE_REF" not in prompt
    # 360p isn't offered by Kling: mapped to its lowest, 720p
    assert body["settings"] == {"resolution": "720p", "duration": 6, "aspect_ratio": "16:9",
                                "audio": "native", "multi_shot": False}

    meta = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["provider"] == "kling" and meta["model"] == "kling-3.0-omni"
    assert meta["output_url"].endswith("k1.mp4") and meta["task_id"] == "k1"
    assert meta["cost_usd"] == pytest.approx(0.8 * 6 * 0.14)         # from Kling's billing record
    kinds = [(e["kind"], e.get("provider")) for e in log_entries(proj)[-2:]]
    assert kinds == [("video_submitted", "kling"), ("video", "kling")]


def test_other_scenes_stay_on_the_default_provider(proj, client, s, kling):
    on_kling(proj, "s01")
    pl.generate_take(client, s, proj, "s03")
    assert not posts(kling)
    assert [c for c in client.calls if c[0] == "interactions.create"]


def test_short_scenes_are_stretched_to_klings_minimum(proj, client, s, kling):
    plan = proj.load_plan()
    plan["scenes"][2]["duration_s"] = 2
    proj.save_plan(plan)
    on_kling(proj, "s03")
    pl.generate_take(client, s, proj, "s03")
    assert posts(kling)[0]["settings"]["duration"] == 3


def test_prompt_overrides_are_per_provider(proj, client, s, kling):
    plan = proj.load_plan()
    plan["prompt_overrides"] = {"s01": "omni-only prompt"}
    plan["video_providers"] = {"s01": "kling"}
    proj.save_plan(plan)
    pl.generate_take(client, s, proj, "s01")
    assert posts(kling)[0]["contents"][0]["text"] != "omni-only prompt"
    plan["prompt_overrides"]["s01@kling"] = "kling prompt"
    proj.save_plan(plan)
    pl.generate_take(client, s, proj, "s01")
    assert posts(kling)[1]["contents"][0]["text"] == "kling prompt"


def test_unconfigured_provider_fails_before_any_request(proj, client, s, kling, monkeypatch):
    monkeypatch.delenv("KLING_API_KEY")
    on_kling(proj, "s01")
    with pytest.raises(providers.ProviderError) as ei:
        pl.generate_take(client, s, proj, "s01")
    assert ei.value.status_code == 401 and not kling.requests
    assert pl._is_fatal(ei.value)


@pytest.mark.parametrize("status, code, expect, fatal", [
    (429, 1102, "Out of credits", True),          # HTTP 429 but it's billing: must not retry
    (401, 1002, "Permission denied", True),
    (400, 1301, "safety filter", False),
    (400, 1201, "The request was rejected", False),
])
def test_kling_errors_map_to_the_shared_handling(proj, client, s, kling, status, code, expect, fatal):
    s.retry_base_s = 0
    on_kling(proj, "s01")
    kling.errors = [(status, code, "details")]
    with pytest.raises(providers.ProviderError) as ei:
        pl.generate_take(client, s, proj, "s01")
    msg = pl.friendly_error(ei.value)
    assert expect in msg and pl._is_fatal(ei.value) == fatal
    assert len(posts(kling)) == 1, "not retried"


def test_kling_rate_limits_are_retried(proj, client, s, kling):
    s.retry_base_s = 0
    on_kling(proj, "s01")
    kling.errors = [(429, 1302, "slow down"), (503, 5001, "maintenance")]
    assert pl.generate_take(client, s, proj, "s01").exists()
    assert len(posts(kling)) == 3
    assert [e["status"] for e in log_entries(proj) if e["kind"] == "retry"] == [429, 503]


def test_task_blocked_by_content_policy(proj, client, s, kling):
    on_kling(proj, "s01")
    kling.fail_task = "Failure to pass the risk control system"
    with pytest.raises(providers.ProviderError) as ei:
        pl.generate_take(client, s, proj, "s01")
    assert pl.friendly_error(ei.value).startswith("Blocked by the model's safety filter")


def test_edit_uses_the_takes_own_provider(proj, client, s, kling):
    on_kling(proj, "s01")
    take = pl.generate_take(client, s, proj, "s01")
    on_kling(proj)                                   # scene switched back to Omni afterwards
    out = pl.edit_take(client, s, proj, "s01", take, "heavier snow")
    body = posts(kling)[1]
    assert [c["type"] for c in body["contents"]] == ["prompt", "base_video"]
    assert body["contents"][1]["url"].endswith("k1.mp4")
    assert body["contents"][0]["text"] == "heavier snow. Keep everything else the same."
    assert body["settings"]["audio"] == "original"
    meta = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["provider"] == "kling" and meta["edited_from"] == take.name
    assert meta["output_url"].endswith("k2.mp4")    # the edit's own url, for further edits


def test_old_kling_takes_cant_be_edited(proj, client, s, kling):
    on_kling(proj, "s01")
    take = pl.generate_take(client, s, proj, "s01")
    meta_path = take.with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["created"] -= 31 * 86400
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(providers.ProviderError, match="30 days"):
        pl.edit_take(client, s, proj, "s01", take, "x")


def test_pre_provider_takes_edit_with_omni(proj, client, s):
    take = pl.generate_take(client, s, proj, "s01")
    meta_path = take.with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    del meta["provider"]
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    pl.edit_take(client, s, proj, "s01", take, "x")
    assert [c for c in client.calls if c[0] == "interactions.create"][-1][1]["previous_interaction_id"]


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_continuous_scene_sends_first_frame_to_kling(proj, client, s, kling):
    pl.generate_assets(client, s, proj)
    pl.generate_take(client, s, proj, "s01")          # on Omni
    on_kling(proj, "s02")                            # s02 continues s01, shot on Kling
    pl.generate_take(client, s, proj, "s02")
    body = posts(kling)[0]
    assert body["contents"][1]["type"] == "first_frame"
    assert body["contents"][0]["text"].startswith("The shot starts exactly on the provided first frame.")


def test_estimates_follow_each_scenes_provider(proj, s):
    before = pl.estimate_remaining(proj, s)["usd"]
    on_kling(proj, "s01")
    after = pl.estimate_remaining(proj, s)["usd"]
    omni = pl.estimate_video_usd(s, 6)
    k = pl.estimate_video_usd(s, 6, "kling")
    assert k == pytest.approx(0.112 * 6, abs=0.01)   # 360p asked, Kling bills its 720p
    assert after == pytest.approx(before - omni + k, abs=0.02)


# ---------------------------------------------------------------- Veo

@pytest.fixture
def veo(monkeypatch, mp4_bytes):
    import providers.veo as veo_mod
    from fakes import FakeVeo
    v = FakeVeo(mp4_bytes)
    monkeypatch.setattr(veo_mod, "CLIENT_FACTORY", lambda s: v)
    monkeypatch.setattr(veo_mod.time, "sleep", lambda s: None)
    return v


def on(proj, provider, *scene_ids):
    plan = proj.load_plan()
    plan["video_providers"] = {sid: provider for sid in scene_ids}
    proj.save_plan(plan)


def test_veo_fast_request_and_cost(proj, client, s, veo):
    pl.generate_assets(client, s, proj)
    on(proj, "veo-fast", "s02")                         # refs: char_a, prop_cup, env_night
    out = pl.generate_take(client, s, proj, "s02")
    call = veo.calls[0]
    cfg = call["config"]
    assert call["model"] == "veo-3.1-fast-generate-preview"      # the Gemini API id (tests use that backend)
    assert (cfg.resolution, cfg.duration_seconds, cfg.aspect_ratio) == ("720p", 6, "16:9")   # 360p -> 720p, 5 s -> 6 s
    assert len(cfg.reference_images) == 3 and cfg.reference_images[0].reference_type == types.VideoGenerationReferenceType.ASSET
    assert "CGI" in cfg.negative_prompt and "melting hands" in cfg.negative_prompt
    assert "looks exactly like the person in the reference image" in call["source"].prompt
    meta = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["provider"] == "veo-fast" and meta["cost_usd"] == pytest.approx(0.60)


def test_veo_keeps_characters_first_when_refs_overflow(proj, client, s, veo):
    plan = proj.load_plan()
    plan["characters"].append({"id": "char_b", "name": "Ben", "appearance": "x", "costume": "y", "voice": "z"})
    plan["scenes"][1]["refs"] = ["env_night", "prop_cup", "char_a", "char_b"]
    proj.save_plan(plan)
    pl.generate_assets(client, s, proj)
    on(proj, "veo-fast", "s02")
    out = pl.generate_take(client, s, proj, "s02")
    meta = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["refs"] == ["char_a", "char_b", "env_night"]      # the prop is dropped, not a character


@pytest.mark.parametrize("planned, shot", [(2, 4), (4, 4), (5, 6), (7, 8), (10, 8)])
def test_veo_durations_snap_to_4_6_8(s, planned, shot):
    from providers.veo import VeoFastVideo
    assert VeoFastVideo(s).duration_for(planned) == shot


def test_veo_retries_without_refs_if_rejected(proj, client, s, veo):
    pl.generate_assets(client, s, proj)
    on(proj, "veo-fast", "s01")
    veo.reject_refs = True
    out = pl.generate_take(client, s, proj, "s01")
    assert veo.calls[1]["config"].reference_images is None
    assert "reference" in json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))["refs_dropped"]


def test_veo_safety_block_is_reported(proj, client, s, veo):
    on(proj, "veo", "s01")
    veo.rai = ["violence"]
    with pytest.raises(providers.ProviderError) as ei:
        pl.generate_take(client, s, proj, "s01")
    assert pl.friendly_error(ei.value).startswith("Blocked by the model's safety filter")


def test_veo_takes_cant_be_edited(proj, client, s, veo):
    on(proj, "veo-fast", "s01")
    take = pl.generate_take(client, s, proj, "s01")
    with pytest.raises(providers.ProviderError, match="can't edit"):
        pl.edit_take(client, s, proj, "s01", take, "x")


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_veo_continuous_scene_gets_the_first_frame(proj, client, s, veo):
    pl.generate_take(client, s, proj, "s01")          # Omni
    on(proj, "veo-fast", "s02")
    pl.generate_take(client, s, proj, "s02")
    assert veo.calls[0]["source"].image is not None
    assert veo.calls[0]["source"].prompt.startswith("The video starts exactly on the given first frame.")
