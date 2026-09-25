"""API tests: the real FastAPI app with a fake Gemini client. Nothing is billed."""
import time

import pytest
from fastapi.testclient import TestClient

import server
from fakes import HAS_FFMPEG, FakeClient, api_error, interactions_error


@pytest.fixture
def fake(mp4_bytes):
    return FakeClient(mp4_bytes)


@pytest.fixture
def api(tmp_path, monkeypatch, fake):
    monkeypatch.setitem(server.CONFIG, "projects", tmp_path / "projects")
    monkeypatch.setitem(server.CONFIG, "fake", True)
    monkeypatch.setattr(server, "PREFS_PATH", tmp_path / "prefs.json")
    monkeypatch.setattr(server, "_fake", fake)
    monkeypatch.setattr(server, "STATS_PATH", tmp_path / "stats.json")
    server.JOBS.clear()
    return TestClient(server.app)


def wait(api, job: dict, timeout=30) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        j = api.get(f"/api/jobs/{job['id']}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError(f"job {job['id']} still running")


@pytest.fixture
def pid(api):
    job = wait(api, api.post("/api/projects", json={"story": "a story", "scenes": 3,
                                                   "orientation": "16:9"}).json())
    assert job["status"] == "done", job
    return job["result"]["project"]


def test_state_and_settings_roundtrip(api):
    st = api.get("/api/state").json()
    assert st["fake"] is True and st["settings"]["orientation"] == "9:16"
    assert st["settings"]["prices"]["video_per_s"]["720p"] == pytest.approx(0.1014, abs=1e-3)
    st = api.put("/api/settings", json={"resolution": "360p", "backend": "gemini",
                                        "models": {"gemini": {"video_model": "x-video"}}}).json()
    assert st["settings"]["resolution"] == "360p" and st["settings"]["video_model"] == "x-video"
    assert api.get("/api/state").json()["settings"]["resolution"] == "360p"
    assert api.put("/api/settings", json={"backend": "nope"}).status_code == 400
    assert api.post("/api/settings/check").json()["ok"] is True


def test_new_film_plan_only(api, pid):
    v = api.get(f"/api/projects/{pid}").json()
    assert v["plan"]["title"] == "Test Film" and v["orientation"] == "16:9"
    assert [a["status"] for a in v["assets"]] == ["missing"] * 4
    assert [s["status"] for s in v["scenes"]] == ["missing"] * 3
    assert v["costs"]["calls"] == 1
    lst = api.get("/api/projects").json()
    assert lst[0]["id"] == pid and lst[0]["refs"] == [0, 4] and lst[0]["scenes"] == [0, 3]


def test_refs_then_take_then_edit(api, pid):
    j = wait(api, api.post(f"/api/projects/{pid}/assets", json={}).json())
    assert j["status"] == "done", j
    v = api.get(f"/api/projects/{pid}").json()
    assert all(a["status"] == "done" and a["image"] for a in v["assets"])
    img = api.get(v["assets"][0]["image"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"

    j = wait(api, api.post(f"/api/projects/{pid}/scenes/s01/takes").json())
    assert j["status"] == "done", j
    s01 = api.get(f"/api/projects/{pid}").json()["scenes"][0]
    assert s01["selected"] == "take_01.mp4" and s01["takes"][0]["cost_usd"] > 0
    r = api.get(s01["takes"][0]["url"], headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100      # seekable video
    if HAS_FFMPEG:
        p = api.get(s01["takes"][0]["poster"])
        assert p.status_code == 200 and p.headers["content-type"] == "image/jpeg"

    j = wait(api, api.post(f"/api/projects/{pid}/scenes/s01/takes/take_01.mp4/edit",
                           json={"instruction": "heavier snow"}).json())
    assert j["status"] == "done", j
    s01 = api.get(f"/api/projects/{pid}").json()["scenes"][0]
    assert s01["selected"] == "take_02.mp4" and s01["takes"][1]["edited_from"] == "take_01.mp4"
    v = api.put(f"/api/projects/{pid}/scenes/s01/selected", json={"take": "take_01.mp4"}).json()
    assert v["scenes"][0]["selected"] == "take_01.mp4"


def test_prompt_override_and_reset(api, pid):
    v = api.put(f"/api/projects/{pid}/prompt", json={"id": "s01", "prompt": "custom"}).json()
    assert v["scenes"][0]["prompt"] == "custom" and v["scenes"][0]["overridden"]
    assert v["scenes"][0]["default_prompt"] != "custom"
    v = api.put(f"/api/projects/{pid}/prompt", json={"id": "s01", "prompt": None}).json()
    assert not v["scenes"][0]["overridden"]


def test_plan_edit_validation_keeps_overrides(api, pid):
    api.put(f"/api/projects/{pid}/prompt", json={"id": "char_a", "prompt": "custom"})
    plan = api.get(f"/api/projects/{pid}").json()["plan"]
    plan["logline"] = "Edited."
    v = api.put(f"/api/projects/{pid}/plan", json={"plan": plan}).json()
    assert v["plan"]["logline"] == "Edited." and v["plan"]["prompt_overrides"]["char_a"] == "custom"
    plan["scenes"][0]["refs"].append("ghost")
    assert api.put(f"/api/projects/{pid}/plan", json={"plan": plan}).status_code == 400


def test_failures_show_on_cards(api, pid, fake):
    fake.errors["image"] = [api_error(400, "Image blocked by safety filter")]
    wait(api, api.post(f"/api/projects/{pid}/assets", json={"ids": ["char_a"]}).json())
    a = next(a for a in api.get(f"/api/projects/{pid}").json()["assets"] if a["id"] == "char_a")
    assert a["status"] == "missing" and "safety filter" in a["error"]
    fake.errors["video"] = [interactions_error(403, "denied")]
    j = wait(api, api.post(f"/api/projects/{pid}/scenes/s03/takes").json())
    assert j["status"] == "failed" and "Permission denied" in j["error"]
    s03 = api.get(f"/api/projects/{pid}").json()["scenes"][2]
    assert "Permission denied" in s03["error"]


def test_conflicting_jobs_are_refused(api, pid):
    blocker = server.Job(id="x", kind="produce", label="busy", project=pid, claims={"*"})
    server.JOBS["x"] = blocker
    assert api.post(f"/api/projects/{pid}/scenes/s01/takes").status_code == 409
    v = api.get(f"/api/projects/{pid}").json()
    assert v["busy"] == ["*"] and all(s["status"] == "generating" for s in v["scenes"])
    blocker.status = "done"
    assert api.post(f"/api/projects/{pid}/scenes/s01/takes").status_code == 200


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_produce_makes_the_film(api, pid):
    j = wait(api, api.post(f"/api/projects/{pid}/produce").json())
    assert j["status"] == "done", j
    v = api.get(f"/api/projects/{pid}").json()
    assert v["final"] and v["final"]["duration_s"] == pytest.approx(6.0, abs=0.3)
    assert api.get("/api/projects").json()[0]["final"] is True


def test_auto_film_from_scratch(api):
    j = wait(api, api.post("/api/projects", json={"story": "x", "scenes": 3, "auto": True}).json())
    assert j["status"] == "done" and any("Final cut" in l or "Not stitching" in l for l in j["logs"])


def test_bad_ids_are_rejected(api, pid):
    assert api.get("/api/projects/..%2F..%2Fetc").status_code in (400, 404)
    assert api.get("/api/projects/nope").status_code == 404
    assert api.post(f"/api/projects/{pid}/scenes/s99/takes").status_code == 404
    assert api.get(f"/api/projects/{pid}/poster?path=../../x.mp4").status_code == 404
    assert api.post("/api/projects", json={"story": "  "}).status_code == 400


def test_errors_persist_in_the_log_and_clear_on_success(api, pid, fake):
    fake.errors["video"] = [interactions_error(400, "Output blocked: sexual content")]
    j = wait(api, api.post(f"/api/projects/{pid}/scenes/s03/takes").json())
    assert j["status"] == "failed" and j["error"].startswith("Blocked by the model's safety filter")
    server.JOBS.clear()                                  # as if the app restarted
    s03 = api.get(f"/api/projects/{pid}").json()["scenes"][2]
    assert "safety filter" in s03["error"]
    wait(api, api.post(f"/api/projects/{pid}/scenes/s03/takes").json())
    assert api.get(f"/api/projects/{pid}").json()["scenes"][2]["error"] is None


def test_jobs_report_progress_and_learn_durations(api, pid):
    j = wait(api, api.post(f"/api/projects/{pid}/assets", json={}).json())
    assert j["progress"]["kind"] == "image" and j["progress"]["done"] == j["progress"]["total"] == 4
    j = wait(api, api.post(f"/api/projects/{pid}/scenes/s01/takes").json())
    assert j["progress"]["key"] == "video_720p" and j["progress"]["expected_s"] > 0
    typical = api.get("/api/state").json()["typical_s"]
    assert typical["video_720p"] < 10                    # measured from the fake run, not the default
    assert typical["image"] == server.DEFAULT_TYPICAL_S["image"]  # parallel batch isn't measured


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_produce_progress_counts_every_step(api, pid):
    j = wait(api, api.post(f"/api/projects/{pid}/produce").json())
    assert j["progress"]["total"] == 4 + 3 + 1 and j["progress"]["done"] == 8


def test_delete_moves_film_out_and_refuses_while_busy(api, pid, monkeypatch):
    trashed = []
    import send2trash
    monkeypatch.setattr(send2trash, "send2trash", lambda path: trashed.append(path) or __import__("shutil").rmtree(path))
    server.JOBS["x"] = server.Job(id="x", kind="take", label="busy", project=pid, claims={"s01"})
    assert api.delete(f"/api/projects/{pid}").status_code == 409
    server.JOBS["x"].status = "done"
    r = api.delete(f"/api/projects/{pid}").json()
    assert r["moved_to"] == "the Recycle Bin" and trashed
    assert api.get(f"/api/projects/{pid}").status_code == 404
    assert api.get("/api/projects").json() == []


@pytest.fixture
def kling_api(monkeypatch, mp4_bytes):
    import providers.kling as kling_mod
    from fakes import FakeKling
    k = FakeKling(mp4_bytes)
    monkeypatch.setattr(kling_mod, "TRANSPORT", k.transport)
    monkeypatch.setattr(kling_mod.time, "sleep", lambda s: None)
    monkeypatch.setenv("KLING_API_KEY", "test")
    return k


def test_state_lists_providers_and_default(api):
    st = api.get("/api/state").json()["settings"]
    assert st["video_provider"] == "gemini-omni"
    assert {p["id"] for p in st["providers"]} == {"gemini-omni", "kling"}
    st = api.put("/api/settings", json={"video_provider": "kling", "kling_audio": False}).json()["settings"]
    assert st["video_provider"] == "kling" and st["kling_audio"] is False
    kling = next(p for p in st["providers"] if p["id"] == "kling")
    assert kling["price_per_s"]["720p"] == 0.084                 # no-audio price now
    assert api.put("/api/settings", json={"video_provider": "sora"}).status_code == 400


def test_scene_provider_choice_prompt_and_take(api, pid, kling_api):
    v = api.put(f"/api/projects/{pid}/scenes/s01/provider", json={"provider": "kling"}).json()
    s01 = v["scenes"][0]
    assert s01["provider"] == "kling" and s01["provider_chosen"]
    assert "@image" in s01["prompt"] or "Shot:" in s01["prompt"]
    assert s01["shot"] == {"resolution": "720p", "duration_s": 6}
    # a kling-specific prompt override doesn't leak into the omni prompt
    v = api.put(f"/api/projects/{pid}/prompt", json={"id": "s01", "prompt": "K", "provider": "kling"}).json()
    assert v["scenes"][0]["prompt"] == "K" and v["scenes"][0]["overridden"]
    v = api.put(f"/api/projects/{pid}/scenes/s01/provider", json={"provider": None}).json()
    assert v["scenes"][0]["provider"] == "gemini-omni" and v["scenes"][0]["prompt"] != "K"

    api.put(f"/api/projects/{pid}/scenes/s01/provider", json={"provider": "kling"})
    j = wait(api, api.post(f"/api/projects/{pid}/scenes/s01/takes").json())
    assert j["status"] == "done", j
    assert j["progress"]["key"] == "video_kling_720p"
    take = api.get(f"/api/projects/{pid}").json()["scenes"][0]["takes"][0]
    assert take["provider"] == "kling" and take["cost_usd"] > 0
    assert api.put(f"/api/projects/{pid}/scenes/s01/provider", json={"provider": "x"}).status_code == 400


def test_plan_save_keeps_scene_providers(api, pid):
    api.put(f"/api/projects/{pid}/scenes/s02/provider", json={"provider": "kling"})
    plan = api.get(f"/api/projects/{pid}").json()["plan"]
    plan.pop("video_providers")
    v = api.put(f"/api/projects/{pid}/plan", json={"plan": plan}).json()
    assert v["plan"]["video_providers"] == {"s02": "kling"}
