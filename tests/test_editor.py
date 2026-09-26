"""The small editor: trim, colour, audio (ffmpeg)."""
import pytest

import editor
import pipeline as pl
from fakes import HAS_FFMPEG


def test_clean_clamps_and_drops_no_op_trims():
    e = editor.clean({"brightness": 9, "warmth": -3, "end": 20, "junk": 1}, duration=20)
    assert e["brightness"] == 1.5 and e["warmth"] == -1 and e["end"] is None and "junk" not in e
    assert editor.is_identity(editor.clean({}))
    with pytest.raises(ValueError):
        editor.clean({"start": 3, "end": 3.2})


def test_color_matrix_is_identity_by_default_and_warmth_shifts_red_and_blue():
    m = editor.color_matrix(editor.clean({}))
    assert all(abs(m[i][j] - (1 if i == j else 0)) < 1e-9 for i in range(3) for j in range(3))
    w = editor.color_matrix(editor.clean({"warmth": 1}))
    assert w[0][0] > 1 > w[2][2]
    grey = editor.color_matrix(editor.clean({"saturation": 0}))
    assert grey[0] == grey[1] == pytest.approx(grey[2])      # every channel is the same luma


def test_filters_only_for_what_changed():
    assert editor.video_filter(editor.clean({})) is None and editor.audio_filter(editor.clean({})) is None
    e = editor.clean({"contrast": 1.2, "saturation": 1.1, "denoise": True, "normalize": True, "volume": 1.5})
    vf, af = editor.video_filter(e), editor.audio_filter(e)
    assert vf.startswith("colorchannelmixer=rr=") and "lutrgb" in vf
    assert af == "afftdn=nf=-25,volume=1.500,loudnorm=I=-14:TP=-1.5:LRA=11"
    cmd = editor.command(editor.Path("in.mp4"), editor.Path("out.mp4"), editor.clean({"start": 1, "end": 5, "mute": True}))
    assert cmd[cmd.index("-ss") + 1] == "1.000" and cmd[cmd.index("-t") + 1] == "4.000" and "-an" in cmd


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs ffmpeg")
def test_render_trims_and_grades(tmp_path, mp4_bytes):
    src = tmp_path / "final.mp4"
    src.write_bytes(mp4_bytes)
    out = tmp_path / "edited.mp4"
    e = editor.render(src, out, {"start": 0.5, "end": 1.5, "warmth": 0.5, "contrast": 1.2, "denoise": True,
                                 "normalize": True}, duration=pl.video_duration(src))
    assert out.exists() and abs(pl.video_duration(out) - 1.0) < 0.15
    assert e["warmth"] == 0.5 and not (tmp_path / "edited.part.mp4").exists()
