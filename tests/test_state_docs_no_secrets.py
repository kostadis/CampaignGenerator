"""A dossier's Secrets never reach a prompt or an output of the state documents (spec 033 T030, FR-016).

The published dossier is GM-only and carries a Secrets section. world_state's Key NPCs reads two
sections of it, and ``key_npcs`` has no code path that could name the third. The canary is in the
fixture's published dossier; the first test proves it is there, so a pass is not vacuous.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipelines.summary_native import key_npcs, schema
from tests import conftest_party as cp
from tests import conftest_state as cs

CANARY = "SECRET-CANARY-033"
SRC = Path(key_npcs.__file__)


@pytest.fixture
def built(tmp_path, monkeypatch):
    root = cs.state_campaign(tmp_path)
    fm = cs.fake_models(monkeypatch)
    assert cs.run_cli(cs.extract_args(root))[0] == 0
    # a second published dossier, with the canary in a different place in the file
    (root / "docs" / "npcs" / "kalan.md").write_text(
        "<!-- published by summary_native npc-publish | source: summary_native | npc: Kalan | range: ch002-005 "
        f"| draft run: fixture | draft sha256: {'0' * 64} | authored sha256: none | verify: pass "
        f"| published sha256: {'1' * 64} -->\n# Kalan\n\n## Secrets\n\n{CANARY} Kalan serves the web.\n\n"
        "## Identity\n\nA drow who holds the gate. [ch 004 / entry]\n\n"
        "## Last Observed State\n\nHolds the gate. [ch 004 / 004.01]\n")
    fm.prose_override["## Key NPCs"] = "- **Kalan** — Holds the gate [ch 004 / 004.01]"
    rc, out, err = cs.run_cli(["synth", "world_state", *cs.common(root), "--fallback-npc-lines"])
    assert rc == 0, err
    return root, fm, out + err


def test_the_canary_is_in_both_published_dossiers():
    fixture = (cs.STATE_FIXTURE / "docs" / "npcs" / "ilvara-mizzrym.md").read_text()
    assert CANARY in fixture and fixture.index("## Secrets") < fixture.index(CANARY)


def test_no_prompt_the_model_was_sent_carries_it(built):
    _, fm, _ = built
    assert fm.prose_calls and any(c["heading"] == "## Key NPCs" for c in fm.prose_calls)
    for c in fm.prose_calls:
        assert CANARY not in c["system"] and CANARY not in c["user"], c["heading"]


def test_no_file_the_build_wrote_carries_it(built):
    root, _, said = built
    files = [p for p in cs.range_dir(root).rglob("*") if p.is_file()]
    assert any(p.name == "world_state.draft.md" for p in files)
    assert any(p.parent.name == "reference" for p in files)
    assert any(p.suffix == ".md" and "runs" in p.parts for p in files)
    for p in files:
        assert CANARY not in p.read_text(encoding="utf-8", errors="ignore"), p
    assert CANARY not in said


def test_the_draft_and_the_prompts_hold_the_two_sections_instead(built):
    root, fm, _ = built
    kalan = next(c for c in fm.prose_calls if c["heading"] == "## Key NPCs")["user"]
    assert "A drow who holds the gate. [ch 004 / npcs]" in kalan and "Holds the gate. [ch 004 / 004.01]" in kalan
    draft = (cs.range_dir(root) / schema.STATE_DIR / "drafts" / "world_state.draft.md").read_text()
    assert "→ docs/npcs/ilvara-mizzrym.md" in draft


def test_key_npcs_never_names_the_section_it_must_not_read():
    text = SRC.read_text(encoding="utf-8")
    assert "secret" not in text.casefold()
    assert key_npcs.TAKE == ("## Identity", "## Last Observed State")  # the only sections read


def test_the_view_cannot_carry_what_it_did_not_read(tmp_path):
    p = tmp_path / "x.md"
    p.write_text((cs.STATE_FIXTURE / "docs" / "npcs" / "ilvara-mizzrym.md").read_text())
    v = key_npcs.published_view(p)
    assert CANARY not in repr(v) and CANARY not in v.source
    assert set(vars(v)) == {"name", "slug", "range", "verify", "identity", "state"}


# ── Spec 034 T011: planning reads four sections, still never the third ───────

CANARY_034 = "SECRET-CANARY-034"
DOSSIER_034 = cp.PARTY_FIXTURE / "docs" / "npcs" / "ilvara-mizzrym.md"
SECTION_PREFIX = "## "


def test_the_034_canary_is_in_the_fixture_dossier_so_a_pass_is_not_vacuous():
    text = DOSSIER_034.read_text()
    assert CANARY_034 in text and text.index("## Secrets") < text.index(CANARY_034)
    for heading in ("## Identity", "## Personality and Motivations", "## Last Observed State", "## Relationships"):
        assert heading in text


def test_planning_view_reads_the_four_sections_and_never_the_canary():
    v = key_npcs.planning_view(DOSSIER_034)
    assert v.name == "Ilvara Mizzrym" and v.slug == "ilvara-mizzrym" and v.verify == "pass"
    assert "drow priestess" in v.identity and "every debt repaid" in v.personality
    assert "standing aside" in v.state and "Speaks for House Mizzrym" in v.relationships
    assert CANARY_034 not in repr(v) and CANARY_034 not in v.source
    assert set(vars(v)) == {"name", "slug", "range", "verify", "identity", "personality", "state", "relationships"}


def test_planning_views_take_set_is_the_four_headings_and_none_is_secrets():
    assert key_npcs.PLANNING_TAKE == (
        "## Identity", "## Personality and Motivations", "## Last Observed State", "## Relationships")
    assert key_npcs.TAKE == ("## Identity", "## Last Observed State")
    for take in (key_npcs.TAKE, key_npcs.PLANNING_TAKE):
        assert all("secret" not in h.casefold() for h in take)


def test_a_dossier_with_the_canary_in_every_other_position_still_yields_none_of_it(tmp_path):
    """The canary under Secrets, however the sections are ordered, and a Secrets heading with trailing text."""
    head = DOSSIER_034.read_text().split("\n", 1)[0]
    body = (
        "# X\n\n## Secrets   \n\nSECRET-CANARY-034 first.\n\n## Identity\n\nWho. [ch 002 / entry]\n\n"
        "## Relationships\n\nKnows Y. [ch 003 / 003.02]\n\n## Last Observed State\n\nHere. [ch 003 / 003.02]\n\n"
        "## Secrets\n\nSECRET-CANARY-034 second.\n"
    )
    p = tmp_path / "x.md"
    p.write_text(head + "\n" + body)
    v = key_npcs.planning_view(p)
    assert CANARY_034 not in repr(v)
    assert (v.identity, v.relationships, v.state, v.personality) == (
        "Who. [ch 002 / npcs]", "Knows Y. [ch 003 / 003.02]", "Here. [ch 003 / 003.02]", "")  # entry -> npcs, as in Key NPCs


def test_planning_view_refuses_what_published_view_refuses(tmp_path):
    p = tmp_path / "hand.md"
    p.write_text("# Hand-built\n\n## Last Observed State\n\nx\n")
    with pytest.raises(key_npcs.NotPublished):
        key_npcs.planning_view(p)
    q = tmp_path / "nostate.md"
    q.write_text(DOSSIER_034.read_text().split("## Last Observed State")[0])
    with pytest.raises(key_npcs.NotPublished):
        key_npcs.planning_view(q)


def test_published_view_is_unchanged_by_sharing_the_reader():
    v = key_npcs.published_view(DOSSIER_034)
    assert v.identity.startswith("A drow priestess") and v.state.startswith("Smiling at the parley")
    assert CANARY_034 not in repr(v)
