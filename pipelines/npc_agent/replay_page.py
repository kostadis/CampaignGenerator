"""The replay and forward scoring page: one self-contained HTML file, generated from code.

``npc_agent replay`` and ``npc_agent forward`` write ``replay.html``. For each
replayed turn it shows what was put to her, what she actually did and what the
agent did (each flagged sentence marked) side by side; the GM scores the match
(Same substance / Partly / Different). For each forward move it shows the move
and why, with flags, beside what she actually did next and the GM's own plan;
the GM approves or rejects it. Everything is kept in the artifact database as
``replay/<run_id>--<target>--<NN>`` and ``forward/<run_id>--<index>``, and can be
saved as ``scores.json``. A forward verdict is stored with the move's text and the
prompt's sha256, so the verdicts can be replayed later as a preference record.
The page decides nothing.

The template is ``review/replay_review.html``; this module only fills it.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""


from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent / "review" / "replay_review.html"
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
