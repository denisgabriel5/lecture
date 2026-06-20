# Lecture

Self-hosted PDF-to-audio narration. Upload a PDF, pick an instructor-style voice,
get an MP3 read aloud — built as an installable iOS-friendly PWA.

Text-to-speech is powered by **Google Gemini Flash TTS** (`gemini-3.1-flash-tts-preview`),
which produces natural, teacher-style narration and supports Romanian. The container
is small and stateless apart from a data volume — no local ML models, no GPU.

## Image

Published to GHCR on every push to `main`:

```
ghcr.io/denisgabriel5/lecture:latest
```

## Usage (docker compose)

```yaml
services:
  lecture:
    image: ghcr.io/denisgabriel5/lecture:latest
    container_name: lecture
    volumes:
      - ./data:/data            # jobs DB, chunk cache, output MP3s
    environment:
      - GEMINI_API_KEY=your_key_here
    ports:
      - "8000:8000"
    restart: unless-stopped
```

Then open <http://localhost:8000>.

> Put the real key in an `.env` file / secret rather than committing it.

## Configuration

| Env var                  | Default                       | Purpose                                   |
|--------------------------|-------------------------------|-------------------------------------------|
| `GEMINI_API_KEY`         | — (required)                  | Google AI Studio API key for TTS          |
| `GEMINI_TTS_MODEL`       | `gemini-3.1-flash-tts-preview`| Override the TTS model                    |
| `LECTURE_SYNTH_WORKERS`  | `4`                           | Parallel chunk synthesis (mind rate limits)|
| `DATA_DIR`               | `/data`                       | Where jobs, cache and output live         |

Get a key at <https://aistudio.google.com> → **Get API key**.

## How it works

```
PDF → extract text (PyMuPDF) → sentence-boundary chunks
    → Gemini Flash TTS per chunk (parallel, cached by content hash)
    → ffmpeg concat → MP3
```

- Jobs run in a background worker with a SQLite queue; progress is polled by the UI.
- Synthesised chunks are content-addressed and cached, so re-runs are instant.
- Completed jobs are kept for 7 days, then cleaned up automatically.

## Voices

A curated set of teacher/instructor Gemini voices, each with a pre-generated
Romanian audition sample played from the voice picker. Only voices that have a
sample bundled under `app/static/samples/` are offered in the UI.

## Development

```bash
pip install -r requirements.txt
GEMINI_API_KEY=... uvicorn app.main:app --reload
```
