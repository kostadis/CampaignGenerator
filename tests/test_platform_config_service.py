"""Unit tests for PlatformConfigService — the platform-tier half of the old
``CampaignConfigService`` split, per docs/config/platform-isolation.md
Phase 2.

Covers what THIS class owns outright — ``config.yaml`` (``tracked``),
``.campaigngenerator.local.yaml`` (``local``/``update_local``, including the
warn-and-drop-on-bad-YAML load precedent moved here from
``tests/test_config_service.py`` and the now-strict-model tests moved here
from ``tests/test_config_models.py``) — plus the delegation seam to
``UIStateService`` for ``runtime`` (``update_runtime``/``.runtime``,
``.resolved()``) and for the ``base="session"`` fallback inside
``resolve_path``/``relativize_path``. Construction, path resolution, and
``ui.<section>`` mechanics that don't touch ``local``/``runtime`` stay in
``tests/test_config_service.py`` — this file is deliberately narrow to the
seam this phase introduced.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.config_service import UIStateService
from server.platform_config_service import PlatformConfigService, TRACKED_CONFIG_NAME
from server.platform_config_shared import (
    LOCAL_CONFIG_NAME,
    PlatformConfig,
    PlatformLocalConfig,
    PlatformNav,
    PlatformRuntime,
    PlatformServer,
    load_local_config,
    save_local_config,
)

CONFIG_SUBDIR = "config"


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.fixture
def fresh_campaign(tmp_path):
    """A campaign dir with only ``config.yaml``."""
    _write(
        tmp_path / CONFIG_SUBDIR / TRACKED_CONFIG_NAME,
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
    )
    return tmp_path


# ── Construction wires UIStateService as the last step ──────────────────────


class TestConstruction:
    def test_uis_is_a_uistateservice_composing_this_platform(self, fresh_campaign):
        platform = PlatformConfigService(fresh_campaign)
        assert isinstance(platform.uis, UIStateService)
        assert platform.uis.platform is platform

    def test_local_yaml_syntax_error_does_not_block_startup(self, fresh_campaign):
        # Moved from tests/test_config_service.py: local is now
        # PlatformConfigService's file, but the "machine cruft, don't
        # refuse to boot over it" contract is unchanged.
        _write(fresh_campaign / CONFIG_SUBDIR / LOCAL_CONFIG_NAME, "server: : :")
        platform = PlatformConfigService(fresh_campaign)
        assert any("could not be parsed" in w for w in platform.load_warnings)

    def test_local_yaml_unknown_key_warns_and_drops_rather_than_raises(
        self, fresh_campaign
    ):
        # The behavior the "Strictness rule" exists for: tightening
        # PlatformLocalConfig to extra="forbid" must not turn a stray,
        # hand-edited, or stale on-disk key into a boot-blocking crash.
        _write(
            fresh_campaign / CONFIG_SUBDIR / LOCAL_CONFIG_NAME,
            "server:\n  port: 6001\nsomething_stale: true\n",
        )
        platform = PlatformConfigService(fresh_campaign)
        assert any("failed schema validation" in w for w in platform.load_warnings)
        # Falls back to all-defaults rather than partially adopting the
        # unvalidatable file — same "ignore file contents" contract as a
        # parse error.
        assert platform.local.server.port == 5000


# ── local ownership: read + write ────────────────────────────────────────


class TestLocalOwnership:
    def test_default_local_config(self, fresh_campaign):
        platform = PlatformConfigService(fresh_campaign)
        assert platform.local.server.host == "127.0.0.1"
        assert platform.local.server.port == 5000
        assert platform.local.nav.last_page is None

    def test_update_local_persists(self, fresh_campaign):
        # Moved from tests/test_config_service.py's TestUpdateSection.
        platform = PlatformConfigService(fresh_campaign)
        platform.update_local({"server": {"port": 6001}})
        on_disk = yaml.safe_load(
            (fresh_campaign / CONFIG_SUBDIR / LOCAL_CONFIG_NAME).read_text()
        )
        assert on_disk["server"]["port"] == 6001

    def test_update_local_merges_not_replaces(self, fresh_campaign):
        platform = PlatformConfigService(fresh_campaign)
        platform.update_local({"server": {"port": 6001}})
        platform.update_local({"nav": {"last_page": "/workflow/editor"}})
        assert platform.local.server.port == 6001
        assert platform.local.server.host == "127.0.0.1"
        assert platform.local.nav.last_page == "/workflow/editor"

    def test_update_local_rejects_unknown_top_level_key(self, fresh_campaign):
        # A live write (unlike a load) is a real caller bug, not machine
        # cruft — this is the one deliberate, narrow behavior change
        # tightening the model requires; see the comment in
        # tests/test_config_routes.py's test_local_rejects_ui_top_level_key
        # for the route-level version of this same contract.
        platform = PlatformConfigService(fresh_campaign)
        with pytest.raises(ValidationError):
            platform.update_local({"ui": {"vtt_summary": {}}})
        # Rejected outright — nothing partially written.
        assert platform.local.server.port == 5000

    def test_config_yaml_never_touched_by_local_writes(self, fresh_campaign):
        original = (fresh_campaign / CONFIG_SUBDIR / TRACKED_CONFIG_NAME).read_bytes()
        platform = PlatformConfigService(fresh_campaign)
        platform.update_local({"server": {"port": 6001}})
        assert (
            fresh_campaign / CONFIG_SUBDIR / TRACKED_CONFIG_NAME
        ).read_bytes() == original


# ── runtime: delegated to UIStateService, not owned outright this phase ────


class TestRuntimeDelegation:
    def test_update_runtime_persists_into_ui_state_yaml(self, fresh_campaign):
        # runtime still lives inside ui_state.yaml this phase — see
        # PlatformConfigService's module docstring. update_runtime must
        # NOT create a separate platform.yaml (that's Phase 3).
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime({"default_model": "claude-opus-4-6"})
        assert not (fresh_campaign / CONFIG_SUBDIR / "platform.yaml").exists()
        on_disk = yaml.safe_load(
            (fresh_campaign / CONFIG_SUBDIR / "ui_state.yaml").read_text()
        )
        assert on_disk["runtime"]["default_model"] == "claude-opus-4-6"

    def test_runtime_property_reflects_uis_state(self, fresh_campaign):
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime({"session_dir": "summaries/sess1"})
        assert isinstance(platform.runtime, PlatformRuntime)
        assert platform.runtime.session_dir == "summaries/sess1"
        # Same value UIStateService itself reports — one store, two readers.
        assert platform.runtime.session_dir == platform.uis.ui_state.runtime.session_dir

    def test_resolved_is_a_passthrough_to_uis(self, fresh_campaign):
        platform = PlatformConfigService(fresh_campaign)
        platform.uis.update_section("grounding", {"summaries": "summaries.md"})
        assert platform.resolved() == platform.uis.resolved()


# ── snapshot / tracked / wiring ──────────────────────────────────────────


class TestReadOnlyAccessors:
    def test_tracked_is_read_only_config_yaml(self, fresh_campaign):
        platform = PlatformConfigService(fresh_campaign)
        assert platform.tracked["documents"][0]["label"] == "world_state"

    def test_snapshot_combines_runtime_and_local(self, fresh_campaign):
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime({"default_model": "claude-opus-4-6"})
        platform.update_local({"server": {"port": 6001}})
        snap = platform.snapshot()
        assert isinstance(snap, PlatformConfig)
        assert snap.runtime.default_model == "claude-opus-4-6"
        assert snap.server.port == 6001

    def test_wiring_defaults_to_empty_dict_when_unrendered(self, fresh_campaign):
        # No config/wiring.yaml on this machine (docs/config/
        # platform-isolation.md's "Risks" section) — must degrade to {},
        # not raise.
        platform = PlatformConfigService(fresh_campaign)
        assert platform.wiring == {} or isinstance(platform.wiring, dict)


# ── platform_config_shared.py — strict models + module-level I/O ───────────
# Moved from tests/test_config_models.py's TestLocalConfig/TestIntCoercion:
# LocalConfig/ServerSection moved here (as PlatformLocalConfig/
# PlatformServer) and were tightened from extra="allow"/"ignore" to
# extra="forbid".


class TestPlatformServerIntCoercion:
    def test_stringy_int_becomes_int(self):
        s = PlatformServer(port="6001")
        assert s.port == 6001
        assert isinstance(s.port, int)

    def test_empty_int_string_raises(self):
        with pytest.raises(ValidationError):
            PlatformServer(port="")

    def test_unknown_field_rejected(self):
        # Unlike the retired ServerSection (silently ignored extras),
        # PlatformServer is strict.
        with pytest.raises(ValidationError):
            PlatformServer(port=6001, bogus="x")


class TestPlatformLocalConfig:
    def test_default_server_settings(self):
        local = PlatformLocalConfig()
        assert local.server.host == "127.0.0.1"
        assert local.server.port == 5000

    def test_overrides(self):
        local = PlatformLocalConfig(server={"port": 6001})
        assert local.server.port == 6001
        assert local.server.host == "127.0.0.1"

    def test_nav_extras_rejected(self):
        # Was extra="allow" on the retired NavSection; PlatformNav is
        # strict, matching the design doc's tightening.
        with pytest.raises(ValidationError):
            PlatformLocalConfig(nav={"last_page": "/workflow/editor", "scroll": 42})

    def test_top_level_unknown_key_rejected(self):
        with pytest.raises(ValidationError):
            PlatformLocalConfig(ui={"vtt_summary": {}})


class TestLoadSaveLocalConfig:
    def test_missing_file_returns_defaults_no_warnings(self, tmp_path):
        cfg, warnings = load_local_config(tmp_path / LOCAL_CONFIG_NAME)
        assert cfg == PlatformLocalConfig()
        assert warnings == []

    def test_round_trip(self, tmp_path):
        path = tmp_path / LOCAL_CONFIG_NAME
        save_local_config(
            path,
            PlatformLocalConfig(
                server=PlatformServer(port=6001),
                nav=PlatformNav(last_page="/workflow/editor"),
            ),
        )
        cfg, warnings = load_local_config(path)
        assert warnings == []
        assert cfg.server.port == 6001
        assert cfg.nav.last_page == "/workflow/editor"

    def test_save_is_atomic(self, tmp_path, monkeypatch):
        # Mirrors TestAtomicWrites in test_config_service.py: a crash
        # between tmp.write and os.replace must leave the prior file
        # intact — this write path moved here, so the guarantee must move
        # with it.
        import os

        path = tmp_path / LOCAL_CONFIG_NAME
        save_local_config(path, PlatformLocalConfig(server=PlatformServer(port=5001)))
        before = path.read_bytes()

        original_replace = os.replace

        def boom(*args, **kwargs):
            raise OSError("simulated mid-write crash")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError, match="simulated"):
            save_local_config(path, PlatformLocalConfig(server=PlatformServer(port=6002)))
        monkeypatch.setattr(os, "replace", original_replace)

        assert path.read_bytes() == before
