"""Evidence indexes for the verifier (spec 039 R2, N2, FR-005).

``npc_verify.CorpusIndex.targets`` invents ``(chapter, "entry")`` and ``(chapter, "moment")``
for every in-range chapter. That is right for a full run and wrong for a sparse one: a
``[ch 075 / entry]`` citation would pass although no entry span was ever supplied.

* ``FullEvidence`` wraps a ``CorpusIndex`` and delegates unchanged, so full-mode verifier
  output is identical.
* ``SparseEvidence`` is built from an explicit span list; ``targets`` is exactly those spans.
  Chapter membership never creates a target.

``EvidenceIndex`` is the interface ``npc_verify`` consumes from a corpus index: ``targets``
(the only member any consumer reads today) plus ``kind``. Sparse can never present as full:
``kind`` is a fixed ``"sparse"`` and ``require_full`` refuses it.

No model call, no I/O (Principle V).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

SPAN_KINDS = ("scene", "entry", "moment")
ORIGINS = ("inherited", "new")


class EvidenceKindError(ValueError):
    """A sparse evidence index was supplied where full evidence is required (or a bad span)."""


@runtime_checkable
class EvidenceIndex(Protocol):
    """What the verifier needs from a corpus index."""

    kind: Literal["full", "sparse"]

    @property
    def targets(self) -> frozenset[tuple[int, str]]: ...


@dataclass(frozen=True)
class EvidenceSpan:
    chapter: int
    kind: Literal["scene", "entry", "moment"]
    id: str  # a scene id for kind "scene"; "entry"/"moment" otherwise
    span: str  # the supporting text itself; empty text is not support
    source_path: str
    source_sha256: str
    origin: Literal["inherited", "new"]

    def __post_init__(self) -> None:
        if self.kind not in SPAN_KINDS:
            raise EvidenceKindError(f"unknown span kind {self.kind!r}")
        if self.origin not in ORIGINS:
            raise EvidenceKindError(f"unknown span origin {self.origin!r}")
        if self.kind != "scene" and self.id != self.kind:
            raise EvidenceKindError(f"a {self.kind} span's id must be {self.kind!r}, got {self.id!r}")
        if self.kind == "scene" and not self.id:
            raise EvidenceKindError("a scene span needs a scene id")
        if not self.span.strip():
            raise EvidenceKindError(f"span ch {self.chapter} / {self.id} has no bound text")
        if not self.source_sha256:
            raise EvidenceKindError(f"span ch {self.chapter} / {self.id} has no source digest")

    @property
    def target(self) -> tuple[int, str]:
        return (self.chapter, self.id)


class FullEvidence:
    """Delegates to a ``CorpusIndex`` unchanged."""

    kind: Literal["full"] = "full"

    def __init__(self, corpus_index) -> None:
        self.corpus_index = corpus_index

    @property
    def targets(self) -> frozenset[tuple[int, str]]:
        return self.corpus_index.targets

    @property
    def chapters(self):
        return self.corpus_index.chapters

    @property
    def scenes(self):
        return self.corpus_index.scenes


@dataclass(frozen=True)
class SparseEvidence:
    """Exactly the supplied spans; nothing is derived from chapter membership."""

    spans: tuple[EvidenceSpan, ...]
    missing_scope: tuple[str, ...] = field(default=())  # required support absent: blocks
    unexamined_scope: tuple[str, ...] = field(default=())  # not examined: disclosed only
    kind: Literal["sparse"] = field(default="sparse", init=False)

    def __init__(self, spans, missing_scope=(), unexamined_scope=()) -> None:
        object.__setattr__(self, "spans", tuple(spans))
        object.__setattr__(self, "missing_scope", tuple(missing_scope))
        object.__setattr__(self, "unexamined_scope", tuple(unexamined_scope))
        object.__setattr__(self, "kind", "sparse")

    @property
    def targets(self) -> frozenset[tuple[int, str]]:
        return frozenset(s.target for s in self.spans)

    @property
    def inherited_targets(self) -> frozenset[tuple[int, str]]:
        return frozenset(s.target for s in self.spans if s.origin == "inherited")

    @property
    def new_targets(self) -> frozenset[tuple[int, str]]:
        return frozenset(s.target for s in self.spans if s.origin == "new")

    @property
    def digests(self) -> dict[str, str]:
        """source_path -> sha256, per artifact."""
        return {s.source_path: s.source_sha256 for s in self.spans}

    def text_for(self, chapter: int, id: str) -> str | None:
        """Supplied span text for a target; ``None`` when no span was supplied."""
        parts = [s.span for s in self.spans if s.target == (chapter, id)]
        return "\n".join(parts) if parts else None


def require_full(index) -> None:
    """Refuse a sparse (or unlabelled) index where a full corpus is required."""
    if getattr(index, "kind", None) != "full":
        raise EvidenceKindError(
            f"full evidence required, got {getattr(index, 'kind', type(index).__name__)!r}: "
            "a sparse index cannot stand in for the whole corpus"
        )
