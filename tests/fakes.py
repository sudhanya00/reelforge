"""Fake Gemini client and a small test plan, shared by the offline tests."""
import base64
import io
import json
import shutil
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


def _png(fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 36), (40, 60, 90)).save(buf, format=fmt)
    return buf.getvalue()


class FakeClient:
    """Records every call; returns canned plan / image / video responses."""

    def __init__(self, mp4: bytes, image_mime="image/png"):
        self.calls, self.mp4, self.image_mime = [], mp4, image_mime
        self.fail_save = False
        self.models = NS(generate_content=self._generate_content)
        self.interactions = NS(create=self._create, get=self._get)
        self._n = 0

    def _generate_content(self, model, contents, config):
        self.calls.append(("generate_content", model, contents, config))
        usage = NS(prompt_token_count=1000, candidates_token_count=2000, thoughts_token_count=500)
        if config.response_modalities == ["IMAGE"]:
            data = _png("JPEG" if self.image_mime == "image/jpeg" else "PNG")
            part = NS(inline_data=NS(data=data, mime_type=self.image_mime))
            return NS(candidates=[NS(content=NS(parts=[part]), finish_reason="STOP")],
                      usage_metadata=usage, text=None)
        return NS(text=json.dumps(PLAN), usage_metadata=usage)

    def _create(self, **kw):
        self.calls.append(("interactions.create", kw))
        self._n += 1
        video = None if self.fail_save else NS(data=base64.b64encode(self.mp4).decode(), uri=None)
        return NS(id=f"ix{self._n}", status="completed", output_video=video, errors=None,
                  usage=NS(total_input_tokens=3610, total_output_tokens=11586, total_thought_tokens=772))

    def _get(self, id):
        raise AssertionError("get() should not be needed for completed interactions")

def log_entries(proj):
    return [json.loads(l) for l in (proj.root / "log.jsonl").read_text(encoding="utf-8").splitlines()]
