"""014 — the thread-registry routes (T018-T020, T040-T041a, T050).

Most of what matters here is what is NOT built. Five absences are
requirements, and each is asserted rather than described:

  * no bulk ruling endpoint            (SC-004)   -> test_no_bulk_route_exists
  * no query/paging on /threads/proposals (FR-028, D16)
  * no model flag in the harvest argv  (FR-004)
  * the harvest writes no canon        (FR-006)
  * no route writes on its own         (FR-018/019)
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.main import app  # noqa: E402
from server.platform_config_service import (  # noqa: E402
    PlatformConfigService, TRACKED_CONFIG_NAME,
)

client = TestClient(app)
ROUTER_SRC = Path(__file__).resolve().parent.parent / "server" / "routers" / "projections.py"


@pytest.fixture
def campaign(monkeypatch, tmp_path):
    cfgdir = tmp_path / "config"
    cfgdir.mkdir(parents=True, exist_ok=True)
    (cfgdir / TRACKED_CONFIG_NAME).write_text("documents: []\n", encoding="utf-8")
    (cfgdir / "projections.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(app.state, "platform", PlatformConfigService(tmp_path),
                        raising=False)
    return tmp_path


@pytest.fixture
def fake_cli(monkeypatch):
    """Intercept subprocess.run so tests see argv/stdin without spawning."""
    calls: list[dict] = []
    outcome = {"rc": 0, "stdout": "{}", "stderr": ""}

    def fake_run(cmd, **kw):
        calls.append({"cmd": cmd, "input": kw.get("input"), "cwd": kw.get("cwd")})
        return subprocess.CompletedProcess(cmd, outcome["rc"],
                                           outcome["stdout"], outcome["stderr"])

    monkeypatch.setattr("server.routers.projections.subprocess.run", fake_run)
    return calls, outcome


@pytest.fixture
def captured_sse(monkeypatch):
    calls: list[list[str]] = []

    async def fake_stream(cmd, cwd=None, env_extra=None, on_complete=None):
        calls.append(cmd)
        if on_complete:
            on_complete(0)
        yield "data: done\n\n"

    monkeypatch.setattr("server.routers.projections.stream_subprocess", fake_stream)
    return calls


# ── T018: the read routes return their CLI payloads ──────────────────────

def test_read_routes_return_cli_payload_verbatim(campaign, fake_cli):
    calls, outcome = fake_cli
    outcome["stdout"] = json.dumps({"version": 1, "threads": [], "count": 0})
    r = client.get("/api/projections/threads/registry")
    assert r.status_code == 200
    assert r.json() == {"version": 1, "threads": [], "count": 0}
    assert calls[-1]["cmd"][1:] == ["list", "--json"]

    outcome["stdout"] = json.dumps({"proposals": [], "counts": {}})
    r = client.get("/api/projections/threads/proposals")
    assert r.status_code == 200 and r.json()["counts"] == {}
    assert calls[-1]["cmd"][1:] == ["proposals", "--json"]


def test_check_is_200_even_with_problems(campaign, fake_cli):
    """The CLI exits 1; a failing check is data to render, not a transport
    error. A 4xx here would make the page say "request failed" exactly where
    the GM needs to read which thread is broken."""
    calls, outcome = fake_cli
    outcome["rc"] = 1
    outcome["stdout"] = json.dumps({"threads": 2, "problems": ["x: bad"]})
    r = client.get("/api/projections/threads/check")
    assert r.status_code == 200
    assert r.json()["problems"] == ["x: bad"]


def test_cli_failure_becomes_400_carrying_stderr(campaign, fake_cli):
    calls, outcome = fake_cli
    outcome["rc"] = 1
    outcome["stdout"] = ""
    outcome["stderr"] = "error: no proposal with norm 'nope' — run propose first"
    r = client.get("/api/projections/threads/registry")
    assert r.status_code == 400
    assert "no proposal with norm 'nope'" in r.json()["detail"]


# ── T019: empty selection refused with 400, no subprocess ────────────────

def test_empty_selection_is_400_not_422_and_spawns_nothing(campaign, fake_cli,
                                                           captured_sse):
    calls, _ = fake_cli
    r = client.get("/api/projections/threads/run/propose")
    assert r.status_code == 400          # not FastAPI's generic 422
    assert "corpus is required" in r.json()["detail"]

    r = client.get("/api/projections/threads/corpus")
    assert r.status_code == 400
    assert "pattern is required" in r.json()["detail"]

    assert calls == [] and captured_sse == [], "Constitution X: no silent all"


# ── T019a (FR-006): the harvest writes no canon ──────────────────────────

def test_harvest_writes_no_registry(tmp_path):
    """FR-006 — the line between "harvest" and "ratify".

    Runs the real engine (not a stub): a harvest must leave the registry
    exactly as it found it, including absent.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _thread_fixtures import CORPUS, REGISTRY, chapter, cli, campaign as mk, thread_fact

    c = mk(tmp_path)
    chapter(c, 30, [thread_fact("A thing", "It happened.")])
    assert not (c / REGISTRY).exists()
    r = cli(c, "propose", "--corpus", CORPUS)
    assert r.returncode == 0, r.stderr
    assert not (c / REGISTRY).exists(), "a harvest must not create canon"

    # and with a registry present, it is byte-identical afterwards
    (c / REGISTRY).write_text("version: 1\nthreads: []\n")
    before = (c / REGISTRY).read_bytes()
    cli(c, "propose", "--corpus", CORPUS)
    assert (c / REGISTRY).read_bytes() == before


# ── T040a (FR-004): no model call anywhere in the harvest ────────────────

def test_harvest_argv_has_no_model_or_backend(campaign, captured_sse):
    r = client.get("/api/projections/threads/run/propose",
                   params={"corpus": ["docs/ensemble/per_chapter/*/merged.json"]})
    assert r.status_code == 200
    argv = captured_sse[0]
    for flag in ("--model", "--backend", "--endpoint", "--max-tokens", "--batch"):
        assert flag not in argv, f"{flag} in a zero-token deterministic pass"
    assert argv[1] == "propose"


def test_propose_route_never_resolves_a_selection():
    """FR-004 asserted structurally: run_threads_propose must not call
    resolve_selection / _selection_args at all."""
    tree = ast.parse(ROUTER_SRC.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "run_threads_propose")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "resolve_selection" not in called
    assert "_selection_args" not in called


# ── T040b (FR-028 / D16): no server-side query ───────────────────────────

def test_proposals_route_declares_no_query_parameter():
    tree = ast.parse(ROUTER_SRC.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "threads_proposals")
    names = [a.arg for a in fn.args.args + fn.args.kwonlyargs]
    assert names == [], (
        "GET /threads/proposals must take no query/filter/paging parameter — "
        "server-side search would put 'which candidates matter' in the server")


def test_proposals_route_returns_every_candidate(campaign, fake_cli):
    calls, outcome = fake_cli
    props = [{"norm": f"c{i}", "title": f"C{i}", "status": "pending"}
             for i in range(120)]
    outcome["stdout"] = json.dumps({"proposals": props,
                                    "counts": {"pending": 120}})
    r = client.get("/api/projections/threads/proposals")
    assert len(r.json()["proposals"]) == 120


# ── T040 / T039: ratify is ONE call, validated at the edge ───────────────

def test_ratify_spawns_exactly_one_subprocess_with_plan_on_stdin(campaign, fake_cli):
    calls, outcome = fake_cli
    outcome["stdout"] = "ok: ratified"
    body = {"norm": "a-thing", "id": "a-thing", "title": "A thing",
            "opened": 30,
            "log": [{"chapter": 30, "change": "opened", "summary": "s"}]}
    r = client.post("/api/projections/threads/ratify", json=body)
    assert r.status_code == 200
    assert len(calls) == 1, "the atomic verb is ONE call, not add+log+rule"
    argv = calls[0]["cmd"]
    assert argv[1:] == ["ratify", "--norm", "a-thing", "--plan", "-"]
    sent = json.loads(calls[0]["input"])
    assert "norm" not in sent and sent["title"] == "A thing"
    assert sent["log"] == body["log"], "the plan is forwarded verbatim"


def test_ratify_refuses_a_chapterless_accept_at_the_edge(campaign, fake_cli):
    calls, _ = fake_cli
    r = client.post("/api/projections/threads/ratify", json={
        "norm": "a-thing", "id": "a-thing", "title": "A thing",
        "log": [{"chapter": None, "change": "opened", "summary": "s"}]})
    assert r.status_code == 400
    # Named as a FORM problem, not check_registry's wording about log rows.
    assert "chapter is required" in r.json()["detail"]
    assert calls == [], "no subprocess for a form problem"


def test_ratify_cli_refusal_reaches_the_caller_verbatim(campaign, fake_cli):
    calls, outcome = fake_cli
    outcome["rc"] = 1
    outcome["stderr"] = "error: thread id 'a-thing' already exists"
    r = client.post("/api/projections/threads/ratify", json={
        "norm": "a-thing", "id": "a-thing", "title": "A thing",
        "log": [{"chapter": 30, "change": "opened", "summary": "s"}]})
    assert r.status_code == 400
    assert r.json()["detail"] == "error: thread id 'a-thing' already exists"


# ── T041 (SC-004): no bulk route exists ──────────────────────────────────

def test_no_bulk_route_exists():
    """The strongest reading of Principle II: there is no "ratify all".

    Asserted structurally so it cannot be reintroduced by a well-meaning
    convenience patch — a route taking a LIST of norms would fail here.
    """
    tree = ast.parse(ROUTER_SRC.read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for arg in fn.args.args + fn.args.kwonlyargs:
            if arg.arg in ("norms", "norm_list", "candidates"):
                raise AssertionError(f"{fn.name} accepts a bulk argument {arg.arg!r}")
        src = ast.get_source_segment(ROUTER_SRC.read_text(encoding="utf-8"), fn) or ""
        if "threads" in fn.name:
            assert "--all" not in src, f"{fn.name} builds an --all flag"


# ── T041a (FR-018/019): every write goes through the engine ──────────────

def test_no_threads_route_writes_on_its_own():
    """The registry, the proposals file and the adjudication bundle are only
    ever mutated by `thread_registry`. This is why check_registry cannot be
    bypassed by the surface (FR-020) — there is no second writer to bypass it
    with."""
    src = ROUTER_SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    banned_attrs = {"write_text", "write_bytes", "safe_dump", "dump", "mkdir"}
    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if "thread" not in fn.name:
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Attribute) and f.attr in banned_attrs:
                    offenders.append(f"{fn.name}: .{f.attr}()")
                if isinstance(f, ast.Name) and f.id in ("open", "atomic_write_text"):
                    offenders.append(f"{fn.name}: {f.id}()")
    assert not offenders, f"threads routes must not write: {offenders}"


# ── T050: maintenance refusals reach the caller as the CLI's own text ────

@pytest.mark.parametrize("endpoint,body,message", [
    ("/api/projections/threads/log",
     {"id": "x", "chapter": 3, "change": "advanced", "summary": "s"},
     "error: no thread 'x'"),
    ("/api/projections/threads/status",
     {"id": "x", "status": "resolved"},
     "error: resolving/abandoning needs --chapter"),
    ("/api/projections/threads/alias",
     {"id": "x", "alias": "y"},
     "error: alias 'y' already matches thread 'z'"),
    ("/api/projections/threads/rule",
     {"norm": "x", "status": "maybe"},
     "error: bad ruling 'maybe' (allowed: ratified, rejected, deferred)"),
])
def test_engine_refusal_is_rendered_verbatim(campaign, fake_cli, endpoint, body, message):
    calls, outcome = fake_cli
    outcome["rc"] = 1
    outcome["stderr"] = message
    r = client.post(endpoint, json=body)
    assert r.status_code == 400
    assert r.json()["detail"] == message, "no paraphrase, no traceback (SC-008)"


def test_maintenance_routes_require_their_fields(campaign, fake_cli):
    calls, _ = fake_cli
    assert client.post("/api/projections/threads/log", json={"id": "x"}).status_code == 400
    assert client.post("/api/projections/threads/status", json={"id": "x"}).status_code == 400
    assert client.post("/api/projections/threads/alias", json={"id": "x"}).status_code == 400
    assert calls == []


# ── T020: path resolution belongs to the engine, not the router ──────────

def test_threads_routes_name_no_store_and_no_path_literal():
    """T020, honoured in the shape the design actually took.

    The task asked for an assertion that these routes resolve
    `stores.thread_registry` / `_proposals` / `_adjudication` from
    `ProjectionConfigService.resolved()`. They resolve NONE of them, on
    purpose: `thread_registry` already resolves every store from
    `<config>/projections.yaml` itself, once, before any work. Having the
    router resolve them too and pass them as flags would be a second
    declaration of the same fact — the drift Constitution V exists to
    prevent, and the reason `_backend_flags` was deleted.

    So the guard is stronger than the one requested: the threads routes name
    neither a store NOR a path literal. `test_projection_routes.py::
    test_no_literals_in_router` still covers the file-wide literal rule.
    """
    src = ROUTER_SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if "thread" not in fn.name:
            continue
        body = ast.get_source_segment(src, fn) or ""
        for store in ("thread_registry", "thread_proposals", "thread_adjudication"):
            assert f"stores.{store}" not in body, (
                f"{fn.name} resolves stores.{store}; the CLI already does")
        for node in ast.walk(fn):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "docs/" not in node.value, (
                    f"{fn.name} carries path literal {node.value!r}")


# ── review findings, 2026-08-27 ──────────────────────────────────────────

def test_unusable_corpus_pattern_is_400_not_a_traceback(campaign, fake_cli):
    """`Path.glob` refuses an absolute pattern with NotImplementedError. That
    is user input from the corpus box — a GM pasting the absolute path they
    use at the CLI is the obvious case — so it must be a 400 naming the
    problem, not a 500 with a traceback."""
    calls, _ = fake_cli
    r = client.get("/api/projections/threads/corpus",
                   params={"pattern": ["/home/kroussos/campaigns/x/*.json"]})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "not a usable corpus pattern" in detail
    assert "absolute" in detail          # FR-033: name a way to proceed
    assert calls == []


def test_check_crash_is_not_reported_as_a_clean_registry(campaign, fake_cli):
    """`check --json` runs with allow_nonzero because exit 1 means "problems
    found", which is data. But a non-zero exit with EMPTY stdout means the CLI
    crashed — returning {} made the page render "passes every consistency
    check" over a registry nobody managed to read."""
    calls, outcome = fake_cli
    outcome["rc"] = 1
    outcome["stdout"] = ""
    outcome["stderr"] = "Traceback (most recent call last):\nyaml.scanner.ScannerError"
    r = client.get("/api/projections/threads/check")
    assert r.status_code == 400, "a crash must not read as a clean registry"
    assert "ScannerError" in r.json()["detail"]


def test_write_routes_do_not_block_the_event_loop():
    """The write routes are `async def` (they `await request.json()`), so a
    bare `subprocess.run` in the body would stall the loop for the life of the
    process — including an in-flight harvest SSE stream. They must bridge
    through a threadpool. `get_sections` sidesteps this by being a sync `def`
    that FastAPI threadpools itself."""
    src = ROUTER_SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef) or "thread" not in fn.name:
            continue
        body = ast.get_source_segment(src, fn) or ""
        if "subprocess.run" in body and "run_in_threadpool" not in body:
            offenders.append(fn.name)
    assert not offenders, f"blocking subprocess.run in async route(s): {offenders}"
