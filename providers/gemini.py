"""Google: Gemini Omni Flash (video, via client.interactions) and Nano Banana Pro (images).

Omni facts (ai.google.dev/gemini-api/docs/omni): role tags <FIRST_FRAME> / <IMAGE_REF_N>
declared as [# Sources ...] [# References ...]; edits chain on previous_interaction_id;
output is inline base64 (or a Files/GCS uri for large outputs).
"""
from __future__ import annotations

import base64
import io
import re
import time
from pathlib import Path

from google.genai import types

from prompts import scene_lines
from .base import (ImageProvider, ImageResult, ProviderError, Shot, Submission, VideoCaps,
                   VideoProvider, VideoResult)


def usage_from_interaction(interaction) -> dict:
    u = getattr(interaction, "usage", None)
    return {"input": u.total_input_tokens or 0, "output": u.total_output_tokens or 0,
            "thoughts": u.total_thought_tokens or 0} if u else {}


def usage_from_response(resp) -> dict:
    u = getattr(resp, "usage_metadata", None)
    return {"input": u.prompt_token_count or 0, "output": u.candidates_token_count or 0,
            "thoughts": u.thoughts_token_count or 0} if u else {}


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


class GeminiOmniVideo(VideoProvider):
    id = "gemini-omni"
    label = "Gemini Omni Flash"
    caps = VideoCaps(resolutions=("360p", "720p", "1080p", "4k"), durations=(2, 10),
                     aspects=("16:9", "9:16"), max_refs=8, first_frame=True, edit=True, audio=True,
                     extend=True)
    MAX_EXTENDED_S = 40           # extensions add ~10 s per turn, up to 40 s in total

    @property
    def model(self) -> str:
        return self.s.video_model

    def price_per_s(self, resolution: str, edit: bool = False) -> float:
        rate = self.s.PRICES.get(self.model, {}).get("output", 0)
        return self.s.VIDEO_TOKENS_PER_S.get(resolution, 0) * rate / 1e6

    def build_prompt(self, shot: Shot) -> str:
        header, bind = [], []
        n = 1
        if shot.first_frame:
            header.append("[# Sources <FIRST_FRAME>@Image1]")
            n = 2
        decl = []
        for i, r in enumerate(shot.refs):
            decl.append(f"<IMAGE_REF_{i}>@Image{n + i}")
            if r.kind == "character":
                bind.append(f"{r.name} is the person shown in <IMAGE_REF_{i}> (match face, hair and costume exactly).")
            elif r.kind == "prop":
                bind.append(f"The {r.name} is the object in <IMAGE_REF_{i}>.")
            else:
                bind.append(f"The setting is the location in <IMAGE_REF_{i}> ({r.note}).")
        if decl:
            header.append("[# References " + " ".join(decl) + "]")
        tail = []
        if shot.first_frame:
            tail.append("Use Image1 as the starting frame.")
        if decl:
            tail.append("Use the reference images for identity and setting only; "
                        "they must not appear as literal frames.")
        lines = [" ".join(header), " ".join(bind)] + scene_lines(shot.plan, shot.scene, shot.duration_s) + tail
        return "\n".join(l for l in lines if l)

    def _format(self, aspect: str, resolution: str) -> dict:
        fmt = {"type": "video", "aspect_ratio": aspect, "resolution": resolution}
        if resolution in ("1080p", "4k"):
            if self.s.backend == "vertex":        # fail before paying, not after
                raise NotImplementedError("1080p/4k on Vertex is delivered to Cloud Storage, "
                                          "which isn't wired up yet. Use 720p or lower.")
            fmt["delivery"] = "uri"
        return fmt

    def submit(self, shot: Shot, prompt: str) -> Submission:
        fmt = self._format(shot.aspect, shot.resolution)
        parts = []
        if shot.first_frame:
            parts.append({"type": "image", "data": _b64(shot.first_frame), "mime_type": "image/png"})
        for r in shot.refs:
            parts.append({"type": "image", "data": _b64(r.path), "mime_type": "image/png"})
        parts.append({"type": "text", "text": prompt})
        interaction = self.client.interactions.create(
            model=self.model, input=parts, response_format=fmt, timeout=self.s.video_timeout_s)
        return Submission(ids={"interaction_id": interaction.id, "status": interaction.status},
                          handle={"interaction": interaction, "format": fmt})

    def submit_edit(self, take_meta: dict, instruction: str) -> Submission:
        if "interaction_id" not in take_meta:
            raise ProviderError(400, "This take wasn't made by Gemini Omni, so Omni can't edit it.")
        fmt = take_meta["format"]          # same res/aspect as the source take
        interaction = self.client.interactions.create(
            model=self.model, previous_interaction_id=take_meta["interaction_id"],
            input=instruction, response_format=fmt, timeout=self.s.video_timeout_s)
        return Submission(ids={"interaction_id": interaction.id, "status": interaction.status},
                          handle={"interaction": interaction, "format": fmt})

    def submit_extend(self, take_meta: dict, prompt: str) -> Submission:
        """Continue the same take (same person, voice, room, camera) for about 10 more seconds."""
        if "interaction_id" not in take_meta:
            raise ProviderError(400, "Only a Gemini Omni take can be extended by Omni.")
        fmt = take_meta["format"]
        interaction = self.client.interactions.create(
            model=self.model, previous_interaction_id=take_meta["interaction_id"],
            input=prompt, response_format=fmt, timeout=self.s.video_timeout_s)
        return Submission(ids={"interaction_id": interaction.id, "status": interaction.status},
                          handle={"interaction": interaction, "format": fmt})

    def collect(self, sub: Submission) -> VideoResult:
        interaction = sub.handle["interaction"]
        deadline = time.time() + self.s.video_timeout_s
        # create() normally returns a finished interaction, but may hand back a queued one
        while interaction.status in ("queued", "in_progress"):
            if time.time() > deadline:
                raise TimeoutError(f"Interaction {interaction.id} still {interaction.status} "
                                   f"after {self.s.video_timeout_s}s; fetch it later with interactions.get")
            time.sleep(5)
            interaction = self.client.interactions.get(interaction.id)
        usage = usage_from_interaction(interaction)
        meta = {"interaction_id": interaction.id, "format": sub.handle["format"]}
        try:
            video = self._download(interaction)
        except Exception as e:
            e.usage = usage                        # so the pipeline can still log what it cost
            e.meta = meta
            raise
        return VideoResult(video=video, usage=usage, cost_usd=None, meta=meta)

    def _download(self, interaction) -> bytes:
        vid = interaction.output_video
        if vid is None:
            raise RuntimeError(f"No video in response (status={interaction.status}, "
                               f"errors={getattr(interaction, 'errors', None)})")
        if getattr(vid, "data", None):
            return base64.b64decode(vid.data)
        if (vid.uri or "").startswith("gs://"):
            raise NotImplementedError(f"Video was delivered to Cloud Storage ({vid.uri}); "
                                      "GCS download isn't implemented yet. Use 360p/720p on Vertex.")
        m = re.search(r"files/([A-Za-z0-9_-]+)", vid.uri or "")
        if not m:
            raise RuntimeError("Video returned without data or a usable uri")
        name = f"files/{m.group(1)}"
        while True:
            state = self.client.files.get(name=name).state.name
            if state == "ACTIVE":
                break
            if state == "FAILED":
                raise RuntimeError("Video processing failed on the server")
            time.sleep(5)
        return self.client.files.download(file=vid.uri)


class NanoBananaImage(ImageProvider):
    id = "nano-banana"
    label = "Nano Banana Pro"

    @property
    def model(self) -> str:
        return self.s.image_model

    def generate(self, prompt: str, refs: list[Path], aspect: str, size: str) -> ImageResult:
        contents = [types.Part.from_bytes(data=p.read_bytes(), mime_type="image/png") for p in refs] + [prompt]
        resp = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio=aspect, image_size=size),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        for part in (resp.candidates[0].content.parts if resp.candidates and resp.candidates[0].content else []):
            if part.inline_data and part.inline_data.data:
                data = part.inline_data.data
                if part.inline_data.mime_type != "image/png":     # assets are .png everywhere
                    from PIL import Image
                    buf = io.BytesIO()
                    Image.open(io.BytesIO(data)).save(buf, format="PNG")
                    data = buf.getvalue()
                return ImageResult(png=data, usage=usage_from_response(resp), cost_usd=None)
        reason = resp.candidates[0].finish_reason if resp.candidates else getattr(resp, "prompt_feedback", None)
        if any(k in str(reason) for k in ("SAFETY", "PROHIBITED", "BLOCKLIST", "SPII")):
            raise RuntimeError(f"Image blocked by the safety filter ({reason}).")
        raise RuntimeError(f"No image returned (reason: {reason}).")
