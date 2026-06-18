"""Tests for ``resolve_refs.py``.

We build minimal 5etools-shaped data trees inside ``tmp_path`` so the tests
never depend on the real ``~/src/5etools-kostadis/data/`` checkout. Each test
exercises one resolver concern (canonical, rpglib sidecar, homebrew, paths,
collisions, root precedence) in isolation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

import resolve_refs as rr


# ── Fixtures ─────────────────────────────────────────────────────────────


def _fake_5etools_tree(root: Path, sources: list[str]) -> Path:
    """Build a minimal 5etools data tree under ``root``.

    Creates ``adventures.json``, ``books.json``, ``bestiary/index.json``,
    ``spells/index.json``, plus stub per-source JSON files so the resolver's
    canonical pass can complete without exploding.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "adventures.json").write_text(
        json.dumps({"adventure": [{"id": s, "name": s} for s in sources]}),
        encoding="utf-8",
    )
    (root / "books.json").write_text(
        json.dumps({"book": []}),
        encoding="utf-8",
    )
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
    (root / "spells").mkdir()
    (root / "spells" / "index.json").write_text(
        json.dumps({}),
        encoding="utf-8",
    )
    return root


def _write_yaml(path: Path, body: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(body, str):
        path.write_text(body, encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(body), encoding="utf-8")
    return path


@pytest.fixture
def campaign(tmp_path: Path) -> Path:
    """A bare campaign workspace at ``tmp_path/campaign``."""
    c = tmp_path / "campaign"
    c.mkdir()
    return c


@pytest.fixture
def fivetools_root(tmp_path: Path) -> Path:
    """A minimal canonical 5etools tree with two adventure sources."""
    return _fake_5etools_tree(tmp_path / "fivetools-data", ["OotA", "MM"])


@pytest.fixture
def local_with_roots(campaign: Path, fivetools_root: Path, tmp_path: Path) -> Path:
    """A refs.local.yaml pointing at the test fixtures."""
    rpg = tmp_path / "rpg-library"
    rpg.mkdir()
    hb = tmp_path / "homebrew-private"
    hb.mkdir()
    return _write_yaml(
        campaign / rr.LOCAL_FILENAME,
        {
            "roots": {
                "fivetools_data": str(fivetools_root),
                "rpg_library": str(rpg),
                "homebrew_private": str(hb),
            }
        },
    )


# ── Loading & validation ─────────────────────────────────────────────────


class TestLoadRefs:
    def test_missing_file_raises(self, campaign: Path):
        with pytest.raises(SystemExit, match="not found"):
            rr.load_refs(campaign)

    def test_empty_file_raises(self, campaign: Path):
        _write_yaml(campaign / rr.REFS_FILENAME, "")
        with pytest.raises(SystemExit, match="is empty"):
            rr.load_refs(campaign)

    def test_top_level_not_mapping(self, campaign: Path):
        _write_yaml(campaign / rr.REFS_FILENAME, "- nope\n")
        with pytest.raises(SystemExit, match="top level must be a mapping"):
            rr.load_refs(campaign)

    def test_valid_minimal(self, campaign: Path):
        _write_yaml(campaign / rr.REFS_FILENAME, {"canonical": "all"})
        raw, p = rr.load_refs(campaign)
        assert raw == {"canonical": "all"}
        assert p == (campaign / rr.REFS_FILENAME).resolve()


class TestLoadLocal:
    def test_missing_is_ok(self, campaign: Path):
        raw, p = rr.load_local(campaign)
        assert raw == {}
        assert p is None

    def test_empty_is_ok(self, campaign: Path):
        _write_yaml(campaign / rr.LOCAL_FILENAME, "")
        raw, p = rr.load_local(campaign)
        assert raw == {}
        assert p is not None

    def test_not_mapping_raises(self, campaign: Path):
        _write_yaml(campaign / rr.LOCAL_FILENAME, "- nope\n")
        with pytest.raises(SystemExit, match="top level must be a mapping"):
            rr.load_local(campaign)


class TestRefsListValidation:
    def test_none_ok(self):
        assert rr._validate_refs_list(None) == []

    def test_not_a_list_raises(self):
        with pytest.raises(SystemExit, match="'refs:' must be a list"):
            rr._validate_refs_list({"oops": True})

    def test_entry_not_mapping_raises(self):
        with pytest.raises(SystemExit, match=r"refs\[1\] must be a mapping"):
            rr._validate_refs_list(["bare-string"])

    def test_entry_with_zero_kinds_raises(self):
        with pytest.raises(SystemExit, match="must have exactly one of"):
            rr._validate_refs_list([{"note": "missing kind"}])

    def test_entry_with_multiple_kinds_raises(self):
        with pytest.raises(SystemExit, match="must have exactly one of"):
            rr._validate_refs_list(
                [{"rpglib": "a", "path": "/b"}]
            )

    def test_single_kind_each_ok(self):
        rr._validate_refs_list(
            [
                {"rpglib": "a.pdf"},
                {"homebrew_private": "b/"},
                {"path": "/c.json"},
            ]
        )

    def test_library_on_non_rpglib_raises(self):
        with pytest.raises(SystemExit, match="only valid on 'rpglib:'"):
            rr._validate_refs_list([{"path": "/c.json", "library": "drivethrurpg"}])

    def test_library_empty_string_raises(self):
        with pytest.raises(SystemExit, match="non-empty string"):
            rr._validate_refs_list([{"rpglib": "a.pdf", "library": ""}])

    def test_library_valid_string_ok(self):
        rr._validate_refs_list([{"rpglib": "a.pdf", "library": "kickstarter"}])


# ── Root resolution & precedence ─────────────────────────────────────────


class TestResolveRoots:
    def test_local_beats_env_beats_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Set env var as a decoy
        monkeypatch.setenv("FIVETOOLS_DATA_ROOT", str(tmp_path / "from-env"))
        (tmp_path / "from-env").mkdir()
        (tmp_path / "from-local").mkdir()

        local = {"roots": {"fivetools_data": str(tmp_path / "from-local")}}
        roots = rr.resolve_roots(local, {"fivetools_data"})
        assert roots["fivetools_data"].source == "refs.local.yaml"
        assert roots["fivetools_data"].path == (tmp_path / "from-local").resolve()

    def test_env_used_when_local_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("FIVETOOLS_DATA_ROOT", str(tmp_path / "from-env"))
        (tmp_path / "from-env").mkdir()

        roots = rr.resolve_roots({}, {"fivetools_data"})
        assert roots["fivetools_data"].source == "env:FIVETOOLS_DATA_ROOT"
        assert roots["fivetools_data"].path == (tmp_path / "from-env").resolve()

    def test_default_used_as_last_resort(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("FIVETOOLS_DATA_ROOT", raising=False)
        roots = rr.resolve_roots({}, {"fivetools_data"})
        assert roots["fivetools_data"].source == "default"

    def test_no_default_for_rpg_library(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("RPG_LIBRARY_ROOT", raising=False)
        with pytest.raises(SystemExit, match="rpg_library"):
            rr.resolve_roots({}, {"rpg_library"})

    def test_unrequired_root_not_resolved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Even with rpg_library unconfigured, asking for only fivetools_data succeeds.
        monkeypatch.delenv("RPG_LIBRARY_ROOT", raising=False)
        roots = rr.resolve_roots({}, {"fivetools_data"})
        assert "rpg_library" not in roots

    def test_invalid_local_roots_section_raises(self):
        with pytest.raises(SystemExit, match="'roots:' must be a mapping"):
            rr.resolve_roots({"roots": ["bad"]}, {"fivetools_data"})


# ── Canonical resolution ─────────────────────────────────────────────────


class TestCanonicalResolution:
    def test_all_default(self, fivetools_root: Path):
        mode, in_scope, excluded = rr.resolve_canonical(
            {"canonical": "all"}, fivetools_root
        )
        assert mode == "all"
        assert "OotA" in in_scope and "MM" in in_scope
        assert excluded == []

    def test_all_with_exclude(self, fivetools_root: Path):
        mode, in_scope, excluded = rr.resolve_canonical(
            {"canonical": "all", "canonical_exclude": ["MM"]},
            fivetools_root,
        )
        assert mode == "all"
        assert "MM" not in in_scope
        assert "OotA" in in_scope
        assert excluded == ["MM"]

    def test_canonical_none_treated_as_all(self, fivetools_root: Path):
        # If the user omits canonical entirely, default to "all".
        mode, in_scope, _ = rr.resolve_canonical({}, fivetools_root)
        assert mode == "all"
        assert "OotA" in in_scope

    def test_whitelist(self, fivetools_root: Path):
        mode, in_scope, excluded = rr.resolve_canonical(
            {"canonical": ["OotA"]}, fivetools_root
        )
        assert mode == "whitelist"
        assert in_scope == ["OotA"]
        assert excluded == []

    def test_whitelist_unknown_source_raises(self, fivetools_root: Path):
        with pytest.raises(SystemExit, match="unknown source code"):
            rr.resolve_canonical({"canonical": ["NOPE"]}, fivetools_root)

    def test_whitelist_with_exclude_raises(self, fivetools_root: Path):
        with pytest.raises(
            SystemExit, match="'canonical_exclude:' only applies when 'canonical: all'"
        ):
            rr.resolve_canonical(
                {"canonical": ["OotA"], "canonical_exclude": ["MM"]},
                fivetools_root,
            )

    def test_bad_canonical_type_raises(self, fivetools_root: Path):
        with pytest.raises(SystemExit, match="must be 'all' or a list"):
            rr.resolve_canonical({"canonical": 42}, fivetools_root)

    def test_bad_exclude_type_raises(self, fivetools_root: Path):
        with pytest.raises(SystemExit, match="must be a list"):
            rr.resolve_canonical(
                {"canonical": "all", "canonical_exclude": "MM"}, fivetools_root
            )

    def test_missing_5etools_index_raises(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(SystemExit, match="not found"):
            rr.resolve_canonical({"canonical": "all"}, empty)


# ── rpglib sidecar resolution ────────────────────────────────────────────


class TestRpglibResolution:
    def test_resolves_sibling_json(self, tmp_path: Path):
        rpg = tmp_path / "rpg"
        sub = rpg / "WotC" / "Adventures"
        sub.mkdir(parents=True)
        # The PDF is referenced; its JSON sidecar is what we need.
        (sub / "T14.json").write_text("{}", encoding="utf-8")
        # The PDF itself doesn't need to exist on disk for the test —
        # the resolver only needs the JSON.

        root = rr.ResolvedRoot("rpg_library", rpg, "default")
        ref = rr._resolve_rpglib_entry(
            {"rpglib": "WotC/Adventures/T14.pdf"}, {"rpg_library": root}
        )
        assert ref.kind == "rpglib"
        assert ref.json_path == (sub / "T14.json").resolve()

    def test_missing_sidecar_raises(self, tmp_path: Path):
        rpg = tmp_path / "rpg"
        (rpg / "WotC" / "Adventures").mkdir(parents=True)
        root = rr.ResolvedRoot("rpg_library", rpg, "default")
        with pytest.raises(SystemExit, match="no JSON sidecar"):
            rr._resolve_rpglib_entry(
                {"rpglib": "WotC/Adventures/T14.pdf"}, {"rpg_library": root}
            )

    def test_book_id_preserved(self, tmp_path: Path):
        rpg = tmp_path / "rpg"
        sub = rpg / "x"
        sub.mkdir(parents=True)
        (sub / "b.json").write_text("{}", encoding="utf-8")
        root = rr.ResolvedRoot("rpg_library", rpg, "default")
        ref = rr._resolve_rpglib_entry(
            {"rpglib": "x/b.pdf", "book_id": 42, "note": "hi"},
            {"rpg_library": root},
        )
        assert ref.book_id == 42
        assert ref.note == "hi"

    def test_named_library_root_selects_correct_directory(self, tmp_path: Path):
        # DriveThru root has the PDF; Kickstarter root does not.
        dt = tmp_path / "drivethrurpg"
        ks = tmp_path / "kickstarter"
        (dt / "WotC").mkdir(parents=True)
        (dt / "WotC" / "T14.json").write_text("{}", encoding="utf-8")
        ks.mkdir()

        roots = {
            "rpg_library_drivethrurpg": rr.ResolvedRoot(
                "rpg_library_drivethrurpg", dt, "refs.local.yaml"
            ),
            "rpg_library_kickstarter": rr.ResolvedRoot(
                "rpg_library_kickstarter", ks, "refs.local.yaml"
            ),
        }
        ref = rr._resolve_rpglib_entry(
            {"rpglib": "WotC/T14.pdf", "library": "drivethrurpg"}, roots
        )
        assert ref.json_path == (dt / "WotC" / "T14.json").resolve()

    def test_named_library_root_missing_sidecar_raises(self, tmp_path: Path):
        ks = tmp_path / "kickstarter"
        ks.mkdir()
        roots = {
            "rpg_library_kickstarter": rr.ResolvedRoot(
                "rpg_library_kickstarter", ks, "refs.local.yaml"
            )
        }
        with pytest.raises(SystemExit, match="no JSON sidecar"):
            rr._resolve_rpglib_entry(
                {"rpglib": "SomeModule.pdf", "library": "kickstarter"}, roots
            )

    def test_rpglib_root_name_no_library(self):
        assert rr._rpglib_root_name({"rpglib": "a.pdf"}) == "rpg_library"

    def test_rpglib_root_name_with_library(self):
        assert rr._rpglib_root_name({"rpglib": "a.pdf", "library": "drivethrurpg"}) == "rpg_library_drivethrurpg"
        assert rr._rpglib_root_name({"rpglib": "a.pdf", "library": "kickstarter"}) == "rpg_library_kickstarter"


# ── homebrew_private resolution ──────────────────────────────────────────


class TestHomebrewResolution:
    def test_single_file(self, tmp_path: Path):
        hb = tmp_path / "hb"
        hb.mkdir()
        (hb / "a.json").write_text("{}", encoding="utf-8")
        root = rr.ResolvedRoot("homebrew_private", hb, "default")
        refs = rr._resolve_homebrew_entry(
            {"homebrew_private": "a.json"}, {"homebrew_private": root}
        )
        assert len(refs) == 1
        assert refs[0].json_path == (hb / "a.json").resolve()

    def test_directory_recursive(self, tmp_path: Path):
        hb = tmp_path / "hb"
        (hb / "sub" / "deep").mkdir(parents=True)
        (hb / "sub" / "x.json").write_text("{}", encoding="utf-8")
        (hb / "sub" / "deep" / "y.json").write_text("{}", encoding="utf-8")
        (hb / "sub" / "z.txt").write_text("ignored", encoding="utf-8")
        root = rr.ResolvedRoot("homebrew_private", hb, "default")
        refs = rr._resolve_homebrew_entry(
            {"homebrew_private": "sub"}, {"homebrew_private": root}
        )
        paths = {r.json_path for r in refs}
        assert (hb / "sub" / "x.json").resolve() in paths
        assert (hb / "sub" / "deep" / "y.json").resolve() in paths
        assert (hb / "sub" / "z.txt").resolve() not in paths

    def test_directory_skips_dotdirs(self, tmp_path: Path):
        hb = tmp_path / "hb"
        (hb / "sub" / ".git").mkdir(parents=True)
        (hb / "sub" / "ok.json").write_text("{}", encoding="utf-8")
        (hb / "sub" / ".git" / "secret.json").write_text("{}", encoding="utf-8")
        root = rr.ResolvedRoot("homebrew_private", hb, "default")
        refs = rr._resolve_homebrew_entry(
            {"homebrew_private": "sub"}, {"homebrew_private": root}
        )
        paths = {r.json_path for r in refs}
        assert (hb / "sub" / "ok.json").resolve() in paths
        assert (hb / "sub" / ".git" / "secret.json").resolve() not in paths

    def test_missing_path_raises(self, tmp_path: Path):
        hb = tmp_path / "hb"
        hb.mkdir()
        root = rr.ResolvedRoot("homebrew_private", hb, "default")
        with pytest.raises(SystemExit, match="does not exist"):
            rr._resolve_homebrew_entry(
                {"homebrew_private": "missing.json"}, {"homebrew_private": root}
            )

    def test_empty_dir_raises(self, tmp_path: Path):
        hb = tmp_path / "hb"
        (hb / "empty").mkdir(parents=True)
        root = rr.ResolvedRoot("homebrew_private", hb, "default")
        with pytest.raises(SystemExit, match="contains no .json files"):
            rr._resolve_homebrew_entry(
                {"homebrew_private": "empty"}, {"homebrew_private": root}
            )


# ── path resolution ──────────────────────────────────────────────────────


class TestPathResolution:
    def test_absolute_path(self, tmp_path: Path, campaign: Path):
        f = tmp_path / "x.json"
        f.write_text("{}", encoding="utf-8")
        ref = rr._resolve_path_entry({"path": str(f)}, campaign)
        assert ref.kind == "path"
        assert ref.json_path == f.resolve()

    def test_relative_resolves_against_campaign(self, campaign: Path):
        (campaign / "local.json").write_text("{}", encoding="utf-8")
        ref = rr._resolve_path_entry({"path": "local.json"}, campaign)
        assert ref.json_path == (campaign / "local.json").resolve()

    def test_missing_raises(self, campaign: Path):
        with pytest.raises(SystemExit, match="is not a file"):
            rr._resolve_path_entry({"path": "/nope/never.json"}, campaign)


# ── Collision detection ──────────────────────────────────────────────────


class TestCollisionDetection:
    def _ref(self, name: str) -> rr.ResolvedRef:
        return rr.ResolvedRef(
            kind="path", abstract=name, json_path=Path(f"/tmp/{name}")
        )

    def test_no_collisions_ok(self):
        rr._detect_collisions(["OotA"], [self._ref("bestiary-cos.json")])

    def test_ref_collides_with_canonical(self):
        with pytest.raises(SystemExit, match="already in the canonical scope"):
            rr._detect_collisions(["MM"], [self._ref("bestiary-mm.json")])

    def test_two_refs_collide(self):
        with pytest.raises(SystemExit, match="two refs both resolve to"):
            rr._detect_collisions(
                [],
                [self._ref("bestiary-cos.json"), self._ref("bestiary-cos.json")],
            )

    def test_unrecognized_filename_does_not_collide(self):
        # Files that don't follow the source-code prefix convention don't
        # participate in collision detection — we only know what we can parse.
        rr._detect_collisions(
            ["MM"],
            [self._ref("my-homebrew.json"), self._ref("another.json")],
        )


# ── Top-level resolve() integration ──────────────────────────────────────


class TestResolve:
    def test_minimal_canonical_all(
        self, campaign: Path, fivetools_root: Path, local_with_roots: Path
    ):
        _write_yaml(campaign / rr.REFS_FILENAME, {"canonical": "all"})
        scope = rr.resolve(campaign)
        assert scope.canonical_mode == "all"
        assert set(scope.canonical_sources) >= {"OotA", "MM"}
        assert scope.refs == []
        assert scope.local_path is not None

    def test_canonical_with_exclude_and_refs(
        self,
        campaign: Path,
        fivetools_root: Path,
        local_with_roots: Path,
        tmp_path: Path,
    ):
        # Set up a homebrew file the resolver should pick up.
        hb_root = Path(yaml.safe_load((campaign / rr.LOCAL_FILENAME).read_text())["roots"]["homebrew_private"])
        (hb_root / "my-homebrew.json").write_text("{}", encoding="utf-8")

        _write_yaml(
            campaign / rr.REFS_FILENAME,
            {
                "canonical": "all",
                "canonical_exclude": ["MM"],
                "refs": [{"homebrew_private": "my-homebrew.json"}],
            },
        )
        scope = rr.resolve(campaign)
        assert "MM" not in scope.canonical_sources
        assert scope.canonical_excluded == ["MM"]
        assert len(scope.refs) == 1
        assert scope.refs[0].kind == "homebrew_private"

    def test_resolve_without_local_uses_defaults(
        self, campaign: Path, fivetools_root: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Point the env var at our test fixture so the default-fallback hits something real.
        monkeypatch.setenv("FIVETOOLS_DATA_ROOT", str(fivetools_root))
        _write_yaml(campaign / rr.REFS_FILENAME, {"canonical": "all"})
        scope = rr.resolve(campaign)
        assert scope.local_path is None
        assert scope.roots["fivetools_data"].path == fivetools_root.resolve()

    def test_resolve_errors_when_rpg_library_missing(
        self, campaign: Path, fivetools_root: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("FIVETOOLS_DATA_ROOT", str(fivetools_root))
        monkeypatch.delenv("RPG_LIBRARY_ROOT", raising=False)
        _write_yaml(
            campaign / rr.REFS_FILENAME,
            {
                "canonical": "all",
                "refs": [{"rpglib": "x/y.pdf"}],
            },
        )
        with pytest.raises(SystemExit, match="rpg_library"):
            rr.resolve(campaign)
