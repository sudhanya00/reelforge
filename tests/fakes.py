"""Fake Gemini client and a small test plan, shared by the offline tests."""
import base64
import hashlib
import io
import json
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace as NS

from PIL import Image

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

PLAN = {
    "title": "Test Film", "logline": "A test.",
    "style": {"look": "Photoreal.", "color_grade": "cool", "lens": "35mm", "avoid": "CGI"},
    "characters": [{"id": "char_a", "name": "Asha", "appearance": "30s woman", "costume": "red coat",
                    "voice": "low, calm"}],
    "props": [{"id": "prop_cup", "name": "cup", "description": "steel cup"}],
    "environments": [
        {"id": "env_night", "name": "pass", "description": "road", "time_and_weather": "night snow",
         "lighting": "blue", "based_on": ""},
        {"id": "env_day", "name": "pass", "description": "road", "time_and_weather": "clear morning",
         "lighting": "sun", "based_on": "env_night"},
    ],
    "scenes": [
        {"id": "s01", "duration_s": 6, "refs": ["char_a", "env_night"], "shot": "wide.",
         "action": "Asha walks.", "camera": "static", "lighting": "blue", "audio": "wind",
         "continuity": "cut"},
        {"id": "s02", "duration_s": 5, "refs": ["char_a", "prop_cup", "env_night"], "shot": "close",
         "action": "Asha holds the cup", "camera": "push-in", "lighting": "amber", "audio": "fire",
         "continuity": "continuous", "dialogue": [{"speaker": "Asha", "line": "Cold night."}]},
        {"id": "s03", "duration_s": 4, "refs": ["env_day"], "shot": "wide", "action": "Empty road",
         "camera": "static", "lighting": "sun", "audio": "birds", "continuity": "cut"},
    ],
}


def _png(fmt="PNG", aspect="16:9", seed="") -> bytes:
    """A flat placeholder in the requested aspect, coloured by `seed` so cards differ."""
    w, h = (64, 36) if aspect == "16:9" else (36, 64)
    rgb = tuple(40 + b % 150 for b in hashlib.md5(seed.encode()).digest()[:3]) if seed else (40, 60, 90)
    buf = io.BytesIO()
    Image.new("RGB", (w * 10, h * 10), rgb).save(buf, format=fmt)
    return buf.getvalue()


def demo_clip(path: Path) -> dict[str, bytes]:
    """Short test clips in both orientations for demo mode (cached next to `path`)."""
    out = {}
    for aspect, size in (("16:9", "640x360"), ("9:16", "360x640")):
        p = Path(path).with_name(f"{Path(path).stem}_{aspect.replace(':', 'x')}.mp4")
        if not p.exists() and HAS_FFMPEG:
            p.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=d=4:s={size}:r=24",
                            "-f", "lavfi", "-i", "sine=d=4:f=220", "-shortest", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", str(p)], check=True)
        out[aspect] = p.read_bytes() if p.exists() else b"not-a-real-mp4"
    return out


class FakeClient:
    """Records every call; returns canned plan / image / video responses."""

    def __init__(self, mp4: bytes | dict[str, bytes], image_mime="image/png", delay=False):
        self.calls, self.mp4, self.image_mime = [], mp4, image_mime
        self.delay = delay        # demo mode: take a few seconds like the real thing
        self.fail_save = False
        # exceptions to raise on the next calls of each kind, in order
        self.errors = {"plan": [], "image": [], "video": []}
        self.models = NS(generate_content=self._generate_content)
        self.interactions = NS(create=self._create, get=self._get)
        self._n = 0

    def _maybe_fail(self, kind):
        if self.errors[kind]:
            raise self.errors[kind].pop(0)

    def _generate_content(self, model, contents, config):
        self.calls.append(("generate_content", model, contents, config))
        is_image = config.response_modalities == ["IMAGE"]
        self._maybe_fail("image" if is_image else "plan")
        if self.delay:
            time.sleep(3 if is_image else 4)
        usage = NS(prompt_token_count=1000, candidates_token_count=2000, thoughts_token_count=500)
        if is_image:
            data = _png("JPEG" if self.image_mime == "image/jpeg" else "PNG",
                        config.image_config.aspect_ratio, str(contents[-1]))
            part = NS(inline_data=NS(data=data, mime_type=self.image_mime))
            return NS(candidates=[NS(content=NS(parts=[part]), finish_reason="STOP")],
                      usage_metadata=usage, text=None)
        return NS(text=json.dumps(PLAN), usage_metadata=usage)

    def _create(self, **kw):
        self.calls.append(("interactions.create", kw))
        self._maybe_fail("video")
        if self.delay:
            time.sleep(8)
        self._n += 1
        aspect = kw.get("response_format", {}).get("aspect_ratio", "16:9")
        clip = self.mp4 if isinstance(self.mp4, bytes) else self.mp4[aspect]
        video = None if self.fail_save else NS(data=base64.b64encode(clip).decode(), uri=None)
        return NS(id=f"ix{self._n}", status="completed", output_video=video, errors=None,
                  usage=NS(total_input_tokens=3610, total_output_tokens=11586, total_thought_tokens=772))

    def _get(self, id):
        raise AssertionError("get() should not be needed for completed interactions")

def log_entries(proj):
    return [json.loads(l) for l in (proj.root / "log.jsonl").read_text(encoding="utf-8").splitlines()]


def api_error(code: int, message: str = "boom"):
    """What client.models.* raises."""
    from google.genai import errors
    cls = errors.ClientError if code < 500 else errors.ServerError
    return cls(code, {"error": {"code": code, "message": message, "status": "X"}})


def interactions_error(code: int, message: str = "boom"):
    """What client.interactions.* raises."""
    import httpx
    from google.genai._gaos.errors import GenAiError
    return GenAiError(message, httpx.Response(code, request=httpx.Request("POST", "https://x")))


class FakeKling:
    """A stand-in for Kling's HTTP API (httpx.MockTransport): tasks, polling, download, billing."""

    def __init__(self, mp4: bytes | dict[str, bytes], polls_before_done=1, delay=False):
        import httpx
        self.mp4, self.polls_before_done, self.delay = mp4, polls_before_done, delay
        self.requests: list[tuple[str, str, dict | None]] = []
        self.errors: list[tuple[int, int, str]] = []      # (http status, kling code, message) for next POSTs
        self.fail_task: str | None = None                 # task ends 'failed' with this message
        self.tasks: dict[str, dict] = {}
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request):
        import httpx
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body))
        if request.method == "POST" and request.url.path.startswith("/omni-video/"):
            if self.errors:
                status, code, msg = self.errors.pop(0)
                return httpx.Response(status, json={"code": code, "message": msg})
            tid = f"k{len(self.tasks) + 1}"
            aspect = body["settings"].get("aspect_ratio", "16:9")
            self.tasks[tid] = {"polls": 0, "aspect": aspect, "seconds": body["settings"]["duration"]}
            return httpx.Response(200, json={"code": 0, "data": {"id": tid, "status": "submitted"}})
        if request.method == "GET" and request.url.path == "/tasks":
            tid = request.url.params["task_ids"]
            t = self.tasks[tid]
            t["polls"] += 1
            if self.delay:
                time.sleep(2)
            if self.fail_task:
                task = {"id": tid, "status": "failed", "message": self.fail_task}
            elif t["polls"] <= self.polls_before_done:
                task = {"id": tid, "status": "processing"}
            else:
                task = {"id": tid, "status": "succeeded",
                        "outputs": [{"type": "video", "url": f"https://cdn.fake-kling/{tid}.mp4",
                                     "duration": str(t["seconds"])}],
                        "billing": [{"charge_type": "unit", "amount": str(0.8 * t["seconds"]),
                                     "package_type": "video"}]}
            return httpx.Response(200, json={"code": 0, "data": [task]})
        if request.url.host == "cdn.fake-kling":
            tid = request.url.path.strip("/").removesuffix(".mp4")
            clip = self.mp4 if isinstance(self.mp4, bytes) else self.mp4[self.tasks[tid]["aspect"]]
            return httpx.Response(200, content=clip)
        return httpx.Response(404, json={"code": 1202, "message": "no such method"})
