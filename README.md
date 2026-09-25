# ReelForge

Idea in, film out. Gemini 3.1 Pro writes the production plan, Nano Banana Pro paints
character / prop / location references, Gemini Omni Flash shoots each scene with those
references attached, ffmpeg stitches the selected takes.

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
