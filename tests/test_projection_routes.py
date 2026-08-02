"""Tests for the State Projection API routes (006-state-projection-service,
User Story 4, Phase 6, T034-T036).

Mirrors ``tests/test_grounding_config_service.py`` /
``tests/test_grounding_routes_config.py`` for the config round-trip and
isolation guarantees, and ``tests/test_ensemble_chapters.py`` /
``tests/test_ensemble_config_defaults.py`` for the "no silent all" and
no-drift-literal guards, applied to ``server/routers/projections.py`` and
``server/projection_config_service.py``.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.main import app  # noqa: E402
from server.platform_config_service import (  # noqa: E402
    PlatformConfigService,
    TRACKED_CONFIG_NAME,
)
from server.projection_config_service import ProjectionConfigService  # noqa: E402

client = TestClient(app)

ROUTER_SRC = Path(__file__).resolve().parent.parent / "server" / "routers" / "projections.py"


@pytest.fixture
def campaign(monkeypatch, tmp_path):
    """A booted platform in tmp_path, subprocess spawning stubbed out."""
    cfgdir = tmp_path / "config"
    cfgdir.mkdir(parents=True, exist_ok=True)
    (cfgdir / TRACKED_CONFIG_NAME).write_text(
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(app.state, "platform", PlatformConfigService(tmp_path),
                        raising=False)
    return ProjectionConfigService(cfgdir)


@pytest.fixture
def captured(monkeypatch):
    """Intercept stream_subprocess so tests see the argv without spawning
    anything real."""
    calls: list[list[str]] = []

    async def fake_stream_subprocess(cmd, cwd=None, env_extra=None, on_complete=None):
        calls.append(cmd)
        if on_complete:
            on_complete(0)
        return
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr("server.routers.projections.stream_subprocess",
                        fake_stream_subprocess)
    return calls


def _run(path: str, params: dict | None = None):
    r = client.get(path, params=params or {})
    _ = r.text  # drain the SSE generator so the fake subprocess (if any) runs
    return r


# ── T034: config round-trip, 400 on unknown key, deep-merge isolation ──────

def test_get_config_returns_defaults(campaign):
    r = client.get("/api/projections/config")
    assert r.status_code == 200
    body = r.json()
    assert body["stores"]["events"] == "docs/ensemble/events.jsonl"
    assert body["output"]["draft"] == "docs/projections/{doc}_draft.md"


def test_put_config_round_trips_a_grouped_partial(campaign):
    r = client.put("/api/projections/config",
                   json={"stores": {"events": "docs/alt/events.jsonl"}})
    assert r.status_code == 200
    assert r.json()["stores"]["events"] == "docs/alt/events.jsonl"

    r2 = client.get("/api/projections/config")
    assert r2.json()["stores"]["events"] == "docs/alt/events.jsonl"


def test_put_config_rejects_unknown_key(campaign):
    r = client.put("/api/projections/config", json={"stores": {"nope": 1}})
    assert r.status_code == 400


def test_put_config_rejects_draft_without_doc_placeholder(campaign):
    r = client.put("/api/projections/config",
                   json={"output": {"draft": "docs/projections/fixed.md"}})
    assert r.status_code == 400


def test_deep_merge_leaves_untouched_groups_intact(campaign):
    client.put("/api/projections/config",
              json={"stores": {"events": "docs/alt/events.jsonl"}})
    client.put("/api/projections/config",
              json={"inputs": {"party": "docs/alt_party.md"}})
    r = client.get("/api/projections/config")
    body = r.json()
    # The stores write from the first PUT survives a second PUT to a
    # different group untouched.
    assert body["stores"]["events"] == "docs/alt/events.jsonl"
    assert body["inputs"]["party"] == "docs/alt_party.md"
    # Everything else in `stores` stayed at its default.
    assert body["stores"]["thread_registry"] == "docs/thread_registry.yaml"


def test_projections_write_cannot_touch_sibling_documents(campaign, tmp_path):
    """Mirrors test_grounding_write_cannot_touch_sibling_documents — a
    projections write re-serializes only projections.yaml."""
    cfgdir = tmp_path / "config"
    siblings = {}
    for name, body in [
        ("grounding.yaml", "sections_dir: docs/grounding_sections\n"),
        ("ensemble.yaml", "chapters_selected: []\n"),
        ("platform.yaml", "runtime:\n  default_model: claude-sonnet-4-6\n"),
    ]:
        p = cfgdir / name
        p.write_text(body, encoding="utf-8")
        siblings[p] = p.read_bytes()

    r = client.put("/api/projections/config",
                   json={"stores": {"events": "docs/alt/events.jsonl"}})
    assert r.status_code == 200

    for p, before in siblings.items():
        assert p.read_bytes() == before, f"{p.name} was modified by a projections write"


# ── T035: /run/build rejects an empty `sections` with 400, never "all" ─────

def test_build_rejects_empty_sections(campaign, captured):
    r = client.get("/api/projections/run/build", params={"doc": "campaign_state"})
    assert r.status_code == 400
    assert "sections" in r.json()["detail"]
    assert not captured, "no subprocess may be spawned on a rejected build"


def test_build_rejects_blank_sections_entries(campaign, captured):
    """An explicitly-empty list (e.g. `sections=`) is refused identically —
    no glob/'all' fallback hiding behind a blank string."""
    r = client.get("/api/projections/run/build",
                   params={"doc": "campaign_state", "sections": ""})
    assert r.status_code == 400
    assert not captured


def test_build_with_sections_runs(campaign, captured):
    r = _run("/api/projections/run/build",
             {"doc": "campaign_state", "sections": ["recent_events"]})
    assert r.status_code == 200
    assert captured
    cmd = captured[-1]
    assert "--doc" in cmd and cmd[cmd.index("--doc") + 1] == "campaign_state"
    assert "--sections" in cmd and cmd[cmd.index("--sections") + 1] == "recent_events"


def test_build_never_expands_to_every_section_implicitly(campaign, captured):
    """A 422 from FastAPI's own required-param validation would also stop
    the subprocess, but it would not name the problem the way a 400 does —
    this is the behavioural half of Constitution X, not just the status code."""
    r = client.get("/api/projections/run/build", params={"doc": "campaign_state"})
    assert r.status_code == 400
    assert r.status_code != 422


# ── /run/recent-events: same "no silent all" contract for --corpus ─────────

def test_recent_events_rejects_empty_corpus(campaign, captured):
    r = client.get("/api/projections/run/recent-events")
    assert r.status_code == 400
    assert not captured


def test_recent_events_runs_with_corpus(campaign, captured):
    r = _run("/api/projections/run/recent-events",
             {"corpus": ["docs/ensemble/per_chapter/*/merged.json"]})
    assert r.status_code == 200
    cmd = captured[-1]
    assert "docs/ensemble/per_chapter/*/merged.json" in cmd
    assert "--output" in cmd and cmd[cmd.index("--output") + 1] == "docs/recent_events.md"
    assert "--store" in cmd and cmd[cmd.index("--store") + 1] == "docs/ensemble/events.jsonl"


# ── T036: no docs/-shaped literal in the router ─────────────────────────────
#
# AST-based (not a raw substring scan) so a comment or docstring that merely
# explains where output lands does not trip the guard — the defect this
# closes is a location baked into a default argument or module constant, the
# same shape tests/test_projection_isolation.py::test_no_docs_literals
# already guards for the pipeline-side engine files, one layer down.

_DOCS_SHAPED = __import__("re").compile(r"^(docs/|summaries/|summaries$)")


def _docstring_constants(tree: ast.AST) -> list[ast.Constant]:
    hosts = [tree] + [n for n in ast.walk(tree)
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    out: list[ast.Constant] = []
    for node in hosts:
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            out.append(body[0].value)
    return out


def test_no_literals_in_router():
    tree = ast.parse(ROUTER_SRC.read_text(encoding="utf-8"), filename=str(ROUTER_SRC))
    docstrings = _docstring_constants(tree)
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if any(node is d for d in docstrings):
            continue
        if _DOCS_SHAPED.match(node.value):
            offenders.append((node.lineno, node.value))
    assert not offenders, (
        "docs/-shaped literal(s) survive in server/routers/projections.py — "
        "every path must come from ProjectionConfigService.resolved():\n"
        + "\n".join(f"  projections.py:{ln}: {v!r}" for ln, v in offenders)
    )


def test_no_literals_in_router_detects_a_violation():
    """The guard above is only meaningful if it can actually fail."""
    tree = ast.parse('DEFAULT = "docs/ensemble/events.jsonl"\n')
    assert any(
        _DOCS_SHAPED.match(n.value) for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    )
