"""CLI to HTTP adapter parity for the complete promotion and claims surface."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipelines.summary_native.review.web.app import create_review_app
from campaignlib.review_config import ReviewConfig
from server.platform_config_service import PlatformConfigService
from server.routers import summary_native as routes
from server.routers import review_routes
from server.subprocess_runner import console_script

FACTORY_PATH = Path(__file__).parent / "fixtures/summary_native/promotion/create_campaign.py"
SPEC = importlib.util.spec_from_file_location("parity_factory", FACTORY_PATH)
assert SPEC and SPEC.loader
FACTORY = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(FACTORY)


def _request(root: Path):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(platform=PlatformConfigService(root))))


@pytest.fixture
def campaign(tmp_path: Path) -> Path:
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    for name in ("selection.json", "candidates.json", "report.json"):
        (root / name).write_text("{}\n")
    return root


def _normalize(root: Path, command: list[str]) -> list[str]:
    return [
        "summary_native" if value == console_script("summary_native") else
        "migrate_grounding_bundle" if value == console_script("migrate_grounding_bundle") else
        "CONFIG" if value == str(root / "config/grounding.yaml") else
        "ROOT" if value == str(root) else value
        for value in command
    ]


def test_claims_routes_preserve_every_cli_option_stdin_and_envelope(campaign: Path, monkeypatch) -> None:
    calls = []
    envelope = {"ok": True, "code": "OK", "message": "done", "artifacts": [], "data": {"typed": True}}

    async def run(command, **kwargs):
        calls.append((_normalize(campaign, command), kwargs)); return envelope

    monkeypatch.setattr(routes, "run_bounded_json", run)
    request = _request(campaign)
    object_selection = {"schema_version": 1, "selection_digest": "a" * 64}
    operations = [
        routes.claims_selection_save(request, routes.ClaimsSelectionSaveRequest(selection="selection.json")),
        routes.claims_selection_save(request, routes.ClaimsSelectionSaveRequest(selection=object_selection, reviewer="GM")),
        routes.claims_extract(request, routes.ClaimsExtractRequest(selection="selection.json", backend="local", model="model-x", max_tokens=123, chunk_chars=456, force=True)),
        routes.claims_import(request, routes.ClaimsImportRequest(selection="selection.json", candidates="candidates.json")),
        routes.claims_disposition(request, routes.ClaimsDispositionRequest(review="review-1", item="finding-1", expected_decision_revision=7, disposition="accept_uncertainty", rationale="Exact rationale")),
    ]
    assert [asyncio.run(value) for value in operations] == [envelope] * len(operations)
    assert [value[0] for value in calls] == [
        ["summary_native", "claims", "selection", "save", "--input", str(campaign / "selection.json"), "--config", "CONFIG", "--json"],
        ["summary_native", "claims", "selection", "save", "--input", "-", "--reviewer", "GM", "--config", "CONFIG", "--json"],
        ["summary_native", "claims", "extract", "--selection", str(campaign / "selection.json"), "--backend", "local", "--model", "model-x", "--max-tokens", "123", "--chunk-chars", "456", "--force", "--config", "CONFIG", "--json"],
        ["summary_native", "claims", "import", "--selection", str(campaign / "selection.json"), "--candidates", str(campaign / "candidates.json"), "--config", "CONFIG", "--json"],
        ["summary_native", "claims", "prepare-disposition", "--review", "review-1", "--item", "finding-1", "--expected-decision-revision", "7", "--disposition", "accept_uncertainty", "--rationale", "Exact rationale", "--config", "CONFIG", "--json"],
    ]
    assert calls[1][1]["stdin_bytes"] == json.dumps(object_selection, sort_keys=True, separators=(",", ":")).encode()
    assert all(kwargs["cwd"] == str(campaign) and kwargs["save_run_log"] is False for _cmd, kwargs in calls)


def test_promotion_and_every_migration_mode_have_exact_cli_argv(campaign: Path) -> None:
    preview = routes.PromotionPreviewRequest(since=1, until=3, review="review-1", check_report="report-1", out_root="docs/summary_native")
    commit = routes.PromotionCommitRequest(**preview.model_dump(), preview_sha256="a" * 64, request_id="request-1")
    assert _normalize(campaign, routes._promotion_preview_command(campaign, preview)) == [
        "summary_native", "promote", "--config", "CONFIG", "--since", "1", "--until", "3",
        "--review", "review-1", "--check-report", "report-1", "--dry-run", "--json", "--out-root", "docs/summary_native",
    ]
    committed = _normalize(campaign, routes._promotion_commit_command(campaign, commit))
    assert "--dry-run" not in committed and committed[-4:] == ["--preview-sha256", "a" * 64, "--request-id", "request-1"]
    assert [_normalize(campaign, routes._promotion_inspection_command(campaign, action, "op-1")) for action in ("status", "receipt", "recover")] == [
        ["summary_native", "promotion", action, "--config", "CONFIG", "--operation", "op-1", "--json"]
        for action in ("status", "receipt", "recover")
    ]
    assert [_normalize(campaign, routes._migration_command(campaign, mode, "x")) for mode in ("dry-run", "apply", "status", "verify", "recover")] == [
        ["migrate_grounding_bundle", "--campaign-dir", "ROOT", "--dry-run", "--json"],
        ["migrate_grounding_bundle", "--campaign-dir", "ROOT", "--plan-sha256", "x", "--json"],
        ["migrate_grounding_bundle", "--campaign-dir", "ROOT", "--status", "--json"],
        ["migrate_grounding_bundle", "--campaign-dir", "ROOT", "--verify", "--json"],
        ["migrate_grounding_bundle", "--campaign-dir", "ROOT", "--recover", "--operation", "x", "--json"],
    ]


def test_four_signoff_cli_shape_and_private_capability_surface(campaign: Path, monkeypatch) -> None:
    digest = "b" * 64
    commands = [
        ["review", "document", "sign", "review-1", "--item", f"document-{name}",
         "--document-sha256", digest, "--expected-decision-revision", "0", "--reviewer", "GM"]
        for name in ("world_state", "campaign_state", "party", "planning")
    ]
    assert len(commands) == 4 and {command[5] for command in commands} == {
        "document-world_state", "document-campaign_state", "document-party", "document-planning"
    }
    captured = []
    async def fake_run(root, *arguments):
        captured.append((root, list(arguments))); return {"ok": True}
    monkeypatch.setattr(review_routes, "_root", lambda _request: campaign)
    monkeypatch.setattr(review_routes, "_run", fake_run)
    for command in commands:
        payload = review_routes.DocumentSignRequest(
            item=command[5], document_sha256=digest, expected_decision_revision=0, reviewer="GM"
        )
        asyncio.run(review_routes.document_sign(object(), "review-1", payload))
    assert [arguments for _root, arguments in captured] == [command[1:] for command in commands]
    app = create_review_app(campaign, "review-1", ReviewConfig.model_validate({
        "origin": "http://review.test", "bind_host": "127.0.0.1", "port": 8765,
    }))
    paths = {route.path for route in app.routes}
    forbidden = ("publish", "promote", "migrate", "model", "extract")
    assert not any(any(word in path for word in forbidden) for path in paths)
