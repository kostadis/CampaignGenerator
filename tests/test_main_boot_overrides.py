"""Regression tests for the boot-override construction in ``server/main.py``.

## The contract as of Phase 0 (docs/config/platform-isolation.md, O1)

Twelve CLI flags used to map to dotted ``session_doc.*`` boot-override keys:
``--session``, ``--extract-dir``, ``--roleplay-extract-dir``,
``--output-dir``, ``--summary-extract-dir``, ``--session-summary``,
``--party``, ``--voice-dir``, ``--examples``, ``--characters``,
``--narrate-tokens``, ``--context``. All twelve were silent no-ops:
``session_doc`` left ``UISection`` in Phase 5 of the session-editor
isolation, so ``CampaignConfigService.resolved()`` (now split into
``PlatformConfigService``/``UIStateService`` per
``docs/config/platform-isolation.md``) was routing every one of
them into ``ui_raw.setdefault("session_doc", {})`` — a phantom key nothing
downstream ever read. ``SessionEditorConfigService`` (the only place those
fields have meaning) reads exclusively from its own persisted
``session_doc.yaml`` plus ``platform_resolved["runtime"]["session_dir"]`` /
``["default_model"]``; it never consults ``boot_overrides`` for anything
under ``session_doc.*``.

All twelve were deleted from argparse and from ``_boot_overrides_from_args``
rather than wired to a real consumer — a real per-campaign persisted store
for those fields already exists (``session_doc.yaml``, owned by the Session
Doc Editor). The boot surface is now just the five flags that do something:
``--campaign-dir``, ``--session-dir``, ``--config-dir``, ``--host``,
``--port``. Of those, only ``--session-dir`` produces a boot override
(``runtime.session_dir``) — ``--host``/``--port`` are deliberately excluded
inside ``_boot_overrides_from_args`` (argparse can't distinguish a typed
value from a firing default, so including them would silently clobber a
custom port persisted in ``.campaigngenerator.local.yaml``).

## Why the pre-Phase-0 version of this file didn't catch the twelve dead flags

It only asserted the *mapping dict* ``_boot_overrides_from_args`` returns —
e.g. ``overrides["session_doc.scene_extractions_dir"] == "/custom/scenes"``.
Nothing asserted that any consumer ever read that key back out, so all
twelve flags could (and did) rot into no-ops without a single test
failing. ``test_session_dir_boot_override_reaches_resolved_editor_paths``
below closes that gap: it builds a real ``PlatformConfigService`` +
``SessionEditorConfigService`` pair with a boot override in place and
asserts the override changes a *resolved path* on the consumer side,
proving the value actually propagates rather than merely appearing in a
dict.

## The historical derived-vs-typed bug this file still guards against

Before Phase 0, launching with ``--session-dir`` risked ``main()``
auto-*deriving* the other session_doc-ish flags from the session dir and
folding those derived values into boot overrides. A *derived* value is not
a user override, but boot overrides win permanently in ``resolved()`` — so
a derived default would be re-applied on top of the persisted
``ui_state.yaml`` value on every read, making the field impossible to
change from the UI. That whole flag family is gone now, but the same
failure mode remains reachable through the one flag that's left
(``--session-dir`` → ``runtime.session_dir``) should a future change ever
start deriving something from it before boot overrides are captured — the
first few tests below keep freezing "typed flags become overrides,
unset/derived values never do" for that surviving flag.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server.main as server_main
from server.platform_config_service import PlatformConfigService
from server.main import _boot_overrides_from_args
from server.session_editor_config_service import SessionEditorConfigService

# Reuse the tmp-campaign scaffolding test_session_editor_config_service.py
# already built (config/ + config.yaml) instead of duplicating it here.
# Pytest puts this file's own directory on sys.path (no tests/__init__.py),
# so the plain module import resolves without a `tests.` package prefix.
from test_session_editor_config_service import _service


def _args(**over):
    """A parsed-args stand-in with the one flag ``_boot_overrides_from_args``
    still reads (``session_dir``) defaulted to ``None``, argparse's default
    when a flag is omitted."""
    base = dict(session_dir=None)
    base.update(over)
    return types.SimpleNamespace(**base)


def _boot_wired_editor_service(tmp_path: Path, session_dir: Path) -> SessionEditorConfigService:
    """A ``SessionEditorConfigService`` whose platform carries a
    ``runtime.session_dir`` boot override — the shape a real
    ``--session-dir <dir>`` launch produces in ``server.main.main()``.

    Reuses ``_service``'s tmp-campaign scaffolding (writes
    ``config/config.yaml``) for its side effect, then wraps a *second*
    ``PlatformConfigService`` — this time with ``boot_overrides`` set — over
    the same ``tmp_path``, mirroring how ``main()`` constructs the one real
    service from CLI-derived overrides.
    """
    _service(tmp_path)  # side effect only: seeds config/config.yaml on disk
    platform = PlatformConfigService(
        str(tmp_path), boot_overrides={"runtime.session_dir": str(session_dir)}
    )
    return SessionEditorConfigService(platform)


# ── _boot_overrides_from_args: only --session-dir survives ─────────────────


def test_session_dir_only_launch_produces_only_runtime_override():
    """The common launch — ``./startup --session-dir <dir>`` — must yield
    exactly ``{"runtime.session_dir": ...}``. Nothing else is left in the
    flag map to leak in."""
    overrides = _boot_overrides_from_args(_args(session_dir="/x/session"))
    assert overrides == {"runtime.session_dir": "/x/session"}


def test_unset_session_dir_produces_no_overrides():
    overrides = _boot_overrides_from_args(_args())
    assert overrides == {}


def test_empty_string_session_dir_is_ignored():
    """Empty-string args (argparse default firing on some flags) are
    dropped, same as ``None`` — they are not user intent."""
    overrides = _boot_overrides_from_args(_args(session_dir=""))
    assert overrides == {}


def test_removed_flags_produce_no_overrides_even_if_present_on_namespace():
    """Defense in depth: even if a stale caller still hands
    ``_boot_overrides_from_args`` a namespace carrying the twelve removed
    attributes (e.g. a half-migrated call site), none of them may resurrect
    a ``session_doc.*`` key — the flag_map entries that produced them are
    gone, not merely skipped."""
    ns = _args(
        session_dir="/x/session",
        session="recap.md",
        extract_dir="/custom/scenes",
        roleplay_extract_dir="/custom/roleplay",
        output_dir="/custom/output",
        summary_extract_dir="/custom/summary",
        session_summary="summary.md",
        party="party.md",
        voice_dir="/custom/voice",
        examples="/custom/examples",
        characters="Alice,Bob",
        narrate_tokens=8000,
        context=["a.md", "b.md"],
    )
    overrides = _boot_overrides_from_args(ns)
    assert overrides == {"runtime.session_dir": "/x/session"}
    assert not any(key.startswith("session_doc.") for key in overrides)


def test_argparse_rejects_removed_flag(monkeypatch, capsys):
    """The CLI surface itself must reject a removed flag, not merely fail to
    map it — proves ``--party`` (and by extension the other eleven) is
    genuinely gone from argparse, not just dropped from the mapping."""
    orig_argv = sys.argv
    try:
        sys.argv = ["prog", "--party", "party.md"]
        with pytest.raises(SystemExit) as exc_info:
            server_main.main()
        # argparse exits 2 on an unrecognized-argument parse error — this
        # happens before any campaign-dir resolution or service
        # construction, so no tmp campaign setup is needed for this test.
        assert exc_info.value.code == 2
    finally:
        sys.argv = orig_argv

    captured = capsys.readouterr()
    assert "--party" in captured.err


# ── The critical test: a surviving boot override reaches a consumer ────────


def test_session_dir_boot_override_reaches_resolved_editor_paths(tmp_path):
    """Closes the assertion gap that let the twelve dead flags die
    unnoticed: a boot override must be provably read by a consumer, not
    merely present in the dict ``_boot_overrides_from_args`` builds.

    Wires a ``PlatformConfigService`` with a ``runtime.session_dir`` boot
    override (the surviving flag) into a ``SessionEditorConfigService`` and
    asserts a session-scoped field in ``resolved_editor_config()`` — the
    Session Doc Editor's actual read path — resolves under the
    boot-overridden directory. If this override stopped reaching
    ``SessionEditorConfigService`` (the same failure mode that killed the
    twelve ``session_doc.*`` flags), this is the test that would catch it.
    """
    session_dir = tmp_path / "summaries" / "session1"
    session_dir.mkdir(parents=True)

    svc = _boot_wired_editor_service(tmp_path, session_dir)
    svc.update_config({"paths": {"scene_extractions_dir": "scene_extractions"}})

    resolved = svc.resolved_editor_config()
    assert resolved.paths.scene_extractions_dir == str(
        (session_dir / "scene_extractions").resolve()
    )
