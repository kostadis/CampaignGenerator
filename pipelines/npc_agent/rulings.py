"""The GM's presence ruling file: read, validated, never written.

Shape::

    version: 1
    npcs:
      Sylvira Savikas:
        "061.05": present
        "061.p07": present
        "058.05": mentioned
        "063.05": unsure
        "063.06":            # empty: unruled

Every key must be a published NPC's subject. A value is ``present``,
``mentioned``, ``unsure`` or empty, and the item id decides which are allowed:

- one of the NPC's **candidates** (an item that names them): any value;
- any other **scene** in the corpus: ``present`` or ``unsure`` only. A companion
  is in most scenes nobody names him in (Glabbagool, riding in the bag of
  holding, is named in 91 of the 240 scenes of his span), so presence cannot be
  limited to the items that name him. ``mentioned`` is refused there: an item
  that does not name the NPC cannot be about them.

Anything else is refused, because a ruling the tool silently ignores is a ruling
the GM believes was applied.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

from pathlib import Path

import yaml

PRESENT = "present"
MENTIONED = "mentioned"
UNSURE = "unsure"
VALUES = (PRESENT, MENTIONED, UNSURE)
VERSION = 1


class RulingError(Exception):
    """The ruling file cannot be used; the message is user-facing."""


def load_rulings(
    path: Path, candidate_ids: dict[str, set[str]], scene_ids: frozenset[str] = frozenset()
) -> dict[str, dict[str, str]]:
    """``{subject: {item_id: value}}`` with unruled items omitted.

    ``candidate_ids`` maps each in-scope subject to its candidate item ids;
    ``scene_ids`` is every scene id in the corpus. A subject absent from the file
    simply has no rulings.
    """
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

    problems: list[str] = []
    out: dict[str, dict[str, str]] = {}
    for subject, rulings in npcs.items():
        if subject not in candidate_ids:
            problems.append(f"{subject!r}: not an NPC with a published dossier in this campaign")
            continue
        rulings = rulings or {}
        if not isinstance(rulings, dict):
            problems.append(f"{subject!r}: rulings must be a mapping of item id -> value")
            continue
        kept: dict[str, str] = {}
        for item_id, value in rulings.items():
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
            else:
                kept[item_id] = value
        out[subject] = kept
    if problems:
        raise RulingError(f"{path}: {len(problems)} problem(s):\n  " + "\n  ".join(problems))
    return out
