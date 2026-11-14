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

The CG#294 review then found four ways back into that same failure — a check that did
not run, reported as clean:

- a bookkeeping block the parser only half understood still built a ``Bookkeeping``,
  so empty name tuples matched nobody and no skip note fired;
- ``SECTION_RE`` captured one word, so a two-word narrator never matched its rule;
- an unreadable ``--genre-file`` exited 0;
- a cap of ``0`` was refused and replaced by the *looser* default.

Every test below the "review" divider pins one of those shut.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

import session_doc.voice_lint as _vl
from session_doc import voice_lint as voice_lint_module
from session_doc.voice_lint import (
    PORTRAIT_RE,
    TAXONOMY_RE,
    Bookkeeping,
    LintConfig,
    lint,
    load_config,
    parse_config,
    split_sections,
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


def _run_cli(*argv):
    """Invoke the CLI in a subprocess, pinned to *this* checkout.

    The editable install's .pth hardcodes the main checkout, so a bare `python -m` from a
    worktree can silently exercise main's copy. Deriving the root from the module under
    test makes a green run proof that this branch was tested.
    """
    root = Path(_vl.__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": str(root)}
    return subprocess.run([sys.executable, "-m", "session_doc.voice_lint", *argv],
                          capture_output=True, text=True, cwd=root, env=env)


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


# ── CG#294 review ────────────────────────────────────────────────────────────────
# Four routes back to "the check did not run, and the run looked clean".

# --- 1. a half-understood block must skip, not enforce blanks ---

@pytest.mark.parametrize("body", [
    "bookkeeping:\n  licensed: {a: b}\n  unlicensed: 5\n",   # neither list parses
    "bookkeeping:\n  licensed: [grygum]\n  unlicensed: 5\n",  # only one fails
    "bookkeeping:\n  licensed: [grygum]\n  typo_key: 1\n",    # a key nobody recognises
    "bookkeeping:\n  licensed: [grygum]\n  per_section_cap: nope\n",
])
def test_a_partly_understood_bookkeeping_block_skips_rather_than_enforcing_blanks(body):
    """The review's finding 1: Bookkeeping(licensed=(), unlicensed=()) matches no narrator.

    It enforced nothing, said nothing, and exited 0 — the exact F4 shape, reached from
    inside a rulebook that *did* try to declare a register.
    """
    config = parse_config(f"```yaml voice_lint\n{body}```\n")
    assert config.bookkeeping is None, "a block the parser could not use must not enforce"
    assert config.problems
    _, _, notes = _lint("## Thorin — Scene 01\n\nI filed it away.\n", config)
    assert any("skipped" in n and "did not parse cleanly" in n for n in notes), notes


def test_a_bookkeeping_block_naming_no_narrators_is_a_skip():
    """`bookkeeping: {}` produced a Bookkeeping with no names and not even a note."""
    config = parse_config("```yaml voice_lint\nbookkeeping: {}\n```\n")
    assert config.bookkeeping is None
    _, _, notes = _lint("## Thorin — Scene 01\n\nI filed it away.\n", config)
    assert any("names no narrators" in n for n in notes), notes


def test_unlicensed_alone_is_a_complete_register():
    """"Thorin does not file" is a whole rule. Requiring both lists would over-skip."""
    config = parse_config("```yaml voice_lint\nbookkeeping:\n  unlicensed: [thorin]\n```\n")
    assert config.bookkeeping == Bookkeeping(licensed=(), unlicensed=("thorin",))
    errors, _, _ = _lint("## Thorin — Scene 01\n\nI filed it away.\n", config)
    assert any("cross-pollination" in e for e in errors), errors


# --- 2. narrator names of more than one word ---

@pytest.mark.parametrize("heading,expected", [
    ("## Daz — Scene 01", "Daz"),
    ("## Unla Kee — Scene 01", "Unla Kee"),
    ("## Unla Kee – Scene 01", "Unla Kee"),      # en-dash
    ("## Unla Kee - Scene 01", "Unla Kee"),      # hyphen, spaced
    ("## Jean-Luc — Scene 01", "Jean-Luc"),      # hyphen inside a name, unspaced
    ("## Grygum", "Grygum"),
    ("## Lord Zymorven — Scene 12", "Lord Zymorven"),
])
def test_section_heading_keeps_the_whole_narrator_name(heading, expected):
    assert split_sections(f"{heading}\n\nbody\n")[0][0] == expected


def test_a_two_word_narrator_matches_its_rulebook_rule():
    """The review's finding 2: `(\\w+)` gave "Unla", the rulebook said "unla kee"."""
    config = parse_config(
        "```yaml voice_lint\nbookkeeping:\n"
        "  licensed:   [orsik]\n  unlicensed: ['unla kee']\n```\n")
    errors, _, _ = _lint("## Unla Kee — Scene 01\n\nI filed it away.\n", config)
    assert any("cross-pollination" in e and "Unla Kee" in e for e in errors), errors


def test_a_listed_name_does_not_claim_a_longer_one():
    """`startswith` let `daz` flag a narrator called Dazzle."""
    config = parse_config("```yaml voice_lint\nbookkeeping:\n  unlicensed: [daz]\n```\n")
    errors, _, _ = _lint("## Dazzle — Scene 01\n\nI filed it away.\n", config)
    assert errors == [], errors


def test_a_qualified_heading_still_matches_on_a_whole_word_prefix():
    config = parse_config("```yaml voice_lint\nbookkeeping:\n  unlicensed: [grygum]\n```\n")
    errors, _, _ = _lint("## Grygum the Deep Gnome — Scene 01\n\nI filed it.\n", config)
    assert any("cross-pollination" in e for e in errors), errors


# --- 3. an unreadable --genre-file is a usage error, not a skip ---

def test_cli_exits_2_when_the_named_rulebook_cannot_be_read(tmp_path):
    """The review's finding 3: a path typo turned a gating step green with checks off."""
    doc = tmp_path / "n.md"
    doc.write_text("## Thorin — Scene 01\n\nI filed it away.\n")
    proc = _run_cli(str(doc), "--genre-file", str(tmp_path / "nope" / "_genre.md"))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "does not exist" in proc.stderr


def test_cli_exits_0_when_no_rulebook_is_named(tmp_path):
    """Omitting --genre-file is a legitimate skip and stays non-fatal."""
    doc = tmp_path / "n.md"
    doc.write_text("## Thorin — Scene 01\n\nI filed it away.\n")
    proc = _run_cli(str(doc))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "skipped" in proc.stdout


def test_cli_prints_rulebook_problems_once_not_once_per_file(tmp_path):
    genre = tmp_path / "_genre.md"
    genre.write_text("```yaml voice_lint\nbookkeeping:\n  licensed: [daz\n```\n")
    docs = []
    for i in range(3):
        d = tmp_path / f"n{i}.md"
        d.write_text("## Daz — Scene 01\n\nnothing here\n")
        docs.append(str(d))
    proc = _run_cli(*docs, "--genre-file", str(genre))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # The rulebook's own complaint appears once for the run. Each document still gets its
    # own skip note — that one is per-document by design.
    assert proc.stdout.count("[config]") == 1, proc.stdout
    assert proc.stdout.count("[skipped]") == 3, proc.stdout


# --- 4. a cap of 0 is the strictest setting, not an error ---

def test_a_zero_cap_is_honoured_not_replaced_by_the_looser_default():
    """The review's finding 4: `per_section_cap: 0` became 1, i.e. laxer than requested."""
    config = parse_config(
        "```yaml voice_lint\nbookkeeping:\n"
        "  licensed: [grygum]\n  per_section_cap: 0\n  doc_sections_cap: 0\n```\n")
    assert config.problems == (), config.problems
    assert config.bookkeeping.per_section_cap == 0
    assert config.bookkeeping.doc_sections_cap == 0
    errors, warns, _ = _lint("## Grygum — Scene 01\n\nI filed it.\n", config)
    assert any("density" in w for w in warns), warns
    assert any("convergence" in e for e in errors), errors


def test_a_negative_cap_is_still_a_problem():
    config = parse_config(
        "```yaml voice_lint\nbookkeeping:\n  licensed: [grygum]\n  per_section_cap: -1\n```\n")
    assert any("per_section_cap" in p for p in config.problems), config.problems
    assert config.bookkeeping is None


# --- 5. the skip note names the actual cause ---

@pytest.mark.parametrize("config_factory,fragment", [
    (lambda: LintConfig(), "no rulebook was given"),
    (lambda: load_config("/nonexistent/voice/_genre.md"), "does not exist"),
    (lambda: parse_config("# no block here\n", source="voice/_genre.md"),
     "has no ```yaml voice_lint block"),
    (lambda: parse_config("```yaml voice_lint\nportable_tics:\n  the_shape_of: 0\n```\n",
                          source="voice/_genre.md"),
     "declares no bookkeeping section"),
])
def test_each_skip_states_its_own_cause(config_factory, fragment):
    """One message for five causes told a GM "no filing register" when the path was a typo."""
    _, _, notes = _lint("## Daz — Scene 01\n\ntext\n", config_factory())
    assert any(fragment in n for n in notes), notes


def test_d4_v1_registry_projects_every_category_without_changing_legacy_api():
    assert voice_lint_module.CHECKER_SCHEMA_VERSION == 1
    assert voice_lint_module.MEASUREMENT_PROFILE == "d4-v1"
    assert {item.key for item in voice_lint_module.D4_CHECK_REGISTRY} == {
        "shape_of", "portable_portrait", "taxonomy", "filing_sections",
        "bookkeeping_per_narrator", "em_dash",
    }
    errors, warnings, notes = voice_lint_module.lint("## Aria — One\n\nThe shape of fear.")
    assert isinstance(errors, list) and isinstance(warnings, list) and isinstance(notes, list)


# ---------------------------------------------------------------------------
# extra_tics — campaign-declared banned constructions (CG#365)
#
# PORTABLE_TICS is the cross-campaign floor, and the Phandalin ch40-48 sweep showed the
# same behavioural-taxonomy MOVE that #246/#251 chased still walking past all three of
# them in shells they cannot see: the simile ("like a man who ..."), the portrait with no
# `who` ("with the quiet deliberation of a man shopping at a market"), and the possessive
# habit ("that particular stillness she gets when ..."). Those are Phandalin's corpus, not
# every campaign's, so they belong in Phandalin's rulebook — which needs the rulebook to
# be able to carry a pattern, not just a cap. The instances below are pinned verbatim from
# docs/chapters/chapter_4*.md so a regex tidy-up cannot quietly reopen the hole.
# ---------------------------------------------------------------------------

PHANDALIN_CH40_48_INSTANCES = [
    "Valphine was moving through the twig blights like a woman who finds this "
    "situation aesthetically appropriate.",
    "He shifted his weight from foot to foot like a man who had misplaced his axe.",
    "Brewbarry confessed like a man laying flowers on a grave.",
    "Vukradin listed his new workings with the quiet deliberation of a man shopping "
    "at a market.",
    "She watched, head tilted, that particular stillness she gets when she's cataloguing.",
    "Vukradin moved toward the bodies with the particular energy he gets when a "
    "principle is at stake.",
]

EXTRA_TICS_BLOCK = """\
```yaml voice_lint
extra_tics:
  like_a_man_who:
    label:   "like-a-man-who"
    pattern: "\\\\blike (?:a|an|the) (?:man|woman|men|women|someone|somebody|person|people|creature)s?\\\\b[^.]{0,60}?(?:\\\\bwho\\\\b|\\\\bwhose\\\\b|ing\\\\b)"
    cap:     0
  of_a_man_no_who:
    label:   "X-of-a-man (no 'who')"
    pattern: "\\\\bthe [\\\\w ]{0,30}? of (?:a|an|the) (?:man|woman|men|women|someone|person|people|creature)s?\\\\b(?![^.]{0,60}\\\\bwho\\\\b)"
    cap:     0
  that_particular_X_he_gets_when:
    label:   "that-particular-X-he-gets-when"
    pattern: "\\\\b(?:that|the) particular [\\\\w' ]{0,30}?\\\\b(?:he|she|they|it)\\\\s+(?:get|gets|use|uses|ha[sd]|do|does)\\\\b"
    cap:     0
```
"""


@pytest.mark.parametrize("line", PHANDALIN_CH40_48_INSTANCES)
def test_extra_tics_catch_every_pinned_ch40_48_instance(line):
    config = parse_config(EXTRA_TICS_BLOCK)
    assert not config.problems, config.problems
    assert any(rx.search(line) for _, _, rx in config.extra_tics), \
        f"no extra tic matched a confirmed ch40-48 instance: {line!r}"


@pytest.mark.parametrize("line", PHANDALIN_CH40_48_INSTANCES)
def test_the_builtin_tics_miss_them_which_is_why_extra_tics_exists(line):
    """Documents the gap the campaign sweep found; without it these read as clean."""
    assert not PORTRAIT_RE.search(line)
    assert not TAXONOMY_RE.search(line)


@pytest.mark.parametrize("line", [
    # A simile whose vehicle is an object or an animal is not person-taxonomy.
    "It came down like a hammer on a nail.",
    "Now it's not my problem, she said, like the tide going out.",
    # Naming one individual is a specific observation, not a class.
    "He fixed it like Brewbarry would.",
    # "particular" used deictically — this gift, not a category of gift.
    "It's not the fire-burst; I spent that particular gift elsewhere.",
    # The portrait shell with `who` is PORTRAIT_RE's job, not of_a_man_no_who's.
    "He spoke with the tone of a man who has given up expecting to be followed.",
])
def test_extra_tics_do_not_over_fire(line):
    config = parse_config(EXTRA_TICS_BLOCK)
    hit = [key for _, key, rx in config.extra_tics if rx.search(line)]
    assert not hit, f"false positive from {hit} on legitimate prose: {line!r}"


def test_extra_tic_hit_is_reported_by_lint_with_its_label():
    config = parse_config(EXTRA_TICS_BLOCK)
    doc = "## Vukradin — Scene 02\n\n" + PHANDALIN_CH40_48_INSTANCES[0] + "\n"
    errors, _, _ = _lint(doc, config)
    assert any("like-a-man-who" in e for e in errors), errors


def test_extra_tic_shorthand_is_a_bare_pattern_string():
    config = parse_config('```yaml voice_lint\nextra_tics:\n  moot: "\\\\bmoot\\\\b"\n```\n')
    assert not config.problems
    assert [key for _, key, _ in config.extra_tics] == ["moot"]
    # No explicit cap means the shared default, so one occurrence warns rather than errors.
    errors, warns, _ = _lint("## Daz\n\nThe point is moot.\n", config)
    assert not errors and any("moot" in w for w in warns)


def test_extra_tic_cannot_shadow_a_builtin_tic():
    """Letting a campaign redefine one of the three floor checks is how #125 happened."""
    config = parse_config(
        '```yaml voice_lint\nextra_tics:\n  the_shape_of: "\\\\bnever-matches\\\\b"\n```\n')
    assert any("shadows a built-in" in p for p in config.problems), config.problems
    assert config.extra_tics == ()
    # The real check still runs.
    errors, warns, _ = _lint("## Daz\n\nI saw the shape of it.\n", config)
    assert any("the shape of" in m for m in errors + warns)


@pytest.mark.parametrize("body,expected", [
    ("extra_tics: [nope]\n", "must be a mapping"),
    ("extra_tics:\n  bad: {cap: 0}\n", "no 'pattern'"),
    ("extra_tics:\n  bad: \"(unclosed\"\n", "does not compile"),
])
def test_a_malformed_extra_tic_is_dropped_loudly_not_crashed_on(body, expected):
    config = parse_config(f"```yaml voice_lint\n{body}```\n")
    assert config.extra_tics == ()
    assert any(expected in p for p in config.problems), config.problems


def test_no_extra_tics_section_is_not_a_problem():
    """OOTA's rulebook declares none; that is a legitimate campaign, not a broken one."""
    config = parse_config(OOTA_RULEBOOK)
    assert config.extra_tics == ()
    assert not any("extra_tics" in p for p in config.problems)
