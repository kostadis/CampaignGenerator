"""#655: every review action declares its decisions; an unknown action fails closed (spec 043, FR-016/FR-017)."""

from __future__ import annotations

import itertools
import re
from pathlib import Path

import pytest

from pipelines.summary_native.review.store import ReviewStoreError, _validate_action_decision
from tests import _custody_fixture as fixture
from tests.test_summary_native_review_delegated import SUMMARY, _item

VERDICTS = ("approve", "reject", "discuss")
DISPOSITIONS = ("accept_no_change", "source_correction", "merge", "distinct", "reject_action", "defer",
                "document_signoff")

_FINDING = {("approve", "accept_no_change"), ("reject", "reject_action"), ("discuss", "defer")}
_SIGNOFF = {("approve", "document_signoff"), ("reject", "reject_action"), ("discuss", "defer")}

# Research R4. Existing rows are restated here so a change to them is visible.
TABLE: dict[str, set[tuple[str, str]]] = {
    "review_claim_against_evidence": _FINDING,
    "review_presentation": _FINDING,
    "review_classified_noise": _FINDING,
    "rerun_selected_check": _FINDING,
    "repair_or_recheck_pointer": _FINDING,
    "review_supersession": _FINDING,
    "review_audience_and_knowledge": _FINDING,
    "acknowledge_claim_coverage": _FINDING,
    "adjudicate_identity": {("approve", "merge"), ("approve", "distinct"), ("reject", "reject_action"),
                            ("discuss", "defer")},
    "confirm_claim_mapping": _FINDING,
    "resolve_claim_finding": {("reject", "reject_action"), ("discuss", "defer")},
    "dismiss_claim_finding": _FINDING,
    "accept_claim_uncertainty": _FINDING,
    "prepare_claim_source_correction": {("approve", "source_correction"), ("reject", "reject_action"),
                                        ("discuss", "defer")},
    "signoff_document": _SIGNOFF,
    "signoff_npc_draft": _SIGNOFF,
}
_BOUND = {"dismiss_claim_finding", "accept_claim_uncertainty"}


def _make(action: str):
    import uuid
    details = {"evidence_digest": "e" * 64, "rationale_digest": "r" * 64} if action in _BOUND else {}
    return _item(uuid.UUID(int=1), "r", "item-1", summary_sha="a" * 64,
                 action={"action": action, "details": details})


@pytest.mark.parametrize("action", sorted(TABLE))
def test_every_declared_action_allows_exactly_its_pairs(action):
    item = _make(action)
    for verdict, disposition in itertools.product(VERDICTS, DISPOSITIONS):
        if (verdict, disposition) in TABLE[action]:
            _validate_action_decision(item, verdict=verdict, disposition=disposition)
        else:
            with pytest.raises(ReviewStoreError) as exc:
                _validate_action_decision(item, verdict=verdict, disposition=disposition)
            assert exc.value.code == "REVIEW_ACTION_MISMATCH", (action, verdict, disposition)


def test_unknown_action_fails_closed():
    item = _make("made_up_action")
    with pytest.raises(ReviewStoreError) as exc:
        _validate_action_decision(item, verdict="approve", disposition="accept_no_change")
    assert exc.value.code == "REVIEW_ACTION_MISMATCH"
    assert "made_up_action" in str(exc.value)


def test_basis_rule_and_digest_rule_unchanged():
    item = _make("dismiss_claim_finding")
    bare = item.model_copy(update={"proposed_action": item.proposed_action.model_copy(update={"details": {}})})
    with pytest.raises(ReviewStoreError) as exc:
        _validate_action_decision(bare, verdict="approve", disposition="accept_no_change")
    assert "lacks bound evidence" in str(exc.value)
    blocked = item.model_copy(update={"proposed_action": item.proposed_action.model_copy(
        update={"details": {**item.proposed_action.details, "basis": "mechanical"}})})
    with pytest.raises(ReviewStoreError) as exc:
        _validate_action_decision(blocked, verdict="approve", disposition="accept_no_change")
    assert "cannot be waived" in str(exc.value)


def test_document_signoff_disposition_refused_on_non_signoff_action():
    with pytest.raises(ReviewStoreError) as exc:
        _validate_action_decision(_make("review_presentation"), verdict="approve", disposition="document_signoff")
    assert exc.value.code == "REVIEW_ACTION_MISMATCH"


def test_every_produced_action_literal_has_a_row():
    """Any action the code produces must have a row, or take the sign-off branch."""
    base = Path(__file__).resolve().parents[1] / "pipelines" / "summary_native"
    files = [base / "review" / "verification.py", base / "review" / "cli.py", base / "review" / "documents.py",
             base / "claims" / "review.py", base / "claims" / "cli.py"]
    # ``action = "x"`` (spaced assignment) only: argparse's ``action="store_true"`` is not an action.
    pattern = re.compile(r"""["']action["']\s*:\s*["']([a-z_]+)["']|\baction = ["']([a-z_]+)["']""")
    produced: set[str] = set()
    for path in files:
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            produced.add(match.group(1) or match.group(2))
    # claims/review.py maps alternatives to actions through a dict of string values.
    text = (base / "claims" / "review.py").read_text(encoding="utf-8")
    produced.update(re.findall(r'"(?:dismiss|accept_uncertainty|source_correction)":\s*"([a-z_]+)"', text))
    assert {"review_claim_against_evidence", "review_classified_noise", "adjudicate_identity",
            "acknowledge_claim_coverage", "signoff_npc_draft", "signoff_document"} <= produced
    missing = produced - set(TABLE)
    assert not missing, f"actions produced with no row in the table: {sorted(missing)}"


def test_review_decide_refuses_wrong_pairs_and_leaves_store_unchanged(tmp_path):
    fx = fixture.build(tmp_path)
    findings = [i for npc in fx.items.values() for i in npc
                if i.proposed_action.action in {"review_claim_against_evidence", "review_presentation"}]
    assert findings, "fixture must produce review_claim_against_evidence / review_presentation items"
    # The two pairs the spec names are already refused earlier, by DecisionEvent's own
    # meaning check (REVIEW_INVALID). The pairs below pass that check and reach the table.
    model_refused = [("approve", "reject_action"), ("reject", "accept_no_change")]
    table_refused = [("approve", "source_correction"), ("approve", "merge"), ("approve", "distinct"),
                     ("approve", "document_signoff")]
    for item in findings[:2]:
        for verdict, disposition in model_refused + table_refused:
            before = fx.review_tree_sha()
            rc, out = fx.decide([item], verdict=verdict, disposition=disposition)
            assert rc != 0 and out.get("ok") is False, (item.proposed_action.action, verdict, disposition, out)
            if (verdict, disposition) in table_refused:
                assert "REVIEW_ACTION_MISMATCH" in str(out), out
            assert fx.review_tree_sha() == before
