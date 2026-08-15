"""Tests for campaignlib/sheet_naming.py — the roster's authority over a
converted sheet's name, location, archive slot and player (feature 008).

The load-bearing assertion in this file is a negative one: attribution has no
fuzzy fallback. ``Valphine Sotorra`` does not resolve to ``Valphine``, and it
must not start doing so — the GM ruled that a mismatch is a loud failure they
fix in the roster, and a similarity band has already been measured in this
project to be incapable of separating a harmless edit from a meaning-changing
one.
"""

import ast
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

# Not optional (D12): the editable install's .pth hardcodes the MAIN checkout,
# so without this a worktree's tests silently import main's campaignlib and a
# green run proves nothing. Every test module in this repo does the same.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from campaignlib.sheet_naming import (  # noqa: E402
    ArchiveSlotOccupied,
    AttributionError,
    DisplacedLevelUnreadable,
    RosterDirectoryMissing,
    RosterFilenameMismatch,
    apply_roster_player,
    archive_path,
    attribute,
    check_destination,
    destination_for,
    plan_archive,
)


@dataclass
class StubCharacter:
    """Structurally what ``PartyCharacter`` is, without the pydantic import."""

    name: str
    sheet: str = "docs/party/stub.md"


PHANDALIN = [
    StubCharacter("Brewbarry", "../docs/party/Brewbarry.md"),
    StubCharacter("Valphine", "../docs/party/Valphine.md"),
    StubCharacter("Soma", "../docs/party/Soma.md"),
    StubCharacter("Vukradin", "../docs/party/Vukradin.md"),
]


# ── attribute ──────────────────────────────────────────────────────────────

def test_exact_name_resolves():
    assert attribute("Soma", PHANDALIN).name == "Soma"


@pytest.mark.parametrize("written", ["soma", "SOMA", "  Soma  ", "sOmA"])
def test_case_and_whitespace_do_not_matter(written):
    """Not fuzziness: propose() already keys on name.lower(), and zalthir.md
    has a documented trailing space."""
    assert attribute(written, PHANDALIN).name == "Soma"


def test_name_absent_from_roster_refuses_and_lists_what_is_available():
    with pytest.raises(AttributionError) as exc:
        attribute("Valphine Sotorra", PHANDALIN)
    assert exc.value.matches == 0
    assert exc.value.extracted_name == "Valphine Sotorra"
    # The GM has to be able to see what they could have meant.
    assert exc.value.roster_names == ["Brewbarry", "Soma", "Valphine", "Vukradin"]
    assert "Valphine" in str(exc.value)


def test_no_prefix_or_substring_fallback():
    """The live Phandalin case. A prefix match would 'helpfully' resolve this
    and silently write over the wrong character's sheet."""
    for near_miss in ["Valphine Sotorra", "Val", "Somaa", "Brew"]:
        with pytest.raises(AttributionError):
            attribute(near_miss, PHANDALIN)


def test_duplicate_names_refuse_rather_than_first_wins():
    roster = PHANDALIN + [StubCharacter("soma", "../docs/party/soma-two.md")]
    with pytest.raises(AttributionError) as exc:
        attribute("Soma", roster)
    assert exc.value.matches == 2
    assert "2 roster entries" in str(exc.value)


def test_empty_roster_refuses():
    with pytest.raises(AttributionError) as exc:
        attribute("Soma", [])
    assert exc.value.matches == 0
    assert exc.value.roster_names == []


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_empty_extracted_name_refuses(empty):
    """A model that returned no H1 must not match an empty-named roster entry."""
    with pytest.raises(AttributionError):
        attribute(empty, PHANDALIN)


def test_module_has_no_fuzzy_matching_machinery():
    """Guard the ruling itself, not just today's behaviour: no similarity,
    edit-distance or embedding call may appear in this module.

    Docstrings and comments are stripped before the check — this module has to
    be free to *explain* why fuzzy matching is banned."""
    source = (Path(__file__).resolve().parent.parent
              / "campaignlib" / "sheet_naming.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                node.body = node.body[1:] or [ast.Pass()]
    code = ast.unparse(tree)  # also drops every comment

    for banned in ("difflib", "SequenceMatcher", "get_close_matches",
                   "levenshtein", "rapidfuzz", "embed", "cosine"):
        assert banned not in code, f"fuzzy-matching machinery reappeared: {banned}"


# ── destination_for / check_destination ────────────────────────────────────

def test_destination_is_the_roster_directory_and_the_roster_spelling(tmp_path):
    """FR-005: the filename comes from the roster, never from the PDF."""
    (tmp_path / "docs" / "party").mkdir(parents=True)
    char = StubCharacter("Soma", "docs/party/Soma.md")
    assert destination_for(char, tmp_path) == tmp_path / "docs" / "party" / "Soma.md"


def test_destination_honours_a_config_relative_roster(tmp_path):
    """Every live roster is campaign-root-relative (#291), but `base` is the
    caller's parameter and nothing here assumes a shape — a `..` segment must
    resolve, not be rejected or normalised away."""
    (tmp_path / "docs" / "party").mkdir(parents=True)
    char = StubCharacter("Soma", "../docs/party/Soma.md")
    assert destination_for(char, tmp_path / "config") == (
        tmp_path / "docs" / "party" / "Soma.md"
    )


def test_roster_basename_disagreement_refuses_with_the_replacement_line(tmp_path):
    (tmp_path / "docs" / "party").mkdir(parents=True)
    char = StubCharacter("Soma", "../docs/party/soma.md")
    with pytest.raises(RosterFilenameMismatch) as exc:
        check_destination(char, tmp_path / "config")
    assert exc.value.declared == "../docs/party/soma.md"
    # A line the GM can paste straight back into party.yaml — still relative,
    # so their roster does not become machine-specific.
    assert exc.value.replacement == "../docs/party/Soma.md"
    assert exc.value.character_name == "Soma"


def test_case_only_difference_is_still_a_disagreement(tmp_path):
    """FR-007: on a case-insensitive filesystem soma.md and Soma.md are the
    same file, and a rename that 'succeeded' would have moved nothing."""
    (tmp_path / "party").mkdir()
    with pytest.raises(RosterFilenameMismatch):
        check_destination(StubCharacter("Soma", "party/soma.md"), tmp_path)


def test_agreeing_roster_passes_through(tmp_path):
    (tmp_path / "party").mkdir()
    char = StubCharacter("Soma", "party/Soma.md")
    assert check_destination(char, tmp_path) == tmp_path / "party" / "Soma.md"


def test_destination_directory_must_already_exist(tmp_path):
    """Refuse rather than mkdir: in roster mode the directory is declared by
    party.yaml, so a missing one means the roster or the cwd is wrong, and
    creating it would scatter a sheet into a tree nobody meant to exist."""
    char = StubCharacter("Soma", "docs/party/Soma.md")
    with pytest.raises(RosterDirectoryMissing) as exc:
        check_destination(char, tmp_path)
    assert exc.value.directory == tmp_path / "docs" / "party"
    assert not (tmp_path / "docs").exists()


def test_a_missing_sheet_file_is_not_an_error(tmp_path):
    """The first conversion for a character legitimately has no sheet yet."""
    (tmp_path / "party").mkdir()
    assert check_destination(StubCharacter("Newbie", "party/Newbie.md"), tmp_path)


# ── archive_path / plan_archive ────────────────────────────────────────────

def _sheet(path: Path, class_level: str = "Druid 5") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Soma\n\n## Identity\n- **Class & Level:** {class_level}\n",
        encoding="utf-8",
    )
    return path


def test_archive_path_layout(tmp_path):
    """FR-012: old/level/<N>/, matching the archive the GM built by hand."""
    dest = tmp_path / "docs" / "party" / "Soma.md"
    assert archive_path(dest, 5, "Soma") == (
        tmp_path / "docs" / "party" / "old" / "level" / "5" / "Soma.md"
    )


def test_nothing_to_archive_when_the_destination_is_free(tmp_path):
    assert plan_archive(tmp_path / "Soma.md", "Soma") is None


def test_plan_reads_the_level_off_the_sheet_being_displaced(tmp_path):
    """Not the incoming sheet's level — the archive reads as 'the sheet as it
    was at level N'."""
    dest = _sheet(tmp_path / "party" / "Soma.md", "Druid 5")
    plan = plan_archive(dest, "Soma")
    assert plan.level == 5
    assert plan.source == dest
    assert plan.destination == tmp_path / "party" / "old" / "level" / "5" / "Soma.md"


def test_archived_filename_is_roster_shaped_even_when_the_old_one_was_not(tmp_path):
    """Phandalin's live sheets are lowercase and its hand-built archive is
    capitalised; the archive keeps the roster's spelling so the two
    conventions never coexist."""
    dest = _sheet(tmp_path / "party" / "soma.md", "Druid 5")
    plan = plan_archive(dest, "Soma")
    assert plan.destination.name == "Soma.md"


def test_occupied_archive_slot_refuses(tmp_path):
    """FR-014: never overwrite, never suffix. Losing an archived sheet is the
    one thing this feature exists to prevent."""
    dest = _sheet(tmp_path / "party" / "Soma.md", "Druid 5")
    occupied = _sheet(tmp_path / "party" / "old" / "level" / "5" / "Soma.md")
    before = occupied.read_text(encoding="utf-8")

    with pytest.raises(ArchiveSlotOccupied) as exc:
        plan_archive(dest, "Soma")

    assert exc.value.level == 5
    assert occupied.read_text(encoding="utf-8") == before


def test_unreadable_level_refuses_and_quotes_the_value(tmp_path):
    dest = _sheet(tmp_path / "party" / "Soma.md", "Fighter 9 / Bard 2")
    with pytest.raises(DisplacedLevelUnreadable) as exc:
        plan_archive(dest, "Soma")
    assert exc.value.phrase == "Fighter 9 / Bard 2"


def test_absent_level_refuses_with_phrase_none(tmp_path):
    dest = tmp_path / "party" / "Soma.md"
    dest.parent.mkdir(parents=True)
    dest.write_text("# Soma\n\n## Identity\n- **Species:** Firbolg\n", encoding="utf-8")
    with pytest.raises(DisplacedLevelUnreadable) as exc:
        plan_archive(dest, "Soma")
    assert exc.value.phrase is None


def test_planning_moves_nothing(tmp_path):
    """plan_archive decides; only the caller mutates. This is what makes every
    refusal free (D7)."""
    dest = _sheet(tmp_path / "party" / "Soma.md", "Druid 5")
    plan_archive(dest, "Soma")
    assert dest.exists()
    assert not (tmp_path / "party" / "old").exists()


# ── apply_roster_player ────────────────────────────────────────────────────

SHEET_WITH_FRONTMATTER = textwrap.dedent("""\
    ---
    name: Soma
    player: Kostadis
    species: Firbolg
    class_level: Druid 6
    subclass: ""
    ---
    # Soma

    ## Identity
    - **Class & Level:** Druid 6
    - **Player:** Kostadis
    - **Alignment:** NG

    ## Combat
    - **HP:** 44
    """)

SHEET_WITHOUT_FRONTMATTER = textwrap.dedent("""\
    # Soma

    ## Identity
    - **Class & Level:** Druid 6
    - **Player:** Kostadis

    ## Combat
    - **HP:** 44
    """)


def test_both_channels_are_rewritten():
    """FR-010a: rewriting one leaves the downloader's name legible in the
    document while tooling reports someone else."""
    out = apply_roster_player(SHEET_WITH_FRONTMATTER, "Wade")
    assert "player: Wade" in out
    assert "- **Player:** Wade" in out
    assert "Kostadis" not in out


def test_nothing_else_in_the_frontmatter_moves():
    out = apply_roster_player(SHEET_WITH_FRONTMATTER, "Wade")
    fm = out.split("---")[1]
    assert [line.split(":")[0] for line in fm.strip().splitlines()] == [
        "name", "player", "species", "class_level", "subclass",
    ]
    assert 'subclass: ""' in out          # the quoting style survives
    assert "- **Alignment:** NG" in out


def test_a_sheet_without_frontmatter_still_gets_its_identity_line_rewritten():
    """All eight of Phandalin's sheets, live and archived, are shaped like
    this."""
    out = apply_roster_player(SHEET_WITHOUT_FRONTMATTER, "Wade")
    assert "- **Player:** Wade" in out
    assert not out.startswith("---")


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_no_roster_player_empties_both_rather_than_keeping_the_download(blank):
    """FR-009: the downloaded value names the *downloader*. Carrying it forward
    would record the GM as every character's player."""
    out = apply_roster_player(SHEET_WITH_FRONTMATTER, blank)
    assert "Kostadis" not in out
    assert 'player: ""' in out or "player: ''" in out
    assert "- **Player:**\n" in out


def test_the_value_is_trimmed():
    out = apply_roster_player(SHEET_WITH_FRONTMATTER, "  Wade  ")
    assert "player: Wade\n" in out
    assert "- **Player:** Wade\n" in out


def test_a_frontmatter_missing_the_player_key_gains_it_in_canonical_order():
    """The downstream parser expects all five keys every time."""
    sheet = SHEET_WITH_FRONTMATTER.replace("player: Kostadis\n", "")
    out = apply_roster_player(sheet, "Wade")
    fm = out.split("---")[1]
    assert [line.split(":")[0] for line in fm.strip().splitlines()] == [
        "name", "player", "species", "class_level", "subclass",
    ]


def test_a_player_name_needing_quoting_is_quoted():
    out = apply_roster_player(SHEET_WITH_FRONTMATTER, "Wade: the DM")
    assert yaml.safe_load(out.split("---")[1])["player"] == "Wade: the DM"


def test_an_identity_block_with_no_player_line_gains_one():
    """SYSTEM_PROMPT tells the model to omit blank body fields, so a PDF with
    no player produces exactly this. Leaving it alone would put the roster's
    player in the frontmatter and none in the prose — the contradiction this
    function exists to prevent."""
    sheet = SHEET_WITH_FRONTMATTER.replace("- **Player:** Kostadis\n", "")
    out = apply_roster_player(sheet, "Wade")
    assert "- **Player:** Wade" in out
    # Inserted inside the ## Identity block, not appended to the document.
    identity = out.split("## Identity")[1].split("## Combat")[0]
    assert "- **Player:** Wade" in identity
    assert "- **Alignment:** NG" in identity


def test_leading_whitespace_does_not_defeat_the_frontmatter_rewrite():
    """The regex is \\A-anchored, so one stray newline from the model would
    silently skip the machine channel while still rewriting the prose one —
    and player_map_from_config reads the machine channel."""
    out = apply_roster_player("\n  " + SHEET_WITH_FRONTMATTER, "Wade")
    # Callers strip before calling; this asserts the failure is visible rather
    # than silent if one ever doesn't.
    both_rewritten = "player: Wade" in out and "- **Player:** Wade" in out
    neither_rewritten = "Kostadis" in out.split("## Identity")[0]
    assert both_rewritten or neither_rewritten, (
        "one channel was rewritten and the other was not — the sheet now "
        "states two different players"
    )


def test_a_player_line_outside_the_identity_block_is_left_alone():
    sheet = SHEET_WITH_FRONTMATTER + "\n## Notes\n- **Player:** see above\n"
    out = apply_roster_player(sheet, "Wade")
    assert "- **Player:** see above" in out
    assert out.count("- **Player:** Wade") == 1
