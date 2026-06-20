"""SQLite-backed job queue with a single dispatcher thread and parallel synthesis."""
import hashlib
import logging
import os
import sqlite3
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from queue import Queue, Empty
from typing import Dict, List, Optional

# Gemini TTS is network-bound, so several chunks can synthesise concurrently.
# Kept modest to stay within API rate limits.
_SYNTH_WORKERS = int(os.environ.get("LECTURE_SYNTH_WORKERS", "4"))

JOB_RETENTION_DAYS = 7

logger = logging.getLogger(__name__)

_DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
JOBS_DIR = _DATA_DIR / "jobs"
CHUNKS_DIR = _DATA_DIR / "chunks"
OUTPUT_DIR = _DATA_DIR / "output"
VOICES_DIR = _DATA_DIR / "voices"
UPLOADS_DIR = _DATA_DIR / "uploads"
DB_PATH = JOBS_DIR / "jobs.db"

_queue: Queue = Queue()
_worker_thread: Optional[threading.Thread] = None


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def init_dirs() -> None:
    for d in (JOBS_DIR, CHUNKS_DIR, OUTPUT_DIR, VOICES_DIR, UPLOADS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id              TEXT PRIMARY KEY,
                filename        TEXT NOT NULL,
                language        TEXT NOT NULL DEFAULT 'ro',
                voice           TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'queued',
                total_chunks    INTEGER DEFAULT 0,
                done_chunks     INTEGER DEFAULT 0,
                current_chunk   TEXT,
                error           TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
        """)
        # Re-queue any jobs that were in-flight when the process was killed
        conn.execute(
            "UPDATE jobs SET status='queued', done_chunks=0 WHERE status='processing'"
        )
        conn.commit()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(job_id: str, filename: str, language: str, voice: str) -> None:
    now = _now()
    with _db() as conn:
        conn.execute(
            "INSERT INTO jobs (id,filename,language,voice,status,created_at,updated_at)"
            " VALUES (?,?,?,?,'queued',?,?)",
            (job_id, filename, language, voice, now, now),
        )
        conn.commit()


def get_job(job_id: str) -> Optional[Dict]:
    with _db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs() -> List[Dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def _update(job_id: str, **kwargs) -> None:
    kwargs["updated_at"] = _now()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [job_id]
    with _db() as conn:
        conn.execute(f"UPDATE jobs SET {sets} WHERE id=?", vals)
        conn.commit()


def delete_job(job_id: str) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        conn.commit()
    mp3 = OUTPUT_DIR / f"{job_id}.mp3"
    if mp3.exists():
        mp3.unlink()


def cleanup_old_jobs() -> None:
    """Remove done/failed jobs older than JOB_RETENTION_DAYS and their MP3 files."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=JOB_RETENTION_DAYS)).isoformat()
    with _db() as conn:
        old = conn.execute(
            "SELECT id FROM jobs WHERE status IN ('done','failed') AND created_at < ?",
            (cutoff,),
        ).fetchall()
        for row in old:
            mp3 = OUTPUT_DIR / f"{row['id']}.mp3"
            if mp3.exists():
                mp3.unlink()
            conn.execute("DELETE FROM jobs WHERE id=?", (row["id"],))
        conn.commit()
    if old:
        logger.info("Cleaned up %d expired jobs", len(old))


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def _chunk_key(text: str, language: str, voice: str) -> str:
    return hashlib.sha256(f"{text}\x00{language}\x00{voice}".encode()).hexdigest()


def _process(job_id: str, pdf_path: str) -> None:
    from .pdf_processor import extract_text_from_pdf, chunk_text
    from .tts_engine import synthesize, VOICES

    try:
        _update(job_id, status="processing")
        job = get_job(job_id)
        language = job["language"]
        voice = job["voice"]

        if voice not in VOICES:
            raise ValueError(f"Unknown voice: {voice}")

        text = extract_text_from_pdf(pdf_path)
        if not text:
            raise ValueError("No text could be extracted from the PDF")

        chunks = chunk_text(text)
        logger.info("Job %s: %d chunks", job_id, len(chunks))

        # Resolve cache paths; only synthesise the misses.
        chunk_paths: Dict[int, str] = {}
        to_synth: List[tuple] = []
        for i, chunk in enumerate(chunks):
            key = _chunk_key(chunk, language, voice)
            path = str(CHUNKS_DIR / f"{key}.wav")
            chunk_paths[i] = path
            if not os.path.exists(path):
                to_synth.append((i, chunk))

        cached_n = len(chunks) - len(to_synth)
        _update(job_id, total_chunks=len(chunks), done_chunks=cached_n)
        logger.info("Job %s: %d cached, %d to synthesise", job_id, cached_n, len(to_synth))

        done_count = [cached_n]
        done_lock = threading.Lock()

        def _synth(args: tuple) -> None:
            idx, text_chunk = args
            synthesize(text_chunk, chunk_paths[idx], voice, language)
            with done_lock:
                done_count[0] += 1
                _update(job_id, done_chunks=done_count[0], current_chunk=text_chunk[:80])

        if to_synth:
            with ThreadPoolExecutor(max_workers=_SYNTH_WORKERS,
                                    thread_name_prefix="tts") as pool:
                futures = {pool.submit(_synth, item): item[0] for item in to_synth}
                for future in as_completed(futures):
                    future.result()  # re-raise synthesis errors

        # Concatenate in original order → MP3
        wav_files = [chunk_paths[i] for i in range(len(chunks))]
        concat_file = JOBS_DIR / f"{job_id}_concat.txt"
        concat_file.write_text("\n".join(f"file '{p}'" for p in wav_files) + "\n")
        output = OUTPUT_DIR / f"{job_id}.mp3"
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(concat_file),
             "-c:a", "libmp3lame", "-q:a", "2", str(output)],
            capture_output=True, text=True,
        )
        concat_file.unlink(missing_ok=True)

        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")

        _update(job_id, status="done", current_chunk=None)
        logger.info("Job %s complete → %s", job_id, output)

    except Exception as exc:
        logger.error("Job %s failed: %s", job_id, exc, exc_info=True)
        _update(job_id, status="failed", error=str(exc)[:500])

    finally:
        if pdf_path and os.path.exists(pdf_path):
            os.unlink(pdf_path)


def _worker() -> None:
    logger.info("Job worker started")
    last_cleanup = 0.0
    while True:
        # Run cleanup once per day
        if time.monotonic() - last_cleanup > 86400:
            try:
                cleanup_old_jobs()
            except Exception as exc:
                logger.error("Cleanup error: %s", exc)
            last_cleanup = time.monotonic()

        try:
            job_id, pdf_path = _queue.get(timeout=5)
            _process(job_id, pdf_path)
            _queue.task_done()
        except Empty:
            # Re-queue any jobs that survived a crash (added to DB but never enqueued)
            with _db() as conn:
                rows = conn.execute(
                    "SELECT id FROM jobs WHERE status='queued' ORDER BY created_at"
                ).fetchall()
            for row in rows:
                jid = row["id"]
                pdf = UPLOADS_DIR / f"{jid}.pdf"
                if pdf.exists():
                    logger.info("Re-queuing orphaned job %s", jid)
                    _queue.put((jid, str(pdf)))
        except Exception as exc:
            logger.error("Worker loop error: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_worker() -> None:
    global _worker_thread
    _worker_thread = threading.Thread(target=_worker, daemon=True, name="tts-worker")
    _worker_thread.start()


def enqueue(job_id: str, pdf_path: str) -> None:
    _queue.put((job_id, pdf_path))
