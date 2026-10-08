"""Helpers shared by the spec 034 party and planning tests (import them; this is not a conftest).

``tests/fixtures/summary_native/party_planning`` is a second campaign root, separate from spec 033's
``state`` fixture so that adding party, thread and planning material to it cannot move any 033 test.
It holds chapters 2-4 and the checked-note set below:

* party notes for two player characters (``Daz``, ``Zalthir``), one companion (``Ront``, a registry
  NPC), one unattributed subject (``Dazz``: not an entity, and a near-spelling of ``Daz`` that must
  never be matched by similarity), ``**Party**`` notes and a joint subject (``Daz and Zalthir``);
* ``[LEVEL] **Party** — 9`` whose cited scene says "the party reaches 9th level", and two ``[LEVEL]``
  rows whose cited text only has a spell level ("a 4th-level slot", "a 9th-level spell scroll"), which
  the code check drops as ``level-not-in-cited-text``;
* thread notes that name one thread differently (``The Carver's march`` / ``Carver march``), plus a
  resolved one (``The signet ring``, which the thread registry also has GM-set to ``resolved``);
* a published dossier whose ``## Secrets`` holds ``SECRET-CANARY-034``.

``checked_results()`` runs the real code check over the canned extraction without a CLI; ``party_campaign``
copies the fixture and builds its 031 corpus; ``fake_party_models`` is spec 033's fake client answering
extraction calls from :data:`CANNED_PARTY`.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from pipelines.summary_native import extract, notes
from tests import conftest_state as cs

PARTY_FIXTURE = Path(__file__).parent / "fixtures" / "summary_native" / "party_planning"
SINCE, UNTIL = 2, 4
RANGE_NAME = "ch002-004"
CANARY = "SECRET-CANARY-034"

CANNED_PARTY = {
    2: """\
## Events
- Daz and Zalthir hold the gate of Brindol. [ch 002 / 002.01]
- Zalthir wards the camp. [ch 002 / 002.02]

## Concluded
- (none)

## Threads
- [OPENED] **The Carver's march** — A horde is spoken of in whispers. [ch 002 / 002.02]
- [OPENED] **The signet ring** — Ilvara leaves a signet ring at the fire. [ch 002 / 002.02]

## NPC Status
- Ront | Alive | the wall | Friendly [ch 002 / 002.01]
- Ilvara Mizzrym | Alive | the camp | Bargaining [ch 002 / 002.02]

## World
- [NPC] **Ilvara Mizzrym** — A drow priestess of House Mizzrym who left a signet ring. [ch 002 / npcs]
- [FACTION] **House Mizzrym** — Ilvara speaks for it. [ch 002 / npcs]

## Party
- **Party** — The party holds the gate of Brindol. [ch 002 / 002.01]
- [LEVEL] **Party** — 9 [ch 002 / 002.01]
- [LEVEL] **Zalthir** — 4 [ch 002 / 002.02]
- **Zalthir** — Wards the camp. [ch 002 / 002.02]
- **Daz and Zalthir** — Hold the gate together. [ch 002 / 002.01]
- **Ront** — Keeps watch from the wall. [ch 002 / 002.01]
- **Dazz** — Offers to carry the packs. [ch 002 / 002.01]
- The party camps for the night. [ch 002 / 002.02]
""",
    3: """\
## Events
- Daz counts the banners of the march from the ridge. [ch 003 / 003.01]
- House Mizzrym sends word that it will stand aside. [ch 003 / 003.02]

## Concluded
- (none)

## Threads
- [ADVANCED] **Carver march** — Daz counts the banners from the ridge. [ch 003 / 003.01]

## NPC Status
- Ilvara Mizzrym | Alive | the parley | Smiling [ch 003 / 003.02]

## World
- [FACTION] **House Mizzrym** — It will stand aside while the horde passes. [ch 003 / 003.02]

## Party
- **Daz** — Counts the march's banners from the ridge. [ch 003 / 003.01]
- **Zalthir** — Reads a scroll aloud. [ch 003 / 003.01]
- [LEVEL] **Zalthir** — 9 [ch 003 / 003.01]
- **Ront** — Scouts ahead. [ch 003 / 003.01]
""",
    4: """\
## Events
- The march breaks against the gate. [ch 004 / 004.01]

## Concluded
- The Carver's march ends at the gate. [ch 004 / 004.01]

## Threads
- [ADVANCED] **The Carver's march** — The march breaks against the gate. [ch 004 / 004.01]
- [RESOLVED] **The signet ring** — Nobody could say what became of the ring. [ch 004 / 004.02]

## NPC Status
- Ront | Unknown | — | — [ch 004 / 004.01]

## World
- [THREAT] **The horde** — It has broken against the gate. [ch 004 / 004.01]

## Party
- **Daz** — Is wounded in the fight. [ch 004 / 004.01]
- **Zalthir** — Carries Daz back from the gate. [ch 004 / 004.01]
- **Party** — The party holds the gate of Brindol. [ch 004 / end]
""",
}


def checked_results() -> list[notes.CheckedChunk]:
    """The code check run over :data:`CANNED_PARTY`, one chunk per chapter (no CLI, no model)."""
    chapters = notes.load_chapters(PARTY_FIXTURE / "docs" / "summaries", SINCE, UNTIL)
    return [notes.check_chunk(CANNED_PARTY[c.number], [c]) for c in chapters]


def common(root: Path) -> list[str]:
    return [
        "--config", str(root / "config" / "config.yaml"),
        "--summaries-dir", str(root / "docs" / "summaries"),
        "--since", str(SINCE), "--until", str(UNTIL),
    ]


def extract_args(root: Path, *extra: str) -> list[str]:
    return [
        "extract", *common(root), "--chunk-chars", "1",
        "--backend", "dgx", "--model", "fake-model", "--endpoint", "http://spark:8001/v1", *extra,
    ]


def party_campaign(tmp_path: Path) -> Path:
    """Copy the fixture under ``tmp_path`` and build its 031 corpus; return the campaign root."""
    root = tmp_path / "camp"
    shutil.copytree(PARTY_FIXTURE, root)
    rc, out, err = cs.run_cli(["build", *common(root)])
    assert rc == 0, f"fixture build failed ({rc}):\n{out}\n{err}"
    return root


def range_dir(root: Path) -> Path:
    return root / "docs" / "summary_native" / RANGE_NAME


def fake_party_models(monkeypatch) -> cs.FakeModels:
    """Spec 033's fake models, with extraction answering from :data:`CANNED_PARTY`."""

    class PartyModels(cs.FakeModels):
        def __init__(self) -> None:
            super().__init__()
            self.party_calls: list[dict] = []  # every party prose call: heading, character (or None), prompts
            self.character_override: dict[str, str] = {}  # character -> the model's full output ("" = nothing)

        def prose_render(self, client, system, user, model, max_tokens):
            heading = re.search(r"^SECTION: (## .+)$", user, re.M).group(1)
            m = re.search(r"^CHARACTER: (.+)$", user, re.M)
            character = m.group(1) if m else None
            self.party_calls.append({"heading": heading, "character": character, "system": system, "user": user})
            self.prose_calls.append({"heading": heading, "system": system, "user": user, "model": model})
            if character in self.character_override:
                return self.character_override[character]
            return f"Body for {character or heading[3:]} [ch 004 / 004.01].\n"

        def extract_render(self, client, system, user, model, max_tokens):
            rng = re.search(r"CHAPTERS IN THIS CHUNK: (\d{3}-\d{3})", user).group(1)
            self.extract_calls.append({"range": rng, "system": system, "user": user, "model": model})
            return CANNED_PARTY[int(rng[:3])]

    fm = PartyModels()
    monkeypatch.setattr(extract, "render_part", fm.extract_render)
    monkeypatch.setattr(extract, "client_from_args", fm.make_client)
    monkeypatch.setattr(extract, "_served_models", fm.served_models)
    monkeypatch.setattr(cs.audit, "render_part", fm.audit_render)
    monkeypatch.setattr(cs.audit, "client_from_args", fm.make_client)
    monkeypatch.setattr(cs.synth, "render_part", fm.prose_render)
    monkeypatch.setattr(cs.synth, "client_from_args", fm.make_client)
    return fm
