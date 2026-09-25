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


def _v2(plan):
    """PLAN with what planner v2 adds: pacing, a full style profile, timed beats."""
    import copy
    p = copy.deepcopy(plan)
    p["pacing"] = "balanced"
    p["style"].update({"medium": "live-action film", "motion": "natural weight",
                       "camera_grammar": "motivated moves", "sheet_look": "photographic reference"})
    for sc in p["scenes"]:
        d = sc["duration_s"]
        sc["multi_shot"] = False
        sc["beats"] = [{"t_start": 0, "t_end": d / 2, "action": f"{sc['action']} begins", "camera": "holds"},
                       {"t_start": d / 2, "t_end": d, "action": f"{sc['action']} completes", "camera": "pushes in"}]
    p["scenes"][1]["risks"] = [{"what": "hands on a cup", "handling": "cup already in hand"}]
    return p


PLAN_V2 = _v2(PLAN)
DIRECTOR_NOTES = [{"scene": "s01", "change": "Asha is already walking at 0 s", "reason": "no idle lead-in"}]

FAKE_PROFILE = {
    "name": "Mira Sol", "handle": "mirasol", "gender": "woman", "age": "27", "ethnicity": "Filipino",
    "skin": "warm tan, light freckles", "hair": "shoulder-length black, wavy", "body": "petite",
    "features": "small mole above the lip", "style": "thrifted casual", "outfit": "oversized olive cardigan",
    "niche": "budget cooking", "persona": "warm, a little chaotic", "speech": "fast, says 'okay so'",
    "voice": "bright alto", "setting": "a small studio-apartment kitchen with a green kettle",
}
FAKE_REEL = {
    "title": "Three-ingredient pancakes", "hook": "Okay so you only need three things.",
    "caption": "Broke-week breakfast #budget",
    "setup": {"location": "a bright corner shop aisle", "outfit": "grey hoodie and jeans",
              "position": "walking down the aisle", "light": "fluorescent shop light"},
    "segments": [
        {"id": "a", "seconds": 12, "lines": ["Okay so you only need three things."], "delivery": "excited",
         "action": "holds up an egg"},
        {"id": "b", "seconds": 10, "lines": ["Banana, egg, oats. That's it."], "delivery": "matter-of-fact",
         "action": "leans in"},
    ],
}

FAKE_REVIEW = {
    "summary": "A usable shot with a slow start.",
    "beats_observed": [{"t_start": 0, "t_end": 2, "what": "Asha walks in"}],
    "scores": {c: {"score": 4, "note": "ok"} for c in ("identity", "costume", "environment", "action", "camera",
                                                       "pacing", "physics", "artifacts", "style", "continuity")},
    "issues": [{"t_start": 0, "t_end": 1.5, "category": "pacing", "severity": "minor",
                "description": "Nothing happens for the first 1.5 seconds."}],
    "dead_time_s": 1.5, "verdict": "fix", "fix_instruction": "Start the walk immediately.",
    "prompt_advice": "Say the action is already underway in the first frame.",
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
        system = config.system_instruction or ""
        if "fictional social-media creators" in system:          # influencer designer
            return NS(text=json.dumps(FAKE_PROFILE), usage_metadata=usage)
        if "short-form video scripts" in system:                 # influencer script
            return NS(text=json.dumps(FAKE_REEL), usage_metadata=usage)
        if "film editor" in system:                              # the take reviewer
            return NS(text=json.dumps(FAKE_REVIEW), usage_metadata=usage)
        if "reviewing a production plan" in system:              # the director pass
            return NS(text=json.dumps({"plan": PLAN_V2, "notes": DIRECTOR_NOTES}), usage_metadata=usage)
        if "timed BEATS" in system:                              # planner v2
            return NS(text=json.dumps(PLAN_V2), usage_metadata=usage)
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


class FakeVeo:
    """A stand-in for client.models.generate_videos + client.operations.get."""

    def __init__(self, mp4: bytes | dict[str, bytes]):
        self.mp4, self.calls = mp4, []
        self.reject_refs = False          # first call with references fails with a 400
        self.rai = None                   # list of reasons: the video is filtered
        self.models = NS(generate_videos=self._generate)
        self.operations = NS(get=self._get)
        self._n = 0

    def _generate(self, model, source, config):
        self.calls.append({"model": model, "source": source, "config": config})
        if self.reject_refs and config.reference_images:
            self.reject_refs = False
            from google.genai import errors
            raise errors.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                                     "message": "reference images are not supported with image input"}})
        self._n += 1
        return NS(name=f"operations/veo{self._n}", done=False, config=config)

    def _get(self, op):
        clip = self.mp4 if isinstance(self.mp4, bytes) else self.mp4[op.config.aspect_ratio]
        resp = NS(generated_videos=[NS(video=NS(video_bytes=clip, uri=None))],
                  rai_media_filtered_count=len(self.rai or []), rai_media_filtered_reasons=self.rai)
        return NS(name=op.name, done=True, error=None, response=resp, result=None)
