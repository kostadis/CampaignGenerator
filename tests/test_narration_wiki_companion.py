from pathlib import Path

from session_doc.narration_wiki.indexes import load_companion_capability
from session_doc.narration_wiki.paths import resolve_scope


FIXTURES = Path(__file__).parent / "fixtures" / "narration_wiki" / "portable"


def test_capability_requires_contract_one_campaign_resolution_and_both_roles(tmp_path):
    root = tmp_path / "portable"
    root.mkdir()
    (root / "capabilities.yaml").write_bytes((FIXTURES / "capabilities-valid.yaml").read_bytes())
    valid = load_companion_capability(root)
    assert valid["compatible"]
    assert valid["capabilities"] == ["maintainer", "proposer"]
    (root / "capabilities.yaml").write_bytes((FIXTURES / "capabilities-incompatible.yaml").read_bytes())
    invalid = load_companion_capability(root)
    assert invalid["present"] and not invalid["compatible"]


def test_missing_dependency_is_explicit_and_creates_nothing(tmp_path):
    root = tmp_path / "missing"
    assert load_companion_capability(root)["reason"] == "capabilities.yaml is missing"
    assert not root.exists()


def test_deployed_home_manifest_reports_repository_revision_and_both_roles(tmp_path, monkeypatch):
    home = tmp_path / "home"
    deployed = home / ".claude" / "narration-wiki"
    deployed.mkdir(parents=True)
    (deployed / "capabilities.yaml").write_bytes((FIXTURES / "capabilities-valid.yaml").read_bytes())
    campaign = tmp_path / "campaign"
    session = campaign / "sessions" / "one"
    session.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    scope = resolve_scope(campaign, session, "acceptance-001")
    result = load_companion_capability(scope.portable_root)
    assert result["compatible"]
    assert result["source_repository"] == "kostadis/narration-wiki-companion"
    assert result["source_revision"] == "fixture-revision"
    assert result["capabilities"] == ["maintainer", "proposer"]
