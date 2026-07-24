"""Phases 3 and 4 of docs/config/ensemble-isolation.md: ensemble.yaml is the
ONLY source of the router's defaults, and the sidebar model pick finally
reaches an ensemble run (TestModelResolution, at the bottom).

Two things are tested here:

1. **The no-drift guard.** A mechanical assertion that no ensemble path literal
   has crept back into ``server/routers/ensemble.py``. This is the test that
   keeps §2 of the design doc ("three-way default drift") from happening again
   — in the spirit of ``tests/test_retrieve_render_isolation.py``.

2. **The values actually reach the command.** A guard alone would pass if the
   router simply stopped using the values. These tests intercept command
   construction and assert the built argv carries what ensemble.yaml says.

The spec-002 reproducibility contract (US1: the echoed command must reproduce
the run) is what makes (2) load-bearing rather than incidental: the command is
built from RESOLVED values, so an omitted query parameter still produces a
fully explicit command.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.platform_config_service import PlatformConfigService
from server.routers import ensemble

ROUTER_SRC = Path(__file__).resolve().parent.parent / "server" / "routers" / "ensemble.py"

CONFIG_SUBDIR = "config"


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.fixture
def campaign(tmp_path):
    _write(
        tmp_path / CONFIG_SUBDIR / "config.yaml",
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
    )
    return tmp_path


@pytest.fixture
def captured(monkeypatch):
    """Intercept _run_locked so tests see the argv without spawning anything."""
    calls: list[list[str]] = []

    def fake_run_locked(stage, cmd, env_extra=None, prelude=""):
        calls.append(cmd)
        return {"stage": stage, "cmd": cmd}

    monkeypatch.setattr(ensemble, "_run_locked", fake_run_locked)
    return calls


@pytest.fixture
def client(campaign, monkeypatch):
    monkeypatch.chdir(campaign)  # the server chdirs to campaign_dir at boot
    app = FastAPI()
    app.include_router(ensemble.router, prefix="/api/ensemble")
    app.state.platform = PlatformConfigService(campaign)
    return TestClient(app)


# ── (1) The no-drift guard ─────────────────────────────────────────────────

class TestNoDrift:
    """Ensemble artifact paths must live in ensemble_config_shared.py only."""

    # Deliberately NOT including "docs/world_state.md" & co: GROUNDING_DOCS is
    # the promote allow-list (FR-013), a different concern from the ensemble
    # workspace layout, and it stays in the router on purpose.
    FORBIDDEN = (
        "docs/ensemble",
        "docs/chapters",
        "docs/recent_events",
    )

    def test_no_ensemble_path_literal_in_the_router(self):
        src = ROUTER_SRC.read_text(encoding="utf-8")
        offenders = [
            (n, line.strip())
            for n, line in enumerate(src.splitlines(), 1)
            for lit in self.FORBIDDEN
            if lit in line
        ]
        assert not offenders, (
            "ensemble path literal(s) back in the router — they belong in "
            "server/ensemble_config_shared.py's EnsemblePaths:\n"
            + "\n".join(f"  ensemble.py:{n}: {t}" for n, t in offenders)
        )

    def test_no_hardcoded_backend_default_in_the_router(self):
        """`backend: str = "anthropic"` in a route signature is the same drift
        in a different costume — the per-stage backend comes from the config."""
        src = ROUTER_SRC.read_text(encoding="utf-8")
        assert not re.search(r'backend:\s*str\s*=\s*"anthropic"', src)

    def test_the_defaults_are_declared_where_they_belong(self):
        """Counterpart to the guard: prove the literals didn't just vanish."""
        shared = (
            ROUTER_SRC.parent.parent / "ensemble_config_shared.py"
        ).read_text(encoding="utf-8")
        for lit in self.FORBIDDEN:
            assert lit in shared, f"{lit} is declared nowhere"


# ── (2) Config actually reaches the built command ──────────────────────────

class TestConfigReachesTheCommand:
    def _put(self, client, partial):
        assert client.put("/api/ensemble/config", json=partial).status_code == 200

    def test_extract_uses_configured_paths_and_tuning(self, client, captured):
        self._put(client, {
            "paths": {"per_chapter_dir": "out/pc", "merged_out": "out/all.json"},
            "tuning": {"chapter_parallel": 7, "chunk_parallel": 9},
        })
        client.get("/api/ensemble/run/extract", params={"chapters": ["ch01.md"]})
        cmd = captured[-1]
        assert "out/pc" in cmd and "out/all.json" in cmd
        assert "7" in cmd and "9" in cmd

    def test_extract_uses_configured_backend_and_endpoints(self, client, captured):
        self._put(client, {
            "extract": {"backend": "dgx", "model": "qwen3-next",
                        "endpoints": ["http://spark:8001/v1"]},
        })
        client.get("/api/ensemble/run/extract", params={"chapters": ["ch01.md"]})
        joined = " ".join(captured[-1])
        assert "qwen3-next" in joined
        assert "http://spark:8001/v1" in joined

    def test_explicit_request_value_beats_config(self, client, captured):
        """Config supplies DEFAULTS; an explicit parameter still wins. This is
        what keeps the spec-002 copyable command honest."""
        self._put(client, {"paths": {"merged_out": "out/from_config.json"}})
        client.get("/api/ensemble/run/extract",
                   params={"chapters": ["ch01.md"], "out": "out/explicit.json"})
        cmd = captured[-1]
        assert "out/explicit.json" in cmd
        assert "out/from_config.json" not in cmd

    def test_explicit_zero_is_not_overridden_by_config(self, client, captured):
        """The `is None` sentinel, not `or`: 0 is a legitimate value, and a
        falsy-test would silently substitute the config's number for it."""
        self._put(client, {"tuning": {"chapter_parallel": 7}})
        client.get("/api/ensemble/run/extract",
                   params={"chapters": ["ch01.md"], "chapter_parallel": 0})
        # _cmd_opt drops falsy values, so an explicit 0 must leave the flag off
        # entirely rather than emit the configured 7.
        cmd = captured[-1]
        assert "7" not in cmd

    def test_bundle_uses_configured_corpus_out_dir_and_min_facts(self, client, captured):
        self._put(client, {
            "paths": {"corpus_glob": "out/pc/*/m.json",
                      "state_dossiers_dir": "out/dossiers"},
            "tuning": {"bundle_min_facts": 5},
        })
        client.get("/api/ensemble/run/bundle")
        cmd = captured[-1]
        assert "out/pc/*/m.json" in cmd
        assert "out/dossiers" in cmd
        assert "5" in cmd

    def test_threads_and_bundle_keep_their_distinct_min_facts(self, client, captured):
        """Defaults differ (3 vs 2) and must stay independent."""
        client.get("/api/ensemble/run/bundle")
        bundle_cmd = captured[-1]
        client.get("/api/ensemble/run/threads")
        threads_cmd = captured[-1]
        assert bundle_cmd[bundle_cmd.index("--min-facts") + 1] == "3"
        assert threads_cmd[threads_cmd.index("--min-facts") + 1] == "2"

    def test_recent_events_uses_configured_output(self, client, captured):
        self._put(client, {"paths": {"recent_events_out": "out/recent.md"}})
        client.get("/api/ensemble/run/recent-events")
        assert "out/recent.md" in captured[-1]

    def test_synthesize_uses_configured_dossiers_and_backend(self, client, captured):
        self._put(client, {
            "paths": {"dossiers_glob": "out/dossiers/*.md"},
            "tuning": {"dossier_min_facts": 4},
            "synthesize": {"backend": "openrouter", "model": "openai/gpt-5"},
        })
        client.get("/api/ensemble/run/synthesize", params={"doc": "world_state"})
        joined = " ".join(captured[-1])
        assert "out/dossiers/*.md" in joined
        assert "openai/gpt-5" in joined
        assert "4" in captured[-1]

    def test_synthesize_uses_configured_planning_depth(self, client, captured):
        self._put(client, {"planning": {"depth": "full"}})
        client.get("/api/ensemble/run/synthesize", params={"doc": "planning"})
        cmd = captured[-1]
        assert "--depth" in cmd and cmd[cmd.index("--depth") + 1] == "full"

    def test_scene_depth_stays_off_the_command_line(self, client, captured):
        """'scene' is planning.py's own default — passing it explicitly would
        bloat the copyable command for no behavior change."""
        client.get("/api/ensemble/run/synthesize", params={"doc": "planning"})
        assert "--depth" not in captured[-1]


# ── Principle X survives the refactor ──────────────────────────────────────

class TestNoSilentAll:
    def test_configured_chapters_selected_does_not_stand_in_for_an_omitted_one(
        self, client, captured
    ):
        """The persisted selection must NOT default an omitted `chapters`
        parameter — that would be exactly the silent "all" Principle X
        forbids, reintroduced through the config seam."""
        assert client.put(
            "/api/ensemble/config",
            json={"chapters_selected": ["docs/chapters/chapter_01.md"]},
        ).status_code == 200

        resp = client.get("/api/ensemble/run/extract")
        assert resp.status_code == 200
        assert not captured, "extraction ran despite no chapters in the request"
        assert "No chapters selected" in resp.text


# ── /chapters and /status read the config too ──────────────────────────────

class TestReadRoutes:
    def test_chapters_falls_back_to_the_configured_glob(self, client, campaign):
        (campaign / "book").mkdir()
        (campaign / "book" / "ch_01.md").write_text("x", encoding="utf-8")
        assert client.put(
            "/api/ensemble/config", json={"paths": {"chapters_glob": "book/ch_*.md"}}
        ).status_code == 200

        body = client.get("/api/ensemble/chapters").json()
        assert [c["path"] for c in body["chapters"]] == ["book/ch_01.md"]

    def test_explicit_glob_still_wins(self, client, campaign):
        (campaign / "book").mkdir()
        (campaign / "book" / "ch_01.md").write_text("x", encoding="utf-8")
        (campaign / "other.md").write_text("y", encoding="utf-8")
        client.put("/api/ensemble/config",
                   json={"paths": {"chapters_glob": "book/ch_*.md"}})

        body = client.get("/api/ensemble/chapters", params={"glob": ["other.md"]}).json()
        assert [c["path"] for c in body["chapters"]] == ["other.md"]

    def test_status_counts_artifacts_under_the_configured_dirs(self, client, campaign):
        client.put("/api/ensemble/config", json={
            "paths": {"corpus_glob": "out/pc/*/merged.json",
                      "state_dossiers_dir": "out/dossiers"},
        })
        d = campaign / "out" / "pc" / "ch01"
        d.mkdir(parents=True)
        (d / "merged.json").write_text("{}", encoding="utf-8")

        stages = {s["id"]: s for s in client.get("/api/ensemble/status").json()["stages"]}
        assert stages["extract"]["status"] == "complete"
        assert stages["extract"]["artifacts"] == 1
        assert stages["bundle"]["status"] == "not_started"


# ── Phase 4: the sidebar model pick reaches ensemble ───────────────────────

class TestModelResolution:
    """server/routers/ensemble.py was the only /run/* router outside
    resolve_default_model. On the Anthropic branch backend_cli_args emits
    nothing at all, so the subprocess fell back to campaignlib's literal and
    platform.runtime.default_model never reached an ensemble run."""

    def _model_of(self, cmd):
        return cmd[cmd.index("--model") + 1] if "--model" in cmd else None

    def test_extract_uses_the_platform_default_model(self, client, captured, campaign):
        client.app.state.platform.update_runtime({"default_model": "claude-opus-5"})
        client.get("/api/ensemble/run/extract", params={"chapters": ["ch01.md"]})
        assert self._model_of(captured[-1]) == "claude-opus-5"

    def test_bundle_uses_the_platform_default_model(self, client, captured):
        client.app.state.platform.update_runtime({"default_model": "claude-opus-5"})
        client.get("/api/ensemble/run/bundle")
        assert self._model_of(captured[-1]) == "claude-opus-5"

    def test_synthesize_uses_the_platform_default_model(self, client, captured):
        client.app.state.platform.update_runtime({"default_model": "claude-opus-5"})
        client.get("/api/ensemble/run/synthesize", params={"doc": "world_state"})
        assert self._model_of(captured[-1]) == "claude-opus-5"

    def test_ensemble_yaml_model_beats_the_platform_default(self, client, captured):
        client.app.state.platform.update_runtime({"default_model": "claude-opus-5"})
        client.put("/api/ensemble/config",
                   json={"extract": {"backend": "anthropic", "model": "claude-sonnet-5"}})
        client.get("/api/ensemble/run/extract", params={"chapters": ["ch01.md"]})
        assert self._model_of(captured[-1]) == "claude-sonnet-5"

    def test_explicit_request_model_beats_everything(self, client, captured):
        client.app.state.platform.update_runtime({"default_model": "claude-opus-5"})
        client.put("/api/ensemble/config",
                   json={"extract": {"model": "claude-sonnet-5"}})
        client.get("/api/ensemble/run/extract",
                   params={"chapters": ["ch01.md"], "model": "claude-haiku-4-5"})
        assert self._model_of(captured[-1]) == "claude-haiku-4-5"

    def test_non_anthropic_backend_is_not_given_a_claude_model(self, client, captured):
        """A DGX model name and a Claude id are not interchangeable —
        substituting the platform default here would be a bug, not a default."""
        client.app.state.platform.update_runtime({"default_model": "claude-opus-5"})
        client.put("/api/ensemble/config", json={
            "extract": {"backend": "dgx", "model": "", "endpoints": ["http://spark:8001/v1"]},
        })
        client.get("/api/ensemble/run/extract", params={"chapters": ["ch01.md"]})
        cmd = captured[-1]
        assert "claude-opus-5" not in cmd
        assert "--backend" in cmd and cmd[cmd.index("--backend") + 1] == "dgx"

    def test_dgx_model_is_still_forwarded_untouched(self, client, captured):
        client.app.state.platform.update_runtime({"default_model": "claude-opus-5"})
        client.put("/api/ensemble/config", json={
            "extract": {"backend": "dgx", "model": "qwen3-next",
                        "endpoints": ["http://spark:8001/v1"]},
        })
        client.get("/api/ensemble/run/extract", params={"chapters": ["ch01.md"]})
        assert self._model_of(captured[-1]) == "qwen3-next"

    def test_bundle_list_does_no_model_work(self, client, captured):
        """--list is a scope report with no model call; it must not acquire a
        --model (or the backend env) just because resolution now exists."""
        client.get("/api/ensemble/run/bundle", params={"list": True})
        cmd = captured[-1]
        assert "--list" in cmd
        assert "--model" not in cmd

    def test_threads_and_recent_events_get_no_model(self, client, captured):
        """Deterministic renders — no model call, so no --model."""
        client.get("/api/ensemble/run/threads")
        assert "--model" not in captured[-1]
        client.get("/api/ensemble/run/recent-events")
        assert "--model" not in captured[-1]

    def test_stale_non_anthropic_model_is_dropped_not_forwarded(self, client, captured):
        """The Setup page keeps a per-stage model across a backend switch, so
        an Anthropic run can arrive carrying a Qwen id. It must be discarded
        before resolution — never forwarded, never left as 'no model'."""
        client.app.state.platform.update_runtime({"default_model": "claude-opus-5"})
        client.get("/api/ensemble/run/extract", params={
            "chapters": ["ch01.md"],
            "backend": "anthropic",
            "model": "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8",
        })
        cmd = captured[-1]
        assert "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8" not in cmd
        assert self._model_of(cmd) == "claude-opus-5"

    def test_openrouter_style_id_is_also_treated_as_foreign(self, client, captured):
        """`anthropic/claude-sonnet-4` is an OpenRouter id, not an Anthropic
        API one — the `claude-` prefix check must not be fooled by the vendor
        segment."""
        client.app.state.platform.update_runtime({"default_model": "claude-opus-5"})
        client.get("/api/ensemble/run/extract", params={
            "chapters": ["ch01.md"],
            "backend": "anthropic",
            "model": "anthropic/claude-sonnet-4",
        })
        assert self._model_of(captured[-1]) == "claude-opus-5"

    def test_a_claude_id_absent_from_the_registry_is_still_honoured(self, client, captured):
        """Deliberately a prefix check, not MODELS membership: swapping in the
        platform default for a legitimate-but-unlisted Claude id would quietly
        run a model the caller did not ask for."""
        client.app.state.platform.update_runtime({"default_model": "claude-opus-5"})
        client.get("/api/ensemble/run/extract", params={
            "chapters": ["ch01.md"],
            "backend": "anthropic",
            "model": "claude-not-in-the-registry-yet",
        })
        assert self._model_of(captured[-1]) == "claude-not-in-the-registry-yet"
