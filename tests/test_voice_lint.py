"""Tests for session_doc/voice_lint.py's banned-construction checks.

The behavioral-taxonomy family is banned in base.md as a MOVE, not a wording
(#246). The #245 Opus-vs-Fable benchmark then showed it surviving that ban by
rotating shells: every mechanical scan returned zero hits across all 12 scenes
while reading found three confirmed instances, none of which PORTRAIT_RE's
"with the X of a man who ..." pattern can match. TAXONOMY_RE (#251) covers the
rotated shell, and the three instances below are pinned verbatim from the issue
so a future regex tidy-up cannot quietly reopen the hole.

The bookkeeping half is per-campaign (kostadis/mytools#125 F4/D3). It used to be
module constants naming out-of-the-abyss' narrators, so on every other campaign the
check was inert while the run still reported clean. It now comes from the campaign's
own rulebook, and a rulebook that says nothing produces a *skip note*, never a pass.
"""
import pytest

from session_doc.voice_lint import (
    PORTRAIT_RE,
    TAXONOMY_RE,
    Bookkeeping,
    LintConfig,
    lint,
    load_config,
    parse_config,
)

# Verbatim from CG#251 — all three found by reading the opus benchmark arm.
BENCHMARK_INSTANCES = [
    "He said *aha*, in the way men say it when they have understood nothing.",
    "…everyone looked at me the way they do when they want someone else to decide.",
    "The third one said it plain, the way they say things at that age…",
]

OOTA_RULEBOOK = """\
# Out of the Abyss Narration Genre

- **Thorin:** *noted, worth noting, clocked, kept it.* He does NOT *file*.
- **Grygum:** *took notes, filed, inscribed.* Filing is canonical and protected.

```yaml voice_lint
bookkeeping:
  licensed:          [grygum, daz]
  unlicensed:        [thorin, zalthir]
  per_section_cap:   1
  doc_sections_cap:  2
```
"""

# Phandalin's real rulebook: register rules, portable tics, and no bookkeeping section
# at all. The point of the fixture is that this is a legitimate campaign, not a broken one.
PHANDALIN_RULEBOOK = """\
# Phandalin Narration Genre

- Em-dash **only** for interrupted speech or interrupted thought — never as a connective.
- **"the shape of X"** — Claude tic. Never use.
"""


def _lint(text, config=None):
    return lint(text, config)


@pytest.mark.parametrize("line", BENCHMARK_INSTANCES)
def test_taxonomy_re_catches_every_benchmark_instance(line):
    assert TAXONOMY_RE.search(line), f"TAXONOMY_RE missed a confirmed #251 instance: {line!r}"


@pytest.mark.parametrize("line", BENCHMARK_INSTANCES)
def test_portrait_re_misses_them_which_is_why_taxonomy_re_exists(line):
    """Documents the gap: the #246-era pattern cannot see the rotated shell."""
    assert not PORTRAIT_RE.search(line)


@pytest.mark.parametrize("line", [
    # One named individual or one person is a specific observation, not a class.
    "I liked the way she said my name.",
    "He fixed it the way Brewbarry does, badly.",
    # No taxonomy verb at all.
    "I went the way he pointed.",
    "That is the way home when the river floods.",
    # `when` with no "the way X <verb>" lead-in.
    "She smiled when the song ended.",
])
def test_taxonomy_re_does_not_over_fire(line):
    assert not TAXONOMY_RE.search(line), f"false positive on legitimate prose: {line!r}"


def test_taxonomy_hit_is_reported_by_lint():
    """A single occurrence warns; more than one is a hard error (doc-level rule)."""
    one = "## Vukradin — Scene 02\n\n" + BENCHMARK_INSTANCES[0] + "\n"
    errors, warns, _ = _lint(one)
    assert not errors
    assert any("the-way-X-do-when" in w for w in warns), warns

    two = ("## Vukradin — Scene 02\n\n" + BENCHMARK_INSTANCES[0] + "\n"
           "\n## Soma — Scene 05\n\n" + BENCHMARK_INSTANCES[1] + "\n")
    errors, _, _ = _lint(two)
    assert any("the-way-X-do-when" in e for e in errors), errors


def test_clean_narration_trips_nothing():
    text = ("## Brewbarry — Scene 01\n\n"
            "He said *aha* and looked at his hands. Nobody answered him.\n"
            "I counted the coins twice and put them back in the bag.\n")
    errors, warns, _ = _lint(text)
    assert (errors, warns) == ([], [])


# --- portable tics run without a rulebook; base.md bans them for every campaign ---

def test_portable_tics_are_campaign_independent():
    """No --genre-file must not disable the HARD BANS checks."""
    text = "## Daz — Scene 01\n\nI saw the shape of it. Then the shape of the next one.\n"
    errors, _, _ = _lint(text)
    assert any("the shape of" in e for e in errors), errors


def test_portable_tic_cap_is_tunable_from_the_rulebook():
    text = "## Daz — Scene 01\n\nI saw the shape of it. Then the shape of the next one.\n"
    loose = parse_config("```yaml voice_lint\nportable_tics:\n  the_shape_of: 2\n```\n")
    errors, warns, _ = _lint(text, loose)
    assert not errors
    assert any("the shape of" in w for w in warns), warns


# --- bookkeeping: absent rulebook is a skip, never a pass (F4/C2) ---

def test_no_rulebook_skips_filing_checks_and_says_so():
    """The regression this replaced: OOTA's constants reported clean on other campaigns."""
    text = ("## Thorin — Scene 01\n\nI filed it away and said nothing.\n"
            "\n## Zalthir — Scene 02\n\nI filed that too.\n"
            "\n## Daz — Scene 03\n\nI filed the third one.\n")
    errors, warns, notes = _lint(text)
    assert errors == [] and warns == []
    assert any("skipped" in n and "bookkeeping" in n for n in notes), notes
    assert any("Not the same as clean" in n for n in notes), notes


def test_rulebook_without_a_block_is_also_a_skip():
    """Phandalin declares no bookkeeping register. Absent, not inert."""
    config = parse_config(PHANDALIN_RULEBOOK, source="voice/_genre.md")
    assert config.bookkeeping is None
    _, _, notes = _lint("## Brewbarry — Scene 01\n\nI filed it.\n", config)
    assert any("voice/_genre.md" in n for n in notes), notes


def test_missing_genre_file_is_reported_not_swallowed():
    config = load_config("/nonexistent/voice/_genre.md")
    assert config.bookkeeping is None
    _, _, notes = _lint("## Daz — Scene 01\n\nnothing here\n", config)
    assert any("does not exist" in n for n in notes), notes


# --- bookkeeping: with a rulebook, the OOTA rules still hold ---

def test_unlicensed_filer_is_an_error_when_the_rulebook_says_so():
    config = parse_config(OOTA_RULEBOOK)
    assert config.bookkeeping == Bookkeeping(
        licensed=("grygum", "daz"), unlicensed=("thorin", "zalthir"),
        per_section_cap=1, doc_sections_cap=2,
    )
    errors, _, _ = _lint("## Thorin — Scene 01\n\nI filed it away.\n", config)
    assert any("cross-pollination" in e and "Thorin" in e for e in errors), errors


def test_licensed_filer_within_cap_is_clean():
    config = parse_config(OOTA_RULEBOOK)
    errors, warns, _ = _lint("## Grygum — Scene 01\n\nI filed that thought for later.\n", config)
    assert (errors, warns) == ([], [])


def test_licensed_filer_over_the_per_section_cap_warns():
    config = parse_config(OOTA_RULEBOOK)
    text = "## Grygum — Scene 01\n\nI filed it. Later I filed the other one.\n"
    _, warns, _ = _lint(text, config)
    assert any("density" in w and "Grygum" in w for w in warns), warns


def test_doc_level_convergence_uses_the_rulebook_cap():
    config = parse_config(OOTA_RULEBOOK)
    text = ("## Grygum — Scene 01\n\nI filed it.\n"
            "\n## Daz — Scene 02\n\nI filed it.\n"
            "\n## Buppido — Scene 03\n\nI filed it.\n")
    errors, _, _ = _lint(text, config)
    assert any("convergence" in e and "cap is 2" in e for e in errors), errors


def test_third_person_filing_is_not_the_tic():
    config = parse_config(OOTA_RULEBOOK)
    text = "## Thorin — Scene 01\n\nThe scholars file a grievance every tenday.\n"
    errors, warns, _ = _lint(text, config)
    assert (errors, warns) == ([], [])


# --- a hand-authored block is campaign content: malformed input degrades, never crashes ---

@pytest.mark.parametrize("body,fragment", [
    ("bookkeeping:\n  licensed: [daz\n", "not valid YAML"),
    ("bookkeeping: 7\n", "must be a mapping"),
    ("bookkeeping:\n  licensed: [daz]\n  per_section_cap: nope\n", "per_section_cap"),
    ("bookkeeping:\n  licensed: [daz]\n  typo_key: 1\n", "unrecognised bookkeeping key"),
    ("nonsense_top_level: 1\n", "unrecognised voice_lint key"),
])
def test_malformed_block_is_reported_and_does_not_raise(body, fragment):
    config = parse_config(f"```yaml voice_lint\n{body}```\n")
    assert any(fragment in p for p in config.problems), config.problems
    _, _, notes = _lint("## Daz — Scene 01\n\ntext\n", config)
    assert any("[config]" in n for n in notes), notes


def test_a_yaml_error_never_falls_back_to_another_campaigns_rules():
    """Degrading to defaults would resurrect the bug: silent OOTA rules elsewhere."""
    config = parse_config("```yaml voice_lint\nbookkeeping:\n  licensed: [daz\n```\n")
    assert config.bookkeeping is None
    errors, _, _ = _lint("## Thorin — Scene 01\n\nI filed it.\n", config)
    assert errors == []


def test_block_indented_under_a_list_item_still_parses():
    """The block belongs beside the prose rule it encodes, which means indented."""
    rulebook = (
        "- **Bookkeeping verbs are per-character AND rate-limited.**\n"
        "  - **Thorin:** *noted, clocked.* He does NOT *file*.\n"
        "  - The machine-checkable subset:\n"
        "\n"
        "    ```yaml voice_lint\n"
        "    bookkeeping:\n"
        "      licensed:          [grygum, daz]\n"
        "      unlicensed:        [thorin, zalthir]\n"
        "      per_section_cap:   1\n"
        "      doc_sections_cap:  2\n"
        "    ```\n"
        "\n"
        "- Preserve the kuo-toan orthography.\n"
    )
    config = parse_config(rulebook)
    assert config.problems == (), config.problems
    assert config.bookkeeping == Bookkeeping(
        licensed=("grygum", "daz"), unlicensed=("thorin", "zalthir"),
        per_section_cap=1, doc_sections_cap=2,
    )


def test_empty_config_is_the_default_and_checks_nothing_silently_absent():
    config = LintConfig()
    assert config.bookkeeping is None
    assert config.cap_for("the_shape_of") == 1
