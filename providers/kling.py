"""Kling 3.0 Omni (video), via Kling's own API.

Docs: kling.ai/document-api (read 2026-09-25)
  POST {base}/omni-video/{model}   contents: prompt | first_frame | refer_image | base_video
  GET  {base}/tasks?task_ids=ID    status: submitted | processing | succeeded | failed
  Auth: "Authorization: Bearer <API key>". Images as URL or base64. Up to 7 reference
  images, referred to in the prompt as @<id>. 3-15 s clips, 720p/1080p/4k, optional native
  audio. Editing takes a base_video URL, so only Kling's own recent outputs (their result
  URLs last 30 days) can be edited. Each finished task reports what it was billed.
"""
from __future__ import annotations

import base64
import os
import time
import uuid

import httpx

from prompts import dialogue_line, dot, scene_lines, shots_of, style_line
from .base import ProviderError, Shot, Submission, VideoCaps, VideoProvider, VideoResult

BASE_URL = os.environ.get("KLING_BASE_URL", "https://api-singapore.klingai.com")
TRANSPORT: httpx.BaseTransport | None = None      # tests and demo mode swap in a fake API

# Kling service code -> HTTP-like status (their HTTP status is 429 even for "out of credits",
# which must stop a run rather than be retried)
_STATUS = {1000: 401, 1001: 401, 1002: 401, 1003: 401, 1004: 401,
           1100: 402, 1101: 402, 1102: 402, 1103: 403, 1304: 403,
           1200: 400, 1201: 400, 1202: 404, 1203: 404, 1300: 400, 1301: 400,
           1302: 429, 1303: 429, 5000: 500, 5001: 503, 5002: 504}


def kling_error(http_status: int, body: dict) -> ProviderError:
    code, msg = body.get("code"), body.get("message") or "unknown error"
    if code in (1300, 1301):
        return ProviderError(400, f"Kling content policy ({code}): {msg}")
    return ProviderError(_STATUS.get(code, http_status), f"Kling {code}: {msg}")


class KlingOmniVideo(VideoProvider):
    id = "kling"
    label = "Kling 3.0 Omni"
    caps = VideoCaps(resolutions=("720p", "1080p", "4k"), durations=(3, 15),
                     aspects=("16:9", "9:16", "1:1"), max_refs=7, first_frame=True, edit=True, audio=True)

    @property
    def model(self) -> str:
        return self.s.kling_model

    def configured(self) -> tuple[bool, str]:
        if os.environ.get("KLING_API_KEY"):
            return True, ""
        return False, "Add KLING_API_KEY to the .env file (Kling console → API Keys)."

    def price_per_s(self, resolution: str, edit: bool = False) -> float:
        p = self.s.PRICES.get(self.model, {})
        table = p.get("per_s_edit") if edit else (p.get("per_s_audio") if self.s.kling_audio else p.get("per_s"))
        return (table or {}).get(resolution, 0)

    # ---------------------------------------------------------------- prompt

    def build_prompt(self, shot: Shot) -> str:
        bind = []
        for i, r in enumerate(shot.refs, start=1):
            tag = f"@image_{i}"
            if r.kind == "character":
                bind.append(f"{r.name} is the person in {tag} (match face, hair and costume exactly).")
            elif r.kind == "prop":
                bind.append(f"The {r.name} is the object in {tag}.")
            else:
                bind.append(f"The setting is the location in {tag} ({r.note}).")
        head = ["The shot starts exactly on the provided first frame."] if shot.first_frame else []
        tail = ["Use the reference images for identity and setting only; they must not appear as literal frames."] \
            if shot.refs else []
        shots = shots_of(shot.scene)
        body = self._multi_shot_lines(shot, shots) if len(shots) > 1 else \
            scene_lines(shot.plan, shot.scene, shot.duration_s)
        return "\n".join(head + ([" ".join(bind)] if bind else []) + body + tail)

    @staticmethod
    def _multi_shot_lines(shot: Shot, shots: list[list[dict]]) -> list[str]:
        """Kling's in-clip cut syntax: "shot n, seconds, words; ..." with whole-second shots
        that add up to the clip's duration."""
        lengths = [max(1, round(sh[-1]["t_end"] - sh[0]["t_start"])) for sh in shots]
        lengths[-1] = max(1, shot.duration_s - sum(lengths[:-1]))
        segs = [f"shot {i}, {n}, " + " ".join(f"{dot(b['action'])} {dot(b['camera'])}" for b in sh)
                for i, (sh, n) in enumerate(zip(shots, lengths), start=1)]
        plan, scene = shot.plan, shot.scene
        lines = ["; ".join(segs) + ";", f"Lighting: {dot(scene['lighting'])}", dialogue_line(plan, scene),
                 f"Sound design: {dot(scene['audio'])} No background music unless described.", style_line(plan)]
        if plan["style"].get("motion"):
            lines.append(f"Motion: {dot(plan['style']['motion'])}")
        return lines

    # ---------------------------------------------------------------- API

    def _http(self) -> httpx.Client:
        key = os.environ.get("KLING_API_KEY")
        if not key:
            raise ProviderError(401, "Kling isn't set up: add KLING_API_KEY to the .env file.")
        return httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {key}"},
                            timeout=httpx.Timeout(60, connect=15), transport=TRANSPORT)

    @staticmethod
    def _json(resp: httpx.Response) -> dict:
        try:
            body = resp.json()
        except ValueError:
            raise ProviderError(resp.status_code, f"Kling returned HTTP {resp.status_code}: {resp.text[:200]}")
        if resp.status_code >= 400 or body.get("code", 0) != 0:
            raise kling_error(resp.status_code, body)
        return body

    def _create(self, contents: list[dict], settings: dict) -> Submission:
        with self._http() as http:
            body = self._json(http.post(f"/omni-video/{self.model}", json={
                "contents": contents,
                "settings": settings,
                "options": {"external_task_id": f"rf-{uuid.uuid4().hex[:16]}",
                            "watermark_info": {"enabled": False}},
            }))
        task = body["data"]
        return Submission(ids={"task_id": task["id"], "status": task.get("status")},
                          handle={"task_id": task["id"], "settings": settings})

    def submit(self, shot: Shot, prompt: str) -> Submission:
        contents: list[dict] = [{"type": "prompt", "text": prompt}]
        if shot.first_frame:
            contents.append({"type": "first_frame", "url": _b64(shot.first_frame), "id": "first_frame"})
        for i, r in enumerate(shot.refs[: self.caps.max_refs], start=1):
            contents.append({"type": "refer_image", "url": _b64(r.path), "id": f"image_{i}"})
        return self._create(contents, {
            "resolution": shot.resolution, "duration": shot.duration_s, "aspect_ratio": shot.aspect,
            "audio": "native" if self.s.kling_audio else "off",
            "multi_shot": len(shots_of(shot.scene)) > 1,
        })

    def submit_edit(self, take_meta: dict, instruction: str) -> Submission:
        src = take_meta.get("output_url")
        if take_meta.get("provider") != self.id or not src:
            raise ProviderError(400, "Kling can only edit takes it made itself.")
        if time.time() - take_meta.get("created", 0) > 29 * 86400:
            raise ProviderError(400, "Kling keeps its clips for 30 days; this take is too old to edit there.")
        fmt = take_meta.get("format", {})
        return self._create(
            [{"type": "prompt", "text": instruction}, {"type": "base_video", "url": src, "id": "video_1"}],
            # an edited base video can't have native audio generated; keep the original sound
            {"resolution": fmt.get("resolution", "720p"), "duration": int(round(take_meta.get("duration_s") or 5)),
             "audio": "original", "multi_shot": False},
        )

    def collect(self, sub: Submission) -> VideoResult:
        task_id = sub.handle["task_id"]
        deadline = time.time() + self.s.video_timeout_s
        with self._http() as http:
            while True:
                try:
                    body = self._json(http.get("/tasks", params={"task_ids": task_id}))
                    task = body["data"][0]
                except ProviderError as e:
                    if e.status_code not in (429, 500, 503, 504):
                        raise
                    task = {"status": "processing"}  # transient; keep polling
                if task["status"] == "succeeded":
                    break
                if task["status"] == "failed":
                    msg = task.get("message") or "the task failed"
                    raise ProviderError(400, f"Kling: {msg}")
                if time.time() > deadline:
                    raise TimeoutError(f"Kling task {task_id} still {task['status']} after "
                                       f"{self.s.video_timeout_s}s; it may still finish in the Kling console.")
                time.sleep(5)
            video = next((o for o in task.get("outputs", []) if o.get("type") == "video"), None)
            if not video or not video.get("url"):
                raise ProviderError(502, "Kling finished but returned no video")
            usage = {"seconds": float(video.get("duration") or 0)}
            cost = self._billed_usd(task.get("billing") or [])
            meta = {"task_id": task_id, "output_url": video["url"]}
            try:
                dl = http.get(video["url"], follow_redirects=True, timeout=300)
                dl.raise_for_status()
            except Exception as e:
                e.usage, e.meta, e.cost_usd = usage, meta, cost
                raise
        return VideoResult(video=dl.content, usage=usage, cost_usd=cost, meta=meta)

    def _billed_usd(self, billing: list[dict]) -> float | None:
        """What the task actually cost, from Kling's own billing record."""
        usd_per_unit = self.s.PRICES.get(self.model, {}).get("usd_per_unit", 0.14)
        total, known = 0.0, False
        for b in billing:
            try:
                amount = float(b.get("amount") or 0)
            except ValueError:
                continue
            if b.get("charge_type") == "unit":
                total, known = total + amount * usd_per_unit, True
            elif b.get("charge_type") == "cash" and b.get("currency") == "USD":
                total, known = total + amount, True
        return round(total, 4) if known else None


def _b64(path) -> str:
    return base64.b64encode(path.read_bytes()).decode()
