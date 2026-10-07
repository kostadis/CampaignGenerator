"""Helpers shared by the spec 033 chunked-state tests (import them; this is not a conftest).

``state_campaign`` copies ``fixtures/summary_native/state`` and builds the 031 corpus for chapters
2-5. ``fake_models`` replaces the two model seams (``extract.render_part`` and
``synth.render_part``) with canned outputs, so no test reaches a backend.
"""

from __future__ import annotations

import contextlib
import io
import re
import shutil
from pathlib import Path

from pipelines.summary_native import extract, schema, synth
from pipelines.summary_native.cli import main

STATE_FIXTURE = Path(__file__).parent / "fixtures" / "summary_native" / "state"
SINCE, UNTIL = 2, 5
RANGE_NAME = "ch002-005"

#: One canned extraction per chapter (``--chunk-chars 1`` makes each chapter its own chunk).
#: Chapter 3 carries two bad bullets (a citation outside the chunk, an invented quotation) so
#: the drop report has something to say.
CANNED = {
    2: """\
## Events
- The party wakes in the pens of Velkynvelve. [ch 002 / 002.01]
- Ilvara Mizzrym offers a bargain and leaves a signet ring. [ch 002 / 002.02]

## Concluded
- (none)

## Threads
- [OPENED] **The signet ring** — Ilvara leaves a signet ring on the floor. [ch 002 / 002.02]

## NPC Status
- Sarith Kzekarit | Alive | the gate | Hostile [ch 002 / 002.01]
- Ilvara | Alive | the pens | Offers a bargain [ch 002 / 002.02]
- Kalan | Unknown | east stair | — [ch 002 / 002.01]

## World
- [LOCATION] **Velkynvelve** — A drow outpost built into the cavern wall. [ch 002 / locations]
- [NPC] **Ilvara Mizzrym** — A drow priestess who offers the party a bargain. [ch 002 / npcs]
- [ITEM] **Signet Ring** — A ring bearing the sigil of House Mizzrym. [ch 002 / items]
- [FACTION] **House Mizzrym** — Its sigil is on the signet ring. [ch 002 / items]
- [THREAT] **The gate guards** — Sarith watches the party through the bars. [ch 002 / 002.01]

## Party
- The party is held in the pens of Velkynvelve. [ch 002 / 002.01]
""",
    3: """\
## Events
- The party breaks out of Velkynvelve and descends the long stair. [ch 003 / 003.01; ch 003 / 003.02]
- A claim about a later chapter. [ch 004 / 004.01]

## Concluded
- The escape from Velkynvelve ends at the foot of the stair. [ch 003 / 003.02]

## Threads
- [ADVANCED] **The signet ring** — Ilvara watches the escape without a word. [ch 003 / 003.01]
- The thread with no tag. [ch 003 / 003.01]

## NPC Status
- Thorin Giantfriend | Alive | the long stair | Leads the party [ch 003 / NPCs]
- Sarith Kzekarit | Alive | the landing | Gave up the chase [ch 003 / 003.02]

## World
- [LOCATION] **The Long Stair** — A spiral stair cut into the cavern wall. [ch 003 / Locations]
- [NPC] **Thorin Giantfriend** — A dwarf who has joined the party. [ch 003 / npcs]
- [NPC] **Ilvara** — She said "the web is a lie" and nothing else. [ch 003 / 003.01]

## Party
- The party stands at the foot of the long stair. [ch 003 / end]
""",
    4: """\
## Events
- Sarith dies at the foot of the stair. [ch 004 / 004.01]
- Ilvara Mizzrym is struck down in the doorway. [ch 004 / 004.02]

## Concluded
- The fight at the gate ends with Sarith's death and Kalan holding the gate. [ch 004 / 004.01]

## Threads
- [RESOLVED] **The signet ring** — Nobody could say what became of the signet ring. [ch 004 / 004.02]

## NPC Status
- Sarith | Dead | the foot of the stair | — [ch 004 / 004.01]
- Ilvara Mizzrym | Dead | the doorway | — [ch 004 / 004.02]
- Kalan | Alive | the gate | Holds the gate [ch 004 / 004.01]

## World
- [NPC] **Kalan** — A drow who now holds the gate. [ch 004 / npcs]
- [THREAT] **Kalan at the gate** — Kalan holds the gate of Velkynvelve. [ch 004 / 004.01]

## Party
- The party holds the gate of Velkynvelve. [ch 004 / end]
""",
    5: """\
## Events
- The party rests and speaks of Ilvara Mizzrym's death. [ch 005 / 005.01]

## Concluded
- (none)

## Threads
- [ADVANCED] **Kalan's intentions** — The party wonders what Kalan might do next. [ch 005 / 005.01]

## NPC Status
- Kalan | Unknown | — | — [ch 005 / 005.01]

## World
- [LOCATION] **Velkynvelve** — The party rests at its gate. [ch 005 / end]

## Party
- The party rests at the gate of Velkynvelve. [ch 005 / end]
""",
}


def run_cli(args: list[str]) -> tuple[int, str, str]:
    """Run ``summary_native.cli.main`` and return ``(exit_code, stdout, stderr)``."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = main(list(args))
    return rc, out.getvalue(), err.getvalue()


def common(root: Path) -> list[str]:
    return [
        "--config", str(root / "config" / "config.yaml"),
        "--summaries-dir", str(root / "docs" / "summaries"),
        "--since", str(SINCE), "--until", str(UNTIL),
    ]


def state_campaign(tmp_path: Path) -> Path:
    """Copy the fixture under ``tmp_path`` and build its corpus; return the campaign root."""
    root = tmp_path / "camp"
    shutil.copytree(STATE_FIXTURE, root)
    rc, out, err = run_cli(["build", *common(root)])
    assert rc == 0, f"fixture build failed ({rc}):\n{out}\n{err}"
    return root


def range_dir(root: Path) -> Path:
    return root / "docs" / "summary_native" / RANGE_NAME


def notes_dir(root: Path) -> Path:
    return range_dir(root) / schema.STATE_DIR / "notes"


def extract_args(root: Path, *extra: str) -> list[str]:
    return [
        "extract", *common(root), "--chunk-chars", "1",
        "--backend", "dgx", "--model", "fake-model", "--endpoint", "http://spark:8001/v1", *extra,
    ]


class FakeModels:
    """Records every extraction and prose call and answers from canned text."""

    def __init__(self) -> None:
        self.extract_calls: list[dict] = []
        self.prose_calls: list[dict] = []
        self.fail_chunks: dict[str, int] = {}  # chapter range -> number of calls that raise
        self.prose_override: dict[str, str] = {}  # heading -> full output text
        self.prose_missing: set[str] = set()  # headings the model "forgets"

    def extract_render(self, client, system, user, model, max_tokens):
        rng = re.search(r"CHAPTERS IN THIS CHUNK: (\d{3}-\d{3})", user).group(1)
        self.extract_calls.append({"range": rng, "system": system, "user": user, "model": model})
        left = self.fail_chunks.get(rng, 0)
        if left:
            self.fail_chunks[rng] = left - 1
            raise RuntimeError(f"upstream failure for {rng}")
        return CANNED[int(rng[:3])]

    def prose_render(self, client, system, user, model, max_tokens):
        heading = re.search(r"^SECTION: (## .+)$", user, re.M).group(1)
        self.prose_calls.append({"heading": heading, "system": system, "user": user, "model": model})
        if heading in self.prose_missing:
            return "I could not write that section.\n"
        if heading in self.prose_override:
            return self.prose_override[heading]
        return f"{heading}\n\nProse for {heading[3:]} [ch 004 / 004.01].\n"


def fake_models(monkeypatch) -> FakeModels:
    fm = FakeModels()
    monkeypatch.setattr(extract, "render_part", fm.extract_render)
    monkeypatch.setattr(extract, "client_from_args", lambda a, **k: object())
    monkeypatch.setattr(synth, "render_part", fm.prose_render)
    monkeypatch.setattr(synth, "client_from_args", lambda a, **k: object())
    return fm
