"""A dossier's Secrets never reach a prompt or an output of the state documents (spec 033 T030, FR-016).

The published dossier is GM-only and carries a Secrets section. world_state's Key NPCs reads two
sections of it, and ``key_npcs`` has no code path that could name the third. The canary is in the
fixture's published dossier; the first test proves it is there, so a pass is not vacuous.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipelines.summary_native import key_npcs, schema
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
