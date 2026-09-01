from pathlib import Path

import pytest
import yaml

from campaignlib.narration_context import resolve_narration_guidance
from session_doc.narration_wiki.models import ScopeError


def _campaign(tmp_path: Path) -> Path:
    campaign = tmp_path / "campaign"
    (campaign / "config").mkdir(parents=True)
    (campaign / "voice").mkdir()
    (campaign / "examples").mkdir()
    (campaign / "voice" / "_genre.md").write_text("# Rules\n")
    (campaign / "voice" / "Aria.md").write_text("# Aria\n")
    (campaign / "examples" / "Aria.one.md").write_text("# Example\n")
    (campaign / "config" / "session_doc.yaml").write_text(yaml.safe_dump({"paths": {
        "genre_file": "voice/_genre.md", "voice_dir": "voice", "examples_dir": "examples",
    }}))
    return campaign


def test_resolver_reads_only_configured_campaign_paths_and_creates_nothing(tmp_path):
    campaign = _campaign(tmp_path)
    before = sorted(path.relative_to(campaign) for path in campaign.rglob("*"))
    guidance = resolve_narration_guidance(campaign, require_rulebook=True)
    assert guidance.rulebook.path == "voice/_genre.md"
    assert list(guidance.voice_files) == ["Aria"]
    assert guidance.example_files["Aria"][0].path == "examples/Aria.one.md"
    assert before == sorted(path.relative_to(campaign) for path in campaign.rglob("*"))


def test_resolver_never_falls_back_or_borrows_another_campaign(tmp_path):
    campaign = _campaign(tmp_path)
    other = _campaign(tmp_path / "other")
    (campaign / "config" / "session_doc.yaml").write_text("paths: {}\n")
    guidance = resolve_narration_guidance(campaign)
    assert guidance.rulebook is None
    with pytest.raises(ScopeError):
        resolve_narration_guidance(campaign, paths={"genre_file": str(other / "voice" / "_genre.md")})
