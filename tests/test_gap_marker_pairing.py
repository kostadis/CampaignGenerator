"""The gap marker has a live producer — contract X2 (#455).

`26ec5b0` deleted the prompt that emitted `table-speech reclassified:` and left
everything downstream standing: the stripper in `assemble.py`, its seven tests,
a mandatory section in an out-of-repo review skill, and `/scrub`'s masking.
Nothing failed, because nothing tied a marker to a producer (#396).

Here the exposure is worse. The gap marker has **two** consumers — the block
parser and `assemble`'s gate — and both would keep passing their own tests while
the contract that feeds them was edited away. The visible symptom would be
scenes that quietly stop having gaps, which reads as the model behaving
differently rather than as a deleted rule.

Sibling: `tests/test_apparatus_marker_pairing.py`, which does the same job for
the comment-shaped markers `assemble` strips. This marker is deliberately NOT
one of those — it is content, and stripping it would delete the feature's own
output.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from session_doc.blocks import GAP_MARKER  # noqa: E402

CONTRACT = ROOT / "config/agents/session_doc/narrate/gm_attribution_gap.md"


def test_the_contract_fragment_exists():
    """#455 depends on #454. If the fragment is gone, nothing emits gaps and
    every parser in this layer is reading for something that is never written."""
    assert CONTRACT.is_file(), (
        f"the gap-marking contract is missing: {CONTRACT}. "
        "Without it sd_narrate emits no markers and this whole layer is inert."
    )


def test_the_marker_constant_appears_in_the_prompt_that_emits_it():
    """The binding. One definition in `session_doc/blocks.py`, and the prompt
    asking for it must contain that exact string."""
    assert GAP_MARKER in CONTRACT.read_text(encoding="utf-8")


def test_the_marker_is_not_an_apparatus_comment():
    """It must never join `APPARATUS_MARKERS`.

    That registry drives `strip_audit_comments`, which REMOVES what it matches
    from the assembled document. A gap marker is the feature's output — #455
    composes it away and #456 edits it — so registering it would delete the
    thing at assembly. Asserted here as well as in the apparatus suite, because
    the reflex to register a new marker is strong and the failure is silent.
    """
    from session_doc.apparatus import APPARATUS_MARKERS, strip_audit_comments

    assert not any("GM NARRATION" in m.pattern for m in APPARATUS_MARKERS)
    body = f"prose\n\n{GAP_MARKER} something the GM established]\n"
    assert GAP_MARKER in strip_audit_comments(body)
