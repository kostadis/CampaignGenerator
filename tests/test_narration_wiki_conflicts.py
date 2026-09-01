from pathlib import Path

import pytest

from session_doc.narration_wiki.models import CompanionCapabilityManifest, ValidationError


def test_seed_capability_never_chooses_a_source_automatically():
    with pytest.raises(ValidationError):
        CompanionCapabilityManifest.from_mapping({
            "schema_version": 1,
            "source_repository": "fixture",
            "source_revision": "rev",
            "narration_wiki_contract": 1,
            "guidance_source": "campaign-resolved",
            "capabilities": ["proposer"],
        })
