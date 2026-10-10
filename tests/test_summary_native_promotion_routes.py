from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from pipelines.summary_native import cli as summary_native_cli
from server.routers import summary_native as summary_native_routes
from server.platform_config_service import PlatformConfigService
from server.subprocess_runner import console_script


BASE = "/api/grounding/summary-native/promotion/preview"
FACTORY_PATH = Path(__file__).parent / "fixtures/summary_native/promotion/create_campaign.py"
SPEC = importlib.util.spec_from_file_location("promotion_route_factory", FACTORY_PATH)
assert SPEC and SPEC.loader
FACTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FACTORY)
DOCUMENTS = ("world_state", "campaign_state", "party", "planning")
TIMELINE = "canon_events_timeline.md"


def _tree(root: Path) -> tuple[tuple[str, str, str], ...]:
    result: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            result.append((relative, "symlink", os.readlink(path)))
        elif path.is_dir():
            result.append((relative, "directory", ""))
        else:
            result.append((relative, "file", hashlib.sha256(path.read_bytes()).hexdigest()))
    return tuple(result)


def _managed(root: Path) -> Path:
    return FACTORY.initialize_managed(root)


@pytest.fixture
def campaign(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = _managed(FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy"))
    return root


def _request(root: Path):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(platform=PlatformConfigService(root))))


def _json_response(value):
    if isinstance(value, dict):
        return 200, value
    return value.status_code, json.loads(value.body)


def _body() -> dict[str, object]:
    return {
        "since": 1,
        "until": 3,
        "review": "promotion-check",
        "check_report": "claims-unavailable",
        "out_root": "docs/summary_native",
    }


def _cli_argv(root: Path) -> list[str]:
    return [
        "promote",
        "--config", str(root / "config/grounding.yaml"),
        "--since", "1",
        "--until", "3",
        "--review", "promotion-check",
        "--check-report", "claims-unavailable",
        "--dry-run",
        "--json",
        "--out-root", "docs/summary_native",
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"until": 3, "review": "r", "check_report": "claims-unavailable"},
        {"since": 1, "review": "r", "check_report": "claims-unavailable"},
        {"since": 1, "until": 3, "check_report": "claims-unavailable"},
        {"since": 1, "until": 3, "review": "r"},
        {"since": 4, "until": 3, "review": "r", "check_report": "claims-unavailable"},
    ],
)
def test_preview_requires_an_explicit_complete_selection(campaign: Path, payload: dict) -> None:
    with pytest.raises(ValidationError):
        summary_native_routes.PromotionPreviewRequest.model_validate(payload)


def test_route_is_a_typed_installed_cli_adapter(
    campaign: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    expected = {"ok": False, "code": "PROMOTION_BLOCKED", "message": "review needed", "data": {"x": 1}}

    async def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return expected

    monkeypatch.setattr("server.routers.summary_native.run_bounded_json", fake_run)
    response = asyncio.run(summary_native_routes.promotion_preview(
        _request(campaign), summary_native_routes.PromotionPreviewRequest.model_validate(_body())
    ))
    status, body = _json_response(response)
    assert status == 200
    assert body == expected
    assert captured["cmd"] == [console_script("summary_native"), *_cli_argv(campaign)]
    kwargs = captured["kwargs"]
    assert kwargs["cwd"] == str(campaign)
    assert kwargs["save_run_log"] is False


def test_preview_is_mounted_at_the_frontend_api_path() -> None:
    from server.main import app
    paths = set(app.openapi()["paths"])
    assert BASE in paths
    assert "/api/summary-native/promotion/preview" not in paths


def test_route_matches_cli_preview_and_both_are_zero_write(
    campaign: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _tree(campaign)
    direct_exit = summary_native_cli.main(_cli_argv(campaign))
    direct = json.loads(capsys.readouterr().out)
    assert direct_exit == 5  # claims unavailable is an honest blocked preview
    assert _tree(campaign) == before

    from server.subprocess_runner import BoundedJSONError

    async def installed_cli_result(cmd, **_kwargs):
        assert cmd == [console_script("summary_native"), *_cli_argv(campaign)]
        # run_bounded_json preserves a valid nonzero CLI envelope this way.
        raise BoundedJSONError(
            direct["message"], returncode=direct_exit, category="nonzero_exit", payload=direct
        )

    monkeypatch.setattr("server.routers.summary_native.run_bounded_json", installed_cli_result)

    response = asyncio.run(summary_native_routes.promotion_preview(
        _request(campaign), summary_native_routes.PromotionPreviewRequest.model_validate(_body())
    ))
    status, body = _json_response(response)
    assert status == 200
    assert body == direct
    assert _tree(campaign) == before


def test_non_json_process_failure_is_sanitized(
    campaign: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from server.subprocess_runner import BoundedJSONError

    async def failed(*_args, **_kwargs):
        raise BoundedJSONError("private child detail", category="process_failure")

    monkeypatch.setattr("server.routers.summary_native.run_bounded_json", failed)
    response = asyncio.run(summary_native_routes.promotion_preview(
        _request(campaign), summary_native_routes.PromotionPreviewRequest.model_validate(_body())
    ))
    status, body = _json_response(response)
    assert status == 503
    assert body == {
        "ok": False,
        "code": "PROMOTION_COMMAND_FAILED",
        "message": "Promotion preview failed safely.",
    }
    assert "private child detail" not in json.dumps(body)


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (lambda request: summary_native_routes.promotion_status(request),
         ["summary_native", "promotion", "status", "--config", "CONFIG", "--json"]),
        (lambda request: summary_native_routes.promotion_receipt(request, summary_native_routes.PromotionOperationRequest(operation="op-1")),
         ["summary_native", "promotion", "receipt", "--config", "CONFIG", "--operation", "op-1", "--json"]),
        (lambda request: summary_native_routes.promotion_recover(request, summary_native_routes.PromotionOperationRequest(operation="op-1")),
         ["summary_native", "promotion", "recover", "--config", "CONFIG", "--operation", "op-1", "--json"]),
        (lambda request: summary_native_routes.migration_preview(request),
         ["migrate_grounding_bundle", "--campaign-dir", "ROOT", "--dry-run", "--json"]),
        (lambda request: summary_native_routes.migration_status(request),
         ["migrate_grounding_bundle", "--campaign-dir", "ROOT", "--status", "--json"]),
        (lambda request: summary_native_routes.migration_verify(request),
         ["migrate_grounding_bundle", "--campaign-dir", "ROOT", "--verify", "--json"]),
        (lambda request: summary_native_routes.migration_recover(request, summary_native_routes.PromotionOperationRequest(operation="migration-1")),
         ["migrate_grounding_bundle", "--campaign-dir", "ROOT", "--recover", "--operation", "migration-1", "--json"]),
    ],
)
def test_inspection_and_migration_routes_are_exact_installed_cli_adapters(
    campaign: Path, monkeypatch: pytest.MonkeyPatch, call, expected: list[str]
) -> None:
    captured = {}

    async def fake_run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        return {"ok": True, "code": "OK", "message": "done", "data": {}}

    monkeypatch.setattr(summary_native_routes, "run_bounded_json", fake_run)
    asyncio.run(call(_request(campaign)))
    normalized = [
        "CONFIG" if item == str(campaign / "config/grounding.yaml") else
        "ROOT" if item == str(campaign) else
        Path(item).name if item in {console_script("summary_native"), console_script("migrate_grounding_bundle")} else item
        for item in captured["command"]
    ]
    assert normalized == expected
    assert captured["kwargs"]["cwd"] == str(campaign)
    assert captured["kwargs"]["save_run_log"] is False


def test_commit_and_migration_apply_forward_only_typed_digest_bound_inputs(
    campaign: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = []

    async def fake_run(command, **_kwargs):
        commands.append(command)
        return {"ok": True, "code": "OK", "message": "done", "data": {}}

    monkeypatch.setattr(summary_native_routes, "run_bounded_json", fake_run)
    commit = summary_native_routes.PromotionCommitRequest.model_validate({
        **_body(), "preview_sha256": "a" * 64, "request_id": "request-1",
    })
    asyncio.run(summary_native_routes.promotion_commit(_request(campaign), commit))
    apply = summary_native_routes.MigrationApplyRequest(plan_sha256="b" * 64)
    asyncio.run(summary_native_routes.migration_apply(_request(campaign), apply))
    assert "--dry-run" not in commands[0]
    assert commands[0][-4:] == ["--preview-sha256", "a" * 64, "--request-id", "request-1"]
    assert commands[1] == [console_script("migrate_grounding_bundle"), "--campaign-dir", str(campaign),
                           "--plan-sha256", "b" * 64, "--json"]


def test_all_promotion_adapters_are_mounted_under_the_actual_grounding_prefix() -> None:
    from server.main import app
    paths = set(app.openapi()["paths"])
    expected = {
        "/api/grounding/summary-native/promotion/commit",
        "/api/grounding/summary-native/promotion/status",
        "/api/grounding/summary-native/promotion/receipt",
        "/api/grounding/summary-native/promotion/recover",
        "/api/grounding/summary-native/promotion/migration/preview",
        "/api/grounding/summary-native/promotion/migration/apply",
        "/api/grounding/summary-native/promotion/migration/status",
        "/api/grounding/summary-native/promotion/migration/verify",
        "/api/grounding/summary-native/promotion/migration/recover",
    }
    assert expected <= paths


@pytest.mark.parametrize(("call", "expected"), [
    (lambda req, root: summary_native_routes.claims_select(req, summary_native_routes.ClaimsSelectRequest(since=1, until=3, out_root="docs/summary_native")),
     ["claims", "select", "--since", "1", "--until", "3", "--out-root", "docs/summary_native"]),
    (lambda req, root: summary_native_routes.claims_selection_save(req, summary_native_routes.ClaimsSelectionRequest(selection="selection.json")),
     ["claims", "selection", "save", "--input", "SELECTION"]),
    (lambda req, root: summary_native_routes.claims_extract(req, summary_native_routes.ClaimsExtractRequest(selection="selection.json", backend="offline", model="none", max_tokens=99, chunk_chars=1000, force=True)),
     ["claims", "extract", "--selection", "SELECTION", "--backend", "offline", "--model", "none", "--max-tokens", "99", "--chunk-chars", "1000", "--force"]),
    (lambda req, root: summary_native_routes.claims_import(req, summary_native_routes.ClaimsImportRequest(selection="selection.json", candidates="candidates.json")),
     ["claims", "import", "--selection", "SELECTION", "--candidates", "CANDIDATES"]),
    (lambda req, root: summary_native_routes.claims_review(req, summary_native_routes.ClaimsReviewRequest(selection="selection.json", candidates="candidates.json", review="MY-ID")),
     ["claims", "review", "--selection", "SELECTION", "--review", "MY-ID", "--candidates", "CANDIDATES"]),
    (lambda req, root: summary_native_routes.claims_check(req, summary_native_routes.ClaimsCheckRequest(selection="selection.json", review="MY-ID")),
     ["claims", "check", "--selection", "SELECTION", "--review", "MY-ID"]),
    (lambda req, root: summary_native_routes.claims_show(req, summary_native_routes.ClaimsShowRequest(report="report.json")),
     ["claims", "show", "--report", "REPORT"]),
    (lambda req, root: summary_native_routes.claims_disposition(req, summary_native_routes.ClaimsDispositionRequest(
        review="MY-ID", item="finding-1", expected_decision_revision=2,
        disposition="dismiss", rationale="Exact evidence supports dismissal.")),
     ["claims", "prepare-disposition", "--review", "MY-ID", "--item", "finding-1",
      "--expected-decision-revision", "2", "--disposition", "dismiss", "--rationale", "Exact evidence supports dismissal."]),
])
def test_claims_routes_are_exact_installed_cli_adapters(campaign, monkeypatch, call, expected):
    captured = {}
    async def fake_run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        return {"ok": True, "code": "OK", "message": "done", "data": {}}
    monkeypatch.setattr(summary_native_routes, "run_bounded_json", fake_run)
    asyncio.run(call(_request(campaign), campaign))
    replacements = {
        str(campaign / "selection.json"): "SELECTION",
        str(campaign / "candidates.json"): "CANDIDATES",
        str(campaign / "report.json"): "REPORT",
        str(campaign / "config/grounding.yaml"): "CONFIG",
    }
    normalized = [Path(value).name if value == console_script("summary_native") else replacements.get(value, value)
                  for value in captured["command"]]
    assert normalized == ["summary_native", *expected, "--config", "CONFIG", "--json"]
    assert captured["kwargs"]["cwd"] == str(campaign) and captured["kwargs"]["save_run_log"] is False


def test_claims_mutation_transport_loss_has_stable_unknown_ack(campaign, monkeypatch):
    from server.subprocess_runner import BoundedJSONError
    async def lost(*_args, **_kwargs):
        raise BoundedJSONError("lost", category="timeout")
    monkeypatch.setattr(summary_native_routes, "run_bounded_json", lost)
    response = asyncio.run(summary_native_routes.claims_import(
        _request(campaign), summary_native_routes.ClaimsImportRequest(
            selection="selection.json", candidates="candidates.json")))
    status, body = _json_response(response)
    assert status == 504 and body["code"] == "CLAIMS_COMMAND_UNKNOWN"


def test_claims_selection_object_uses_bounded_stdin_and_explicit_reviewer(campaign, monkeypatch):
    captured = {}
    async def fake_run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        return {"ok": True, "code": "OK", "message": "saved", "data": {}}
    monkeypatch.setattr(summary_native_routes, "run_bounded_json", fake_run)
    selection = {"schema_version": 1, "sources": [{"source_id": "required"}], "chunks": []}
    payload = summary_native_routes.ClaimsSelectionSaveRequest(selection=selection, reviewer="GM")
    asyncio.run(summary_native_routes.claims_selection_save(_request(campaign), payload))
    assert captured["command"][1:7] == ["claims", "selection", "save", "--input", "-", "--reviewer"]
    assert captured["command"][7] == "GM"
    assert json.loads(captured["kwargs"]["stdin_bytes"]) == selection


def test_claims_chunk_materialization_uses_cli_and_bounded_stdin(campaign, monkeypatch):
    captured = {}
    async def fake_run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        return {"ok": True, "code": "OK", "message": "chunks", "data": {}}
    monkeypatch.setattr(summary_native_routes, "run_bounded_json", fake_run)
    selection = {"schema_version": 1, "sources": [], "chunks": []}
    payload = summary_native_routes.ClaimsChunkSelectionRequest(selection=selection, source_ids=["source-a", "source-b"])
    asyncio.run(summary_native_routes.claims_selection_chunks(_request(campaign), payload))
    command = captured["command"]
    assert command[1:11] == ["claims", "selection", "chunks", "--input", "-", "--source", "source-a", "--source", "source-b", "--config"]
    assert json.loads(captured["kwargs"]["stdin_bytes"]) == selection


def test_claims_routes_mount_only_under_grounding_summary_native_prefix():
    from server.main import app
    paths = set(app.openapi()["paths"])
    expected = {f"/api/grounding/summary-native/claims/{suffix}" for suffix in (
        "select", "selection/save", "selection/chunks", "extract", "import", "review", "check", "show", "disposition")}
    assert expected <= paths
    assert not any(path.startswith("/api/summary-native/claims/") for path in paths)
