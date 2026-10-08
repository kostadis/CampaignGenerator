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


# ── spec 034 US3: group proposals (T030) ─────────────────────────────────

GROUP_BASE = "/api/projections/threads"
GRANGE = {"summaries_dir": "docs/summaries", "since": 3, "until": 9}


def _flag(cmd: list[str], flag: str) -> str | None:
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


def _sse(path: str, params: dict) -> int:
    r = client.get(f"{GROUP_BASE}{path}", params=params)
    _ = r.text  # drain the SSE generator so the fake subprocess runs
    return r.status_code


def test_group_propose_requires_both_ends_of_the_range_and_spawns_nothing(campaign, captured_sse):
    for params in ({"summaries_dir": "docs/summaries"}, {"summaries_dir": "docs/summaries", "since": 3},
                   {"summaries_dir": "docs/summaries", "until": 9}):
        r = client.get(f"{GROUP_BASE}/run/group-propose", params=params)
        assert r.status_code == 400 and "since and until are required" in r.json()["detail"]
    assert captured_sse == []


def test_group_propose_needs_a_summaries_directory(campaign, captured_sse):
    r = client.get(f"{GROUP_BASE}/run/group-propose", params={"since": 3, "until": 9})
    assert r.status_code == 400 and "summaries directory" in r.json()["detail"] and captured_sse == []


@pytest.mark.parametrize("bad", [{"max_input_chars": 0}, {"max_tokens": 0}])
def test_group_propose_refuses_a_non_positive_limit(campaign, captured_sse, bad):
    r = client.get(f"{GROUP_BASE}/run/group-propose", params={**GRANGE, **bad})
    assert r.status_code == 400 and captured_sse == []


def test_group_propose_streams_thread_propose_with_the_prose_selection(campaign, captured_sse):
    from pipelines.summary_native import schema

    assert _sse("/run/group-propose", GRANGE) == 200
    cmd = captured_sse[0]
    assert cmd[1] == "thread-propose"
    assert _flag(cmd, "--since") == "3" and _flag(cmd, "--until") == "9"
    assert _flag(cmd, "--summaries-dir") == "docs/summaries"
    assert _flag(cmd, "--backend") == schema.DEFAULT_PROSE_BACKEND and _flag(cmd, "--model") == schema.DEFAULT_PROSE_MODEL
    for flag in ("--max-input-chars", "--max-tokens", "--dump-only", "--registry", "--out-root"):
        assert flag not in cmd, f"{flag} is not sent unless asked for"


def test_group_propose_carries_the_per_run_flags_and_the_effort(campaign, captured_sse):
    assert _sse("/run/group-propose", {**GRANGE, "max_input_chars": 5000, "max_tokens": 4000, "dump_only": True,
                                       "model": "claude-opus-5-5", "claude_code_effort": "high"}) == 200
    cmd = captured_sse[0]
    assert _flag(cmd, "--max-input-chars") == "5000" and _flag(cmd, "--max-tokens") == "4000"
    assert "--dump-only" in cmd and _flag(cmd, "--model") == "claude-opus-5-5"
    assert _flag(cmd, "--claude-code-effort") == "high"


def test_group_propose_reads_the_prose_block_of_grounding_yaml(campaign, captured_sse):
    from server.grounding_config_service import GroundingConfigService

    GroundingConfigService(campaign / "config").update_config(
        {"summary_native": {"prose": {"backend": "claude-code", "model": "claude-opus-5-5"}}})
    assert _sse("/run/group-propose", GRANGE) == 200
    assert _flag(captured_sse[0], "--model") == "claude-opus-5-5"


def test_plan_route_is_the_emit_plan_verb_and_read_only(campaign, fake_cli):
    calls, outcome = fake_cli
    outcome["stdout"] = json.dumps({"id": "x", "title": "X", "members": ["n-1"], "log": []})
    r = client.get(f"{GROUP_BASE}/plan", params={"key": "g-0123456789ab"})
    assert r.status_code == 200 and r.json()["title"] == "X"
    assert len(calls) == 1 and calls[0]["cmd"][1:] == ["ratify", "--key", "g-0123456789ab", "--emit-plan"]
    assert calls[0]["input"] is None
    assert client.get(f"{GROUP_BASE}/plan").status_code == 400
    assert client.get(f"{GROUP_BASE}/plan", params={"key": "  "}).status_code == 400
    assert len(calls) == 1


def test_plan_route_carries_the_cli_refusal_verbatim(campaign, fake_cli):
    calls, outcome = fake_cli
    outcome.update(rc=1, stdout="", stderr="error: no group proposal with key 'g-nope'")
    r = client.get(f"{GROUP_BASE}/plan", params={"key": "g-nope"})
    assert r.status_code == 400 and r.json()["detail"] == "error: no group proposal with key 'g-nope'"


@pytest.fixture
def group_cli(monkeypatch):
    """subprocess.run that answers `proposals --json` from a fixed queue and records every call."""
    calls: list[dict] = []
    state = {"rc": 0, "stderr": ""}
    queue = {"proposals": [{"key": "g-aaaaaaaaaaaa", "kind": "new", "status": "pending",
                            "members": [{"id": "n-1"}, {"id": "n-2"}, {"id": "n-3"}]},
                           {"norm": "a-thing", "title": "A thing", "status": "pending"}], "counts": {"pending": 2}}

    def fake_run(cmd, **kw):
        calls.append({"cmd": cmd, "input": kw.get("input")})
        if cmd[1] == "proposals":
            return subprocess.CompletedProcess(cmd, 0, json.dumps(queue), "")
        return subprocess.CompletedProcess(cmd, state["rc"], "ok: ratified" if not state["rc"] else "", state["stderr"])

    monkeypatch.setattr("server.routers.projections.subprocess.run", fake_run)
    return calls, state


GPLAN = {"key": "g-aaaaaaaaaaaa", "id": "x", "title": "X", "status": "open", "members": ["n-1", "n-2"],
         "aliases_add": ["Ex"], "log": [{"chapter": 3, "change": "opened", "summary": "s", "cite": "[ch 003 / 003.01]"}]}


def test_ratify_a_group_forwards_the_plan_without_the_key_in_one_write(campaign, group_cli):
    calls, _ = group_cli
    r = client.post(f"{GROUP_BASE}/ratify", json=GPLAN)
    assert r.status_code == 200 and r.json()["ok"] is True
    writes = [c for c in calls if c["cmd"][1] == "ratify"]
    assert len(writes) == 1 and writes[0]["cmd"][1:] == ["ratify", "--key", "g-aaaaaaaaaaaa", "--plan", "-"]
    sent = json.loads(writes[0]["input"])
    assert "key" not in sent and sent == {k: v for k, v in GPLAN.items() if k != "key"}


@pytest.mark.parametrize("edit,needle", [
    ({"members": []}, "members is required"),
    ({"members": None}, "members is required"),
    ({"members": ["n-1", "n-9"]}, "n-9"),
    ({"log": []}, "log is required"),
    ({"log": [{"chapter": 0, "change": "opened", "summary": "s"}]}, "log row 1: chapter"),
    ({"log": [{"chapter": "3", "change": "opened", "summary": "s"}]}, "log row 1: chapter"),
    ({"log": [{"chapter": 3, "change": "opened"}, {"chapter": None, "change": "advanced"}]}, "log row 2: chapter"),
])
def test_ratify_a_group_refuses_form_problems_at_the_edge_and_writes_nothing(campaign, group_cli, edit, needle):
    calls, _ = group_cli
    r = client.post(f"{GROUP_BASE}/ratify", json={**GPLAN, **edit})
    assert r.status_code == 400 and needle in r.json()["detail"]
    assert [c for c in calls if c["cmd"][1] == "ratify"] == []


def test_ratify_a_group_with_an_unknown_key_is_400(campaign, group_cli):
    r = client.post(f"{GROUP_BASE}/ratify", json={**GPLAN, "key": "g-bbbbbbbbbbbb"})
    assert r.status_code == 400 and "g-bbbbbbbbbbbb" in r.json()["detail"]


def test_ratify_a_group_carries_the_cli_refusal_verbatim(campaign, group_cli):
    _, state = group_cli
    state.update(rc=1, stderr="error: alias 'Ex' collides with thread 'old' (its title or an alias) — a name belongs to one thread")
    r = client.post(f"{GROUP_BASE}/ratify", json=GPLAN)
    assert r.status_code == 400 and r.json()["detail"].startswith("error: alias 'Ex' collides")


def test_ratify_takes_a_norm_or_a_key_never_both_or_neither(campaign, group_cli):
    calls, _ = group_cli
    assert client.post(f"{GROUP_BASE}/ratify", json={**GPLAN, "norm": "a-thing"}).status_code == 400
    assert client.post(f"{GROUP_BASE}/ratify", json={k: v for k, v in GPLAN.items() if k != "key"}).status_code == 400
    assert calls == []


def test_rule_a_group_by_key(campaign, fake_cli):
    calls, outcome = fake_cli
    outcome["stdout"] = "ok"
    r = client.post(f"{GROUP_BASE}/rule", json={"key": "g-aaaaaaaaaaaa", "status": "rejected", "note": "no"})
    assert r.status_code == 200
    assert calls[0]["cmd"][1:] == ["rule", "--key", "g-aaaaaaaaaaaa", "--status", "rejected", "--note", "no"]
    # the old form is unchanged
    client.post(f"{GROUP_BASE}/rule", json={"norm": "a-thing", "status": "deferred"})
    assert calls[1]["cmd"][1:] == ["rule", "--norm", "a-thing", "--status", "deferred"]


def test_rule_takes_a_norm_or_a_key_never_both_or_neither(campaign, fake_cli):
    calls, _ = fake_cli
    assert client.post(f"{GROUP_BASE}/rule", json={"status": "rejected"}).status_code == 400
    assert client.post(f"{GROUP_BASE}/rule", json={"key": "g-a", "norm": "n", "status": "rejected"}).status_code == 400
    assert calls == []


def test_proposals_route_returns_group_entries_beside_name_keyed_ones(campaign, group_cli):
    r = client.get(f"{GROUP_BASE}/proposals")
    assert r.status_code == 200
    body = r.json()
    assert [p.get("key") or p.get("norm") for p in body["proposals"]] == ["g-aaaaaaaaaaaa", "a-thing"]
    assert body["proposals"][0]["members"][0]["id"] == "n-1"


def test_no_group_route_accepts_a_list_of_keys():
    tree = ast.parse(ROUTER_SRC.read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in fn.args.args + fn.args.kwonlyargs:
                assert arg.arg not in ("keys", "key_list"), f"{fn.name} accepts a bulk argument {arg.arg!r}"
