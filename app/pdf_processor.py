"""PDF text extraction and sentence-boundary chunking."""
import re
from collections import Counter
from typing import List

import fitz  # PyMuPDF


# Gemini TTS handles long passages cleanly; larger chunks mean far fewer API
# calls (faster, fewer rate-limit hits) while keeping each response a sane length.
_CHUNK_TARGET = 800
_CHUNK_MAX = 1200

# Sentence boundary: end punctuation followed by whitespace or end of string.
# Handles Romanian ellipses and abbreviations imperfectly but well enough.
_SENT_END = re.compile(r'(?<=[.!?…])\s+')


def _detect_repeated(line_lists: List[List[str]], threshold: float = 0.6) -> set:
    """Return lines that appear unchanged on >= threshold fraction of pages."""
    n = len(line_lists)
    if n < 3:
        return set()
    counter: Counter = Counter()
    for lines in line_lists:
        for pos in (0, -1):
            if lines:
                counter[lines[pos].strip()] += 1
    return {line for line, count in counter.items() if line and count / n >= threshold}


def _clean_page(text: str, repeated: set) -> str:
    lines = text.splitlines()
    out = []
    for line in lines:
        stripped = line.strip()
        # drop blank lines, page-number-only lines, and detected headers/footers
        if not stripped:
            continue
        if re.fullmatch(r'\d{1,4}', stripped):
            continue
        if stripped in repeated:
            continue
        out.append(stripped)
    return ' '.join(out)


def extract_text_from_pdf(path: str) -> str:
    doc = fitz.open(path)
    raw_pages: List[str] = [page.get_text("text") for page in doc]
    doc.close()

    line_lists = [p.splitlines() for p in raw_pages]
    repeated = _detect_repeated(line_lists)

    cleaned = [_clean_page(p, repeated) for p in raw_pages]
    text = ' '.join(cleaned)

    # Collapse whitespace, fix common PDF extraction artefacts
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'(\w)-\s+(\w)', r'\1\2', text)   # rejoin hyphenated line-breaks
    return text.strip()


def chunk_text(text: str, target: int = _CHUNK_TARGET, max_chars: int = _CHUNK_MAX) -> List[str]:
    """
    Split text on sentence boundaries into chunks of ~target characters.
    Chunks never exceed max_chars unless a single sentence is that long.
    """
    sentences = [s.strip() for s in _SENT_END.split(text) if s.strip()]

    chunks: List[str] = []
    buf: List[str] = []
    buf_len = 0

    for sent in sentences:
        if buf and buf_len + len(sent) + 1 > max_chars:
            chunks.append(' '.join(buf))
            buf, buf_len = [], 0

        buf.append(sent)
        buf_len += len(sent) + 1

        # Flush when we've hit the target naturally at a sentence boundary
        if buf_len >= target:
            chunks.append(' '.join(buf))
            buf, buf_len = [], 0

    if buf:
        chunks.append(' '.join(buf))

    return [c for c in chunks if c]
