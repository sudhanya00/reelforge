# R&D log: planning, directing, pacing

Goal: better films per dollar. Every change is measured with the instruments below on a
fixed story set at 360p before it becomes the default.

## Instruments (review.py)

- **Motion meter** (`motion_profile`): ffmpeg decodes the clip to 64x36 greyscale at 8 fps;
  mean absolute frame difference per step. Frozen = below 1.2 (0-255) for 1 s or more;
  a cut = a jump above 28. Free, ~0.25 s per clip.
- **Reviewer** (`review_take`): Gemini 3.1 Pro watches the take at 4 fps (the default
  1 fps misses one-second glitches) beside the brief, the reference sheets, the intended
  first frame and the motion meter's numbers. Returns 1-5 scores on identity, costume,
  environment, action, camera, pacing, physics, artifacts, style, continuity; timestamped
  issues; keep / fix / reshoot; a short edit instruction; prompt advice. ~$0.05, ~30-50 s.

## Baseline findings (2026-09-25, 4 takes, planner v1 + Omni, 360p)

| Take | Verdict | Overall | Dead time | Main problems |
|---|---|---|---|---|
| The Pass s01 (bike passes camera) | reshoot | 3.7 | 0 s | bike + rider morph and flip direction while turning toward camera (3.5-5.5 s) |
| Green Means Go s01 (reads note, lowers it) | reshoot | 3.5 | 1.75 s | frozen start; prop wrong (big sheet vs card); garbled text; neckline morphs |
| Green Means Go s02 (whisper) | keep | 4.6 | 0 s | 2.5 s walk-in before the action; static lens flare |
| Green Means Go s06 (note into jacket pocket) | reshoot | 4.1 | 1.5 s | frozen start; jacket "worn by an invisible torso"; pocket melts |

Patterns, and the hypothesis each suggests:

1. **Warm-up stall**: 3 of 4 takes open with 1.5-2.5 s of nothing. → Prompts should say the
   action is already underway in the first frame, and plan timed beats so there's no slack.
2. **Complex 3D motion toward camera morphs** (vehicle turning, body rotating). → The director
   should prefer lateral / profile motion paths and simple, readable blocking.
3. **Text on props comes out garbled**. → Never rely on legible text; say "no readable text"
   or make text a separate insert shot.
4. **Garments and soft objects morph during interaction** (neckline, jacket, pocket). →
   Describe the physical state of cloth explicitly; avoid hands manipulating fabric in close-up.
5. **Style words cause artifacts** ("anamorphic bokeh" → static lens flare). → Style profiles
   should hold vetted vocabulary per look.

## Plan

1. **Instruments.** Done: motion meter, reviewer, review panel in the app.
2. **Planner v2** (built; first live plan below)
   - Scenes as timed beats (t_start, t_end, what changes, camera), a visible change every
     ~1.5-3 s, holds only when deliberate and labelled. Clip length = sum of beats.
   - Camera moves with motivation, speed, start and end framing.
   - Optional multi-shot clips (2-3 shots inside one 8-10 s generation) when a scene needs
     coverage; single take otherwise. Both Omni and Kling support in-clip cuts.
   - Director pass: a second call that critiques the plan against the patterns above and
     rewrites weak scenes before anything is generated.
3. **Style profiles**: medium, visual descriptors, motion language, camera grammar, pacing
   defaults, reference-sheet look, avoid list. Presets (3D animated feature, anime,
   cyberpunk, noir, live-action drama) + free text expanded by the planner into a profile.
   Describe traits, don't name studios.
4. **Prompt compiler v2** per provider: beats → Omni timing language / Kling multi-shot syntax.
5. **A/B rounds**: same scenes, v1 vs v2, 2 takes each at 360p (~$1-2 per round); compare
   reviewer scores, dead time, and your picks.

## Planner v2, first live plan (The Pass, 2026-09-25)

Draft + director: 128 s, $0.22 (8.8k input, 8.5k output, 8.4k thinking tokens), about 4x v1.
- Every scene is timed beats with the action underway at 0 s; s05 (the photo reveal) became a
  2-shot clip: a push-in on the photo, then a cut to Tsering's smile.
- Restaged where the story didn't need the risk: bike ploughs straight instead of fishtailing,
  chai already on the counter instead of handed over, departure rides straight away from camera.
- Kept risks the story needs and recorded the handling (the photo gets a locked-off shot and is
  described as a physical curled print).
- To watch: 3 scenes use deliberate holds; the A/B round should show whether they read as
  intentional or as stalling.
