"""Veo 3.1 and Veo 3.1 Fast (video), via client.models.generate_videos.

Facts (SDK GenerateVideosConfig + ai.google.dev pricing, 2026-09-26):
  - on Vertex the models live in regional endpoints (us-central1), not "global"
  - 720p / 1080p; 4, 6 or 8 s; 16:9 or 9:16; audio on by default
  - up to 3 reference images ("asset"), a first frame (image), optional last frame
  - a real negative_prompt; no conversational edit (re-shoot or extend instead)
  - long-running operation; the clip comes back as bytes (or a Files uri on the Gemini API)
Prices per second incl. audio: Veo 3.1 $0.40 (720p/1080p); Fast $0.10 (720p) / $0.12 (1080p).
"""
from __future__ import annotations

import os
import time

import google.auth
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from prompts import scene_lines
from .base import ProviderError, Shot, Submission, VideoCaps, VideoProvider, VideoResult

CLIENT_FACTORY = None           # tests and demo mode swap in a fake client

# What we've measured going wrong (docs/RND.md), phrased as things not to show.
NEGATIVE = ("morphing objects, warped or melting hands, extra fingers, garbled text, "
            "cross-dissolve transitions, film strip borders, gliding vehicles with still wheels")


def _client(s):
    if CLIENT_FACTORY:
        return CLIENT_FACTORY(s)
    if s.backend == "vertex":
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"],
                                       quota_project_id=s.gcp_project)
        return genai.Client(vertexai=True, project=s.gcp_project, location=s.veo_location, credentials=creds)
    return genai.Client(vertexai=False, api_key=os.environ.get("GEMINI_API_KEY"))


def _image(path) -> types.Image:
    return types.Image(image_bytes=path.read_bytes(), mime_type="image/png")


class VeoVideo(VideoProvider):
    id = "veo"
    label = "Veo 3.1"
    model_field = "veo_model"
    caps = VideoCaps(resolutions=("720p", "1080p"), durations=(4, 8), aspects=("16:9", "9:16"),
                     max_refs=3, first_frame=True, edit=False, audio=True)
    # three references at most: who is in the shot matters more than the plate
    ref_priority = ("character", "environment", "prop")
    DURATIONS = (4, 6, 8)

    @property
    def model(self) -> str:
        return getattr(self.s, self.model_field)

    def duration_for(self, seconds: int) -> int:
        """Veo only does 4, 6 or 8 s: the shortest that fits the beats (8 at most)."""
        return next((d for d in self.DURATIONS if d >= seconds), self.DURATIONS[-1])

    def price_per_s(self, resolution: str, edit: bool = False) -> float:
        return self.s.PRICES.get(self.model, {}).get("per_s", {}).get(resolution, 0)

    def build_prompt(self, shot: Shot) -> str:
        who = []
        for r in shot.refs:
            if r.kind == "character":
                who.append(f"{r.name} looks exactly like the person in the reference image (face, hair and costume).")
            elif r.kind == "prop":
                who.append(f"The {r.name} looks exactly like the object in the reference image.")
            else:
                who.append(f"The setting matches the location reference image ({r.note}).")
        head = ["The video starts exactly on the given first frame."] if shot.first_frame else []
        return "\n".join(head + ([" ".join(who)] if who else []) + scene_lines(shot.plan, shot.scene, shot.duration_s))

    def _config(self, shot: Shot, with_refs: bool) -> types.GenerateVideosConfig:
        avoid = shot.plan.get("style", {}).get("avoid", "")
        kw = dict(aspect_ratio=shot.aspect, resolution=shot.resolution, duration_seconds=shot.duration_s,
                  number_of_videos=1, generate_audio=True,
                  negative_prompt=", ".join(x for x in (avoid.strip().rstrip("."), NEGATIVE) if x))
        if with_refs and shot.refs:
            kw["reference_images"] = [types.VideoGenerationReferenceImage(image=_image(r.path), reference_type=types.VideoGenerationReferenceType.ASSET)
                                      for r in shot.refs[: self.caps.max_refs]]
        return types.GenerateVideosConfig(**kw)

    def submit(self, shot: Shot, prompt: str) -> Submission:
        client = self.client or _client(self.s)
        source = types.GenerateVideosSource(prompt=prompt, image=_image(shot.first_frame) if shot.first_frame else None)
        dropped = None
        try:
            op = client.models.generate_videos(model=self.model, source=source, config=self._config(shot, True))
        except genai_errors.APIError as e:
            # rejected requests aren't billed; if Veo won't take references with this setup
            # (e.g. together with a first frame), shoot without them and say so on the take
            if e.code != 400 or not shot.refs or "reference" not in str(e).lower():
                raise
            dropped = str(e)[:300]
            op = client.models.generate_videos(model=self.model, source=source, config=self._config(shot, False))
        return Submission(ids={"operation": op.name},
                          handle={"op": op, "client": client, "seconds": shot.duration_s,
                                  "resolution": shot.resolution, "refs_dropped": dropped})

    def collect(self, sub: Submission) -> VideoResult:
        op, client = sub.handle["op"], sub.handle["client"]
        deadline = time.time() + self.s.video_timeout_s
        while not op.done:
            if time.time() > deadline:
                raise TimeoutError(f"Veo operation {op.name} still running after {self.s.video_timeout_s}s")
            time.sleep(5)
            op = client.operations.get(op)
        seconds = sub.handle["seconds"]
        usage = {"seconds": seconds}
        meta = {"operation": op.name}
        if sub.handle["refs_dropped"]:
            meta["refs_dropped"] = sub.handle["refs_dropped"]
        if op.error:
            raise ProviderError(int(op.error.get("code", 500)) if str(op.error.get("code", "")).isdigit() else 500,
                                f"Veo: {op.error.get('message', op.error)}")
        res = op.response or op.result
        if res and getattr(res, "rai_media_filtered_count", 0):
            reasons = "; ".join(res.rai_media_filtered_reasons or []) or "no reason given"
            raise ProviderError(400, f"Veo safety filter blocked the video: {reasons}")
        videos = (res.generated_videos if res else None) or []
        if not videos or not videos[0].video:
            raise ProviderError(502, "Veo finished but returned no video")
        video = videos[0].video
        data = video.video_bytes
        if not data:
            data = client.files.download(file=video)
        cost = round(self.price_per_s(sub.handle["resolution"]) * seconds, 4)
        return VideoResult(video=data, usage=usage, cost_usd=cost, meta=meta)


class VeoFastVideo(VeoVideo):
    id = "veo-fast"
    label = "Veo 3.1 Fast"
    model_field = "veo_fast_model"
