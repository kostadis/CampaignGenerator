"""assemble must not put the same scene in a chapter twice (#429).

`collect_scene_files` dedupes on the filename stem. That correctly collapses the
`foo.md` / `foo.scrubbed.md` pair it was written for, but scene identity is the
`scene:` frontmatter, not the slug — so two renders of one scene saved under
different titles are two stems, both survive collection, and both land in the
assembled document under the same number.

The audit in `docs/design/NarrationPipelineAudit.md` got seven files for five
scenes that way, and `Assembled 7 scene(s)` reads like success: the duplicate
numbers are visible in the left column if you look, nothing warns, and the exit
status is 0. That is how a discarded draft ships as canon — renaming a
regenerated scene, the natural thing to do when trying a second title, is enough
to reintroduce the rejected one.

Refusal rather than a warning, and rather than picking one: which revision is
final is knowledge only the operator has. The same convention as `sd_plan`
refusing an empty narrator pool instead of falling back to the roster.

Reuses the subprocess harness pattern from the sibling frontmatter tests.
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: The reproduction from #429 — seven files, five distinct `scene:` values,
#: scenes 1 and 5 each with a second file under an alternate title.
COLLIDING = [
    (1, "session_doc_scene_01_rumors_and_preparations_at_the_common_chord.md"),
    (1, "session_doc_scene_01_rumors_at_the_common_chord.md"),
    (2, "session_doc_scene_02_the_sewer_stakeout.md"),
    (3, "session_doc_scene_03_encounter_in_the_sewers.md"),
    (4, "session_doc_scene_04_the_stakeout_of_denvar.md"),
    (5, "session_doc_scene_05_the_dead_drop_at_the_house_of_a_thousand_faces.md"),
    (5, "session_doc_scene_05_the_house_of_a_thousand_faces.md"),
]


def _scenes(dir_path: Path, spec) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    for scene, name in spec:
        (dir_path / name).write_text(
            f"---\nscene: {scene}\nscene_name: S{scene}\nnarrator: Soma\n---\n"
            f"Prose for {name}.\n", encoding="utf-8")
    return dir_path


def _run(narr: Path, out: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "session_doc/assemble.py"), str(narr),
         "--output", str(out), *extra],
        capture_output=True, text=True, cwd=REPO)


def test_two_files_claiming_one_scene_are_refused(tmp_path):
    narr = _scenes(tmp_path / "summaries" / "20260706" / "narration", COLLIDING)
    out = tmp_path / "out.md"

    result = _run(narr, out)

    assert result.returncode == 1, result.stdout
    assert not out.exists(), "a refused run must not leave a partial chapter"


def test_the_refusal_names_every_competing_file(tmp_path):
    """The operator has to rule on this, so the message has to be rulable from:
    which scenes, which files, and what to do about it."""
    narr = _scenes(tmp_path / "summaries" / "20260706" / "narration", COLLIDING)

    err = _run(narr, tmp_path / "out.md").stderr

    assert "scene 1:" in err and "scene 5:" in err
    for scene, name in COLLIDING:
        if scene in (1, 5):
            assert name in err, name
    # ...and the uncontested scenes are not dragged into it.
    assert "scene 2:" not in err
    assert "--use" in err


def test_a_clean_directory_still_assembles(tmp_path):
    """The guard must cost nothing when there is nothing to rule on."""
    clean = [(s, n) for s, n in COLLIDING
             if n not in {"session_doc_scene_01_rumors_at_the_common_chord.md",
                          "session_doc_scene_05_the_house_of_a_thousand_faces.md"}]
    narr = _scenes(tmp_path / "summaries" / "20260706" / "narration", clean)
    out = tmp_path / "out.md"

    result = _run(narr, out)

    assert result.returncode == 0, result.stderr
    assert "Assembled 5 scene(s)" in result.stdout
    assert out.exists()


def test_use_selects_the_final_revision(tmp_path):
    narr = _scenes(tmp_path / "summaries" / "20260706" / "narration", COLLIDING)
    out = tmp_path / "out.md"
    keep_1 = "session_doc_scene_01_rumors_at_the_common_chord.md"
    keep_5 = "session_doc_scene_05_the_house_of_a_thousand_faces.md"

    result = _run(narr, out, "--use", keep_1, "--use", keep_5)

    assert result.returncode == 0, result.stderr
    assert "Assembled 5 scene(s)" in result.stdout
    body = out.read_text(encoding="utf-8")
    assert f"Prose for {keep_1}." in body
    assert f"Prose for {keep_5}." in body
    # The rejected drafts are the whole point — they must not be in the chapter.
    assert "rumors_and_preparations" not in body
    assert "the_dead_drop" not in body


def test_use_on_only_one_of_two_collisions_still_refuses(tmp_path):
    """Ruling on one scene is not ruling on the other."""
    narr = _scenes(tmp_path / "summaries" / "20260706" / "narration", COLLIDING)

    result = _run(narr, tmp_path / "out.md", "--use",
                  "session_doc_scene_01_rumors_at_the_common_chord.md")

    assert result.returncode == 1
    assert "scene 5:" in result.stderr
    assert "scene 1:" not in result.stderr


def test_use_naming_both_sides_of_one_collision_refuses(tmp_path):
    """Selecting both is not a selection, and must not silently take the first."""
    narr = _scenes(tmp_path / "summaries" / "20260706" / "narration", COLLIDING)

    result = _run(narr, tmp_path / "out.md",
                  "--use", "session_doc_scene_01_rumors_at_the_common_chord.md",
                  "--use", "session_doc_scene_01_rumors_and_preparations_at_the_common_chord.md",
                  "--use", "session_doc_scene_05_the_house_of_a_thousand_faces.md")

    assert result.returncode == 1
    assert "names 2 of these" in result.stderr


def test_a_stale_use_fails_loudly(tmp_path):
    """A --use naming a file that is no longer there must not quietly select
    nothing — the same reason transcript_corrections checks `was` against the
    tape before applying a repair."""
    narr = _scenes(tmp_path / "summaries" / "20260706" / "narration", COLLIDING)

    result = _run(narr, tmp_path / "out.md", "--use", "renamed_yesterday.md")

    assert result.returncode == 1
    assert "renamed_yesterday.md" in result.stderr
    assert "not in this directory" in result.stderr


def test_the_scrubbed_variant_rule_is_untouched(tmp_path):
    """`foo.md` / `foo.scrubbed.md` is a real variant pair, not a collision:
    one scene, two renderings of it, and the existing preference decides. It
    must not start being refused as ambiguous."""
    narr = tmp_path / "summaries" / "20260706" / "narration"
    narr.mkdir(parents=True)
    for suffix, body in ((".md", "raw"), (".scrubbed.md", "scrubbed")):
        (narr / f"session_doc_scene_01_x{suffix}").write_text(
            f"---\nscene: 1\nscene_name: One\nnarrator: Soma\n---\n{body} prose.\n",
            encoding="utf-8")
    out = tmp_path / "out.md"

    result = _run(narr, out)

    assert result.returncode == 0, result.stderr
    assert "Assembled 1 scene(s)" in result.stdout
    assert "scrubbed prose." in out.read_text(encoding="utf-8")
