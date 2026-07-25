"""Unit tests for PlatformConfigService — the platform-tier half of the old
``CampaignConfigService`` split, per docs/config/platform-isolation.md
Phase 2, plus Phase 3 (O3)'s relocation of ``runtime`` into its own file.

Covers what THIS class owns outright — ``config.yaml`` (``tracked``),
``.campaigngenerator.local.yaml`` (``local``/``update_local``, including the
warn-and-drop-on-bad-YAML load precedent moved here from
``tests/test_config_service.py`` and the now-strict-model tests moved here
from ``tests/test_config_models.py``), and — as of Phase 3 — ``<config>/
platform.yaml`` (``runtime``/``update_runtime``) outright, no delegation to
``UIStateService`` any more. ``.resolved()`` stays a thin passthrough to
``UIStateService.resolved()`` (see that method's docstring for why); this
file covers ``runtime`` storage itself, not the resolved/rebase mechanics
that live in ``tests/test_config_service.py``. Construction, path
resolution, and ``ui.<section>`` mechanics that don't touch
``local``/``runtime`` stay in ``tests/test_config_service.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.config_service import UIStateService
from server.platform_config_service import (
    ConfigError,
    PlatformConfigService,
    TRACKED_CONFIG_NAME,
)
from server.platform_config_shared import (
    LOCAL_CONFIG_NAME,
    PLATFORM_CONFIG_NAME,
    PlatformConfig,
    PlatformDocument,
    PlatformLocalConfig,
    PlatformNav,
    PlatformRuntime,
    PlatformServer,
    load_local_config,
    load_platform_config,
    save_local_config,
    save_platform_config,
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
            platform.update_local({"ui": {"query": {}}})
        # Rejected outright — nothing partially written.
        assert platform.local.server.port == 5000

    def test_config_yaml_never_touched_by_local_writes(self, fresh_campaign):
        original = (fresh_campaign / CONFIG_SUBDIR / TRACKED_CONFIG_NAME).read_bytes()
        platform = PlatformConfigService(fresh_campaign)
        platform.update_local({"server": {"port": 6001}})
        assert (
            fresh_campaign / CONFIG_SUBDIR / TRACKED_CONFIG_NAME
        ).read_bytes() == original


# ── runtime: owned outright by PlatformConfigService (Phase 3, O3) ─────────


class TestRuntimeOwnership:
    def test_update_runtime_persists_into_platform_yaml(self, fresh_campaign):
        # runtime moved out of ui_state.yaml in Phase 3 — see
        # PlatformConfigService's module docstring. update_runtime must
        # create/write ONLY platform.yaml, never touch ui_state.yaml.
        platform = PlatformConfigService(fresh_campaign)
        assert not (fresh_campaign / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME).exists()
        platform.update_runtime({"default_model": "claude-opus-4-6"})
        on_disk = yaml.safe_load(
            (fresh_campaign / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME).read_text()
        )
        assert on_disk["runtime"]["default_model"] == "claude-opus-4-6"
        # ui_state.yaml was never created by this write — no ui.<section>
        # write has happened yet in this test.
        assert not (fresh_campaign / CONFIG_SUBDIR / "ui_state.yaml").exists()

    def test_update_runtime_merges_not_replaces(self, fresh_campaign):
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime({"session_dir": "summaries/sess1"})
        platform.update_runtime({"default_model": "claude-opus-4-6"})
        assert platform.runtime.session_dir == "summaries/sess1"
        assert platform.runtime.default_model == "claude-opus-4-6"

    def test_runtime_property_reads_platform_yaml_directly(self, fresh_campaign):
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime({"session_dir": "summaries/sess1"})
        assert isinstance(platform.runtime, PlatformRuntime)
        assert platform.runtime.session_dir == "summaries/sess1"
        # No more UIStateService delegation to compare against — runtime is
        # this class's own in-memory state now, re-read straight from disk
        # for good measure.
        reloaded = load_platform_config(
            fresh_campaign / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME
        )
        assert platform.runtime == reloaded.runtime

    def test_resolved_carries_no_ui_key(self, fresh_campaign):
        """``resolved()`` came home to the platform and dropped ``ui`` with the
        move — docs/config/ui-state-retirement.md. It used to be a passthrough
        to ``UIStateService.resolved()``, whose extra ``ui`` key held six
        sections that were empty in every campaign and had no writer."""
        platform = PlatformConfigService(fresh_campaign)
        resolved = platform.resolved()
        assert "ui" not in resolved
        assert set(resolved) == {"campaign_dir", "runtime", "server", "nav"}

    def test_resolved_wire_shape_still_carries_runtime(self, fresh_campaign):
        # Requirement 1 of Phase 3: relocating runtime's STORAGE must not
        # change resolved()'s READ shape. The HTTP-level version of this
        # assertion lives in tests/test_config_routes.py
        # (TestPutRuntime.test_runtime_update_persists / TestGetConfig); this
        # is the service-level twin.
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime(
            {"session_dir": "summaries/sess1", "default_model": "claude-opus-4-6"}
        )
        resolved = platform.resolved()
        assert "runtime" in resolved
        assert resolved["runtime"]["default_model"] == "claude-opus-4-6"
        assert resolved["runtime"]["session_dir"].endswith("summaries/sess1")


# ── The isolation invariant: a ui.<section> write cannot touch platform.yaml ┐
# The whole point of O3 — see docs/config/platform-isolation.md problem #2
# ("a write to any of ten loose UI sections re-serializes the same
# ui_state.yaml that holds runtime"). Phase 3 fixes this by construction
# (separate files, separate writers); this test is the regression guard.


class TestIsolationInvariant:
    def test_ui_section_write_cannot_touch_platform_yaml(self, fresh_campaign):
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime(
            {"session_dir": "summaries/sess1", "default_model": "claude-opus-4-6"}
        )
        platform_yaml_path = fresh_campaign / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME
        before = platform_yaml_path.read_bytes()

        # A loose ui.<section> write — the kind the old fused
        # CampaignConfigService re-serialized the WHOLE document for,
        # including runtime.
        platform.uis.update_section("prep", {"some_field": "value"})
        platform.uis.update_section("query", {"summaries": "summaries.md"})

        after = platform_yaml_path.read_bytes()
        assert after == before, (
            "a ui.<section> write touched platform.yaml — the isolation "
            "invariant O3 exists to guarantee is broken"
        )

    def test_ui_section_write_cannot_touch_platform_yaml_via_route(self, fresh_campaign):
        # Same invariant, exercised through the HTTP route a real UI save
        # goes through — PUT /api/config/section/{name}.
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from server.routers import config_routes

        app = FastAPI()
        app.include_router(config_routes.router, prefix="/api/config")
        app.state.platform = PlatformConfigService(fresh_campaign)
        app.state.platform.update_runtime(
            {"session_dir": "summaries/sess1", "default_model": "claude-opus-4-6"}
        )
        client = TestClient(app)

        platform_yaml_path = fresh_campaign / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME
        before = platform_yaml_path.read_bytes()

        resp = client.put(
            "/api/config/section/prep",
            json={"values": {"some_field": "value"}},
        )
        assert resp.status_code == 200

        after = platform_yaml_path.read_bytes()
        assert after == before


# ── Boot-override precedence ─────────────────────────────────────────────


class TestBootOverridePrecedence:
    def test_boot_override_wins_over_persisted_session_dir(self, fresh_campaign):
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime({"session_dir": "summaries/persisted"})

        booted = PlatformConfigService(
            fresh_campaign,
            boot_overrides={"runtime.session_dir": "summaries/booted"},
        )
        resolved = booted.resolved()
        assert resolved["runtime"]["session_dir"].endswith("summaries/booted")
        # The override never touches the persisted value on disk.
        assert platform.runtime.session_dir == "summaries/persisted"
        on_disk = load_platform_config(
            fresh_campaign / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME
        )
        assert on_disk.runtime.session_dir == "summaries/persisted"


# ── platform.yaml present vs. absent ──────────────────────────────────────


class TestPlatformYamlPresenceHandling:
    def test_missing_platform_yaml_loads_as_all_defaults(self, fresh_campaign):
        # Matches session_doc.yaml's contract: a missing file is a
        # legitimate first-launch state, not an error.
        assert not (fresh_campaign / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME).exists()
        platform = PlatformConfigService(fresh_campaign)
        assert platform.runtime.session_dir is None
        assert platform.runtime.default_model  # env fallback or literal

    def test_present_platform_yaml_is_honored(self, fresh_campaign):
        _write(
            fresh_campaign / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME,
            "runtime:\n  default_model: claude-opus-4-6\n  session_dir: summaries/sess1\n",
        )
        platform = PlatformConfigService(fresh_campaign)
        assert platform.runtime.default_model == "claude-opus-4-6"
        assert platform.runtime.session_dir == "summaries/sess1"

    def test_malformed_platform_yaml_raises_config_error_at_construction(
        self, fresh_campaign
    ):
        # Unlike the local file's warn-and-drop, a bad platform.yaml is
        # load-bearing (runtime.session_dir feeds path resolution during
        # construction) and must fail loudly — see load_platform_config's
        # docstring.
        _write(fresh_campaign / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME, "runtime: : :")
        with pytest.raises(ConfigError, match="platform.yaml failed to load"):
            PlatformConfigService(fresh_campaign)


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


# ── discover_campaign_paths — O2's narrowed, discovery-only helper ─────────
# docs/config/platform-isolation.md O2: this is what survives from the old
# server/config.py::derive_campaign_paths after its derivation half
# (output_dir, DERIVED_SUBDIRS, the hardcoded voice/examples layout) was
# deleted outright. A bare @staticmethod — no config.yaml, no live
# PlatformConfigService instance required — matching how SessionConfig.vue's
# deriveAll() calls it: on a campaign_dir that may not even be
# app.state.platform yet.


class TestDiscoverCampaignPaths:
    def test_voice_and_examples_are_probes_not_formulas(self, tmp_path):
        """``voice_dir``/``examples_dir`` must stay an ``is_dir()`` probe that
        yields ``""`` when the conventional directory is absent — NOT an
        unconditional ``<campaign>/voice`` string.

        ``SessionConfig.vue``'s ``deriveAll()`` runs on a debounced watch of
        campaign_dir/session_dir and guards each assignment with
        ``if (d.voice_dir)``. If this returned a path unconditionally, that
        guard would always pass and every session switch would silently
        overwrite a GM's custom voice directory with one that doesn't exist.
        The single-candidate path looks like layout arithmetic; the existence
        check is what makes it discovery, and it is load-bearing.
        """
        campaign = tmp_path / "campaign"
        session = campaign / "summaries" / "s1"
        session.mkdir(parents=True)
        (campaign / "voice").mkdir()  # present; examples/ deliberately absent

        result = PlatformConfigService.discover_campaign_paths(str(campaign), str(session))

        assert result["voice_dir"] == str(campaign / "voice")
        assert result["examples_dir"] == "", (
            "examples/ does not exist, so discovery must report nothing rather "
            "than a path — see this test's docstring"
        )

    def test_finds_gm_recap_and_summaries(self, tmp_path):
        campaign = tmp_path / "campaign"
        session = campaign / "summaries" / "20260318"
        session.mkdir(parents=True)
        (session / "session.vtt").write_text("x", encoding="utf-8")
        (session / "gm-assist.md").write_text("x", encoding="utf-8")
        (campaign / "summaries.md").write_text("x", encoding="utf-8")

        result = PlatformConfigService.discover_campaign_paths(str(campaign), str(session))

        # The raw *.vtt is deliberately NOT discovered: the page that used
        # it went with the vtt_summary chain, and the Session Doc Editor
        # globs the session dir itself (scene_editor._vtt_path).
        assert "vtt_input" not in result
        assert result["gm_recap"] == str(session / "gm-assist.md")
        assert result["summaries"] == str(campaign / "summaries.md")

    def test_sniffs_recap_and_summary_filename_variants(self, tmp_path):
        # gm_assist.md (underscore) is the second candidate tried, after
        # gm-assist.md (hyphen); session-clean.md is the second
        # session_summary candidate. Exercise the non-first-choice branch
        # of each sniff loop.
        campaign = tmp_path / "campaign"
        session = campaign / "summaries" / "s1"
        session.mkdir(parents=True)
        (session / "gm_assist.md").write_text("x", encoding="utf-8")
        (session / "session-clean.md").write_text("x", encoding="utf-8")

        result = PlatformConfigService.discover_campaign_paths(str(campaign), str(session))
        assert result["gm_recap"] == str(session / "gm_assist.md")
        assert result["session_summary"] == str(session / "session-clean.md")

    def test_sniffs_legacy_all_summaries_name(self, tmp_path):
        campaign = tmp_path / "campaign"
        session = campaign / "summaries" / "s1"
        session.mkdir(parents=True)
        (campaign / "all_summaries.md").write_text("x", encoding="utf-8")

        result = PlatformConfigService.discover_campaign_paths(str(campaign), str(session))
        assert result["summaries"] == str(campaign / "all_summaries.md")

    def test_docs_md_exist_checks_mixed_present_and_absent(self, tmp_path):
        campaign = tmp_path / "campaign"
        session = campaign / "summaries" / "s1"
        docs = campaign / "docs"
        docs.mkdir(parents=True)
        session.mkdir(parents=True)
        (docs / "campaign_state.md").write_text("x", encoding="utf-8")
        (docs / "world_state.md").write_text("x", encoding="utf-8")
        # party.md and planning.md deliberately absent.

        result = PlatformConfigService.discover_campaign_paths(str(campaign), str(session))
        assert result["campaign_state"] == str(docs / "campaign_state.md")
        assert result["world_state"] == str(docs / "world_state.md")
        assert result["party"] == ""
        assert result["planning"] == ""

    def test_finds_party_config_and_npc_dossiers(self, tmp_path):
        campaign = tmp_path / "campaign"
        session = campaign / "summaries" / "s1"
        session.mkdir(parents=True)
        (campaign / "config").mkdir(parents=True)
        (campaign / "config" / "party.yaml").write_text("x", encoding="utf-8")
        npcs = campaign / "docs" / "npcs"
        npcs.mkdir(parents=True)
        (npcs / "npc_a.md").write_text("x", encoding="utf-8")
        (npcs / "npc_b.md").write_text("x", encoding="utf-8")

        result = PlatformConfigService.discover_campaign_paths(str(campaign), str(session))
        assert result["party_config"] == str(campaign / "config" / "party.yaml")
        assert str(npcs / "npc_a.md") in result["plan_npc"]
        assert str(npcs / "npc_b.md") in result["plan_npc"]

    def test_missing_files_degrade_gracefully_rather_than_raise(self, tmp_path):
        # A brand-new campaign with nothing on disk yet must not raise —
        # SessionConfig.vue's deriveAll() calls this on every debounced
        # keystroke in the campaign/session dir fields, well before
        # anything has been created.
        campaign = tmp_path / "campaign"
        session = campaign / "summaries" / "s1"
        session.mkdir(parents=True)

        result = PlatformConfigService.discover_campaign_paths(str(campaign), str(session))
        assert result["campaign_state"] == ""
        assert result["world_state"] == ""
        assert result["party"] == ""
        assert result["planning"] == ""
        assert result["party_config"] == ""
        for absent_key in ("gm_recap", "summaries", "plan_npc", "session_summary"):
            assert absent_key not in result

    def test_nonexistent_session_dir_does_not_raise(self, tmp_path):
        # session_dir itself need not exist yet (the user may still be
        # typing a not-yet-created directory) — glob()/exists() on a
        # missing directory just report nothing found, per Python's Path
        # semantics; this pins that we rely on it rather than pre-checking.
        campaign = tmp_path / "campaign"
        campaign.mkdir()
        session = campaign / "summaries" / "does-not-exist-yet"

        result = PlatformConfigService.discover_campaign_paths(str(campaign), str(session))
        assert "gm_recap" not in result
        assert "session_summary" not in result


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
            PlatformLocalConfig(ui={"query": {}})


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


# ── platform_config_shared.py — PlatformDocument + load/save (Phase 3, O3) ─


class TestPlatformDocument:
    def test_default_runtime(self):
        doc = PlatformDocument()
        assert doc.runtime.session_dir is None
        assert doc.runtime.default_model

    def test_unknown_top_level_key_rejected(self):
        # Strict, matching SessionEditorConfig/PlanningConfig per the
        # design doc's data model.
        with pytest.raises(ValidationError):
            PlatformDocument(server={"port": 6001})

    def test_runtime_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            PlatformRuntime(default_model="x", session_dir=None, bogus="y")


class TestLoadSavePlatformConfig:
    def test_missing_file_returns_defaults(self, tmp_path):
        # session-doc.yaml's contract, not the local file's: no warnings
        # tuple, just the all-defaults document.
        cfg = load_platform_config(tmp_path / PLATFORM_CONFIG_NAME)
        assert cfg == PlatformDocument()

    def test_round_trip(self, tmp_path):
        path = tmp_path / PLATFORM_CONFIG_NAME
        save_platform_config(
            path,
            PlatformDocument(
                runtime=PlatformRuntime(
                    default_model="claude-opus-4-6", session_dir="summaries/sess1"
                )
            ),
        )
        cfg = load_platform_config(path)
        assert cfg.runtime.default_model == "claude-opus-4-6"
        assert cfg.runtime.session_dir == "summaries/sess1"

    def test_malformed_yaml_raises_value_error(self, tmp_path):
        path = tmp_path / PLATFORM_CONFIG_NAME
        path.write_text("runtime: : :", encoding="utf-8")
        with pytest.raises(ValueError, match="invalid YAML"):
            load_platform_config(path)

    def test_unknown_key_raises_validation_error(self, tmp_path):
        # Strict, unguarded — unlike load_local_config, a schema mismatch
        # is NOT warned-and-dropped. See load_platform_config's docstring
        # for why platform.yaml gets session_doc.yaml's contract, not the
        # local file's.
        path = tmp_path / PLATFORM_CONFIG_NAME
        path.write_text("runtime:\n  bogus: true\n", encoding="utf-8")
        with pytest.raises(ValidationError):
            load_platform_config(path)

    def test_save_is_atomic(self, tmp_path, monkeypatch):
        import os

        path = tmp_path / PLATFORM_CONFIG_NAME
        save_platform_config(
            path, PlatformDocument(runtime=PlatformRuntime(default_model="a"))
        )
        before = path.read_bytes()

        original_replace = os.replace

        def boom(*args, **kwargs):
            raise OSError("simulated mid-write crash")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError, match="simulated"):
            save_platform_config(
                path, PlatformDocument(runtime=PlatformRuntime(default_model="b"))
            )
        monkeypatch.setattr(os, "replace", original_replace)

        assert path.read_bytes() == before
