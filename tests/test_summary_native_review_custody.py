"""Unit tests for ``review/custody.py`` (spec 042 T003-T010): per-item source custody.

Pure computation over a real review built by ``tests/_custody_fixture.py``; simulated
changes use an override probe so nothing is written, and the few tests that need a real
byte change use the fixture's ``touch`` / ``restore``.
"""

from __future__ import annotations

import pytest

from pipelines.summary_native.review import custody
from pipelines.summary_native.review.custody import FileState, SourceRole
from pipelines.summary_native.review.models import SubjectReference
from pipelines.summary_native.review.store import ReviewStoreError
from tests import _custody_fixture as fixture

KIND = "npc_verification"


@pytest.fixture(scope="module")
def ro(tmp_path_factory):
    """One read-only fixture shared by every test that never writes a file."""
    return fixture.build(tmp_path_factory.mktemp("custody_ro"))


def _ctx(fx):
    _manifest, cust, items = fx.snapshot()
    return cust, list(items)


def _ids(cust, *paths):
    by_path = {s.path: s.source_id for s in cust.sources}
    return {by_path[p] for p in paths}


def _p(fx, path):
    return fx.rel(path)


def _probe(fx, **overrides):
    return custody.disk_probe(fx.root).with_overrides(overrides)


# ── T003: ReviewStoreError.detail ──────────────────────────────────────────

def test_store_error_detail_defaults_to_none_and_prefix_inference_holds():
    plain = ReviewStoreError("REVIEW_INVALID_BATCH: nope")
    assert plain.detail is None and plain.code == "REVIEW_INVALID_BATCH"
    assert ReviewStoreError("no prefix here").code == "REVIEW_INVALID"
    carried = ReviewStoreError("REVIEW_STALE_CUSTODY: x", "REVIEW_STALE_CUSTODY", detail={"k": 1})
    assert carried.detail == {"k": 1} and carried.code == "REVIEW_STALE_CUSTODY"
    keyword_only = ReviewStoreError("REVIEW_STALE_CUSTODY: x", detail={"k": 2})
    assert keyword_only.detail == {"k": 2} and keyword_only.code == "REVIEW_STALE_CUSTODY"


# ── role_of ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("source_id, role", [
    ("draft-0123456789abcdef", SourceRole.draft),
    ("evidence-0123456789abcdef", SourceRole.evidence),
    ("summary-1-0123456789abcdef", SourceRole.summary),
    ("summary-12-0123456789abcdef", SourceRole.summary),
    ("duplicate-selection", SourceRole.other),
    ("zzz-1", SourceRole.other),
    ("drafty", SourceRole.other),
])
def test_role_of(source_id, role):
    assert custody.role_of(source_id) is role


# ── evidence_summary_paths (R5) ────────────────────────────────────────────

NUG_PATHS = {
    "docs/summaries/004-session-clan-licehair.md",
    "docs/summaries/005-session-other.md",
    "docs/npcs/summary_native/ch001-086/draft/npc_nug.md",
}
NUG = (
    "---\nsubject: Nug\nglobal: false\nchapters:\n- 4\n---\n\n# NPC — Nug\n"
    "\n## Chapter 004\n"
    "\n### Entry — Nug\n- Source: docs/summaries/004-session-clan-licehair.md (line 31)\n\nA goblin.\n"
    "\n### Scene 004.02 — Camp (mentioned)\n- Source: docs/summaries/004-session-clan-licehair.md (line 40)\n"
    "- Mention lines: 41\n\nNug shouts.\n"
)


def _esp(text, paths=NUG_PATHS):
    return custody.evidence_summary_paths(text.encode("utf-8"), paths)


def test_stormgiants_shaped_evidence_names_its_one_summary():
    assert _esp(NUG) == frozenset({"docs/summaries/004-session-clan-licehair.md"})


def test_selected_evidence_delta_form_falls_back():
    text = NUG.replace("docs/summaries/004-session-clan-licehair.md (line 31)", "selected evidence")
    assert _esp(text) is None


def test_chapter_section_without_source_falls_back():
    assert _esp(NUG + "\n## Chapter 005\n\nNo items here.\n") is None
    # ...even though the frontmatter agrees: add it so only rule 3 can be the cause
    assert _esp(NUG.replace("- 4\n", "- 4\n- 5\n") + "\n## Chapter 005\n\nNo items here.\n") is None


def test_path_not_in_custody_falls_back():
    assert _esp(NUG, paths={"docs/summaries/999-other.md"}) is None


def test_frontmatter_chapters_mismatch_falls_back():
    assert _esp(NUG.replace("- 4\n", "- 4\n- 9\n")) is None
    assert _esp(NUG.replace("- 4\n", "- 7\n")) is None


def test_one_malformed_source_line_among_good_ones_falls_back():
    bad = NUG + "- Source: docs/summaries/005-session-other.md line 3\n"
    assert _esp(bad) is None
    assert _esp(NUG + "- Source: docs/summaries/005-session-other.md (line 3) trailing\n") is None


def test_no_source_line_at_all_falls_back():
    assert _esp("---\nsubject: Nug\n---\n\n# NPC — Nug\n\n## Chapter 004\n\ntext\n") is None


def test_malformed_frontmatter_or_bytes_fall_back():
    assert _esp(NUG.replace("subject: Nug", "subject: [unclosed")) is None
    assert _esp(NUG.replace("chapters:\n- 4\n", "chapters: four\n")) is None
    assert custody.evidence_summary_paths(b"\xff\xfe\x00", NUG_PATHS) is None


def test_two_summaries_union():
    text = NUG.replace("- 4\n", "- 4\n- 5\n") + (
        "\n## Chapter 005\n\n### Entry — Nug\n- Source: docs/summaries/005-session-other.md (line 3)\n\nBack.\n"
    )
    assert _esp(text) == frozenset({
        "docs/summaries/004-session-clan-licehair.md", "docs/summaries/005-session-other.md",
    })


# ── npc_evidence (R6) ──────────────────────────────────────────────────────

def _evid_id(cust, fx, npc):
    return next(iter(_ids(cust, _p(fx, fx.evidence(npc)))))


def _renamed(cust, path, new="docs/elsewhere/renamed.md"):
    """A custody copy whose source at ``path`` now lives at ``new`` (source id kept)."""
    return cust.model_copy(update={"sources": tuple(
        s.model_copy(update={"path": new}) if s.path == path else s for s in cust.sources)})


def test_npc_evidence_bound(ro):
    cust, items = _ctx(ro)
    presentation = ro.findings("a")[0]
    ids, basis = custody.npc_evidence(presentation, items, cust)
    assert ids == {_evid_id(cust, ro, "a")} and basis == "bound"


def test_npc_evidence_sibling_only(ro):
    cust, items = _ctx(ro)
    ids, basis = custody.npc_evidence(ro.signoff("a"), items, cust)  # signoff binds the draft only
    assert ids == {_evid_id(cust, ro, "a")} and basis == "sibling"


def test_npc_evidence_layout_only_when_no_sibling(ro):
    cust, items = _ctx(ro)
    ids, basis = custody.npc_evidence(ro.signoff("c"), items, cust)  # C raised no finding
    assert ids == {_evid_id(cust, ro, "c")} and basis == "layout"


def test_npc_evidence_layout_path_not_in_custody_plus_sibling(ro):
    cust, items = _ctx(ro)
    moved = _renamed(cust, _p(ro, ro.evidence("a")))
    ids, basis = custody.npc_evidence(ro.signoff("a"), items, moved)
    assert ids == {_evid_id(cust, ro, "a")} and basis == "sibling"


def test_npc_evidence_neither_means_all_evidence_role_sources(ro):
    cust, items = _ctx(ro)
    moved = _renamed(cust, _p(ro, ro.evidence("c")))
    ids, basis = custody.npc_evidence(ro.signoff("c"), items, moved)
    every_evidence = {s.source_id for s in cust.sources if custody.role_of(s.source_id) is SourceRole.evidence}
    assert ids == every_evidence and basis == "fallback_all_evidence"


# ── dependency_sets (data-model "Construction") ────────────────────────────

def _deps(fx, item_ids=None, *, cust=None, items=None, state=None):
    c, its = _ctx(fx)
    return custody.dependency_sets(KIND, cust or c, items or its, item_ids, state or custody.disk_probe(fx.root))


def test_claim_of_a_depends_on_its_draft_evidence_and_summary(ro):
    cust, _ = _ctx(ro)
    item = ro.findings("a")[0]
    dep = _deps(ro, [item.item_id])[item.item_id]
    assert dep.source_ids == _ids(cust, _p(ro, ro.draft("a")), _p(ro, ro.evidence("a")), _p(ro, ro.summary(1)))
    assert (dep.evidence_basis, dep.summary_basis) == ("bound", "evidence_sources")
    assert dep.npc == "a" and dep.npc_key == _p(ro, ro.draft("a"))


def test_signoff_of_c_depends_on_draft_evidence_and_both_summaries(ro):
    cust, _ = _ctx(ro)
    item = ro.signoff("c")
    dep = _deps(ro, [item.item_id])[item.item_id]
    assert dep.source_ids == _ids(
        cust, _p(ro, ro.draft("c")), _p(ro, ro.evidence("c")), _p(ro, ro.summary(1)), _p(ro, ro.summary(3)))
    assert dep.evidence_basis == "layout"


def test_d_selected_evidence_depends_on_every_summary(ro):
    cust, _ = _ctx(ro)
    every_summary = {s.source_id for s in cust.sources if custody.role_of(s.source_id) is SourceRole.summary}
    assert len(every_summary) == 3
    for item in ro.items["d"]:
        dep = _deps(ro, [item.item_id])[item.item_id]
        assert every_summary <= dep.source_ids and dep.summary_basis == "fallback_all_summaries"
        assert _ids(cust, _p(ro, ro.draft("d")), _p(ro, ro.evidence("d"))) <= dep.source_ids


def test_a_changed_evidence_file_makes_the_summary_basis_fallback(ro):
    cust, _ = _ctx(ro)
    every_summary = {s.source_id for s in cust.sources if custody.role_of(s.source_id) is SourceRole.summary}
    state = _probe(ro, **{_p(ro, ro.evidence("a")): FileState.changed})
    item = ro.findings("a")[0]
    dep = _deps(ro, [item.item_id], state=state)[item.item_id]
    assert every_summary <= dep.source_ids and dep.summary_basis == "fallback_all_summaries"


def test_non_npc_domain_item_depends_on_bound_plus_unbound_sources(ro):
    cust, items = _ctx(ro)
    target = ro.findings("a")[0]
    other = target.model_copy(update={"domain": "grounding_document"})
    swapped = [other if i.item_id == target.item_id else i for i in items]
    bound_anywhere = {b.source_id for i in swapped for b in i.input_bindings}
    unbound = {s.source_id for s in cust.sources} - bound_anywhere
    assert unbound  # summaries are bound by no item in this fixture
    dep = custody.dependency_sets("grounding_documents", cust, swapped, [target.item_id],
                                  custody.disk_probe(ro.root))[target.item_id]
    assert dep.source_ids == {b.source_id for b in target.input_bindings} | unbound
    assert dep.evidence_basis == "not_applicable" and dep.summary_basis == "unbound_sources"


def test_other_role_source_is_in_every_set(ro):
    cust, items = _ctx(ro)
    extra = cust.sources[0].model_copy(update={"source_id": "zzz-1", "path": "docs/x/odd.md"})
    with_other = cust.model_copy(update={"sources": (*cust.sources, extra)})
    deps = custody.dependency_sets(KIND, with_other, items, None, custody.disk_probe(ro.root))
    assert deps and all("zzz-1" in d.source_ids for d in deps.values())


# ── stale_report ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("state", [FileState.changed, FileState.missing, FileState.unreadable])
def test_each_state_stales_exactly_the_dependents(ro, state):
    cust, items = _ctx(ro)
    report = custody.stale_report(KIND, cust, items, None, _probe(ro, **{_p(ro, ro.draft("a")): state}))
    assert set(report.stale) == {i.item_id for i in ro.items["a"]}
    assert [f.state for f in report.changed_files] == [state]
    assert report.changed_files[0].path == _p(ro, ro.draft("a")) and report.changed_files[0].role is SourceRole.draft


def test_summary_change_stales_only_naming_npcs_and_the_fallback_one(ro):
    cust, items = _ctx(ro)
    report = custody.stale_report(KIND, cust, items, None, _probe(ro, **{_p(ro, ro.summary(2)): FileState.changed}))
    assert set(report.stale) == {i.item_id for npc in ("b", "d") for i in ro.items[npc]}  # D: fallback
    report3 = custody.stale_report(KIND, cust, items, None, _probe(ro, **{_p(ro, ro.summary(3)): FileState.changed}))
    assert set(report3.stale) == {i.item_id for npc in ("c", "d") for i in ro.items[npc]}


def test_submitted_subset_is_the_only_thing_examined(ro):
    cust, items = _ctx(ro)
    state = _probe(ro, **{_p(ro, ro.draft("a")): FileState.changed})
    b_only = custody.stale_report(KIND, cust, items, [i.item_id for i in ro.items["b"]], state)
    assert b_only.stale == {} and b_only.changed_files == ()
    mixed = custody.stale_report(
        KIND, cust, items, [ro.signoff("b").item_id, ro.signoff("a").item_id], state)
    assert set(mixed.stale) == {ro.signoff("a").item_id}


def test_unknown_item_ids_are_ignored(ro):
    cust, items = _ctx(ro)
    report = custody.stale_report(KIND, cust, items, ["no-such-item"], custody.disk_probe(ro.root))
    assert report.stale == {} and report.dependency_sets == {}


def test_change_and_change_back_is_current(tmp_path):
    fx = fixture.build(tmp_path)
    cust, items = _ctx(fx)
    fx.touch(fx.draft("a"))
    assert custody.stale_report(KIND, cust, items, None, custody.disk_probe(fx.root)).stale
    fx.restore(fx.draft("a"))
    clean = custody.stale_report(KIND, cust, items, None, custody.disk_probe(fx.root))
    assert clean.stale == {} and clean.changed_files == ()


def test_real_missing_and_symlink_behaviour(tmp_path):
    fx = fixture.build(tmp_path)
    cust, items = _ctx(fx)
    fx.delete(fx.draft("b"))
    report = custody.stale_report(KIND, cust, items, None, custody.disk_probe(fx.root))
    assert set(report.stale) == {i.item_id for i in fx.items["b"]}
    assert report.changed_files[0].state is FileState.missing
    # a directory where a file belongs is "missing" (not a file), never an exception
    fx.draft("b").mkdir()
    again = custody.stale_report(KIND, cust, items, None, custody.disk_probe(fx.root))
    assert again.changed_files[0].state is FileState.missing
    # a symlink is a security refusal, not a staleness state
    fx.draft("b").rmdir()
    fx.draft("b").symlink_to(fx.draft("a"))
    with pytest.raises(ReviewStoreError, match="REVIEW_PATH"):
        custody.stale_report(KIND, cust, items, None, custody.disk_probe(fx.root))


def test_probe_hashes_each_path_at_most_once(ro, monkeypatch):
    cust, items = _ctx(ro)
    import hashlib
    calls = []
    real = hashlib.sha256

    def counting(data=b"", *a, **k):
        calls.append(len(data))
        return real(data, *a, **k)

    monkeypatch.setattr(custody.hashlib, "sha256", counting)
    probe = custody.disk_probe(ro.root)
    custody.stale_report(KIND, cust, items, None, probe)
    first = len(calls)
    custody.stale_report(KIND, cust, items, None, probe)
    assert len(calls) == first and first <= len(cust.sources)


def test_empty_dependency_set_is_stale_with_no_dependency(ro):
    cust, items = _ctx(ro)
    keep = ro.findings("a")[0]
    bare = keep.model_copy(update={"item_id": "bare-item", "domain": "grounding_document", "input_bindings": ()})
    only = [keep.model_copy(update={"domain": "grounding_document"}), bare]
    one_source = cust.model_copy(update={"sources": tuple(s for s in cust.sources if s.source_id in
                                                          {b.source_id for b in keep.input_bindings})})
    report = custody.stale_report("grounding_documents", one_source, only, ["bare-item"], custody.disk_probe(ro.root))
    assert "bare-item" in report.stale and report.stale["bare-item"] == ()
    assert "bare-item" in report.no_dependency
    detail = custody.refusal_detail(report, review_id="r", generation=1, operation="decide", items=only)
    entry = next(e for e in detail["stale_items"] if e["item_id"] == "bare-item")
    assert entry["paths"] == [] and entry["reason"] == "no_dependency"


def test_comparison_uses_the_custody_generation_sha_not_the_binding_sha(ro):
    cust, items = _ctx(ro)
    old = [
        i.model_copy(update={"input_bindings": tuple(
            b.model_copy(update={"custody_sha256": "0" * 64}) for b in i.input_bindings)})
        for i in items
    ]
    report = custody.stale_report(KIND, cust, old, None, custody.disk_probe(ro.root))
    assert report.stale == {}


# ── refusal_detail / message / text / by-npc / remedy ──────────────────────

def _two_file_report(fx):
    cust, items = _ctx(fx)
    state = _probe(fx, **{_p(fx, fx.draft("a")): FileState.changed, _p(fx, fx.summary(2)): FileState.missing})
    submitted = [fx.findings("b")[0].item_id, fx.signoff("a").item_id, fx.findings("a")[0].item_id]
    return custody.stale_report(KIND, cust, items, submitted, state), items, submitted


def test_refusal_detail_matches_the_contract(ro):
    report, items, submitted = _two_file_report(ro)
    detail = custody.refusal_detail(report, review_id=ro.review_id, generation=ro.generation,
                                    operation="decide", items=items)
    assert set(detail) == {"version", "operation", "review_id", "review_generation", "changed_files",
                           "stale_items", "by_npc", "remedy"}
    assert detail["version"] == 1 and detail["operation"] == "decide"
    assert detail["review_id"] == ro.review_id and detail["review_generation"] == ro.generation
    files = detail["changed_files"]
    assert [f["path"] for f in files] == sorted(f["path"] for f in files) == [
        _p(ro, ro.draft("a")), _p(ro, ro.summary(2))]
    assert set(files[0]) == {"path", "source_id", "role", "state", "items"}
    assert (files[0]["role"], files[0]["state"]) == ("draft", "changed")
    assert (files[1]["role"], files[1]["state"]) == ("summary", "missing")
    a_ids = sorted([ro.signoff("a").item_id, ro.findings("a")[0].item_id])
    assert [i["item_id"] for i in files[0]["items"]] == a_ids  # sorted, only submitted dependents
    assert {i["npc"] for i in files[0]["items"]} == {"a"}
    assert {i["action"] for i in files[0]["items"]} == {"signoff_npc_draft", "review_presentation"}
    assert [i["item_id"] for i in files[1]["items"]] == [ro.findings("b")[0].item_id]
    stale = detail["stale_items"]
    assert [s["item_id"] for s in stale] == sorted(s["item_id"] for s in stale)
    assert {s["item_id"] for s in stale} == set(submitted)
    assert next(s for s in stale if s["item_id"] == ro.findings("b")[0].item_id)["paths"] == [_p(ro, ro.summary(2))]
    assert [(g["npc"], g["item_ids"]) for g in detail["by_npc"]] == [
        ("a", a_ids), ("b", [ro.findings("b")[0].item_id])]
    assert detail["remedy"]["command"] == (
        f"summary_native review refresh {ro.review_id} --expected-generation {ro.generation}")
    assert "note" in detail["remedy"]


def test_remedy_note_only_when_a_draft_changed(ro):
    cust, items = _ctx(ro)
    state = _probe(ro, **{_p(ro, ro.summary(2)): FileState.changed})
    report = custody.stale_report(KIND, cust, items, [ro.findings("b")[0].item_id], state)
    detail = custody.refusal_detail(report, review_id="r1", generation=3, operation="import", items=items)
    assert detail["operation"] == "import"
    assert detail["remedy"] == {"command": "summary_native review refresh r1 --expected-generation 3"}
    assert custody.remedy("r1", 3, True)["note"].startswith("A changed draft also needs a new verification review")
    assert "note" not in custody.remedy("r1", 3, False)


def test_refusal_message_is_one_line_with_the_code_prefix(ro):
    report, _items, submitted = _two_file_report(ro)
    message = custody.refusal_message(report)
    assert "\n" not in message and message.startswith("REVIEW_STALE_CUSTODY: ")
    assert f"2 source file(s) changed; {len(submitted)} submitted item(s) depend on them; nothing was saved" in message


def test_refusal_text_lines(ro):
    report, items, _ = _two_file_report(ro)
    detail = custody.refusal_detail(report, review_id=ro.review_id, generation=ro.generation,
                                    operation="decide", items=items)
    lines = custody.refusal_text_lines(detail)
    assert lines[0].startswith("  changed  " + _p(ro, ro.draft("a")) + ": a")
    assert lines[1].startswith("  missing  " + _p(ro, ro.summary(2)) + ": b")
    assert any(l.startswith("Bring them current: summary_native review refresh ") for l in lines)
    assert lines[-1].startswith("A changed draft also needs a new verification review")


def test_stale_by_npc_per_review_status_contract(ro):
    cust, items = _ctx(ro)
    state = _probe(ro, **{_p(ro, ro.draft("a")): FileState.changed, _p(ro, ro.summary(1)): FileState.changed})
    report = custody.stale_report(KIND, cust, items, None, state)
    out = custody.stale_by_npc(report, items)
    assert set(out) == {"changed_files", "stale_by_npc"}
    files = {f["path"]: f for f in out["changed_files"]}
    assert [f["path"] for f in out["changed_files"]] == sorted(files)
    assert set(files[_p(ro, ro.draft("a"))]) == {"path", "role", "state", "stale_item_count"}
    assert files[_p(ro, ro.draft("a"))]["stale_item_count"] == len(ro.items["a"])
    npcs = out["stale_by_npc"]
    assert [n["npc"] for n in npcs] == ["a", "c", "d"]  # 001 is named by A and C; D falls back to all summaries
    entry = npcs[0]
    assert set(entry) == {"npc", "npc_key", "stale_item_count", "stale_item_ids", "changed_files"}
    assert entry["npc_key"] == _p(ro, ro.draft("a")) and entry["stale_item_count"] == len(ro.items["a"])
    assert entry["stale_item_ids"] == sorted(i.item_id for i in ro.items["a"])
    assert {f["path"] for f in entry["changed_files"]} == {_p(ro, ro.draft("a")), _p(ro, ro.summary(1))}
    assert custody.stale_by_npc(custody.stale_report(KIND, cust, items, None, custody.disk_probe(ro.root)), items) == {
        "changed_files": [], "stale_by_npc": []}


# ── npc_label ──────────────────────────────────────────────────────────────

def test_npc_label_registry_name_first_else_draft_stem(ro):
    item = ro.findings("a")[0]
    assert custody.npc_label(item) == "a"
    named = item.model_copy(update={"subject_ref": SubjectReference(
        subject_id=item.subject_ref.subject_id, kind="entity",
        registry_name="Aaa Prime", registry_type="npc", registry_snapshot_sha256="0" * 64)})
    assert custody.npc_label(named) == "Aaa Prime"
    verify = item.model_copy(update={"locator": item.locator.model_copy(
        update={"source_path": "docs/x/draft/npc_big_bob.verify.md"})})
    assert custody.npc_label(verify) == "big_bob"


def test_indented_or_bulleted_source_lines_are_still_dependencies():
    two = NUG.replace("- 4\n", "- 4\n- 5\n") + (
        "\n## Chapter 005\n\n### Entry — Nug\n  - Source: docs/summaries/005-session-other.md (line 3)\n\nBack.\n"
    )
    assert _esp(two) == frozenset({
        "docs/summaries/004-session-clan-licehair.md", "docs/summaries/005-session-other.md"})
    star = NUG + "* Source: docs/summaries/005-session-other.md (line 3)\n"
    assert _esp(star) == frozenset({
        "docs/summaries/004-session-clan-licehair.md", "docs/summaries/005-session-other.md"})


def test_indented_unparsable_source_line_falls_back():
    assert _esp(NUG + "  - Source: selected evidence\n") is None
    assert _esp(NUG + "\t- Source: docs/summaries/005-session-other.md line 3\n") is None
    assert _esp(NUG + "  - Source: docs/summaries/999-unknown.md (line 3)\n") is None
