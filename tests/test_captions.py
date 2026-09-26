"""Captions: script words, timing, grouping, ASS output, burn-in."""
import json
from types import SimpleNamespace as NS

import pytest

import captions as cap
import editor
import pipeline as pl
from fakes import HAS_FFMPEG

PLAN = {"segments": [
    {"id": "p1", "seconds": 10, "lines": ["Okay, hear me out.", "I literally haven't spoken to anyone today."]},
    {"id": "p2", "seconds": 10, "lines": ["It's wild, right?"]},
]}


def test_estimate_keeps_every_script_word_in_its_segment():
    words = cap.estimate_words(PLAN, 20.0)
    assert [w["text"] for w in words] == "Okay, hear me out. I literally haven't spoken to anyone today. It's wild, right?".split()
    assert all(0 <= w["start"] < w["end"] <= 10 for w in words if w["seg"] == 0)
    assert all(10 <= w["start"] < w["end"] <= 20 for w in words if w["seg"] == 1)
    assert [w["br"] for w in words].count(True) == 3                  # one per script line
    assert all(a["end"] <= b["start"] for a, b in zip(words, words[1:]))
    # a slightly longer video stretches the windows
    assert cap.estimate_words(PLAN, 22.0)[-1]["end"] > 20


def test_fix_times_interpolates_and_orders():
    words = [{"text": "a", "start": 1.0, "end": 1.3}, {"text": "b", "start": None, "end": None},
             {"text": "c", "start": 0.2, "end": 0.4},            # goes backwards: re-timed
             {"text": "d", "start": 2.0, "end": 2.4}]
    out = cap.fix_times(words, 3.0)
    assert [w["text"] for w in out] == ["a", "b", "c", "d"]
    assert out[0]["end"] <= out[1]["start"] < out[2]["start"] < out[3]["start"]


def test_chunks_break_at_sentences_lines_and_size():
    words = cap.estimate_words(PLAN, 20.0)
    style = cap.clean_style({"words": 3})
    texts = [" ".join(words[i]["text"] for i in c["words"]) for c in cap.chunk(words, style)]
    assert texts[:3] == ["Okay,", "hear me out.", "I literally haven't"]
    assert texts[-2:] == ["It's wild,", "right?"]
    one = cap.chunk(words, cap.clean_style({"words": 1}))
    assert len(one) == len(words)


def test_clean_style_guards_everything():
    s = cap.clean_style({"font": "comic-sans", "color": "red", "size": 99, "words": 0, "animation": "spin", "x": 1})
    assert s["font"] == "poppins-extrabold" and s["color"] == "#FFFFFF" and s["size"] == 14
    assert s["words"] == 1 and s["animation"] == "pop" and "x" not in s
    assert {p["id"] for p in cap.PRESETS} >= {"bold-pop", "boxed", "one-word"}
    assert all(cap.clean_style(p["style"])["font"] in cap.BUNDLED_IDS for p in cap.PRESETS)


def test_ass_highlights_the_spoken_word_and_respects_the_trim():
    words = cap.estimate_words(PLAN, 20.0)
    style = {"font": "kanit-bold", "animation": "highlight", "words": 3, "highlight": "#39E75F", "uppercase": True}
    a = cap.ass(words, style, 720, 1280)
    assert "PlayResX: 720" in a and "Style: Cap,Kanit Bold," in a                        # matched by full name
    lines = [l for l in a.splitlines() if l.startswith("Dialogue")]
    assert len(lines) == len(words)                  # one event per spoken word
    assert "{\\c&H005FE739}HEAR{\\c&H00FFFFFF" in a  # green, as ASS BGR
    trimmed = cap.ass(words, style, 720, 1280, start=10, end=20)
    first = [l for l in trimmed.splitlines() if l.startswith("Dialogue")][0]
    assert first.split(",")[1].startswith("0:00:00") and "IT'S" in first
    boxed = cap.ass(words, {"box": True, "words": 6, "lines": 2, "animation": "none"}, 720, 1280)
    assert ",3," in [l for l in boxed.splitlines() if l.startswith("Style")][0] and "\\N" in boxed


def test_fonts_have_metrics(tmp_path):
    import fontbook as fb
    fonts = fb.FontBook(tmp_path).all()
    assert len(fonts) == len(fb.BUNDLED)
    assert all(0.4 < f["em_scale"] < 1.2 for f in fonts)      # Poppins is ~0.57: tall win metrics
    assert {f["id"]: f["ass_name"] for f in fonts}["kanit-bold"] == "Kanit Bold"


def test_align_keeps_the_words_and_takes_only_times(tmp_path, s, monkeypatch):
    words = cap.estimate_words(PLAN, 20.0)
    monkeypatch.setattr(cap, "extract_audio", lambda v, out: (out.write_bytes(b"mp3"), out)[1])
    reply = {"words": [{"i": i, "start": 1 + i * 0.5, "end": 1.3 + i * 0.5} for i in range(len(words))],
             "differences": [{"at": 2.1, "expected": "hear me out", "heard": "hear me out, okay"}]}
    reply["words"][3] = {"i": 3, "start": -1, "end": -1}          # not spoken
    calls = []
    client = NS(models=NS(generate_content=lambda **kw: calls.append(kw) or NS(
        text=json.dumps(reply), usage_metadata=NS(prompt_token_count=900, candidates_token_count=800, thoughts_token_count=0))))
    out, diffs, usage = cap.align(client, s, tmp_path / "final.mp4", words, 20.0)
    assert [w["text"] for w in out] == [w["text"] for w in words]
    assert out[0]["start"] == 1.0 and out[2]["start"] == 2.0
    assert out[1]["end"] <= out[3]["start"] < out[4]["start"] == 3.0        # the missing one interpolated
    assert diffs[0]["heard"] == "hear me out, okay" and usage["input"] == 900
    assert "0: Okay," in calls[0]["contents"][1]


def test_state_rebuilds_when_the_script_changes():
    st = cap.state(PLAN, 20.0)
    assert not st["enabled"] and st["synced"] == "estimate" and st["style"]["animation"] == "highlight_pop"
    plan = {**PLAN, "captions": {**st, "enabled": True, "synced": "voice", "words": st["words"][:2]}}
    assert cap.state(plan, 20.0)["synced"] == "voice"                       # same script: kept
    plan["segments"] = [{"id": "p1", "seconds": 10, "lines": ["Totally new."]}]
    fresh = cap.state(plan, 10.0)
    assert fresh["synced"] == "estimate" and [w["text"] for w in fresh["words"]] == ["Totally", "new."]
    assert fresh["enabled"]                                                 # choice kept


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_burn_in(tmp_path, mp4_bytes):
    src = tmp_path / "final.mp4"
    src.write_bytes(mp4_bytes)
    words = cap.estimate_words({"segments": [{"id": "p1", "seconds": 2, "lines": ["Hello there friend."]}]}, 2.0)
    ass_file = tmp_path / "captions.ass"
    ass_file.write_text(cap.ass(words, {"animation": "highlight_pop"}, 320, 180), encoding="utf-8")
    out = tmp_path / "edited.mp4"
    editor.render(src, out, {}, 2.0, subtitles=cap.subtitles_filter(ass_file))
    assert out.exists() and abs(pl.video_duration(out) - 2.0) < 0.2
