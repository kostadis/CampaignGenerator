"""SC-006, as an assertion rather than a claim.

``docs/design/PlayerIdentity.md`` measured the failure class this feature
exists to remove and found a clean split:

    Everything that fails LOUDLY is a path, or an exact-match refusal.
    Everything that fails SILENTLY is a name approximately matched.

Feature 009 deleted the approximate matches. This module asserts they stay
deleted — that the render path resolves an identity by an exact match, a
declared path, or a refusal, and never by a shared prefix.

It is deliberately structural rather than behavioural. A behavioural test
proves the current call sites do the right thing; the risk here is the *next*
person reaching for `startswith` because it is convenient, in a call site that
does not exist yet. ``tests/test_ensemble_config_defaults.py`` guards the
analogous "no default literal reappears in the router" rule the same way.

The history is why the bar is this high:

* #247 — a real voice file on disk never reached the prompt for five months.
* #300 — a typo'd ``voice_dir`` silently dropped every voice spec, and the
  #247 warning could not fire because it needed a non-empty result.
* #301 — an example file that matched nobody joined a block sent to EVERY
  narrator, so one character's style steered all of them.
* campaigns#175 — a renamed character stopped resolving, and the obvious
  one-line repair converted the silent drop into the #301 bleed.
* #315 — the detector added for #301 could not see a rename, so it reported
  nothing in all three measured scenarios.

Five defects, one rule.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

#: Modules that resolve a narrator, a character or a player to something.
IDENTITY_MODULES = (
    "session_doc/voice.py",
    "session_doc/examples.py",
    "session_doc/sd_narrate.py",
    "session_doc/narrate.py",
    "session_doc/roster.py",
    "campaignlib/players_config.py",
    "campaignlib/party_config.py",
)

#: Gone, and staying gone. Each was a step in the first-name-prefix rule or a
#: detector for the fall-through that rule created.
DELETED_SYMBOLS = (
    ("session_doc.examples", "routes_to"),
    ("session_doc.examples", "examples_routing_problems"),
    ("session_doc.voice", "_resolve_voice_key"),
    ("session_doc.voice", "voice_resolution_problems"),
    ("session_doc.voice", "_first_name"),
    ("campaignlib.npc", "player_map_from_config"),
)


@pytest.mark.parametrize("module_name,symbol", DELETED_SYMBOLS)
def test_the_prefix_rule_and_its_detector_stay_deleted(module_name, symbol):
    """Re-adding any of these is re-adding the defect.

    ``examples_routing_problems`` is on the list for a reason worth stating: it
    was the *fix* for #301, and it could not see the case that produced
    campaigns#175. A detector for a fall-through that no longer exists has
    nothing to detect — keeping it would be keeping a signal that reads as
    coverage and is not.
    """
    module = __import__(module_name, fromlist=[symbol])
    assert not hasattr(module, symbol), (
        f"{module_name}.{symbol} is back. It resolved an identity from a shared "
        f"name prefix, which is the mechanism behind #247, #300, #301, #315 and "
        f"campaigns#175. See docs/design/PlayerIdentity.md."
    )


def _prefix_calls(path: Path) -> list[str]:
    """``x.startswith(y)`` calls whose receiver is not a literal string.

    A literal — ``line.startswith("#")``, ``name.startswith("_")`` — is parsing
    text, not asserting that two names denote the same character. Those are
    fine and there are several. What is forbidden is testing one *name* against
    another *name*.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "startswith":
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            continue          # a literal prefix — parsing, not identity
        found.append(f"line {node.lineno}: {ast.unparse(node)[:90]}")
    return found


@pytest.mark.parametrize("rel", IDENTITY_MODULES)
def test_no_identity_is_asserted_from_a_name_prefix(rel):
    """Zero prefix-matched identity joins in the render path.

    This restates, for the joins that predate it, the rule
    ``provenance/identity.py`` already enforces elsewhere:

        Nothing here computes a string distance in order to *assert* a match.
        ``Vera`` does not resolve to ``Veyra`` because they look alike — it
        resolves only if a GM has recorded the link.

    Voice and example routing predate that doctrine and were never held to it.
    They are now.
    """
    offenders = _prefix_calls(REPO_ROOT / rel)
    assert not offenders, (
        f"{rel} resolves a name against another name with startswith():\n  "
        + "\n  ".join(offenders)
        + "\n\nUse an exact match or a declared path. A character's voice and "
          "example files are named by its party.yaml entry; a player's display "
          "names are listed in players.yaml and matched exactly."
    )


def test_the_declared_replacements_exist():
    """The other half of the guard: deleting the rule without the declarations
    would simply mean nothing resolves. Named here so a partial revert cannot
    leave the codebase with neither."""
    from campaignlib.party_config import PATH_FIELDS
    from session_doc.examples import (  # noqa: F401
        load_declared_examples,
        load_shared_examples,
        undeclared_files,
    )
    from session_doc.voice import (  # noqa: F401
        load_declared_voices,
        unknown_narrators,
        voice_declaration_problems,
    )

    assert "voice" in PATH_FIELDS
    assert "examples" in PATH_FIELDS
