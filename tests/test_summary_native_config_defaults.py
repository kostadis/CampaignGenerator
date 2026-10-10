"""One declaration of the summary_native defaults (feature 031, Principle XII).

``pipelines/summary_native/schema.py`` declares every default once.
``SummaryNativeRun`` imports them, the CLI falls back to them, and
``server/routers/summary_native.py`` must contain none of them. Modelled on
``tests/test_ensemble_config_defaults.py``.

The CLI keeps a plain-YAML read of ``grounding.yaml`` rather than calling
``load_grounding_config``: the server package imports ``pipelines`` (for these
very constants), so a pipeline CLI importing the server back would make the
dependency run both ways, and the strict loader would also make the CLI refuse
a ``grounding.yaml`` that carries keys it never reads. ``TestReadersAgree``
pins the two readers to the same defaults instead.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipelines.summary_native import cli, resolve, schema  # noqa: E402
from server.grounding_config_service import GroundingConfigService  # noqa: E402
from server.grounding_config_shared import (  # noqa: E402
    GROUNDING_DOCS,
    GroundingConfig,
    SummaryNativeRun,
    load_grounding_config,
    save_grounding_config,
)
from server.main import app  # noqa: E402
from server.platform_config_service import (  # noqa: E402
    TRACKED_CONFIG_NAME,
    PlatformConfigService,
)

ROUTER_SRC = Path(__file__).resolve().parent.parent / "server" / "routers" / "summary_native.py"


class TestModelDefaults:
    def test_declared_defaults(self):
        run = SummaryNativeRun()
        assert run.out_root == "docs/summary_native"
        assert run.recent_chapters == 4
        assert run.recurring_min == 10
        assert run.dup_threshold == 0.88
        assert not hasattr(run, "parts")  # retired by spec 034: every document is one call per section
        assert run.summaries_dir is None
        assert run.range_since is None and run.range_until is None

    def test_defaults_are_the_schema_constants(self):
        run = SummaryNativeRun()
        assert run.out_root == schema.DEFAULT_OUT_ROOT
        assert run.recent_chapters == schema.DEFAULT_RECENT_CHAPTERS
        assert run.recurring_min == schema.DEFAULT_RECURRING_MIN
        assert run.dup_threshold == schema.DEFAULT_DUP_THRESHOLD

    def test_path_keys_default_to_none_the_derive_it_sentinel(self):
        run = SummaryNativeRun()
        assert run.canon_file is None and run.registry is None

    def test_old_grounding_yaml_without_the_path_keys_loads(self, tmp_path):
        path = tmp_path / "grounding.yaml"
        path.write_text(
            yaml.safe_dump({"summary_native": {"out_root": "docs/sn"}}),
            encoding="utf-8",
        )
        run = load_grounding_config(path).summary_native
        assert run.canon_file is None and run.registry is None

    def test_a_stale_parts_key_is_refused_naming_the_fix_not_silently_dropped(self, tmp_path):
        path = tmp_path / "grounding.yaml"
        path.write_text(yaml.safe_dump({"summary_native": {"out_root": "docs/sn", "parts": 0}}), encoding="utf-8")
        with pytest.raises(ValueError, match="summary_native.parts is retired.*delete the `parts:` line"):
            load_grounding_config(path)

    def test_path_keys_round_trip(self, tmp_path):
        path = tmp_path / "grounding.yaml"
        cfg = GroundingConfig(summary_native=SummaryNativeRun(canon_file="c.yaml", registry="~/reg"))
        save_grounding_config(path, cfg)
        run = load_grounding_config(path).summary_native
        assert (run.canon_file, run.registry) == ("c.yaml", "~/reg")

    def test_strict(self):
        with pytest.raises(Exception):
            SummaryNativeRun.model_validate({"nope": 1})

    def test_not_a_promotable_doc(self):
        assert "summary_native" not in GROUNDING_DOCS

    def test_existing_grounding_yaml_without_the_group_loads(self, tmp_path):
        path = tmp_path / "grounding.yaml"
        path.write_text(
            yaml.safe_dump({"summaries": "docs/s.md", "distill": {"output": "o.md"}}),
            encoding="utf-8",
        )
        cfg = load_grounding_config(path)
        assert cfg.summaries == "docs/s.md"
        assert cfg.summary_native == SummaryNativeRun()

    def test_round_trips_through_save(self, tmp_path):
        path = tmp_path / "grounding.yaml"
        cfg = GroundingConfig(summary_native=SummaryNativeRun(range_since=3, range_until=9))
        save_grounding_config(path, cfg)
        assert load_grounding_config(path).summary_native.range_until == 9


class TestUnknownKeyIs400:
    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / TRACKED_CONFIG_NAME).write_text(
            "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(app.state, "platform", PlatformConfigService(tmp_path), raising=False)
        return TestClient(app), GroundingConfigService(tmp_path / "config")

    def test_unknown_key_in_the_group(self, client):
        c, _ = client
        r = c.put("/api/grounding/config", json={"summary_native": {"nope": 1}})
        assert r.status_code == 400

    def test_partial_merge_updates_one_field(self, client):
        c, svc = client
        assert c.put("/api/grounding/config",
                     json={"summary_native": {"range_since": 5}}).status_code == 200
        assert c.put("/api/grounding/config",
                     json={"summary_native": {"range_until": 8}}).status_code == 200
        run = svc.resolved().summary_native
        assert (run.range_since, run.range_until) == (5, 8)
        assert run.recent_chapters == schema.DEFAULT_RECENT_CHAPTERS


class TestReadersAgree:
    """The CLI's plain-YAML read and the strict model must not disagree."""

    def test_cli_reads_what_the_server_wrote(self, tmp_path):
        cfgdir = tmp_path / "config"
        cfgdir.mkdir()
        save_grounding_config(cfgdir / "grounding.yaml", GroundingConfig())
        assert cli._grounding_section(cfgdir / "config.yaml") == SummaryNativeRun().model_dump(mode="json")

    def test_cli_without_the_group_falls_back_to_the_model_defaults(self, tmp_path):
        cfgdir = tmp_path / "config"
        cfgdir.mkdir()
        (cfgdir / "grounding.yaml").write_text("summaries: docs/s.md\n", encoding="utf-8")
        assert cli._grounding_section(cfgdir / "config.yaml") == {}
        run = SummaryNativeRun()
        assert run.out_root == schema.DEFAULT_OUT_ROOT
        assert run.dup_threshold == schema.DEFAULT_DUP_THRESHOLD


class TestNoDriftInTheRouter:
    """No default literal may creep back into the route signatures."""

    SRC = ROUTER_SRC.read_text(encoding="utf-8")

    def test_no_out_root_literal(self):
        assert "docs/summary_native" not in self.SRC
        assert "canon.yaml" not in self.SRC

    @pytest.mark.parametrize("pattern", [
        r"=\s*4\b", r"=\s*10\b", r"\b0\.88\b",
        r'backend:\s*str\s*=\s*"anthropic"',
    ])
    def test_no_default_literal(self, pattern):
        offenders = [
            (n, line.strip())
            for n, line in enumerate(self.SRC.splitlines(), 1)
            if re.search(pattern, line)
            # Transport constants are not Summary Native route/config defaults.
            and not re.match(r"\s*[A-Z][A-Z0-9_]*\s*=", line)
        ]
        assert not offenders, offenders

    def test_the_defaults_are_declared_where_they_belong(self):
        shared = (ROUTER_SRC.parent.parent / "grounding_config_shared.py").read_text(encoding="utf-8")
        assert "DEFAULT_OUT_ROOT" in shared and "DEFAULT_DUP_THRESHOLD" in shared
        assert "0.88" not in shared and "docs/summary_native" not in shared


class TestExtractAndProseBlocks:
    """Spec 033 T008/T011: the ``extract:`` and ``prose:`` blocks, declared once in schema.py."""

    def test_extract_defaults_are_the_schema_constants(self):
        e = SummaryNativeRun().extract
        assert e.backend == schema.DEFAULT_DRAFT_BACKEND
        assert e.model == schema.DEFAULT_DRAFT_MODEL
        assert e.chunk_chars == schema.DEFAULT_CHUNK_CHARS

    def test_prose_defaults_are_the_schema_constants(self):
        p = SummaryNativeRun().prose
        assert p.backend == schema.DEFAULT_PROSE_BACKEND == "claude-code"
        assert p.model == schema.DEFAULT_PROSE_MODEL == "claude-sonnet-5-5"
        assert p.effort == schema.DEFAULT_PROSE_EFFORT == "medium"
        assert p.budgets == schema.DEFAULT_WORLD_BUDGETS

    def test_budgets_are_copied_not_shared(self):
        a, b = SummaryNativeRun(), SummaryNativeRun()
        a.prose.budgets["Party"] = 1
        assert b.prose.budgets["Party"] == schema.DEFAULT_WORLD_BUDGETS["Party"]
        assert schema.DEFAULT_WORLD_BUDGETS["Party"] == 700

    def test_party_and_planning_budget_defaults_are_the_schema_constants(self):
        """Spec 034 T010: declared once in schema.py, surfaced by the shared model."""
        p = SummaryNativeRun().prose
        assert p.party_budgets == schema.DEFAULT_PARTY_BUDGETS == {
            "Party Overview": 300, "Characters": 500, "Party Dynamics": 300}
        assert p.planning_budgets == schema.DEFAULT_PLANNING_BUDGETS == {
            "NPC Dossiers": 1500, "Faction States": 600, "Active Plots": 1200, "DM Notes": 400}

    def test_party_and_planning_budgets_are_copied_not_shared(self):
        a, b = SummaryNativeRun(), SummaryNativeRun()
        a.prose.party_budgets["Characters"] = 1
        a.prose.planning_budgets["DM Notes"] = 1
        assert b.prose.party_budgets["Characters"] == schema.DEFAULT_PARTY_BUDGETS["Characters"] == 500
        assert b.prose.planning_budgets["DM Notes"] == schema.DEFAULT_PLANNING_BUDGETS["DM Notes"] == 400

    @pytest.mark.parametrize("payload", [
        {"party_budgets": {"Party": 100}},                 # a world_state section is not a party section
        {"party_budgets": {"Characters": 0}},
        {"party_budgets": {"Characters": -5}},
        {"planning_budgets": {"Key NPCs": 100}},
        {"planning_budgets": {"Active Plots": 0}},
        {"budgets": {"Characters": 100}},                  # and the reverse
    ])
    def test_the_new_budget_blocks_are_strict(self, payload):
        with pytest.raises(Exception):
            SummaryNativeRun.model_validate({"prose": payload})

    def test_the_new_budget_blocks_take_known_sections(self):
        """Like ``budgets``, a given mapping is stored as written; ``resolve_prose`` merges it over the defaults."""
        p = SummaryNativeRun.model_validate(
            {"prose": {"party_budgets": {"Characters": 700}, "planning_budgets": {"DM Notes": 200}}}).prose
        assert p.party_budgets == {"Characters": 700} and p.planning_budgets == {"DM Notes": 200}
        assert p.budgets == schema.DEFAULT_WORLD_BUDGETS

    def test_an_old_prose_block_without_them_loads_with_defaults(self, tmp_path):
        path = tmp_path / "grounding.yaml"
        path.write_text(yaml.safe_dump({"summary_native": {"prose": {"budgets": {"Party": 10}}}}), encoding="utf-8")
        p = load_grounding_config(path).summary_native.prose
        assert p.party_budgets == schema.DEFAULT_PARTY_BUDGETS and p.planning_budgets == schema.DEFAULT_PLANNING_BUDGETS

    def test_resolve_prose_merges_the_new_blocks_over_the_schema_defaults(self):
        s = resolve.resolve_prose({"prose": {"party_budgets": {"Characters": 700}, "planning_budgets": {"DM Notes": 200}}})
        assert s.party_budgets == {**schema.DEFAULT_PARTY_BUDGETS, "Characters": 700}
        assert s.planning_budgets == {**schema.DEFAULT_PLANNING_BUDGETS, "DM Notes": 200}
        assert s.budgets == schema.DEFAULT_WORLD_BUDGETS
        d = resolve.resolve_prose({})
        assert (d.party_budgets, d.planning_budgets) == (schema.DEFAULT_PARTY_BUDGETS, schema.DEFAULT_PLANNING_BUDGETS)

    @pytest.mark.parametrize("block", [
        {"party_budgets": {"Nope": 5}}, {"planning_budgets": {"Key NPCs": 5}},
        {"party_budgets": {"Characters": 0}}, {"planning_budgets": [1]},
    ])
    def test_resolve_prose_refuses_a_bad_new_block(self, block):
        with pytest.raises(resolve.ConfigRefusal):
            resolve.resolve_prose({"prose": block})

    def test_the_other_constants(self):
        assert schema.DEFAULT_EXTRACT_PARALLEL == 6
        assert schema.DEFAULT_AUDIT_CANDIDATES == 3
        assert schema.STATE_DIR == "state"
        assert schema.TIMELINE_FILE == "canon_events_timeline.md"
        assert (schema.LATER, schema.SINCE, schema.UNVERIFIED) == ("⚠ later:", "ℹ since:", "⚠ unverified:")

    @pytest.mark.parametrize("block,key", [
        ("extract", "endpoints"), ("extract", "endpoint"), ("extract", "parallel"),
        ("prose", "endpoints"), ("prose", "nope"),
    ])
    def test_unknown_block_keys_are_refused(self, block, key):
        with pytest.raises(Exception):
            SummaryNativeRun.model_validate({block: {key: 1}})

    def test_fallback_npc_lines_is_never_a_config_key(self):
        """GM ruling 2026-10-07: per run only, never persisted."""
        for payload in (
            {"fallback_npc_lines": True},
            {"prose": {"fallback_npc_lines": True}},
            {"extract": {"fallback_npc_lines": True}},
        ):
            with pytest.raises(Exception):
                SummaryNativeRun.model_validate(payload)
        assert "fallback_npc_lines" not in SummaryNativeRun().model_dump()

    def test_partial_blocks_keep_the_other_defaults(self):
        run = SummaryNativeRun.model_validate({"extract": {"model": "m"}, "prose": {"effort": "high"}})
        assert run.extract.model == "m" and run.extract.backend == schema.DEFAULT_DRAFT_BACKEND
        assert run.prose.effort == "high" and run.prose.model == schema.DEFAULT_PROSE_MODEL

    def test_bad_values_are_refused(self):
        for payload in (
            {"extract": {"chunk_chars": 0}},
            {"extract": {"model": "  "}},
            {"prose": {"effort": "minimal"}},
            {"prose": {"budgets": {"Party": 0}}},
            {"prose": {"budgets": {"Not A Section": 100}}},
        ):
            with pytest.raises(Exception):
                SummaryNativeRun.model_validate(payload)

    def test_old_grounding_yaml_without_the_blocks_loads_with_defaults(self, tmp_path):
        path = tmp_path / "grounding.yaml"
        path.write_text(yaml.safe_dump({"summary_native": {"recent_chapters": 2}}), encoding="utf-8")
        run = load_grounding_config(path).summary_native
        assert run.extract == SummaryNativeRun().extract and run.prose == SummaryNativeRun().prose

    def test_blocks_round_trip_through_save(self, tmp_path):
        path = tmp_path / "grounding.yaml"
        run = SummaryNativeRun.model_validate({"extract": {"chunk_chars": 5000}, "prose": {"budgets": {"Party": 300}}})
        save_grounding_config(path, GroundingConfig(summary_native=run))
        back = load_grounding_config(path).summary_native
        assert back.extract.chunk_chars == 5000 and back.prose.budgets["Party"] == 300

    def test_cli_reads_the_blocks_the_server_wrote(self, tmp_path):
        cfgdir = tmp_path / "config"
        cfgdir.mkdir()
        save_grounding_config(cfgdir / "grounding.yaml", GroundingConfig())
        got = cli._grounding_section(cfgdir / "config.yaml")
        assert got["extract"] == SummaryNativeRun().extract.model_dump(mode="json")
        assert got["prose"] == SummaryNativeRun().prose.model_dump(mode="json")


class TestResolvePrecedence:
    """flag > grounding.yaml > schema (031's rule), for the extract and prose settings."""

    def test_extract_defaults(self):
        s = resolve.resolve_extract({})
        assert (s.backend, s.model, s.chunk_chars) == (
            schema.DEFAULT_DRAFT_BACKEND, schema.DEFAULT_DRAFT_MODEL, schema.DEFAULT_CHUNK_CHARS)

    def test_extract_config_beats_schema_and_flag_beats_config(self):
        cfg = {"extract": {"backend": "dgx", "model": "cfg-model", "chunk_chars": 1000}}
        s = resolve.resolve_extract(cfg)
        assert (s.model, s.chunk_chars) == ("cfg-model", 1000)
        s = resolve.resolve_extract(cfg, model="flag-model", chunk_chars=2000)
        assert (s.model, s.chunk_chars) == ("flag-model", 2000)

    def test_prose_defaults(self):
        s = resolve.resolve_prose({})
        assert (s.backend, s.model, s.effort) == (
            schema.DEFAULT_PROSE_BACKEND, schema.DEFAULT_PROSE_MODEL, schema.DEFAULT_PROSE_EFFORT)
        assert s.budgets == schema.DEFAULT_WORLD_BUDGETS

    def test_prose_config_and_flag_precedence(self):
        cfg = {"prose": {"backend": "claude-code", "model": "m1", "effort": "low", "budgets": {"Party": 10}}}
        s = resolve.resolve_prose(cfg)
        assert (s.model, s.effort) == ("m1", "low")
        assert s.budgets["Party"] == 10 and s.budgets["Key NPCs"] == schema.DEFAULT_WORLD_BUDGETS["Key NPCs"]
        s = resolve.resolve_prose(cfg, model="m2", effort="high")
        assert (s.model, s.effort) == ("m2", "high")

    def test_another_backend_does_not_inherit_the_schema_model(self):
        """A model id belongs to its backend: a spark model id must not reach anthropic."""
        s = resolve.resolve_extract({"extract": {"backend": "anthropic", "model": schema.DEFAULT_DRAFT_MODEL}})
        assert s.backend == "anthropic" and s.model is None
        assert resolve.resolve_extract({}, backend="anthropic").model is None
        assert resolve.resolve_prose({}, backend="dgx").model is None
        assert resolve.resolve_prose({}, backend="dgx", model="x").model == "x"

    def test_effort_only_applies_to_claude_code(self):
        assert resolve.resolve_prose({}, backend="dgx").effort is None

    def test_bad_config_values_refuse(self):
        with pytest.raises(resolve.ConfigRefusal):
            resolve.resolve_extract({"extract": {"chunk_chars": "lots"}})


class TestSchedulerFlagFamily:
    """Shared controls keep one spelling and no parser-owned concurrency default."""

    @pytest.mark.parametrize("command,remote", [
        ("extract", True), ("audit", True), ("npc-draft", True), ("npc-verify", False),
    ])
    def test_parallel_and_resume_have_one_contract_across_operations(self, command, remote):
        parser = cli.build_parser()
        args = parser.parse_args([command, "--summaries-dir", "docs/summaries", "--since", "2", "--until", "6"])
        assert args.parallel is None and args.resume is None
        if remote:
            assert args.endpoints is None
            parsed = parser.parse_args([command, "--summaries-dir", "docs/summaries", "--since", "2", "--until", "6",
                                        "--endpoints", "http://spark-a/v1", "http://spark-b/v1", "--parallel", "3", "--resume", "run-17"])
            assert parsed.endpoints == ["http://spark-a/v1", "http://spark-b/v1"]
        else:
            parsed = parser.parse_args([command, "--summaries-dir", "docs/summaries", "--since", "2", "--until", "6",
                                        "--parallel", "3", "--resume", "run-17"])
            assert not hasattr(parsed, "endpoints")
        assert parsed.parallel == 3 and parsed.resume == "run-17"
        bare = parser.parse_args([command, "--summaries-dir", "docs/summaries", "--since", "2", "--until", "6", "--resume"])
        assert bare.resume == ""


class TestNoDriftInTheRouterForSpec033:
    SRC = ROUTER_SRC.read_text(encoding="utf-8")

    @pytest.mark.parametrize("pattern", [
        r"claude-sonnet", r"\b60000\b",
        r"=\s*6\b", r"=\s*3\b",                       # DEFAULT_EXTRACT_PARALLEL, DEFAULT_AUDIT_CANDIDATES
        r'effort[^\n]*=\s*"medium"',
        r'(backend|model)[^\n]*=\s*"(dgx|claude-code)"',
    ])
    def test_no_default_literal(self, pattern):
        offenders = [
            (n, line.strip())
            for n, line in enumerate(self.SRC.splitlines(), 1)
            if re.search(pattern, line)
        ]
        assert not offenders, offenders

    def test_new_defaults_are_surfaced_by_the_shared_model_not_spelled_in_it(self):
        shared = (ROUTER_SRC.parent.parent / "grounding_config_shared.py").read_text(encoding="utf-8")
        for name in ("DEFAULT_PROSE_BACKEND", "DEFAULT_PROSE_MODEL", "DEFAULT_PROSE_EFFORT", "DEFAULT_WORLD_BUDGETS"):
            assert name in shared
        assert "claude-sonnet" not in shared and "700" not in shared
