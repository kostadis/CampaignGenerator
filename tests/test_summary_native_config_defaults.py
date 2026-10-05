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

from pipelines.summary_native import cli, schema  # noqa: E402
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
        assert run.parts == 0
        assert run.summaries_dir is None
        assert run.range_since is None and run.range_until is None

    def test_defaults_are_the_schema_constants(self):
        run = SummaryNativeRun()
        assert run.out_root == schema.DEFAULT_OUT_ROOT
        assert run.recent_chapters == schema.DEFAULT_RECENT_CHAPTERS
        assert run.recurring_min == schema.DEFAULT_RECURRING_MIN
        assert run.dup_threshold == schema.DEFAULT_DUP_THRESHOLD
        assert run.parts == schema.DEFAULT_PARTS

    def test_path_keys_default_to_none_the_derive_it_sentinel(self):
        run = SummaryNativeRun()
        assert run.canon_file is None and run.registry is None

    def test_old_grounding_yaml_without_the_path_keys_loads(self, tmp_path):
        path = tmp_path / "grounding.yaml"
        path.write_text(
            yaml.safe_dump({"summary_native": {"out_root": "docs/sn", "parts": 2}}),
            encoding="utf-8",
        )
        run = load_grounding_config(path).summary_native
        assert run.canon_file is None and run.registry is None and run.parts == 2

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
        ]
        assert not offenders, offenders

    def test_the_defaults_are_declared_where_they_belong(self):
        shared = (ROUTER_SRC.parent.parent / "grounding_config_shared.py").read_text(encoding="utf-8")
        assert "DEFAULT_OUT_ROOT" in shared and "DEFAULT_DUP_THRESHOLD" in shared
        assert "0.88" not in shared and "docs/summary_native" not in shared
