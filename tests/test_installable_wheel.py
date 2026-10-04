"""Release smoke for the artifact users actually install (issue #494)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from helpers.installed_distribution import InstalledDistribution, build_installed_distribution


@pytest.fixture(scope="module")
def installed(tmp_path_factory: pytest.TempPathFactory) -> InstalledDistribution:
    return build_installed_distribution(tmp_path_factory.mktemp("installed-wheel"))


def _installed_files(installed: InstalledDistribution) -> dict[str, str]:
    result = installed.run(
        str(installed.python), "-c",
        "import campaignlib; print(campaignlib.__file__)",
    )
    site = Path(result.stdout.strip()).resolve().parent.parent
    package_names = (
        "campaignlib", "session_doc", "server", "pipelines", "entity_registry",
        "scabard_sdk", "provenance",
    )
    return {
        str(path.relative_to(site)): hashlib.sha256(path.read_bytes()).hexdigest()
        for name in package_names
        for path in (site / name).rglob("*")
        if path.is_file()
    }


def test_wheel_contains_shipped_resources(installed: InstalledDistribution) -> None:
    members = installed.members()
    assert "session_doc/review/reviewer.html" in members
    assert "campaignlib/resources/system_prompt.md" in members
    assert "campaignlib/resources/agents/citation_rules_extract.md" in members
    assert not any(member.startswith("frontend/") for member in members)


def test_imports_and_commands_work_away_from_checkout(installed: InstalledDistribution) -> None:
    installed.run(
        str(installed.python), "-c",
        "import campaignlib, session_doc, pipelines, entity_registry, provenance",
    )
    installed.run(
        str(installed.python), "-c",
        "import pipelines.ensemble.ensemble, pipelines.ensemble.ensemble_batch, "
        "pipelines.ensemble.ensemble_extract, pipelines.grounding.grounding_sections, "
        "pipelines.grounding.event_spine, pipelines.grounding.thread_registry, "
        "pipelines.grounding.build_recent_events, server.routers.connections, "
        "server.routers.scene_editor",
    )
    for command in ("registry", "distill", "sd_verify_quotes"):
        installed.run(str(installed.scripts / command), "--help")
    for command in ("ensemble", "ensemble_batch", "grounding_sections"):
        installed.run(str(installed.scripts / command), "--help")
    installed.run(str(installed.scripts / "migrate_wiring"), "--help")


def test_installed_command_writes_only_to_workspace(installed: InstalledDistribution) -> None:
    before = _installed_files(installed)
    workspace = installed.away / "workspace"
    installed.run(str(installed.scripts / "new_workspace"), str(workspace))
    assert (workspace / "config" / "config.yaml").is_file()
    assert _installed_files(installed) == before


def test_installed_campaign_prompt_override_and_fallback(installed: InstalledDistribution) -> None:
    prompt = installed.away / "config" / "agents" / "citation_rules_extract.md"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("LOCAL OVERRIDE\n", encoding="utf-8")
    probe = (
        "from campaignlib import load_agent_prompt; "
        "print(load_agent_prompt('citation_rules_extract').strip())"
    )
    assert installed.run(str(installed.python), "-c", probe).stdout.strip() == "LOCAL OVERRIDE"
    prompt.unlink()
    assert installed.run(str(installed.python), "-c", probe).stdout.strip() != "LOCAL OVERRIDE"


def test_installed_copy_reads_explicit_external_wiring(installed: InstalledDistribution) -> None:
    wiring = installed.away / "wiring.yaml"
    wiring.write_text("dgx_endpoint: http://example.invalid:8000\n", encoding="utf-8")
    result = installed.run(
        str(installed.python), "-c",
        "from campaignlib import wiring_get; print(wiring_get('dgx_endpoint'))",
        env_extra={"MNEME_WIRING": str(wiring)},
    )
    assert result.stdout.strip() == "http://example.invalid:8000"


def test_installed_migrator_moves_temporary_legacy_wiring(installed: InstalledDistribution) -> None:
    checkout = installed.away / "old-checkout"
    source = checkout / "config" / "wiring.yaml"
    source.parent.mkdir(parents=True)
    source.write_text("dgx_endpoint: http://example.invalid:9000\n", encoding="utf-8")
    target = installed.away / "new-config" / "wiring.yaml"
    installed.run(
        str(installed.scripts / "migrate_wiring"),
        "--source-checkout", str(checkout), "--target", str(target),
    )
    assert not source.exists() and target.is_file()
    result = installed.run(
        str(installed.python), "-c",
        "from campaignlib import wiring_get; print(wiring_get('dgx_endpoint'))",
        env_extra={"MNEME_WIRING": str(target)},
    )
    assert result.stdout.strip() == "http://example.invalid:9000"
