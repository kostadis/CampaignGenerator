"""Tests for fivetools_catalog — the awareness layer over 5etools data.

Strategy: build a tiny on-disk fixture tree (one bestiary file, one
spells file, one adventure file) and assert the catalog produces the
right candidate records and search rankings. No I/O outside ``tmp_path``.
"""

from __future__ import annotations

import json
import os
import pickle
import time
from pathlib import Path

import pytest

import pipelines.rlm.fivetools_catalog as fc


# ── Fixture data tree ─────────────────────────────────────────────────────


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    """Tiny but realistic 5etools data tree."""
    root = tmp_path / "data"

    # Bestiary shard: 3 monsters from MM.
    bestiary = root / "bestiary"
    bestiary.mkdir(parents=True)
    (bestiary / "bestiary-mm.json").write_text(json.dumps({
        "_meta": {},
        "monster": [
            {"name": "Drow Priestess of Lolth", "source": "MM", "page": 129,
             "size": ["M"], "type": "humanoid"},
            {"name": "Drow", "source": "MM", "page": 128,
             "size": ["M"], "type": "humanoid"},
            {"name": "Goblin", "source": "MM", "page": 166,
             "size": ["S"], "type": "humanoid"},
        ],
    }))
    # Required by load_dependency_pool but not by build_catalog.
    (bestiary / "index.json").write_text(json.dumps({"MM": "bestiary-mm.json"}))

    # Spells shard.
    spells = root / "spells"
    spells.mkdir(parents=True)
    (spells / "spells-phb.json").write_text(json.dumps({
        "_meta": {},
        "spell": [
            {"name": "Fireball", "source": "PHB", "page": 241, "level": 3, "school": "V"},
            {"name": "Faerie Fire", "source": "PHB", "page": 239, "level": 1, "school": "V"},
        ],
    }))
    (spells / "index.json").write_text(json.dumps({"PHB": "spells-phb.json"}))

    # Adventure file.
    adventures = root / "adventure"
    adventures.mkdir(parents=True)
    (adventures / "adventure-oota.json").write_text(json.dumps({
        "_meta": {"sources": [{"json": "OotA", "abbreviation": "OotA",
                                "full": "Out of the Abyss"}]},
        "adventure": [{"id": "OotA", "source": "OotA", "name": "Out of the Abyss"}],
        "adventureData": [{
            "id": "OotA", "source": "OotA",
            "data": [
                {"type": "section", "name": "Prisoners of the Drow",
                 "entries": [
                     {"type": "entries", "name": "Velkynvelve",
                      "entries": ["A drow outpost in the Underdark."]},
                     {"type": "entries", "name": "The Slavers",
                      "entries": ["Ilvara Mizzrym leads the patrol."]},
                 ]},
                {"type": "section", "name": "Into Darkness", "entries": []},
            ],
        }],
    }))
    (adventures / "index.json").write_text(json.dumps({"OotA": "adventure-oota.json"}))

    # An unrelated file at the top of the tree (gendata-style; should be skipped).
    (root / "gendata-tag-redirects.json").write_text(json.dumps({
        "redirects": {"PHB": "XPHB"},
    }))

    return root


# ── Build ─────────────────────────────────────────────────────────────────


class TestBuildCatalog:
    def test_records_every_catalog_entity(self, data_root: Path):
        cat = fc.build_catalog(data_root)
        names = {(c.entity_type, c.name, c.source) for c in cat.entities}
        # Catalog entities present.
        assert ("monster", "Drow Priestess of Lolth", "MM") in names
        assert ("monster", "Drow", "MM") in names
        assert ("monster", "Goblin", "MM") in names
        assert ("spell", "Fireball", "PHB") in names
        assert ("spell", "Faerie Fire", "PHB") in names

    def test_records_adventure_chapters_and_subsections(self, data_root: Path):
        cat = fc.build_catalog(data_root)
        chapters = [c for c in cat.entities if c.entity_type == "chapter"]
        sections = [c for c in cat.entities if c.entity_type == "section"]
        assert {c.name for c in chapters} == {"Prisoners of the Drow", "Into Darkness"}
        # Sub-sections one level deep are indexed.
        assert "Velkynvelve" in {c.name for c in sections}
        assert "The Slavers" in {c.name for c in sections}

    def test_chapter_ordinal_is_zero_based(self, data_root: Path):
        cat = fc.build_catalog(data_root)
        c1 = next(c for c in cat.entities if c.name == "Prisoners of the Drow")
        c2 = next(c for c in cat.entities if c.name == "Into Darkness")
        assert c1.chapter_ordinal == 0
        assert c2.chapter_ordinal == 1
        # Sub-sections inherit their parent chapter ordinal.
        velkyn = next(c for c in cat.entities if c.name == "Velkynvelve")
        assert velkyn.chapter_ordinal == 0

    def test_adventure_source_pulled_from_meta(self, data_root: Path):
        cat = fc.build_catalog(data_root)
        for c in cat.entities:
            if c.entity_type in ("chapter", "section"):
                assert c.source == "OotA"

    def test_file_path_is_absolute(self, data_root: Path):
        cat = fc.build_catalog(data_root)
        for c in cat.entities:
            p = Path(c.file_path)
            assert p.is_absolute()
            assert p.is_file()

    def test_page_carried_when_present(self, data_root: Path):
        cat = fc.build_catalog(data_root)
        drow_priestess = next(c for c in cat.entities if c.name == "Drow Priestess of Lolth")
        assert drow_priestess.page == 129

    def test_skips_index_and_gendata_files(self, data_root: Path):
        # index.json and gendata-* should not contribute entities.
        cat = fc.build_catalog(data_root)
        for c in cat.entities:
            assert "index.json" not in c.file_path
            assert "gendata-" not in Path(c.file_path).name

    def test_missing_root_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            fc.build_catalog(tmp_path / "nonexistent")

    def test_corrupt_json_is_skipped_with_warning(self, data_root: Path):
        (data_root / "broken.json").write_text("{not json")
        warnings: list[str] = []
        cat = fc.build_catalog(data_root, on_warning=warnings.append)
        # Catalog still built; warning recorded.
        assert any("broken.json" in w for w in warnings)
        assert len(cat.entities) > 0


# ── Search ────────────────────────────────────────────────────────────────


class TestSearch:
    def test_exact_match_outranks_substring(self, data_root: Path):
        cat = fc.build_catalog(data_root)
        # "Drow" matches exactly the second-row monster, and as a prefix
        # to "Drow Priestess of Lolth". Exact match should win.
        hits = fc.search(cat, "Drow")
        assert hits[0].name == "Drow"
        # 100 base + type-quality bonus for primary entity.
        assert hits[0].score >= 100

    def test_prefix_outranks_substring(self, data_root: Path):
        cat = fc.build_catalog(data_root)
        # "Drow P" — prefix to "Drow Priestess..." (score 80), no exact.
        hits = fc.search(cat, "Drow P")
        assert hits[0].name == "Drow Priestess of Lolth"
        assert 80 <= hits[0].score < 100

    def test_substring_match(self, data_root: Path):
        cat = fc.build_catalog(data_root)
        hits = fc.search(cat, "priestess")
        names = [h.name for h in hits]
        assert "Drow Priestess of Lolth" in names

    def test_case_insensitive(self, data_root: Path):
        cat = fc.build_catalog(data_root)
        hits = fc.search(cat, "FIREBALL")
        assert any(h.name == "Fireball" and h.score >= 100 for h in hits)

    def test_primary_entity_outranks_chapter_at_same_name_match(self, tmp_path: Path):
        """Regression: real-data search for "fireball" was returning the
        adventure chapter named "Fireball" before the actual spell.
        Type-quality bonus should keep primary catalog entries on top.
        """
        root = tmp_path / "data"
        (root / "spells").mkdir(parents=True)
        (root / "spells" / "spells-phb.json").write_text(json.dumps({
            "_meta": {},
            "spell": [{"name": "Fireball", "source": "PHB", "page": 241}],
        }))
        (root / "adventure").mkdir(parents=True)
        # An adventure that happens to have a chapter named "Fireball".
        (root / "adventure" / "adventure-x.json").write_text(json.dumps({
            "_meta": {"sources": [{"json": "X", "abbreviation": "X"}]},
            "adventure": [{"id": "X", "source": "X", "name": "X"}],
            "adventureData": [{"id": "X", "source": "X",
                "data": [{"type": "section", "name": "Fireball", "entries": []}]}],
        }))
        cat = fc.build_catalog(root)
        hits = fc.search(cat, "fireball", limit=5)
        # The spell entry must rank ahead of the adventure chapter.
        spell_idx = next(i for i, h in enumerate(hits) if h.entity_type == "spell")
        chapter_idx = next(i for i, h in enumerate(hits) if h.entity_type == "chapter")
        assert spell_idx < chapter_idx

    def test_adventure_subsection_matches(self, data_root: Path):
        cat = fc.build_catalog(data_root)
        hits = fc.search(cat, "velkynvelve")
        assert hits and hits[0].name == "Velkynvelve"
        assert hits[0].entity_type == "section"
        assert hits[0].file_path.endswith("adventure-oota.json")
        assert hits[0].chapter_ordinal == 0

    def test_token_overlap_falls_back(self, data_root: Path):
        cat = fc.build_catalog(data_root)
        # "lolth priestess" — neither substring of any one name, but
        # both tokens appear in "Drow Priestess of Lolth".
        hits = fc.search(cat, "lolth priestess")
        names = [h.name for h in hits]
        assert "Drow Priestess of Lolth" in names

    def test_no_match_returns_empty(self, data_root: Path):
        cat = fc.build_catalog(data_root)
        assert fc.search(cat, "xyzzy_no_such_entity") == []

    def test_empty_query_returns_empty(self, data_root: Path):
        cat = fc.build_catalog(data_root)
        assert fc.search(cat, "") == []
        assert fc.search(cat, "   ") == []

    def test_limit_applied(self, data_root: Path):
        cat = fc.build_catalog(data_root)
        # "drow" matches 2 monsters by name + Drow Priestess by prefix.
        hits = fc.search(cat, "drow", limit=1)
        assert len(hits) == 1

    def test_results_are_deterministic(self, data_root: Path):
        cat = fc.build_catalog(data_root)
        a = fc.search(cat, "drow")
        b = fc.search(cat, "drow")
        assert [(h.name, h.file_path) for h in a] == [(h.name, h.file_path) for h in b]


# ── Cache ─────────────────────────────────────────────────────────────────


class TestLoadOrBuild:
    def test_first_call_builds_and_writes_cache(self, data_root: Path):
        cat = fc.load_or_build(data_root)
        assert len(cat.entities) > 0
        assert fc.cache_path(data_root).is_file()

    def test_second_call_uses_cache(self, data_root: Path):
        # Build once.
        first = fc.load_or_build(data_root)
        # Mutate the cache file's contents to a sentinel — if the second
        # call rebuilds, our sentinel is gone.
        cache = fc.cache_path(data_root)
        sentinel = fc.CatalogIndex(
            entities=[fc.Candidate(
                entity_type="sentinel", name="SENTINEL", source="X",
                file_path="/x", wrapper_key="x",
            )],
            data_root=str(data_root),
            deepest_mtime=first.deepest_mtime,
            built_at=first.built_at,
        )
        cache.write_bytes(pickle.dumps(sentinel))
        loaded = fc.load_or_build(data_root)
        assert any(c.name == "SENTINEL" for c in loaded.entities)

    def test_stale_cache_rebuilds(self, data_root: Path):
        fc.load_or_build(data_root)
        # Bump a JSON file's mtime forward → cache is stale.
        future = time.time() + 3600
        os.utime(data_root / "bestiary" / "bestiary-mm.json", (future, future))
        cat = fc.load_or_build(data_root)
        # Real entities are present (sentinel from prior test isn't here).
        names = {c.name for c in cat.entities}
        assert "Drow" in names

    def test_force_rebuild_ignores_cache(self, data_root: Path):
        first = fc.load_or_build(data_root)
        # Plant a sentinel in the cache.
        cache = fc.cache_path(data_root)
        cache.write_bytes(pickle.dumps(fc.CatalogIndex(
            entities=[fc.Candidate(
                entity_type="sentinel", name="SHOULD_NOT_LOAD", source="X",
                file_path="/x", wrapper_key="x",
            )],
            data_root=str(data_root),
            deepest_mtime=first.deepest_mtime,
        )))
        cat = fc.load_or_build(data_root, force_rebuild=True)
        assert all(c.name != "SHOULD_NOT_LOAD" for c in cat.entities)

    def test_corrupt_cache_falls_back_to_rebuild(self, data_root: Path):
        cache = fc.cache_path(data_root)
        cache.write_bytes(b"not a pickle")
        cat = fc.load_or_build(data_root)
        # Built fresh.
        assert any(c.name == "Drow" for c in cat.entities)


# ── Stats ─────────────────────────────────────────────────────────────────


class TestCountByType:
    def test_counts(self, data_root: Path):
        cat = fc.build_catalog(data_root)
        counts = fc.count_by_type(cat)
        assert counts["monster"] == 3
        assert counts["spell"] == 2
        assert counts["chapter"] == 2  # Prisoners of the Drow + Into Darkness


# ── CLI smoke ─────────────────────────────────────────────────────────────


class TestCli:
    def test_build_then_search(self, data_root: Path, capsys):
        rc = fc.main(["build", str(data_root)])
        assert rc == 0
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["entities"] > 0
        assert payload["data_root"] == str(data_root.resolve())

        rc = fc.main(["search", "drow priestess", "--data-root", str(data_root)])
        assert rc == 0
        captured = capsys.readouterr()
        # Each hit is a JSON line.
        lines = [l for l in captured.out.splitlines() if l.strip()]
        first = json.loads(lines[0])
        assert first["name"] == "Drow Priestess of Lolth"
        assert first["score"] >= 60
