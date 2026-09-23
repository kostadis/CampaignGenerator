"""The session export — the reviewer's input, and an interface (#455).

The review page is **not regenerated per session**. It is versioned once, saved
to a phone, and fed a JSON document. That inverts the workflow that produced the
31 accepted rulings, where each review meant publishing a new page — and it makes
this schema an interface, because the page and the data now drift independently.

Hence :data:`EXPORT_VERSION`, checked on **both** sides:
``tests/test_reviewer_selfcontained.py`` asserts the number the page declares
equals the one here. That test exists precisely *because* the page is no longer
regenerated; without it the two would diverge silently and the first symptom
would be a scene that renders wrong on a train.

Shape follows ``campaignlib/transcript_corrections.py``: strict, versioned, and
refusing an unknown version rather than ignoring it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

#: Bumped when the export's shape changes in a way an older page cannot render.
#: The page refuses a version it does not know rather than rendering a partial
#: scene, which is the failure a GM would not notice until the rulings were
#: already wrong.
EXPORT_VERSION = 1


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExportBlock(_Strict):
    """One block, carrying **the id the authored record will use** (FR-018).

    Not a display concern. If the export and the record numbered blocks
    differently, a review could not be reconciled with the draft it was made
    against, and the mismatch would surface as prose landing in the wrong place.
    """

    id: str
    kind: str
    anchor: str
    text: str

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        if v not in ("prose", "gap"):
            raise ValueError(f"block kind must be 'prose' or 'gap', not {v!r}")
        return v


class SourceTurn(_Strict):
    """One GM turn from the scene's extraction.

    What the reviewer's foot table renders, so a gap is ruled **against the
    source** rather than from memory — the single most useful thing about the
    page the GM actually used.
    """

    line: int
    label: str
    note: str = ""
    quote: str = ""


class SceneExport(_Strict):
    """One scene, ready to paste into the reviewer.

    One scene per file by default: 14–26 KB each on the corpus against 82 KB for
    a whole session, and 82 KB is not something to paste on a touch keyboard
    (research D9).
    """

    version: int = EXPORT_VERSION
    narration: str
    generated_sha256: str
    session: str = ""
    scene_index: int
    scene_name: str
    narrator: str
    word_count: int
    gap_count: int
    gm_turn_count: int
    blocks: list[ExportBlock]
    source_gm_turns: list[SourceTurn] = []

    @field_validator("version")
    @classmethod
    def _known_version(cls, v: int) -> int:
        if v != EXPORT_VERSION:
            raise ValueError(
                f"unknown export version {v!r}; this build writes and understands "
                f"version {EXPORT_VERSION}"
            )
        return v
