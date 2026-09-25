"""Headless run:  python cli.py --story "..." --style "..." [--orientation 16:9] [--resolution 360p]"""
import argparse
from pathlib import Path

import pipeline as pl

ap = argparse.ArgumentParser()
ap.add_argument("--story", required=True)
ap.add_argument("--style", default="")
ap.add_argument("--orientation", default="9:16", choices=["9:16", "16:9"])
ap.add_argument("--resolution", default="720p", choices=["360p", "720p", "1080p", "4k"],
                help="use 360p for test runs")
ap.add_argument("--image-size", default="2K", choices=["1K", "2K", "4K"],
                help="reference images; 1K and 2K cost the same")
ap.add_argument("--scenes", type=int, default=6)
ap.add_argument("--out", default="projects")
ap.add_argument("--backend", choices=["gemini", "vertex"],
                help="default: vertex if GOOGLE_GENAI_USE_VERTEXAI is set, else gemini")
a = ap.parse_args()

s = pl.Settings(orientation=a.orientation, resolution=a.resolution, image_size=a.image_size)
if a.backend:
    s.backend = a.backend
proj = pl.run_all(a.story, a.style, s, Path(a.out), a.scenes)
print(f"Project folder: {proj.root}")
