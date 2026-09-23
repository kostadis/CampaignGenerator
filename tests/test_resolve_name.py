"""Tests for entity_registry/resolve.py — read-only canon-chain resolution.

Covers the five tiers and their precedence, the three statuses, and the three
hazards the design doc records from the live Out-of-the-Abyss corpus:

  1. the glossary's overloaded parenthetical (alias vs provenance note, same
     syntax) must come back raw and unclassified;
  2. a tier-1/tier-2 length difference ("Thorin Giantfriend" vs "Thorin") is
     NOT a conflict;
  3. a dossier's filename is never evidence.

Plus the two structural guarantees the whole design rests on: `ambiguous`
emits no `canonical` key at all, and nothing in this module writes.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from entity_registry import registry, resolve  # noqa: E402


# ── fixtures ────────────────────────────────────────────────────────────────

GLOSSARY = """# VTT transcription corrections

## PCs

| Wrong | Right |
|---|---|
| Grygum, Graham, Gurrigam | **Gyrgum** |
| Thorne, Thornton | **Thorin** |

## NPCs and creatures

| Wrong | Right |
|---|---|
| Ebum Mir, Ebonir | **Ebonmire** (Princess Ebonmire) |
| Zuggtomy, Zugtmoy | **Zuggtmoy** (confirmed via 5etools: MTF + OotA) |
| Jam Jar, Jim Jar | **Jimjar** |
"""

KNOWN_ADDITIONS = """# VTT spell-pass known additions

## Earlier rulings

- **Overbright** — Underdark slang for the surface world — 2026-05-04
- **First Reader** — Candlekeep title — 2026-05-02
"""


def _campaign(tmp_path, *, glossary=GLOSSARY, known=KNOWN_ADDITIONS,
              party=("Thorin Giantfriend", "Gyrgum"), registry_entities=True):
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "notes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    chars = "\n".join(f"- name: {n}" for n in party)
    (tmp_path / "config" / "party.yaml").write_text(
        f"characters:\n{chars}\n", encoding="utf-8")
    if glossary is not None:
        (tmp_path / "notes" / "vtt_transcription_corrections.md").write_text(
            glossary, encoding="utf-8")
    if known is not None:
        (tmp_path / "notes" / "vtt_known_additions.md").write_text(
            known, encoding="utf-8")
    if registry_entities:
        assert registry.main(["init", str(tmp_path)]) == 0
        assert registry.main([
            "add", str(tmp_path), "--name", "Ilvara Mizzrym", "--type", "npc",
            "--aliases", "Elvara", "Olvara", "--yes",
        ]) == 0
    return tmp_path


def _dossier(campaign, filename, body):
    d = campaign / "docs" / "npcs"
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(body, encoding="utf-8")


# ── tier 1: party.yaml ──────────────────────────────────────────────────────

def test_pc_name_resolves_from_party_yaml(tmp_path):
    c = _campaign(tmp_path)
    r = resolve.resolve_name(c, "Thorin Giantfriend")
    assert r["status"] == "resolved"
    assert r["tier"] == 1
    assert r["canonical"] == "Thorin Giantfriend"
    assert r["is_change"] is False
    assert r["entity_type"] == "pc"


def test_party_yaml_wins_over_glossary_for_a_pc(tmp_path):
    """Chain order is the authority: tier 1 is consulted first, full stop."""
    c = _campaign(tmp_path)
    r = resolve.resolve_name(c, "Gyrgum")
    assert r["tier"] == 1


# ── hazard 2: length difference is not a conflict ───────────────────────────

def test_short_pc_form_is_compatible_not_ambiguous(tmp_path):
    """party.yaml says "Thorin Giantfriend"; the glossary rules on "Thorin".

    That is one name at two lengths, not a disagreement. Reporting it as
    ambiguous on every PC name would train the GM to dismiss the status.
    """
    c = _campaign(tmp_path)
    r = resolve.resolve_name(c, "Thorin")
    assert r["status"] == "resolved"
    assert r["is_change"] is False, "a surname is not a name change"
    assert r["conflicts"] == []


def test_compatible_is_prefix_not_substring():
    assert resolve.compatible("Thorin", "Thorin Giantfriend", allow_prefix=True)
    assert resolve.compatible("Thorin Giantfriend", "Thorin", allow_prefix=True)
    assert resolve.compatible("Ilvara", "ilvara!")
    assert not resolve.compatible("Giantfriend", "Thorin Giantfriend", allow_prefix=True)
    assert not resolve.compatible("Sequoia", "Sequioa")


def test_prefix_matching_is_off_by_default():
    """Found on the live corpus: with prefix matching everywhere, "Night"
    matched the tavern "The Night Beneath the Night", "Does" matched the
    garbling "Does Bookworm", and "Brother" matched both "Brother Vareth" and
    "Brother Kel" and came back ambiguous. A bare title or common word is not a
    short form of every name beginning with it, so only tier 1 — where
    party.yaml's full names meet the corpus's short ones — gets the tolerance.
    """
    assert not resolve.compatible("Night", "The Night Beneath the Night")
    assert not resolve.compatible("Does", "Does Bookworm")
    assert not resolve.compatible("Brother", "Brother Vareth")
    assert resolve.compatible("Night", "The Night Beneath the Night", allow_prefix=True)


def test_possessive_is_not_a_spelling_difference():
    """"Daz's" against party.yaml's "Daz" was coming back ambiguous, on every
    possessive in the transcript."""
    assert resolve.compatible("Daz's", "Daz")
    assert resolve.compatible("Daz", "Daz's")
    assert resolve.compatible("Glabbagool\u2019s", "Glabbagool")
    assert not resolve.compatible("Dazes", "Daz")


# ── tier 2: the glossary ────────────────────────────────────────────────────

def test_misspelling_resolves_and_flags_the_change(tmp_path):
    c = _campaign(tmp_path)
    r = resolve.resolve_name(c, "Gurrigam")
    assert r["status"] == "resolved"
    assert r["canonical"] == "Gyrgum"
    assert r["tier"] == 2
    assert r["is_change"] is True
    assert "notes/vtt_transcription_corrections.md:" in r["authority"]
    assert "Gurrigam" in r["evidence"]
    assert "ruling" in r["guidance"]


def test_canonical_form_resolves_without_flagging_a_change(tmp_path):
    c = _campaign(tmp_path)
    r = resolve.resolve_name(c, "Jimjar")
    assert r["status"] == "resolved"
    assert r["is_change"] is False
    assert "guidance" not in r


def test_glossary_section_heading_supplies_entity_type(tmp_path):
    c = _campaign(tmp_path)
    assert resolve.resolve_name(c, "Jim Jar")["entity_type"] == "npc"


# ── hazard 1: the overloaded parenthetical ──────────────────────────────────

@pytest.mark.parametrize("surface,canon,paren", [
    ("Ebonir", "Ebonmire", "(Princess Ebonmire)"),
    ("Zugtmoy", "Zuggtmoy", "(confirmed via 5etools: MTF + OotA)"),
])
def test_parenthetical_returned_raw_and_unclassified(tmp_path, surface, canon, paren):
    """"(Princess Ebonmire)" is an alias; "(confirmed via 5etools)" is a
    provenance note. Same syntax. Nothing here decides which — a classifier
    eventually promotes a provenance note into a canonical name."""
    c = _campaign(tmp_path)
    r = resolve.resolve_name(c, surface)
    assert r["canonical"] == canon, "the bold form, and only the bold form"
    assert r["parenthetical"] == paren
    assert "UNCLASSIFIED" in resolve.format_result(r)


# ── tier 3: the registry ────────────────────────────────────────────────────

def test_registry_alias_resolves_to_canonical(tmp_path):
    c = _campaign(tmp_path)
    r = resolve.resolve_name(c, "Olvara")
    assert r["status"] == "resolved"
    assert r["canonical"] == "Ilvara Mizzrym"
    assert r["tier"] == 3
    assert r["is_change"] is True
    assert "alias: Olvara" in r["evidence"]


# ── tier 4: dossiers, and hazard 3 ──────────────────────────────────────────

def test_dossier_stated_ruling_resolves(tmp_path):
    c = _campaign(tmp_path)
    _dossier(c, "whatever.md", "---\nname: Asha Vandree\naliases:\n  - Ashas\n---\n\nbody\n")
    r = resolve.resolve_name(c, "Ashas")
    assert r["status"] == "resolved"
    assert r["tier"] == 4
    assert r["canonical"] == "Asha Vandree"


def test_filename_is_not_evidence(tmp_path):
    """docs/npcs/sequioa.md does not make "Sequioa" canonical. A dossier with
    no STATED name states nothing."""
    c = _campaign(tmp_path)
    _dossier(c, "sequioa.md", "# Sequioa\n\nNo frontmatter here.\n")
    r = resolve.resolve_name(c, "Sequioa")
    assert r["status"] == "not_canon"


# ── tier 5: known additions ─────────────────────────────────────────────────

def test_known_addition_resolves_as_unpromoted(tmp_path):
    c = _campaign(tmp_path)
    r = resolve.resolve_name(c, "Overbright")
    assert r["status"] == "resolved"
    assert r["tier"] == 5
    assert r["promoted"] is False


# ── ambiguous ───────────────────────────────────────────────────────────────

def test_ambiguous_emits_no_canonical_key(tmp_path):
    """The structural guarantee: when sources disagree there is nothing for a
    caller to apply, because the field it would read does not exist.

    This is also the case exact-key matching cannot see on its own. "Sequioa"
    hits the dossier that states it and stops; tier 1 holds "Sequoia" but never
    matches the surface key. Without the higher-authority drift check this
    would come back "resolved, no change" — waving through exactly the
    transposed-letter pair the canon rule exists to catch.
    """
    c = _campaign(tmp_path, party=("Sequoia",))
    _dossier(c, "s.md", "---\nname: Sequioa\n---\n\nbody\n")
    r = resolve.resolve_name(c, "Sequioa")
    assert r["status"] == "ambiguous"
    assert "canonical" not in r
    assert r["favoured"]["value"] == "Sequoia", "tier 1 outranks a dossier"
    assert r["favoured"]["tier"] == 1
    assert [x["value"] for x in r["conflicts"]] == ["Sequioa"]
    assert "do not adjudicate" in r["guidance"].lower()


def test_correct_spelling_resolves_cleanly_at_the_top_tier(tmp_path):
    """The mirror of the above: drift is only ever reported by a tier that
    OUTRANKS the one that ruled, so the authoritative spelling does not get
    flagged against the wrong one sitting below it."""
    c = _campaign(tmp_path, party=("Sequoia",))
    _dossier(c, "s.md", "---\nname: Sequioa\n---\n\nbody\n")
    r = resolve.resolve_name(c, "Sequoia")
    assert r["status"] == "resolved"
    assert r["tier"] == 1
    assert r["is_change"] is False


# ── not_canon ───────────────────────────────────────────────────────────────

def test_unknown_name_is_not_canon_with_near_misses_as_questions(tmp_path):
    c = _campaign(tmp_path)
    r = resolve.resolve_name(c, "Jimjarr")
    assert r["status"] == "not_canon"
    assert "canonical" not in r
    assert "Jimjar" in [nm["candidate"] for nm in r["near_misses"]]
    assert "questions, not answers" in r["guidance"]


def test_unknown_name_with_no_near_miss(tmp_path):
    c = _campaign(tmp_path)
    r = resolve.resolve_name(c, "Xyzzy Plughmaster")
    assert r["status"] == "not_canon"
    assert r["near_misses"] == []


def test_near_misses_are_ranked_best_first(tmp_path):
    c = _campaign(tmp_path)
    nms = resolve.near_misses(c, "Ilvara Mizzrim", 0.5)
    assert nms == sorted(nms, key=lambda d: (-d["ratio"], d["tier"]))


# ── missing sources degrade, never crash ────────────────────────────────────

def test_missing_chain_files_are_silent_not_fatal(tmp_path):
    c = _campaign(tmp_path, glossary=None, known=None, registry_entities=False)
    r = resolve.resolve_name(c, "Anybody")
    assert r["status"] == "not_canon"


def test_empty_surface_form(tmp_path):
    c = _campaign(tmp_path)
    assert resolve.resolve_name(c, "   ")["status"] == "not_canon"


# ── read-only ───────────────────────────────────────────────────────────────

def test_resolve_writes_nothing(tmp_path):
    """The guarantee that lets every skill call this freely."""
    c = _campaign(tmp_path)
    before = {p: p.read_bytes() for p in sorted(c.rglob("*")) if p.is_file()}
    for name in ["Gurrigam", "Olvara", "Jimjer", "Thorin", "Overbright", "Zugtmoy"]:
        resolve.resolve_name(c, name)
    after = {p: p.read_bytes() for p in sorted(c.rglob("*")) if p.is_file()}
    assert before == after


# ── CLI ─────────────────────────────────────────────────────────────────────

def test_cli_exit_codes_distinguish_the_three_statuses(tmp_path, capsys):
    c = _campaign(tmp_path, party=("Sequoia",))
    _dossier(c, "s.md", "---\nname: Sequioa\n---\n\nbody\n")
    assert registry.main(["resolve", str(c), "Gurrigam"]) == 0
    assert registry.main(["resolve", str(c), "Sequioa"]) == 3
    assert registry.main(["resolve", str(c), "Xyzzy"]) == 4


def test_cli_json_is_the_same_dict(tmp_path, capsys):
    c = _campaign(tmp_path)
    capsys.readouterr()  # drop the fixture's init/add chatter
    registry.main(["resolve", str(c), "Gurrigam", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload == resolve.resolve_name(c, "Gurrigam")


def test_cli_human_output_names_the_tier(tmp_path, capsys):
    c = _campaign(tmp_path)
    capsys.readouterr()
    registry.main(["resolve", str(c), "Gurrigam"])
    out = capsys.readouterr().out
    assert "RESOLVED" in out
    assert "Gyrgum" in out
    assert "is_change : True" in out


# ── articles are not spelling differences ───────────────────────────────────

def test_leading_article_is_not_a_conflict(tmp_path):
    """Found on the live OOTA corpus: the registry carries "the Overbright"
    and known-additions carries "Overbright". One name, one article — not a
    disagreement, and flagging it would fire on every article-prefixed entity
    in the campaign."""
    c = _campaign(tmp_path, known="- **Overbright** — Underdark slang\n")
    assert registry.main([
        "add", str(c), "--name", "the Overbright", "--type", "location", "--yes",
    ]) == 0
    r = resolve.resolve_name(c, "Overbright")
    assert r["status"] == "resolved"
    assert r["tier"] == 3
    assert r["is_change"] is False
    assert r["conflicts"] == []


def test_article_stripping_is_comparison_only(tmp_path):
    """The stored canonical keeps its article — nothing rewrites a name."""
    c = _campaign(tmp_path, known=None)
    assert registry.main([
        "add", str(c), "--name", "the Overbright", "--type", "location", "--yes",
    ]) == 0
    assert resolve.resolve_name(c, "Overbright")["canonical"] == "the Overbright"


# ── source caching ──────────────────────────────────────────────────────────

def test_cache_is_invalidated_when_the_glossary_changes(tmp_path):
    """A GM who has just added a glossary row expects the very NEXT resolution
    to honour it. Caching keyed on content-stat, not on process lifetime."""
    c = _campaign(tmp_path)
    resolve.clear_cache()
    assert resolve.resolve_name(c, "Grunkle")["status"] == "not_canon"

    g = c / "notes" / "vtt_transcription_corrections.md"
    g.write_text(g.read_text(encoding="utf-8").replace(
        "| Grygum, Graham, Gurrigam | **Gyrgum** |",
        "| Grygum, Graham, Gurrigam, Grunkle | **Gyrgum** |",
    ), encoding="utf-8")

    r = resolve.resolve_name(c, "Grunkle")
    assert r["status"] == "resolved"
    assert r["canonical"] == "Gyrgum"


def test_cache_survives_repeated_reads_of_an_unchanged_source(tmp_path):
    c = _campaign(tmp_path)
    resolve.clear_cache()
    first = resolve.resolve_name(c, "Gurrigam")
    assert all(resolve.resolve_name(c, "Gurrigam") == first for _ in range(20))


# ── tier 0: the character sheet ─────────────────────────────────────────────

def _sheet(campaign, filename, name, roster_name=None):
    (campaign / "docs").mkdir(parents=True, exist_ok=True)
    (campaign / "docs" / filename).write_text(
        f"---\nname: {name}\nplayer: A Player\n---\n\n# {name}\n", encoding="utf-8")
    p = campaign / "config" / "party.yaml"
    p.write_text(
        f"characters:\n- name: {roster_name or name}\n  sheet: docs/{filename}\n",
        encoding="utf-8")


def test_character_sheet_is_the_top_tier(tmp_path):
    c = _campaign(tmp_path, glossary=None, known=None, registry_entities=False)
    _sheet(c, "Gyrgum.md", "Gyrgum")
    resolve.clear_cache()
    r = resolve.resolve_name(c, "Gyrgum")
    assert r["status"] == "resolved"
    assert r["tier"] == 0
    assert r["authority"] == "docs/Gyrgum.md"
    assert r["entity_type"] == "pc"


def test_sheet_disagreeing_with_the_roster_is_ambiguous(tmp_path):
    """The gap this tier closes. `Grygum` resolved correctly only because
    party.yaml happened to agree with the sheet; had the roster drifted,
    nothing in the chain would have noticed."""
    c = _campaign(tmp_path, glossary=None, known=None, registry_entities=False)
    _sheet(c, "Gyrgum.md", "Gyrgum", roster_name="Grygum")
    resolve.clear_cache()
    r = resolve.resolve_name(c, "Grygum")
    assert r["status"] == "ambiguous"
    assert "canonical" not in r
    assert r["favoured"]["value"] == "Gyrgum"
    assert r["favoured"]["tier"] == 0, "the sheet outranks the roster"
    assert [x["value"] for x in r["conflicts"]] == ["Grygum"]


def test_sheet_surname_is_not_a_change(tmp_path):
    c = _campaign(tmp_path, glossary=None, known=None, registry_entities=False)
    _sheet(c, "Thorin Giantfriend.md", "Thorin Giantfriend")
    resolve.clear_cache()
    r = resolve.resolve_name(c, "Thorin")
    assert r["status"] == "resolved"
    assert r["tier"] == 0
    assert r["is_change"] is False


def test_only_declared_sheets_are_read(tmp_path):
    """A filename is not evidence and does not become evidence by sitting in
    docs/. Only a sheet party.yaml DECLARES via its `sheet:` field is read."""
    c = _campaign(tmp_path, glossary=None, known=None, registry_entities=False)
    _sheet(c, "Gyrgum.md", "Gyrgum")
    (c / "docs" / "Sequioa.md").write_text(
        "---\nname: Sequioa\n---\n\nnot in the roster\n", encoding="utf-8")
    resolve.clear_cache()
    assert resolve.resolve_name(c, "Sequioa")["status"] == "not_canon"


def test_sheet_without_a_stated_name_is_not_a_ruling(tmp_path):
    c = _campaign(tmp_path, glossary=None, known=None, registry_entities=False)
    (c / "docs").mkdir(parents=True, exist_ok=True)
    (c / "docs" / "Gyrgum.md").write_text("# Gyrgum\n\nno frontmatter\n", encoding="utf-8")
    (c / "config" / "party.yaml").write_text(
        "characters:\n- name: Gyrgum\n  sheet: docs/Gyrgum.md\n", encoding="utf-8")
    resolve.clear_cache()
    r = resolve.resolve_name(c, "Gyrgum")
    assert r["status"] == "resolved"
    assert r["tier"] == 1, "falls through to the roster, never to the filename"


def test_missing_sheet_file_degrades_silently(tmp_path):
    c = _campaign(tmp_path, glossary=None, known=None, registry_entities=False)
    (c / "config" / "party.yaml").write_text(
        "characters:\n- name: Gyrgum\n  sheet: docs/nope.md\n", encoding="utf-8")
    resolve.clear_cache()
    assert resolve.resolve_name(c, "Gyrgum")["tier"] == 1


def test_registry_declared_alias_is_not_a_conflict(tmp_path):
    """Found on the live corpus: the glossary rules `**Fembris**` while the
    registry holds `Fembris Lancer` with `Fembris` as a registered alias. Same
    entity at two lengths, declared as such -- not a disagreement to bring the
    GM. Prefix matching would also "fix" this, but it overmatches badly enough
    to stay confined to the PC tiers, so the registry is asked instead."""
    c = _campaign(tmp_path, glossary="## NPCs\n\n| Wrong | Right |\n|---|---|\n"
                                     "| Fembrus | **Fembris** |\n",
                  known=None, registry_entities=False)
    assert registry.main(["init", str(c)]) == 0
    assert registry.main(["add", str(c), "--name", "Fembris Lancer", "--type", "npc",
                          "--aliases", "Fembris", "Lancer", "--yes"]) == 0
    resolve.clear_cache()
    r = resolve.resolve_name(c, "Fembris")
    assert r["status"] == "resolved", "the registry says these are one entity"
    assert r["conflicts"] == []
