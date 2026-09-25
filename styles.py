"""Style presets and pacing modes: data the planner, director and prompts all read.

Presets describe what a look *is* (medium, surfaces, motion, camera grammar, how reference
sheets are drawn), never a studio's name: names get imitated inconsistently or refused,
traits get rendered. A preset is a starting point; free-text style refines it, and the
director writes the final profile into plan["style"], where you can edit it.
"""
from __future__ import annotations

STYLE_PRESETS: dict[str, dict] = {
    "live_action": {
        "label": "Live-action drama",
        "medium": "live-action cinematography with real actors in real locations",
        "look": "photorealistic, natural skin texture, practical light sources, subtle film grain",
        "color_grade": "naturalistic with gentle filmic contrast",
        "lens": "35mm and 50mm primes, shallow depth of field for close-ups",
        "motion": "natural human motion with real weight, inertia and balance",
        "camera_grammar": "motivated moves: slow dolly and push-ins, handheld only for tension; eye-level coverage",
        "sheet_look": "photographic character reference, natural skin, real fabric",
        "avoid": "plastic CGI look, over-smoothed skin, oversaturated colour",
        "pacing": "balanced",
    },
    "animated_3d": {
        "label": "3D animated feature",
        "medium": "stylised 3D computer-animated feature film",
        "look": ("appealing rounded shapes, slightly exaggerated proportions, large expressive eyes, "
                 "soft subsurface skin, clean richly textured materials, soft global illumination"),
        "color_grade": "warm, saturated but harmonious palette with soft contrast",
        "lens": "virtual 35mm camera, gentle depth of field",
        "motion": ("expressive animation: anticipation, squash and stretch, follow-through, strong "
                   "readable poses, lively secondary motion in hair and cloth"),
        "camera_grammar": "smooth virtual camera, clean staging and readable silhouettes, gentle arcs and push-ins",
        "sheet_look": "stylised 3D character model turnaround with the same materials and proportions as the film",
        "avoid": "photoreal skin pores, live-action footage, uncanny realistic faces",
        "pacing": "balanced",
    },
    "anime": {
        "label": "Anime",
        "medium": "2D hand-drawn anime",
        "look": ("clean line art, cel shading with two-tone shadows, painted backgrounds with "
                 "atmospheric depth, luminous skies"),
        "color_grade": "vivid but controlled palette, soft bloom on light sources",
        "lens": "flat 2D framing with layered parallax depth",
        "motion": "anime timing: held key poses, snappy transitions, hair and cloth moving in the wind",
        "camera_grammar": "dramatic compositions, slow pans across painted backgrounds, quick push-ins for emphasis, low angles for power",
        "sheet_look": "anime character model sheet, clean line art, flat cel colours",
        "avoid": "3D render look, photoreal textures, western cartoon proportions",
        "pacing": "kinetic",
    },
    "cyberpunk": {
        "label": "Cyberpunk",
        "medium": "live-action science-fiction cinematography",
        "look": ("dense neon-lit megacity, rain-slick streets, glowing holographic signage without "
                 "readable text, atmospheric haze and steam"),
        "color_grade": "magenta and cyan neon against deep teal shadows",
        "lens": "anamorphic-style widescreen framing, reflections in wet surfaces",
        "motion": "natural human motion; vehicles and drones move with visible weight",
        "camera_grammar": "low angles, slow crane and dolly moves through layered depth, framing through reflections",
        "sheet_look": "photographic character reference under neutral light, real fabric and hardware",
        "avoid": "readable signage text, clean daylight, empty streets",
        "pacing": "balanced",
    },
    "noir": {
        "label": "Film noir",
        "medium": "black-and-white live-action cinematography",
        "look": "high-contrast monochrome, hard key light, venetian-blind shadows, cigarette smoke",
        "color_grade": "black and white, deep blacks, bright specular highlights",
        "lens": "40mm, deep focus for interiors",
        "motion": "restrained, deliberate human motion",
        "camera_grammar": "slow push-ins, faces framed by shadow, occasional canted angles",
        "sheet_look": "black-and-white photographic character reference",
        "avoid": "colour, flat lighting, modern objects",
        "pacing": "calm",
    },
}

# How often something visibly changes, how long clips run, how busy the camera is.
PACING: dict[str, dict] = {
    "calm": {
        "label": "Calm",
        "beat_s": (2.5, 4.0), "clip_s": (6, 10),
        "camera": ("slow, deliberate moves or locked-off frames; a held moment is fine when it is "
                   "labelled a hold and carries emotion"),
    },
    "balanced": {
        "label": "Balanced",
        "beat_s": (1.5, 3.0), "clip_s": (5, 8),
        "camera": "motivated moves that follow or reveal the action",
    },
    "kinetic": {
        "label": "Kinetic",
        "beat_s": (0.8, 2.0), "clip_s": (3, 6),
        "camera": "energetic but readable: tracking moves, quick reveals; in-clip cuts for coverage are welcome",
    },
}

DEFAULT_PACING = "balanced"


def preset_brief(preset: str | None) -> str:
    """The preset as planner-readable text."""
    if not preset or preset not in STYLE_PRESETS:
        return ""
    p = STYLE_PRESETS[preset]
    return "\n".join(f"- {k}: {p[k]}" for k in
                     ("medium", "look", "color_grade", "lens", "motion", "camera_grammar", "sheet_look", "avoid"))


def pacing_brief(pacing: str) -> str:
    p = PACING.get(pacing, PACING[DEFAULT_PACING])
    lo, hi = p["beat_s"]
    clo, chi = p["clip_s"]
    return (f"{p['label']}: a visible change every {lo}-{hi} s; clips usually {clo}-{chi} s; "
            f"camera: {p['camera']}.")
