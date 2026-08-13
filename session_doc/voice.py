"""Voice-file loading and per-narrator lookups for session_doc and the sd_* CLIs."""

import re
import sys
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


def _first_name(narrator: str) -> str:
    parts = narrator.lower().strip().split()
    return parts[0] if parts else narrator.lower().strip()


def _resolve_voice_key(voices: dict[str, str], narrator: str) -> tuple[str | None, bool]:
    """Resolve ``narrator`` to a key in ``voices`` without warning.

    Resolution order:
      (a) exact full-name key (``narrator.lower()``),
      (b) first-name key (``narrator.lower().split()[0]``),
      (c) the unique key whose name starts with the first name followed by a
          ``_`` or ``-`` separator — this is what makes real filenames like
          ``brewbarry_new_pipeline.md`` resolve for narrator "Brewbarry".

    Returns ``(key, ambiguous)``. ``key`` is ``None`` on a miss. ``ambiguous``
    is True when step (c) found two or more candidate keys — the caller must
    treat that as "cannot resolve," never guess which file to use.
    """
    if not voices:
        return None, False
    full = narrator.lower().strip()
    if full in voices:
        return full, False
    firstname = _first_name(narrator)
    if firstname in voices:
        return firstname, False
    prefix_len = len(firstname)
    candidates = sorted(
        k for k in voices
        if k.startswith(firstname) and len(k) > prefix_len and k[prefix_len] in "_-"
    )
    if len(candidates) == 1:
        return candidates[0], False
    if len(candidates) >= 2:
        return None, True
    return None, False


def get_voice_note(voices: dict[str, str], narrator: str) -> str | None:
    """Look up a voice note for a narrator by case-insensitive name match.

    An empty ``voices`` dict just means no ``--voice-dir`` was given and is
    not worth warning about. A *non-empty* dict that still can't resolve the
    narrator is the #247 failure mode — a real voice file sitting on disk
    that silently never reaches the prompt — so that case warns to stderr
    naming the narrator and the available keys, rather than vanishing.
    """
    if not voices:
        return None
    key, ambiguous = _resolve_voice_key(voices, narrator)
    if key is not None:
        return voices[key]
    firstname = _first_name(narrator)
    if ambiguous:
        print(
            f"Warning: voice file lookup for narrator '{narrator}' is ambiguous — "
            f"multiple keys start with '{firstname}_' or '{firstname}-' in "
            f"{sorted(voices)}. Refusing to guess; no voice spec will be used for "
            f"this narrator.\n"
            f"  -> rename the voice files so only one begins with '{firstname}' "
            f"followed by '_' or '-'.",
            file=sys.stderr,
        )
    else:
        print(
            f"Warning: no voice file found for narrator '{narrator}' — available "
            f"keys in --voice-dir: {sorted(voices)}.\n"
            f"  -> expected a file named '{firstname}.md', '{firstname}_voice.md', "
            f"or '{firstname}_<anything>.md'.",
            file=sys.stderr,
        )
    return None


def voice_resolution_problems(voices: dict[str, str],
                              narrators: list[str]) -> list[str]:
    """One problem line per narrator that has no usable voice spec.

    The pre-flight behind ``sd_narrate``'s refusal (#300). ``get_voice_note``
    warns and returns ``None`` per narrator, mid-render, once tokens have
    already been spent on earlier scenes; this answers the same question for
    every narrator in the plan *before* the first API call, so a render either
    has all its specs or does not start.

    Deliberately says nothing about an empty ``voices``: "no ``--voice-dir``
    was given" is a legitimate mode and the caller is the only one that can
    tell it apart from "the directory was given and is unusable" — which is
    exactly the distinction ``load_voice_files`` cannot make, since a glob over
    a missing directory yields the same ``{}`` as no flag at all.

    Returns ``[]`` when every narrator resolves. Order follows ``narrators``,
    de-duplicated, so a plan that gives one character four scenes reports the
    problem once.
    """
    problems: list[str] = []
    seen: set[str] = set()
    for narrator in narrators:
        key_of = narrator.strip().lower()
        if not key_of or key_of in seen:
            continue
        seen.add(key_of)
        key, ambiguous = _resolve_voice_key(voices, narrator)
        if key is not None:
            continue
        firstname = _first_name(narrator)
        if ambiguous:
            candidates = sorted(
                k for k in voices
                if k.startswith(firstname) and len(k) > len(firstname)
                and k[len(firstname)] in "_-"
            )
            problems.append(
                f"narrator '{narrator}': ambiguous — {candidates} all match "
                f"'{firstname}'. Refusing to guess which one the render should "
                f"use; rename so only one begins with '{firstname}' + '_' or '-'."
            )
        else:
            problems.append(
                f"narrator '{narrator}': no voice file. Expected "
                f"'{firstname}.md', '{firstname}_voice.md' or "
                f"'{firstname}_<anything>.md'."
            )
    return problems


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
