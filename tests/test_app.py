"""Headless Streamlit checks: the app renders every view without raising. No API calls."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import pipeline as pl
from fakes import FakeClient

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def workdir(tmp_path, monkeypatch, mp4_bytes):
    """A cwd with one project that has refs and a take, like a real session."""
    monkeypatch.chdir(tmp_path)
    s = pl.Settings(backend="gemini", orientation="16:9", resolution="360p", image_size="1K")
    c = FakeClient(mp4_bytes)
    proj = pl.new_project(c, s, "story", "style", 3, base_dir=tmp_path / "projects")
    pl.generate_assets(c, s, proj)
    pl.generate_take(c, s, proj, "s01")
    return proj


def run(at):
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_new_film_page(workdir):
    at = run(AppTest.from_file(APP, default_timeout=60))
    assert at.title[0].value == "New film"
    at.sidebar.radio[0].set_value("vertex")
    run(at)


def test_project_page_renders_all_tabs(workdir):
    at = run(AppTest.from_file(APP, default_timeout=60))
    pick = next(sb for sb in at.sidebar.selectbox if sb.label == "Open project")
    pick.set_value(workdir.root.name)
    run(at)
    assert at.title[0].value == "Test Film"
    assert [t.label for t in at.tabs] == ["Plan", "References", "Scenes", "Final cut"]
    assert any("spent so far: $" in c.value for c in at.caption)
    labels = [b.label for b in at.button]
    assert any(l.startswith("Shoot a take (720p, ≈$") for l in labels)
    assert any(l.startswith("Apply fix (≈$") for l in labels)


def test_final_cut_offers_to_finish(workdir):
    at = run(AppTest.from_file(APP, default_timeout=60))
    next(sb for sb in at.sidebar.selectbox if sb.label == "Open project").set_value(workdir.root.name)
    run(at)
    assert any(b.label.startswith("Make everything missing, then stitch (≈$") for b in at.button)
