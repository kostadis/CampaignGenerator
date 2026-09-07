#!/usr/bin/env python3
"""The provenance apparatus a pipeline pass writes INTO a scene file.

An apparatus comment records what a pass did and why. It is the GM's audit
trail, it belongs in the per-scene file, and it is not part of the assembled
document — the assembled doc feeds the release append and the chapter split, so
anything left in it travels into the bible.

A comment that matches none of these markers is the GM's own note and SURVIVES
assembly untouched. That distinction is deliberate and covered by
``tests/test_assemble_audit_comment.py::test_unrelated_html_comment_survives``.

**Why this module exists rather than a constant in ``assemble.py``.** Two
stages need the registry, and Stage 3 importing Stage 4 is backwards.
``assemble`` (Stage 4) strips the markers from the assembled document;
``sd_narrate`` (Stage 3) must skip a trailing one when it takes the prose
handoff into the next scene, and must mask them before the unknown-name scan —
the comment quotes raw table speech verbatim, so an unmasked scan reports the
words the pass just removed from the fiction (#396).

**Every marker declares who produces it.** `26ec5b0` deleted the prompt that
emitted ``table-speech reclassified:`` while leaving this stripper, its tests
and three out-of-repo review skills in place; nothing failed, because nothing
tied a marker to a producer. ``origin`` and ``produced_by`` are what
``tests/test_apparatus_marker_pairing.py`` checks, so the same deletion now
breaks the build.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ApparatusMarker:
    """One recognised provenance comment, and where it comes from.

    ``pattern`` is a regex fragment matched immediately after ``<!--``.
    ``origin`` is ``"narrate-prompt"`` when a template in this repo asks the
    model for it — those are enforced to have a live producer — or
    ``"external"`` when a human or an out-of-repo skill writes it, which this
    repo cannot check and does not pretend to.
    """

    pattern: str
    origin: str
    produced_by: str


APPARATUS_MARKERS: tuple[ApparatusMarker, ...] = (
    ApparatusMarker(
        r"table-speech\s+reclassified:",
        "narrate-prompt",
        "config/agents/session_doc/narrate/audit_hatch.md",
    ),
    ApparatusMarker(
        r"hand-fixed",
        "external",
        "a human's manual post-narration repair pass",
    ),
    ApparatusMarker(
        r"Editorial\s+note:",
        "external",
        "the /voice-smooth skill, out of repo — a per-quote ruling carried down",
    ),
    ApparatusMarker(
        r"Scene\s+boundary\s+note:",
        "external",
        "the /voice-smooth skill, out of repo — a de-duplication ruling",
    ),
)

AUDIT_COMMENT_RE = re.compile(
    r"[ \t]*<!--\s*(?:" + "|".join(m.pattern for m in APPARATUS_MARKERS) + r").*?-->[ \t]*\n?",
    re.DOTALL | re.IGNORECASE,
)


def strip_audit_comments(body: str) -> str:
    """Remove pipeline provenance comments from a scene body.

    Strips only comments whose opening text matches a known apparatus marker.
    A hand-written comment the GM added themselves is left alone.
    """
    return AUDIT_COMMENT_RE.sub("", body)
