"""Influencer mode: profiles, identity pack, scripts and extension-based reels (offline)."""
import copy

import pytest

import influencers as inf
from fakes import FAKE_PROFILE, HAS_FFMPEG, api_error, log_entries


@pytest.fixture
def lib(tmp_path):
    return inf.Influencers(tmp_path / "library")


@pytest.fixture
def mira(lib):
    return lib.create(FAKE_PROFILE)["id"]


def test_create_gives_unique_ids_and_keeps_only_profile_fields(lib):
    a = lib.create({**FAKE_PROFILE, "junk": "x"})
    b = lib.create(FAKE_PROFILE)
    assert (a["id"], b["id"]) == ("mira_sol", "mira_sol_2")
    assert "junk" not in a["profile"] and a["profile"]["niche"] == "budget cooking"
    assert [i["id"] for i in lib.all()] == ["mira_sol_2", "mira_sol"]
    with pytest.raises(KeyError):
        lib.get("../mira_sol")


def test_fill_profile_keeps_chosen_fields(client, s):
    out, usage = inf.fill_profile(client, s, {"name": "Dev", "niche": "", "hair": "buzz cut"}, "gym guy")
    assert out["name"] == "Dev" and out["hair"] == "buzz cut"          # chosen fields win
    assert out["niche"] == "budget cooking"                              # empty ones are filled
    assert out["handle"] == "@mirasol" and usage["output"] == 2000


def test_identity_prompts_are_raw_and_anchor_on_the_face():
    face = inf.identity_prompt(FAKE_PROFILE, "face")
    side = inf.identity_prompt(FAKE_PROFILE, "profile")
    room = inf.identity_prompt(FAKE_PROFILE, "setting")
    assert "selfie" in face and "visible pores" in face and "reference photo" not in face
    assert side.startswith("The same person as in the reference photo")
    assert "mole above the lip" in side and "olive cardigan" in side
    assert "nobody in it" in room and "green kettle" in room and "Filipino" not in room


def test_paint_identity_face_first_then_views_from_it(client, s, lib, mira):
    res = inf.paint_identity(client, s, lib, mira)
    assert set(res.values()) == {"done"}
    assert all(lib.image(mira, v).exists() for v in inf.VIEW_IDS)
    image_calls = [c for c in client.calls if c[0] == "generate_content"]
    assert len(image_calls) == 5
    # face and setting are painted from text; the three other views carry the face as a reference
    n_refs = [len(c[2]) - 1 for c in image_calls]
    assert n_refs == [0, 0, 1, 1, 1]
    costs = [e for e in (lib.dir(mira) / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(costs) == 5
    # a second run skips what exists; force repaints
    assert set(inf.paint_identity(client, s, lib, mira).values()) == {"skipped"}
    assert inf.paint_identity(client, s, lib, mira, views=["profile"], force=True) == {"profile": "done"}


def test_paint_identity_needs_the_face_and_stops_on_fatal(client, s, lib, mira):
    res = inf.paint_identity(client, s, lib, mira, views=["profile"])
    assert res == {"profile": "failed: paint the face first"}
    client.errors["image"] = [api_error(403, "billing disabled")]
    res = inf.paint_identity(client, s, lib, mira)
    assert res["face"].startswith("fatal") and len(res) == 1


def test_write_script_normalizes_segments(client, s, lib, mira):
    proj = inf.write_script(client, s, lib, mira, "talking_head", "cheap breakfast", "", 27)
    plan = proj.load_plan()
    assert plan["kind"] == "reel" and plan["influencer"] == mira
    assert plan["brief"]["length_s"] == 30
    assert [(g["id"], g["seconds"]) for g in plan["segments"]] == [("p1", 10), ("p2", 10), ("p3", 10)]
    assert [v.root for v in lib.videos(mira)] == [proj.root]
    assert log_entries(proj)[0]["kind"] == "plan"
    prompt = [c for c in client.calls if c[0] == "generate_content"][-1][2]
    assert "budget cooking" in prompt and "3 segments" in prompt


def test_segment_prompts(lib):
    seg = {"id": "p1", "seconds": 10, "lines": ["Okay so.", "Three things."], "delivery": "excited",
           "action": "holds up an egg"}
    first = inf.segment_prompt(FAKE_PROFILE, seg, ["face", "three_quarter", "setting"], first=True)
    assert first.startswith("[# References <IMAGE_REF_0>@Image1 <IMAGE_REF_1>@Image2 <IMAGE_REF_2>@Image3]")
    assert "person in <IMAGE_REF_0>, <IMAGE_REF_1>" in first and "place in <IMAGE_REF_2>" in first
    assert '"Okay so. Three things."' in first and "front camera" in first and "no background music" in first
    more = inf.segment_prompt(FAKE_PROFILE, seg, [], first=False)
    assert more.startswith("Continue the same continuous selfie take for 10 more seconds")
    assert "IMAGE_REF" not in more and more.endswith("Keep everything else the same.")


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_shoot_reel_generates_then_extends(client, s, lib, mira):
    inf.paint_identity(client, s, lib, mira)
    proj = inf.write_script(client, s, lib, mira, "talking_head", "pancakes", "", 30)
    steps = []
    final = inf.shoot_reel(client, s, lib, mira, proj, log=lambda *_: None, step=lambda *a: steps.append(a[:2]))
    assert final.exists()
    creates = [c[1] for c in client.calls if c[0] == "interactions.create"]
    assert len(creates) == 3
    first, ext1, ext2 = creates
    assert "previous_interaction_id" not in first
    assert len([x for x in first["input"] if x["type"] == "image"]) == 4        # face, 3/4, profile, setting
    assert first["response_format"]["aspect_ratio"] == "9:16"
    assert ext1["previous_interaction_id"] == "ix1" and ext2["previous_interaction_id"] == "ix2"
    assert isinstance(ext1["input"], str) and ext1["input"].startswith("Continue the same")
    kinds = [e["kind"] for e in log_entries(proj)]
    assert kinds.count("video") == 1 and kinds.count("video_edit") == 2
    plan = proj.load_plan()
    assert plan["turns"] == ["take_01.mp4", "take_02.mp4", "take_03.mp4"]
    assert plan["extension_mode"] == "segments"        # the fake clip is 2 s each time, so turns are joined
    assert steps[0] == ("video", "Shooting · segment 1 of 3") and steps[-1][0] == "stitch"


def test_shoot_reel_needs_a_face(client, s, lib, mira):
    proj = inf.write_script(client, s, lib, mira, "talking_head", "pancakes", "", 10)
    with pytest.raises(Exception, match="identity pack"):
        inf.shoot_reel(client, s, lib, mira, proj)
    assert not [c for c in client.calls if c[0] == "interactions.create"]


def test_shoot_reel_uses_prompt_overrides(client, s, lib, mira, mp4_bytes):
    inf.paint_identity(client, s, lib, mira, views=["face"])
    proj = inf.write_script(client, s, lib, mira, "talking_head", "pancakes", "", 10)
    plan = copy.deepcopy(proj.load_plan())
    plan["prompt_overrides"] = {"p1": "my own prompt"}
    proj.save_plan(plan)
    inf.shoot_reel(client, s, lib, mira, proj, log=lambda *_: None)
    create = [c[1] for c in client.calls if c[0] == "interactions.create"][0]
    assert create["input"][-1]["text"] == "my own prompt"
    assert len([x for x in create["input"] if x["type"] == "image"]) == 1
    assert proj.load_plan()["extension_mode"] == "cumulative"          # one turn: that is the reel


def test_omni_is_the_only_provider_that_extends(s):
    import providers
    caps = {c["id"]: c["caps"]["extend"] for c in providers.catalog(s)}
    assert caps == {"gemini-omni": True, "veo-fast": False, "veo": False, "kling": False}
    with pytest.raises(providers.ProviderError, match="can't extend"):
        providers.video_provider("veo-fast", s).submit_extend({}, "more")
