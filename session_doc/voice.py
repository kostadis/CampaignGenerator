"""Voice-file loading and per-narrator lookups for session_doc and the sd_* CLIs.

**A character's voice file is declared, not matched** (feature 009). The roster
entry names it — ``voice: voice/gyrgum_voice.md`` — and resolution is following
that path.

What this replaced was a three-step rule: exact name, else first name, else the
unique key beginning with the first name plus ``_`` or ``-``. That rule is a
similarity-based identity assertion, which ``provenance/identity.py`` forbids
everywhere else in this codebase ("``Vera`` does not resolve to ``Veyra``
because they look alike"). It failed exactly as you would expect: a character
renamed ``Grygum`` -> ``Gyrgum`` kept resolving to nothing, every render since
went out with no register rules and no banned-tic list for that narrator, and
the only signal was a warning in a long log (campaigns#175, #247). A path
cannot fail that way — it is either there or it is named in a refusal.

:func:`load_voice_files` survives the change and is deliberately unchanged. It
scans a directory and keys by file stem, which is now used for exactly one
thing: finding files that **nothing declares**, so an orphan left behind by a
rename is visible instead of silently inert.
"""

import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from campaignlib.party_config import ResolvedPartyConfig


def load_voice_files(voice_dir: Path) -> dict[str, str]:
    """Load every voice file in a directory, keyed by lowercased file stem.

    **Not** how a narrator finds its voice spec — that is
    :func:`load_declared_voices`. This is the directory census the orphan
    report is computed against: a file here that no character's ``voice:``
    entry names is reaching nobody, which is the state a rename produces.

    Files whose name starts with ``_`` are skipped — they are shared campaign
    material (``_genre.md``), not a per-character voice file.
    """
    voices: dict[str, str] = {}
    for f in voice_dir.glob("*.md"):
        if f.name.startswith("_"):
            continue
        stem = f.stem.lower()
        key = stem.removesuffix("_voice")
        voices[key] = f.read_text(encoding="utf-8").strip()
    return voices


def load_declared_voices(cfg: "ResolvedPartyConfig") -> dict[str, str]:
    """Character name (lowercased) -> voice text, from the roster's declarations.

    Only characters that declare a ``voice:`` path **and** whose file exists
    contribute. A character that declares nothing has no voice spec, and that
    is a statement rather than an accident; a character that declares a file
    which is absent is a refusal, reported by
    :func:`voice_declaration_problems` before any tokens are spent.
    """
    voices: dict[str, str] = {}
    for character in cfg.characters:
        path = character.voice
        if path is not None and path.exists():
            voices[character.name.strip().lower()] = path.read_text(
                encoding="utf-8"
            ).strip()
    return voices


def get_voice_note(voices: dict[str, str], narrator: str) -> str | None:
    """The voice spec for ``narrator``, or ``None``.

    Exact match on the character name, case- and whitespace-insensitive.
    Nothing here computes a distance or a prefix in order to assert that two
    names are the same character.

    Returns ``None`` silently. Every miss that matters has already been
    reported by :func:`voice_declaration_problems`, which runs before the first
    API call; warning again per-scene, mid-render, was the #247 shape — a
    signal that arrives after the tokens are spent.
    """
    return voices.get(narrator.strip().lower())


def voice_declaration_problems(
    cfg: "ResolvedPartyConfig", narrators: list[str]
) -> list[str]:
    """One problem line per narrator that has no usable voice spec.

    The pre-flight behind ``sd_narrate``'s refusal (#300), rewritten for
    declarations. It answers the question for every narrator in the plan
    **before** the first API call, so a render either has all its specs or does
    not start — rather than discovering the gap in scene 7's output.

    Two failures, each named: the character declares no ``voice:`` file, or it
    declares one and the file is not there. A narrator the roster does not have
    at all is :func:`unknown_narrators`'s to report — that is a disagreement
    between the plan and the roster rather than a missing spec, and it is worth
    saying once however many kinds of file are declared.

    Returns ``[]`` when every narrator resolves. Order follows ``narrators``,
    de-duplicated, so a plan that gives one character four scenes reports the
    problem once.
    """
    by_name = {c.name.strip().lower(): c for c in cfg.characters}
    problems: list[str] = []
    seen: set[str] = set()
    for narrator in narrators:
        key = narrator.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        character = by_name.get(key)
        if character is None:
            continue          # unknown_narrators says it, once
        if character.voice is None:
            problems.append(
                f"narrator {narrator!r}: declares no voice file. Add a "
                f"'voice:' entry to its party.yaml roster entry."
            )
            continue
        if not character.voice.exists():
            problems.append(
                f"narrator {narrator!r}: declared voice file does not exist — "
                f"{character.voice}"
            )
    return problems


def unknown_narrators(
    cfg: "ResolvedPartyConfig", narrators: list[str]
) -> list[str]:
    """Narrators the roster does not have, one line each.

    A plan and a roster that disagree about a name is the drift a rename
    creates, and it is the finding — not something to paper over by matching
    the name approximately, which is how ``Gyrgum`` ended up resolving to
    nothing in silence.

    Separate from :func:`voice_declaration_problems` so it is reported once
    whether the campaign declares voice files, example files, or both.
    """
    known = {c.name.strip().lower() for c in cfg.characters}
    problems: list[str] = []
    seen: set[str] = set()
    for narrator in narrators:
        key = narrator.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        if key not in known:
            problems.append(
                f"narrator {narrator!r}: not a character in party.yaml "
                f"(it has {sorted(c.name for c in cfg.characters)}). The plan "
                f"and the roster disagree about this name."
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
