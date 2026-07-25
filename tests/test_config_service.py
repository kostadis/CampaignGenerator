"""Tests for server/config_service.py — the residual UIStateService.

The hard invariants this file freezes:

  - ``config.yaml`` is never opened for write.
  - Path resolution is uniform: relative → absolute against campaign_dir;
    absolute and ``~`` paths pass through.
  - Boot overrides are in-memory only; a second instance does not see them.
  - Atomic writes: a crash between ``tmp.write`` and ``os.replace`` leaves
    the original file untouched.
  - Concurrent updates serialize on the section lock.
  - A `--session-dir` boot override rebases stale absolute paths persisted
    under the prior session dir.

Per docs/config/platform-isolation.md Phase 2, the old ``CampaignConfigService``
is split into ``PlatformConfigService`` (path resolution, ``config.yaml``,
``.campaigngenerator.local.yaml``, boot overrides) and ``UIStateService``
(the residual ``ui.<section>`` blobs, this module). These tests construct
the ``PlatformConfigService`` — the only public entry point now — and reach
the residual service through ``platform.uis`` wherever a test exercises
``update_section``/``ui_state`` directly; everything else (``resolve_path``,
``resolved()``, ``update_runtime``) is called straight on the platform
instance, since those either live there now or are thin passthroughs to
``uis``. Local-file and load-warnings coverage lives in
``tests/test_platform_config_service.py``.

Phase 3 of the same doc (O3) relocates ``runtime`` out of ``ui_state.yaml``
entirely, into its own ``<config>/platform.yaml`` that
``PlatformConfigService`` owns outright — ``UIState`` no longer has a
``runtime`` field at all, so ``svc.uis.ui_state.runtime`` no longer exists;
read it via ``svc.runtime`` instead. ``update_runtime``'s persisted-storage
coverage (what file it writes, that it merges rather than replaces) moved to
``tests/test_platform_config_service.py`` alongside the rest of Phase 3's
runtime-ownership tests; what stays here is ``update_runtime``'s effect on
THIS module's own concerns — session-scoped path resolution/relativization
and the sibling-session rebase in ``resolved()`` — via calls to
``svc.update_runtime(...)`` used purely to set up scenario state.

Session-editor config isolation (Phase 5,
docs/config/session-editor-isolation.md): ``session_doc`` is no longer a UI
section at all — that data lives in the Session Doc Editor's own
``<config>/session_doc.yaml`` now (see
``tests/test_session_editor_config_service.py``). These generic
mechanism tests, which used to exercise ``session_doc`` purely as a
convenient stand-in typed section, then moved to ``vtt_summary``.

Retiring the vtt_summary chain took the LAST session-scoped ``ui.<section>``
path field with it: ``_PATH_FIELDS`` is now ``{"query": {"summaries":
"campaign"}}``. The session base itself is still live machinery — the
Session Doc Editor resolves every path in its own ``session_doc.yaml``
through ``PlatformConfigService``'s ``base="session"`` branch — so the
session-scoped tests below keep it covered via the ``session_scoped_field``
fixture, which registers synthetic fields for the duration of a test rather
than leaning on a production section. ``ui.query`` is the stand-in section
throughout — it is a surviving loose section with no semantics of its own,
which is exactly what a generic section-machinery test wants.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import config_service as config_service_module
from server.config_service import ConfigError, UI_STATE_NAME
from server.platform_config_service import PlatformConfigService, TRACKED_CONFIG_NAME

# Field names registered by the ``session_scoped_field`` fixture. They live
# on ``ui.query`` (``extra="allow"``, so the model accepts them) purely
# as vehicles for exercising the ``base="session"`` code path. Three of them
# because the rebase tests below assert that a whole section's worth of
# session-scoped fields moves together.
PROBE_DIR = "probe_dir"
PROBE_OUT = "probe_out"
PROBE_FILE = "probe_file"
SESSION_PROBES = (PROBE_DIR, PROBE_OUT, PROBE_FILE)

# ...and one campaign-scoped probe. Campaign coverage used to ride on the real
# ``grounding.summaries``; Phase 10 of the grounding isolation moved that to
# <config>/grounding.yaml, emptying _PATH_FIELDS entirely. Both bases are now
# exercised through synthetic fields, which is the more honest arrangement:
# these are tests of the resolution machinery, not of any production section.
PROBE_CAMPAIGN = "probe_campaign"

# The service reads/writes its documents under <campaign>/<config_dir>/;
# config_dir defaults to "config". Tests build on-disk paths against this same
# subdir so fixtures land where the service looks.
CONFIG_SUBDIR = "config"


# ── Fixtures ──────────────────────────────────────────────────────────────


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.fixture(autouse=True)
def session_scoped_field(monkeypatch):
    """Register synthetic session-scoped ``ui.query`` path fields.

    No production ``ui.<section>`` field is session-scoped since the
    ``vtt_summary`` retirement, but ``PlatformConfigService``'s
    ``base="session"`` resolution/relativization/rebase machinery is still
    live (the Session Doc Editor's ``session_doc.yaml`` runs through it).
    Autouse so the section-scan loops in ``resolved()`` and
    ``_normalize_stored_paths`` see the same table the tests write against.
    """
    patched = {
        section: dict(fields)
        for section, fields in config_service_module._PATH_FIELDS.items()
    }
    section = patched.setdefault("query", {})
    for probe in SESSION_PROBES:
        section[probe] = "session"
    section[PROBE_CAMPAIGN] = "campaign"
    monkeypatch.setattr(config_service_module, "_PATH_FIELDS", patched)
    return SESSION_PROBES


@pytest.fixture
def fresh_campaign(tmp_path):
    """A campaign dir with only ``config.yaml``."""
    cfg = tmp_path / CONFIG_SUBDIR / TRACKED_CONFIG_NAME
    _write(
        cfg,
        "# hand-written, do not touch\ndocuments:\n  - label: world_state\n    path: docs/world_state.md\n",
    )
    return tmp_path


# ── Construction ──────────────────────────────────────────────────────────


class TestConstruction:
    def test_missing_campaign_dir_raises(self, tmp_path):
        with pytest.raises(ConfigError, match="does not exist"):
            PlatformConfigService(tmp_path / "nope")

    def test_missing_config_yaml_raises(self, tmp_path):
        # Empty dir, no config.yaml.
        with pytest.raises(ConfigError, match="no config.yaml"):
            PlatformConfigService(tmp_path)

    def test_invalid_config_yaml_raises(self, tmp_path):
        _write(tmp_path / CONFIG_SUBDIR / TRACKED_CONFIG_NAME, "key: : :")
        with pytest.raises(ConfigError, match="not valid YAML"):
            PlatformConfigService(tmp_path)

    def test_invalid_ui_state_yaml_raises(self, tmp_path):
        _write(tmp_path / CONFIG_SUBDIR / TRACKED_CONFIG_NAME, "documents: []\n")
        _write(tmp_path / CONFIG_SUBDIR / UI_STATE_NAME, "version: 2\nui: : :")
        with pytest.raises(ConfigError, match="ui_state.yaml is not valid YAML"):
            PlatformConfigService(tmp_path)

    # Local-file (.campaigngenerator.local.yaml) construction behavior —
    # including the warn-and-drop-on-bad-YAML case — moved to
    # tests/test_platform_config_service.py alongside the rest of Platform's
    # own coverage; UIStateService no longer touches that file at all.


# ── config.yaml read-only invariant ──────────────────────────────────────


class TestConfigYamlNeverWritten:
    def test_config_yaml_unchanged_after_updates(self, fresh_campaign):
        original = (fresh_campaign / CONFIG_SUBDIR / TRACKED_CONFIG_NAME).read_bytes()
        svc = PlatformConfigService(fresh_campaign)
        svc.uis.update_section("query", {"label": "Session 12"})
        svc.update_local({"server": {"port": 6001}})
        assert (fresh_campaign / CONFIG_SUBDIR / TRACKED_CONFIG_NAME).read_bytes() == original

    def test_service_module_has_no_config_yaml_writer(self):
        """Source-level guard: no function in config_service.py opens
        config.yaml for writing. The strongest enforcement of the
        'human-only' contract.

        Since Phase 2 (docs/config/platform-isolation.md), UIStateService
        (this module) doesn't even hold config.yaml's path any more — that
        moved to PlatformConfigService, along with the ``TRACKED_CONFIG_
        NAME`` constant and the ``config_path`` property it named. This
        module only reaches ``config_path_base`` (the shared directory,
        via ``self.platform``) to build ``ui_state_path`` — never the
        tracked-config-specific path itself.
        """
        src = Path(__file__).resolve().parent.parent / "server" / "config_service.py"
        text = src.read_text(encoding="utf-8")
        assert "_persist_ui_state" in text
        assert "TRACKED_CONFIG_NAME" not in text
        assert "def config_path(" not in text
        assert ".config_path.write" not in text

    def test_platform_module_has_no_config_yaml_writer(self):
        """Same guard, mirrored onto PlatformConfigService: it holds
        ``config_path``/``tracked`` for reading, but must never write
        through them."""
        src = (
            Path(__file__).resolve().parent.parent
            / "server"
            / "platform_config_service.py"
        )
        text = src.read_text(encoding="utf-8")
        assert "_load_tracked" in text
        assert ".config_path.write" not in text
        assert "config_path.write_text" not in text


# ── Path resolution ──────────────────────────────────────────────────────


class TestPathResolution:
    def test_relative_resolves_against_campaign_dir(self, fresh_campaign):
        svc = PlatformConfigService(fresh_campaign)
        resolved = svc.resolve_path("docs/world_state.md")
        assert resolved == str((fresh_campaign / "docs" / "world_state.md").resolve())

    def test_absolute_passes_through(self, fresh_campaign, tmp_path):
        svc = PlatformConfigService(fresh_campaign)
        resolved = svc.resolve_path(str(tmp_path / "elsewhere"))
        assert resolved == str((tmp_path / "elsewhere").resolve())

    def test_tilde_expands(self, fresh_campaign):
        svc = PlatformConfigService(fresh_campaign)
        resolved = svc.resolve_path("~/file.md")
        assert resolved == str(Path.home() / "file.md")

    def test_empty_becomes_none(self, fresh_campaign):
        svc = PlatformConfigService(fresh_campaign)
        assert svc.resolve_path("") is None
        assert svc.resolve_path("   ") is None
        assert svc.resolve_path(None) is None


# ── Boot overrides ───────────────────────────────────────────────────────


class TestBootOverrides:
    def test_boot_override_visible_in_resolved(self, fresh_campaign):
        svc = PlatformConfigService(
            fresh_campaign,
            boot_overrides={"query.label": "Boot Session"},
        )
        resolved = svc.resolved()
        assert resolved["ui"]["query"]["label"] == "Boot Session"

    def test_boot_override_does_not_persist(self, fresh_campaign):
        # First instance with override.
        PlatformConfigService(
            fresh_campaign,
            boot_overrides={"query.label": "Boot Session"},
        )
        # Second instance with no override sees the file's value (default).
        second = PlatformConfigService(fresh_campaign)
        resolved = second.resolved()
        # `label` is an extra key, absent until something writes it.
        assert "label" not in resolved["ui"]["query"]

    def test_runtime_dotted_override_lands_in_runtime(self, fresh_campaign):
        svc = PlatformConfigService(
            fresh_campaign,
            boot_overrides={"runtime.session_dir": "/tmp/x"},
        )
        resolved = svc.resolved()
        assert resolved["runtime"]["session_dir"] == "/tmp/x"


# ── Fresh-campaign defaults ──────────────────────────────────────────────


class TestFreshCampaign:
    def test_no_ui_state_starts_with_defaults(self, fresh_campaign):
        svc = PlatformConfigService(fresh_campaign)
        assert svc.load_warnings == []
        # Defaults applied from the schema. `ui.grounding` and the other four
        # grounding sections left for <config>/grounding.yaml in Phase 10 of
        # docs/config/grounding-isolation.md, so the stand-in section here is
        # `query` — a surviving loose section.
        assert svc.uis.ui_state.ui.query.model_dump() == {}

    def test_old_ui_state_with_stale_session_doc_loads_fine(self, fresh_campaign):
        # A pre-Phase-5 ui_state.yaml still carrying a ui.session_doc /
        # ui.profiles block (nobody has run the manual data lift yet, or
        # the one-shot server/migrate_session_doc.py CLI). UISection's
        # default extra="ignore" means construction must NOT fail — the
        # stale block is just dropped; SessionEditorConfigService reads
        # its own session_doc.yaml instead.
        (fresh_campaign / CONFIG_SUBDIR / UI_STATE_NAME).write_text(
            "version: 2\nui:\n  session_doc:\n    narrate_tokens: 4000\n"
            "    prose_mode: null\n"
            "  profiles:\n    profiles: []\n    active: null\n",
            encoding="utf-8",
        )
        svc = PlatformConfigService(fresh_campaign)
        assert svc.load_warnings == []
        assert "session_doc" not in svc.resolved()["ui"]
        assert "profiles" not in svc.resolved()["ui"]


# ── update_section ──────────────────────────────────────────────────────
# update_local moved to PlatformConfigService — see
# tests/test_platform_config_service.py.


class TestUpdateSection:
    def test_update_section_persists(self, fresh_campaign):
        svc = PlatformConfigService(fresh_campaign)
        svc.uis.update_section("query", {"label": "Session 12"})

        # Re-read from disk.
        on_disk = yaml.safe_load((fresh_campaign / CONFIG_SUBDIR / UI_STATE_NAME).read_text())
        assert on_disk["ui"]["query"]["label"] == "Session 12"

    def test_update_section_merges_not_replaces(self, fresh_campaign):
        svc = PlatformConfigService(fresh_campaign)
        svc.uis.update_section("query", {"label": "Session 12"})
        svc.uis.update_section("query", {"note": "n"})
        # Both fields present after the second call.
        assert svc.uis.ui_state.ui.query.label == "Session 12"
        assert svc.uis.ui_state.ui.query.note == "n"

    def test_unknown_section_rejected(self, fresh_campaign):
        svc = PlatformConfigService(fresh_campaign)
        with pytest.raises(ValueError, match="unknown UI section"):
            svc.uis.update_section("server", {"port": 6001})

    def test_session_doc_section_rejected(self, fresh_campaign):
        # Phase 5: session_doc left ui_state.yaml entirely, so it's no
        # longer among UI_SECTION_NAMES.
        svc = PlatformConfigService(fresh_campaign)
        with pytest.raises(ValueError, match="unknown UI section"):
            svc.uis.update_section("session_doc", {"narrate_tokens": 12000})


# ── Atomic writes & concurrency ──────────────────────────────────────────


class TestAtomicWrites:
    def test_replace_failure_leaves_existing_file_intact(
        self, fresh_campaign, monkeypatch
    ):
        svc = PlatformConfigService(fresh_campaign)
        svc.uis.update_section("query", {"label": "11111"})
        before = (fresh_campaign / CONFIG_SUBDIR / UI_STATE_NAME).read_bytes()

        original_replace = os.replace

        def boom(*args, **kwargs):
            raise OSError("simulated mid-write crash")

        monkeypatch.setattr(os, "replace", boom)

        with pytest.raises(OSError, match="simulated"):
            svc.uis.update_section("query", {"label": "22222"})

        # Original file unchanged.
        assert (fresh_campaign / CONFIG_SUBDIR / UI_STATE_NAME).read_bytes() == before

        # Restore so cleanup works.
        monkeypatch.setattr(os, "replace", original_replace)

    def test_concurrent_writes_to_same_section_no_torn_file(self, fresh_campaign):
        svc = PlatformConfigService(fresh_campaign)
        errors: list[BaseException] = []

        def writer(value: int) -> None:
            try:
                svc.uis.update_section("query", {"label": str(value)})
            except BaseException as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(v,)) for v in range(100, 200)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        # File is parseable (no torn YAML) — that's the actual invariant.
        on_disk = yaml.safe_load((fresh_campaign / CONFIG_SUBDIR / UI_STATE_NAME).read_text())
        assert isinstance(on_disk, dict)
        # Whatever the last writer was, it's a valid value from our range.
        assert 100 <= int(on_disk["ui"]["query"]["label"]) < 200


# ── Resolved view ────────────────────────────────────────────────────────


class TestResolvedView:
    def test_campaign_relative_path_resolves_against_campaign_dir(
        self, fresh_campaign
    ):
        # PROBE_CAMPAIGN is registered campaign-scoped by session_scoped_field.
        svc = PlatformConfigService(fresh_campaign)
        svc.uis.update_section("query", {PROBE_CAMPAIGN: "summaries.md"})
        resolved = svc.resolved()
        summaries = resolved["ui"]["query"][PROBE_CAMPAIGN]
        assert Path(summaries).is_absolute()
        assert summaries == str((fresh_campaign / "summaries.md").resolve())

    def test_session_relative_path_resolves_against_session_dir(
        self, fresh_campaign
    ):
        # The user-reported bug: a relative `session_summary` was landing
        # in the campaign root instead of the session dir.
        svc = PlatformConfigService(fresh_campaign)
        svc.uis.update_section(
            "query", {PROBE_FILE: "session-summary.md", PROBE_CAMPAIGN: "summaries.md"}
        )
        # Without a session_dir set, the legacy fallback to campaign_dir
        # still applies.
        no_sd = svc.resolved()
        assert no_sd["ui"]["query"][PROBE_FILE] == \
            str((fresh_campaign / "session-summary.md").resolve())

        # With session_dir set, session-scoped paths resolve there.
        svc2 = PlatformConfigService(
            fresh_campaign,
            boot_overrides={"runtime.session_dir": "summaries/sess1"},
        )
        svc2.uis.update_section(
            "query", {PROBE_FILE: "session-summary.md", PROBE_CAMPAIGN: "summaries.md"}
        )
        with_sd = svc2.resolved()
        # session-scoped → resolves against session_dir
        assert with_sd["ui"]["query"][PROBE_FILE] == str(
            (fresh_campaign / "summaries" / "sess1" / "session-summary.md").resolve()
        )
        # campaign-scoped → still campaign root, even with session_dir set
        assert with_sd["ui"]["query"][PROBE_CAMPAIGN] == str(
            (fresh_campaign / "summaries.md").resolve()
        )

    def test_absolute_path_overrides_base(self, fresh_campaign, tmp_path):
        # Absolute paths pass through regardless of base hint.
        elsewhere = tmp_path / "elsewhere" / "file.md"
        svc = PlatformConfigService(fresh_campaign)
        svc.uis.update_section("query", {PROBE_FILE: str(elsewhere)})
        resolved = svc.resolved()
        assert resolved["ui"]["query"][PROBE_FILE] == \
            str(elsewhere.resolve())

    def test_non_path_fields_pass_through(self, fresh_campaign):
        svc = PlatformConfigService(fresh_campaign)
        svc.uis.update_section(
            "query", {"date": "2026-07-01", "label": "Session 12"}
        )
        resolved = svc.resolved()
        assert resolved["ui"]["query"]["date"] == "2026-07-01"
        assert resolved["ui"]["query"]["label"] == "Session 12"

    def test_resolved_includes_campaign_dir(self, fresh_campaign):
        svc = PlatformConfigService(fresh_campaign)
        resolved = svc.resolved()
        assert resolved["campaign_dir"] == str(fresh_campaign.resolve())

    def test_boot_session_dir_rebases_stale_absolute_paths(self, fresh_campaign):
        """The user-reported bug: ``ui_state.yaml`` had session-scoped fields
        persisted as absolute paths under the previous session dir. Booting
        with ``--session-dir`` overrode ``runtime.session_dir`` but the
        absolute paths in the section's session-scoped fields passed through
        unchanged. The
        rebase pass in ``resolved()`` is the fix."""
        old_sd = fresh_campaign / "summaries" / "20260505"
        new_sd = fresh_campaign / "summaries" / "20260512"
        for d in (old_sd, new_sd):
            d.mkdir(parents=True)

        # Persist the stale state — these are what the previous session left
        # behind in ui_state.yaml.
        svc_init = PlatformConfigService(fresh_campaign)
        svc_init.uis.update_section(
            "query",
            {
                PROBE_DIR: str(old_sd / "scene_extractions_new"),
                PROBE_OUT: str(old_sd / "narration"),
                PROBE_FILE: str(old_sd / "session-summary.md"),
                # campaign-scoped — must NOT rebase
                "summaries": str(fresh_campaign / "summaries.md"),
            },
        )
        svc_init.update_runtime({"session_dir": str(old_sd)})

        # New launch with --session-dir 20260512.
        svc = PlatformConfigService(
            fresh_campaign,
            boot_overrides={"runtime.session_dir": str(new_sd)},
        )
        r = svc.resolved()

        assert r["runtime"]["session_dir"] == str(new_sd.resolve())
        assert r["ui"]["query"][PROBE_DIR] == str(
            (new_sd / "scene_extractions_new").resolve()
        )
        assert r["ui"]["query"][PROBE_OUT] == str(
            (new_sd / "narration").resolve()
        )
        assert r["ui"]["query"][PROBE_FILE] == str(
            (new_sd / "session-summary.md").resolve()
        )
        # Campaign-scoped path stays put.
        assert r["ui"]["query"]["summaries"] == str(
            (fresh_campaign / "summaries.md").resolve()
        )

    def test_rebase_handles_persisted_paths_under_unrelated_session(
        self, fresh_campaign
    ):
        """The Phandalin failure mode: persisted runtime.session_dir was
        ``summaries/20260429`` but the session-scoped fields were under
        ``summaries/20260505`` (different historical save). The rebase pass
        must key off the path PATTERN, not the persisted runtime value."""
        for d in (
            fresh_campaign / "summaries" / "20260429",
            fresh_campaign / "summaries" / "20260505",
            fresh_campaign / "summaries" / "20260512",
        ):
            d.mkdir(parents=True)
        wrong_sd = fresh_campaign / "summaries" / "20260505"
        stale_runtime_sd = fresh_campaign / "summaries" / "20260429"
        new_sd = fresh_campaign / "summaries" / "20260512"

        svc_init = PlatformConfigService(fresh_campaign)
        svc_init.uis.update_section(
            "query",
            {PROBE_OUT: str(wrong_sd / "narration")},
        )
        svc_init.update_runtime({"session_dir": str(stale_runtime_sd)})

        svc = PlatformConfigService(
            fresh_campaign,
            boot_overrides={"runtime.session_dir": str(new_sd)},
        )
        r = svc.resolved()
        assert r["ui"]["query"][PROBE_OUT] == str(
            (new_sd / "narration").resolve()
        )

    def test_rebase_only_runs_when_boot_overrides_session_dir(
        self, fresh_campaign
    ):
        """Without a --session-dir CLI flag, persisted absolute paths must pass
        through unchanged — even if ``runtime.session_dir`` happens to point
        somewhere else. The rebase is a fix-the-stale-data behavior gated on
        an explicit boot override."""
        old_sd = fresh_campaign / "summaries" / "20260505"
        runtime_sd = fresh_campaign / "summaries" / "20260512"
        for d in (old_sd, runtime_sd):
            d.mkdir(parents=True)

        svc_init = PlatformConfigService(fresh_campaign)
        svc_init.uis.update_section(
            "query", {PROBE_OUT: str(old_sd / "narration")}
        )
        svc_init.update_runtime({"session_dir": str(runtime_sd)})

        # No boot override.
        svc = PlatformConfigService(fresh_campaign)
        r = svc.resolved()
        assert r["ui"]["query"][PROBE_OUT] == str(
            (old_sd / "narration").resolve()
        )

    def test_explicit_boot_override_wins_over_rebase(self, fresh_campaign):
        """If the CLI passes both --session-dir AND an explicit override for a
        session-scoped field, the explicit one must win."""
        old_sd = fresh_campaign / "summaries" / "old"
        new_sd = fresh_campaign / "summaries" / "new"
        custom = fresh_campaign / "custom" / "narration"
        for d in (old_sd, new_sd, custom):
            d.mkdir(parents=True)

        svc_init = PlatformConfigService(fresh_campaign)
        svc_init.uis.update_section(
            "query", {PROBE_OUT: str(old_sd / "narration")}
        )
        svc_init.update_runtime({"session_dir": str(old_sd)})

        svc = PlatformConfigService(
            fresh_campaign,
            boot_overrides={
                "runtime.session_dir": str(new_sd),
                f"query.{PROBE_OUT}": str(custom),
            },
        )
        r = svc.resolved()
        assert r["ui"]["query"][PROBE_OUT] == str(custom.resolve())


# ── update_runtime ────────────────────────────────────────────────────────
# Persisted-storage coverage (what file it writes, that it merges rather
# than replaces) moved to tests/test_platform_config_service.py's
# TestRuntimeOwnership, alongside Phase 3's other runtime-ownership tests —
# ``svc.uis.ui_state.runtime`` no longer exists at all (UIState dropped the
# field), so this module's own use of update_runtime is confined to setup
# calls inside the resolved()/rebase scenarios above.


# ── Write-time relativization (issue #120 split-brain fix) ─────────────────
#
# The bug: session-scoped path fields were persisted as absolute (baked to
# whatever session_dir was active at write time), so an absolute value never
# re-tracked a later session_dir change — only relative values did. The fix
# is a write-time choke point (`relativize_path`, wired into `update_section`)
# that collapses absolute-but-under-base values back to relative storage
# regardless of what the caller sent.


class TestRelativizeOnWrite:
    def test_update_section_relativizes_absolute_session_path(self, fresh_campaign):
        session_dir = fresh_campaign / "summaries" / "sess1"
        session_dir.mkdir(parents=True)
        svc = PlatformConfigService(fresh_campaign)
        svc.update_runtime({"session_dir": str(session_dir)})
        svc.uis.update_section(
            "query",
            {PROBE_DIR: str(session_dir / "scene_extractions")},
        )
        # Raw stored value is relative, even though an absolute path was sent.
        assert getattr(svc.uis.ui_state.ui.query, PROBE_DIR) == "scene_extractions"
        # resolved() still reports it absolute, anchored under the session dir.
        resolved = svc.resolved()
        assert resolved["ui"]["query"][PROBE_DIR] == str(
            (session_dir / "scene_extractions").resolve()
        )

    def test_update_section_leaves_out_of_tree_absolute(self, fresh_campaign):
        session_dir = fresh_campaign / "summaries" / "sess1"
        session_dir.mkdir(parents=True)
        svc = PlatformConfigService(fresh_campaign)
        svc.update_runtime({"session_dir": str(session_dir)})
        svc.uis.update_section(
            "query", {PROBE_DIR: "/totally/other/place"}
        )
        # A genuine out-of-tree override has no relative form — stored as-is.
        assert (
            getattr(svc.uis.ui_state.ui.query, PROBE_DIR)
            == "/totally/other/place"
        )

    def test_session_path_retracks_after_session_dir_change(self, fresh_campaign):
        session_a = fresh_campaign / "summaries" / "sessA"
        session_b = fresh_campaign / "summaries" / "sessB"
        session_a.mkdir(parents=True)
        session_b.mkdir(parents=True)

        svc = PlatformConfigService(fresh_campaign)
        svc.uis.update_section(
            "query", {PROBE_DIR: "scene_extractions"}
        )
        svc.update_runtime({"session_dir": str(session_a)})
        resolved_a = svc.resolved()
        assert resolved_a["ui"]["query"][PROBE_DIR] == str(
            (session_a / "scene_extractions").resolve()
        )

        # Switching session_dir alone must retrack the relative value — the
        # exact behavior that broke when the value was stored absolute.
        svc.update_runtime({"session_dir": str(session_b)})
        resolved_b = svc.resolved()
        assert resolved_b["ui"]["query"][PROBE_DIR] == str(
            (session_b / "scene_extractions").resolve()
        )
