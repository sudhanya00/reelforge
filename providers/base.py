"""The contract every image/video model implements.

A provider owns everything model-specific: how reference images are declared in the
prompt, the request format, submitting, waiting, downloading, and what a clip costs.
The pipeline only speaks these types, so adding a model never touches it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Ref:
    """A reference image and what it shows."""
    id: str
    kind: str                     # character | prop | environment
    name: str
    path: Path
    note: str = ""                # environments: time and weather


@dataclass
class Shot:
    """Everything needed to shoot one scene, independent of the model."""
    plan: dict
    scene: dict
    refs: list[Ref]
    first_frame: Path | None      # continuous scenes start on the previous take's last frame
    aspect: str                   # "9:16" | "16:9"
    resolution: str               # already mapped to one the provider supports
    duration_s: int               # already clamped to the provider's range


@dataclass
class Submission:
    """A generation accepted by the provider. `ids` go to the log before we wait."""
    ids: dict
    handle: object = None         # whatever the provider needs to collect it


@dataclass
class VideoResult:
    video: bytes
    usage: dict
    cost_usd: float | None        # None: let the pipeline price it from usage
    meta: dict = field(default_factory=dict)   # kept in the take's json (e.g. ids, output url)


@dataclass
class ImageResult:
    png: bytes
    usage: dict
    cost_usd: float | None


@dataclass
class VideoCaps:
    resolutions: tuple[str, ...]  # lowest first
    durations: tuple[int, int]    # min, max seconds per clip
    aspects: tuple[str, ...]
    max_refs: int
    first_frame: bool
    edit: bool
    audio: bool


class ProviderError(Exception):
    """A provider failure with an HTTP-like status, so retries, 'stop the run' and
    friendly messages treat every provider the same way."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class VideoProvider:
    id: str = ""
    label: str = ""
    caps: VideoCaps

    def __init__(self, settings, client=None):
        self.s = settings
        self.client = client      # the SDK/HTTP client, when the provider needs one

    @property
    def model(self) -> str:
        raise NotImplementedError

    def configured(self) -> tuple[bool, str]:
        """(usable, why not)."""
        return True, ""

    def resolution_for(self, requested: str) -> str:
        """The requested resolution, or the nearest one this model supports."""
        order = ["360p", "720p", "1080p", "4k"]
        if requested in self.caps.resolutions:
            return requested
        want = order.index(requested) if requested in order else 1
        return min(self.caps.resolutions, key=lambda r: abs(order.index(r) - want))

    def duration_for(self, seconds: int) -> int:
        lo, hi = self.caps.durations
        return max(lo, min(hi, int(seconds)))

    def price_per_s(self, resolution: str, edit: bool = False) -> float:
        raise NotImplementedError

    def build_prompt(self, shot: Shot) -> str:
        raise NotImplementedError

    def submit(self, shot: Shot, prompt: str) -> Submission:
        raise NotImplementedError

    def submit_edit(self, take_meta: dict, instruction: str) -> Submission:
        raise ProviderError(400, f"{self.label} can't edit a take; shoot a new one instead.")

    def collect(self, sub: Submission) -> VideoResult:
        raise NotImplementedError


class ImageProvider:
    id: str = ""
    label: str = ""

    def __init__(self, settings, client=None):
        self.s = settings
        self.client = client

    @property
    def model(self) -> str:
        raise NotImplementedError

    def generate(self, prompt: str, refs: list[Path], aspect: str, size: str) -> ImageResult:
        raise NotImplementedError
