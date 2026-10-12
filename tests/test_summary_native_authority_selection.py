from __future__ import annotations

from pathlib import Path

import pytest

from campaignlib.planning_config import PlanningNoteSelector
from pipelines.summary_native.authority import AuthorityError
from pipelines.summary_native.authority_inputs import resolve_selection


def test_selection_dedupes_aliases_discloses_external_and_detects_membership_drift(tmp_path: Path):
    notes = tmp_path / "notes"; notes.mkdir()
    one = notes / "one.md"; one.write_text("one")
    (notes / "alias.md").symlink_to(one)
    external = tmp_path.parent / "external-authority-note.md"; external.write_text("external")
    selectors = [
        PlanningNoteSelector(id="glob", path="notes/*.md", record_ids={"one"}),
        PlanningNoteSelector(id="exact", path="notes/one.md", record_ids={"one-exact"}),
        PlanningNoteSelector(id="external", path=str(external), record_ids={"outside"}),
    ]
    first = resolve_selection(tmp_path, selectors)
    assert len(first.members) == 2
    assert any(member.external for member in first.members)
    assert [member.resolved_path for member in first.members] == sorted(member.resolved_path for member in first.members)
    concrete = next(member for member in first.members if member.resolved_path == str(one.resolve()))
    assert concrete.selector_id == "exact,glob" and concrete.reason == "selector:exact,selector:glob"
    assert concrete.record_ids == ("one", "one-exact")
    (notes / "two.md").write_text("two")
    assert resolve_selection(tmp_path, selectors).membership_digest != first.membership_digest


def test_selection_refuses_zero_matches(tmp_path: Path):
    with pytest.raises(AuthorityError, match="matched no notes"):
        resolve_selection(tmp_path, [PlanningNoteSelector(id="missing", path="notes/*.md")])


def test_an_all_records_selector_is_not_narrowed_by_a_selector_naming_ids(tmp_path: Path):
    """An empty ``record_ids`` means every record in the file; a merge must keep that."""
    notes = tmp_path / "notes"; notes.mkdir()
    (notes / "x.md").write_text("x")
    for selectors in (
        [PlanningNoteSelector(id="all", path="notes/x.md"), PlanningNoteSelector(id="some", path="notes/*.md", record_ids={"r1"})],
        [PlanningNoteSelector(id="some", path="notes/*.md", record_ids={"r1"}), PlanningNoteSelector(id="all", path="notes/x.md")],
    ):
        (member,) = resolve_selection(tmp_path, selectors).members
        assert member.record_ids == ()
        assert member.selector_id == "all,some"
