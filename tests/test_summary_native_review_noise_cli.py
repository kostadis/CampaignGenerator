"""``review noise`` and ``review noise decide`` (spec 041 US4, contracts/cli-review-noise.md)."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from pipelines.summary_native import noise
from pipelines.summary_native.cli import main
from pipelines.summary_native.review.delegated import list_noise, plan_noise_class
from pipelines.summary_native.review.models import ReviewItem
from pipelines.summary_native.review.store import ReviewStoreError
from tests.test_summary_native_review_delegated import (  # noqa: F401  (campaign is a fixture)
    DRAFT,
    SUMMARY,
    _create,
    _decide,
    _events,
    _sha,
    campaign,
)

RID = "noise-review"


def _noise_item(cid: UUID, item_id: str, cls: str | None, *, summary_sha: str, extra_code: str | None = None,
                npc: str | None = "Blasius") -> ReviewItem:
    number = int(_sha(item_id.encode())[:6], 16)
    diagnostics = []
    if cls is not None:
        diagnostics.append({
            "diagnostic_id": f"diag-{item_id}-n", "legacy_code": f"noise-{cls}", "message": f"{cls} noise.",
            "blocking": False,
            "details": {"check": "number", "noise_class": cls, "token": f"tok-{item_id}",
                        "sentence": f"Sentence of {item_id}.", "cited_scenes": ["ch 036 / 036.04"],
                        "resolved_by": "Chapter 036", "line": 14},
        })
    if extra_code:
        diagnostics.append({"diagnostic_id": f"diag-{item_id}-x", "legacy_code": extra_code,
                            "message": "other.", "blocking": False})
    subject = {"subject_id": UUID(int=100 + number), "kind": "entity"}
    if npc:
        subject.update(registry_name=npc, registry_type="npc", registry_snapshot_sha256="d" * 64)
    return ReviewItem(
        item_id=item_id, revision=1, campaign_id=cid, review_id=RID, domain="npc_finding",
        subject_ref=subject, occurrence_id=UUID(int=200 + number),
        locator={"source_path": DRAFT, "anchor": f"line:14", "display_line": 14},
        claim_text=f"Exact claim {item_id}",
        evidence=({"source_id": "summary-1", "source_path": SUMMARY, "anchor": item_id,
                   "exact_excerpt": "Exact evidence", "selected_span_sha256": _sha(b"Exact evidence")},),
        diagnostics=tuple(diagnostics),
        categories={"classified_noise"} if cls and not extra_code else {"citation_non_entailment"},
        severity="advisory" if cls and not extra_code else "needs_judgment",
        assignment_basis="mechanical" if cls and not extra_code else "advisory_candidate",
        rationale="Classified noise.",
        proposed_action={"action": "review_classified_noise", "details": {"legacy_code": f"noise-{cls}"}},
        scope={"kind": "evidence", "value": item_id},
        rule_versions=({"rule_id": "npc-verify", "version": "1"},),
        input_bindings=({"source_id": "summary-1", "path": SUMMARY, "custody_sha256": summary_sha, "semantic_sha256": "c" * 64},),
    )


@pytest.fixture
def noise_review(campaign):
    root, cid, summary_sha, _d, sources = campaign
    items = {
        "label-1": _noise_item(cid, "label-1", "label", summary_sha=summary_sha),
        "label-2": _noise_item(cid, "label-2", "label", summary_sha=summary_sha, npc=None),
        "label-3": _noise_item(cid, "label-3", "label", summary_sha=summary_sha),
        "idiom-1": _noise_item(cid, "idiom-1", "idiom", summary_sha=summary_sha),
        "syn-1": _noise_item(cid, "syn-1", "synonym", summary_sha=summary_sha),
        "mixed": _noise_item(cid, "mixed", "label", summary_sha=summary_sha, extra_code="number-inconsistency"),
        "plain": _noise_item(cid, "plain", None, summary_sha=summary_sha, extra_code="number-inconsistency"),
    }
    _create(root, cid, RID, list(items.values()), sources)
    _decide(root, RID, items["label-3"], "discuss", "defer", request="r-l3")
    return root, items


def _argv(root: Path, *args: str) -> list[str]:
    return ["review", "noise", *args, "--campaign-dir", str(root), "--json"]


def _run(capsys, argv):
    code = main(argv)
    return code, json.loads(capsys.readouterr().out)


def _decide_argv(root, *extra, cls="label", verdict="approve", note="Chapter labels are not story facts."):
    base = ["review", "noise", "decide", RID, "--reviewer", "GM", "--campaign-dir", str(root), "--json"]
    if cls:
        base += ["--class", cls]
    if verdict:
        base += ["--verdict", verdict]
    if note is not None:
        base += ["--note", note]
    return base + list(extra)


def test_noise_lists_classes_in_precedence_order_with_zero_counts(noise_review, capsys):
    root, _items = noise_review
    code, response = _run(capsys, _argv(root, RID))
    assert code == 0
    data = response["data"]
    assert data["review_id"] == RID and data["review_generation"] == 1
    assert [c["noise_class"] for c in data["classes"]] == list(noise.CLASSES)
    by = {c["noise_class"]: c for c in data["classes"]}
    assert by["label"]["legacy_code"] == "noise-label"
    # the mixed-code item is not a member; the discussed item is a member but not undecided
    assert by["label"]["count"] == 3 and by["label"]["undecided"] == 2
    assert by["label"]["approved"] == 0 and by["label"]["rejected"] == 0
    assert by["idiom"]["count"] == 1 and by["negated-status"]["count"] == 0
    assert by["negated-status"]["occurrences"] == []
    occ = {o["item_id"]: o for o in by["label"]["occurrences"]}
    assert set(occ) == {"label-1", "label-2", "label-3"}
    first = occ["label-1"]
    assert first["npc"] == "Blasius" and first["draft_path"] == DRAFT and first["line"] == 14
    assert first["token"] == "tok-label-1" and first["sentence"] == "Sentence of label-1."
    assert first["cited_scenes"] == ["ch 036 / 036.04"] and first["resolved_by"] == "Chapter 036"
    assert first["decision"] is None
    assert occ["label-3"]["decision"]["verdict"] == "discuss"


def test_noise_text_mode_prints_one_line_per_class(noise_review, capsys):
    root, _ = noise_review
    argv = [a for a in _argv(root, RID) if a != "--json"]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "label  3 (2 undecided)" in out
    assert "negated-status  0 (0 undecided)" in out


def test_dry_run_writes_nothing(noise_review, capsys):
    root, _ = noise_review
    before = _events(root, RID)
    code, response = _run(capsys, _decide_argv(root))
    assert code == 0
    data = response["data"]
    assert data["planned"] == ["label-1", "label-2"] and data["already_decided"] == ["label-3"]
    assert data["written"] is False and data["noise_class"] == "label" and data["verdict"] == "approve"
    assert _events(root, RID) == before


def test_write_decides_only_undecided_items_of_that_class_with_class_note(noise_review, capsys):
    root, _ = noise_review
    code, response = _run(capsys, _decide_argv(root, "--write"))
    assert code == 0 and response["data"]["written"] is True
    new = [e for e in _events(root, RID) if e["request_id"] != "r-l3"]
    assert sorted(e["item_id"] for e in new) == ["label-1", "label-2"]
    for event in new:
        assert event["verdict"] == "approve" and event["disposition"] == "accept_no_change"
        assert event["reviewer"] == "GM"
        assert event["note"] == ("GM class verdict on batch card [noise-label] (2 occurrences): "
                                 "Chapter labels are not story facts.")
    # the earlier discuss decision on label-3 is untouched
    assert [e["verdict"] for e in _events(root, RID) if e["item_id"] == "label-3"] == ["discuss"]


def test_reject_records_reject_action(noise_review, capsys):
    root, _ = noise_review
    code, _ = _run(capsys, _decide_argv(root, "--write", cls="idiom", verdict="reject", note="Not an idiom."))
    assert code == 0
    (event,) = [e for e in _events(root, RID) if e["item_id"] == "idiom-1"]
    assert event["verdict"] == "reject" and event["disposition"] == "reject_action"
    assert "(1 occurrences)" in event["note"]


def test_unmarked_class_stays_undecided_in_status(noise_review, capsys):
    root, _ = noise_review
    _run(capsys, _decide_argv(root, "--write", cls="idiom"))
    code = main(["review", "status", RID, "--campaign-dir", str(root), "--json"])
    status = json.loads(capsys.readouterr().out)["data"]
    assert code == 0
    assert [e["item_id"] for e in _events(root, RID) if e["item_id"] == "syn-1"] == []
    _, response = _run(capsys, _argv(root, RID))
    by = {c["noise_class"]: c for c in response["data"]["classes"]}
    assert by["synonym"]["undecided"] == 1 and by["idiom"]["approved"] == 1


def test_nothing_to_decide_refuses(noise_review, capsys):
    root, _ = noise_review
    code, response = _run(capsys, _decide_argv(root, cls="negated-status"))
    assert code == 2 and response["code"] == "REVIEW_NOISE_NOTHING_TO_DECIDE"


def test_blank_note_refuses(noise_review, capsys):
    root, _ = noise_review
    code, response = _run(capsys, _decide_argv(root, note="   "))
    assert code == 2 and response["code"] == "REVIEW_NOISE_NOTE_REQUIRED"


def test_note_too_long_once_prefixed_refuses(noise_review, capsys):
    root, _ = noise_review
    (root / "config" / "review.yaml").write_text("max_note_chars: 100\n", encoding="utf-8")
    note = "x" * 80  # fits alone, not after the ~60-char prefix
    code, response = _run(capsys, _decide_argv(root, "--write", note=note))
    assert code == 2 and response["code"] == "REVIEW_NOISE_NOTE_TOO_LONG"
    assert [e for e in _events(root, RID) if e["item_id"] == "label-1"] == []


def test_missing_class_is_an_argparse_error(noise_review):
    root, _ = noise_review
    with pytest.raises(SystemExit):
        main(_decide_argv(root, cls=None))


def test_unknown_class_is_refused_by_argparse_at_the_cli(noise_review):
    root, _ = noise_review
    with pytest.raises(SystemExit):
        main(_decide_argv(root, cls="everything"))


def test_unknown_class_refused_at_the_function_level(noise_review):
    root, _ = noise_review
    with pytest.raises(ReviewStoreError) as exc:
        plan_noise_class(root, RID, noise_class="everything", verdict="approve", note="n")
    assert exc.value.code == "REVIEW_NOISE_UNKNOWN_CLASS"
    assert "label, idiom" in str(exc.value)


def test_list_noise_is_read_only(noise_review):
    root, _ = noise_review
    before = _events(root, RID)
    assert [c["noise_class"] for c in list_noise(root, RID)["classes"]] == list(noise.CLASSES)
    assert _events(root, RID) == before
