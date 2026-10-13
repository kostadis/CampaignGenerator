"""The backtest scoring page: one self-contained HTML file, generated from code.

``npc_agent backtest`` writes ``backtest.html`` with every target's situation,
the agent's answer (each flagged sentence marked), what actually happened, and
what the agent was given, all embedded as JSON. The GM scores each target: is it
in character, is it plausible at this point, and whether each flag is a real
leak. Scores are kept in the artifact database as ``scores/<run_id>--<target>``
and can be saved as ``scores.json`` or copied as YAML. The page decides nothing.

The template is ``review/backtest_review.html``; this module only fills it.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent / "review" / "backtest_review.html"
DATA_SLOT = "/*__NPC_AGENT_DATA__*/null"
#: Bumped when the bundle's shape changes; the page refuses a bundle it does not know.
BUNDLE_VERSION = 1


def render(bundle: dict) -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count(DATA_SLOT) != 1:
        raise RuntimeError(f"{TEMPLATE}: expected exactly one data slot")
    payload = json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # A summary line containing "</script" must not close the data block early.
    payload = payload.replace("</", "<\\/")
    return template.replace(DATA_SLOT, payload)
