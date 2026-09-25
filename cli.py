"""Headless run:  python cli.py --story "..." --style "..." --orientation 9:16 --scenes 6"""
import argparse
from pathlib import Path

import pipeline as pl

ap = argparse.ArgumentParser()
ap.add_argument("--story", required=True)
ap.add_argument("--style", default="")
ap.add_argument("--orientation", default="16:9", choices=["16:9", "9:16"])
ap.add_argument("--resolution", default="720p", choices=["360p", "720p", "1080p", "4k"])
ap.add_argument("--scenes", type=int, default=6)
ap.add_argument("--out", default="projects")
a = ap.parse_args()

s = pl.Settings(orientation=a.orientation, resolution=a.resolution)
proj = pl.run_all(a.story, a.style, s, Path(a.out), a.scenes)
print(f"Project folder: {proj.root}")
