"""Tests for the sheet_frontmatter importer CLI (issue #265).

Deterministic, zero-token: parses an existing sheet's ``## Identity`` block
and proposes YAML frontmatter for it, per the GM ruling in
``docs/design/PartyRosterCanonicalFormat.md`` (the D&D Beyond sheet is
canonical; ``party.yaml`` only references it). No API call is made — see
``tests/test_retrieve_render_isolation.py`` / ``tests/test_layering.py``,
which this module must not violate.

Fixtures are built entirely under ``tmp_path`` — never against
``~/src/campaigns`` (that data is real GM content and the migration itself
is explicitly out of scope for #265; --apply is never run against it here).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from campaignlib.textproc import split_frontmatter  # noqa: E402
from pipelines.content_ingest import sheet_frontmatter as sf  # noqa: E402


SHEET_NO_FRONTMATTER = (
    "# Zalthir\n"
    "\n"
    "## Identity\n"
    "- **Class & Level:** Monk 8\n"
    "- **Species:** Dragonborn (Brass Dragon)\n"
    "- **Background:** Sailor\n"
    "- **Player:** Gabe\n"
    "- **Alignment:** Neutral Good\n"
    "- **Age / Gender / Size:** 27 / Male / Medium\n"
    "\n"
    "## Ability Scores\n"
    "| Ability | Score | Modifier |\n"
    "|---|---|---|\n"
)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ── Propose (dry-run) ────────────────────────────────────────────────────────

def test_propose_dry_run_writes_nothing(tmp_path, capsys):
    sheet = _write(tmp_path, "zalthir.md", SHEET_NO_FRONTMATTER)
    before = sheet.read_text(encoding="utf-8")

    rc = sf.main([str(sheet)])

    assert rc == 0
    assert sheet.read_text(encoding="utf-8") == before
    out = capsys.readouterr().out
    assert "name: Zalthir" in out
    assert "player: Gabe" in out
    assert "species: Dragonborn (Brass Dragon)" in out
    assert "class_level: Monk 8" in out


def test_two_dry_runs_produce_identical_proposal_and_no_mutation(tmp_path, capsys):
    sheet = _write(tmp_path, "zalthir.md", SHEET_NO_FRONTMATTER)
    before = sheet.read_text(encoding="utf-8")

    rc1 = sf.main([str(sheet)])
    out1 = capsys.readouterr().out
    rc2 = sf.main([str(sheet)])
    out2 = capsys.readouterr().out

    assert rc1 == rc2 == 0
    assert out1 == out2
    assert sheet.read_text(encoding="utf-8") == before


# ── --apply ───────────────────────────────────────────────────────────────────

def test_apply_writes_frontmatter(tmp_path):
    sheet = _write(tmp_path, "zalthir.md", SHEET_NO_FRONTMATTER)

    rc = sf.main([str(sheet), "--apply"])

    assert rc == 0
    new_text = sheet.read_text(encoding="utf-8")
    fm, body = split_frontmatter(new_text)
    assert fm == {
        "name": "Zalthir",
        "player": "Gabe",
        "species": "Dragonborn (Brass Dragon)",
        "class_level": "Monk 8",
        "subclass": "",
    }
    # Body — the original document — must survive unchanged.
    assert body == SHEET_NO_FRONTMATTER


def test_subclass_always_blank_and_reported(tmp_path, capsys):
    sheet = _write(tmp_path, "zalthir.md", SHEET_NO_FRONTMATTER)
    sf.main([str(sheet), "--apply"])
    fm, _ = split_frontmatter(sheet.read_text(encoding="utf-8"))
    assert fm["subclass"] == ""

    out = capsys.readouterr().out
    assert "subclass" in out.lower()
    assert "manual fill-in" in out.lower() or "not recoverable" in out.lower()


# ── Refuse-to-clobber ─────────────────────────────────────────────────────────

def test_refuses_to_clobber_existing_frontmatter_without_force(tmp_path, capsys):
    sheet = _write(
        tmp_path, "zalthir.md",
        "---\nname: Zalthir\nplayer: OldGabe\nspecies: X\nclass_level: Y\nsubclass: ''\n---\n"
        + SHEET_NO_FRONTMATTER,
    )
    before = sheet.read_text(encoding="utf-8")

    rc = sf.main([str(sheet), "--apply"])

    assert rc == 1
    assert sheet.read_text(encoding="utf-8") == before
    err = capsys.readouterr().err
    assert "--force" in err


def test_force_overwrites_existing_frontmatter(tmp_path):
    sheet = _write(
        tmp_path, "zalthir.md",
        "---\nname: Zalthir\nplayer: OldGabe\nspecies: X\nclass_level: Y\nsubclass: ''\n---\n"
        + SHEET_NO_FRONTMATTER,
    )

    rc = sf.main([str(sheet), "--apply", "--force"])

    assert rc == 0
    fm, body = split_frontmatter(sheet.read_text(encoding="utf-8"))
    assert fm["player"] == "Gabe"  # re-derived from ## Identity, not the stale frontmatter
    assert body == SHEET_NO_FRONTMATTER


# ── Missing '## Identity' ────────────────────────────────────────────────────

def test_missing_identity_block_is_a_clean_refusal(tmp_path, capsys):
    sheet = _write(tmp_path, "notasheet.md", "# Notes\n\nJust some prose, no Identity section.\n")
    before = sheet.read_text(encoding="utf-8")

    rc = sf.main([str(sheet), "--apply"])

    assert rc == 1
    assert sheet.read_text(encoding="utf-8") == before
    out = capsys.readouterr().out
    assert "REFUSED" in out
    assert "Identity" in out


# ── Unrecognised '## Identity' keys ──────────────────────────────────────────

def test_unrecognised_identity_keys_are_reported_not_dropped(tmp_path, capsys):
    text = SHEET_NO_FRONTMATTER.replace(
        "- **Alignment:** Neutral Good\n",
        "- **Alignment:** Neutral Good\n- **Favorite Color:** Brass\n",
    )
    sheet = _write(tmp_path, "zalthir.md", text)

    sf.main([str(sheet)])

    out = capsys.readouterr().out
    assert "Favorite Color" in out
    assert "Unrecognised" in out


# ── Conflict reporting vs party.md — never auto-resolved ────────────────────

def test_conflict_reporting_shows_both_sides(tmp_path, capsys):
    """toee-shaped case: the sheet's Player field is a D&D Beyond account
    handle, party.md has the real name. The importer must show BOTH, never
    prefer one."""
    sheet_text = SHEET_NO_FRONTMATTER.replace("- **Player:** Gabe\n", "- **Player:** kostadis1\n")
    sheet = _write(tmp_path, "zalthir.md", sheet_text)
    party_md = _write(
        tmp_path, "party.md",
        "### Zalthir — Monk 8 (Warrior of Shadow) · Bronze Dragonborn · Player: George Kolivakis\n",
    )

    rc = sf.main([str(sheet), "--party", str(party_md)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "kostadis1" in out
    assert "George Kolivakis" in out
    assert "Conflicts" in out


def test_species_conflict_reports_both_sides(tmp_path, capsys):
    """out-of-the-abyss Zalthir case: sheet says Dragonborn (Brass Dragon),
    party.md says Bronze Dragonborn — a real, unresolved factual conflict."""
    sheet = _write(tmp_path, "zalthir.md", SHEET_NO_FRONTMATTER)
    party_md = _write(
        tmp_path, "party.md",
        "### Zalthir — Monk 8 (Warrior of Shadow) · Bronze Dragonborn · Player: Gabe\n",
    )

    sf.main([str(sheet), "--party", str(party_md)])

    out = capsys.readouterr().out
    assert "Dragonborn (Brass Dragon)" in out
    assert "Bronze Dragonborn Monk 8 (Warrior of Shadow)" in out


def test_no_conflict_when_party_md_agrees(tmp_path, capsys):
    sheet = _write(tmp_path, "zalthir.md", SHEET_NO_FRONTMATTER)
    party_md = _write(
        tmp_path, "party.md",
        "### Zalthir — Monk 8 (Warrior of Shadow) · Dragonborn (Brass Dragon) · Player: Gabe\n",
    )

    rc = sf.main([str(sheet), "--party", str(party_md)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "No conflicts vs party.md." in out
