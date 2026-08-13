"""Per-character example file routing for session_doc and the sd_* CLIs."""

from pathlib import Path


def _first_name(narrator: str) -> str:
    """First token of a narrator name, lowercased.

    Mirrors ``voice._first_name`` including its empty-input guard. That guard
    is the whole point here: ``parse_plan`` accepts a bare ``narrator:`` line as
    ``""`` and only tests ``if "narrator" in section``, so an empty narrator
    reaches Pass 5 — and ``narrator.lower().split()[0]`` raised ``IndexError``
    on it, taking the render down with a stack trace instead of a message
    (#301). ``voice.py`` had this guard; this module was the copy without it.
    """
    parts = narrator.lower().strip().split()
    return parts[0] if parts else narrator.lower().strip()


def routes_to(stem: str, first_name: str) -> bool:
    """Whether an examples file ``stem`` belongs to the character ``first_name``.

    The single authority for the rule, so ``_load_examples`` (which routes) and
    ``examples_routing_problems`` (which detects a file that *should* have
    routed) can never disagree about it.
    """
    if not first_name:
        return False
    return (stem == first_name
            or stem.startswith(first_name + "_")
            or stem.startswith(first_name + "-"))


def example_files(examples_dir: Path) -> list[Path]:
    """Style-example files in ``examples_dir``, `_`-prefixed ones excluded.

    A `_`-prefixed file is shared campaign material (``_genre.md``); it is not
    a style example and must not join the global block, where it would reach
    every narrator.
    """
    return [f for f in sorted(examples_dir.glob("*.md"))
            if not f.name.startswith("_")]


def examples_routing_problems(examples_dir: Path | None,
                              characters: list[str],
                              narrators: list[str]) -> list[str]:
    """Example files that will reach every narrator but were written for one.

    The #301 bleed: ``_load_examples`` routes a file to a character only when
    its stem matches a name in ``--characters``. With an empty or incomplete
    roster the routing loop matches nothing, every file falls through to the
    GLOBAL block, and the global block is passed to *every* narrator's prompt —
    so Vukradin's style reference silently steers Soma's narration. The output
    still looks right, which is why this needs detecting rather than warning.

    Deliberately keyed off the **plan's narrators**, not off the file names
    alone. A campaign whose examples are all house style — toee's
    ``combat_and_consequences.md``, ``political_maneuvering.md`` — is not
    misconfigured, and a rule that fired on "roster empty + any examples
    present" would refuse it. A file is only a problem when it would have
    routed to somebody actually narrating this render.

    Returns ``[]`` when nothing is mis-routed.
    """
    if examples_dir is None or not examples_dir.is_dir():
        return []
    char_firsts = {_first_name(c) for c in characters if c.strip()}
    narrator_firsts: dict[str, str] = {}
    for n in narrators:
        first = _first_name(n)
        if first:
            narrator_firsts.setdefault(first, n)

    problems: list[str] = []
    for f in example_files(examples_dir):
        stem = f.stem.lower()
        if any(routes_to(stem, first) for first in char_firsts):
            continue                     # already routed per-character
        for first, narrator in narrator_firsts.items():
            if routes_to(stem, first):
                problems.append(
                    f"{f.name} would route to narrator '{narrator}' but is "
                    f"reaching EVERY narrator instead — '{narrator}' is not in "
                    f"--characters."
                )
                break
    return problems


def get_char_examples(per_char_examples: dict[str, str], narrator: str) -> str | None:
    """Look up per-character style examples by case-insensitive first-name match."""
    key = _first_name(narrator)
    if not key:
        return None
    return per_char_examples.get(key) or per_char_examples.get(narrator.lower())
