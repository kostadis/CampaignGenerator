"""Differential guard for the `locate_quote` consolidation (spec 007, D10).

`campaignlib.textproc.locate_quote` replaces two independently-grown copies of
the same whitespace-tolerant match:

    extract_facts.verify_quotes  -> kept only a bool  (q in chunk, or normalized-in-normalized)
    ensemble_merge.quote_offset  -> kept the position (find, or \\s+-joined regex)

Those two were *not* the same code, and their equivalence was never asserted
anywhere. This feature does not need the ensemble pipeline changed at all — the
rewire is a reuse-over-duplication call — so it has to be provably inert rather
than argued to be. Per specs/007-two-phase-extraction/plan.md § Complexity
Tracking: **if this file fails, revert the rewire and duplicate the matcher in
session_doc/ instead.** The ensemble corpus is not worth a tidiness win.

The reference implementations below are the pre-rewire originals, pinned here
on purpose. Do not "simplify" them to call the new helper — that would make the
test assert that a function equals itself.
"""

import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import campaignlib  # noqa: E402

# Guard against the worktree import-shadowing trap, which otherwise surfaces
# here as an opaque `ImportError: cannot import name 'locate_quote'` naming a
# path most people won't read closely.
#
# The editable install's .pth hardcodes the MAIN checkout, so `campaignlib` can
# resolve there even from inside a worktree — and once any earlier-collected
# test module has imported it (tests/benchmarks/ does, and many test files have
# no sys.path.insert of their own), it is cached in sys.modules and the
# insert above cannot win. A run in that state is testing main's code, so a
# green result here would be meaningless rather than reassuring.
_resolved = Path(campaignlib.__file__).resolve().parent.parent
if _resolved != _REPO_ROOT:
    pytest.skip(
        f"campaignlib resolved to {_resolved}, not this worktree ({_REPO_ROOT}) "
        f"— the editable-install .pth points at the main checkout, so this run "
        f"would be testing main's code, not the branch's. Run this file on its "
        f"own (`pytest tests/test_locate_quote_parity.py`), or install this "
        f"worktree into a venv of its own.",
        allow_module_level=True,
    )

from campaignlib.textproc import locate_quote  # noqa: E402
from pipelines.ensemble.extract_facts import verify_quotes  # noqa: E402
from pipelines.ensemble.ensemble_merge import quote_offset  # noqa: E402


def _legacy_verified(quote: str, chunk: str) -> bool:
    """`extract_facts.verify_quotes` as it read before the rewire."""
    chunk_norm = " ".join(chunk.split())
    return bool(quote) and (
        quote in chunk or " ".join(quote.split()) in chunk_norm
    )


def _legacy_offset(quote: str, document: str) -> int | None:
    """`ensemble_merge.quote_offset` as it read before the rewire."""
    if not quote:
        return None
    i = document.find(quote)
    if i >= 0:
        return i
    tokens = quote.split()
    if not tokens:
        return None
    pattern = re.compile(r"\s+".join(re.escape(t) for t in tokens))
    m = pattern.search(document)
    return m.start() if m else None


DOC = (
    "Kostadis Roussos: So you found yourself scrambled, so with where we\n"
    "left off, the party departed the mine with their 30 gold pieces.\n"
    "David Mendenhall: I do, like, cross promotions.\n"
    "Wade Brown: The town has been protected by the strength of Lathander.\n"
    "Stephane Bourdeaud:  I'm...  I'm...  I think,   from now on.\n"
)

CASES = [
    # exact substrings
    "I do, like, cross promotions.",
    "The town has been protected by the strength of Lathander.",
    "Kostadis Roussos:",
    # spans a newline in the document -> only the tolerant tier can find it
    "So you found yourself scrambled, so with where we left off, the party",
    # quote carries collapsed whitespace where the document has runs
    "I'm... I'm... I think, from now on.",
    # quote carries MORE whitespace than the document
    "I  do,  like,  cross   promotions.",
    # leading/trailing whitespace
    "  I do, like, cross promotions.  ",
    # absent
    "I have always hated the sea and everything in it.",
    # regex metacharacters must be escaped, not interpreted
    "30 gold pieces.",
    "(paraphrase)",
    "a.b*c+d?",
    # degenerate
    "",
    "   ",
    "\n",
]


@pytest.mark.parametrize("quote", CASES)
def test_offset_matches_legacy(quote):
    assert locate_quote(quote, DOC) == _legacy_offset(quote, DOC)


@pytest.mark.parametrize("quote", CASES)
def test_boolean_matches_legacy_verified(quote):
    """The bool `verify_quotes` derives must agree with the old containment test.

    This is the assertion that actually mattered and had never been made: the
    two legacy implementations normalized *different sides* of the comparison
    (verify_quotes collapsed both quote and chunk; quote_offset turned the
    quote's whitespace into `\\s+` and searched the raw document), so agreement
    was plausible but unproven.
    """
    assert (locate_quote(quote, DOC) is not None) == _legacy_verified(quote, DOC)


@pytest.mark.parametrize("quote", CASES)
def test_public_callers_still_agree_with_legacy(quote):
    """The rewired public functions, not just the helper underneath them."""
    assert quote_offset(quote, DOC) == _legacy_offset(quote, DOC)

    facts = [{"source_quote": quote}]
    verify_quotes(facts, DOC)
    assert facts[0]["quote_verified"] == _legacy_verified(quote, DOC)


def test_verify_quotes_skips_non_dict_entries():
    """Pre-existing tolerance for junk in the fact list must survive."""
    facts = [{"source_quote": "I do, like, cross promotions."}, "not-a-dict", None]
    verify_quotes(facts, DOC)
    assert facts[0]["quote_verified"] is True
    assert facts[1] == "not-a-dict"


def test_missing_source_quote_is_unverified():
    facts = [{}, {"source_quote": None}]
    verify_quotes(facts, DOC)
    assert all(f["quote_verified"] is False for f in facts)


def test_offset_actually_points_at_the_quote():
    """A returned offset must be usable, not merely equal to the legacy value."""
    q = "The town has been protected"
    i = locate_quote(q, DOC)
    assert i is not None and DOC[i:i + len(q)] == q
