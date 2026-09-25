"""The motion meter on synthetic clips (frozen / moving / cut), and the reviewer request."""
import json
import subprocess

import pytest

import pipeline as pl
import review
from fakes import HAS_FFMPEG

pytestmark = pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")


def clip(path, filter_graph, seconds=4):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", filter_graph, "-t", str(seconds),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def test_frozen_start_is_measured_as_dead_time(tmp_path):
    # 2 s of a still frame, then 2 s of motion
    still = clip(tmp_path / "a.mp4", "color=c=gray:s=320x180:r=24", 2)
    moving = clip(tmp_path / "b.mp4", "testsrc2=s=320x180:r=24", 2)
    lst = tmp_path / "l.txt"
    lst.write_text(f"file '{still.as_posix()}'\nfile '{moving.as_posix()}'\n")
    out = tmp_path / "out.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c:v", "libx264", str(out)], check=True)
    m = review.motion_profile(out)
    assert m["dead"] and m["dead"][0][0] == 0 and 1.6 <= m["dead"][0][1] <= 2.2
    assert m["cuts"] and 1.8 <= m["cuts"][0] <= 2.3          # the jump into the moving clip


def test_moving_clip_has_no_dead_time(tmp_path):
    m = review.motion_profile(clip(tmp_path / "m.mp4", "testsrc2=s=320x180:r=24"))
    assert m["dead_s"] == 0 and m["mean"] > review.STILL_BELOW


def test_review_sends_brief_refs_and_video(proj, client, s):
    pl.generate_assets(client, s, proj)
    take = pl.generate_take(client, s, proj, "s01")
    r = review.review_take(client, s, proj, "s01", take)
    call = [c for c in client.calls if c[0] == "generate_content"][-1]
    contents = call[2]
    assert contents[0].startswith("BRIEF") and "Asha walks" in contents[0]
    video = contents[-1]
    assert video.inline_data.mime_type == "video/mp4" and video.video_metadata.fps == 4
    assert sum(1 for x in contents if isinstance(x, str) and x.startswith("Reference ")) == 2
    meta = json.loads(take.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["review"]["verdict"] == "fix" and meta["motion"] is not None
    assert r["overall"] == 4.0
