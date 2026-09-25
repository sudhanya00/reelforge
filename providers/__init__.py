"""Model providers. Add a model by writing a VideoProvider/ImageProvider and registering it."""
from __future__ import annotations

from .base import (ImageProvider, ImageResult, ProviderError, Ref, Shot, Submission, VideoCaps,
                   VideoProvider, VideoResult)
from .gemini import GeminiOmniVideo, NanoBananaImage
from .kling import KlingOmniVideo
from .veo import VeoFastVideo, VeoVideo

VIDEO: dict[str, type[VideoProvider]] = {p.id: p for p in (GeminiOmniVideo, VeoFastVideo, VeoVideo, KlingOmniVideo)}
IMAGE: dict[str, type[ImageProvider]] = {p.id: p for p in (NanoBananaImage,)}
DEFAULT_VIDEO = GeminiOmniVideo.id


def video_provider(pid: str | None, settings, google_client=None) -> VideoProvider:
    pid = pid or settings.video_provider
    if pid not in VIDEO:
        raise ProviderError(404, f"Unknown video provider '{pid}'. Known: {', '.join(VIDEO)}")
    return VIDEO[pid](settings, google_client if pid == GeminiOmniVideo.id else None)


def image_provider(pid: str | None, settings, google_client=None) -> ImageProvider:
    pid = pid or settings.image_provider
    if pid not in IMAGE:
        raise ProviderError(404, f"Unknown image provider '{pid}'. Known: {', '.join(IMAGE)}")
    return IMAGE[pid](settings, google_client)


def catalog(settings) -> list[dict]:
    """What the UI shows: every video provider, whether it's usable, and its prices."""
    out = []
    for cls in VIDEO.values():
        p = cls(settings)
        ok, why = p.configured()
        c = p.caps
        out.append({
            "id": p.id, "label": p.label, "model": p.model, "configured": ok, "setup": why,
            "caps": {"resolutions": list(c.resolutions), "durations": list(c.durations),
                     "aspects": list(c.aspects), "max_refs": c.max_refs, "first_frame": c.first_frame,
                     "edit": c.edit, "audio": c.audio, "extend": c.extend},
            "price_per_s": {r: round(p.price_per_s(r), 4) for r in c.resolutions},
            "edit_price_per_s": {r: round(p.price_per_s(r, edit=True), 4) for r in c.resolutions},
        })
    return out


__all__ = ["VIDEO", "IMAGE", "DEFAULT_VIDEO", "video_provider", "image_provider", "catalog",
           "ImageProvider", "ImageResult", "ProviderError", "Ref", "Shot", "Submission", "VideoCaps",
           "VideoProvider", "VideoResult"]
