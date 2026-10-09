"""An annotation adds lines under a line; it never changes one (spec 033 US4, T035, FR-020).

The reader treats the document as canon, so the guarantee is checked as an invariant over a document
that trips every detector, not as a handful of examples: strip the annotation sub-bullets from the
output and what is left is the input, less the player-character lines code removed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

from pipelines.summary_native import annotate, schema
from tests.test_summary_native_annotate import (
    CHAPTER_TEXT, PARTY_DOC, PLANNING_DOC, PLAYERS, REGISTRY, RESULTS, _chapter, _world, notes,
)

MODULE = Path(annotate.__file__)

#: Every detector fires somewhere in this document, and the skipped sections hold lines that would
#: fire if they were scanned.
DOC = """\
<!-- summary_native draft | doc: world_state | range: ch026-070 | record: runs/x/record.json -->
> **How to read this document.** A blockquote.

## Party

### Companions

- **Thorin Giantfriend** — A dwarf. [ch 026 / 026.01]
- **Jimjar** — Travels with the party as a companion. [ch 026 / 026.01]
  - a nested bullet the model wrote itself

## Factions and Powers

- **The Avowed** — Kalan fled the tower. [ch 065 / 065.01] They muster. [ch 070 / 070.01]
- **Kalan** — He said "never again". [ch 065 / 065.09]

## Locations

- **Mantol-Derith** — A trading post. [ch 030 / 030.01]

## Active Threats and Open Pressures

- **Mantol-Derith** — Under siege. [ch 055 / 055.01]

## Key NPCs

- **Jimjar** — Travels with the party. [ch 026 / 026.01] → docs/npcs/jimjar.md

_Source: the published NPC dossiers._

## Canon Events Timeline

The full timeline is a separate file.
"""


@pytest.fixture
def ev(tmp_path):
    (tmp_path / "registry.yaml").write_text(yaml.safe_dump(REGISTRY), encoding="utf-8")
    (tmp_path / "players.yaml").write_text(yaml.safe_dump(PLAYERS), encoding="utf-8")
    return annotate.load_evidence(
        RESULTS, [_chapter(n) for n in CHAPTER_TEXT], tmp_path / "registry.yaml", tmp_path / "players.yaml")


def without_annotations(text: str) -> list[str]:
    return [ln for ln in text.split("\n") if not annotate.ANNOTATION_RE.match(ln)]


def test_the_document_trips_every_detector(ev):
    c = annotate.annotate_text(DOC, ev).counts()
    assert c["later"] >= 2 and c["since"] >= 1 and c["unverified"] >= 2 and c["removed"] == 1


def test_every_surviving_line_is_the_same_text_in_the_same_order(ev):
    r = annotate.annotate_text(DOC, ev)
    removed = {x.text for x in r.removed}
    assert without_annotations(r.text) == [ln for ln in DOC.split("\n") if ln not in removed]


def test_the_only_lines_added_are_annotation_sub_bullets_under_a_bullet(ev):
    r = annotate.annotate_text(DOC, ev)
    original = set(DOC.split("\n"))
    lines = r.text.split("\n")
    added = [ln for ln in lines if ln not in original]
    assert added and all(annotate.ANNOTATION_RE.match(ln) for ln in added)
    for i, ln in enumerate(lines):
        if annotate.ANNOTATION_RE.match(ln):
            above = lines[i - 1]
            assert above.startswith("- ") or annotate.ANNOTATION_RE.match(above)


def test_a_models_own_nested_bullet_is_not_mistaken_for_an_annotation(ev):
    assert "  - a nested bullet the model wrote itself" in annotate.annotate_text(DOC, ev).text


def test_reannotating_replaces_the_old_sub_bullets(ev):
    once = annotate.annotate_text(DOC, ev)
    twice = annotate.annotate_text(once.text, ev)
    assert twice.text == once.text  # the first run already removed the player character
    assert twice.counts()["removed"] == 0
    marked = [ln for ln in twice.text.split("\n") if annotate.ANNOTATION_RE.match(ln)]
    assert len(marked) == sum(len(h.annotations) for h in once.hits)


def test_an_annotation_from_an_earlier_run_is_dropped_not_kept(ev):
    old = DOC.replace(
        "- **Mantol-Derith** — A trading post. [ch 030 / 030.01]\n",
        f"- **Mantol-Derith** — A trading post. [ch 030 / 030.01]\n  - {schema.LATER} an old finding that no longer holds\n")
    assert "an old finding that no longer holds" not in annotate.annotate_text(old, ev).text


def test_a_clean_document_comes_back_byte_for_byte(ev):
    clean = "## Party\n\n- **Kalan** — At the tower. [ch 067 / 067.01]\n"
    assert annotate.annotate_text(clean, ev).text == clean
    assert annotate.annotate_text(clean.rstrip("\n"), ev).text == clean.rstrip("\n")


def test_unicode_line_separators_inside_a_line_are_not_split(ev):
    # str.splitlines() would break a line on U+2028; annotating must leave the line whole
    line = "- **Kalan** — At the tower. Still there. [ch 067 / 067.01]"
    assert line in annotate.annotate_text(f"## Party\n\n{line}\n", ev).text


# ── Spec 034 US5 (T043): the same guarantee over party and planning drafts ───


@pytest.fixture
def ev2(tmp_path):
    (tmp_path / "registry.yaml").write_text(yaml.safe_dump(REGISTRY), encoding="utf-8")
    (tmp_path / "players.yaml").write_text(yaml.safe_dump(PLAYERS), encoding="utf-8")
    results = [notes.CheckedChunk("026-070", [*RESULTS[0].notes, _world("FACTION", "The Avowed", "They muster at dawn.", 70)])]
    return annotate.load_evidence(
        results, [_chapter(n) for n in CHAPTER_TEXT], tmp_path / "registry.yaml", tmp_path / "players.yaml")


@pytest.mark.parametrize("doc", [PARTY_DOC, PLANNING_DOC], ids=["party", "planning"])
class TestPartyAndPlanningDrafts:
    def test_the_draft_trips_a_detector(self, ev2, doc):
        c = annotate.annotate_text(doc, ev2).counts()
        assert c["later"] + c["since"] + c["unverified"] + c["removed"] >= 2

    def test_what_is_left_is_the_input_less_the_removed_lines(self, ev2, doc):
        r = annotate.annotate_text(doc, ev2)
        removed = {x.text for x in r.removed}
        assert without_annotations(r.text) == [ln for ln in doc.split("\n") if ln not in removed]

    def test_every_added_line_is_an_annotation_directly_under_a_line_of_the_document(self, ev2, doc):
        r = annotate.annotate_text(doc, ev2)
        original = set(doc.split("\n"))
        lines = r.text.split("\n")
        added = [ln for ln in lines if ln not in original]
        assert added and all(annotate.ANNOTATION_RE.match(ln) for ln in added)
        for i, ln in enumerate(lines):
            if annotate.ANNOTATION_RE.match(ln):
                above = lines[i - 1]
                assert above in original or annotate.ANNOTATION_RE.match(above)

    def test_reannotating_is_a_fixed_point_and_never_stacks(self, ev2, doc):
        once = annotate.annotate_text(doc, ev2)
        twice = annotate.annotate_text(once.text, ev2)
        assert twice.text == once.text and twice.counts()["removed"] == 0

    def test_a_clean_draft_comes_back_byte_for_byte(self, ev2, doc):
        clean = annotate.annotate_text(doc, ev2).text
        assert annotate.annotate_text(clean, ev2).text == clean

    def test_the_skipped_blocks_come_back_byte_for_byte(self, ev2, doc):
        skipped = ("| kalan-arc |", "Goals: He said", "- **Jimjar** — A dormant line", "- [OPENED] **Jimjar**",
                   "- A bare unratified line.", "- Thorin falls back", "- Thorin holds the line [ch")
        out = annotate.annotate_text(doc, ev2).text.split("\n")
        for needle in skipped:
            for i, ln in enumerate(doc.split("\n")):
                if ln.startswith(needle):
                    assert ln in out
                    assert not annotate.ANNOTATION_RE.match(out[out.index(ln) + 1])


def test_apply_annotations_never_assigns_into_a_sequence():
    """The write path appends and filters; it has no statement that replaces a line's text."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "apply_annotations")
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                assert not isinstance(t, ast.Subscript), f"line {node.lineno} assigns into a sequence"
