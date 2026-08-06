"""Per-campaign corrections: models, loader, and the matching rule.

A correction is the GM's hand-authored record that a specific file is **known
stale**, what is actually true, and as of when. It is the mechanism by which a
generated document that has drifted from the table's truth stops being able to
mislead a reader — the correction rides along inside the hit's frame (FR-004),
not in a footer nobody reads.

## The matching rule is the load-bearing decision in this feature

A correction attaches when:

1. the hit's campaign-relative path matches a glob in ``applies_to.paths``, **and**
2. ``applies_to.subjects`` is empty, **or** a subject appears (case-insensitively)
   in the search query or in the hit's excerpt.

**``stale_claim`` is displayed to the reader and never used for matching.**

That is not a stylistic choice, it is empirical. Incident 1's stale text is
*already gone*: Phandalin's ``docs/world_state.md`` was regenerated between the
spec being written and 2026-08-05, and now says the Woodland Manse was cleared.
Text-matching would have made that correction **silently stop applying** at the
moment the file changed — which is exactly the silent-degradation class this
feature exists to kill. The symmetric hazard closes too: text-matching would let
a correction silently *start* applying to a paraphrase it was never written for.
Path-and-subject matching keeps a correction attached until a human prunes it
(research D12).

## An unreproducible correction is a question, not a fact

``verified: false`` exists because one of the five seed incidents could not be
reproduced on disk. Publishing it anyway would assert something unverified, so
the entry ships with the evidence in ``note``, ``provenance check`` reports it as
a finding so it cannot be quietly forgotten, and an annotated hit is labeled
unsettled rather than presented as settled (data-model.md section 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from .manifest import _StrictLoader, _render
from .tiers import matches_any


class CorrectionsError(Exception):
    """A corrections record could not be loaded. Maps to CLI exit code 3."""


class CorrectionsStatus(str, Enum):
    """Three enum values spanning four distinguishable states (FR-005).

    The fourth state is the split within ``CONSULTED``: a loaded record with
    matches, and a loaded record with none. A two-state design (empty list vs.
    absent field) cannot express all four, which is precisely what FR-005
    demands — "no corrections recorded for this campaign" and "corrections
    exist, none apply here" and "the record was unreadable" are three different
    answers, and collapsing any two of them tells the reader something false.
    """

    CONSULTED = "consulted"
    NO_RECORD = "no-record"
    NOT_CONSULTED = "not-consulted"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppliesTo(_Strict):
    paths: list[str]
    subjects: list[str] = []

    @field_validator("paths")
    @classmethod
    def _paths_non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("applies_to.paths must be non-empty")
        return v


class Correction(_Strict):
    id: str
    applies_to: AppliesTo
    stale_claim: str
    truth: str
    as_of: str | None = None
    recorded: date
    recorded_by: str = "GM"
    verified: bool = True
    note: str | None = None

    @field_validator("id")
    @classmethod
    def _id_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("id must be a non-empty slug")
        return v

    @field_validator("stale_claim", "truth")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must be non-empty")
        return v

    @field_validator("as_of", mode="before")
    @classmethod
    def _as_of_is_free_text(cls, v):
        # "chapter-43" or a date; YAML will have parsed a bare date into a
        # datetime.date, so normalise it back to a string rather than rejecting
        # a perfectly reasonable authoring.
        return None if v is None else str(v)

    def matches(self, rel_path: str, query: str = "", excerpt: str = "") -> bool:
        """Path-and-subject matching. ``stale_claim`` is never consulted here.

        Do not "improve" this by also matching ``stale_claim`` against the
        excerpt — see the module docstring and research D12. The text it
        describes is routinely regenerated away, and a correction that silently
        detaches when the file changes is worse than no correction at all.
        """
        if not matches_any(rel_path, self.applies_to.paths):
            return False
        if not self.applies_to.subjects:
            return True
        haystack = f"{query}\n{excerpt}".casefold()
        return any(s.casefold() in haystack for s in self.applies_to.subjects)


class CorrectionRecord(_Strict):
    version: int
    campaign: str
    corrections: list[Correction] = []

    @field_validator("version")
    @classmethod
    def _known_version(cls, v: int) -> int:
        if v != 1:
            raise ValueError(f"unknown corrections version {v!r}; this build understands version 1")
        return v

    @model_validator(mode="after")
    def _ids_unique(self) -> "CorrectionRecord":
        seen: set[str] = set()
        for c in self.corrections:
            if c.id in seen:
                raise ValueError(
                    f"duplicate correction id {c.id!r} — ids must be stable and unique "
                    f"so a GM can refer to one"
                )
            seen.add(c.id)
        return self

    @property
    def unverified(self) -> list[Correction]:
        return [c for c in self.corrections if not c.verified]


@dataclass(frozen=True)
class CorrectionsLookup:
    """The consultation outcome for one campaign — status plus payload.

    ``record`` is ``None`` for both NO_RECORD and NOT_CONSULTED; ``reason`` is
    set only for the latter. That asymmetry is the whole point: "this campaign
    declares no corrections file" and "this campaign declares one and it would
    not parse" must never look the same to a caller.
    """

    status: CorrectionsStatus
    record: CorrectionRecord | None = None
    reason: str | None = None

    def apply(self, rel_path: str, query: str = "", excerpt: str = "") -> list[Correction]:
        if self.record is None:
            return []
        return [c for c in self.record.corrections if c.matches(rel_path, query, excerpt)]


def load_corrections(path: str | Path, expected_campaign: str) -> CorrectionRecord:
    """Load and validate one corrections record. Raises ``CorrectionsError``."""
    path = Path(path)
    if not path.is_file():
        raise CorrectionsError(f"no corrections record at {path}")

    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictLoader)
    except yaml.YAMLError as exc:
        raise CorrectionsError(f"{path} is not valid YAML:\n  {exc}") from exc

    if raw is None:
        raise CorrectionsError(f"{path} is empty")
    if not isinstance(raw, dict):
        raise CorrectionsError(f"{path} must contain a mapping at the top level")

    try:
        record = CorrectionRecord.model_validate(raw)
    except ValidationError as exc:
        raise CorrectionsError(f"{path} failed validation:\n{_render(exc)}") from exc

    if record.campaign != expected_campaign:
        raise CorrectionsError(
            f"{path} declares campaign {record.campaign!r} but is registered under "
            f"{expected_campaign!r} in the manifest — one of the two is wrong, and "
            f"guessing which would attach another game's corrections to this one"
        )
    return record


def consult(campaign, campaign_root: Path) -> CorrectionsLookup:
    """Resolve a campaign's corrections into one of the four states.

    Never raises: an unreadable record degrades to NOT_CONSULTED with the reason
    attached, because a malformed corrections file in one campaign must not take
    down a search of another. A malformed *manifest* is different — that one is
    fatal, since it decides what gets searched at all.
    """
    declared = getattr(campaign, "corrections", None)
    if not declared:
        return CorrectionsLookup(CorrectionsStatus.NO_RECORD)

    path = campaign_root / declared
    try:
        record = load_corrections(path, campaign.name)
    except CorrectionsError as exc:
        return CorrectionsLookup(CorrectionsStatus.NOT_CONSULTED, reason=str(exc))
    return CorrectionsLookup(CorrectionsStatus.CONSULTED, record=record)
