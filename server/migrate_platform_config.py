"""One-shot migration CLI — Phase 3 of ``docs/config/platform-isolation.md``
(O3).

Moves the ``runtime`` key out of ``<campaign>/<config-dir>/ui_state.yaml``
into the dedicated ``<campaign>/<config-dir>/platform.yaml`` that
``PlatformConfigService`` now owns exclusively.

Usage::

    python -m server.migrate_platform_config --campaign-dir DIR [--config-dir config] [--force]

Modelled directly on ``server/migrate_session_doc.py`` (Phase 5 of
``docs/config/session-editor-isolation.md``): ``ui_state.yaml`` is read RAW
via ``yaml.safe_load`` — deliberately NOT through the typed ``UIState``
model, since ``UIState`` no longer declares a ``runtime`` field (Phase 3's
Task 2 in ``server/config_models.py``) and would silently drop it on load,
exactly the data this CLI exists to rescue. Only ``UIState``'s
``extra="allow"`` root config keeps that drop harmless rather than fatal —
this CLI is what turns "harmlessly ignored" into "durably migrated".

Only the two keys the live ``PlatformRuntime`` schema still recognizes
(``default_model``, ``session_dir``) are carried over; anything else that
may have accumulated under a pre-Phase-3 ``runtime:`` block (the retired
``RuntimeSection`` was ``extra="allow"``, so a stray key was possible even
though nothing in this codebase ever wrote one) is silently dropped, the
same "explicit known-field table, nothing else survives" contract
``migrate_session_doc.py``'s ``TYPED_SESSION_DOC_TO_GROUPED`` uses.

Migrated values are copied as-is. The old ``runtime.session_dir`` was
already stored relative-to-campaign (per the retired
``CampaignConfigService``/``UIStateService`` ``_RUNTIME_PATH_FIELDS``) —
exactly what ``platform.yaml``'s ``runtime.session_dir`` field expects — so
this CLI does NOT re-resolve or re-relativize anything.

Unlike ``migrate_session_doc.py``, a second run against an unchanged source
is NOT treated as "refuse to overwrite" — it is treated as nothing left to
do. ``main()`` compares the runtime data it would write against
``platform.yaml``'s current contents (if any) and reports "nothing to
migrate" whenever they already agree, so re-running this CLI (e.g. from an
idempotent provisioning script) is a safe no-op rather than an error the
operator has to remember to route around with ``--force``. ``--force`` is
still required to overwrite a platform.yaml whose runtime data GENUINELY
differs from what the source would produce (e.g. hand-edited or migrated
from a different source).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from server.config_service import UI_STATE_NAME
from server.platform_config_service import PLATFORM_CONFIG_NAME
from server.platform_config_shared import (
    PlatformDocument,
    PlatformRuntime,
    load_platform_config,
    save_platform_config,
)

# The only fields the live PlatformRuntime schema recognizes. Anything else
# that may be sitting in a pre-Phase-3 `runtime:` block is dropped, not
# preserved — see module docstring.
_KNOWN_RUNTIME_KEYS: tuple[str, ...] = ("default_model", "session_dir")


def _load_raw_ui_state(path: Path) -> dict[str, Any]:
    """Load ``ui_state.yaml`` as a plain dict — no typed validation, so a
    pre-Phase-3 file's ``runtime`` key survives even though the current
    ``UIState`` model no longer declares it."""
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def build_platform_document(raw_ui_state: dict[str, Any]) -> PlatformDocument | None:
    """Map the raw ``runtime`` dict to a :class:`PlatformDocument`.

    Returns ``None`` when there is nothing to migrate: no ``runtime`` key at
    all, an empty ``runtime`` dict, or a ``runtime`` dict whose only keys are
    ones :data:`_KNOWN_RUNTIME_KEYS` doesn't recognize.
    """
    runtime = raw_ui_state.get("runtime")
    if not isinstance(runtime, dict) or not runtime:
        return None
    grouped = {k: runtime[k] for k in _KNOWN_RUNTIME_KEYS if k in runtime}
    if not grouped:
        return None
    return PlatformDocument(runtime=PlatformRuntime.model_validate(grouped))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "One-shot migration: move the `runtime` key out of ui_state.yaml "
            "into the dedicated <config>/platform.yaml."
        )
    )
    parser.add_argument(
        "--campaign-dir", required=True, metavar="DIR",
        help="Campaign root directory (contains <config-dir>/ui_state.yaml)",
    )
    parser.add_argument(
        "--config-dir", default="config", metavar="DIR",
        help="Configuration subdirectory within campaign (default: 'config')",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite an existing platform.yaml whose runtime data differs",
    )
    args = parser.parse_args(argv)

    campaign_dir = Path(args.campaign_dir).expanduser().resolve()
    config_dir_path = campaign_dir / args.config_dir
    ui_state_path = config_dir_path / UI_STATE_NAME
    dest_path = config_dir_path / PLATFORM_CONFIG_NAME

    raw = _load_raw_ui_state(ui_state_path)
    doc = build_platform_document(raw)
    if doc is None:
        print(
            f"nothing to migrate — no runtime data found in {ui_state_path}"
        )
        return 0

    if dest_path.exists():
        existing = load_platform_config(dest_path)
        if existing.runtime == doc.runtime:
            print(
                f"nothing to migrate — {dest_path} already reflects this "
                f"runtime state"
            )
            return 0
        if not args.force:
            print(
                f"refusing to overwrite existing {dest_path} with different "
                f"runtime data — pass --force to overwrite.",
                file=sys.stderr,
            )
            return 1

    save_platform_config(dest_path, doc)

    summary_lines = [
        "migrated platform config",
        f"  source:       {ui_state_path}",
        f"  destination:  {dest_path}",
        f"  default_model: {doc.runtime.default_model}",
        f"  session_dir:   {doc.runtime.session_dir or '(unset)'}",
    ]
    print("\n".join(summary_lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
