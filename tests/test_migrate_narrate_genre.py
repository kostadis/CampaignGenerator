"""Tests for ``server/migrate_narrate_genre.py`` — #276 fix 2's relocation CLI.

The interesting behaviour is not the happy path; it is **where it refuses**.
Two copies of a document disagreeing is not a merge problem, it is a question
about which one is the campaign's real rulebook, and that is a GM decision.

The cases here are the ones the live trees actually present:

* Phandalin: paste and file agree modulo whitespace -> migrate, file wins.
* out-of-the-abyss: paste is flattened **and** has drifted (0.999 similarity)
  -> refuse, because the drift is content, not just lost newlines.
* A pure flattening with no content change -> migrate silently; demanding a
  ruling there would be noise, since it is the same rulebook badly stored.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.migrate_narrate_genre import main  # noqa: E402

RULEBOOK = "\n".join([
    "GENRE & REGISTER",
    "",
    "First-person noir fantasy memoir, present tense.",
    "Each narrator keeps their own vocabulary.",
    "Bookkeeping: at most two ledger beats per narrator per document.",
])
FLATTENED = " ".join(RULEBOOK.split())


def _campaign(tmp_path: Path, session_doc: dict | None, rulebook: str | None = None):
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "config.yaml").write_text(
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
        encoding="utf-8",
    )
    if session_doc is not None:
        (tmp_path / "config" / "session_doc.yaml").write_text(
            yaml.safe_dump(session_doc, sort_keys=False), encoding="utf-8"
        )
    if rulebook is not None:
        (tmp_path / "voice").mkdir(parents=True, exist_ok=True)
        (tmp_path / "voice" / "_genre.md").write_text(rulebook, encoding="utf-8")
    return tmp_path


def _run(tmp_path: Path, *extra: str) -> int:
    return main(["--campaign-dir", str(tmp_path), *extra])


def _yaml(tmp_path: Path) -> dict:
    return yaml.safe_load(
        (tmp_path / "config" / "session_doc.yaml").read_text(encoding="utf-8")
    )


def _rulebook(tmp_path: Path) -> str:
    return (tmp_path / "voice" / "_genre.md").read_text(encoding="utf-8")


# ── The happy paths ──────────────────────────────────────────────────────

def test_identical_copies_migrate_and_the_file_wins(tmp_path, capsys):
    """The Phandalin case: paste == file, so relocation is mechanical."""
    _campaign(tmp_path, {"narrate": {"tokens": 9000, "genre": RULEBOOK}}, RULEBOOK)

    assert _run(tmp_path) == 0

    cfg = _yaml(tmp_path)
    assert cfg["paths"]["genre_file"] == "voice/_genre.md"
    assert "genre" not in cfg["narrate"]
    assert cfg["narrate"]["tokens"] == 9000        # untouched
    assert _rulebook(tmp_path) == RULEBOOK        # file not rewritten
    out = capsys.readouterr().out
    assert "identical to the paste" in out


def test_pure_flattening_is_not_a_conflict(tmp_path, capsys):
    """Newlines lost on the way into YAML is the same rulebook, badly stored.

    Demanding a GM ruling here would be noise — and it is the difference
    between #249's damage and real divergence.
    """
    _campaign(tmp_path, {"narrate": {"genre": FLATTENED}}, RULEBOOK)

    assert _run(tmp_path) == 0

    assert _yaml(tmp_path)["paths"]["genre_file"] == "voice/_genre.md"
    # The file keeps its line structure; the flattened copy is discarded.
    assert _rulebook(tmp_path) == RULEBOOK
    assert "\n" in _rulebook(tmp_path)


def test_no_file_yet_writes_one_from_the_paste(tmp_path, capsys):
    _campaign(tmp_path, {"narrate": {"genre": RULEBOOK}}, rulebook=None)

    assert _run(tmp_path) == 0

    assert _rulebook(tmp_path) == RULEBOOK + "\n"
    assert _yaml(tmp_path)["paths"]["genre_file"] == "voice/_genre.md"
    assert "written" in capsys.readouterr().out


def test_writing_a_flattened_paste_warns_that_the_file_is_unreadable(tmp_path, capsys):
    # Sized like the real out-of-the-abyss value (16,303 chars on one line), not
    # like the short fixture: a genuinely short one-line directive is a legitimate
    # rulebook and must not draw a warning.
    long_flattened = (FLATTENED + " ") * 20
    assert len(long_flattened) > 200 and "\n" not in long_flattened
    _campaign(tmp_path, {"narrate": {"genre": long_flattened}}, rulebook=None)

    assert _run(tmp_path) == 0

    err = capsys.readouterr().err
    assert "no newlines" in err
    assert "flattened" in err
    assert "#249" in err


def test_a_short_one_line_directive_draws_no_warning(tmp_path, capsys):
    """The complement: a genuine one-line directive is a legitimate rulebook."""
    _campaign(tmp_path, {"narrate": {"genre": "First-person noir memoir"}},
              rulebook=None)

    assert _run(tmp_path) == 0

    assert "flattened" not in capsys.readouterr().err
    assert _rulebook(tmp_path).strip() == "First-person noir memoir"


def test_existing_file_with_nothing_pasted_just_gets_pointed_at(tmp_path, capsys):
    _campaign(tmp_path, {"narrate": {"tokens": 9000}}, RULEBOOK)

    assert _run(tmp_path) == 0

    assert _yaml(tmp_path)["paths"]["genre_file"] == "voice/_genre.md"
    assert "pointed the editor at the existing rulebook" in capsys.readouterr().out


def test_nothing_anywhere_is_a_no_op(tmp_path, capsys):
    _campaign(tmp_path, {"narrate": {"tokens": 9000}}, rulebook=None)

    assert _run(tmp_path) == 0
    assert "nothing to migrate" in capsys.readouterr().out
    assert _yaml(tmp_path).get("paths", {}).get("genre_file") is None


def test_second_run_is_a_no_op(tmp_path, capsys):
    _campaign(tmp_path, {"narrate": {"genre": RULEBOOK}}, RULEBOOK)
    assert _run(tmp_path) == 0
    capsys.readouterr()

    assert _run(tmp_path) == 0
    assert "already set" in capsys.readouterr().out


# ── Where it refuses ─────────────────────────────────────────────────────

def test_divergent_copies_refuse_and_change_nothing(tmp_path, capsys):
    """The out-of-the-abyss case: flattened AND drifted."""
    drifted = FLATTENED.replace("present tense", "past tense")
    _campaign(tmp_path, {"narrate": {"genre": drifted}}, RULEBOOK)

    assert _run(tmp_path) == 1

    err = capsys.readouterr().err
    assert "REFUSING" in err
    assert "similarity" in err
    assert "--prefer-file" in err and "--prefer-yaml" in err
    # Nothing moved: both copies are exactly as they were.
    assert _yaml(tmp_path)["narrate"]["genre"] == drifted
    assert _rulebook(tmp_path) == RULEBOOK
    assert _yaml(tmp_path).get("paths", {}).get("genre_file") is None


def test_refusal_reports_words_not_lines(tmp_path, capsys):
    """A line diff is useless when the paste is flattened — every line differs.

    The real out-of-the-abyss case: the only difference between the two copies
    was the file's H1 title, and a line diff buried that under the whole
    document. A word diff names it in one line, which is what makes
    ``--prefer-file`` an obvious call rather than a coin flip.
    """
    titled = "# Campaign Genre\n\n" + RULEBOOK
    _campaign(tmp_path, {"narrate": {"genre": FLATTENED}}, titled)

    assert _run(tmp_path) == 1

    err = capsys.readouterr().err
    assert "words, not lines" in err
    assert "only in the file:" in err
    assert "# Campaign Genre" in err
    # The rest of the document is identical, so it must NOT be echoed back.
    assert "Bookkeeping: at most two ledger beats" not in err.split("only in the file:")[1]


def test_prefer_file_keeps_the_file(tmp_path, capsys):
    drifted = FLATTENED.replace("present tense", "past tense")
    _campaign(tmp_path, {"narrate": {"genre": drifted}}, RULEBOOK)

    assert _run(tmp_path, "--prefer-file") == 0

    assert _rulebook(tmp_path) == RULEBOOK
    assert "genre" not in _yaml(tmp_path)["narrate"]
    assert "--prefer-file" in capsys.readouterr().out


def test_prefer_yaml_overwrites_the_file(tmp_path):
    drifted = RULEBOOK.replace("present tense", "past tense")
    _campaign(tmp_path, {"narrate": {"genre": drifted}}, RULEBOOK)

    assert _run(tmp_path, "--prefer-yaml") == 0

    assert _rulebook(tmp_path).strip() == drifted
    assert "genre" not in _yaml(tmp_path)["narrate"]


def test_prefer_flags_are_mutually_exclusive(tmp_path, capsys):
    _campaign(tmp_path, {"narrate": {"genre": RULEBOOK}}, RULEBOOK)
    assert _run(tmp_path, "--prefer-file", "--prefer-yaml") == 2
    assert "mutually exclusive" in capsys.readouterr().err


# ── Profiles: the third copy (#220) ──────────────────────────────────────

def test_profile_knob_becomes_a_path(tmp_path):
    _campaign(
        tmp_path,
        {
            "narrate": {"genre": RULEBOOK},
            "profiles": [
                {"name": "Fast", "knobs": {"narrate_tokens": 4000,
                                           "narration_genre": RULEBOOK}},
            ],
        },
        RULEBOOK,
    )

    assert _run(tmp_path) == 0

    knobs = _yaml(tmp_path)["profiles"][0]["knobs"]
    assert knobs["narration_genre_file"] == "voice/_genre.md"
    assert "narration_genre" not in knobs
    assert knobs["narrate_tokens"] == 4000  # other knobs survive


def test_divergent_profile_genre_refuses(tmp_path, capsys):
    _campaign(
        tmp_path,
        {
            "narrate": {"genre": RULEBOOK},
            "profiles": [
                {"name": "Grimdark", "knobs": {
                    "narration_genre": RULEBOOK.replace("noir", "grimdark")}},
            ],
        },
        RULEBOOK,
    )

    assert _run(tmp_path) == 1

    err = capsys.readouterr().err
    assert "REFUSING" in err
    assert "Grimdark" in err
    assert "needs its own file" in err
    assert "--drop-profile-genre" in err
    assert "genre" in _yaml(tmp_path)["narrate"]  # nothing written


def test_drop_profile_genre_discards_it_loudly(tmp_path, capsys):
    _campaign(
        tmp_path,
        {
            "narrate": {"genre": RULEBOOK},
            "profiles": [
                {"name": "Grimdark", "knobs": {
                    "narration_genre": RULEBOOK.replace("noir", "grimdark")}},
            ],
        },
        RULEBOOK,
    )

    assert _run(tmp_path, "--drop-profile-genre") == 0

    knobs = _yaml(tmp_path)["profiles"][0]["knobs"]
    assert knobs["narration_genre_file"] == "voice/_genre.md"
    out = capsys.readouterr().out
    assert "DISCARDED" in out and "Grimdark" in out


def test_profiles_carrying_genre_with_no_paste_and_no_file_refuses(tmp_path, capsys):
    _campaign(
        tmp_path,
        {"profiles": [{"name": "Fast", "knobs": {"narration_genre": RULEBOOK}}]},
        rulebook=None,
    )

    assert _run(tmp_path) == 1
    assert "no rulebook" in capsys.readouterr().err


# ── Custom target ────────────────────────────────────────────────────────

def test_custom_genre_file_path(tmp_path):
    _campaign(tmp_path, {"narrate": {"genre": RULEBOOK}}, rulebook=None)

    assert _run(tmp_path, "--genre-file", "docs/register.md") == 0

    assert (tmp_path / "docs" / "register.md").is_file()
    assert _yaml(tmp_path)["paths"]["genre_file"] == "docs/register.md"
