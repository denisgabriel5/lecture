# AGENTS.md

Guidance for automated coding agents working in this repository.

## What this is

A self-hosted PWA that converts PDFs into narrated MP3s. Text-to-speech uses the
Google Gemini Flash TTS API (`gemini-3.1-flash-tts-preview`) in a teacher/lecture
style. The service is a single FastAPI app; there are no local ML models.

## Layout

```
Dockerfile              # python:3.11-slim + ffmpeg, runs uvicorn
requirements.txt        # fastapi, uvicorn, PyMuPDF, Pillow (no torch / no ML deps)
app/
  main.py               # FastAPI routes: /api/voices, /api/jobs, audio streaming
  job_manager.py        # SQLite job queue + background worker; parallel synthesis
  tts_engine.py         # Gemini TTS HTTP client, voice catalog, style prompt
  pdf_processor.py      # PyMuPDF text extraction + sentence-boundary chunking
  make_icons.py         # generates PWA icons at build time → static/icons/
  static/               # PWA frontend (vanilla JS, no framework) + voice samples
.github/workflows/      # builds & pushes ghcr.io/denisgabriel5/lecture:latest
```

## Pipeline

`PDF → extract text (PyMuPDF) → chunk → Gemini TTS per chunk (parallel, cached)
→ ffmpeg concat → MP3`. Chunks are content-addressed (`sha256(text+lang+voice)`)
and cached under `DATA_DIR/chunks`, so re-runs are cheap. Jobs live in
`DATA_DIR/jobs/jobs.db`; completed jobs are auto-pruned after 7 days.

## Conventions

- **No framework on the frontend** — plain ES, `app.js` + `style.css`. Match the
  existing iOS/Apple-style visual language (system colors, frosted materials,
  spring easings, bottom-sheet modals). Keep all class names stable; the JS and
  HTML depend on them.
- **Bump the service worker cache** (`static/sw.js`, `const CACHE`) whenever you
  change any shell asset (`index.html`, `app.js`, `style.css`, `manifest.json`),
  or clients will keep serving stale files.
- **Voices**: defined in `tts_engine.py:VOICES`. A voice is only offered in the UI
  if a matching `static/samples/<Voice>.mp3` audition clip exists (see
  `_voices_with_samples` in `main.py`). When adding a voice, add its sample too.
- **TTS style** lives in `tts_engine.py:STYLE`. It is prepended to every chunk and
  must read as an instructor, not a storyteller. Verify the instruction is not
  spoken aloud after changing it.
- Keep the image free of heavyweight ML dependencies; synthesis is a remote API
  call, which is why chunks can be synthesised in parallel.

## Configuration

| Env var                 | Default                         | Purpose                              |
|-------------------------|---------------------------------|--------------------------------------|
| `GEMINI_API_KEY`        | required                        | Google AI Studio key                 |
| `GEMINI_TTS_MODEL`      | `gemini-3.1-flash-tts-preview`  | TTS model override                   |
| `LECTURE_SYNTH_WORKERS` | `4`                             | Parallel chunk synthesis             |
| `DATA_DIR`              | `/data`                         | jobs DB, chunk cache, output         |

Never commit a real `GEMINI_API_KEY`; it is supplied at runtime via env.

## Build & run

```bash
# Local dev
pip install -r requirements.txt
GEMINI_API_KEY=... uvicorn app.main:app --reload

# Container
docker build -t lecture .
docker run -p 8000:8000 -e GEMINI_API_KEY=... -v "$PWD/data:/data" lecture
```

## Gotchas

- The Gemini free tier is rate-limited (per-minute and daily). Generating many
  clips quickly returns HTTP 429; `tts_engine` retries with backoff, but a job can
  still fail if the daily quota is gone. Space out bulk sample generation.
- Audio is returned as raw PCM (`audio/L16`, 24 kHz mono); wrap it in a WAV
  container before handing it to ffmpeg.
- Icons under `static/icons/` are generated at build time and git-ignored — do not
  commit them.
