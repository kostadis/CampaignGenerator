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

Every key must be a published NPC's subject and every item id one of that NPC's
candidates; a value is ``present``, ``mentioned``, ``unsure`` or empty. Anything
else is refused, because a ruling the tool silently ignores is a ruling the GM
believes was applied.

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


def load_rulings(path: Path, candidate_ids: dict[str, set[str]]) -> dict[str, dict[str, str]]:
    """``{subject: {item_id: value}}`` with unruled items omitted.

    ``candidate_ids`` maps each in-scope subject to its candidate item ids. A
    subject absent from the file simply has no rulings.
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
            if item_id not in candidate_ids[subject]:
                problems.append(f"{subject!r} {item_id}: not one of this NPC's candidate items")
            elif value is None:
                continue
            elif value not in VALUES:
                problems.append(f"{subject!r} {item_id}: {value!r} is not one of {', '.join(VALUES)}")
            else:
                kept[item_id] = value
        out[subject] = kept
    if problems:
        raise RulingError(f"{path}: {len(problems)} problem(s):\n  " + "\n  ".join(problems))
    return out
