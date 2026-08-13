"""A `*_smoothed/` layer must not claim `## Verbatim moments` (#304).

`session_doc/io.py` binds a moments heading to what it promises (#250 R5):
`## Verbatim moments` says *these are the tape's words*, and a smoothing pass
edits them, so the smoothed layer renames its heading to `## Voiced moments`
rather than carrying a claim it cannot keep. Measured on ch46, smoothing more
than doubles the unverified rate — the two layers cannot promise the same thing.

Nothing enforced it at either end. Phandalin's `scene_extractions_smoothed/`
heads every file `## Verbatim moments` while its frontmatter correctly declares
`source: voice-smoothed`, and that directory is what
`paths.scene_extractions_dir` points at — so quote verification measures edited
prose against the tape as though it were a transcript, on the campaign where
smoothing is standard.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_doc.io import (  # noqa: E402
    is_smoothed_dir,
    load_scene_extractions,
    smoothed_claim_problems,
    warn_if_smoothed_claims_verbatim,
)

VERBATIM = """---
scene: Scene One
source: voice-smoothed
from: ../scene_extractions/01_scene_one.md
---

## Scene summary (from gm-assist, verbatim)

The party arrives.

## Verbatim moments

Soma: "We should wait."
"""

VOICED = VERBATIM.replace("## Verbatim moments", "## Voiced moments")

# The raw Stage-2 layer: no smoothing stamp. `## Verbatim moments` is CORRECT
# here — that IS the tape's words.
RAW = VERBATIM.replace("source: voice-smoothed\n", "").replace(
    "from: ../scene_extractions/01_scene_one.md\n", "")

# A smoothed file with no `## Scene summary`. `split_scene_sections` returns
# CLAIM_NONE for this shape, but `parse_scene_quotes` falls back to treating the
# whole body as the moments section — so every quote IS verified as verbatim.
NO_SUMMARY = """---
scene: Scene One
source: voice-smoothed
---

## Verbatim moments

Soma: "We should wait."
"""


def _dir(tmp_path: Path, name: str, **files: str) -> Path:
    d = tmp_path / name
    d.mkdir()
    for stem, body in files.items():
        (d / f"{stem}.md").write_text(body, encoding="utf-8")
    return d


def test_smoothed_dir_claiming_verbatim_is_reported(tmp_path):
    d = _dir(tmp_path, "scene_extractions_smoothed",
             **{"01_scene_one": VERBATIM, "02_scene_two": VERBATIM})

    assert smoothed_claim_problems(d) == ["01_scene_one.md", "02_scene_two.md"]


def test_smoothed_dir_claiming_voiced_is_clean(tmp_path):
    d = _dir(tmp_path, "scene_extractions_smoothed",
             **{"01_scene_one": VOICED, "02_scene_two": VOICED})

    assert smoothed_claim_problems(d) == []


def test_a_mixed_layer_reports_only_the_offenders(tmp_path):
    d = _dir(tmp_path, "scene_extractions_smoothed",
             **{"01_scene_one": VOICED, "02_scene_two": VERBATIM})

    assert smoothed_claim_problems(d) == ["02_scene_two.md"]


def test_the_raw_layer_is_never_reported(tmp_path):
    """`## Verbatim moments` in the raw extraction layer is correct — that IS
    the tape's words. The claim is only wrong once something has edited them."""
    d = _dir(tmp_path, "scene_extractions",
             **{"01_scene_one": RAW, "02_scene_two": RAW})

    assert smoothed_claim_problems(d) == []
    assert not is_smoothed_dir(d)


def test_frontmatter_is_authoritative_when_the_directory_is_renamed(tmp_path):
    """The signal that survives a copy.

    `/voice-smooth` stamps `source: voice-smoothed` on every file it writes. A
    layer copied or renamed into `scene_extractions/` — which is where obelisk
    and out-of-the-abyss point — loses the directory name but keeps the stamp,
    and keying detection on the directory alone would miss it entirely.
    """
    d = _dir(tmp_path, "scene_extractions", **{"01_scene_one": VERBATIM})

    assert not is_smoothed_dir(d)
    assert smoothed_claim_problems(d) == ["01_scene_one.md"]


def test_a_file_with_no_scene_summary_is_still_caught(tmp_path):
    """`split_scene_sections` returns CLAIM_NONE without a `## Scene summary`,
    so deferring to it would report this file clean — while `parse_scene_quotes`
    treats its whole body as moments and verifies every quote as verbatim. The
    file most in need of the warning was the one reported fine."""
    d = _dir(tmp_path, "scene_extractions_smoothed", **{"01_scene_one": NO_SUMMARY})

    assert smoothed_claim_problems(d) == ["01_scene_one.md"]


def test_an_unreadable_file_cannot_abort_a_render(tmp_path, capsys):
    """This runs on `load_scene_extractions`'s hot path. A diagnostic must
    never be the thing that stops a narration run, so a file it cannot decode
    is skipped rather than raised on."""
    d = _dir(tmp_path, "scene_extractions_smoothed", **{"01_scene_one": VERBATIM})
    (d / "02_scene_two.md").write_bytes("scene: caf\xe9\n".encode("latin-1"))

    assert smoothed_claim_problems(d) == ["01_scene_one.md"]


def test_only_files_the_loader_would_read_are_scanned(tmp_path):
    """A stray `notes.md` or a sibling artifact is not a scene extraction, and
    counting it would send the GM after a file nothing verifies."""
    d = _dir(tmp_path, "scene_extractions_smoothed", **{"01_scene_one": VOICED})
    (d / "notes.md").write_text(VERBATIM, encoding="utf-8")
    (d / "plan.md").write_text(VERBATIM, encoding="utf-8")

    assert smoothed_claim_problems(d) == []


def test_a_scaffold_shadows_its_raw_sibling(tmp_path):
    """`load_scene_extractions` prefers `NN_<slug>.scaffold.md`, so that is the
    file whose claim matters — the raw sibling is not what gets rendered."""
    d = _dir(tmp_path, "scene_extractions_smoothed", **{"01_scene_one": VERBATIM})
    (d / "01_scene_one.scaffold.md").write_text(VOICED, encoding="utf-8")

    assert smoothed_claim_problems(d) == []


def test_sibling_artifacts_are_skipped(tmp_path):
    d = _dir(tmp_path, "scene_extractions_smoothed", **{"01_scene_one": VOICED})
    (d / "plan.md").write_text(VERBATIM, encoding="utf-8")
    (d / "consistency_report.md").write_text(VERBATIM, encoding="utf-8")
    (d / "_notes.md").write_text(VERBATIM, encoding="utf-8")

    assert smoothed_claim_problems(d) == []


def test_a_missing_directory_is_not_an_error(tmp_path):
    assert smoothed_claim_problems(tmp_path / "nope_smoothed") == []


def test_the_warning_names_the_files_and_the_consequence(tmp_path, capsys):
    d = _dir(tmp_path, "scene_extractions_smoothed", **{"01_scene_one": VERBATIM})

    warn_if_smoothed_claims_verbatim(d)

    err = capsys.readouterr().err
    assert "01_scene_one.md" in err
    assert "voice-smoothed" in err
    assert "Voiced moments" in err          # names the fix
    assert "Nothing is rewritten" in err    # and its own limits
    # The remedy must not over-promise. Renaming drops the file out of the
    # CONTRACT axis (R1/R3); it does NOT change the verdict counts — a voiced
    # layer is "outside the contract (R5), still classified". Saying otherwise
    # sends the GM to rename seven headings and get identical numbers.
    assert "does NOT change the verdict counts" in err
    assert "R1/R3" in err


def test_the_warning_caps_the_file_list(tmp_path, capsys):
    d = _dir(tmp_path, "scene_extractions_smoothed",
             **{f"{i:02d}_scene": VERBATIM for i in range(1, 9)})

    warn_if_smoothed_claims_verbatim(d)

    err = capsys.readouterr().err
    assert "(+3 more)" in err


def test_loading_a_smoothed_layer_warns_but_still_loads(tmp_path, capsys):
    """Detection only — a mislabelled layer is still usable, and Pass 5 must
    keep working on it. Refusing here would stop Phandalin rendering today."""
    d = _dir(tmp_path, "scene_extractions_smoothed",
             **{"01_scene_one": VERBATIM})

    scenes = load_scene_extractions(d)

    assert len(scenes) == 1
    assert scenes[0]["name"] == "Scene One"
    assert 'Soma: "We should wait."' in scenes[0]["moments"]
    assert "still head their moments section" in capsys.readouterr().err


def test_loading_the_raw_layer_is_silent(tmp_path, capsys):
    d = _dir(tmp_path, "scene_extractions", **{"01_scene_one": RAW})

    load_scene_extractions(d)

    assert capsys.readouterr().err == ""
