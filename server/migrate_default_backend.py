"""One-shot migration CLI — feature 003, ``specs/003-model-selection-resolution``.

Moves the **app-wide backend choice** out of ``<config>/session_doc.yaml``'s
``backends.active`` and into ``<config>/platform.yaml``'s
``runtime.default_backend``.

Usage::

    python -m server.migrate_default_backend --campaign-dir DIR [--config-dir config]

Why this exists
---------------
Before feature 003, the sidebar showed a MODEL picker and a BACKEND toggle side
by side and presented both as global. They were not: MODEL wrote
``platform.yaml``'s ``runtime.default_model``, while BACKEND wrote
``session_doc.yaml``'s ``backends.active`` — the Session Doc Editor's *own*
service config. That asymmetry is why ``server/routers/grounding.py`` had to
construct a ``SessionEditorConfigService`` to find out which backend to run on,
and why a Grounding run could carry a model from one owner and a backend from
another.

This CLI copies the de-facto global value up to the tier that now owns it.

What it deliberately does NOT do
--------------------------------
It does **not** remove ``backends`` from ``session_doc.yaml``. Under the new
rule that block is legitimate — it is the Session Doc Editor's own per-service
override, which the editor is entitled to keep. Only its *role as the app-wide
value* moves. Deleting it would destroy a real setting, not clean up a stale
one.

Idempotence
-----------
Re-running against an already-migrated campaign is a no-op that reports
"nothing to migrate", matching ``server/migrate_platform_config.py``'s contract
so this is safe to call from a provisioning script.

Note this is a *separate* CLI rather than an extension of
``migrate_platform_config.py``: that script's input is ``ui_state.yaml``, which
``docs/config/ui-state-retirement.md`` deleted. Bolting an unrelated
session_doc→platform copy onto a script whose own source file no longer exists
would leave one CLI with two premises, one of them dead.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from server.platform_config_shared import (
    BACKENDS,
    compatible,
    PLATFORM_CONFIG_NAME,
    load_platform_config,
    save_platform_config,
)

SESSION_DOC_FILENAME = "session_doc.yaml"


def read_active_selection(session_doc_path: Path) -> tuple[str | None, str | None]:
    """Return ``(backends.active, backends.<active>.model)`` from a raw
    ``session_doc.yaml``.

    The **model matters as much as the backend**. Before 003 a Grounding run on
    dgx got its backend AND its model from this document (via the cross-service
    read); migrating only the backend would leave the platform's Anthropic
    default paired with a local backend — an incompatible pair that refuses
    every run. A campaign that was working before the migration would be wholly
    blocked after it. Carrying the model across is not a substitution: it is the
    selection that was already in effect.

    Read raw via ``yaml.safe_load`` rather than through
    ``SessionEditorConfig``: a campaign whose document fails strict validation
    for an unrelated reason should still have its backend rescued, and this CLI
    must not depend on the editor schema staying loadable.
    """
    if not session_doc_path.is_file():
        return None, None
    try:
        raw: Any = yaml.safe_load(session_doc_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None, None
    if not isinstance(raw, dict):
        return None, None
    backends = raw.get("backends")
    if not isinstance(backends, dict):
        return None, None
    active = backends.get("active")
    if not (isinstance(active, str) and active.strip() in BACKENDS):
        return None, None
    active = active.strip()
    profile = backends.get(active)
    model = None
    if isinstance(profile, dict):
        candidate = profile.get("model")
        if isinstance(candidate, str) and candidate.strip():
            model = candidate.strip()
    return active, model


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate the app-wide backend from session_doc.yaml to platform.yaml",
    )
    parser.add_argument("--campaign-dir", required=True, metavar="DIR")
    parser.add_argument("--config-dir", default="config", metavar="DIR")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing")
    args = parser.parse_args(argv)

    config_base = Path(args.campaign_dir).expanduser().resolve() / args.config_dir
    session_doc_path = config_base / SESSION_DOC_FILENAME
    platform_path = config_base / PLATFORM_CONFIG_NAME

    active, active_model = read_active_selection(session_doc_path)
    if active is None:
        print(f"nothing to migrate: no usable backends.active in {session_doc_path}")
        return 0

    doc = load_platform_config(platform_path)
    current = doc.runtime.default_backend
    current_model = doc.runtime.default_model

    # Carry the model across too, but only when the one already on the platform
    # cannot serve the incoming backend. An operator who has deliberately set a
    # compatible model keeps it; one whose platform still holds the Anthropic
    # default gets the model that was actually in effect for this backend.
    update: dict[str, str] = {}
    if current != active:
        update["default_backend"] = active
    if active_model and not compatible(current_model, active):
        update["default_model"] = active_model

    if not update:
        print(f"nothing to migrate: runtime.default_backend is already {active!r} "
              f"and {current_model!r} can serve it")
        return 0

    if args.dry_run:
        for key, value in update.items():
            was = current if key == "default_backend" else current_model
            print(f"would set runtime.{key}: {was!r} -> {value!r} in {platform_path}")
        if "default_model" not in update and not compatible(current_model, active):
            print(f"WARNING: {current_model!r} cannot run on {active!r} and "
                  f"{session_doc_path.name} pins no model for it — set one in the "
                  f"sidebar or every run will be refused")
        return 0

    new_runtime = doc.runtime.model_copy(update=update)
    save_platform_config(platform_path, doc.model_copy(update={"runtime": new_runtime}))
    for key, value in update.items():
        was = current if key == "default_backend" else current_model
        print(f"migrated runtime.{key}: {was!r} -> {value!r} in {platform_path}")
    if not compatible(new_runtime.default_model, new_runtime.default_backend):
        print(f"WARNING: {new_runtime.default_model!r} cannot run on "
              f"{new_runtime.default_backend!r} — {session_doc_path.name} pinned no "
              f"model for that backend. Set one in the sidebar or every run will "
              f"be refused.")
    print(f"left {session_doc_path.name}'s backends block intact "
          f"(it remains the Session Doc Editor's own override)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
