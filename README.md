# ReelForge

Idea in, film out. Gemini 3.1 Pro writes the production plan, Nano Banana Pro paints
character / prop / location references, Gemini Omni Flash shoots each scene with those
references attached, ffmpeg stitches the selected takes.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-local%20API-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini-Vertex%20AI-4285F4?logo=google&logoColor=white)
![ffmpeg](https://img.shields.io/badge/ffmpeg-edit%20%26%20stitch-007808?logo=ffmpeg&logoColor=white)

## Highlights

- **A pipeline with checkpoints, not a one-shot prompt.** Plan, references,
  scenes and final cut are separate steps you can review and redo, and any
  run can be resumed where it stopped.
- **Consistent characters.** Every scene is shot with the same painted
  reference sheets attached, so people, props and places hold across takes.
- **Pluggable video models.** Each model is a provider behind one interface
  (prompt syntax, submit, collect, price); Gemini Omni and Kling ship today.
- **Cost is a first-class feature.** Every call logs token usage and an
  estimated cost, every button that spends money shows an estimate first,
  and anything over $1 asks.
- **Tested offline.** The test suite runs against a fake client, so nothing
  is billed, and `--demo` runs the whole UI the same way.
- **Stack:** Python pipeline and FastAPI server, Next.js UI exported as
  static files and served locally, ffmpeg for editing, captions and stitching.

## Start it
Double-click **`ReelForge.bat`**. It sets things up on first run, starts the app and opens
your browser at http://localhost:8765. Close the console window to stop it.

    python launch.py --shortcut     # put a ReelForge icon on the desktop
    python launch.py --demo         # try the UI with a fake model; nothing is billed

Needs Python 3.11+, Node.js (only to build the UI after updates) and ffmpeg
(`winget install Gyan.FFmpeg`) for continuous scenes, posters and stitching.

## Credentials (`.env` next to this file)
GCP credits apply only through Vertex AI:

    GOOGLE_GENAI_USE_VERTEXAI=true
    GOOGLE_CLOUD_PROJECT=<your-project-id>
    GOOGLE_CLOUD_LOCATION=global     # preview models are usually served from global

then run `gcloud auth application-default login` once. Or use an AI Studio key:
`GEMINI_API_KEY=...`. Backend, project, models and defaults can also be changed in the
app's Settings (saved to `reelforge.settings.json`). On Vertex, 1080p/4k needs a Cloud
Storage bucket, which isn't wired up yet; 360p/720p work.

## Video models
Every scene can be shot by a different model (Scenes tab, per-scene picker; the default is in
Settings). Each model is a provider in `providers/` talking to that company's own API:

| Provider | Model | Setup |
|---|---|---|
| Gemini Omni Flash | `gemini-omni-1.1-flash(-preview)` | the Google credentials above |
| Kling 3.0 Omni | `kling-3.0-omni` | `KLING_API_KEY=...` in `.env` (Kling console → API Keys) |

Kling shoots 3-15 s clips at 720p and up (360p requests are shot at 720p), and can only edit
takes it made in the last 30 days. Edits always go to the model that made the take. To add a
model, write a `VideoProvider` (prompt syntax, submit, collect, price) and register it in
`providers/__init__.py`.

## Workflow
1. **Plan**: describe the story; review and edit the plan before anything costly runs.
2. **References**: paint the cast, props and locations; repaint or edit prompts until right.
3. **Scenes**: shoot takes, pick the best, or describe a fix ("heavier snow") to edit a take
   instead of re-rolling it.
4. **Final cut**: stitch the selected takes.

"Make it all" / "Make everything missing" run the rest with no checkpoints. They skip
what already exists, so re-running resumes an interrupted or failed run. Rate limits are
retried; billing/credential/permission errors stop the run at once; a scene whose
references failed is skipped rather than shot without them.

## Influencers
Switch to **Influencers** in the top bar. Design a fictional creator (look, persona, voice,
home); AI fills whatever you leave empty. Paint their **identity pack** (face first, then
three-quarter, profile, full body and home, all raw and unretouched) and add **places**
they film in more than once (gym, café, car...).

A creator can also be made **from photos** of a real person (yourself, or someone who agreed;
a consent statement is stored with them): every identity view is painted from the photos. The
voice is still Omni's, from the description: Omni takes no audio references, so it can't clone one.

**Products** (Influencers page): add photos of a real item, AI fills in what it looks like, and a
clean product shot is painted. Feature up to two in a video, worn or held: the script uses only
the facts you give, the opening frame shows the exact item, and Omni keeps it through the take.

Each video has its own **setup**: a format (selfie talking head, propped-up phone, walk and
talk, mirror, walk into frame, podcast), where, what they wear, their position and the light.
AI proposes it with the script, in their voice, split into 10 s segments; you edit both.
An **opening frame** (one image, two for walk-ins) is painted from the identity pack for the
setup; **Shoot** starts the video from it and extends the same take with Gemini Omni, 10 s
at a time, up to 40 s. Stored under `library/influencers/<id>/`.

## Edit, download, 1080p
Finished films and videos have **Download** and **Edit**: trim, colour (looks, brightness,
contrast, saturation, warmth) and audio (volume, reduce noise, even out loudness, mute).
Edits export a copy (`edited.mp4`); the original stays.

**Captions** (influencer videos, in Edit → Captions) are your script's words, never
transcribed. Timing is estimated from the script, or **Sync to the voice** (≈$0.02) times your
words to the audio without changing them, and flags where the delivery differs from the
script. Pick a preset or set font, size, colours, outline, box, position, words per caption
and animation (pop, fade, highlight the spoken word, word by word); save your own presets.
Captions are burned in on export with bundled open-licence fonts (`fonts/`), plus any you add
under Font → **Add font**: search Google Fonts (free, any weight), one-click popular caption fonts,
or upload a .ttf/.otf. Added fonts live in `library/fonts/`.

1080p is native (Omni renders it), not upscaled. On Vertex it's delivered through a Cloud
Storage bucket: **Settings → Generation → Create bucket** once (private, in your project,
files deleted after a day), then pick 1080p. It costs about 1.5x 720p.

## Costs
Every generation call logs its token usage and an estimated `cost_usd` to `log.jsonl`
(prices live in `Settings.PRICES`). The app shows spend per film, an estimate on every
button that spends money, and asks before anything over $1.

## Headless
    python cli.py --story "..." --style "..."        # 9:16, 720p by default
    python cli.py --story "..." --resolution 360p     # cheap test run
    python cli.py --resume projects/<folder>          # finish an interrupted/failed run

## Code
    pipeline.py   all generation logic (no UI)
    influencers.py  influencer profiles, identity pack, scripts, extended reels
    captions.py   script-based captions: timing, grouping, styles, ASS for burn-in
    fontbook.py   caption fonts: bundled, uploaded, imported from Google Fonts
    products.py   products for videos: photos, description, packshot
    uploads.py    uploaded images, cleaned (no EXIF/location) until used
    editor.py     trim, colour, audio (and captions) exported with ffmpeg
    server.py     local API + background jobs over pipeline.py; serves the UI
    web/          Next.js UI (exported to web/out, served by server.py)
    launch.py     builds the UI when needed, starts the server, opens the browser
    cli.py        headless runs

UI development: run `python launch.py --no-browser`, then in `web/`:
`set NEXT_PUBLIC_API=http://localhost:8765 && npm run dev` (hot reload on :3000).

## Tests
    pip install -r requirements-dev.txt
    python -m pytest -q          # offline: a fake client stands in for the API, nothing is billed

## Project folder
    projects/<date>-<title>/
      plan.json           production plan (also stores prompt overrides + chosen takes)
      assets/*.png        reference sheets and environment plates
      scenes/s01/take_01.mp4 + take_01.json   clip + exact prompt, refs, usage, cost
      frames/             continuity frames and poster stills
      log.jsonl           every generation call, in order, with cost
      final.mp4
