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

## A/B round 1: v1 vs v2 prompts (2026-09-25)

Setup: the original v1 plan of The Pass vs a copy converted to v2 by the director (same ids,
same reference images), Gemini Omni at 360p, scenes s01 (bike in the storm), s02 (chai: hands
and objects), s05 (departure on the bike), 2 takes each, all reviewed. Spend $4.43 (refs $0.67,
video $3.03, director $0.11, reviews $0.62). Takes rendered in 25-66 s.

| | v1 | v2 |
|---|---|---|
| Mean overall (1-5) | 3.85 | **4.22** |
| Keep / fix / reshoot | 1 / 0 / 5 | 0 / **3** / 3 |
| Physics | 2.50 | **3.33** |
| Artifacts | 2.00 | **2.50** |
| Costume | 3.67 | **4.33** |
| Environment | 4.00 | **4.50** |
| Style | 4.00 | **5.00** |
| Pacing | **4.67** | 4.50 |
| Identity | **4.00** | 3.83 |
| Dead time (meter) | 0 s | 0 s |

Reading it (n = 6 per arm, so treat as direction, not proof):
- v2 is better overall, mainly physics, costume, environment and style; usable-or-fixable takes
  went from 1/6 to 3/6.
- No frozen starts in either arm this time (all were motion scenes); the stall pattern from
  Green Means Go was in static close-ups, which this round didn't test.
- v2 s05 finished its only action early and froze: the conversion kept v1's thin content
  (one head turn over 7 s). Beats must fill the clip, or the clip must be shorter.
- Failures common to both arms, i.e. model limits rather than prompts: motorcycle wheels not
  turning (the bike glides), faces melting in close-ups, hands merging into handlebars,
  reference details dropped (gloves, reflective bands).
- New style artefact: "35mm film grain" produced literal film-strip borders with sprocket holes
  (v2 s02). Like "anamorphic" -> lens flare: style vocabulary needs vetting.

Next changes to test:
1. Director: vehicles get explicit motion cues (wheels turning, spray from the rear tyre,
   suspension working); thin scenes get richer beats or a shorter duration.
2. Style vocabulary rules: describe the texture ("fine film grain") and never the film stock,
   format or lens hardware ("35mm", "anamorphic") in prompts.
3. Next round with a fresh v2 plan (not a conversion), including static close-ups, and the
   same scenes on Kling once a key is set up.

## A/B round 2: fresh v1 plan vs fresh v2 plan (2026-09-25)

Setup: one story (monsoon courier delivers a letter; the old postman reads it and smiles) planned
from scratch by each planner, each with its own references, 9:16, Gemini Omni at 360p, scenes
s01 (scooter in flood), s02 (letter handed over), s03 (reading close-up), 2 takes each, all
reviewed. Director changes from round 1 were in. Spend $5.71 (refs $1.94, video $2.91, planning
$0.20, reviews $0.66). Estimate was $4.60: two full reference sets cost more than assumed.

| | v1 | v2 |
|---|---|---|
| Mean overall (1-5) | **4.28** | 3.75 |
| Keep / fix / reshoot | **2** / 0 / 4 | 0 / 0 / 6 |
| Costume | **4.67** | 2.83 |
| Artifacts | **3.33** | 2.17 |
| Physics | **3.50** | 2.67 |
| Camera | **4.83** | 3.83 |
| Pacing | 3.83 | **4.33** |

Across both rounds (12 takes each): v1 4.07, v2 3.98. A tie on averages; the mechanisms matter more:

1. **In-clip cuts hurt consistency on Omni.** Both v2 multi-shot scenes drifted at the cut: the
   helmet gained a visor, the scooter badge changed, the helmet turned into a silver dome, gloves
   appeared. Costume fell from 4.67 to 2.83. Coverage should come from separate scenes for now.
2. **A precise close-up hand-off still fails.** v2 kept the handover (the story needs it) and
   described it exactly: in both takes the fingers merged into the envelope. v1 had the postman
   already holding the letter and got a keep. Lesson: some actions should be implied through the
   edit (courier offers it / next shot he's holding it). That keeps the story and drops the risk.
3. **A big push-in to a tight close-up can come out as a cross-dissolve** (v2 s03 take 2: ghosted
   faces). One observation; watch for it.
4. **v2's beats did reduce stalling**: pacing 4.33 vs 3.83. v1's postman froze in a stare for
   3.5 s, and v1's reader stared without reading.
5. **Model limits in both arms**: water spray renders as a rigid V that slides with the scooter,
   wheels don't turn, handwriting is gibberish, small costume details drift. Motion cues in the
   prompt didn't fix gliding.
6. **Meter blind spot**: 0 s dead time everywhere, yet the reviewer found stalls. Rain and grain
   keep pixels moving while the subject is frozen; a whole-frame measure can't see subject stalls.

Changes to make:
- In-clip cuts off by default (opt-in per scene). Test them separately, and on Kling later.
- Director rule: hand-offs and fingers on small objects are implied across a cut or scene
  boundary, not shown in close-up. This is restaging that keeps the story, per the balance rule.
- Keep push-ins moderate within one beat (e.g. medium to close-up, not to extreme close-up).
