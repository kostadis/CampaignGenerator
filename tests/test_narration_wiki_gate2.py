from session_doc.narration_wiki.models import StateError
from session_doc.narration_wiki.storage import finalize_proposal
from tests.test_narration_wiki_patches import accepted_scope


def test_gate2_requires_after_measurement(tmp_path):
    from session_doc.narration_wiki.proposals import apply_proposal, stage_proposal
    scope = accepted_scope(tmp_path)
    stage_proposal(scope, "proposal-001", "incoming/proposal.yaml")
    apply_proposal(scope, "proposal-001")
    try:
        finalize_proposal(scope, "proposal-001", "accept")
    except StateError as exc:
        assert "after measurement" in str(exc)
    else:
        raise AssertionError("Gate 2 accepted without after measurement")
