import shutil
from pathlib import Path

import pytest

from session_doc.narration_wiki.measure import measure
from session_doc.narration_wiki.models import StateError
from session_doc.narration_wiki.proposals import apply_proposal, stage_proposal
from session_doc.narration_wiki.storage import finalize_proposal
from tests.test_narration_wiki_storage import prepared_scope


PROPOSALS = Path(__file__).parent / "fixtures" / "narration_wiki" / "proposals"


def accepted_scope(tmp_path: Path):
    scope = prepared_scope(tmp_path)
    from session_doc.narration_wiki.storage import record_conflict_ruling, record_pattern_ruling
    record_conflict_ruling(scope, "seed-voice", "Use campaign source", "This campaign owns the named rule")
    record_pattern_ruling(scope, "distinct-bookkeeping", "accept", tier="campaign")
    incoming = scope.iteration_root / "incoming"
    incoming.mkdir()
    shutil.copy2(PROPOSALS / "valid.yaml", incoming / "proposal.yaml")
    shutil.copy2(PROPOSALS / "candidate", incoming / "candidate")
    return scope


def test_rejected_gate2_restores_exact_bytes_and_keeps_wiki_lesson(tmp_path):
    scope = accepted_scope(tmp_path)
    target = scope.campaign_root / "voice" / "_genre.md"
    before = target.read_bytes()
    stage_proposal(scope, "proposal-001", "incoming/proposal.yaml")
    assert target.read_bytes() == before
    apply_proposal(scope, "proposal-001")
    assert target.read_bytes() != before
    measure(scope, "after", "proposal-001")
    finalize_proposal(scope, "proposal-001", "reject")
    assert target.read_bytes() == before
    assert (scope.campaign_wiki_root / "patterns" / "distinct-bookkeeping.md").is_file()
    ledger = (scope.campaign_wiki_root / "skill-impact.md").read_text()
    assert ledger.count("narration-wiki-proposal:proposal-001") == 1
    with pytest.raises(StateError, match="equivalent rejected"):
        stage_proposal(scope, "proposal-002", "incoming/proposal.yaml")


@pytest.mark.parametrize("fixture", ["unauthorized.yaml", "multi-target.yaml", "stale-hash.yaml"])
def test_stage_refuses_unauthorized_multi_target_and_stale_drafts(tmp_path, fixture):
    scope = accepted_scope(tmp_path)
    incoming = scope.iteration_root / "incoming"
    shutil.copy2(PROPOSALS / fixture, incoming / fixture)
    with pytest.raises(Exception):
        stage_proposal(scope, f"proposal-{fixture.split('.')[0]}", f"incoming/{fixture}")


def test_a_failed_stage_leaves_the_proposal_id_reusable(tmp_path, monkeypatch):
    """Staging failure must not permanently burn the proposal ID.

    The staging writes created proposals/<id>/ before the live-target race check,
    and the guard at the top of stage_proposal then refused every retry -- with no
    verb anywhere that removes a half-staged proposal.
    """
    import session_doc.narration_wiki.proposals as proposals

    scope = accepted_scope(tmp_path)

    def out_of_space(*_args, **_kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(proposals, "write_json", out_of_space)
    with pytest.raises(OSError, match="no space left"):
        stage_proposal(scope, "proposal-001", "incoming/proposal.yaml")
    monkeypatch.undo()

    root = scope.iteration_root / "proposals"
    assert list(root.iterdir()) == []
    assert stage_proposal(scope, "proposal-001", "incoming/proposal.yaml")["state"] == "staged"
