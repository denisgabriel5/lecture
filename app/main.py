"""Lecture — PDF-to-audio API (Gemini Flash TTS)."""
import logging
import uuid
from pathlib import Path

import aiofiles
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .job_manager import (
    UPLOADS_DIR, OUTPUT_DIR,
    create_job, delete_job, enqueue, get_job, init_db, init_dirs, list_jobs,
    start_worker,
)
from .tts_engine import VOICES, DEFAULT_VOICE

# Route module loggers (job progress) to stdout for `docker logs`.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Lecture", docs_url=None, redoc_url=None)

_SAMPLES_DIR = Path("/app/app/static/samples")


def _voices_with_samples() -> list[str]:
    """Only offer voices that have a pre-generated audition sample on disk."""
    avail = [v for v in VOICES if (_SAMPLES_DIR / f"{v}.mp3").exists()]
    return avail or list(VOICES)  # fall back to full list if samples missing


@app.on_event("startup")
async def startup() -> None:
    init_dirs()
    init_db()
    start_worker()


# ---------------------------------------------------------------------------
# Voices (Gemini prebuilt voices — fixed catalog, nothing to manage)
# ---------------------------------------------------------------------------

@app.get("/api/voices")
async def list_voices() -> list[dict]:
    avail = _voices_with_samples()
    default = DEFAULT_VOICE if DEFAULT_VOICE in avail else avail[0]
    return [
        {"id": name, "label": f"{name} · {VOICES[name]}", "default": name == default}
        for name in avail
    ]


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@app.get("/api/jobs")
async def get_jobs() -> list:
    return list_jobs()


@app.post("/api/jobs", status_code=201)
async def create_new_job(
    file: UploadFile = File(...),
    language: str = Form("ro"),
    voice: str = Form(DEFAULT_VOICE),
) -> dict:
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")
    if voice not in VOICES:
        raise HTTPException(404, f"Unknown voice: {voice}")

    job_id = str(uuid.uuid4())
    pdf_path = UPLOADS_DIR / f"{job_id}.pdf"
    async with aiofiles.open(pdf_path, "wb") as f:
        await f.write(await file.read())

    create_job(job_id=job_id, filename=file.filename, language=language, voice=voice)
    enqueue(job_id, str(pdf_path))
    return get_job(job_id)


@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.delete("/api/jobs/{job_id}")
async def remove_job(job_id: str) -> dict:
    if not get_job(job_id):
        raise HTTPException(404, "Job not found")
    delete_job(job_id)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/audio")
async def stream_audio(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] != "done":
        raise HTTPException(400, "Job not complete yet")

    audio = OUTPUT_DIR / f"{job_id}.mp3"
    if not audio.exists():
        raise HTTPException(404, "Audio file missing")

    return FileResponse(
        str(audio),
        media_type="audio/mpeg",
        filename=Path(job["filename"]).stem + ".mp3",
        headers={"Accept-Ranges": "bytes"},
    )


# ---------------------------------------------------------------------------
# Frontend (must be last)
# ---------------------------------------------------------------------------

_STATIC_DIR = "/app/app/static"
_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


@app.get("/sw.js")
async def service_worker() -> FileResponse:
    # Never let the service worker script itself be HTTP-cached, otherwise
    # clients (especially iOS Safari) won't notice new versions.
    return FileResponse(f"{_STATIC_DIR}/sw.js", media_type="application/javascript",
                        headers=_NO_CACHE)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(f"{_STATIC_DIR}/index.html", media_type="text/html",
                        headers=_NO_CACHE)


app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
