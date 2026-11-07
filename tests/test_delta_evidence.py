"""Spec 039 T012: FullEvidence / SparseEvidence (R2, N2, FR-005)."""

import pytest

from pipelines.summary_native import npc_verify
from pipelines.summary_native.delta.evidence import (
    EvidenceIndex, EvidenceKindError, EvidenceSpan, FullEvidence, SparseEvidence, require_full,
)

CORPUS = npc_verify.CorpusIndex(frozenset({1, 2}), frozenset({"001.01", "002.01"}))


def span(ch, kind, id_, origin="new", text="Jimjar kept watch.", sha="a" * 64):
    return EvidenceSpan(ch, kind, id_, text, f"summaries/{ch:03d}.md", sha, origin)


def ctx(index, draft="A deep gnome. [ch 001 / entry]\n"):
    # Real verifier context; the citation check reads only corpus_index.targets from the index.
    c = npc_verify.build_context("## Identity\n\n" + draft, "", CORPUS, "", [])
    return npc_verify.VerificationContext(**{**c.__dict__, "corpus_index": index})


def test_full_delegates_unchanged():
    f = FullEvidence(CORPUS)
    assert f.kind == "full" and f.targets == CORPUS.targets
    assert isinstance(f, EvidenceIndex)
    require_full(f)


def test_sparse_targets_are_exactly_the_spans():
    s = SparseEvidence([span(1, "scene", "001.01")])
    assert s.kind == "sparse" and s.targets == {(1, "001.01")}
    assert (1, "entry") not in s.targets and (1, "moment") not in s.targets
    assert isinstance(s, EvidenceIndex)


def test_inherited_new_digests_and_scopes():
    s = SparseEvidence(
        [span(1, "entry", "entry", "inherited", sha="b" * 64), span(2, "scene", "002.01", "new")],
        missing_scope=["ch 003"], unexamined_scope=["ch 004"],
    )
    assert s.inherited_targets == {(1, "entry")} and s.new_targets == {(2, "002.01")}
    assert s.digests == {"summaries/001.md": "b" * 64, "summaries/002.md": "a" * 64}
    assert s.missing_scope == ("ch 003",) and s.unexamined_scope == ("ch 004",)
    assert s.text_for(2, "002.01") == "Jimjar kept watch." and s.text_for(1, "moment") is None


def test_sparse_never_passes_as_full():
    with pytest.raises(EvidenceKindError):
        require_full(SparseEvidence([]))
    assert SparseEvidence([]).kind == "sparse"


@pytest.mark.parametrize("bad", [
    dict(kind="entry", id_="001.01"), dict(kind="bogus", id_="x"), dict(kind="scene", id_=""),
    dict(kind="scene", id_="001.01", text="  "), dict(kind="scene", id_="001.01", sha=""),
])
def test_bad_spans_refused(bad):
    with pytest.raises(EvidenceKindError):
        span(1, bad["kind"], bad["id_"], text=bad.get("text", "x"), sha=bad.get("sha", "a" * 64))


def test_entry_citation_passes_full_fails_sparse_without_entry_span():
    # [ch 001 / entry] is in the evidence dossier's targets only if the NPC evidence has it;
    # isolate the corpus-membership half: INVALID means "not in the in-range corpus".
    full = npc_verify.check_citations(ctx(FullEvidence(CORPUS)))
    assert not [f for f in full.failures if f.code == npc_verify.INVALID]
    sparse = npc_verify.check_citations(ctx(SparseEvidence([span(1, "scene", "001.01")])))
    assert [f.code for f in sparse.failures] == [npc_verify.INVALID]
    with_entry = npc_verify.check_citations(
        ctx(SparseEvidence([span(1, "scene", "001.01"), span(1, "entry", "entry")])))
    assert not [f for f in with_entry.failures if f.code == npc_verify.INVALID]
