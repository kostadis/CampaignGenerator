"""Per-character example-file resolution for session_doc and the sd_* CLIs.

**Declared, not routed** (feature 009). A character names its own examples file
in the roster (``examples: examples/gyrgum.md``), and material that belongs to
the whole campaign is listed in the roster's ``shared_examples:``. Those two
declarations are the only ways a file reaches a prompt.

What this replaced was a fall-through: a file whose stem matched a character's
first name went to that character, and **everything else joined a GLOBAL block
that was passed to every narrator**. That is how one character's style
reference silently steers all of them (#301), and it is not a hypothetical —
measured against the live campaigns, three of the five had a global block
nobody had chosen, the largest 51,073 characters wide. The detector added for
#301 could not see the worst case, because it keyed off the same first-name
rule that had already failed (#315). Both the rule and the detector are gone:
there is no fall-through left for a detector to detect.

A file that nothing declares is **unused**, not shared. ``players check``
reports it, which is what a rename now produces instead of a silent bleed.
"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from campaignlib.party_config import ResolvedPartyConfig


def example_files(examples_dir: Path) -> list[Path]:
    """Every example file in a directory, `_`-prefixed ones excluded.

    **Not** how a narrator finds its examples — that is
    :func:`load_declared_examples`. This is the directory census the orphan
    report is computed against.
    """
    return [f for f in sorted(examples_dir.glob("*.md"))
            if not f.name.startswith("_")]


def load_declared_examples(cfg: "ResolvedPartyConfig") -> dict[str, str]:
    """Character name (lowercased) -> example text, from the declarations.

    Only characters that declare an ``examples:`` path whose file exists
    contribute. A character that declares nothing gets no per-character
    examples — stated, not inferred from a filename that happens to look right.
    """
    per_char: dict[str, str] = {}
    for character in cfg.characters:
        path = character.examples
        if path is not None and path.exists():
            per_char[character.name.strip().lower()] = path.read_text(
                encoding="utf-8"
            ).strip()
    return per_char


def load_shared_examples(cfg: "ResolvedPartyConfig") -> str | None:
    """The campaign-wide example block, or ``None``.

    Built **only** from the roster's ``shared_examples:`` list. This block does
    reach every narrator — the difference from the rule it replaces is that a
    human wrote down that it should. toee's six house-style files and obelisk's
    ``house_style.md`` are the real cases, and they are legitimate; what was
    never legitimate was a file arriving here because it matched nobody.
    """
    parts = [
        p.read_text(encoding="utf-8").strip()
        for p in cfg.shared_examples
        if p.exists()
    ]
    return "\n\n---\n\n".join(parts) if parts else None


def examples_declaration_problems(
    cfg: "ResolvedPartyConfig", narrators: list[str]
) -> list[str]:
    """One problem line per declared example file that is not on disk.

    Deliberately narrower than its voice counterpart: a narrator with **no**
    examples is a normal configuration — toee gives every character its style
    through the shared block and nothing per-character — so silence about it is
    correct. A declared file that is missing is always a mistake.

    Order follows ``narrators``, de-duplicated; campaign-wide declarations are
    checked once at the end.
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
            # Reported by voice_declaration_problems, which runs first and says
            # it better. Repeating it here would double every message.
            continue
        if character.examples is not None and not character.examples.exists():
            problems.append(
                f"narrator {narrator!r}: declared examples file does not "
                f"exist — {character.examples}"
            )
    for path in cfg.shared_examples:
        if not path.exists():
            problems.append(f"shared_examples: file does not exist — {path}")
    return problems


def undeclared_files(directory: Path | None, declared: list[Path]) -> list[Path]:
    """Files present in ``directory`` that nothing in ``declared`` names.

    The orphan report. This is what a rename leaves behind — ``grygum.md``
    after the character became ``Gyrgum`` — and under the old rule it was
    invisible twice over: the file reached nobody, and the detector that
    existed to catch exactly this could not see it.

    Returns ``[]`` for a missing directory: "no directory" and "an empty
    directory" are both "nothing to orphan".
    """
    if directory is None or not directory.is_dir():
        return []
    claimed = {p.resolve() for p in declared if p is not None}
    return [f for f in example_files(directory) if f.resolve() not in claimed]


def get_char_examples(per_char_examples: dict[str, str], narrator: str) -> str | None:
    """The per-character examples for ``narrator``, or ``None``.

    Exact match on the character name, case- and whitespace-insensitive. No
    first-name fallback, no prefix rule: nothing here asserts that two names are
    the same character because they start the same way.
    """
    return per_char_examples.get(narrator.strip().lower())
