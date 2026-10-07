"""Two names per NPC (spec 032 research R6): the corpus stem and the published slug.

``<stem>`` is the 031 corpus dossier stem (``npc_<slug>``, hash suffix on collision),
used inside generated range folders. ``<slug>`` is the lowercase hyphenated canonical
name (``ilvara-mizzrym``), used for everything under ``docs/npcs/`` and ``authored/``.
Both are computed from the registry canonical name; a slug collision is reported,
never resolved silently.

No model call (guarded by ``tests/test_summary_native_no_llm.py``).
"""

from __future__ import annotations

import re

from pipelines.summary_native import corpus

_NON_ALNUM_RE = re.compile(r"[\W_]+")
#: Used when a canonical name has no alphanumeric character at all; the same fallback
#: the corpus stem uses, so an empty slug can never name a file.
UNNAMED = "unnamed"


def slug_for(canonical: str) -> str:
    """Lowercase; every run of non-alphanumerics becomes ``-``; leading/trailing ``-`` stripped."""
    return _NON_ALNUM_RE.sub("-", canonical.casefold()).strip("-") or UNNAMED


def stem_for(category: str, canonical: str) -> str:
    """The corpus stem for one subject, with ``corpus.dossier_filenames`` semantics.

    A stem that collides with another subject's gets a hash suffix; that needs the
    whole set, so use ``stems_for`` when more than one subject is in play.
    """
    return stems_for([(category, canonical)])[(category, canonical)]


def stems_for(subjects: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """``{(category, canonical): stem}`` for a set of subjects, collision suffixes included."""
    ordered = sorted(set(subjects), key=lambda cs: (cs[0], cs[1].casefold(), cs[1]))
    names = corpus.dossier_filenames([(cat, subj, []) for cat, subj in ordered])
    return {cs: name.removesuffix(".md") for cs, name in zip(ordered, names)}


def slug_collisions(canonicals) -> dict[str, list[str]]:
    """``{slug: [canonical, ...]}`` for every slug two or more distinct names share (sorted)."""
    by_slug: dict[str, set[str]] = {}
    for c in canonicals:
        by_slug.setdefault(slug_for(c), set()).add(c)
    return {slug: sorted(names) for slug, names in sorted(by_slug.items()) if len(names) > 1}
