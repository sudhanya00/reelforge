# ReelForge guide

How to set it up and use every part of it. For what it is and how it works, see the
[README](../README.md).

## Start it
Double-click **`ReelForge.bat`**. It sets things up on first run, starts the app and opens
your browser at http://localhost:8765. Close the console window to stop it.

    python launch.py --shortcut     # put a ReelForge icon on the desktop
    python launch.py --demo         # try the UI with a fake model; nothing is billed

Needs Python 3.11+, Node.js (only to build the UI after updates) and ffmpeg
(`winget install Gyan.FFmpeg`) for continuous scenes, posters, stitching, editing and captions.
If ReelForge is updated while it's running, a banner asks you to restart it.

## Credentials (`.env` next to `launch.py`)
Google Cloud credits apply only through Vertex AI:

    GOOGLE_GENAI_USE_VERTEXAI=true
    GOOGLE_CLOUD_PROJECT=<your-project-id>
    GOOGLE_CLOUD_LOCATION=global     # preview models are usually served from global

then run `gcloud auth application-default login` once. Or use an AI Studio key:
`GEMINI_API_KEY=...`. Backend, project, models and defaults can also be changed in the
app's Settings (saved to `reelforge.settings.json`).

**1080p and 4K** are rendered natively by Omni, not upscaled. On Vertex they're delivered
through Cloud Storage: **Settings → Generation → Create bucket** once (private, in your
project, files deleted after a day). 1080p costs about 1.5x 720p.

## Video models
Every film scene can be shot by a different model (Scenes tab, per-scene picker; the default
is in Settings). Each model is a provider in `providers/` talking to that company's own API:

| Provider | Model | Setup | Notes |
|---|---|---|---|
| Gemini Omni Flash (default) | `gemini-omni-1.1-flash(-preview)` | the Google credentials above | edits takes; extends takes (influencer videos) |
| Veo 3.1 / Veo 3.1 Fast | `veo-3.1(-fast)-generate-001` | the Google credentials (served from `us-central1`) | 8 s clips when references are attached; no edits |
| Kling 3.0 Omni | `kling-3.0-omni` | `KLING_API_KEY=...` in `.env` | 3-15 s, 720p and up; edits its own takes (30 days) |

Edits always go to the model that made the take. To add a model, write a `VideoProvider`
(prompt syntax, submit, collect, price) and register it in `providers/__init__.py`.

## Films
1. **Plan**: describe the story, pick a style preset and pacing, and optionally cast saved
   characters. Gemini writes a plan with timed beats; a director pass reviews it for what
   video models get wrong. Edit anything before paying for images or video.
2. **References**: paint the cast, props and locations; repaint or edit prompts until right.
   Save a character to the library to reuse them in later films.
3. **Scenes**: shoot takes, pick the best, describe a fix ("heavier snow") to edit a take
   instead of re-rolling it, or ask the AI reviewer to score a take.
4. **Final cut**: stitch the selected takes, then edit or download.

"Make it all" / "Make everything missing" run the rest with no checkpoints. They skip what
already exists, so re-running resumes an interrupted or failed run. Rate limits are retried;
billing, credential and permission errors stop the run at once; a scene whose references
failed is skipped rather than shot without them.

## Influencers
Switch to **Influencers** in the top bar.

**Design a creator**: name, look, personality, how they talk, voice and home. AI fills
whatever you leave empty. Three ways to start:
- **From words**: describe a concept.
- **Mood board**: images of looks, styles and vibes you like are read into words for the
  type (hair, skin tone, build, style, a signature outfit, energy). Faces aren't described
  and the images are never passed to the image or video models, so the creator gets a face
  of their own.
- **From photos of a real person**: yourself, or someone who agreed (a consent statement is
  stored with them). Every identity view is painted from the photos. Video models may refuse
  well-known faces.

**Identity tab**
- **Casting**: paint 2-6 faces from the description, refine any option with notes ("bigger
  smile, lighter brows"), then *Use this face*.
- **Identity pack**: face, three-quarter, profile, full body and home, raw and unretouched.
  Views painted from an older face are flagged and can be updated in one click.
- **Places**: where they film more than once (gym, café, car...), each with an empty plate.

**Products** (Influencers home): photos of a real item; AI describes it (printed text word for
word), and a clean product shot is painted. Add what the creator may say about it: the script
only uses those facts.

**Videos tab**: pick a format (selfie talking head, propped-up phone, walk and talk, mirror,
walk into frame, podcast), where, what they wear, and up to two products (worn or held), then
a topic. AI writes the script in their voice, in 10 s segments, and the setup (place, outfit,
position, light); you edit both. An **opening frame** is painted from the identity pack,
place and products; **Shoot** starts the video from it and extends the same take with Gemini
Omni, 10 s at a time, up to 40 s. Omni can't clone voices (no audio references); the voice
comes from the description.

## Edit, captions, download
Finished films and videos have **Edit** and **Download**. Edit exports a copy
(`edited.mp4`); the original stays.
- **Trim, colour, audio**: two-handle trim; looks and sliders for brightness, contrast,
  saturation and warmth (previewed with the same maths ffmpeg exports); volume up to 200%,
  reduce noise, even out loudness, mute.
- **Captions** (influencer videos): the script's words, never transcribed. Timing is estimated
  from the script, or **Sync to the voice** (about $0.02) times your words to the audio
  without changing them and flags where the delivery differs. Presets or your own style
  (font, size, colours, outline, box, position, words per caption, six animations); save
  presets. Fonts: ten bundled, plus **Add font** from Google Fonts (any family and weight) or
  a .ttf/.otf upload.

## Costs
Every generation call logs its token usage and an estimated `cost_usd` to `log.jsonl`
(prices live in `Settings.PRICES`). The app shows spend per film and creator, an estimate on
every button that spends money, and asks before anything over $1. Measured on real runs:
an Omni extension returns the whole take but bills output for its new seconds only, plus a
small charge to re-read the take so far.

## Headless
    python cli.py --story "..." --style "..."        # 9:16, 720p by default
    python cli.py --story "..." --resolution 360p     # cheap test run
    python cli.py --resume projects/<folder>          # finish an interrupted/failed run

## Code
    pipeline.py     film generation logic and settings (no UI)
    director.py     planner v2 schema and the director pass
    prompts.py      deterministic prompt text; styles.py: presets and pacing
    providers/      one module per model API (Gemini/Omni, Veo, Kling, Cloud Storage)
    review.py       the AI take reviewer and the motion meter
    influencers.py  creators: identity, casting, places, setups, scripts, extended takes
    products.py     products: photos, description, packshot
    captions.py     script captions: timing, grouping, styles, ASS for burn-in
    fontbook.py     caption fonts: bundled, uploaded, imported from Google Fonts
    editor.py       trim, colour, audio (and captions) exported with ffmpeg
    uploads.py      uploaded images, cleaned (no EXIF/location) until used
    library.py      saved film characters
    server.py       local API + background jobs; serves the UI
    web/            Next.js UI (exported to web/out, served by server.py)
    launch.py       builds the UI when needed, starts the server, opens the browser
    cli.py          headless runs

UI development: run `python launch.py --no-browser`, then in `web/`:
`set NEXT_PUBLIC_API=http://localhost:8765 && npm run dev` (hot reload on :3000).

## Tests
    pip install -r requirements-dev.txt
    python -m pytest -q          # offline: fakes stand in for every API, nothing is billed

## Where things are kept
    projects/<date>-<title>/          a film: plan.json, assets/, scenes/, log.jsonl, final.mp4
    library/characters/               saved film characters
    library/influencers/<id>/         a creator: profile, identity/, places/, videos/<video>/
    library/products/<id>/            photos, packshot.png, product.json
    library/fonts/                    fonts you added
