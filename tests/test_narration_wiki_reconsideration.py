import shutil
from pathlib import Path

import pytest

from session_doc.narration_wiki.models import ValidationError
from session_doc.narration_wiki.proposals import stage_proposal
from tests.test_narration_wiki_patches import PROPOSALS, accepted_scope


def test_reconsideration_forms_are_mutually_exclusive(tmp_path):
    scope = accepted_scope(tmp_path)
    digest = __import__("json").loads((scope.iteration_root / "trace-manifest.json").read_text())["artifacts"][0]["sha256"]
    with pytest.raises(ValidationError, match="mutually exclusive"):
        stage_proposal(scope, "proposal-001", "incoming/proposal.yaml", evidence_bindings=[{
            "source_ref": "narration/Aria.md",
            "source_sha256": digest,
            "applies_to_kind": "rule",
            "applies_to_key": "bookkeeping-per-narrator",
        }], override_rationale="GM override")
