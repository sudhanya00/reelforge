"""Influencer mode: profiles, identity pack, places, setups, opening frames and extended reels (offline)."""
import copy

import pytest

import influencers as inf
import pipeline as pl
from fakes import FAKE_PROFILE, HAS_FFMPEG, api_error, log_entries


@pytest.fixture
def lib(tmp_path):
    return inf.Influencers(tmp_path / "library")


@pytest.fixture
def mira(lib):
    return lib.create(FAKE_PROFILE)["id"]


def image_calls(client):
    return [c for c in client.calls if c[0] == "generate_content" and c[3].response_modalities == ["IMAGE"]]


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
    calls = image_calls(client)
    # face and setting are painted from text; the three other views carry the face as a reference
    assert [len(c[2]) - 1 for c in calls] == [0, 0, 1, 1, 1]
    assert len((lib.dir(mira) / "log.jsonl").read_text(encoding="utf-8").splitlines()) == 5
    assert set(inf.paint_identity(client, s, lib, mira).values()) == {"skipped"}
    assert inf.paint_identity(client, s, lib, mira, views=["profile"], force=True) == {"profile": "done"}


def test_paint_identity_needs_the_face_and_stops_on_fatal(client, s, lib, mira):
    assert inf.paint_identity(client, s, lib, mira, views=["profile"]) == {"profile": "failed: paint the face first"}
    client.errors["image"] = [api_error(403, "billing disabled")]
    res = inf.paint_identity(client, s, lib, mira)
    assert res["face"].startswith("fatal") and len(res) == 1


def test_places_home_plus_saved(client, s, lib, mira):
    place = lib.add_place(mira, "Club Nova", "a dark club with neon strips and a packed dance floor")
    assert place["id"] == "club_nova" and lib.add_place(mira, "Club Nova", "x")["id"] == "club_nova_2"
    ids = [x["id"] for x in lib.places(lib.get(mira))]
    assert ids == ["home", "club_nova", "club_nova_2"]
    inf.paint_place(client, s, lib, mira, "club_nova")
    assert lib.place(lib.get(mira), "club_nova")["image"].exists()
    assert "neon strips" in image_calls(client)[-1][2][-1]
    lib.remove_place(mira, "club_nova")
    assert not (lib.dir(mira) / "places" / "club_nova.png").exists()
    with pytest.raises(KeyError):
        lib.remove_place(mira, "home")


def test_write_script_sets_up_the_video(client, s, lib, mira):
    proj = inf.write_script(client, s, lib, mira, "walk_and_talk", "cheap breakfast", "", 27, outfit="red dress")
    plan = proj.load_plan()
    assert plan["kind"] == "reel" and plan["influencer"] == mira and plan["format"] == "walk_and_talk"
    assert plan["brief"]["length_s"] == 30
    assert [(g["id"], g["seconds"]) for g in plan["segments"]] == [("p1", 10), ("p2", 10), ("p3", 10)]
    # the AI's setup, with the user's outfit kept
    assert plan["setup"] == {"location": "a bright corner shop aisle", "outfit": "red dress",
                             "position": "walking down the aisle", "light": "fluorescent shop light", "place": "",
                             "products": []}
    prompt = [c for c in client.calls if c[0] == "generate_content"][-1][2]
    assert "Walk and talk" in prompt and "outfit: red dress" in prompt and "3 segments" in prompt
    assert [v.root for v in lib.videos(mira)] == [proj.root]
    assert log_entries(proj)[0]["kind"] == "plan"


def test_write_script_at_a_saved_place(client, s, lib, mira):
    lib.add_place(mira, "Gym", "a small concrete gym with chalky racks")
    proj = inf.write_script(client, s, lib, mira, "mirror", "leg day fit", "", 10, place="gym")
    setup = proj.load_plan()["setup"]
    assert setup["place"] == "gym" and setup["location"] == "a small concrete gym with chalky racks"
    with pytest.raises(ValueError):
        inf.write_script(client, s, lib, mira, "interpretive_dance", "x", "", 10)


def test_opening_prompts_per_format():
    plan = {"format": "mirror", "setup": {"location": "hotel bathroom", "outfit": "black slip dress",
                                          "position": "", "light": "warm vanity bulbs", "place": ""}}
    o = inf.opening_prompt(FAKE_PROFILE, plan, "opening", [("the person", 3)])
    assert o.startswith("Reference images, in order: image 1-3: the person.")
    assert "Ignore the clothes in those images" in o and "black slip dress" in o
    assert "mirror" in o and "phone held at chest height and visible" in o and "olive cardigan" not in o
    walk_in = {**plan, "format": "walk_in"}
    assert inf.opening_views(walk_in) == ["opening", "look"]
    empty = inf.opening_prompt(FAKE_PROFILE, walk_in, "opening", [("the place", 1)])
    assert "nobody in it" in empty and "black slip dress" not in empty and "place is the one in its reference" in empty
    look = inf.opening_prompt(FAKE_PROFILE, walk_in, "look", [("the person", 3)])
    assert "full-length" in look and "black slip dress" in look
    # an old video (no setup) is at home in the go-to outfit
    old = inf.setup_of({"format": "talking_head"}, FAKE_PROFILE)
    assert old["place"] == "home" and old["outfit"] == FAKE_PROFILE["outfit"]


def test_segment_prompts():
    plan = {"format": "podcast", "setup": {"location": "a small studio", "outfit": "denim jacket",
                                           "position": "seated", "light": "warm practicals", "place": ""}}
    seg = {"id": "p1", "seconds": 10, "lines": ["Okay so.", "Three things."], "delivery": "excited",
           "action": "leans into the mic"}
    first = inf.segment_prompt(FAKE_PROFILE, plan, seg, ["face", "three_quarter", "profile"], first=True)
    assert first.startswith("[# Sources <FIRST_FRAME>@Image1] [# References <IMAGE_REF_0>@Image2 "
                            "<IMAGE_REF_1>@Image3 <IMAGE_REF_2>@Image4]")
    assert "Start from Image1" in first and "broadcast microphone" in first and "denim jacket" in first
    assert "half to an off-screen co-host" in first and '"Okay so. Three things."' in first
    assert "no background music" in first
    more = inf.segment_prompt(FAKE_PROFILE, plan, seg, [], first=False)
    assert more.startswith("Continue the same continuous take for 10 more seconds: same person, podcast set")
    assert "IMAGE_REF" not in more and more.endswith("Keep everything else the same.")
    # no opening frame (videos from before setups): identity + home as references
    old = inf.segment_prompt(FAKE_PROFILE, {"format": "talking_head"}, seg, ["face", "place"], first=True,
                             has_opening=False)
    assert old.startswith("[# References <IMAGE_REF_0>@Image1 <IMAGE_REF_1>@Image2]")
    assert "place is the one in <IMAGE_REF_1>" in old and "Start from" not in old


def test_paint_opening_and_staleness(client, s, lib, mira):
    inf.paint_identity(client, s, lib, mira)
    lib.add_place(mira, "Gym", "a small concrete gym")
    inf.paint_place(client, s, lib, mira, "gym")
    proj = inf.write_script(client, s, lib, mira, "walk_in", "leg day", "", 10, place="gym")
    assert not inf.opening_ok(lib, mira, proj)
    n = len(image_calls(client))
    inf.paint_opening(client, s, lib, mira, proj)
    calls = image_calls(client)[n:]
    assert len(calls) == 2 and inf.opening_ok(lib, mira, proj)
    assert len(calls[0][2]) == 2                    # empty opening: just the gym plate
    assert len(calls[1][2]) == 4                    # the look: face, three-quarter, full body
    assert [e["id"] for e in log_entries(proj) if e["kind"] == "image"] == ["opening", "look"]
    plan = proj.load_plan()
    plan["setup"]["outfit"] = "a tracksuit"
    proj.save_plan(plan)
    assert not inf.opening_ok(lib, mira, proj)      # the setup changed


def test_estimate_bills_new_seconds_plus_reread(s, lib, mira, client):
    proj = inf.write_script(client, s, lib, mira, "talking_head", "x", "", 30)
    e = inf.estimate_usd(s, proj.load_plan(), needs_opening=True)
    per_s = 1931 * 17.5 / 1e6                        # 360p output
    reread = (10 + 20) * 1931 * 1.5 / 1e6            # turns 2 and 3 re-read 10 s and 20 s
    assert e["video_usd"] == round(30 * per_s + reread, 2)
    assert e["images_usd"] == pl.estimate_image_usd(s, 1) and e["usd"] == round(e["video_usd"] + e["images_usd"], 2)
    assert inf.estimate_usd(s, proj.load_plan(), needs_opening=False)["images_usd"] == 0


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_shoot_reel_paints_opening_then_generates_and_extends(client, s, lib, mira):
    inf.paint_identity(client, s, lib, mira)
    proj = inf.write_script(client, s, lib, mira, "walk_and_talk", "pancakes", "", 30)
    steps = []
    final = inf.shoot_reel(client, s, lib, mira, proj, log=lambda *_: None, step=lambda *a: steps.append(a[:2]))
    assert final.exists() and inf.opening_ok(lib, mira, proj)
    creates = [c[1] for c in client.calls if c[0] == "interactions.create"]
    assert len(creates) == 3
    first, ext1, ext2 = creates
    assert "previous_interaction_id" not in first
    assert len([x for x in first["input"] if x["type"] == "image"]) == 4        # opening + face, 3/4, profile
    assert first["input"][-1]["text"].startswith("[# Sources <FIRST_FRAME>@Image1]")
    assert "walk" in first["input"][-1]["text"] and first["response_format"]["aspect_ratio"] == "9:16"
    assert ext1["previous_interaction_id"] == "ix1" and ext2["previous_interaction_id"] == "ix2"
    assert ext1["input"].startswith("Continue the same continuous take")
    kinds = [e["kind"] for e in log_entries(proj)]
    assert kinds.count("image") == 1 and kinds.count("video") == 1 and kinds.count("video_edit") == 2
    plan = proj.load_plan()
    assert plan["turns"] == ["take_01.mp4", "take_02.mp4", "take_03.mp4"]
    assert plan["extension_mode"] == "segments"        # the fake clip is 2 s each time, so turns are joined
    assert steps[0] == ("image", "Painting the opening frame") and steps[1] == ("video", "Shooting · segment 1 of 3")
    # shooting again reuses the opening frame
    n = len(image_calls(client))
    inf.shoot_reel(client, s, lib, mira, proj, log=lambda *_: None)
    assert len(image_calls(client)) == n


def test_shoot_reel_needs_a_face(client, s, lib, mira):
    proj = inf.write_script(client, s, lib, mira, "talking_head", "pancakes", "", 10)
    with pytest.raises(Exception, match="identity pack"):
        inf.shoot_reel(client, s, lib, mira, proj)
    assert not [c for c in client.calls if c[0] == "interactions.create"]


def test_shoot_reel_uses_prompt_overrides(client, s, lib, mira):
    inf.paint_identity(client, s, lib, mira, views=["face"])
    proj = inf.write_script(client, s, lib, mira, "talking_head", "pancakes", "", 10)
    plan = copy.deepcopy(proj.load_plan())
    plan["prompt_overrides"] = {"p1": "my own prompt"}
    proj.save_plan(plan)
    inf.shoot_reel(client, s, lib, mira, proj, log=lambda *_: None)
    create = [c[1] for c in client.calls if c[0] == "interactions.create"][0]
    assert create["input"][-1]["text"] == "my own prompt"
    assert len([x for x in create["input"] if x["type"] == "image"]) == 2      # opening + face
    assert proj.load_plan()["extension_mode"] == "cumulative"          # one turn: that is the reel


def test_omni_is_the_only_provider_that_extends(s):
    import providers
    caps = {c["id"]: c["caps"]["extend"] for c in providers.catalog(s)}
    assert caps == {"gemini-omni": True, "veo-fast": False, "veo": False, "kling": False}
    with pytest.raises(providers.ProviderError, match="can't extend"):
        providers.video_provider("veo-fast", s).submit_extend({}, "more")


# ---------------------------------------------------------------- products and characters from photos

from PIL import Image  # noqa: E402

import products as prodmod  # noqa: E402
import uploads as up  # noqa: E402


def _photo(tmp_path, name, color=(200, 30, 60), exif_gps=False):
    img = Image.new("RGB", (800, 600), color)
    path = tmp_path / name
    if exif_gps:
        exif = Image.Exif()
        exif[0x8825] = {2: (51, 30, 0)}                 # a GPS latitude
        img.save(path, format="JPEG", exif=exif)
    else:
        img.save(path, format="JPEG")
    return path


def test_uploads_are_cleaned_pngs_without_metadata(tmp_path):
    ups = up.Uploads(tmp_path / "library")
    tok = ups.add(_photo(tmp_path, "gps.jpg", exif_gps=True).read_bytes())
    stored = ups.path(tok)
    assert stored.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert not Image.open(stored).getexif()                     # GPS and all EXIF gone
    with pytest.raises(up.UploadError):
        ups.add(b"not an image")
    with pytest.raises(KeyError):
        ups.path("../../etc")


def _product(lib, tmp_path, kind="beauty", name="satin lipstick", brand="Rouge Co"):
    ups = up.Uploads(tmp_path / "library")
    photos = [ups.path(ups.add(_photo(tmp_path, f"p{i}.jpg").read_bytes())) for i in range(2)]
    return lib.products.create({"name": name, "brand": brand, "kind": kind,
                                "description": 'red bullet, gold case printed "ROUGE"', "notes": "12 shades"}, photos)


def test_products_are_stored_described_and_packshotted(client, s, lib, mira, tmp_path):
    x = _product(lib, tmp_path)
    assert x["id"] == "rouge_co_satin_lipstick" and len(lib.products.photos(x["id"])) == 2
    assert lib.products.refs(x["id"]) == lib.products.photos(x["id"])[:1]      # no packshot yet
    prodmod.paint_packshot(client, s, lib.products, x["id"])
    assert lib.products.refs(x["id"])[0].name == "packshot.png"
    call = image_calls(client)[-1]
    assert len(call[2]) == 3 and "plain light-grey background" in call[2][-1] and "Rouge Co" in call[2][-1]
    out, usage = prodmod.describe(client, s, lib.products.photos(x["id"]))
    assert out["kind"] in prodmod.KINDS and usage


def test_a_worn_and_a_held_product_in_the_script_opening_and_video(client, s, lib, mira, tmp_path):
    inf.paint_identity(client, s, lib, mira)
    top = _product(lib, tmp_path, kind="clothing", name="lilac cable-knit top", brand="")
    stick = _product(lib, tmp_path)
    proj = inf.write_script(client, s, lib, mira, "talking_head", "lipstick review", "", 20,
                            products=[{"id": top["id"], "use": ""}, {"id": stick["id"], "use": "hold"}])
    setup = proj.load_plan()["setup"]
    assert setup["products"] == [{"id": top["id"], "use": "wear"}, {"id": stick["id"], "use": "hold"}]
    assert setup["outfit"].startswith("the lilac cable-knit top")          # worn product forced into the outfit
    sp = [c for c in client.calls if c[0] == "generate_content"][-1][2]
    assert "FEATURING:" in sp and "satin lipstick by Rouge Co (they hold it" in sp and "12 shades" in sp
    assert "must wear: the lilac cable-knit top" in sp

    n = len(image_calls(client))
    inf.paint_opening(client, s, lib, mira, proj)
    call = image_calls(client)[n]
    prompt = call[2][-1]
    assert len(call[2]) - 1 == 3 + 1 + 1                                    # person x3, top x1, lipstick x1
    assert prompt.startswith("Reference images, in order: image 1-3: the person; image 4: the lilac cable-knit top; "
                             "image 5: the satin lipstick by Rouge Co.")
    assert "wearing the lilac cable-knit top exactly as in its reference images" in prompt
    assert "hold the satin lipstick by Rouge Co in one hand" in prompt

    if not HAS_FFMPEG:
        return
    inf.shoot_reel(client, s, lib, mira, proj, log=lambda *_: None)
    first, ext = [c[1] for c in client.calls if c[0] == "interactions.create"][-2:]
    text = first["input"][-1]["text"]
    assert len([x for x in first["input"] if x["type"] == "image"]) == 1 + 3 + 2   # opening, identity, products
    assert "They wear the lilac cable-knit top from <IMAGE_REF_3>" in text
    assert "The satin lipstick by Rouge Co is the object in <IMAGE_REF_4>" in text
    assert "the satin lipstick by Rouge Co exactly as before" in ext["input"]


def test_a_deleted_product_drops_out_quietly(lib, tmp_path):
    x = _product(lib, tmp_path)
    assert [f["id"] for f in lib.featured({"products": [{"id": x["id"]}, {"id": "gone"}]})] == [x["id"]]
    assert lib.featured({"products": [{"id": x["id"]}]})[0]["use"] == "hold"     # a beauty product: held


def test_character_from_photos_needs_consent_and_paints_from_them(client, s, tmp_path):
    lib = inf.Influencers(tmp_path / "library")
    ups = up.Uploads(tmp_path / "library")
    photos = [ups.path(ups.add(_photo(tmp_path, f"me{i}.jpg", (90, 60, 40)).read_bytes())) for i in range(3)]
    with pytest.raises(ValueError, match="right to use"):
        lib.create({"name": "Me"}, sources=photos)
    me = lib.create({"name": "Me", **{k: FAKE_PROFILE[k] for k in ("age", "hair", "outfit", "setting")}},
                    sources=photos, consent="These are photos of me.")
    assert len(lib.sources(me["id"])) == 3 and me["consent"]["text"] == "These are photos of me."
    inf.paint_identity(client, s, lib, me["id"])
    calls = image_calls(client)
    face, setting = calls[0], calls[1]                                     # face and home first
    assert len(face[2]) - 1 == 3 and "same person as in the reference photos" in face[2][-1]
    assert len(setting[2]) == 1                                           # the room: no photos of the person
    side = calls[-1]
    assert len(side[2]) - 1 == 1 + 3                                       # the painted face + the photos
    lib.remove_source(me["id"], "01.png")
    assert len(lib.sources(me["id"])) == 2
    out, usage = inf.describe_person(client, s, lib.sources(me["id"]))
    assert set(out) >= set(inf.DESCRIBE_PERSON_KEYS)


def test_look_text_skips_blank_fields():
    assert inf.look_text({"age": "", "ethnicity": "", "gender": "", "skin": "olive", "hair": "bob",
                          "body": "", "features": ""}) == "Skin: olive. Hair: bob."
    assert inf.look_text(FAKE_PROFILE).startswith("27-year-old Filipino woman. Skin:")


# ---------------------------------------------------------------- casting

def test_casting_options_refine_and_lock(client, s, lib, mira):
    import os
    names = inf.cast_faces(client, s, lib, mira, 3, direction="softer, girl-next-door")
    assert names == ["01.png", "02.png", "03.png"]
    prompts = [c[2][-1] for c in image_calls(client)]
    assert len(set(prompts)) == 3                                        # each nudged to be its own person
    assert all("girl-next-door" in x and "mole above the lip" in x for x in prompts)
    assert all(len(c[2]) == 1 for c in image_calls(client))            # from words only

    new = inf.refine_face(client, s, lib, mira, "02.png", "fuller lips, lighter brows")
    last = image_calls(client)[-1]
    assert new == "04.png" and len(last[2]) == 2 and "only these changes: fuller lips" in last[2][-1]
    cast = lib.get(mira)["casting"]
    assert [c["from"] for c in cast["candidates"]] == [None, None, None, "02.png"]

    # views painted from an older face go out of date when a new face is locked
    inf.paint_identity(client, s, lib, mira)
    old = lib.image(mira, "profile").stat().st_mtime
    os.utime(lib.image(mira, "profile"), (old - 60, old - 60))
    inf.lock_face(lib, mira, "04.png")
    assert lib.image(mira, "face").read_bytes() == (inf.casting_dir(lib, mira) / "04.png").read_bytes()
    assert "profile" in inf.stale_views(lib, mira) and lib.get(mira)["casting"]["locked"] == "04.png"
    inf.paint_identity(client, s, lib, mira, views=inf.stale_views(lib, mira), force=True)
    assert inf.stale_views(lib, mira) == []

    inf.remove_candidate(lib, mira, "04.png")
    assert lib.get(mira)["casting"]["locked"] is None and not (inf.casting_dir(lib, mira) / "04.png").exists()
    with pytest.raises(KeyError):
        inf.lock_face(lib, mira, "../face.png")
    with pytest.raises(ValueError):
        inf.refine_face(client, s, lib, mira, "01.png", "  ")
