"""The prep sheet review page: one self-contained HTML file, generated from code.

``npc_agent prep`` writes the page with every target's passages embedded as JSON
(:func:`pipelines.npc_agent.prep.extract`). The GM marks each passage Hers or GM
only. Rulings are kept in the artifact database as ``prep/<target>`` and can be
saved as ``prep.json`` (the file :func:`prep.load_rulings` reads) or copied as
YAML. The page decides nothing.

The template is ``review/prep_review.html``; this module only fills it.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent / "review" / "prep_review.html"
DATA_SLOT = "/*__NPC_AGENT_DATA__*/null"
#: Bumped when the bundle's shape changes; the page refuses a bundle it does not know.
BUNDLE_VERSION = 1


def render(bundle: dict) -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count(DATA_SLOT) != 1:
        raise RuntimeError(f"{TEMPLATE}: expected exactly one data slot")
    payload = json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # Prep text containing "</script" must not close the data block early.
    payload = payload.replace("</", "<\\/")
    return template.replace(DATA_SLOT, payload)
