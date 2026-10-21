"""The reaction scoring page: one self-contained HTML file, generated from code.

``npc_agent react`` writes ``react.html`` from every ``OUT/*/bundle.json``. Per
moment it shows the question, what reached him (collapsed), his reaction, his
assessment, and each decision for the GM to approve or reject, with flags; the
GM's answer-key files are shown collapsed as preformatted text beside them. The
GM answers four questions per moment. Everything is kept in the artifact
database as ``react/<run_id>--<moment>`` and can be saved as ``scores.json``.
The page decides nothing.

The template is ``review/react_review.html``; this module only fills it.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent / "review" / "react_review.html"
DATA_SLOT = "/*__NPC_AGENT_DATA__*/null"
#: Bumped when the bundle's shape changes; the page refuses a bundle it does not know.
BUNDLE_VERSION = 1


def render(bundle: dict) -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count(DATA_SLOT) != 1:
        raise RuntimeError(f"{TEMPLATE}: expected exactly one data slot")
    payload = json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # A summary or canon line containing "</script" must not close the data block early.
    payload = payload.replace("</", "<\\/")
    return template.replace(DATA_SLOT, payload)
