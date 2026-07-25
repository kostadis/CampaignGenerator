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
    PLATFORM_CONFIG_NAME,
    load_platform_config,
    save_platform_config,
)

SESSION_DOC_FILENAME = "session_doc.yaml"


def read_active_backend(session_doc_path: Path) -> str | None:
    """Return ``backends.active`` from a raw ``session_doc.yaml``, or None.

    Read raw via ``yaml.safe_load`` rather than through
    ``SessionEditorConfig``: a campaign whose document fails strict validation
    for an unrelated reason should still have its backend rescued, and this CLI
    must not depend on the editor schema staying loadable.
    """
    if not session_doc_path.is_file():
        return None
    try:
        raw: Any = yaml.safe_load(session_doc_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(raw, dict):
        return None
    backends = raw.get("backends")
    if not isinstance(backends, dict):
        return None
    active = backends.get("active")
    if isinstance(active, str) and active.strip() in BACKENDS:
        return active.strip()
    return None


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

    active = read_active_backend(session_doc_path)
    if active is None:
        print(f"nothing to migrate: no usable backends.active in {session_doc_path}")
        return 0

    doc = load_platform_config(platform_path)
    current = doc.runtime.default_backend

    if current == active:
        print(f"nothing to migrate: runtime.default_backend is already {active!r}")
        return 0

    if args.dry_run:
        print(f"would set runtime.default_backend: {current!r} -> {active!r} in {platform_path}")
        return 0

    new_runtime = doc.runtime.model_copy(update={"default_backend": active})
    save_platform_config(platform_path, doc.model_copy(update={"runtime": new_runtime}))
    print(f"migrated runtime.default_backend: {current!r} -> {active!r} in {platform_path}")
    print(f"left {session_doc_path.name}'s backends block intact "
          f"(it remains the Session Doc Editor's own override)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
