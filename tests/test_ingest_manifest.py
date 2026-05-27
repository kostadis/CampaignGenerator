"""Tests for ``apply_ingest_manifest.py``.

The manifest replayer is a thin orchestrator over ``fivetools_ingest.py``,
so the tests focus on the parts the orchestrator owns:

* manifest loading and validation,
* palace resolution precedence (CLI > manifest > config.yaml),
* status reporting (never-run / ingested / stale / missing-source),
* argv construction (so a regression in flag-mapping is caught without
  spawning a real ingest subprocess),
* ``--only`` index selection.

We never spawn ``fivetools_ingest.py`` from these tests; the integration
between the two scripts is exercised in CI by running the manifest itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import apply_ingest_manifest as aim
import fivetools_ingest as fti


# ── Manifest loading ─────────────────────────────────────────────────────


def _write_manifest(dir_: Path, body: dict | str) -> Path:
    p = dir_ / aim.MANIFEST_FILENAME
    if isinstance(body, str):
        p.write_text(body, encoding="utf-8")
    else:
        p.write_text(yaml.safe_dump(body), encoding="utf-8")
    return p


class TestLoadManifest:
    def test_valid_minimal(self, tmp_path: Path):
        p = _write_manifest(tmp_path, {"ingests": [{"source": "a.json"}]})
        m = aim.load_manifest(p)
        assert m["ingests"] == [{"source": "a.json"}]

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(SystemExit, match="not found"):
            aim.load_manifest(tmp_path / "missing.yaml")

    def test_empty_yaml_raises(self, tmp_path: Path):
        p = _write_manifest(tmp_path, "")
        with pytest.raises(SystemExit, match="is empty"):
            aim.load_manifest(p)

    def test_top_level_not_mapping_raises(self, tmp_path: Path):
        p = _write_manifest(tmp_path, "- just a list\n")
        with pytest.raises(SystemExit, match="top level must be a mapping"):
            aim.load_manifest(p)

    def test_missing_ingests_raises(self, tmp_path: Path):
        p = _write_manifest(tmp_path, {"palace": "abyss"})
        with pytest.raises(SystemExit, match="missing or empty 'ingests:'"):
            aim.load_manifest(p)

    def test_empty_ingests_raises(self, tmp_path: Path):
        p = _write_manifest(tmp_path, {"ingests": []})
        with pytest.raises(SystemExit, match="missing or empty 'ingests:'"):
            aim.load_manifest(p)

    def test_entry_without_source_raises(self, tmp_path: Path):
        p = _write_manifest(tmp_path, {"ingests": [{"note": "oops"}]})
        with pytest.raises(SystemExit, match="missing 'source'"):
            aim.load_manifest(p)

    def test_entry_not_mapping_raises(self, tmp_path: Path):
        p = _write_manifest(tmp_path, {"ingests": ["raw-string"]})
        with pytest.raises(SystemExit, match=r"\[1\] must be a mapping"):
            aim.load_manifest(p)


# ── Palace resolution ────────────────────────────────────────────────────


class TestResolvePalace:
    def test_cli_beats_everything(self):
        manifest = {"palace": "from-manifest"}
        config = {"mempalace": {"palace": "from-config"}}
        assert aim.resolve_palace(manifest, config, "from-cli") == "from-cli"

    def test_manifest_beats_config(self):
        manifest = {"palace": "from-manifest"}
        config = {"mempalace": {"palace": "from-config"}}
        assert aim.resolve_palace(manifest, config, None) == "from-manifest"

    def test_config_fallback(self):
        manifest = {}
        config = {"mempalace": {"palace": "from-config"}}
        assert aim.resolve_palace(manifest, config, None) == "from-config"

    def test_no_source_raises(self):
        with pytest.raises(SystemExit, match="palace not specified"):
            aim.resolve_palace({}, None, None)

    def test_config_without_mempalace_section_raises(self):
        with pytest.raises(SystemExit, match="palace not specified"):
            aim.resolve_palace({}, {"unrelated": True}, None)


# ── Source resolution ────────────────────────────────────────────────────


class TestResolveSource:
    def test_absolute_path_unchanged(self, tmp_path: Path):
        f = tmp_path / "abs.json"
        f.write_text("{}", encoding="utf-8")
        assert aim.resolve_source(str(f), tmp_path) == f

    def test_relative_path_resolves_against_manifest_dir(self, tmp_path: Path):
        sub = tmp_path / "converted"
        sub.mkdir()
        f = sub / "book.json"
        f.write_text("{}", encoding="utf-8")
        got = aim.resolve_source("./converted/book.json", tmp_path)
        assert got == f.resolve()

    def test_tilde_expansion(self, tmp_path: Path):
        # We can't easily fake $HOME inside resolve_source, but expanduser
        # on a non-tilde path is a no-op so this is a smoke test that
        # tilde input doesn't crash.
        got = aim.resolve_source("~/some-path.json", tmp_path)
        assert "~" not in str(got)


# ── Argv construction ────────────────────────────────────────────────────


class TestBuildArgv:
    def test_minimal_entry(self, tmp_path: Path):
        f = tmp_path / "a.json"
        f.write_text("{}", encoding="utf-8")
        argv = aim.build_argv(
            {"source": str(f)},
            palace="abyss",
            manifest_dir=tmp_path,
            script_dir=Path("/scripts"),
        )
        assert argv[1:] == [
            "/scripts/fivetools_ingest.py",
            str(f),
            "--palace",
            "abyss",
        ]

    def test_filter_and_book_id(self, tmp_path: Path):
        f = tmp_path / "a.json"
        f.write_text("{}", encoding="utf-8")
        argv = aim.build_argv(
            {"source": str(f), "filter": "chapter=0", "book_id": 42},
            palace="abyss",
            manifest_dir=tmp_path,
            script_dir=Path("/scripts"),
        )
        assert "--filter" in argv and "chapter=0" in argv
        assert "--book-id" in argv and "42" in argv

    def test_force_flag_only_when_truthy(self, tmp_path: Path):
        f = tmp_path / "a.json"
        f.write_text("{}", encoding="utf-8")
        without = aim.build_argv(
            {"source": str(f)},
            palace="abyss",
            manifest_dir=tmp_path,
            script_dir=Path("/scripts"),
        )
        assert "--force" not in without
        with_ = aim.build_argv(
            {"source": str(f), "force": True},
            palace="abyss",
            manifest_dir=tmp_path,
            script_dir=Path("/scripts"),
        )
        assert "--force" in with_

    def test_dry_run_propagates(self, tmp_path: Path):
        f = tmp_path / "a.json"
        f.write_text("{}", encoding="utf-8")
        argv = aim.build_argv(
            {"source": str(f)},
            palace="abyss",
            manifest_dir=tmp_path,
            script_dir=Path("/scripts"),
            dry_run=True,
        )
        assert "--dry-run" in argv


# ── Status reporting ─────────────────────────────────────────────────────


class TestCheckStatus:
    def test_missing_source(self, tmp_path: Path):
        status, prior = aim.check_status(
            {"source": "nope.json"}, palace="abyss", manifest_dir=tmp_path
        )
        assert status == "missing-source"
        assert prior is None

    def test_never_run(self, tmp_path: Path):
        f = tmp_path / "a.json"
        f.write_text("{}", encoding="utf-8")
        status, prior = aim.check_status(
            {"source": str(f)}, palace="abyss", manifest_dir=tmp_path
        )
        assert status == "never-run"
        assert prior is None

    def test_ingested(self, tmp_path: Path):
        f = tmp_path / "a.json"
        f.write_text("{}", encoding="utf-8")
        sig = fti.file_signature(f)
        fti.write_state(
            f,
            {"version": 2, "size": sig["size"], "mtime": sig["mtime"], "ingested_at": "2026-05-25T10:00:00"},
            palace="abyss",
            filter_key="{}",
        )
        status, prior = aim.check_status(
            {"source": str(f)}, palace="abyss", manifest_dir=tmp_path
        )
        assert status == "ingested"
        assert prior and prior["ingested_at"] == "2026-05-25T10:00:00"

    def test_stale(self, tmp_path: Path):
        # Sidecar from an old (size, mtime). Source has changed since.
        f = tmp_path / "a.json"
        f.write_text("{}", encoding="utf-8")
        fti.write_state(
            f,
            {"version": 2, "size": 999, "mtime": 1.0, "ingested_at": "2026-01-01T00:00:00"},
            palace="abyss",
            filter_key="{}",
        )
        status, _ = aim.check_status(
            {"source": str(f)}, palace="abyss", manifest_dir=tmp_path
        )
        assert status == "stale"

    def test_different_palace_reports_never_run(self, tmp_path: Path):
        # Sidecar exists for palace=abyss, but we ask about palace=icespire.
        f = tmp_path / "a.json"
        f.write_text("{}", encoding="utf-8")
        sig = fti.file_signature(f)
        fti.write_state(
            f,
            {"version": 2, "size": sig["size"], "mtime": sig["mtime"]},
            palace="abyss",
            filter_key="{}",
        )
        status, _ = aim.check_status(
            {"source": str(f)}, palace="icespire", manifest_dir=tmp_path
        )
        assert status == "never-run"

    def test_different_filter_reports_never_run(self, tmp_path: Path):
        # Sidecar for filter={}, but we ask about filter=chapter=0.
        f = tmp_path / "a.json"
        f.write_text("{}", encoding="utf-8")
        sig = fti.file_signature(f)
        fti.write_state(
            f,
            {"version": 2, "size": sig["size"], "mtime": sig["mtime"]},
            palace="abyss",
            filter_key="{}",
        )
        status, _ = aim.check_status(
            {"source": str(f), "filter": "chapter=0"},
            palace="abyss",
            manifest_dir=tmp_path,
        )
        assert status == "never-run"


# ── --only parsing ───────────────────────────────────────────────────────


class TestParseOnly:
    def test_none_returns_none(self):
        assert aim.parse_only(None, 5) is None

    def test_single_index(self):
        assert aim.parse_only("3", 5) == {2}

    def test_comma_list(self):
        assert aim.parse_only("1,3,5", 5) == {0, 2, 4}

    def test_whitespace_tolerated(self):
        assert aim.parse_only(" 2 , 4 ", 5) == {1, 3}

    def test_out_of_range_raises(self):
        with pytest.raises(SystemExit, match="out of range"):
            aim.parse_only("6", 5)

    def test_non_integer_raises(self):
        with pytest.raises(SystemExit, match="expects integers"):
            aim.parse_only("a,b", 5)
