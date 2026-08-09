"""Voice-file loading and per-narrator lookups for session_doc and the sd_* CLIs."""

import re
from pathlib import Path


def load_voice_files(voice_dir: Path) -> dict[str, str]:
    """Load per-character voice files from a directory.

    Looks for files named {character_name}_voice.md or {character_name}.md
    (case-insensitive). Returns a dict mapping lowercased character name to content.
    Files whose name starts with ``_`` are skipped — they are shared campaign material.
    """
    voices: dict[str, str] = {}
    for f in voice_dir.glob("*.md"):
        if f.name.startswith("_"):
            # `_genre.md` and friends are shared campaign material, not a
            # per-character voice file (mirrors session_doc/io.py's skip).
            continue
        stem = f.stem.lower()
        key = stem.removesuffix("_voice")
        voices[key] = f.read_text(encoding="utf-8").strip()
    return voices


def get_voice_note(voices: dict[str, str], narrator: str) -> str | None:
    """Look up a voice note for a narrator by case-insensitive name match."""
    key = narrator.lower().split()[0]
    return voices.get(key) or voices.get(narrator.lower())


def extract_contrast_sample(text: str, max_sentences: int = 5) -> str:
    """First substantive paragraph's first ~5 sentences — Phase-3 contrast signal.

    Skips markdown headings, italic-only captions, and `---` separators so the
    sample is drawn from the first verbatim passage in a per-char examples file
    rather than the file's title or subtitle. Title and italic subtitle are often
    joined into one paragraph (single newline between them), so the skip checks
    chrome line-by-line, not chunk-as-a-whole.
    """
    def is_chrome(line: str) -> bool:
        s = line.strip()
        if not s or s == "---":
            return True
        if s.startswith("#"):
            return True
        if s.startswith("*") and s.endswith("*") and len(s) > 1:
            return True
        return False

    for chunk in text.split("\n\n"):
        chunk = chunk.strip()
        if not chunk or chunk == "---":
            continue
        lines = [ln for ln in chunk.splitlines() if ln.strip()]
        if not lines or all(is_chrome(ln) for ln in lines):
            continue
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', chunk) if s.strip()]
        if not sentences:
            return chunk
        return " ".join(sentences[:max_sentences])
    return ""
