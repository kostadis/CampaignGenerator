"""T010 eligibility and freshness contracts for whole-bundle promotion.

These tests intentionally exercise a small, pure gate seam.  Enumeration,
diff rendering, and publication are tested elsewhere; this module specifies
which changes stale source approval and which only stale a destination-bound
preview.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest


FACTORY_PATH = Path(__file__).parent / "fixtures/summary_native/promotion/create_campaign.py"
FACTORY_SPEC = importlib.util.spec_from_file_location("promotion_gate_fixture_factory", FACTORY_PATH)
assert FACTORY_SPEC and FACTORY_SPEC.loader
FACTORY = importlib.util.module_from_spec(FACTORY_SPEC)
FACTORY_SPEC.loader.exec_module(FACTORY)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evaluate(root: Path, context: dict) -> dict:
    """Call the planned pure gate seam and require its stable result envelope."""
    try:
        module = importlib.import_module("pipelines.summary_native.promotion.gates")
    except ModuleNotFoundError:
        pytest.fail("implement pipelines.summary_native.promotion.gates", pytrace=False)
    function = getattr(module, "evaluate_promotion_gates", None)
    assert callable(function), "implement gates.evaluate_promotion_gates(campaign_dir, context)"
    result = function(root, context)
    assert isinstance(result, dict)
    assert set(result) >= {"eligible", "source_signoffs_current", "gates"}
    return result


def _codes(result: dict) -> set[str]:
    return {gate["code"] for gate in result["gates"] if gate.get("code")}


@pytest.fixture
def gate_campaign(tmp_path: Path) -> tuple[Path, dict]:
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    drafts = root / "docs/summary_native/ch001-003/state/drafts"
    documents = {
        document: {
            "path": (drafts / f"{document}.draft.md").relative_to(root).as_posix(),
            "sha256": _sha(drafts / f"{document}.draft.md"),
            "complete": True,
        }
        for document in FACTORY.DOCUMENTS
    }
    support_paths = [drafts / "canon_events_timeline.md", *sorted((drafts / "reference").rglob("*"))]
    support = {
        path.relative_to(root).as_posix(): _sha(path)
        for path in support_paths
        if path.is_file()
    }
    authority = _sha(root / "docs/authority.yaml")
    rules = {"promotion-integrity": "1", "grounding-document-signoff": "2", "claims": "1"}
    signoff_context = {
        "documents": {key: value["sha256"] for key, value in documents.items()},
        "support": support,
        "authority": {"relevant_digest": authority, "ledger_digest": authority},
        "audience": "gm",
        "rules": rules,
        "analysis_digest": "a" * 64,
        "resolution_digest": "b" * 64,
    }
    context = {
        "version": 1,
        "documents": documents,
        "support": support,
        "authority": {
            "relevant_digest": authority,
            "ledger_digest": authority,
            "integrity": "valid",
        },
        "audience": "gm",
        "rules": rules,
        "findings": [],
        "checks_complete": True,
        "signoffs": {
            document: {
                "document": document,
                "rule_version": 2,
                "decision": "document_signoff",
                "event_id": f"signoff-{document}",
                "context": deepcopy(signoff_context),
            }
            for document in FACTORY.DOCUMENTS
        },
        "expected_destination_digest": "c" * 64,
        "actual_destination_digest": "c" * 64,
    }
    return root, context


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("absent", "PROMOTION_SIGNOFF_REQUIRED"),
        ("v1", "PROMOTION_SIGNOFF_RULE_UNSUPPORTED"),
    ],
)
def test_absent_or_v1_only_document_signoff_never_authorizes_v2_bundle(
    gate_campaign: tuple[Path, dict], mutation: str, code: str
):
    root, context = gate_campaign
    if mutation == "absent":
        context["signoffs"].pop("party")
    else:
        context["signoffs"]["party"]["rule_version"] = 1
    result = _evaluate(root, context)
    assert not result["eligible"]
    assert not result["source_signoffs_current"]
    assert code in _codes(result)


@pytest.mark.parametrize("changed", ["support", "authority", "audience", "rules"])
def test_relevant_support_authority_audience_or_rule_change_stales_exact_signoff(
    gate_campaign: tuple[Path, dict], changed: str
):
    root, context = gate_campaign
    if changed == "support":
        member = sorted(context["support"])[0]
        context["support"][member] = "d" * 64
    elif changed == "authority":
        context["authority"]["relevant_digest"] = "d" * 64
        context["authority"]["ledger_digest"] = "d" * 64
    elif changed == "audience":
        context["audience"] = "players"
    else:
        context["rules"]["claims"] = "2"

    result = _evaluate(root, context)
    assert not result["eligible"]
    assert not result["source_signoffs_current"]
    assert "PROMOTION_SIGNOFF_STALE" in _codes(result)


def test_incomplete_draft_blocks_even_when_its_bytes_were_signed(
    gate_campaign: tuple[Path, dict]
):
    root, context = gate_campaign
    context["documents"]["planning"]["complete"] = False
    result = _evaluate(root, context)
    assert not result["eligible"]
    assert "PROMOTION_DRAFT_INCOMPLETE" in _codes(result)


def test_new_unresolved_finding_blocks_without_inheriting_old_signoffs(
    gate_campaign: tuple[Path, dict]
):
    root, context = gate_campaign
    context["findings"].append(
        {
            "finding_id": "finding-after-signoff",
            "analysis_digest": "e" * 64,
            "state": "pending",
            "blocking": True,
        }
    )
    context["analysis_digest"] = "e" * 64
    context["resolution_digest"] = "f" * 64
    result = _evaluate(root, context)
    assert not result["eligible"]
    assert not result["source_signoffs_current"]
    assert "PROMOTION_FINDING_UNRESOLVED" in _codes(result)


def test_destination_only_drift_invalidates_preview_but_preserves_source_signoffs(
    gate_campaign: tuple[Path, dict]
):
    root, context = gate_campaign
    context["actual_destination_digest"] = "d" * 64
    result = _evaluate(root, context)
    assert not result["eligible"]
    assert result["source_signoffs_current"]
    assert "PROMOTION_DESTINATION_STALE" in _codes(result)
    assert "PROMOTION_SIGNOFF_STALE" not in _codes(result)


def test_unrelated_authority_history_does_not_erase_relevant_approvals(
    gate_campaign: tuple[Path, dict]
):
    root, context = gate_campaign
    # Ledger custody/integrity is still checked, while the exact authority
    # projection bound into these documents remains byte-identical.
    context["authority"]["ledger_digest"] = "d" * 64
    context["authority"]["unrelated_event_ids"] = ["unrelated-review-decision"]
    result = _evaluate(root, context)
    assert result["eligible"]
    assert result["source_signoffs_current"]
    assert "PROMOTION_SIGNOFF_STALE" not in _codes(result)
