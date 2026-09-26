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
    monkeypatch.setitem(server.CONFIG, "library", tmp_path / "library")
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


def test_unknown_api_and_stale_code(api, monkeypatch):
    r = api.post("/api/nope")
    assert r.status_code == 404 and "restart it" in r.json()["detail"]
    assert api.get("/api/state").json()["stale"] is False
    monkeypatch.setattr(server, "STARTED_VERSION", "older")
    assert api.get("/api/state").json()["stale"] is True


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
    assert {p["id"] for p in st["providers"]} == {"gemini-omni", "veo-fast", "veo", "kling"}
    st = api.put("/api/settings", json={"video_provider": "kling", "kling_audio": False}).json()["settings"]
    assert st["video_provider"] == "kling" and st["kling_audio"] is False
    kling = next(p for p in st["providers"] if p["id"] == "kling")
    assert kling["price_per_s"]["720p"] == 0.084                 # no-audio price now
    assert api.put("/api/settings", json={"video_provider": "sora"}).status_code == 400


def test_scene_provider_choice_prompt_and_take(api, pid, kling_api):
    v = api.put(f"/api/projects/{pid}/scenes/s01/provider", json={"provider": "kling"}).json()
    s01 = v["scenes"][0]
    assert s01["provider"] == "kling" and s01["provider_chosen"]
    assert "Timeline:" in s01["prompt"] and "<IMAGE_REF" not in s01["prompt"]
    assert s01["render"] == {"resolution": "720p", "duration_s": 6}
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


def test_review_a_take(api, pid):
    wait(api, api.post(f"/api/projects/{pid}/scenes/s01/takes").json())
    j = wait(api, api.post(f"/api/projects/{pid}/scenes/s01/takes/take_01.mp4/review").json())
    assert j["status"] == "done" and j["result"] == {"verdict": "fix", "overall": 4.0}, j
    take = api.get(f"/api/projects/{pid}").json()["scenes"][0]["takes"][0]
    assert take["review"]["fix_instruction"] == "Start the walk immediately."
    assert take["review"]["cost_usd"] > 0
    v = api.get(f"/api/projects/{pid}").json()
    assert v["costs"]["by_kind"]["review"]["calls"] == 1
    assert api.post(f"/api/projects/{pid}/scenes/s01/takes/nope.mp4/review").status_code == 404


def test_new_film_v2_with_preset_and_pacing(api):
    st = api.get("/api/state").json()
    assert {x["id"] for x in st["styles"]} >= {"live_action", "animated_3d", "anime"}
    assert [x["id"] for x in st["pacing"]] == ["calm", "balanced", "kinetic"]
    j = wait(api, api.post("/api/projects", json={"story": "x", "scenes": 3, "preset": "anime",
                                                 "pacing": "kinetic"}).json())
    plan = api.get(f"/api/projects/{j['result']['project']}").json()["plan"]
    assert plan["planner"] == "v2" and plan["brief"]["preset"] == "anime"
    assert plan["director_notes"] and all(sc["beats"] for sc in plan["scenes"])


def test_direct_again_keeps_project_fields(api, pid):
    api.put(f"/api/projects/{pid}/scenes/s01/provider", json={"provider": "kling"})
    j = wait(api, api.post(f"/api/projects/{pid}/direct").json())
    assert j["status"] == "done" and j["result"]["notes"] == 1
    plan = api.get(f"/api/projects/{pid}").json()["plan"]
    assert plan["video_providers"] == {"s01": "kling"} and plan["director_notes"]


def test_saving_the_plan_normalises_beats(api, pid):
    plan = api.get(f"/api/projects/{pid}").json()["plan"]
    plan["scenes"][0]["beats"] = [{"t_start": 3, "t_end": 7.2, "action": "b", "camera": "c"},
                                  {"t_start": 0.4, "t_end": 3, "action": "a", "camera": "c"}]
    v = api.put(f"/api/projects/{pid}/plan", json={"plan": plan}).json()
    sc = v["plan"]["scenes"][0]
    assert [b["t_start"] for b in sc["beats"]] == [0, 3] and sc["duration_s"] == 8


def test_character_library_save_reuse_and_delete(api, pid):
    wait(api, api.post(f"/api/projects/{pid}/assets", json={"ids": ["char_a"]}).json())
    c = api.post("/api/library/characters", json={"project": pid, "id": "char_a"}).json()
    assert c["id"] == "char_a" and c["name"] == "Asha" and c["image"].startswith("/library-files/")
    assert api.get(c["image"]).status_code == 200
    again = api.post("/api/library/characters", json={"project": pid, "id": "char_a"}).json()
    assert again["id"] == "char_a" and len(api.get("/api/library").json()["characters"]) == 1   # updated, not copied
    asset = next(a for a in api.get(f"/api/projects/{pid}").json()["assets"] if a["id"] == "char_a")
    assert asset["library_id"] == "char_a"

    # a new film cast with her: her sheet is copied in, not painted, and her description is kept
    j = wait(api, api.post("/api/projects", json={"story": "x", "scenes": 3, "cast": ["char_a"]}).json())
    new = j["result"]["project"]
    v = api.get(f"/api/projects/{new}").json()
    a = next(a for a in v["assets"] if a["id"] == "char_a")
    assert a["image"] and a["library_id"] == "char_a" and v["plan"]["cast"][0]["name"] == "Asha"
    assert next(ch for ch in v["plan"]["characters"] if ch["id"] == "char_a")["appearance"] == "30s woman"

    assert api.delete("/api/library/characters/char_a").json()["ok"]
    assert api.get("/api/library").json()["characters"] == []
    assert api.post("/api/library/characters", json={"project": pid, "id": "char_zz"}).status_code == 404
    assert api.post("/api/projects", json={"story": "x", "cast": ["char_nope"]}).status_code == 404


# ---------------------------------------------------------------- influencers

def test_influencer_design_create_paint_script_shoot(api, fake, monkeypatch):
    import send2trash
    j = wait(api, api.post("/api/influencers/design", json={"profile": {"name": "Dev"}, "concept": "gym"}).json())
    assert j["status"] == "done" and j["result"]["profile"]["name"] == "Dev"
    assert api.get("/api/influencers").json()["design_usd"] > 0

    assert api.post("/api/influencers", json={"profile": {"name": " "}}).status_code == 400
    inf = api.post("/api/influencers", json={"profile": {**j["result"]["profile"], "handle": "dev"}}).json()
    iid = inf["id"]
    assert inf["profile"]["handle"] == "@dev" and inf["identity_done"] == 0
    assert [v["status"] for v in inf["identity"]] == ["missing"] * 5

    # the side views need the face; the face comes first
    assert api.post(f"/api/influencers/{iid}/identity", json={"views": ["profile"]}).status_code == 400
    j = wait(api, api.post(f"/api/influencers/{iid}/identity", json={}).json())
    assert j["status"] == "done", j
    inf = api.get(f"/api/influencers/{iid}").json()
    assert inf["identity_done"] == 5 and inf["face"].startswith("/library-files/influencers/")
    assert api.get(inf["face"]).status_code == 200 and inf["identity_usd"] > 0

    # a custom prompt for one view, then reset
    v = api.put(f"/api/influencers/{iid}/identity/prompt", json={"view": "face", "prompt": "mine"}).json()
    assert v["identity"][0]["prompt"] == "mine" and v["identity"][0]["overridden"]
    v = api.put(f"/api/influencers/{iid}/identity/prompt", json={"view": "face", "prompt": ""}).json()
    assert not v["identity"][0]["overridden"]

    j = wait(api, api.post(f"/api/influencers/{iid}/videos", json={"topic": "pancakes", "length_s": 20}).json())
    assert j["status"] == "done", j
    vid = j["result"]["video"]
    video = api.get(f"/api/influencers/{iid}/videos/{vid}").json()
    assert [sg["id"] for sg in video["segments"]] == ["p1", "p2"]
    est = video["estimate"]
    assert est["turns"] == 2 and est["usd"] == round(est["video_usd"] + est["images_usd"], 2) and est["images_usd"] > 0
    assert video["setup"]["location"] == "a bright corner shop aisle" and not video["opening_ok"]

    # edit the script: three segments now
    segs = video["segments"] + [{"lines": ["Bye!"], "delivery": "warm", "action": "waves"}]
    video = api.put(f"/api/influencers/{iid}/videos/{vid}", json={"segments": segs, "caption": "new"}).json()
    assert video["seconds"] == 30 and video["caption"] == "new" and video["segments"][2]["id"] == "p3"
    assert api.put(f"/api/influencers/{iid}/videos/{vid}", json={"segments": segs * 2}).status_code == 400

    if HAS_FFMPEG:
        j = wait(api, api.post(f"/api/influencers/{iid}/videos/{vid}/shoot").json())
        assert j["status"] == "done", j
        video = api.get(f"/api/influencers/{iid}/videos/{vid}").json()
        assert video["final"] and len(video["turns"]) == 3 and video["cost_usd"] > 0
        assert api.get(video["poster"]).status_code == 200
        lst = api.get("/api/influencers").json()["influencers"]
        assert lst[0]["videos_count"] == 1 and lst[0]["cost_usd"] > inf["identity_usd"]

    trashed = []
    monkeypatch.setattr(send2trash, "send2trash", lambda p: trashed.append(p))
    assert api.delete(f"/api/influencers/{iid}/videos/{vid}").json()["ok"]
    assert api.delete(f"/api/influencers/{iid}").json()["ok"] and len(trashed) == 2


def test_influencer_shoot_needs_identity_and_records_failures(api, fake):
    inf = api.post("/api/influencers", json={"profile": {"name": "Ana"}}).json()
    iid = inf["id"]
    j = wait(api, api.post(f"/api/influencers/{iid}/videos", json={"topic": "x", "length_s": 10}).json())
    vid = j["result"]["video"]
    assert api.post(f"/api/influencers/{iid}/videos/{vid}/shoot").status_code == 400
    wait(api, api.post(f"/api/influencers/{iid}/identity", json={"views": ["face"]}).json())
    fake.errors["video"] = [interactions_error(400, "blocked by safety")]
    j = wait(api, api.post(f"/api/influencers/{iid}/videos/{vid}/shoot").json())
    assert j["status"] == "failed"
    assert api.get(f"/api/influencers/{iid}/videos/{vid}").json()["error"]
    assert api.get("/api/influencers/nobody").status_code == 404
    assert api.get(f"/api/influencers/{iid}/videos/..%2F..").status_code == 404


def test_influencer_places_setups_and_opening(api, fake):
    iid = api.post("/api/influencers", json={"profile": {"name": "Ana", "setting": "a tiny flat"}}).json()["id"]
    places = api.get(f"/api/influencers/{iid}").json()["places"]
    assert [(x["id"], x["status"]) for x in places] == [("home", "missing")]
    assert api.post(f"/api/influencers/{iid}/places", json={"name": "Club", "description": ""}).status_code == 400
    j = wait(api, api.post(f"/api/influencers/{iid}/places", json={"name": "Club", "description": "neon club"}).json())
    assert j["status"] == "done", j
    places = api.get(f"/api/influencers/{iid}").json()["places"]
    assert places[1]["id"] == "club" and places[1]["image"]
    assert api.delete(f"/api/influencers/{iid}/places/home").status_code == 400

    body = {"topic": "night out", "length_s": 10, "format": "mirror", "place": "club", "outfit": "sequin dress"}
    assert api.post(f"/api/influencers/{iid}/videos", json={**body, "place": "moon"}).status_code == 404
    vid = wait(api, api.post(f"/api/influencers/{iid}/videos", json=body).json())["result"]["video"]
    v = api.get(f"/api/influencers/{iid}/videos/{vid}").json()
    assert v["format"] == "mirror" and v["setup"]["place"] == "club" and v["setup"]["outfit"] == "sequin dress"
    assert v["setup"]["location"] == "neon club" and v["opening"] == {"opening": None}

    # the opening frame needs the face
    assert api.post(f"/api/influencers/{iid}/videos/{vid}/opening").status_code == 400
    wait(api, api.post(f"/api/influencers/{iid}/identity", json={"views": ["face"]}).json())
    j = wait(api, api.post(f"/api/influencers/{iid}/videos/{vid}/opening").json())
    assert j["status"] == "done", j
    v = api.get(f"/api/influencers/{iid}/videos/{vid}").json()
    assert v["opening_ok"] and v["opening"]["opening"] and v["estimate"]["images_usd"] == 0

    # switching to a walk-in with a new outfit: two stills, and the old one is out of date
    v = api.put(f"/api/influencers/{iid}/videos/{vid}",
                json={"format": "walk_in", "setup": {"outfit": "black blazer", "place": "home"}}).json()
    assert v["format"] == "walk_in" and v["setup"]["location"] == "a tiny flat" and v["setup"]["outfit"] == "black blazer"
    assert not v["opening_ok"] and set(v["opening"]) == {"opening", "look"}
    assert api.put(f"/api/influencers/{iid}/videos/{vid}", json={"format": "yodel"}).status_code == 400
    lst = api.get("/api/influencers").json()
    assert [f["id"] for f in lst["formats"]][:2] == ["talking_head", "propped"]


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_edit_export_and_reset(api, fake):
    iid = api.post("/api/influencers", json={"profile": {"name": "Ana"}}).json()["id"]
    vid = wait(api, api.post(f"/api/influencers/{iid}/videos", json={"topic": "x", "length_s": 10}).json())["result"]["video"]
    assert api.put(f"/api/influencers/{iid}/videos/{vid}/edit", json={"params": {}}).status_code == 400   # nothing shot yet
    wait(api, api.post(f"/api/influencers/{iid}/identity", json={"views": ["face"]}).json())
    wait(api, api.post(f"/api/influencers/{iid}/videos/{vid}/shoot").json())
    v = api.get(f"/api/influencers/{iid}/videos/{vid}").json()
    assert v["edit"]["url"] is None and v["edit"]["params"]["brightness"] == 1.0
    j = wait(api, api.put(f"/api/influencers/{iid}/videos/{vid}/edit",
                          json={"params": {"start": 0.3, "warmth": 0.4, "normalize": True}}).json())
    assert j["status"] == "done", j
    v = api.get(f"/api/influencers/{iid}/videos/{vid}").json()
    assert v["edit"]["url"] and v["edit"]["params"]["warmth"] == 0.4 and not v["edit"]["stale"]
    assert api.get(v["edit"]["url"]).status_code == 200
    j = wait(api, api.put(f"/api/influencers/{iid}/videos/{vid}/edit", json={"params": {}}).json())
    v = api.get(f"/api/influencers/{iid}/videos/{vid}").json()
    assert v["edit"]["url"] is None and v["edit"]["params"]["warmth"] == 0.0
    assert api.put(f"/api/influencers/{iid}/videos/{vid}/edit", json={"params": {"start": 1, "end": 1.1}}).status_code == 400


def test_bucket_setup_enables_high_res(api):
    api.put("/api/settings", json={"backend": "gemini"})
    assert api.post("/api/settings/bucket", json={}).status_code == 400          # not on Vertex
    api.put("/api/settings", json={"backend": "vertex", "gcp_project": "my-proj"})
    assert api.get("/api/state").json()["settings"]["high_res_ready"] is False
    assert api.post("/api/settings/bucket", json={"name": "Bad Name!"}).status_code == 400
    r = api.post("/api/settings/bucket", json={}).json()
    assert r["bucket"]["name"] == "my-proj-reelforge"
    st = api.get("/api/state").json()["settings"]
    assert st["gcs_bucket"] == "my-proj-reelforge" and st["high_res_ready"] is True


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_captions_flow(api, fake, monkeypatch):
    import captions
    monkeypatch.setattr(captions, "extract_audio", lambda v, out: (out.write_bytes(b"mp3"), out)[1])
    iid = api.post("/api/influencers", json={"profile": {"name": "Ana"}}).json()["id"]
    vid = wait(api, api.post(f"/api/influencers/{iid}/videos", json={"topic": "x", "length_s": 20}).json())["result"]["video"]
    wait(api, api.post(f"/api/influencers/{iid}/identity", json={"views": ["face"]}).json())
    wait(api, api.post(f"/api/influencers/{iid}/videos/{vid}/shoot").json())
    c = api.get(f"/api/influencers/{iid}/videos/{vid}").json()["captions"]
    script = "Okay so you only need three things. Banana, egg, oats. That's it."
    assert " ".join(w["text"] for w in c["words"]) == script and not c["enabled"] and c["synced"] == "estimate"

    cat = api.get("/api/captions").json()
    assert len(cat["fonts"]) == 10 and any(p["id"] == "boxed" for p in cat["presets"])
    assert api.get("/fonts/Anton-Regular.ttf").status_code == 200

    v = api.put(f"/api/influencers/{iid}/videos/{vid}/captions",
                json={"enabled": True, "style": {**cat["presets"][1]["style"], "color": "#FF0000"}}).json()
    assert v["captions"]["enabled"] and v["captions"]["style"]["color"] == "#FF0000"

    j = wait(api, api.post(f"/api/influencers/{iid}/videos/{vid}/captions/sync").json())
    assert j["status"] == "done", j
    c = api.get(f"/api/influencers/{iid}/videos/{vid}").json()["captions"]
    assert c["synced"] == "voice" and c["differences"][0]["heard"] == "just"
    assert " ".join(w["text"] for w in c["words"]) == script              # the words never change

    words = c["words"]
    words[0]["text"] = "OK"
    c = api.put(f"/api/influencers/{iid}/videos/{vid}/captions", json={"words": words}).json()["captions"]
    assert c["words"][0]["text"] == "OK" and c["synced"] == "voice"

    j = wait(api, api.put(f"/api/influencers/{iid}/videos/{vid}/edit", json={"params": {}}).json())
    assert j["status"] == "done" and j["result"]["edited"] is True       # captions alone are an edit
    assert "Style: Cap," in (server.the_influencers().video(iid, vid).root / "captions.ass").read_text(encoding="utf-8")

    c = api.put(f"/api/influencers/{iid}/videos/{vid}/captions", json={"reset": True}).json()["captions"]
    assert c["words"][0]["text"] == "Okay" and c["synced"] == "estimate" and c["enabled"]

    cat = api.post("/api/captions/presets", json={"name": "Mine", "style": {"font": "bebas"}}).json()
    mine = next(p for p in cat["presets"] if p["name"] == "Mine")
    assert not mine["builtin"] and mine["style"]["font"] == "bebas"
    assert api.delete("/api/captions/presets/bold-pop").status_code == 404
    assert api.delete(f"/api/captions/presets/{mine['id']}").status_code == 200
