"""One declaration of the NPC dossiers defaults (spec 032 T046, Principle XII).

``pipelines/summary_native/schema.py`` declares every default once;
``server/npc_dossiers_config.py`` imports them and the router must contain none.
``npc_dossiers.yaml`` is strict, and the corpus paths that ``grounding.yaml
summary_native`` already owns are not re-declared in it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipelines.summary_native import schema  # noqa: E402
from server.main import app  # noqa: E402
from server.npc_dossiers_config import (  # noqa: E402
    NpcDossiersConfig,
    NpcDossiersConfigService,
    load_npc_dossiers_config,
    save_npc_dossiers_config,
)
from server.platform_config_service import TRACKED_CONFIG_NAME, PlatformConfigService  # noqa: E402

ROUTER_SRC = Path(__file__).resolve().parent.parent / "server" / "routers" / "npc_dossiers.py"


class TestModel:
    def test_defaults_are_the_schema_constants(self):
        cfg = NpcDossiersConfig()
        assert cfg.npc_root == schema.DEFAULT_NPC_ROOT
        assert cfg.recent_chapters == schema.DEFAULT_RECENT_CHAPTERS
        assert cfg.recurring_min == schema.DEFAULT_RECURRING_MIN
        assert cfg.max_tokens == schema.DEFAULT_MAX_TOKENS
        assert cfg.draft.backend == schema.DEFAULT_DRAFT_BACKEND
        assert cfg.draft.model == schema.DEFAULT_DRAFT_MODEL
        assert cfg.draft.mode == schema.DEFAULT_DRAFT_MODE
        assert cfg.draft.chunk_chars == schema.DEFAULT_CHUNK_CHARS
        assert cfg.selection.is_empty()

    @pytest.mark.parametrize("key", ["summaries_dir", "registry", "canon_file", "out_root"])
    def test_corpus_paths_are_not_declared_here(self, key):
        assert key not in NpcDossiersConfig.model_fields
        with pytest.raises(Exception):
            NpcDossiersConfig.model_validate({key: "x"})

    def test_strict_at_both_levels(self):
        with pytest.raises(Exception):
            NpcDossiersConfig.model_validate({"nope": 1})
        with pytest.raises(Exception):
            NpcDossiersConfig.model_validate({"draft": {"endpoint": "http://x/v1"}})
        with pytest.raises(Exception):
            NpcDossiersConfig.model_validate({"draft": {"mode": "sideways"}})
        with pytest.raises(Exception):
            NpcDossiersConfig.model_validate({"draft": {"chunk_chars": 0}})

    def test_a_missing_or_empty_file_is_all_defaults(self, tmp_path):
        assert load_npc_dossiers_config(tmp_path / "npc_dossiers.yaml") == NpcDossiersConfig()
        (tmp_path / "npc_dossiers.yaml").write_text("", encoding="utf-8")
        assert load_npc_dossiers_config(tmp_path / "npc_dossiers.yaml") == NpcDossiersConfig()

    def test_unknown_key_in_the_file_is_a_value_error_naming_it(self, tmp_path):
        p = tmp_path / "npc_dossiers.yaml"
        p.write_text("draft:\n  endpoint: http://x/v1\n", encoding="utf-8")
        with pytest.raises(ValueError, match="endpoint"):
            load_npc_dossiers_config(p)

    def test_round_trip(self, tmp_path):
        p = tmp_path / "npc_dossiers.yaml"
        cfg = NpcDossiersConfig.model_validate({"npc_root": "out/n", "draft": {"mode": "one-shot", "chunk_chars": 5}})
        save_npc_dossiers_config(p, cfg)
        assert load_npc_dossiers_config(p) == cfg
        assert "selection" not in yaml.safe_load(p.read_text(encoding="utf-8"))

    def test_another_backend_without_a_model_does_not_inherit_the_spark_model(self):
        cfg = NpcDossiersConfig.model_validate({"draft": {"backend": "anthropic"}})
        assert cfg.draft.effective_model() is None
        cfg = NpcDossiersConfig.model_validate({"draft": {"backend": "anthropic", "model": "m"}})
        assert cfg.draft.effective_model() == "m"
        assert NpcDossiersConfig().draft.effective_model() == schema.DEFAULT_DRAFT_MODEL


class TestRoutes:
    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / TRACKED_CONFIG_NAME).write_text(
            "documents:\n  - label: world_state\n    path: docs/world_state.md\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(app.state, "platform", PlatformConfigService(tmp_path), raising=False)
        return TestClient(app), NpcDossiersConfigService(tmp_path / "config")

    def test_get_returns_the_resolved_config(self, client):
        c, _ = client
        r = c.get("/api/npc-dossiers/config")
        assert r.status_code == 200
        assert r.json()["npc_root"] == schema.DEFAULT_NPC_ROOT
        assert r.json()["draft"]["mode"] == schema.DEFAULT_DRAFT_MODE

    def test_put_saves_and_get_reads_it_back(self, client):
        c, svc = client
        r = c.put("/api/npc-dossiers/config", json={"npc_root": "out/n", "recent_chapters": 2})
        assert r.status_code == 200
        assert svc.resolved().npc_root == "out/n"
        assert c.get("/api/npc-dossiers/config").json()["recent_chapters"] == 2

    @pytest.mark.parametrize("body", [
        {"nope": 1},
        {"draft": {"endpoint": "http://x/v1"}},
        {"summaries_dir": "docs/summaries"},
        {"registry": "r.yaml"},
        {"canon_file": "c.yaml"},
    ])
    def test_unknown_key_is_422_and_nothing_is_written(self, client, body):
        c, svc = client
        assert c.put("/api/npc-dossiers/config", json=body).status_code == 422
        assert not svc.path.exists()

    def test_a_malformed_file_is_400(self, client):
        c, svc = client
        svc.path.write_text("nope: 1\n", encoding="utf-8")
        assert c.get("/api/npc-dossiers/config").status_code == 400


class TestNoDriftInTheRouter:
    SRC = ROUTER_SRC.read_text(encoding="utf-8")

    def test_no_path_literal(self):
        assert "docs/npcs" not in self.SRC
        assert "summary_native/" not in self.SRC.replace("pipelines/summary_native/schema.py", "")
        assert "canon.yaml" not in self.SRC

    @pytest.mark.parametrize("pattern", [
        r"=\s*4\b", r"=\s*10\b", r"=\s*16000\b", r"=\s*60000\b", r"\b0\.88\b",
        r'backend:\s*str\s*=\s*"(anthropic|dgx)"',
        r'"dgx"', r'"chunked"', r"qwen",
        r'mode:\s*str\s*=\s*"[a-z]',
    ])
    def test_no_default_literal(self, pattern):
        offenders = [
            (n, line.strip())
            for n, line in enumerate(self.SRC.splitlines(), 1)
            if re.search(pattern, line) and not line.lstrip().startswith(("#", '"""'))
        ]
        assert not offenders, offenders

    def test_defaults_are_declared_in_the_schema_and_imported_by_the_model(self):
        model_src = (ROUTER_SRC.parents[2] / "pipelines" / "summary_native" / "npc_config.py").read_text(encoding="utf-8")
        for name in ("DEFAULT_NPC_ROOT", "DEFAULT_DRAFT_BACKEND", "DEFAULT_CHUNK_CHARS", "DEFAULT_MAX_TOKENS"):
            assert name in model_src
        assert "qwen" not in model_src and "docs/npcs" not in model_src
        # One model: the server module re-exports it, it does not redeclare it.
        service_src = (ROUTER_SRC.parent.parent / "npc_dossiers_config.py").read_text(encoding="utf-8")
        assert "class NpcDossiersConfig(" not in service_src and "class NpcDraftBlock" not in service_src
