# ReelForge

Idea in, film out. Gemini 3.1 Pro writes the production bible, Nano Banana Pro paints
character / prop / location references, Gemini Omni Flash shoots each scene with those
references attached, ffmpeg stitches the selected takes.

## Setup
    pip install -r requirements.txt
    echo GEMINI_API_KEY=... > .env   # or export it, or paste it in the sidebar
    # optional but recommended: ffmpeg on PATH (for continuity frames + stitching)

### Billing via Vertex AI (GCP credits)
AI Studio keys bill AI Studio (prepaid or postpaid); GCP credits apply only through Vertex AI.
Put this in `.env` instead, then run `gcloud auth application-default login`:

    GOOGLE_GENAI_USE_VERTEXAI=true
    GOOGLE_CLOUD_PROJECT=<your-project-id>
    GOOGLE_CLOUD_LOCATION=global     # preview models are usually served from global

Or set `VERTEX_API_KEY` (Vertex express mode) instead of using gcloud credentials.
On Vertex, 1080p/4k (`delivery: uri`) needs a GCS bucket; 360p/720p return inline.

## Run
    streamlit run app.py             # step by step, with checkpoints
    python cli.py --story "..." --style "..." --orientation 9:16

## Project folder
    projects/<date>-<title>/
      plan.json           production bible (editable; also stores prompt overrides + chosen takes)
      assets/*.png        reference sheets and environment plates
      scenes/s01/take_01.mp4 + take_01.json   clip + exact prompt, refs, interaction id
      log.jsonl           every generation call, in order
      final.mp4

## Workflow
1. Plan: review and edit plan.json before spending on generation.
2. References: regenerate any sheet until it's right; later scenes reuse it.
3. Scenes: shoot takes, pick the best, or type a fix ("heavier snow") to edit
   the take conversationally instead of re-rolling from scratch.
4. Final cut: stitch the selected takes.

Model ids live in the sidebar / Settings; swap them when Google renames previews.
