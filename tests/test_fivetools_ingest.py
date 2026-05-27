"""Tests for ``fivetools_ingest.py``.

The ingest pipeline is structured as pure functions + a thin I/O
driver. We test the pure layer exhaustively (entry walk, drawer shape,
statblock routing, idempotence signature) and the I/O driver with a
``FakeMempalaceClient`` so no subprocess is needed.
"""

import json
from pathlib import Path

import pytest

import fivetools_ingest as fti
from mempalace_client import FakeMempalaceClient


# ── Pure helpers ─────────────────────────────────────────────────────────


class TestSanitizeRoomSlug:
    def test_basic_title(self):
        assert fti.sanitize_room_slug("Temple of Elemental Evil") == "temple-of-elemental-evil"

    def test_strips_non_ascii(self):
        assert fti.sanitize_room_slug("Obojima — Tales from the Tall Grass") == (
            "obojima-tales-from-the-tall-grass"
        )

    def test_all_punctuation_yields_fallback(self):
        assert fti.sanitize_room_slug("!!!") == "unknown"
        assert fti.sanitize_room_slug("") == "unknown"
        assert fti.sanitize_room_slug(None) == "unknown"  # type: ignore[arg-type]

    def test_collapses_whitespace_and_symbols(self):
        assert fti.sanitize_room_slug("  A: Lost/Mines of 'Phandelver'  ") == (
            "a-lost-mines-of-phandelver"
        )


class TestWalkEntries:
    def test_depth_first_ordering(self):
        doc = {
            "data": [
                {
                    "type": "section",
                    "name": "Chapter 1",
                    "entries": [
                        {"type": "p", "entry": "Intro prose."},
                        {
                            "type": "entries",
                            "name": "Scene A",
                            "entries": [{"type": "p", "entry": "Scene text."}],
                        },
                    ],
                }
            ]
        }
        names = []
        for top in fti._iter_top_level_entries(doc):
            for node, path in fti._walk_entries(top):
                names.append((node.get("type"), path))
        assert names == [
            ("section", ()),
            ("p", ("Chapter 1",)),
            ("entries", ("Chapter 1",)),
            ("p", ("Chapter 1", "Scene A")),
        ]

    def test_homebrew_shape_routes_through_adventureData(self):
        doc = {
            "adventure": [{"id": "idx"}],
            "adventureData": [
                {"data": [{"type": "section", "name": "Only chapter", "entries": []}]}
            ],
        }
        tops = list(fti._iter_top_level_entries(doc))
        assert len(tops) == 1
        assert tops[0]["name"] == "Only chapter"

    def test_sourcebook_shape_routes_through_bookData(self):
        doc = {
            "book": [{"id": "idx"}],
            "bookData": [
                {"data": [{"type": "section", "name": "Only chapter", "entries": []}]}
            ],
        }
        tops = list(fti._iter_top_level_entries(doc))
        assert len(tops) == 1
        assert tops[0]["name"] == "Only chapter"

    def test_bare_list_document(self):
        doc = [{"type": "p", "entry": "stray prose"}]
        tops = list(fti._iter_top_level_entries(doc))
        assert tops == [{"type": "p", "entry": "stray prose"}]


class TestBuildDrawer:
    def test_prose_entry_goes_to_wing_rpglib(self):
        entry = {"type": "p", "entry": "Some session prose."}
        drawer = fti.build_drawer(
            entry,
            ("Book Title", "Chapter 1"),
            book={"id": 42, "filename": "book.pdf", "tags": ["adventure"]},
            book_room_slug="book-title",
            source_filepath="/mnt/g/book.pdf",
        )
        assert drawer is not None
        assert drawer["wing"] == "wing_rpglib"
        assert drawer["room"] == "room_book-title"
        assert "Some session prose." in drawer["content"]
        assert drawer["metadata"]["entry_type"] == "p"
        assert drawer["metadata"]["section_path"] == "Book Title / Chapter 1"
        assert drawer["metadata"]["book_id"] == 42
        assert drawer["metadata"]["tags"] == "adventure"

    def test_statblock_goes_to_wing_bestiary(self):
        entry = {
            "type": "statblock",
            "tag": "creature",
            "source": "CUSTOM",
            "name": "Bugbear Chieftain",
        }
        drawer = fti.build_drawer(
            entry,
            ("Obojima", "Ch.3"),
            book={"id": 1, "filename": "obojima.pdf", "tags": []},
            book_room_slug="obojima",
            source_filepath="/mnt/g/obojima.pdf",
        )
        assert drawer["wing"] == "wing_bestiary"
        assert drawer["room"] == "room_obojima"
        assert "Bugbear Chieftain" in drawer["content"]
        assert drawer["metadata"]["statblock_name"] == "Bugbear Chieftain"
        assert drawer["metadata"]["statblock_source"] == "CUSTOM"

    def test_empty_container_skipped(self):
        drawer = fti.build_drawer(
            {"type": "entries", "entries": []},
            ("Book",),
            book=None,
            book_room_slug="book",
            source_filepath="x.pdf",
        )
        assert drawer is None

    def test_container_with_prose_children_included(self):
        entry = {
            "type": "inset",
            "name": "Read-aloud",
            "entries": [
                {"type": "p", "entry": "You enter the hall."},
                "A stray string child.",
            ],
        }
        drawer = fti.build_drawer(
            entry,
            ("Book",),
            book=None,
            book_room_slug="book",
            source_filepath="x.pdf",
        )
        assert drawer is not None
        assert drawer["wing"] == "wing_rpglib"
        assert "You enter the hall." in drawer["content"]
        assert "A stray string child." in drawer["content"]

    def test_table_renders_column_labels(self):
        entry = {
            "type": "table",
            "caption": "Encounter Difficulty",
            "colLabels": ["Roll", "Result"],
            "rows": [[1, "Bandits"], [2, "Owlbear"]],
        }
        drawer = fti.build_drawer(
            entry,
            (),
            book=None,
            book_room_slug="book",
            source_filepath="x.pdf",
        )
        assert drawer is not None
        assert "Encounter Difficulty" in drawer["content"]
        assert "Roll" in drawer["content"]


class TestIdempotenceState:
    def test_state_roundtrip(self, tmp_path: Path):
        j = tmp_path / "adv.json"
        j.write_text("{}", encoding="utf-8")
        sig = fti.file_signature(j)
        fti.write_state(j, {"version": 1, "size": sig["size"], "mtime": sig["mtime"]})
        got = fti.read_state(j)
        assert got and got["size"] == sig["size"]

    def test_missing_state_returns_none(self, tmp_path: Path):
        j = tmp_path / "adv.json"
        j.write_text("{}", encoding="utf-8")
        assert fti.read_state(j) is None

    def test_state_keyed_by_palace_and_filter(self, tmp_path: Path):
        # Same JSON ingested into two palaces, or with two filters, must
        # produce independent sidecars — otherwise the second ingest would
        # masquerade as already-done.
        j = tmp_path / "adv.json"
        j.write_text("{}", encoding="utf-8")
        fti.write_state(j, {"version": 2, "tag": "abyss-chap0"}, palace="abyss", filter_key='{"chapter":"0"}')
        fti.write_state(j, {"version": 2, "tag": "abyss-chap1"}, palace="abyss", filter_key='{"chapter":"1"}')
        fti.write_state(j, {"version": 2, "tag": "icespire-chap0"}, palace="icespire", filter_key='{"chapter":"0"}')

        a = fti.read_state(j, palace="abyss", filter_key='{"chapter":"0"}')
        b = fti.read_state(j, palace="abyss", filter_key='{"chapter":"1"}')
        c = fti.read_state(j, palace="icespire", filter_key='{"chapter":"0"}')
        assert a and a["tag"] == "abyss-chap0"
        assert b and b["tag"] == "abyss-chap1"
        assert c and c["tag"] == "icespire-chap0"

        # Wrong (palace, filter) combos return None — no cross-talk.
        assert fti.read_state(j, palace="abyss", filter_key='{"chapter":"2"}') is None
        assert fti.read_state(j, palace="unknown", filter_key='{"chapter":"0"}') is None


# ── End-to-end ingest with fake MCP client ───────────────────────────────


@pytest.fixture
def homebrew_doc(tmp_path: Path) -> Path:
    doc = {
        "_meta": {"title": "Test Adventure"},
        "adventure": [{"id": "idx"}],
        "adventureData": [
            {
                "data": [
                    {
                        "type": "section",
                        "name": "Chapter 1",
                        "entries": [
                            {"type": "p", "entry": "Introductory prose."},
                            {
                                "type": "entries",
                                "name": "Scene: The Gate",
                                "entries": [
                                    {
                                        "type": "p",
                                        "entry": "Two goblins guard the gate.",
                                    },
                                    {
                                        "type": "statblock",
                                        "tag": "creature",
                                        "source": "CUSTOM",
                                        "name": "Goblin Scout",
                                    },
                                ],
                            },
                        ],
                    }
                ]
            }
        ],
    }
    p = tmp_path / "test-adventure.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_ingest_file_emits_expected_drawers(homebrew_doc, tmp_path, monkeypatch):
    fake = FakeMempalaceClient()
    # Route validation through a no-op so the test doesn't require
    # pdf-translators installed on the machine running pytest.
    monkeypatch.setattr(fti, "validate_adventure_json", lambda raw, root, strict=False: [])
    monkeypatch.setattr(fti, "lookup_book", lambda db, book_id=None, filepath=None: None)

    report = fti.ingest_file(
        homebrew_doc,
        palace=None,
        book_id=None,
        rpglib_db=tmp_path / "fake.db",
        pdf_translators=tmp_path / "fake_pdf_translators",
        mp_client=fake,
    )

    assert report["status"] == "ingested"
    wings = {c["arguments"]["wing"] for c in fake.calls}
    rooms = {c["arguments"]["room"] for c in fake.calls}
    assert wings == {"wing_rpglib", "wing_bestiary"}
    # Book title comes from _meta.title; slug the expected result.
    assert rooms == {"room_test-adventure"}
    # Every drawer includes the metadata block as kwargs to add_drawer.
    for c in fake.calls:
        assert "metadata" in c["arguments"]
        assert c["arguments"]["metadata"]["source_filepath"].endswith("test-adventure.pdf") or \
               c["arguments"]["metadata"]["source_filepath"].endswith(str(homebrew_doc))

    # Statblock drawer sits in the bestiary wing and carries statblock_name.
    bestiary_calls = [c for c in fake.calls if c["arguments"]["wing"] == "wing_bestiary"]
    assert len(bestiary_calls) == 1
    assert bestiary_calls[0]["arguments"]["metadata"]["statblock_name"] == "Goblin Scout"


def test_ingest_file_is_idempotent(homebrew_doc, tmp_path, monkeypatch):
    fake = FakeMempalaceClient()
    monkeypatch.setattr(fti, "validate_adventure_json", lambda raw, root, strict=False: [])
    monkeypatch.setattr(fti, "lookup_book", lambda db, book_id=None, filepath=None: None)

    r1 = fti.ingest_file(
        homebrew_doc,
        palace=None,
        book_id=None,
        rpglib_db=tmp_path / "fake.db",
        pdf_translators=tmp_path / "fake_pdf_translators",
        mp_client=fake,
    )
    first_call_count = len(fake.calls)
    assert r1["status"] == "ingested"

    r2 = fti.ingest_file(
        homebrew_doc,
        palace=None,
        book_id=None,
        rpglib_db=tmp_path / "fake.db",
        pdf_translators=tmp_path / "fake_pdf_translators",
        mp_client=fake,
    )
    assert r2["status"] == "unchanged"
    # No new drawers pushed on the second run.
    assert len(fake.calls) == first_call_count


def test_dry_run_does_not_call_client(homebrew_doc, tmp_path, monkeypatch):
    fake = FakeMempalaceClient()
    monkeypatch.setattr(fti, "validate_adventure_json", lambda raw, root, strict=False: [])
    monkeypatch.setattr(fti, "lookup_book", lambda db, book_id=None, filepath=None: None)

    report = fti.ingest_file(
        homebrew_doc,
        palace=None,
        book_id=None,
        rpglib_db=tmp_path / "fake.db",
        pdf_translators=tmp_path / "fake_pdf_translators",
        mp_client=fake,
        dry_run=True,
    )
    assert report["status"] == "dry-run"
    assert report["drawer_count"] > 0
    assert fake.calls == []


# ── Wrapper-key dispatch ─────────────────────────────────────────────────


class TestDetectDocKind:
    def test_adventure_via_data_with_sections(self):
        doc = {"data": [{"type": "section", "name": "Ch1", "entries": []}]}
        assert fti.detect_doc_kind(doc) == "adventure"

    def test_adventure_via_adventureData(self):
        doc = {
            "adventure": [{"id": "i"}],
            "adventureData": [{"data": [{"type": "section", "name": "x", "entries": []}]}],
        }
        assert fti.detect_doc_kind(doc) == "adventure"

    def test_adventure_via_bookData(self):
        doc = {
            "book": [{"id": "i"}],
            "bookData": [{"data": [{"type": "section", "name": "x", "entries": []}]}],
        }
        assert fti.detect_doc_kind(doc) == "adventure"

    def test_catalog_via_monster_key(self):
        doc = {"_meta": {}, "monster": [{"name": "Goblin", "source": "MM"}]}
        assert fti.detect_doc_kind(doc) == "catalog"

    def test_catalog_via_class_key(self):
        doc = {"_meta": {}, "class": [{"name": "Fighter"}],
               "subclass": [{"name": "Champion"}]}
        assert fti.detect_doc_kind(doc) == "catalog"

    def test_unknown_when_nothing_matches(self):
        assert fti.detect_doc_kind({"randomKey": [1, 2, 3]}) == "unknown"


class TestIterCatalogEntities:
    def test_yields_each_entity_with_prop(self):
        doc = {
            "_meta": {},
            "monster": [{"name": "Goblin"}, {"name": "Orc"}],
            "spell": [{"name": "Fireball"}],
        }
        items = list(fti.iter_catalog_entities(doc))
        keys = sorted((p, e["name"]) for p, e in items)
        assert keys == [("monster", "Goblin"), ("monster", "Orc"), ("spell", "Fireball")]

    def test_skips_meta_and_index_keys(self):
        doc = {
            "_meta": {"dependencies": {}},
            "adventure": [{"id": "x"}],  # adventure index, not entities
            "monster": [{"name": "G"}],
        }
        items = list(fti.iter_catalog_entities(doc))
        assert items == [("monster", {"name": "G"})]

    def test_skips_item_property_internal_keys(self):
        doc = {
            "_meta": {}, "item": [{"name": "Bag"}],
            "itemProperty": [{"abbreviation": "F"}],  # internal table; not ingested
        }
        items = list(fti.iter_catalog_entities(doc))
        assert items == [("item", {"name": "Bag"})]


class TestWingForWrapperKey:
    def test_known_keys(self):
        assert fti.wing_for_wrapper_key("monster") == "wing_bestiary"
        assert fti.wing_for_wrapper_key("spell") == "wing_spells"
        assert fti.wing_for_wrapper_key("class") == "wing_classes"
        assert fti.wing_for_wrapper_key("race") == "wing_lore"
        assert fti.wing_for_wrapper_key("variantrule") == "wing_rules"

    def test_fluff_routes_to_lore(self):
        assert fti.wing_for_wrapper_key("monsterFluff") == "wing_lore"
        assert fti.wing_for_wrapper_key("spellFluff") == "wing_lore"


class TestBuildDrawerCatalog:
    def test_monster_drawer_full_metadata(self):
        m = {
            "name": "Goblin", "source": "MM", "page": 166,
            "size": ["S"], "type": "humanoid", "alignment": ["N", "E"],
            "ac": [{"ac": 15}], "hp": {"average": 7, "formula": "2d6"},
            "speed": {"walk": 30},
            "str": 8, "dex": 14, "con": 10, "int": 10, "wis": 8, "cha": 8,
            "cr": "1/4",
            "action": [{"name": "Scimitar", "entries": ["+4 to hit"]}],
        }
        drawer = fti.build_drawer_catalog(
            "monster", m, book=None, room_slug="dnd5e", source_filepath="/x/bestiary-mm.json",
        )
        assert drawer["wing"] == "wing_bestiary"
        assert drawer["room"] == "room_dnd5e"
        md = drawer["metadata"]
        assert md["wrapper_key"] == "monster"
        assert md["entity_name"] == "Goblin"
        assert md["entity_source"] == "MM"
        assert md["page"] == 166
        assert md["cr"] == "1/4"
        assert md["creature_type"] == "humanoid"
        assert md["size"] == "S"
        assert md["statblock_name"] == "Goblin"
        assert "# Goblin" in drawer["content"]
        assert "**Armor Class** 15" in drawer["content"]
        assert "## Actions" in drawer["content"]

    def test_spell_drawer_facets(self):
        s = {
            "name": "Mage Hand", "source": "PHB", "level": 0, "school": "T",
            "time": [{"number": 1, "unit": "action"}],
            "range": {"type": "point", "distance": {"type": "feet", "amount": 30}},
            "components": {"v": True, "s": True},
            "duration": [{"type": "timed", "duration": {"number": 1, "type": "minute"}}],
            "entries": ["A spectral hand appears."],
        }
        d = fti.build_drawer_catalog(
            "spell", s, book=None, room_slug="dnd5e", source_filepath="/x/spells.json",
        )
        assert d["wing"] == "wing_spells"
        assert d["metadata"]["spell_level"] == 0
        assert d["metadata"]["spell_school"] == "T"

    def test_unnamed_entity_returns_none(self):
        d = fti.build_drawer_catalog(
            "monster", {"source": "MM"}, book=None, room_slug="x", source_filepath="/x",
        )
        assert d is None


class TestParseFilterSpec:
    def test_empty(self):
        assert fti.parse_filter_spec(None) == {}
        assert fti.parse_filter_spec("") == {}

    def test_single_pair(self):
        assert fti.parse_filter_spec("name=Drow") == {"name": "Drow"}

    def test_multiple_pairs_strip_whitespace(self):
        assert fti.parse_filter_spec("name=Drow,source=MM") == {"name": "Drow", "source": "MM"}
        assert fti.parse_filter_spec(" name = Drow , source = MM ") == {"name": "Drow", "source": "MM"}

    def test_missing_equals_raises(self):
        with pytest.raises(ValueError):
            fti.parse_filter_spec("name")


class TestMatchesFilter:
    def test_no_filters_passes_all(self):
        assert fti.matches_filter({"name": "X"}, {})

    def test_exact_match_case_insensitive(self):
        assert fti.matches_filter({"name": "drow"}, {"name": "Drow"})
        assert fti.matches_filter({"name": "Drow"}, {"name": "drow"})

    def test_and_semantics_all_must_match(self):
        assert fti.matches_filter({"name": "X", "source": "MM"}, {"name": "X", "source": "MM"})
        assert not fti.matches_filter({"name": "X", "source": "MM"}, {"name": "X", "source": "PHB"})


class TestAdventureChapterFilter:
    """`--filter chapter=N` selects one top-level adventure chapter."""

    def _adventure_doc(self) -> dict:
        return {
            "_meta": {"sources": [{"json": "TST", "abbreviation": "TST"}]},
            "data": [
                {"type": "section", "name": "Chapter Zero",
                 "entries": [{"type": "p", "entry": "Prose 0"}]},
                {"type": "section", "name": "Chapter One",
                 "entries": [{"type": "p", "entry": "Prose 1"}]},
                {"type": "section", "name": "Chapter Two",
                 "entries": [{"type": "p", "entry": "Prose 2"}]},
            ],
        }

    def _chapter_names_in(self, drawers: list[dict]) -> set[str]:
        """Pull section-path top-level names out of the drawers' metadata."""
        names: set[str] = set()
        for d in drawers:
            sp = (d.get("metadata") or {}).get("section_path") or ""
            if sp:
                names.add(sp.split(" / ")[0])
        return names

    def test_no_filter_walks_all_chapters(self):
        drawers = fti.build_drawers_from_json(
            self._adventure_doc(),
            book=None, book_room_slug="r", source_filepath="/x.json",
        )
        # Each chapter contributes a "section" drawer + a "p" prose drawer.
        types = sorted(d.get("metadata", {}).get("entry_type")
                       for d in drawers
                       if d.get("metadata", {}).get("entry_type") in {"section", "p"})
        assert types.count("section") == 3
        assert types.count("p") == 3
        # Three different chapters represented in section paths.
        assert self._chapter_names_in(drawers) == {
            "Chapter Zero", "Chapter One", "Chapter Two",
        }

    def test_chapter_zero_filter_keeps_only_chapter_zero(self):
        drawers = fti.build_drawers_from_json(
            self._adventure_doc(),
            book=None, book_room_slug="r", source_filepath="/x.json",
            filters={"chapter": "0"},
        )
        # Only Chapter Zero's section + its child prose should remain.
        types = sorted(d.get("metadata", {}).get("entry_type")
                       for d in drawers
                       if d.get("metadata", {}).get("entry_type") in {"section", "p"})
        assert types == ["p", "section"]
        assert self._chapter_names_in(drawers) == {"Chapter Zero"}

    def test_chapter_one_filter_keeps_only_chapter_one(self):
        drawers = fti.build_drawers_from_json(
            self._adventure_doc(),
            book=None, book_room_slug="r", source_filepath="/x.json",
            filters={"chapter": "1"},
        )
        assert self._chapter_names_in(drawers) == {"Chapter One"}

    def test_non_integer_chapter_raises(self):
        with pytest.raises(ValueError):
            fti.build_drawers_from_json(
                self._adventure_doc(),
                book=None, book_room_slug="r", source_filepath="/x.json",
                filters={"chapter": "first"},
            )

    def test_unsupported_filter_key_warns_but_proceeds(self, caplog):
        caplog.set_level("WARNING")
        drawers = fti.build_drawers_from_json(
            self._adventure_doc(),
            book=None, book_room_slug="r", source_filepath="/x.json",
            filters={"name": "Velkynvelve"},
        )
        # All chapters still walked (unknown key ignored).
        assert self._chapter_names_in(drawers) == {
            "Chapter Zero", "Chapter One", "Chapter Two",
        }
        # Warning logged.
        assert any("ignored for adventure-shape" in r.getMessage()
                   for r in caplog.records)


@pytest.fixture
def catalog_doc(tmp_path: Path) -> Path:
    """A minimal catalog-shaped JSON: 2 monsters + 1 spell."""
    doc = {
        "_meta": {},
        "monster": [
            {
                "name": "Goblin", "source": "MM", "page": 166,
                "size": ["S"], "type": "humanoid", "alignment": ["N", "E"],
                "ac": [{"ac": 15}], "hp": {"average": 7, "formula": "2d6"},
                "speed": {"walk": 30},
                "str": 8, "dex": 14, "con": 10, "int": 10, "wis": 8, "cha": 8,
                "cr": "1/4",
                "action": [{"name": "Scimitar", "entries": ["+4 to hit"]}],
            },
            {
                "name": "Orc", "source": "MM", "page": 246,
                "size": ["M"], "type": "humanoid", "alignment": ["C", "E"],
                "ac": [{"ac": 13}], "hp": {"average": 15, "formula": "2d8"},
                "speed": {"walk": 30},
                "str": 16, "dex": 12, "con": 16, "int": 7, "wis": 11, "cha": 10,
                "cr": "1/2",
                "action": [{"name": "Greataxe", "entries": ["+5 to hit"]}],
            },
        ],
        "spell": [
            {
                "name": "Mage Hand", "source": "PHB",
                "level": 0, "school": "T",
                "time": [{"number": 1, "unit": "action"}],
                "range": {"type": "point", "distance": {"type": "feet", "amount": 30}},
                "components": {"v": True, "s": True},
                "duration": [{"type": "timed", "duration": {"number": 1, "type": "minute"}}],
                "entries": ["A spectral hand appears."],
            }
        ],
    }
    p = tmp_path / "bestiary-mini.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_catalog_ingest_routes_to_correct_wings(catalog_doc, tmp_path, monkeypatch):
    fake = FakeMempalaceClient()
    monkeypatch.setattr(fti, "lookup_book", lambda db, book_id=None, filepath=None: None)
    report = fti.ingest_file(
        catalog_doc, palace=None, book_id=None,
        rpglib_db=tmp_path / "fake.db",
        pdf_translators=tmp_path / "fake_pdf",
        mp_client=fake,
    )
    assert report["status"] == "ingested"
    assert report["kind"] == "catalog"
    wings = sorted(c["arguments"]["wing"] for c in fake.calls)
    assert wings == ["wing_bestiary", "wing_bestiary", "wing_spells"]
    # All drawers go to the same room (book_room_slug is the JSON stem when
    # there's no rpglib book).
    rooms = {c["arguments"]["room"] for c in fake.calls}
    assert rooms == {"room_bestiary-mini"}


def test_catalog_filter_drops_non_matching(catalog_doc, tmp_path, monkeypatch):
    fake = FakeMempalaceClient()
    monkeypatch.setattr(fti, "lookup_book", lambda db, book_id=None, filepath=None: None)
    report = fti.ingest_file(
        catalog_doc, palace=None, book_id=None,
        rpglib_db=tmp_path / "fake.db",
        pdf_translators=tmp_path / "fake_pdf",
        mp_client=fake,
        filters={"name": "Goblin"},
    )
    assert report["drawer_count"] == 1
    assert len(fake.calls) == 1
    assert fake.calls[0]["arguments"]["metadata"]["entity_name"] == "Goblin"


def test_catalog_full_statblock_in_content(catalog_doc, tmp_path, monkeypatch):
    """The headline Step-1 fix: catalog-shaped statblocks are no longer
    skeletal name-only blobs."""
    fake = FakeMempalaceClient()
    monkeypatch.setattr(fti, "lookup_book", lambda db, book_id=None, filepath=None: None)
    fti.ingest_file(
        catalog_doc, palace=None, book_id=None,
        rpglib_db=tmp_path / "fake.db",
        pdf_translators=tmp_path / "fake_pdf",
        mp_client=fake,
        filters={"name": "Goblin"},
    )
    content = fake.calls[0]["arguments"]["content"]
    assert "# Goblin" in content
    assert "**Armor Class** 15" in content
    assert "**Hit Points** 7" in content
    assert "## Actions" in content
    assert "**Scimitar.**" in content


def test_catalog_filter_changes_idempotence_key(catalog_doc, tmp_path, monkeypatch):
    """Different --filter on the same file must NOT be treated as a no-op."""
    fake = FakeMempalaceClient()
    monkeypatch.setattr(fti, "lookup_book", lambda db, book_id=None, filepath=None: None)

    fti.ingest_file(
        catalog_doc, palace=None, book_id=None,
        rpglib_db=tmp_path / "fake.db",
        pdf_translators=tmp_path / "fake_pdf",
        mp_client=fake,
        filters={"name": "Goblin"},
    )
    n_first = len(fake.calls)

    # Different filter → must still ingest, not return "unchanged".
    r2 = fti.ingest_file(
        catalog_doc, palace=None, book_id=None,
        rpglib_db=tmp_path / "fake.db",
        pdf_translators=tmp_path / "fake_pdf",
        mp_client=fake,
        filters={"name": "Orc"},
    )
    assert r2["status"] == "ingested"
    assert len(fake.calls) == n_first + 1


def test_catalog_validator_does_not_invoke_pdf_translators(catalog_doc, tmp_path, monkeypatch):
    """Catalog shapes shouldn't even try to load adventure_model — it only
    knows the adventure schema. Regression: previously this raised."""
    fake = FakeMempalaceClient()
    monkeypatch.setattr(fti, "lookup_book", lambda db, book_id=None, filepath=None: None)
    called = []

    def _boom(*args, **kwargs):
        called.append(args)
        raise RuntimeError("adventure_model should not be loaded for catalog files")

    monkeypatch.setattr(fti, "validate_adventure_json", _boom)
    fti.ingest_file(
        catalog_doc, palace=None, book_id=None,
        rpglib_db=tmp_path / "fake.db",
        pdf_translators=tmp_path / "fake_pdf",
        mp_client=fake,
    )
    assert called == []  # never invoked for catalog shape


# ── Existing rpglib metadata test (unchanged) ────────────────────────────


def test_ingest_uses_rpglib_metadata(homebrew_doc, tmp_path, monkeypatch):
    fake = FakeMempalaceClient()
    stub_book = {
        "id": 999,
        "filename": "obojima.pdf",
        "publisher": "Paizo",
        "game_system": "D&D 5e",
        "product_type": "adventure",
        "series": "Obojima",
        "tags": ["asian-fantasy", "island"],
        "pdf_title": "Obojima — Tales from the Tall Grass",
    }
    monkeypatch.setattr(fti, "validate_adventure_json", lambda raw, root, strict=False: [])
    monkeypatch.setattr(
        fti, "lookup_book", lambda db, book_id=None, filepath=None: stub_book
    )

    report = fti.ingest_file(
        homebrew_doc,
        palace=None,
        book_id=999,
        rpglib_db=tmp_path / "fake.db",
        pdf_translators=tmp_path / "fake_pdf_translators",
        mp_client=fake,
    )
    assert report["book_id"] == 999
    assert report["book_room_slug"] == "obojima-tales-from-the-tall-grass"
    # Every drawer metadata carries the rpglib lookup snapshot.
    for c in fake.calls:
        md = c["arguments"]["metadata"]
        assert md["book_id"] == 999
        assert md["game_system"] == "D&D 5e"
        assert md["tags"] == "asian-fantasy;island"
