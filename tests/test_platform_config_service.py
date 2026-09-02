"""Unit tests for PlatformConfigService — the platform-tier half of the old
``CampaignConfigService`` split, per docs/config/platform-isolation.md
Phase 2, plus Phase 3 (O3)'s relocation of ``runtime`` into its own file.

Covers what THIS class owns outright — ``config.yaml`` (``tracked``),
``.campaigngenerator.local.yaml`` (``local``/``update_local``, including the
warn-and-drop-on-bad-YAML load precedent moved here from
``tests/test_config_service.py`` and the now-strict-model tests moved here
from ``tests/test_config_models.py``), and — as of Phase 3 — ``<config>/
platform.yaml`` (``runtime``/``update_runtime``) outright, no delegation to
``UIStateService`` any more.

As of ``docs/config/ui-state-retirement.md`` this file is the whole story:
``UIStateService`` and ``tests/test_config_service.py`` are both deleted, and
``.resolved()`` — previously a thin passthrough to that class — is implemented
here and covered here. The ``ui.<section>`` mechanics that used to live in
that file (per-field path resolution, the sibling-session rebase, the
write-time relativize choke point) went with the sections themselves; the
surviving boot-override and path-resolution coverage moved into this file.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.platform_config_service import (
    ConfigError,
    IncompatibleSelection,
    PlatformConfigService,
    ResolvedSelection,
    TRACKED_CONFIG_NAME,
    resolve_selection,
    selection_cli_args,
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


# ── Construction ────────────────────────────────────────────────────────────


class TestConstruction:
    def test_no_uistateservice_sub_service(self, fresh_campaign):
        """``self.uis`` is gone — docs/config/ui-state-retirement.md. The
        construction-order hazard it created (platform.yaml had to load first,
        or the normalize pass re-anchored session-scoped paths against default
        runtime data) went with it."""
        platform = PlatformConfigService(fresh_campaign)
        assert not hasattr(platform, "uis")

    def test_boot_override_for_unknown_section_is_fatal(self, fresh_campaign):
        """An override with no consumer fails loudly at boot rather than being
        swept into a dict nothing reads. This is the assertion gap that let
        twelve dead ``session_doc.*`` flags survive (O1); ``resolved()``'s
        catch-all ``else`` branch is what hid them, and it is gone."""
        with pytest.raises(ConfigError, match="unknown section"):
            PlatformConfigService(
                fresh_campaign, boot_overrides={"query.label": "Boot Session"}
            )

    def test_known_boot_override_sections_still_apply(self, fresh_campaign):
        platform = PlatformConfigService(
            fresh_campaign,
            boot_overrides={"runtime.session_dir": "summaries/booted", "server.port": 6100},
        )
        resolved = platform.resolved()
        assert resolved["runtime"]["session_dir"].endswith("summaries/booted")
        assert resolved["server"]["port"] == 6100

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

    def test_backend_model_memory_round_trips_in_platform_yaml(self, fresh_campaign):
        """The sidebar's per-backend picks are durable platform state."""
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime({
            "default_backend": "codex-cli",
            "default_model": "",
            "default_models": {
                "anthropic": "claude-opus-4-6",
                "codex-cli": None,
            },
        })

        assert platform.runtime.default_models == {
            "anthropic": "claude-opus-4-6",
            "codex-cli": None,
        }
        reloaded = load_platform_config(
            fresh_campaign / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME
        )
        assert reloaded.runtime.default_models == platform.runtime.default_models

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


# ── The isolation invariant: no other service's write reaches platform.yaml ┐
# The whole point of O3 — see docs/config/platform-isolation.md problem #2
# ("a write to any of ten loose UI sections re-serializes the same
# ui_state.yaml that holds runtime"). Phase 3 fixed it by construction:
# separate files, separate writers.
#
# The original guard used a ui.<section> write as its probe, because that was
# the write with the largest blast radius. There is no such write any more
# (docs/config/ui-state-retirement.md), so the probe moves to the service that
# now has the widest reach into <config>/ — Grounding, which owns the document
# five former ui.<section> tenants collapsed into. The invariant under test is
# unchanged: one service's persist must never re-serialize another's document.


class TestIsolationInvariant:
    def test_another_services_write_cannot_touch_platform_yaml(self, fresh_campaign):
        from server.grounding_config_service import GroundingConfigService

        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime(
            {"session_dir": "summaries/sess1", "default_model": "claude-opus-4-6"}
        )
        platform_yaml_path = fresh_campaign / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME
        before = platform_yaml_path.read_bytes()

        grounding = GroundingConfigService(platform.config_path_base)
        grounding.update_config({"summaries": "docs/summaries.md"})
        grounding.update_config({"distill": {"chunk_size": 40000}})

        after = platform_yaml_path.read_bytes()
        assert after == before, (
            "a grounding write touched platform.yaml — the isolation "
            "invariant O3 exists to guarantee is broken"
        )

    def test_local_write_cannot_touch_platform_yaml(self, fresh_campaign):
        """The two documents this one service owns are still two documents:
        ``update_local`` and ``update_runtime`` share a lock, not a file."""
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime({"default_model": "claude-opus-4-6"})
        platform_yaml_path = fresh_campaign / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME
        before = platform_yaml_path.read_bytes()

        platform.update_local({"server": {"port": 6001}})

        assert platform_yaml_path.read_bytes() == before
        assert platform.runtime.default_model == "claude-opus-4-6"


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


# ── Batch resolution (feature 005-ui-batch-selection, T009) ────────────────
#
# Direct, unit-level exercise of resolve_selection()'s batch tier — request ->
# service -> platform precedence (mirroring backend's), resolved
# independently of the model/backend pairing rule (research D2), plus the
# refusal it populates when batch cannot be honoured (D2/D3). Uses a bare
# fake Request (just enough for require_platform's
# `request.app.state.platform` lookup) rather than the FastAPI TestClient,
# since the thing under test is the resolver function itself, not any route.


class _FakeAppState:
    def __init__(self, platform):
        self.platform = platform


class _FakeApp:
    def __init__(self, platform):
        self.state = _FakeAppState(platform)


class _FakeRequest:
    def __init__(self, platform):
        self.app = _FakeApp(platform)


def _svc(*, backend=None, model=None, batch=None):
    """A minimal stand-in for the duck-typed `service` tier, extended with
    `batch` (feature 005) alongside the pre-existing `backend`/`model`."""
    return SimpleNamespace(backend=backend, model=model, batch=batch)


# Backend-compatible models, used to isolate a batch refusal from the
# pre-existing model/backend refusal when parametrizing over backends.
_COMPATIBLE_MODEL = {
    "dgx": "Qwen-X",
    "openrouter": "anthropic/claude-sonnet-4",
    "claude-code": "claude-sonnet-4-6",
    "codex-cli": "gpt-5-codex",
}


@pytest.fixture
def no_wiring(monkeypatch):
    """dgx_endpoint resolution is irrelevant to these tests; keep it
    deterministic rather than depending on an ambient config/wiring.yaml."""
    monkeypatch.setattr(
        "server.platform_config_service.wiring_get", lambda key, default=None: default
    )


class TestBatchResolution:
    def _request(self, platform):
        return _FakeRequest(platform)

    def test_platform_default_batch_false_by_default(self, fresh_campaign, no_wiring):
        platform = PlatformConfigService(fresh_campaign)
        resolved = resolve_selection(self._request(platform))
        assert resolved.batch is False
        assert resolved.batch_origin == "platform"

    def test_platform_default_batch_true_flows_through(self, fresh_campaign, no_wiring):
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime({"default_batch": True})
        resolved = resolve_selection(self._request(platform))
        assert resolved.batch is True
        assert resolved.batch_origin == "platform"

    def test_service_batch_true_overrides_platform_false(self, fresh_campaign, no_wiring):
        platform = PlatformConfigService(fresh_campaign)
        resolved = resolve_selection(self._request(platform), service=_svc(batch=True))
        assert resolved.batch is True
        assert resolved.batch_origin == "service"

    def test_service_batch_false_is_sticky_against_platform_true(self, fresh_campaign, no_wiring):
        """`False` at the service tier is a genuine choice, not "unset" — it
        must NOT follow an app-wide change (data-model.md's tier table)."""
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime({"default_batch": True})
        resolved = resolve_selection(self._request(platform), service=_svc(batch=False))
        assert resolved.batch is False
        assert resolved.batch_origin == "service"

    def test_service_batch_none_defers_to_platform(self, fresh_campaign, no_wiring):
        """`None` (unset), unlike `False`, defers — the load-bearing
        distinction data-model.md calls out explicitly."""
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime({"default_batch": True})
        resolved = resolve_selection(self._request(platform), service=_svc(batch=None))
        assert resolved.batch is True
        assert resolved.batch_origin == "platform"

    def test_request_batch_wins_over_service_and_platform(self, fresh_campaign, no_wiring):
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime({"default_batch": True})
        resolved = resolve_selection(
            self._request(platform), service=_svc(batch=False), request_batch=True,
        )
        assert resolved.batch is True
        assert resolved.batch_origin == "request"

    def test_full_precedence_chain(self, fresh_campaign, no_wiring):
        """All three tiers in one scenario: request > service > platform."""
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime({"default_batch": True})

        # request wins over both
        r1 = resolve_selection(
            self._request(platform), service=_svc(batch=False), request_batch=True,
        )
        assert (r1.batch, r1.batch_origin) == (True, "request")

        # service wins over platform when no request value
        r2 = resolve_selection(self._request(platform), service=_svc(batch=False))
        assert (r2.batch, r2.batch_origin) == (False, "service")

        # platform wins when neither request nor service supplies one
        r3 = resolve_selection(self._request(platform), service=_svc(batch=None))
        assert (r3.batch, r3.batch_origin) == (True, "platform")

    def test_batch_does_not_extend_the_model_backend_pairing_rule(self, fresh_campaign, no_wiring):
        """D2: a service overriding only `batch` must not thereby be treated
        as though it also chose this tier's model/backend."""
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime({"default_model": "claude-opus-5", "default_backend": "anthropic"})
        resolved = resolve_selection(self._request(platform), service=_svc(batch=True))
        assert resolved.model_origin == "platform"
        assert resolved.backend_origin == "platform"
        assert resolved.batch is True
        assert resolved.batch_origin == "service"

    def test_batch_true_with_anthropic_is_compatible(self, fresh_campaign, no_wiring):
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime({"default_backend": "anthropic", "default_batch": True})
        resolved = resolve_selection(self._request(platform))
        assert resolved.batch is True
        assert resolved.compatible is True
        assert resolved.refusal is None

    @pytest.mark.parametrize("backend", ["dgx", "openrouter", "claude-code", "codex-cli"])
    def test_batch_true_with_non_anthropic_backend_refuses(self, fresh_campaign, no_wiring, backend):
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime({
            "default_backend": backend,
            "default_model": _COMPATIBLE_MODEL[backend],
            "default_batch": True,
        })
        resolved = resolve_selection(self._request(platform), raise_on_incompatible=False)
        assert resolved.compatible is False
        assert resolved.refusal is not None
        assert "batch" in resolved.refusal.lower()
        assert backend in resolved.refusal

    @pytest.mark.parametrize("backend", ["dgx", "openrouter", "claude-code", "codex-cli"])
    def test_batch_refusal_raises_when_raise_on_incompatible(self, fresh_campaign, no_wiring, backend):
        from fastapi import HTTPException

        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime({
            "default_backend": backend,
            "default_model": _COMPATIBLE_MODEL[backend],
            "default_batch": True,
        })
        with pytest.raises(HTTPException) as exc_info:
            resolve_selection(self._request(platform))
        assert exc_info.value.status_code == 409

    def test_batch_refusal_identical_for_service_vs_platform_origin(self, fresh_campaign, no_wiring):
        """D3: an inherited app-wide batch refuses exactly as a per-service
        one does — same message, regardless of which tier chose batch."""
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime({"default_backend": "dgx", "default_model": "Qwen-X"})

        platform.update_runtime({"default_batch": True})
        from_platform = resolve_selection(self._request(platform), raise_on_incompatible=False)

        platform.update_runtime({"default_batch": False})
        from_service = resolve_selection(
            self._request(platform), service=_svc(batch=True), raise_on_incompatible=False,
        )

        assert from_platform.compatible is False
        assert from_service.compatible is False
        assert from_platform.refusal == from_service.refusal
        assert from_platform.batch_origin == "platform"
        assert from_service.batch_origin == "service"

    def test_batch_false_never_refuses_regardless_of_backend(self, fresh_campaign, no_wiring):
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime({"default_backend": "dgx", "default_model": "Qwen-X"})
        resolved = resolve_selection(self._request(platform))
        assert resolved.batch is False
        assert resolved.compatible is True


class TestSelectionCliArgsBatchFlag:
    def _resolved(self, **overrides):
        base = dict(
            model="claude-sonnet-4-6", backend="anthropic",
            model_origin="platform", backend_origin="platform",
            batch=False, batch_origin="platform",
        )
        base.update(overrides)
        return ResolvedSelection(**base)

    def test_batch_true_emits_the_flag(self):
        args = selection_cli_args(self._resolved(batch=True))
        assert "--batch" in args

    def test_batch_false_omits_the_flag(self):
        args = selection_cli_args(self._resolved(batch=False))
        assert "--batch" not in args

    def test_batch_flag_comes_after_model(self):
        args = selection_cli_args(self._resolved(batch=True))
        assert args.index("--batch") > args.index("--model")

    # ── T028 backstop: selection_cli_args is unconditional on compatibility
    # ── — it emits --batch purely off `resolved.batch`, for EVERY compatible
    # ── batch-true selection, regardless of model/origin. The complementary
    # ── half of the invariant (no *router* ever reaches this function with a
    # ── batch-true-but-incompatible selection) is a property of
    # ── resolve_selection's raise-before-return, exercised below and by the
    # ── per-service "refuses and spawns nothing" tests in
    # ── tests/test_ui_batch_service_selection.py and
    # ── tests/test_ensemble_gates.py.

    @pytest.mark.parametrize("model,backend,origin", [
        ("claude-sonnet-4-6", "anthropic", "platform"),
        ("claude-opus-5", "anthropic", "service"),
        ("claude-haiku-4-5", "anthropic", "request"),
        ("", "anthropic", "platform"),  # no model chosen — batch still stands alone
    ])
    def test_batch_true_emits_the_flag_for_every_compatible_selection(self, model, backend, origin):
        resolved = self._resolved(
            model=model, backend=backend, model_origin=origin, batch=True,
        )
        assert resolved.compatible is True
        assert "--batch" in selection_cli_args(resolved)

    def test_batch_flag_is_not_gated_on_compatible_by_selection_cli_args_itself(self):
        """selection_cli_args has no compatibility check of its own — it is a
        pure renderer of `resolved.batch`. That is deliberate (one seam, one
        job — Constitution V): the refusal gate lives entirely in
        resolve_selection, which must never hand a router an incompatible,
        batch-true ResolvedSelection to render in the first place. This test
        documents why the *router* side of the invariant (covered elsewhere)
        is the one that actually matters."""
        incompatible_but_batch_true = self._resolved(
            backend="dgx", model="Qwen-X", batch=True, refusal="batch is a Claude API option; …",
        )
        assert incompatible_but_batch_true.compatible is False
        # selection_cli_args itself would still render --batch here — proving
        # the backstop is resolve_selection's raise, not a second check here.
        assert "--batch" in selection_cli_args(incompatible_but_batch_true)


class TestNoRouteBuildsFromIncompatibleBatchSelection:
    """T028's other half: resolve_selection's raise is unconditional — no
    caller can reach selection_cli_args (and therefore no router can build a
    command) with a batch-true-but-incompatible selection, for EITHER
    refusal cause (non-anthropic backend, or a service whose static batch
    capability is "incompatible" — the latter has no UI-reachable service
    today per BATCH_CAPABILITY's own comment, but the branch is real code and
    gets covered here rather than only by services that happen to occupy
    "full"/"degraded")."""

    def _request(self, platform=None):
        return _FakeRequest(platform)

    @pytest.mark.parametrize("backend", ["dgx", "openrouter", "claude-code", "codex-cli"])
    def test_non_anthropic_backend_raises_before_any_args_could_be_built(self, backend):
        # A backend-compatible model, so the refusal isolates the batch cause
        # from the pre-existing model/backend refusal (mirrors
        # TestBatchResolution's _COMPATIBLE_MODEL above).
        with pytest.raises(IncompatibleSelection) as exc_info:
            resolve_selection(
                self._request(),
                service=_svc(backend=backend, model=_COMPATIBLE_MODEL[backend], batch=True),
            )
        assert "batch" in exc_info.value.resolved.refusal

    def test_service_incompatible_batch_capability_raises_before_any_args_could_be_built(self, monkeypatch):
        monkeypatch.setattr(
            "server.platform_config_service.BATCH_CAPABILITY",
            {"no_batch_service": "incompatible"},
        )
        with pytest.raises(IncompatibleSelection) as exc_info:
            resolve_selection(
                self._request(),
                service=_svc(batch=True),
                service_name="no_batch_service",
            )
        assert "batch" in exc_info.value.resolved.refusal
        assert "no_batch_service" in exc_info.value.resolved.refusal

    def test_preview_path_never_builds_args_either(self):
        """The one legitimate way to get a batch-true-but-incompatible
        ResolvedSelection back from resolve_selection at all is the preview
        path (`raise_on_incompatible=False`) — and preview routes only ever
        call `.as_dict()` on the result, never `selection_cli_args`. This
        documents that contract at the unit level rather than only at the
        per-router integration level."""
        resolved = resolve_selection(
            self._request(),
            service=_svc(backend="dgx", model="Qwen-X", batch=True),
            raise_on_incompatible=False,
        )
        assert resolved.compatible is False
        # A preview route calls .as_dict() — never selection_cli_args. This
        # assertion is the contract, not an exercise of it: grep guardrails
        # (tests/test_backend_seam_guardrails.py) and the per-service
        # "refuses and spawns nothing" tests are what actually enforce that
        # no router does the wrong thing here.
        assert set(resolved.as_dict()) == {
            "model", "backend", "model_origin", "backend_origin",
            "batch", "batch_origin",
            "codex_reasoning_effort", "codex_reasoning_effort_origin",
            "codex_reasoning_override",
            # 021 — the claude-code twin of the three Codex keys above.
            "claude_code_effort", "claude_code_effort_origin",
            "claude_code_effort_override",
            "compatible", "refusal",
        }


# ── Codex model provenance (feature 016, T040) ─────────────────────────────


def test_request_model_origin_is_preserved_for_codex():
    resolved = resolve_selection(
        _FakeRequest(None),
        request_backend="codex-cli",
        request_model="gpt-5-codex",
    )

    assert resolved.backend == "codex-cli"
    assert resolved.model == "gpt-5-codex"
    assert resolved.model_origin == "request"
    assert resolved.backend_origin == "request"


def test_service_model_origin_is_preserved_for_codex():
    resolved = resolve_selection(
        _FakeRequest(None),
        service=_svc(backend="codex-cli", model="gpt-5-codex"),
    )

    assert resolved.backend == "codex-cli"
    assert resolved.model == "gpt-5-codex"
    assert resolved.model_origin == "service"
    assert resolved.backend_origin == "service"


def test_platform_model_origin_is_preserved_for_codex(fresh_campaign):
    platform = PlatformConfigService(fresh_campaign)
    platform.update_runtime({
        "default_backend": "anthropic",
        "default_model": "claude-platform-sentinel",
    })
    resolved = resolve_selection(
        _FakeRequest(platform),
        request_backend="anthropic",
    )

    assert resolved.model == "claude-platform-sentinel"
    assert resolved.model_origin == "platform"


def test_literal_model_origin_is_distinct_from_platform(monkeypatch):
    monkeypatch.setattr(
        "server.platform_config_service.DEFAULT_MODEL", "claude-literal-sentinel"
    )
    resolved = resolve_selection(_FakeRequest(None))

    assert resolved.model == "claude-literal-sentinel"
    assert resolved.model_origin == "literal"


@pytest.mark.parametrize("backend_origin", ["request", "service", "platform"])
def test_inherited_claude_model_is_omitted_for_codex(
    fresh_campaign, backend_origin
):
    platform = PlatformConfigService(fresh_campaign)
    platform.update_runtime({
        "default_backend": "anthropic",
        "default_model": "claude-inherited-sentinel",
    })
    kwargs = {"request_backend": "codex-cli"} if backend_origin == "request" else {}
    service = _svc(backend="codex-cli") if backend_origin == "service" else None
    if backend_origin == "platform":
        platform.update_runtime({"default_backend": "codex-cli"})

    resolved = resolve_selection(
        _FakeRequest(platform),
        service=service,
        **kwargs,
        raise_on_incompatible=False,
    )

    assert resolved.backend == "codex-cli"
    assert resolved.model is None
    assert resolved.model_origin == "platform"
    assert resolved.compatible is True
    assert resolved.refusal is None


def test_explicit_codex_model_is_forwarded_by_selection_cli_args():
    resolved = resolve_selection(
        _FakeRequest(None),
        request_backend="codex-cli",
        request_model="gpt-5-codex",
    )

    assert selection_cli_args(resolved) == [
        "--backend", "codex-cli", "--model", "gpt-5-codex"
    ]


def test_explicit_claude_model_for_codex_is_refused():
    with pytest.raises(IncompatibleSelection) as exc_info:
        resolve_selection(
            _FakeRequest(None),
            request_backend="codex-cli",
            request_model="claude-opus-4-6",
        )

    refusal = exc_info.value.resolved
    assert refusal.model == "claude-opus-4-6"
    assert refusal.model_origin == "request"
    assert refusal.compatible is False
    assert "codex-cli" in refusal.refusal
