"""The GM's presence ruling file: read, validated, never written.

Shape (version 2)::

    version: 2
    npcs:
      Glabbagool:
        spans:
          - from: "034.03"            # first scene of the span
            to: "071.10"              # last scene of the span
            value: present            # present (default) | unsure
            follows: Zalthir          # optional: a review hint, never a ruling
            note: rides in the bag of holding; counts as present
        items:
          "039.04": absent            # an exception inside the span
      Sylvira Savikas:
        items:
          "061.05": present
          "058.05": mentioned
          "063.05": unsure
          "063.06":                   # empty: unruled

**Values, and which items take them.**

- ``present`` / ``unsure``: any of the NPC's candidates, or any scene in the corpus.
  A companion is in most scenes nobody names him in (Glabbagool, riding in the bag
  of holding, is named in 91 of the 240 scenes of his span).
- ``mentioned``: a candidate only. The item is about the NPC, who was not there;
  an item that does not name them cannot be about them.
- ``absent``: a scene that does not name the NPC. It exists to make an exception
  inside a span; for a candidate, ``mentioned`` says the same thing.

**Spans.** A span rules a run of scenes at once (GM ruling 2026-10-12: Glabbagool
in the bag of holding counts as present, and when the party splits he is with
Zalthir). It covers every scene from ``from`` to ``to`` inclusive, and every prose
paragraph and memorable moment of a chapter whose scenes are *all* inside it; an
``## NPCs`` entry only if it names the NPC. An item ruling always overrides a span.
Spans of one NPC may not overlap. ``follows`` names the character the NPC stays
with; it is shown to the GM as a hint at review and changes no ruling.

Anything the tool cannot apply is refused, because a ruling it silently ignores
is a ruling the GM believes was applied.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from pipelines.npc_agent.corpus import ENTRY, MOMENT, PROSE, SCENE, Corpus

PRESENT = "present"
MENTIONED = "mentioned"
UNSURE = "unsure"
ABSENT = "absent"
VALUES = (PRESENT, MENTIONED, UNSURE, ABSENT)
SPAN_VALUES = (PRESENT, UNSURE)
VERSION = 2

#: Where an effective ruling came from.
FROM_ITEM = "item"
FROM_SPAN = "span"

_SCENE_ID_RE = re.compile(r"^(\d{3})\.(\d{2})$")


class RulingError(Exception):
    """The ruling file cannot be used; the message is user-facing."""


@dataclass(frozen=True)
class Span:
    start: str
    end: str
    value: str = PRESENT
    follows: str | None = None
    note: str | None = None

    def covers_scene(self, scene_id: str) -> bool:
        return _key(self.start) <= _key(scene_id) <= _key(self.end)


@dataclass(frozen=True)
class NpcRulings:
    items: dict[str, str] = field(default_factory=dict)
    spans: tuple[Span, ...] = ()


def _key(scene_id: str) -> tuple[int, int]:
    m = _SCENE_ID_RE.match(scene_id)
    return (int(m.group(1)), int(m.group(2))) if m else (-1, -1)


def _read(path: Path) -> dict:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise RulingError(f"{path}: cannot read ({e.strerror})") from None
    except yaml.YAMLError as e:
        raise RulingError(f"{path}: not valid YAML ({e})") from None
    if not isinstance(raw, dict):
        raise RulingError(f"{path}: expected a mapping with 'version' and 'npcs'")
    extra = set(raw) - {"version", "npcs"}
    if extra:
        raise RulingError(f"{path}: unknown top-level key(s): {', '.join(sorted(map(str, extra)))}")
    if raw.get("version") != VERSION:
        raise RulingError(f"{path}: version must be {VERSION}, got {raw.get('version')!r}")
    npcs = raw.get("npcs") or {}
    if not isinstance(npcs, dict):
        raise RulingError(f"{path}: 'npcs' must be a mapping of NPC name -> rulings")
    return npcs


def _spans(subject: str, raw, scene_ids: set[str], corpus_text: str, problems: list[str]) -> tuple[Span, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        problems.append(f"{subject!r}: spans must be a list")
        return ()
    out: list[Span] = []
    for n, s in enumerate(raw, 1):
        where = f"{subject!r} span {n}"
        if not isinstance(s, dict):
            problems.append(f"{where}: must be a mapping")
            continue
        extra = set(s) - {"from", "to", "value", "follows", "note"}
        if extra:
            problems.append(f"{where}: unknown key(s): {', '.join(sorted(map(str, extra)))}")
            continue
        start, end = str(s.get("from", "")), str(s.get("to", ""))
        value = s.get("value", PRESENT)
        follows, note = s.get("follows"), s.get("note")
        bad = False
        for label, sid in (("from", start), ("to", end)):
            if sid not in scene_ids:
                problems.append(f"{where}: {label} {sid!r} is not a scene in the corpus")
                bad = True
        if not bad and _key(start) > _key(end):
            problems.append(f"{where}: from {start} is after to {end}")
            bad = True
        if value not in SPAN_VALUES:
            problems.append(f"{where}: value {value!r} is not one of {', '.join(SPAN_VALUES)}")
            bad = True
        if follows is not None:
            if not isinstance(follows, str) or not follows.strip():
                problems.append(f"{where}: follows must be a name")
                bad = True
            elif not re.search(rf"(?<!\w){re.escape(follows)}(?!\w)", corpus_text):
                problems.append(f"{where}: follows {follows!r} appears nowhere in the summaries; check the spelling")
                bad = True
        if not bad:
            out.append(Span(start, end, value, follows, None if note is None else str(note)))
    for a in range(len(out)):
        for b in range(a + 1, len(out)):
            x, y = out[a], out[b]
            if _key(x.start) <= _key(y.end) and _key(y.start) <= _key(x.end):
                problems.append(f"{subject!r}: spans {x.start}–{x.end} and {y.start}–{y.end} overlap")
    return tuple(out)


def load_rulings(
    path: Path, candidate_ids: dict[str, set[str]], corpus: Corpus
) -> dict[str, NpcRulings]:
    """``{subject: NpcRulings}``; unruled items are omitted.

    ``candidate_ids`` maps each in-scope subject to its candidate item ids. A
    subject absent from the file simply has no rulings.
    """
    npcs = _read(path)
    scene_ids = {it.item_id for it in corpus.items() if it.kind == SCENE}
    corpus_text = "\n".join(t for it in corpus.items() for _, t in it.lines)
    problems: list[str] = []
    out: dict[str, NpcRulings] = {}
    for subject, block in npcs.items():
        if subject not in candidate_ids:
            problems.append(f"{subject!r}: not an NPC with a published dossier in this campaign")
            continue
        block = block or {}
        if not isinstance(block, dict) or set(block) - {"spans", "items"}:
            problems.append(f"{subject!r}: expected a mapping with 'spans' and/or 'items'")
            continue
        spans = _spans(subject, block.get("spans"), scene_ids, corpus_text, problems)
        raw_items = block.get("items") or {}
        if not isinstance(raw_items, dict):
            problems.append(f"{subject!r}: items must be a mapping of item id -> value")
            continue
        kept: dict[str, str] = {}
        for item_id, value in raw_items.items():
            item_id = str(item_id)
            named = item_id in candidate_ids[subject]
            if not named and item_id not in scene_ids:
                problems.append(
                    f"{subject!r} {item_id}: neither one of this NPC's candidate items nor a scene in the corpus"
                )
            elif value is None:
                continue
            elif value not in VALUES:
                problems.append(f"{subject!r} {item_id}: {value!r} is not one of {', '.join(VALUES)}")
            elif value == MENTIONED and not named:
                problems.append(
                    f"{subject!r} {item_id}: 'mentioned' needs an item that names the NPC; this scene does not"
                )
            elif value == ABSENT and named:
                problems.append(
                    f"{subject!r} {item_id}: this item names the NPC; rule it 'mentioned', not 'absent'"
                )
            else:
                kept[item_id] = value
        out[subject] = NpcRulings(items=kept, spans=spans)
    if problems:
        raise RulingError(f"{path}: {len(problems)} problem(s):\n  " + "\n  ".join(problems))
    return out


def effective(
    npc: NpcRulings, corpus: Corpus, candidate_ids: set[str]
) -> dict[str, tuple[str, str]]:
    """``{item_id: (value, FROM_ITEM | FROM_SPAN)}`` after spans, with item rulings winning."""
    out: dict[str, tuple[str, str]] = {}
    if npc.spans:
        for ch in corpus.chapters:
            scenes = [it for it in ch.items if it.kind == SCENE]
            for span in npc.spans:
                whole = bool(scenes) and all(span.covers_scene(s.item_id) for s in scenes)
                for it in ch.items:
                    if it.kind == SCENE:
                        hit = span.covers_scene(it.item_id)
                    elif it.kind in (PROSE, MOMENT):
                        hit = whole
                    elif it.kind == ENTRY:
                        hit = whole and it.item_id in candidate_ids
                    else:
                        hit = False
                    if hit:
                        out[it.item_id] = (span.value, FROM_SPAN)
    for item_id, value in npc.items.items():
        out[item_id] = (value, FROM_ITEM)
    return out
