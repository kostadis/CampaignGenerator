import ast
import inspect
from pathlib import Path

import pytest
from pydantic import ValidationError

from server.routers import narration_wiki


def test_router_exposes_status_and_all_nine_post_sse_actions():
    methods = {(route.path, next(iter(route.methods))) for route in narration_wiki.router.routes}
    assert ("/status", "GET") in methods
    posts = {path for path, method in methods if method == "POST"}
    assert posts == {
        "/collect", "/measure", "/index-check", "/conflict-rule", "/pattern-rule",
        "/proposal-stage", "/proposal-apply", "/proposal-rule", "/recover",
    }


def test_fixed_builder_has_no_arbitrary_argv():
    scope = narration_wiki.ScopeRequest(campaign_id="campaign", session_relative="sessions/one", iteration_id="iter-001")
    command = narration_wiki.build_command(scope, "status")
    assert command[1] == "status"
    assert command[-1] == "--json"
    assert "." in command and "sessions/one" in command


def test_router_never_launches_a_process_directly():
    tree = ast.parse(inspect.getsource(narration_wiki))
    forbidden = {"create_subprocess_exec", "run", "Popen"}
    calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not (calls & forbidden)


@pytest.mark.parametrize("source_ref", ["/etc/passwd", "../outside.md", "nested/../../outside.md", ".", ".."])
def test_evidence_binding_rejects_uncontained_source_refs(source_ref: str):
    with pytest.raises(ValidationError, match="relative collected artifact"):
        narration_wiki.EvidenceBinding(
            source_ref=source_ref,
            source_sha256="a" * 64,
            applies_to_kind="rule",
            applies_to_key="dialogue-density",
        )


def test_malformed_iteration_id_is_a_validation_error_not_a_server_fault():
    """require_stable_id raises NarrationWikiError, which is not a ValueError.

    Pydantic converts only ValueError/AssertionError into a ValidationError, so
    the refusal escaped the model and every POST carrying a malformed iteration
    ID returned a 500 whose only browser-visible trace was "Stream request
    failed (500)".
    """
    with pytest.raises(ValidationError, match="iteration-id"):
        narration_wiki.ScopeRequest(
            campaign_id="campaign",
            session_relative="sessions/one",
            iteration_id="ITER 001!",
        )


@pytest.mark.parametrize("query", [
    {"campaign_id": "c", "session_relative": "/etc", "iteration_id": "iter-001"},
    {"campaign_id": "c", "session_relative": "../outside", "iteration_id": "iter-001"},
    {"campaign_id": "c", "session_relative": "sessions/one", "iteration_id": "ITER 001!"},
])
def test_status_renders_a_malformed_scope_as_a_refusal_not_a_server_fault(query):
    """GET /status built its model above the try, so its 400 handler never fired."""
    from fastapi.testclient import TestClient

    from server.main import app

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/narration-wiki/status", params=query)
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "invalid_request"
