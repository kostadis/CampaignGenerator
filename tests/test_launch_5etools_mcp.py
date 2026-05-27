"""Tests for ``launch_5etools_mcp.py``.

We exercise the parts the launcher owns directly: runtime-tree construction,
canonical filtering (fast path + filtered mirror), homebrew shape detection
and indexing, idempotence via the sha256 sidecar, and the ``--init-local``
non-destructive behavior. We never exec the actual MCP server; ``--no-exec``
covers that integration boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

import launch_5etools_mcp as launcher
import resolve_refs as rr


# ── Shared fixtures (mirror test_resolve_refs.py shape) ──────────────────


def _fake_5etools_tree(root: Path, sources: list[str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "adventures.json").write_text(
        json.dumps({"adventure": [{"id": s, "name": s, "source": s} for s in sources]}),
        encoding="utf-8",
    )
    (root / "books.json").write_text(json.dumps({"book": []}), encoding="utf-8")
    (root / "bestiary").mkdir()
    (root / "bestiary" / "index.json").write_text(
        json.dumps({s: f"bestiary-{s.lower()}.json" for s in sources}),
        encoding="utf-8",
    )
    for s in sources:
        (root / "bestiary" / f"bestiary-{s.lower()}.json").write_text(
            json.dumps({"monster": []}),
            encoding="utf-8",
        )
        # Adventure content file per source.
        (root / "adventure").mkdir(exist_ok=True)
        (root / "adventure" / f"adventure-{s.lower()}.json").write_text(
            json.dumps({"data": [{"name": f"{s} chapter 1", "id": "ch1"}]}),
            encoding="utf-8",
        )
    (root / "spells").mkdir()
    (root / "spells" / "index.json").write_text(json.dumps({}), encoding="utf-8")
    # A top-level cross-source file (should be symlinked as-is in filtered mode).
    (root / "items.json").write_text(json.dumps({"item": []}), encoding="utf-8")
    return root


def _write_yaml(path: Path, body: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    return path


@pytest.fixture
def campaign(tmp_path: Path) -> Path:
    c = tmp_path / "campaign"
    c.mkdir()
    return c


@pytest.fixture
def fivetools_root(tmp_path: Path) -> Path:
    return _fake_5etools_tree(tmp_path / "fivetools-data", ["OotA", "MM"])


@pytest.fixture
def homebrew_root(tmp_path: Path) -> Path:
    hb = tmp_path / "homebrew-private"
    hb.mkdir()
    return hb


@pytest.fixture
def setup_local(campaign: Path, fivetools_root: Path, homebrew_root: Path, tmp_path: Path) -> Path:
    rpg = tmp_path / "rpg-library"
    rpg.mkdir()
    return _write_yaml(
        campaign / rr.LOCAL_FILENAME,
        {
            "roots": {
                "fivetools_data": str(fivetools_root),
                "rpg_library": str(rpg),
                "homebrew_private": str(homebrew_root),
            }
        },
    )


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the launcher's runtime base into tmp_path so each test is hermetic."""
    base = tmp_path / "runtime"
    monkeypatch.setattr(launcher, "RUNTIME_BASE", base)
    return base


# ── Slug + path computation ──────────────────────────────────────────────


class TestSlug:
    def test_basic_lowercase(self, tmp_path: Path):
        d = tmp_path / "My-Campaign"
        d.mkdir()
        assert launcher._slug(d) == "my-campaign"

    def test_punctuation_collapses(self, tmp_path: Path):
        d = tmp_path / "out.of.the.abyss"
        d.mkdir()
        assert launcher._slug(d) == "out-of-the-abyss"

    def test_only_punct_falls_back(self, tmp_path: Path):
        d = tmp_path / "..."
        d.mkdir()
        assert launcher._slug(d) == "campaign"


class TestRuntimeDirFor:
    def test_path_under_base(self, campaign: Path, runtime: Path):
        out = launcher.runtime_dir_for(campaign)
        assert out.parent == runtime
        assert out.name == launcher._slug(campaign)


# ── Idempotence sidecar ──────────────────────────────────────────────────


class TestSourcesHash:
    def test_refs_only(self, tmp_path: Path):
        r = tmp_path / "refs.yaml"
        r.write_text("a: 1\n", encoding="utf-8")
        h1 = launcher._sources_hash(r, None)
        r.write_text("a: 2\n", encoding="utf-8")
        h2 = launcher._sources_hash(r, None)
        assert h1 != h2

    def test_local_included(self, tmp_path: Path):
        r = tmp_path / "refs.yaml"
        l = tmp_path / "refs.local.yaml"
        r.write_text("a: 1\n", encoding="utf-8")
        l.write_text("b: 1\n", encoding="utf-8")
        h1 = launcher._sources_hash(r, l)
        l.write_text("b: 2\n", encoding="utf-8")
        h2 = launcher._sources_hash(r, l)
        assert h1 != h2

    def test_missing_local_ignored(self, tmp_path: Path):
        r = tmp_path / "refs.yaml"
        r.write_text("a: 1\n", encoding="utf-8")
        h1 = launcher._sources_hash(r, None)
        # Passing a nonexistent path produces the same hash as None.
        h2 = launcher._sources_hash(r, tmp_path / "nope.yaml")
        assert h1 == h2


# ── Shape detection ──────────────────────────────────────────────────────


class TestPeekShape:
    def test_adventure_meta(self, tmp_path: Path):
        f = tmp_path / "x.json"
        f.write_text(json.dumps({"adventure": [{"id": "MyAdv"}]}), encoding="utf-8")
        shape, sid = launcher._peek_shape(f)
        assert shape == "adventure_meta"
        assert sid == "MyAdv"

    def test_book_meta(self, tmp_path: Path):
        f = tmp_path / "x.json"
        f.write_text(json.dumps({"book": [{"id": "MyBook"}]}), encoding="utf-8")
        shape, sid = launcher._peek_shape(f)
        assert shape == "book_meta"
        assert sid == "MyBook"

    def test_adventure_content_with_filename(self, tmp_path: Path):
        f = tmp_path / "adventure-myadv.json"
        f.write_text(json.dumps({"data": [{"name": "Ch1"}]}), encoding="utf-8")
        shape, sid = launcher._peek_shape(f)
        assert shape == "adventure_content"
        assert sid == "MYADV"

    def test_bestiary(self, tmp_path: Path):
        f = tmp_path / "bestiary-mm.json"
        f.write_text(json.dumps({"monster": [{"name": "Goblin"}]}), encoding="utf-8")
        shape, sid = launcher._peek_shape(f)
        assert shape == "bestiary"
        assert sid == "MM"

    def test_spells(self, tmp_path: Path):
        f = tmp_path / "spells-phb.json"
        f.write_text(json.dumps({"spell": [{"name": "Fireball"}]}), encoding="utf-8")
        shape, sid = launcher._peek_shape(f)
        assert shape == "spells"
        assert sid == "PHB"

    def test_meta_source_wins(self, tmp_path: Path):
        # When _meta.source is present, prefer it over filename or first-entry id.
        f = tmp_path / "bestiary-x.json"
        f.write_text(
            json.dumps({"_meta": {"source": "MYSRC"}, "monster": []}),
            encoding="utf-8",
        )
        shape, sid = launcher._peek_shape(f)
        assert shape == "bestiary"
        assert sid == "MYSRC"

    def test_unknown_shape(self, tmp_path: Path):
        f = tmp_path / "x.json"
        f.write_text(json.dumps({"random": "blob"}), encoding="utf-8")
        shape, _ = launcher._peek_shape(f)
        assert shape == "other"

    def test_malformed_raises(self, tmp_path: Path):
        f = tmp_path / "x.json"
        f.write_text("not json", encoding="utf-8")
        with pytest.raises(SystemExit, match="cannot parse"):
            launcher._peek_shape(f)


# ── build_runtime_tree: canonical fast path ──────────────────────────────


class TestCanonicalFastPath:
    def test_no_exclude_symlinks_whole_tree(
        self, campaign: Path, fivetools_root: Path, setup_local: Path, runtime: Path
    ):
        _write_yaml(campaign / rr.REFS_FILENAME, {"canonical": "all"})
        scope = rr.resolve(campaign)
        rt = launcher.runtime_dir_for(campaign)
        launcher.build_runtime_tree(rt, scope)

        assert (rt / "data").is_symlink()
        assert (rt / "data").resolve() == fivetools_root.resolve()
        assert (rt / "homebrew").is_dir()
        assert (rt / launcher.SHA_FILENAME).is_file()


# ── build_runtime_tree: canonical filtered mirror ────────────────────────


class TestCanonicalFilteredMirror:
    def test_exclude_drops_source_files(
        self, campaign: Path, fivetools_root: Path, setup_local: Path, runtime: Path
    ):
        _write_yaml(
            campaign / rr.REFS_FILENAME,
            {"canonical": "all", "canonical_exclude": ["MM"]},
        )
        scope = rr.resolve(campaign)
        rt = launcher.runtime_dir_for(campaign)
        launcher.build_runtime_tree(rt, scope)

        # data/ is now a directory (not a symlink to canonical root).
        assert (rt / "data").is_dir() and not (rt / "data").is_symlink()

        # adventures.json filtered.
        adv = json.loads((rt / "data" / "adventures.json").read_text())
        ids = {e["id"] for e in adv["adventure"]}
        assert "OotA" in ids
        assert "MM" not in ids

        # bestiary/index.json filtered.
        idx = json.loads((rt / "data" / "bestiary" / "index.json").read_text())
        assert "OotA" in idx
        assert "MM" not in idx

        # Per-source bestiary file for in-scope source is symlinked.
        assert (rt / "data" / "bestiary" / "bestiary-oota.json").is_symlink()
        # Per-source bestiary file for excluded source is absent.
        assert not (rt / "data" / "bestiary" / "bestiary-mm.json").exists()

        # adventure/ subdir: in-scope file present, excluded file absent.
        assert (rt / "data" / "adventure" / "adventure-oota.json").is_symlink()
        assert not (rt / "data" / "adventure" / "adventure-mm.json").exists()

        # Cross-source top-level file (items.json) is symlinked as-is.
        items = rt / "data" / "items.json"
        assert items.is_symlink()
        assert items.resolve() == (fivetools_root / "items.json").resolve()


# ── build_runtime_tree: homebrew layout ──────────────────────────────────


class TestHomebrew:
    def test_bestiary_routes_to_subdir_and_index(
        self,
        campaign: Path,
        fivetools_root: Path,
        homebrew_root: Path,
        setup_local: Path,
        runtime: Path,
    ):
        # Drop a homebrew bestiary into the homebrew-private root.
        (homebrew_root / "bestiary-myhb.json").write_text(
            json.dumps({"monster": [{"name": "Goblin Lord"}]}),
            encoding="utf-8",
        )
        _write_yaml(
            campaign / rr.REFS_FILENAME,
            {
                "canonical": "all",
                "refs": [{"homebrew_private": "bestiary-myhb.json"}],
            },
        )
        scope = rr.resolve(campaign)
        rt = launcher.runtime_dir_for(campaign)
        launcher.build_runtime_tree(rt, scope)

        # The bestiary file should land at homebrew/bestiary/bestiary-myhb.json
        target = rt / "homebrew" / "bestiary" / "bestiary-myhb.json"
        assert target.is_symlink()
        assert target.resolve() == (homebrew_root / "bestiary-myhb.json").resolve()
        # And the index should record it.
        idx = json.loads((rt / "homebrew" / "bestiary" / "index.json").read_text())
        assert "MYHB" in idx

    def test_adventure_content_synthesizes_meta(
        self,
        campaign: Path,
        fivetools_root: Path,
        homebrew_root: Path,
        setup_local: Path,
        runtime: Path,
    ):
        (homebrew_root / "adventure-myadv.json").write_text(
            json.dumps({"data": [{"name": "Opening", "id": "ch0"}]}),
            encoding="utf-8",
        )
        _write_yaml(
            campaign / rr.REFS_FILENAME,
            {
                "canonical": "all",
                "refs": [
                    {"homebrew_private": "adventure-myadv.json", "note": "My adv"}
                ],
            },
        )
        scope = rr.resolve(campaign)
        rt = launcher.runtime_dir_for(campaign)
        launcher.build_runtime_tree(rt, scope)

        assert (rt / "homebrew" / "adventure" / "adventure-myadv.json").is_symlink()
        adv = json.loads((rt / "homebrew" / "adventures.json").read_text())
        ids = {e["id"] for e in adv["adventure"]}
        assert "MYADV" in ids

    def test_unknown_shape_goes_to_loose(
        self,
        campaign: Path,
        fivetools_root: Path,
        homebrew_root: Path,
        setup_local: Path,
        runtime: Path,
    ):
        (homebrew_root / "mystery.json").write_text(
            json.dumps({"strange": "thing"}), encoding="utf-8"
        )
        _write_yaml(
            campaign / rr.REFS_FILENAME,
            {
                "canonical": "all",
                "refs": [{"homebrew_private": "mystery.json"}],
            },
        )
        scope = rr.resolve(campaign)
        rt = launcher.runtime_dir_for(campaign)
        launcher.build_runtime_tree(rt, scope)
        assert (rt / "homebrew" / "loose" / "mystery.json").is_symlink()


# ── Idempotence ──────────────────────────────────────────────────────────


class TestIdempotence:
    def test_unchanged_refs_skip_rebuild(
        self, campaign: Path, fivetools_root: Path, setup_local: Path, runtime: Path
    ):
        _write_yaml(campaign / rr.REFS_FILENAME, {"canonical": "all"})
        scope = rr.resolve(campaign)
        rt = launcher.runtime_dir_for(campaign)

        launcher.build_runtime_tree(rt, scope)
        sidecar_before = (rt / launcher.SHA_FILENAME).stat().st_mtime_ns
        marker = rt / "marker.txt"
        marker.write_text("preserved", encoding="utf-8")

        # Second invocation with unchanged refs: should not rebuild.
        launcher.build_runtime_tree(rt, scope)
        assert marker.is_file()  # not blown away
        assert (rt / launcher.SHA_FILENAME).stat().st_mtime_ns == sidecar_before

    def test_changed_refs_trigger_rebuild(
        self, campaign: Path, fivetools_root: Path, setup_local: Path, runtime: Path
    ):
        _write_yaml(campaign / rr.REFS_FILENAME, {"canonical": "all"})
        scope = rr.resolve(campaign)
        rt = launcher.runtime_dir_for(campaign)
        launcher.build_runtime_tree(rt, scope)
        marker = rt / "marker.txt"
        marker.write_text("will be wiped", encoding="utf-8")

        # Change refs and re-resolve.
        _write_yaml(
            campaign / rr.REFS_FILENAME,
            {"canonical": "all", "canonical_exclude": ["MM"]},
        )
        scope2 = rr.resolve(campaign)
        launcher.build_runtime_tree(rt, scope2)
        assert not marker.is_file()


# ── --init-local ─────────────────────────────────────────────────────────


class TestInitLocal:
    def test_writes_starter(self, campaign: Path):
        launcher.cmd_init_local(campaign)
        body = yaml.safe_load((campaign / rr.LOCAL_FILENAME).read_text())
        assert "roots" in body
        assert body["roots"]["rpg_library"] == ""  # intentionally blank

    def test_refuses_to_overwrite(self, campaign: Path):
        (campaign / rr.LOCAL_FILENAME).write_text("existing: true\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="already exists"):
            launcher.cmd_init_local(campaign)


# ── cmd_apply with --no-exec (env construction) ──────────────────────────


class TestApplyEnvConstruction:
    def test_data_dirs_and_campaign_dir_set(
        self,
        campaign: Path,
        fivetools_root: Path,
        setup_local: Path,
        runtime: Path,
        capsys: pytest.CaptureFixture,
    ):
        _write_yaml(campaign / rr.REFS_FILENAME, {"canonical": "all"})
        scope = rr.resolve(campaign)
        rt = launcher.runtime_dir_for(campaign)
        rc = launcher.cmd_apply(scope, rt, Path("/nonexistent/index.js"), {}, no_exec=True)
        out = capsys.readouterr().out
        assert rc == 0
        assert f"DATA_DIRS={rt / 'data'}:{rt / 'homebrew'}" in out
        assert f"CAMPAIGN_DIR={campaign.resolve()}" in out
