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
