"""Gemini Flash TTS engine — cloud synthesis, expressive teacher-style narration.

Each chunk is a single HTTPS call to the Gemini API. No local model, no GPU,
no torch. Network-bound, so the job manager can run several chunks in parallel.
"""
import base64
import json
import logging
import os
import time
import urllib.error
import urllib.request
import wave

logger = logging.getLogger(__name__)

MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview")
_API_KEY = os.environ.get("GEMINI_API_KEY", "")
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

# Delivery style prepended to every chunk. Gemini reads this as guidance and does
# not speak it. Tuned for "an instructor teaching a lesson", not a storyteller.
STYLE = (
    "Read the following text aloud in the clear, measured, articulate voice of a "
    "teacher explaining a lesson to students. Calm, steady pace, confident, with "
    "natural emphasis on the important terms. Not theatrical, not a storyteller — "
    "an instructor. Read only the text, do not add or omit anything"
)

# Curated teacher/instructor voices (clear, firm, informative, warm — not bubbly).
# Each has a pre-generated Romanian audition sample at /samples/<name>.mp3.
# Any of these can speak Romanian (the model auto-detects language from the text).
VOICES: dict = {
    "Charon": "Informative",
    "Rasalgethi": "Informative",
    "Iapetus": "Clear",
    "Erinome": "Clear",
    "Sadaltager": "Knowledgeable",
    "Kore": "Firm",
    "Orus": "Firm",
    "Alnilam": "Firm",
    "Schedar": "Even",
    "Gacrux": "Mature",
    "Sulafat": "Warm",
    "Achird": "Friendly",
}

DEFAULT_VOICE = "Charon"

_MAX_RETRIES = 5
_TIMEOUT = 120


class TTSError(RuntimeError):
    pass


def _request(text: str, voice: str) -> tuple[bytes, int]:
    """One synthesis call → (pcm_bytes, sample_rate). Retries transient failures."""
    if not _API_KEY:
        raise TTSError("GEMINI_API_KEY is not set")

    prompt = f"{STYLE}:\n\n{text}"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}
            },
        },
    }).encode()
    url = _ENDPOINT.format(model=MODEL, key=_API_KEY)

    last_err = None
    for attempt in range(_MAX_RETRIES):
        try:
            req = urllib.request.Request(url, data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.load(resp)
            part = data["candidates"][0]["content"]["parts"][0]["inlineData"]
            pcm = base64.b64decode(part["data"])
            rate = 24000
            for token in part.get("mimeType", "").split(";"):
                token = token.strip()
                if token.startswith("rate="):
                    rate = int(token.split("=")[1])
            if not pcm:
                raise TTSError("empty audio returned")
            return pcm, rate
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            last_err = f"HTTP {e.code}: {detail}"
            # 429 (rate limit) and 5xx are retryable; 4xx others are not
            if e.code != 429 and e.code < 500:
                raise TTSError(last_err) from e
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
            last_err = str(e)
        wait = min(2 ** attempt, 30)
        logger.warning("TTS attempt %d/%d failed (%s); retrying in %ds",
                       attempt + 1, _MAX_RETRIES, last_err, wait)
        time.sleep(wait)

    raise TTSError(f"synthesis failed after {_MAX_RETRIES} attempts: {last_err}")


def synthesize(text: str, output_path: str, voice: str, language: str = "ro") -> None:
    """Synthesise *text* to a WAV file using Gemini voice *voice*."""
    if voice not in VOICES:
        voice = DEFAULT_VOICE
    pcm, rate = _request(text, voice)
    with wave.open(output_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
