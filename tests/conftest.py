"""Fixtures for the offline tests (no API calls, nothing billed)."""
import subprocess

import pytest

import pipeline as pl
from fakes import HAS_FFMPEG, FakeClient


@pytest.fixture(scope="session")
def mp4_bytes(tmp_path_factory) -> bytes:
    if not HAS_FFMPEG:
        return b"not-a-real-mp4"
    out = tmp_path_factory.mktemp("clip") / "c.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=d=2:s=320x180:r=24",
                    "-f", "lavfi", "-i", "sine=d=2", "-shortest", "-c:v", "libx264", "-c:a", "aac",
                    str(out)], check=True)
    return out.read_bytes()


@pytest.fixture
def s():
    return pl.Settings(backend="gemini", orientation="16:9", resolution="360p", image_size="1K")


@pytest.fixture
def client(mp4_bytes):
    return FakeClient(mp4_bytes)


@pytest.fixture
def proj(tmp_path, client, s):
    return pl.new_project(client, s, "story", "style", 3, base_dir=tmp_path)

