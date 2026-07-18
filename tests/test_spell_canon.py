"""Tests for spell_canon.py — the proper-noun spelling canonicaliser.

All deterministic, no API. Covers the matching primitives (where precision
lives), the corpus/inventory parsing, and the case-preserving apply.
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from entity_registry import registry  # noqa: E402
from entity_registry import spell_canon as sc  # noqa: E402
from campaignlib.registry import load_registry  # noqa: E402

SIM = sc.DEFAULT_SIM
DELTA = sc.DEFAULT_MAX_DELTA


def test_same_word_family_true_for_inflections():
    assert sc.same_word_family("keeper", "keepers")       # +s
    assert sc.same_word_family("scene", "scenes")
    assert sc.same_word_family("considered", "reconsidered")  # re- prefix
    assert sc.same_word_family("walk", "walking")


def test_same_word_family_false_for_internal_misspellings():
    assert not sc.same_word_family("bupido", "buppido")
    assert not sc.same_word_family("demogorgon", "demogorgonn")  # doubled tail, not +s family
    assert not sc.same_word_family("whorlstone", "whorlestone")


def test_edit_distance():
    assert sc.edit_distance("abc", "abc") == 0
    assert sc.edit_distance("abc", "abd") == 1
    assert sc.edit_distance("abc", "ab") == 1
    assert sc.edit_distance("kitten", "sitting") == 3


def test_close_excludes_near_words():
    # ratio below the 0.88 floor → not registered as the same name
    assert not sc.close("abyss", "abyssal", SIM, DELTA)
    assert not sc.close("basin", "bastion", SIM, DELTA)
    assert not sc.close("archives", "archivist", SIM, DELTA)


def test_close_pairs_caught_only_by_the_case_guard():
    # plans/planes ARE edit-distance 1 (ratio ~0.91), so close() matches them;
    # the false positive is killed instead by best_canon's capitalisation guard
    # (a lowercase token is never a proper-noun typo) — see test below.
    assert sc.close("plans", "planes", SIM, DELTA)
    assert sc.best_canon("plans", {"planes": "Planes"}, SIM, DELTA) is None


def test_close_accepts_true_misspellings():
    assert sc.close("whorlestone", "whorlstone", SIM, DELTA)
    assert sc.close("menzoberanzan", "menzoberranzan", SIM, DELTA)
    assert sc.close("bupido", "buppido", SIM, DELTA)


def test_best_canon_maps_typo_to_inventory():
    canon = {"whorlstone": "Whorlstone", "buppido": "Buppido"}
    assert sc.best_canon("Whorlestone", canon, SIM, DELTA) == "Whorlstone"
    assert sc.best_canon("Bupido", canon, SIM, DELTA) == "Buppido"


def test_best_canon_skips_valid_and_lowercase_and_nearwords():
    canon = {"whorlstone": "Whorlstone", "abyss": "Abyss"}
    assert sc.best_canon("Whorlstone", canon, SIM, DELTA) is None   # already canonical
    assert sc.best_canon("whorlestone", canon, SIM, DELTA) is None  # lowercase → not a name typo
    assert sc.best_canon("Abyssal", canon, SIM, DELTA) is None      # near-word, excluded


def test_cased_like():
    assert sc.cased_like("whorlestone", "Whorlstone") == "whorlstone"
    assert sc.cased_like("WHORLESTONE", "Whorlstone") == "WHORLSTONE"
    assert sc.cased_like("Whorlestone", "Whorlstone") == "Whorlstone"


def test_apply_is_wholeword_casepreserving_possessive_safe(tmp_path):
    bible = tmp_path / "b.md"
    bible.write_text(
        "Bupido spoke. bupido left. Bupido's knife. Buppidox stays.\n",
        encoding="utf-8",
    )
    counts = sc.apply_map(bible, {"Bupido": "Buppido"}, dry_run=False)
    out = bible.read_text(encoding="utf-8")
    assert counts["Bupido"] == 3                 # two words + the possessive base
    assert "Buppido spoke" in out
    assert "buppido left" in out                 # lowercase preserved
    assert "Buppido's knife" in out              # possessive intact
    assert "Buppidox stays" in out               # substring NOT touched


def test_apply_dry_run_writes_nothing(tmp_path):
    bible = tmp_path / "b.md"
    bible.write_text("Bupido\n", encoding="utf-8")
    sc.apply_map(bible, {"Bupido": "Buppido"}, dry_run=True)
    assert bible.read_text(encoding="utf-8") == "Bupido\n"


def test_proper_nouns_folds_possessive_and_drops_short_and_stopwords(tmp_path):
    bible = tmp_path / "b.md"
    bible.write_text("Shuushar and Shuushar's plan. The cat. Daz ran.\n", encoding="utf-8")
    freq, _ = sc.proper_nouns(bible, sc.DEFAULT_MIN_LEN)
    assert freq["Shuushar"] == 2                 # possessive folded into base
    assert "The" not in freq                     # stopword
    assert "Daz" not in freq                     # under MIN_LEN (5)
    assert "cat" not in freq                      # never capitalised / short


def test_inventory_tokens_parses_bold_and_splits(tmp_path):
    inv = tmp_path / "inv.md"
    inv.write_text("- **Sarith Kzekarit / Sarith** — drow\n- **Whorlstone** tunnels\n",
                   encoding="utf-8")
    canon = sc.inventory_tokens(inv, sc.DEFAULT_MIN_LEN)
    assert canon["whorlstone"] == "Whorlstone"
    assert canon["sarith"] == "Sarith"
    assert canon["kzekarit"] == "Kzekarit"


def test_build_proposal_end_to_end(tmp_path):
    inv = tmp_path / "inv.md"
    inv.write_text("- **Whorlstone**\n- **Shuushar**\n", encoding="utf-8")
    bible = tmp_path / "b.md"
    bible.write_text(
        "Whorlstone Whorlestone Whorelstone. Suushar Suushar Shuushar.\n"
        "Grygum Grygum Grygum Grygum Grygum Grygum Grygum Grygum Grygum Grygm.\n",
        encoding="utf-8",
    )
    mapping, report, n_a, n_b = sc.build_proposal(
        bible, inv, SIM, sc.DEFAULT_MIN_LEN, DELTA, anchor_min=8)
    # Phase A: inventory names
    assert mapping["Whorlestone"] == "Whorlstone"
    assert mapping["Whorelstone"] == "Whorlstone"
    assert mapping["Suushar"] == "Shuushar"
    # Phase B: Grygum (×9 ≥ anchor_min) anchors the rare typo Grygm (×1)
    assert mapping["Grygm"] == "Grygum"
    assert "Phase A" in report and "Phase B" in report


# ── proper_noun_counts refactor (Packet 3b) ──────────────────────────────────

def test_proper_noun_counts_matches_repeated_names_and_drops_stopwords():
    text = "Shuushar and Shuushar's plan. The cat. Daz ran. SHUUSHAR shouted.\n"
    counts = sc.proper_noun_counts(text, sc.DEFAULT_MIN_LEN)
    assert counts["Shuushar"] == 3               # base + possessive + all-caps form, folded by case
    assert "The" not in counts                   # stopword
    assert "Daz" not in counts                   # under MIN_LEN (5)
    assert "cat" not in counts                   # never capitalised / short


def test_proper_nouns_delegates_to_proper_noun_counts(tmp_path):
    bible = tmp_path / "b.md"
    text = "Shuushar and Shuushar's plan. The cat. Daz ran.\n"
    bible.write_text(text, encoding="utf-8")

    freq, lines_of = sc.proper_nouns(bible, sc.DEFAULT_MIN_LEN)
    direct = sc.proper_noun_counts(text, sc.DEFAULT_MIN_LEN)

    assert freq == direct
    assert isinstance(freq, Counter)
    assert set(lines_of) == set(freq)             # every surviving token has line samples
    assert lines_of["Shuushar"] == [1, 1]          # both occurrences are on line 1


# ── inventory_tokens against a registry.py-generated projection (Packet 3b) ─

def test_inventory_tokens_parses_registry_generated_projection(tmp_path):
    campaign_dir = tmp_path / "campaign"
    campaign_dir.mkdir()
    assert registry.main(["init", str(campaign_dir)]) == 0
    assert registry.main([
        "add", str(campaign_dir),
        "--name", "Ilvara Mizzrym", "--type", "npc",
        "--aliases", "Ilvara", "Mistress Ilvara",
    ]) == 0
    assert registry.main([
        "add", str(campaign_dir), "--name", "Gracklstugh", "--type", "location",
    ]) == 0
    assert registry.main(["project", str(campaign_dir)]) == 0

    inventory_path = campaign_dir / "docs" / "entity_inventory.md"
    text = inventory_path.read_text(encoding="utf-8")
    assert text.startswith("<!-- GENERATED from docs/entity_registry.yaml")
    assert "## NPCs" in text and "## Locations" in text

    tokens = sc.inventory_tokens(inventory_path, min_len=3)

    # the HTML-comment header and "## Heading" lines contribute no tokens
    assert "generated" not in tokens
    assert "npcs" not in tokens
    assert "locations" not in tokens

    # each name/alias is its OWN token — never a combined "name/alias" blob
    assert tokens["ilvara"] == "Ilvara"
    assert tokens["mizzrym"] == "Mizzrym"
    assert tokens["mistress"] == "Mistress"
    assert tokens["gracklstugh"] == "Gracklstugh"
    assert not any("/" in v for v in tokens.values())
