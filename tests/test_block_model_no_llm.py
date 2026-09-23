"""No LLM call anywhere in the block layer — contract X1 (#455).

This layer records what a *human* decided about a narration. One `stream_api`
call inside it — to rank the gaps, to summarise one, to draft a passage
"helpfully" — would turn a record of human decisions into a record of mixed
provenance, and nothing downstream could tell which entries were which.

That is not a style preference, so it is guarded statically rather than by
review. A grep would be fooled by a name in a docstring; this walks the AST.

**The evidence, on disk.** `experiments/20260907-phandalin-gm-gaps-selffill`:
asked to resolve its own eleven markers, the model discarded nothing, produced
the best-reading draft of the sequence, and gave **both** of the GM's
Order-of-the-Gauntlet lines to a player character — reproducing, on the one
passage the markers had protected, the exact failure they exist to prevent. A
paragraph would not have stopped a cheap-looking "resolve all gaps" button from
appearing in six months. This does.

Sibling guards: `tests/test_provenance_no_llm.py` (same shape, same reasoning,
for the provenance package) and `tests/test_retrieve_render_isolation.py`.
"""

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: Every module in the block layer. Listed rather than globbed: a new module
#: here must be added deliberately, which is the moment to ask whether it
#: belongs in a layer that may not call a model.
GUARDED = [
    "session_doc/blocks.py",
    "session_doc/authored.py",
    "session_doc/compose.py",
    "session_doc/sd_compose.py",
    "session_doc/sd_review.py",
    "session_doc/review/schema.py",
    "session_doc/review/export.py",
]

#: Importing any of these means an API client is reachable from this layer.
FORBIDDEN_MODULES = ("anthropic", "campaignlib.api", "openai")

#: Calling any of these means a model was asked to decide something.
FORBIDDEN_CALLS = ("make_client", "stream_api", "call_api", "run_batch", "messages")


def _modules():
    return [(p, ROOT / p) for p in GUARDED if (ROOT / p).is_file()]


def test_the_guard_covers_something():
    """A guard over an empty set passes vacuously and protects nothing."""
    assert _modules(), (
        "no block-layer module exists yet, so this guard is asserting nothing. "
        f"Expected at least one of: {', '.join(GUARDED)}"
    )


@pytest.mark.parametrize("rel,path", _modules(), ids=[p for p, _ in _modules()])
def test_no_api_client_is_imported(rel, path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(FORBIDDEN_MODULES), f"{rel}: {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(FORBIDDEN_MODULES), f"{rel}: {node.module}"


@pytest.mark.parametrize("rel,path", _modules(), ids=[p for p, _ in _modules()])
def test_no_model_call(rel, path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = (fn.attr if isinstance(fn, ast.Attribute)
                else fn.id if isinstance(fn, ast.Name) else None)
        assert name not in FORBIDDEN_CALLS, (
            f"{rel} calls {name}() — this layer records what a human decided, "
            "and a model deciding any part of it is the failure in "
            "experiments/20260907-phandalin-gm-gaps-selffill."
        )
