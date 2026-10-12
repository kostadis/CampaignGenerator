"""Regression tests for the #548 review findings on the promotion/claims routes.

Each test names the defect it pins. The routes are typed adapters over the
installed ``summary_native`` CLI (Principle VI), so most assertions are on the
exact argv a route hands the subprocess runner.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from server.platform_config_service import PlatformConfigService
from server.routers import review_routes
from server.routers import summary_native as routes
from server.subprocess_runner import console_script


@pytest.fixture
def campaign(tmp_path: Path) -> Path:
    root = tmp_path / "campaign"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("{}\n", encoding="utf-8")
    (root / "config" / "grounding.yaml").write_text("{}\n", encoding="utf-8")
    for name in ("selection.json", "candidates.json", "report.json"):
        (root / name).write_text("{}\n", encoding="utf-8")
    return root.resolve()


def _request(root: Path):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(platform=PlatformConfigService(root))))


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    commands: list[list[str]] = []

    async def fake_run(command, **_kwargs):
        commands.append(command)
        return {"ok": True, "code": "OK", "message": "done", "artifacts": [], "data": {}}

    monkeypatch.setattr(routes, "run_bounded_json", fake_run)
    return commands


def _preview(**overrides) -> routes.PromotionPreviewRequest:
    body = {"since": 1, "until": 3, "review": "review-1", "check_report": "report-1", **overrides}
    return routes.PromotionPreviewRequest.model_validate(body)


def _commit(**overrides) -> routes.PromotionCommitRequest:
    body = {"since": 1, "until": 3, "review": "review-1", "check_report": "report-1",
            "preview_sha256": "a" * 64, "request_id": "request-1", **overrides}
    return routes.PromotionCommitRequest.model_validate(body)


def _config_value(command: list[str]) -> str:
    return command[command.index("--config") + 1]


def _every_promotion_and_claims_call(request):
    return [
        routes.promotion_preview(request, _preview()),
        routes.promotion_commit(request, _commit()),
        routes.promotion_status(request),
        routes.promotion_receipt(request, routes.PromotionOperationRequest(operation="op-1")),
        routes.promotion_recover(request, routes.PromotionOperationRequest(operation="op-1")),
        routes.claims_select(request, routes.ClaimsSelectRequest(since=1, until=3)),
        routes.claims_selection_save(request, routes.ClaimsSelectionSaveRequest(selection="selection.json")),
        routes.claims_selection_chunks(request, routes.ClaimsChunkSelectionRequest(selection={}, source_ids=["s"])),
        routes.claims_extract(request, routes.ClaimsExtractRequest(selection="selection.json")),
        routes.claims_import(request, routes.ClaimsImportRequest(selection="selection.json", candidates="candidates.json")),
        routes.claims_review(request, routes.ClaimsReviewRequest(selection="selection.json", review="review-1")),
        routes.claims_check(request, routes.ClaimsCheckRequest(selection="selection.json", review="review-1")),
        routes.claims_show(request, routes.ClaimsShowRequest(report="report.json")),
        routes.claims_disposition(request, routes.ClaimsDispositionRequest(
            review="review-1", item="f-1", expected_decision_revision=0, disposition="dismiss", rationale="r")),
    ]


def test_promotion_and_claims_routes_pass_config_yaml_not_grounding_yaml(campaign, captured):
    """Defect: promote / promotion / claims routes passed ``config/grounding.yaml`` as ``--config``.

    Every summary_native subcommand's ``--config`` names ``config/config.yaml``;
    the CLI reads grounding.yaml from beside it and refuses grounding.yaml itself.
    """
    request = _request(campaign)
    for call in _every_promotion_and_claims_call(request):
        asyncio.run(call)
    assert len(captured) == 14
    for command in captured:
        assert _config_value(command) == str(campaign / "config" / "config.yaml"), command
        assert "grounding.yaml" not in " ".join(command)


def test_out_root_reaches_both_preview_and_commit_and_is_omitted_when_unset(campaign, captured):
    """Defect: ``--out-root`` had no UI face; the request model must carry it to preview AND commit.

    An unset out_root is a sentinel: the flag is absent and the CLI resolves the
    configured/default value itself (no route literal, Principle XII).
    """
    request = _request(campaign)
    asyncio.run(routes.promotion_preview(request, _preview(out_root="docs/other_root")))
    asyncio.run(routes.promotion_commit(request, _commit(out_root="docs/other_root")))
    asyncio.run(routes.promotion_preview(request, _preview()))
    asyncio.run(routes.promotion_commit(request, _commit()))
    for command in captured[:2]:
        assert command[command.index("--out-root") + 1] == "docs/other_root"
    for command in captured[2:]:
        assert "--out-root" not in command
    asyncio.run(routes.claims_select(request, routes.ClaimsSelectRequest(since=1, until=3, out_root="docs/other_root")))
    assert captured[-1][captured[-1].index("--out-root") + 1] == "docs/other_root"


def test_blank_out_root_is_refused_rather_than_forwarded():
    """Defect guard: an empty Out root field must mean "not sent", never ``--out-root ''``."""
    with pytest.raises(ValidationError):
        _preview(out_root="   ")


@pytest.mark.parametrize("action", ["preview", "commit"])
@pytest.mark.parametrize("value", ["../outside/report.json", "/etc/report.json", "..", "."])
def test_check_report_path_outside_the_campaign_is_refused(campaign, captured, action, value):
    """Defect: promotion preview/commit forwarded ``check_report`` unvalidated.

    A path now gets the claims routes' ``_authority_path`` containment; nothing
    reaches the subprocess when it escapes the campaign.
    """
    request = _request(campaign)
    call = routes.promotion_preview(request, _preview(check_report=value)) if action == "preview" \
        else routes.promotion_commit(request, _commit(check_report=value))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(call)
    assert caught.value.status_code == 400
    assert captured == []


@pytest.mark.parametrize(("value", "expected"), [
    ("report-1", "report-1"),                      # a report id: the CLI resolves it in its checks store
    ("claims-unavailable", "claims-unavailable"),  # the CLI's declared sentinel
    ("report.json", "report.json"),                # a bare file name is resolved by the CLI too
    ("docs/summary_native/ch001-003/state/promotion/checks/a/report.json",
     "CAMPAIGN/docs/summary_native/ch001-003/state/promotion/checks/a/report.json"),
])
def test_check_report_id_is_forwarded_and_contained_path_is_resolved(campaign, captured, value, expected):
    """Defect companion: validation must not rewrite a report id the CLI resolves itself."""
    asyncio.run(routes.promotion_preview(_request(campaign), _preview(check_report=value)))
    asyncio.run(routes.promotion_commit(_request(campaign), _commit(check_report=value)))
    for command in captured:
        assert command[command.index("--check-report") + 1] == expected.replace("CAMPAIGN", str(campaign))


def test_request_id_stays_bounded_at_96_characters():
    """Defect: the request id bound must match the CLI's (it rejects ids over 96 characters)."""
    _commit(request_id="r" * 96)
    with pytest.raises(ValidationError):
        _commit(request_id="r" * 97)


def test_ui_generated_request_ids_fit_the_route_bound():
    """Defect: the UI's request-id field must not be able to produce an id the route rejects.

    The Request ID input is bounded to the route's 96 characters and its pattern.
    """
    source = (Path(__file__).parents[1] / "frontend/src/components/GroundingPromotion.vue").read_text(encoding="utf-8")
    assert 'maxlength="96"' in source
    assert "REQUEST_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$/" in source


def test_no_invented_claims_review_default_in_the_ui():
    """Defect: the UI pre-filled review id ``'claims-review'``, a value the CLI never declares (X/XII)."""
    frontend = Path(__file__).parents[1] / "frontend/src"
    for relative in ("components/GroundingClaims.vue", "components/GroundingPromotion.vue",
                     "views/grounding/GroundingPromote.vue"):
        assert "'claims-review'" not in (frontend / relative).read_text(encoding="utf-8"), relative


def test_retired_document_routes_run_the_installed_cli_and_relay_its_refusal(campaign):
    """Defect: ``/document/prepare|promote`` returned a hand-built DOCUMENT_PROMOTION_RETIRED/410.

    They now run ``summary_native review document prepare|promote`` and relay the
    CLI's PROMOTION_WHOLE_BUNDLE_REQUIRED with the router's own status mapping.
    """
    if not Path(console_script("summary_native")).exists():
        pytest.skip("summary_native console script is not installed in this environment")
    app = FastAPI()
    app.include_router(review_routes.router, prefix="/api/reviews")
    app.state.platform = PlatformConfigService(campaign)
    client = TestClient(app)
    for action in ("prepare", "promote"):
        response = client.post(f"/api/reviews/review-1/document/{action}", json={"selection": "selection.json"})
        body = response.json()
        assert body["code"] == "PROMOTION_WHOLE_BUNDLE_REQUIRED", body
        assert body["ok"] is False
        assert "summary_native promote" in body["message"]
        assert response.status_code == review_routes._status_for("PROMOTION_WHOLE_BUNDLE_REQUIRED")


def test_retired_document_routes_keep_campaign_containment(campaign, monkeypatch):
    """Defect companion: relaying the CLI must not forward a path outside the campaign."""
    calls = []

    async def fake_run(command, **_kwargs):
        calls.append(command)
        return {}

    monkeypatch.setattr(review_routes, "run_bounded_json", fake_run)
    app = FastAPI()
    app.include_router(review_routes.router, prefix="/api/reviews")
    app.state.platform = PlatformConfigService(campaign)
    client = TestClient(app)
    response = client.post("/api/reviews/review-1/document/prepare", json={"selection": "../elsewhere.json"})
    assert response.status_code == 400
    assert calls == []
    assert json.loads(response.content)["detail"].endswith("must stay inside the active campaign")


def test_scope_ruling_has_a_face_and_reaches_the_cli_unchanged(campaign, monkeypatch):
    """Defect: no command or route recorded the GM's scope choice, so a selection with an
    unresolved scope entry could only be confirmed by deleting the entry from the JSON."""
    seen: dict = {}

    async def fake_run(command, **kwargs):
        seen["command"], seen["stdin"] = command, kwargs.get("stdin_bytes")
        return {"ok": True, "code": "OK", "message": "scope resolution recorded", "artifacts": [], "data": {}}

    monkeypatch.setattr(routes, "run_bounded_json", fake_run)
    body = routes.ClaimsScopeResolutionRequest(
        selection={"unresolved_scope": ["PREP note"]}, entry="PREP note", choice="not_applicable",
        rationale="Planning only", reviewer="GM",
    )
    asyncio.run(routes.claims_selection_resolve_scope(_request(campaign), body))
    command = seen["command"]
    assert command[1:4] == ["claims", "selection", "resolve-scope"]
    for flag, value in (("--input", "-"), ("--entry", "PREP note"), ("--choice", "not_applicable"),
                        ("--rationale", "Planning only"), ("--reviewer", "GM")):
        assert command[command.index(flag) + 1] == value
    assert _config_value(command) == str(campaign / "config" / "config.yaml")
    assert json.loads(seen["stdin"]) == {"unresolved_scope": ["PREP note"]}
    with pytest.raises(ValidationError):
        routes.ClaimsScopeResolutionRequest(selection={}, entry="x", choice="maybe", rationale="r", reviewer="GM")
