"""Regression tests for the boot-override construction in ``server/main.py``.

The bug: launching with ``--session-dir`` made ``main()`` auto-*derive*
``args.extract_dir`` (and the other session_doc paths) from the session dir,
and then built boot overrides from those args. A *derived* value is not a user
override, but boot overrides win permanently in ``resolved()`` — so the derived
default was re-applied on top of the persisted ``ui_state.yaml`` on every read,
making ``scene_extractions_dir`` (and every other derived session_doc field)
impossible to change from the UI.

The fix computes boot overrides from the *raw* args, before the derivation
block backfills them, so only genuinely user-typed flags become overrides.
These tests freeze the contract ``_boot_overrides_from_args`` must satisfy for
that fix to hold: an unset (derived) flag never becomes an override; an
explicitly-set flag does.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.main import _boot_overrides_from_args


def _args(**over):
    """A parsed-args stand-in with every flag ``_boot_overrides_from_args``
    reads defaulted to ``None`` (argparse's default when a flag is omitted)."""
    base = dict(
        session=None,
        extract_dir=None,
        roleplay_extract_dir=None,
        output_dir=None,
        summary_extract_dir=None,
        session_summary=None,
        party=None,
        voice_dir=None,
        examples=None,
        characters=None,
        narrate_tokens=None,
        session_dir=None,
        context=None,
    )
    base.update(over)
    return types.SimpleNamespace(**base)


# The session_doc path fields that get *derived* from --session-dir in main().
# None of these may appear as boot overrides unless the user typed the flag.
_DERIVED_SESSION_DOC_KEYS = {
    "session_doc.session",
    "session_doc.scene_extractions_dir",
    "session_doc.roleplay_dir",
    "session_doc.output_dir",
    "session_doc.summary_dir",
    "session_doc.session_summary",
    "session_doc.party",
    "session_doc.voice_dir",
    "session_doc.examples_dir",
    "session_doc.characters",
}


def test_session_dir_only_launch_produces_no_session_doc_overrides():
    """The common launch — ``./startup --session-dir <dir>`` with no per-field
    flags — must yield only the runtime.session_dir override. Every derived
    session_doc path stays out, so the persisted ui_state value wins."""
    overrides = _boot_overrides_from_args(_args(session_dir="/x/session"))
    assert overrides == {"runtime.session_dir": "/x/session"}
    assert _DERIVED_SESSION_DOC_KEYS.isdisjoint(overrides)


def test_unset_extract_dir_is_not_promoted():
    """The exact field from the bug report: an unset (later-derived)
    ``extract_dir`` must not become ``session_doc.scene_extractions_dir``."""
    overrides = _boot_overrides_from_args(_args(session_dir="/x/session"))
    assert "session_doc.scene_extractions_dir" not in overrides


def test_explicitly_typed_flags_still_become_overrides():
    """A flag the user actually typed is a real override and must win — this is
    why the fix snapshots raw args rather than dropping the flags entirely."""
    overrides = _boot_overrides_from_args(
        _args(
            session_dir="/x/session",
            extract_dir="/custom/scenes",
            narrate_tokens=8000,
        )
    )
    assert overrides["session_doc.scene_extractions_dir"] == "/custom/scenes"
    assert overrides["session_doc.narrate_tokens"] == 8000
    assert overrides["runtime.session_dir"] == "/x/session"


def test_empty_string_flags_are_ignored():
    """Empty-string args (argparse default firing on some flags) are dropped,
    same as ``None`` — they are not user intent."""
    overrides = _boot_overrides_from_args(_args(session_dir="/x/session", party=""))
    assert "session_doc.party" not in overrides


def test_context_list_is_forwarded_when_present():
    overrides = _boot_overrides_from_args(
        _args(session_dir="/x/session", context=["a.md", "b.md"])
    )
    assert overrides["session_doc.context"] == ["a.md", "b.md"]
