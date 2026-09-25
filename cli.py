"""Headless run.

  python cli.py --story "..." --style "..." [--orientation 16:9] [--resolution 360p]
  python cli.py --resume projects/<folder>      # make only what's missing, then stitch
"""
import argparse
import sys
from pathlib import Path

import pipeline as pl

# Windows pipes default to cp1252; plan titles and logs can contain any character
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8", errors="replace")

ap = argparse.ArgumentParser()
ap.add_argument("--story", help="required unless --resume")
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
ap.add_argument("--resume", metavar="PROJECT_DIR",
                help="finish an existing project: skip what's done, make what's missing")
a = ap.parse_args()
if not a.story and not a.resume:
    ap.error("--story is required (or --resume PROJECT_DIR)")

# backend goes in the constructor so the model ids default to that backend's
extra = {"backend": a.backend} if a.backend else {}
s = pl.Settings(orientation=a.orientation, resolution=a.resolution, image_size=a.image_size, **extra)

try:
    if a.resume:
        proj = pl.Project.open(Path(a.resume))
        result = pl.produce(pl.make_client(s), s, proj)
    else:
        proj, result = pl.run_all(a.story, a.style, s, Path(a.out), a.scenes)
except Exception as e:
    print(f"Error: {pl.friendly_error(e)}", file=sys.stderr)
    sys.exit(1)

print(f"Project folder: {proj.root}")
if result["failed"]:
    print(f"Unfinished: {', '.join(result['failed'])}. After fixing the cause, run:\n"
          f'  python cli.py --resume "{proj.root}" --resolution {s.resolution}')
    sys.exit(2)
