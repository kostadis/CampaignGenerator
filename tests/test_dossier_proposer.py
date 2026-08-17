"""Tests for dossier_proposer.

The proposer has three deterministic layers:
  * classify() — keyword heuristics for slot assignment
  * build_candidate() / group_candidates() — shape a hit into a Candidate
  * render() — turn a Proposal into reviewable markdown

Plus the propose() orchestrator, which we cover with an injected
retriever stub so the test never spawns mempalace-mcp.
"""

from __future__ import annotations

from pathlib import Path

import pipelines.rlm.dossier_proposer as dp
import pipelines.rlm.resolve_refs as resolve_refs


# ── classify() ───────────────────────────────────────────────────────────


class TestClassify:
    def test_cheap_candidate_classifies_as_ingest_cheap(self):
        hit = {"kind": "candidate", "cost": "cheap", "drawer_text": "whatever"}
        assert dp.classify(hit) == "ingest_cheap"

    def test_expensive_candidate_classifies_as_ingest_expensive(self):
        hit = {"kind": "candidate", "cost": "expensive", "drawer_text": "whatever"}
        assert dp.classify(hit) == "ingest_expensive"

    def test_statblock_kind_wins(self):
        hit = {"kind": "statblock", "drawer_text": "# Dragon\ntag: creature"}
        assert dp.classify(hit) == "statblock"

    def test_location_via_entry_type_and_keyword(self):
        hit = {
            "kind": "drawer",
            "entry_type": "section",
            "drawer_text": "The ancient temple sits on the hill above the harbor.",
            "section_path": "Book / Ch.1 / The Temple",
        }
        assert dp.classify(hit) == "location"

    def test_encounter_via_combat_verb(self):
        hit = {
            "kind": "drawer",
            "entry_type": "entries",
            "drawer_text": "Three bandits ambush the party at the narrow pass.",
        }
        assert dp.classify(hit) == "encounter"

    def test_npc_via_hint_word(self):
        hit = {
            "kind": "drawer",
            "entry_type": "entries",
            "drawer_text": "Harbin Wester, the nervous townmaster, hands the party a list of chores.",
        }
        assert dp.classify(hit) == "npc"

    def test_lore_fallback(self):
        hit = {
            "kind": "drawer",
            "entry_type": "entries",
            "drawer_text": "The moon rides high over the sea every third winter.",
        }
        assert dp.classify(hit) == "lore"


# ── Named-entity extraction ──────────────────────────────────────────────


class TestNamedEntities:
    def test_two_word_names(self):
        text = "Harbin Wester met with Grundar Quartzvein at the mine."
        names = dp._extract_named_entities(text)
        assert "Harbin Wester" in names
        assert "Grundar Quartzvein" in names

    def test_skips_sentence_starters(self):
        text = "The bandits ambushed. Then they fled."
        names = dp._extract_named_entities(text)
        assert "The bandits" not in names
        assert "Then they" not in names

    def test_cap_limits_results(self):
        text = "Alice Brown. Bob Green. Carol Blue. Dave Red. Eve Pink. Frank Grey."
        names = dp._extract_named_entities(text, max_results=3)
        assert len(names) == 3


# ── build_candidate / group_candidates ───────────────────────────────────


class TestBuildCandidate:
    def test_drawer_hit_basic(self):
        hit = {
            "kind": "drawer",
            "drawer_id": "d1",
            "wing": "wing_rpglib",
            "room": "room_book",
            "drawer_text": "Prose about the temple hold.",
            "entry_type": "section",
            "section_path": "Book / Ch.1 / The Temple Hold",
            "similarity": 0.84,
            "book_id": 42,
            "title": "Book Title",
            "page": 7,
        }
        c = dp.build_candidate(hit)
        assert c.slot == "location"
        assert c.drawer_id == "d1"
        assert c.book_id == 42
        assert c.book_title == "Book Title"
        assert c.page == 7
        assert c.excerpt.startswith("Prose about")

    def test_expensive_candidate_carries_conversion_hint(self):
        hit = {
            "kind": "candidate",
            "cost": "expensive",
            "book_id": 9,
            "title": "Something",
            "convert_command": ["py", "pdf_to_5etools_v2.py", "/x.pdf"],
            "ingest_command": ["py", "fivetools_ingest.py", "/x.json"],
            "estimated_cost_tokens": 10000,
            "estimated_cost_usd_min": 0.01,
            "estimated_cost_usd_max": 0.03,
            "notes": ["bestiary flag"],
        }
        c = dp.build_candidate(hit)
        assert c.slot == "ingest_expensive"
        assert c.conversion_hint["cost"] == "expensive"
        assert c.conversion_hint["convert_command"][0] == "py"
        assert c.conversion_hint["estimated_cost_tokens"] == 10000
        assert c.conversion_hint["notes"] == ["bestiary flag"]

    def test_cheap_candidate_carries_ingest_hint(self):
        hit = {
            "kind": "candidate",
            "cost": "cheap",
            "name": "Drow Priestess of Lolth",
            "entity_type": "monster",
            "source": "MM",
            "file_path": "/d/bestiary-mm.json",
            "ingest_command": ["py", "fivetools_ingest.py",
                               "/d/bestiary-mm.json", "--filter",
                               "name=Drow Priestess of Lolth,source=MM"],
        }
        c = dp.build_candidate(hit)
        assert c.slot == "ingest_cheap"
        assert c.conversion_hint["cost"] == "cheap"
        assert c.conversion_hint["file_path"] == "/d/bestiary-mm.json"
        assert "--filter" in c.conversion_hint["ingest_command"]

    def test_group_candidates_fills_all_slots(self):
        hits = [
            {"kind": "drawer", "entry_type": "section",
             "drawer_text": "The old keep stands on the hill."},
            {"kind": "drawer", "entry_type": "entries",
             "drawer_text": "Goblins ambush the wagon on the road."},
            {"kind": "drawer", "entry_type": "entries",
             "drawer_text": "Harbin Wester is the townmaster."},
            {"kind": "drawer", "entry_type": "entries",
             "drawer_text": "Generic lore about the stars."},
            {"kind": "statblock", "drawer_text": "# Dragon\ntag: creature",
             "statblock_name": "Dragon"},
            {"kind": "candidate", "cost": "expensive", "book_id": 1, "title": "P",
             "convert_command": [], "ingest_command": []},
            {"kind": "candidate", "cost": "cheap",
             "name": "Goblin", "entity_type": "monster", "source": "MM",
             "file_path": "/d/m.json", "ingest_command": []},
        ]
        slots = dp.group_candidates(hits)
        assert len(slots["location"]) == 1
        assert len(slots["encounter"]) == 1
        assert len(slots["npc"]) == 1
        assert len(slots["lore"]) == 1
        assert len(slots["statblock"]) == 1
        assert len(slots["ingest_expensive"]) == 1
        assert len(slots["ingest_cheap"]) == 1


# ── render() ─────────────────────────────────────────────────────────────


class TestRender:
    def test_header_and_empty_slots_note(self):
        proposal = dp.Proposal(
            query="Test query",
            campaign_dir="/fake",
            palace=None,
            rpglib_db=None,
            generated_at="2026-01-01T00:00:00",
            slots={k: [] for k in ("npc", "location", "encounter", "statblock", "lore", "ingest_cheap", "ingest_expensive")},
            raw_hit_count=0,
            fallback=False,
            fallback_reason=None,
        )
        md = dp.render(proposal)
        assert md.startswith("# Dossier Proposal — Test query")
        assert "> **Status:** candidates only" in md
        assert "_Empty slots:" in md

    def test_candidate_excerpt_and_citation(self):
        c = dp.Candidate(
            slot="location",
            label="Icespire Hold",
            excerpt="A windswept keep above the pass.",
            drawer_id="d1",
            kind="drawer",
            book_title="Dragon of Icespire Peak",
            section_path="Book / Ch.3 / Icespire Hold",
            page=42,
            similarity=0.81,
        )
        proposal = dp.Proposal(
            query="q",
            campaign_dir="/x",
            palace=None,
            rpglib_db=None,
            generated_at="t",
            slots={
                "npc": [], "location": [c], "encounter": [], "statblock": [],
                "lore": [], "ingest_cheap": [], "ingest_expensive": [],
            },
            raw_hit_count=1,
            fallback=False,
            fallback_reason=None,
        )
        md = dp.render(proposal)
        assert "### 1. Icespire Hold" in md
        assert "`d1`" in md
        assert "page**: 42" in md
        assert "> A windswept keep above the pass." in md

    def test_expensive_candidate_renders_commands(self):
        c = dp.Candidate(
            slot="ingest_expensive",
            label="Some Book",
            excerpt="",
            kind="candidate",
            book_id=99,
            conversion_hint={
                "cost": "expensive",
                "convert_command": ["python3", "pdf_to_5etools_v2.py", "/mnt/g/x.pdf"],
                "ingest_command": ["python3", "fivetools_ingest.py", "/mnt/g/x.json"],
                "estimated_cost_tokens": 12345,
                "estimated_cost_usd_min": 0.01,
                "estimated_cost_usd_max": 0.04,
                "notes": [],
            },
        )
        proposal = dp.Proposal(
            query="q",
            campaign_dir="/x",
            palace=None,
            rpglib_db=None,
            generated_at="t",
            slots={
                "npc": [], "location": [], "encounter": [], "statblock": [],
                "lore": [], "ingest_cheap": [], "ingest_expensive": [c],
            },
            raw_hit_count=0,
            fallback=False,
            fallback_reason=None,
        )
        md = dp.render(proposal)
        assert "pdf_to_5etools_v2.py /mnt/g/x.pdf" in md
        assert "fivetools_ingest.py /mnt/g/x.json" in md
        assert "~12,345 tokens" in md

    def test_cheap_candidate_renders_ingest_command(self):
        c = dp.Candidate(
            slot="ingest_cheap",
            label="Drow Priestess of Lolth",
            excerpt="",
            kind="candidate",
            conversion_hint={
                "cost": "cheap",
                "ingest_command": ["py", "fivetools_ingest.py",
                                   "/d/bestiary-mm.json", "--filter",
                                   "name=Drow Priestess of Lolth,source=MM"],
                "file_path": "/d/bestiary-mm.json",
                "entity_type": "monster",
                "name": "Drow Priestess of Lolth",
                "source": "MM",
                "notes": [],
            },
        )
        proposal = dp.Proposal(
            query="q", campaign_dir="/x", palace=None, rpglib_db=None,
            generated_at="t",
            slots={"npc": [], "location": [], "encounter": [], "statblock": [],
                   "lore": [], "ingest_cheap": [c], "ingest_expensive": []},
            raw_hit_count=0, fallback=False, fallback_reason=None,
        )
        md = dp.render(proposal)
        assert "fivetools_ingest.py /d/bestiary-mm.json" in md
        assert "name=Drow Priestess of Lolth" in md
        assert "cheap ingest" in md


# ── is_approved() ────────────────────────────────────────────────────────


class TestIsApproved:
    def test_default_banner_unapproved(self):
        md = "# X\n\n> **Status:** candidates only. Review…"
        assert dp.is_approved(md) is False

    def test_edited_banner_approved(self):
        md = "# X\n\n> **Status:** approved by Kostadis on 2026-04-24."
        assert dp.is_approved(md) is True

    def test_missing_banner_unapproved(self):
        md = "# X\n\nno status here"
        assert dp.is_approved(md) is False

    def test_empty_string_unapproved(self):
        assert dp.is_approved("") is False
        assert dp.is_approved(None) is False  # type: ignore[arg-type]


# ── propose() with stub retriever ────────────────────────────────────────


def _stub_retriever(hits, *, fallback=False, fallback_reason=None):
    def _inner(query, **kwargs):
        return {
            "query": query,
            "hits": list(hits),
            "path": {"wings": [], "rooms": []},
            "total_before_filter": len(hits),
            "fallback": fallback,
            "fallback_reason": fallback_reason,
        }
    return _inner


def test_propose_bundles_slots_and_metadata(tmp_path):
    hits = [
        {"kind": "statblock", "drawer_text": "# Dragon", "statblock_name": "Dragon"},
        {"kind": "drawer", "entry_type": "section",
         "drawer_text": "The icy keep towers above the bay."},
        {"kind": "candidate", "cost": "expensive", "book_id": 77, "title": "Unconverted",
         "convert_command": ["x"], "ingest_command": ["y"]},
    ]
    proposal = dp.propose(
        "test query",
        campaign_dir=tmp_path,
        palace="/fake/palace",
        retriever=_stub_retriever(hits),
    )
    assert proposal.query == "test query"
    assert proposal.raw_hit_count == 3
    assert len(proposal.slots["statblock"]) == 1
    assert len(proposal.slots["location"]) == 1
    assert len(proposal.slots["ingest_expensive"]) == 1


def test_propose_handles_empty_retriever(tmp_path):
    proposal = dp.propose(
        "empty",
        campaign_dir=tmp_path,
        retriever=_stub_retriever([], fallback=True, fallback_reason="indices empty"),
    )
    assert proposal.raw_hit_count == 0
    assert proposal.fallback is True
    assert proposal.fallback_reason == "indices empty"
    assert all(len(v) == 0 for v in proposal.slots.values())


def test_write_proposal_creates_parents(tmp_path):
    out = tmp_path / "a" / "b" / "dossier_proposal.md"
    p = dp.write_proposal("# hi", out)
    assert p.read_text() == "# hi"
    assert p.parent.is_dir()


# ── propose() scope kwarg (issue #114 step 4) ──────────────────────────────
#
# `propose()` threads `scope` into `retriever_kwargs` CONDITIONALLY — only
# when the caller actually passes one — mirroring the existing
# `rpg_library_url`/`fivetools_data_root` pattern already in the function
# body. This matters because the default `retriever=retrieve` does not
# accept a `scope` kwarg by design (retrieve()'s signature is untouched by
# step 3), so a caller that omits `scope` must never leak a `scope=None`
# kwarg to a retriever that doesn't expect one.


def _capturing_retriever(captured: dict):
    def _inner(query, **kwargs):
        captured["query"] = query
        captured.update(kwargs)
        return {
            "query": query,
            "hits": [],
            "path": {"wings": [], "rooms": []},
            "total_before_filter": 0,
            "fallback": False,
            "fallback_reason": None,
        }
    return _inner


def _fake_scope() -> resolve_refs.ResolvedScope:
    return resolve_refs.ResolvedScope(
        canonical_mode="whitelist",
        canonical_sources=["MM"],
        canonical_excluded=[],
        refs=[],
        roots={},
        refs_path=Path("/tmp/refs.yaml"),
        local_path=None,
    )


def test_propose_threads_scope_into_retriever_kwargs_when_given(tmp_path):
    captured: dict = {}
    scope = _fake_scope()
    dp.propose(
        "test query",
        campaign_dir=tmp_path,
        scope=scope,
        retriever=_capturing_retriever(captured),
    )
    assert captured.get("scope") is scope


def test_propose_omits_scope_kwarg_when_not_given(tmp_path):
    # The default `retriever=retrieve`-protecting case: no scope passed at
    # all -> the retriever never receives a `scope` key, not even
    # `scope=None`. Confirms the conditional guard, not just that a value
    # round-trips.
    captured: dict = {}
    dp.propose(
        "test query",
        campaign_dir=tmp_path,
        retriever=_capturing_retriever(captured),
    )
    assert "scope" not in captured


def test_stub_retriever_tolerates_scope_kwarg(tmp_path):
    # Confirms the existing _stub_retriever fake (used throughout this
    # file's `propose()` coverage) would not break if a caller passed
    # `scope` — its inner function is `def _inner(query, **kwargs)`, so it
    # already tolerates an unexpected `scope` kwarg without asserting on
    # an exact received-kwargs set. This is what makes the conditional
    # design in propose() safe for this file's existing tests.
    proposal = dp.propose(
        "test query",
        campaign_dir=tmp_path,
        scope=_fake_scope(),
        retriever=_stub_retriever([]),
    )
    assert proposal.raw_hit_count == 0
