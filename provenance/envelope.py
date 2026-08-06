"""The provenance envelope, its assembly, and the deterministic ranking.

The envelope is the feature. A hit without one is a line of text a reader has no
way to weigh; a hit with one says *whose game this is, how much to trust it,
whether a pipeline will overwrite it next Tuesday, which chapter it reflects,
and what the GM has already recorded as wrong about it* — without opening the
file (SC-008).

## Every field is always present

A field with nothing to say carries ``null`` **plus its status field**, never an
omitted key (SC-001). An absent key reads as "not applicable"; a null next to a
status reads as "asked, and the answer is none." Those are different claims, and
only one of them is true. ``ENVELOPE_FIELDS`` is the checked contract.

## Nothing here infers

Tier comes from hand-authored globs, ``generated_by`` from a hand-authored
declaration, ``chapter`` from a hand-authored filename regex, corrections from a
hand-authored record. There is no directory-name heuristic and no pass over file
*contents* — a regex over a file body would be inference and would violate
FR-029. The boundary is the file, and it is not negotiable (research D14).

## The ranking tail is load-bearing

``(-relevance, tier_ordinal, campaign, path, line)``. The last three are not
cosmetic: rg is multithreaded and its file order is **not stable between runs**,
and the Python fallback's ``os.walk`` order is stable but different again. SC-009
requires identical results on rebuild, and a *total* order is what makes
"identical" a checkable claim across both scanners and both machines. Do not
simplify this key having noticed that results already look sorted — the parity
test fails immediately without it (research D9, D18).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from .corrections import Correction, CorrectionsStatus
from .tiers import TrustTier, classify

#: The complete key set of a serialised hit. Asserted structurally by
#: ``tests/test_provenance_search.py`` — SC-001 is a statement about this set,
#: not about any one field being right.
ENVELOPE_FIELDS: frozenset[str] = frozenset(
    {
        "campaign",
        "path",
        "line",
        "excerpt",
        "excerpt_encoding",
        "context_before",
        "context_after",
        "tier",
        "tier_ambiguous",
        "generated_by",
        "generated_but_hand_edited",
        "chapter",
        "provenance_range",
        "corrections",
        "corrections_status",
        "matched_surface_form",
        "relevance",
        "horizon_disposition",
    }
)

#: A hit under an active horizon is one of these. ``None`` means no horizon was
#: requested — distinct from "requested, and this file could not be attributed."
INCLUDED = "included"
UNATTRIBUTABLE = "unattributable"


@dataclass(frozen=True)
class ProvenanceEnvelope:
    """One labeled hit. See ``ENVELOPE_FIELDS`` for the serialised contract."""

    campaign: str
    path: str
    line: int
    excerpt: str
    excerpt_encoding: str
    context_before: tuple[str, ...]
    context_after: tuple[str, ...]
    tier: TrustTier
    tier_ambiguous: tuple[TrustTier, ...]
    generated_by: str | None
    generated_but_hand_edited: bool
    chapter: int | None
    provenance_range: str | None
    corrections: tuple[Correction, ...] | None
    corrections_status: CorrectionsStatus
    matched_surface_form: str
    relevance: float
    horizon_disposition: str | None = None

    @property
    def sort_key(self) -> tuple:
        """Total order. The tail is doing real work — see the module docstring."""
        return (-self.relevance, self.tier.ordinal, self.campaign, self.path, self.line)

    @property
    def dedup_key(self) -> tuple[str, str, int]:
        """Identity of a hit across alias expansions (FR-019)."""
        return (self.campaign, self.path, self.line)

    def as_dict(self) -> dict:
        return {
            "campaign": self.campaign,
            "path": self.path,
            "line": self.line,
            "excerpt": self.excerpt,
            "excerpt_encoding": self.excerpt_encoding,
            "context_before": list(self.context_before),
            "context_after": list(self.context_after),
            "tier": self.tier.value,
            "tier_ambiguous": [t.value for t in self.tier_ambiguous],
            "generated_by": self.generated_by,
            "generated_but_hand_edited": self.generated_but_hand_edited,
            "chapter": self.chapter,
            "provenance_range": self.provenance_range,
            "corrections": (
                None
                if self.corrections is None
                else [c.model_dump(mode="json") for c in self.corrections]
            ),
            "corrections_status": self.corrections_status.value,
            "matched_surface_form": self.matched_surface_form,
            "relevance": self.relevance,
            "horizon_disposition": self.horizon_disposition,
        }


# ── chapter attribution (FR-002, research D14) ───────────────────────────────


def chapter_for(campaign, rel_path: str) -> int | None:
    """The chapter a file reflects, read from the manifest's filename pattern.

    ``None`` when the campaign declares no horizon marker, or when the pattern
    cannot attribute this path. Never guessed, and never read out of the file's
    contents — obelisk needs ``session_(\\d+)_`` where the others need
    ``chapter_(\\d+)_``, which is exactly why the pattern is per-campaign and
    hand-authored (research D2, D14).
    """
    horizon = getattr(campaign, "horizon", None)
    if horizon is None:
        return None
    found = horizon.compiled().search(rel_path)
    if not found:
        return None
    try:
        return int(found.group(1))
    except (TypeError, ValueError):
        # A capture group that is not a number is an authoring problem, and
        # `provenance check` reports it. A query is not the place to raise.
        return None


# ── relevance (research D9) ──────────────────────────────────────────────────

WHOLE_WORD_BONUS = 2.0
HEADING_BONUS = 1.5
BASENAME_BONUS = 1.0


def relevance_for(
    query: str, rel_path: str, line_text: str, match_count: int, *, regex: bool = False
) -> float:
    """Deterministic, disk-only, no model in the loop (FR-033).

    The whole-word bonus is skipped for regex queries: ``\\bfoo|bar\\b`` does not
    mean what wrapping the whole pattern in word boundaries would make it mean,
    and a scoring rule that silently rewrites the caller's pattern is worse than
    one that declines to fire.
    """
    score = float(match_count)
    if not regex and re.search(rf"\b{re.escape(query)}\b", line_text, re.IGNORECASE):
        score += WHOLE_WORD_BONUS
    if line_text.lstrip().startswith("#"):
        score += HEADING_BONUS
    basename = rel_path.rsplit("/", 1)[-1]
    if query.casefold() in basename.casefold():
        score += BASENAME_BONUS
    return score


# ── assembly ─────────────────────────────────────────────────────────────────


def build_envelope(
    campaign,
    rel_path: str,
    line: int,
    excerpt,
    *,
    query: str,
    matched_surface_form: str,
    match_count: int,
    lookup,
    regex: bool = False,
    horizon_disposition: str | None = None,
    relevance: float | None = None,
) -> ProvenanceEnvelope:
    """Assemble one hit's labels from the manifest and the corrections record.

    ``lookup`` is a ``CorrectionsLookup`` — status *and* payload, because
    "no corrections apply here" and "this campaign's corrections file would not
    parse" must never look the same to a caller (FR-005).

    ``relevance`` may be passed in when the caller already scored this hit
    during ranking. Passing the score through rather than recomputing it is not
    an optimisation detail: a hit must not be able to rank at one score and
    report another.
    """
    result = classify(rel_path, campaign.tiers)
    generated_by = campaign.generated_by(rel_path)
    applicable = lookup.apply(rel_path, query, excerpt.text)
    chapter = chapter_for(campaign, rel_path)

    corrections: tuple[Correction, ...] | None
    if lookup.status is CorrectionsStatus.CONSULTED:
        corrections = tuple(applicable)
    else:
        # NO_RECORD and NOT_CONSULTED both carry null, and the status tells them
        # apart. An empty list here would assert "consulted, none apply".
        corrections = None

    return ProvenanceEnvelope(
        campaign=campaign.name,
        path=rel_path,
        line=line,
        excerpt=excerpt.text,
        excerpt_encoding=excerpt.encoding,
        context_before=excerpt.before,
        context_after=excerpt.after,
        tier=result.tier,
        tier_ambiguous=result.ambiguous,
        generated_by=generated_by,
        # A generated file the GM has recorded a correction against has been
        # contradicted by hand; the next pipeline run destroys that contradiction.
        # It is a warning, not a reason to re-tier the file (data-model.md §4).
        generated_but_hand_edited=bool(generated_by and applicable),
        chapter=chapter,
        provenance_range=campaign.range_for(chapter),
        corrections=corrections,
        corrections_status=lookup.status,
        matched_surface_form=matched_surface_form,
        relevance=(
            relevance
            if relevance is not None
            else relevance_for(query, rel_path, excerpt.text, match_count, regex=regex)
        ),
        horizon_disposition=horizon_disposition,
    )


def rank(envelopes: Sequence[ProvenanceEnvelope]) -> list[ProvenanceEnvelope]:
    """One canonical order, whichever scanner produced the input."""
    return sorted(envelopes, key=lambda e: e.sort_key)


def dedupe_by_position(
    envelopes: Sequence[ProvenanceEnvelope],
) -> list[ProvenanceEnvelope]:
    """Collapse alias-expanded duplicates, keeping the **longest** matched form.

    A hit found by both "Marnix" and "Marnix Vale" is one hit. Labeling it with
    the longer form names the most specific match rather than a coincidental
    short one (FR-019, data-model.md §8).
    """
    best: dict[tuple[str, str, int], ProvenanceEnvelope] = {}
    for envelope in envelopes:
        current = best.get(envelope.dedup_key)
        if current is None or len(envelope.matched_surface_form) > len(
            current.matched_surface_form
        ):
            best[envelope.dedup_key] = envelope
    return list(best.values())
