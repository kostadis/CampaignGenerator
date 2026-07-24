"""One-shot migration CLI — Phase 5 of
``docs/config/session-editor-isolation.md``.

Moves the pre-Phase-5 ``ui.session_doc`` + ``ui.profiles`` fragments out of
``<campaign>/<config-dir>/ui_state.yaml`` into the dedicated
``<campaign>/<config-dir>/session_doc.yaml`` that
``SessionEditorConfigService`` now owns exclusively.

Usage::

    python -m server.migrate_session_doc --campaign-dir DIR [--config-dir config] [--force]

``ui_state.yaml`` is read RAW via ``yaml.safe_load`` — deliberately NOT
through the typed ``UIState`` model, since ``UISection`` no longer declares
``session_doc``/``profiles`` fields (Task 2 of this phase) and would
silently drop them on load, exactly the data this CLI exists to rescue.

The flat-typed -> grouped field remap is the single authority in
``server.session_editor_config_shared.TYPED_SESSION_DOC_TO_GROUPED`` — the
same table ``SessionEditorConfigService``'s (now-deleted) temporary adapter
used in Phases 1-4.

Migrated path values are copied as-is. The old ``ui.session_doc`` fields
were already stored relative (to ``runtime.session_dir`` / campaign_dir,
per the retired ``CampaignConfigService._PATH_FIELDS["session_doc"]``) —
exactly what ``session_doc.yaml``'s path fields expect — so this CLI does
NOT re-resolve or re-relativize anything.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from server.config_service import UI_STATE_NAME
from server.session_editor_config_service import SESSION_DOC_FILENAME
from server.session_editor_config_shared import (
    SessionEditorConfig,
    TYPED_SESSION_DOC_TO_GROUPED,
    save_session_editor_config,
)


def _set_nested(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cur = target
    for key in path[:-1]:
        cur = cur.setdefault(key, {})
    cur[path[-1]] = value


def _load_raw_ui_state(path: Path) -> dict[str, Any]:
    """Load ``ui_state.yaml`` as a plain dict — no typed validation, so a
    pre-Phase-5 file's ``ui.session_doc``/``ui.profiles`` keys survive even
    though the current ``UISection`` model no longer declares them."""
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def build_grouped_config(raw_ui_state: dict[str, Any]) -> SessionEditorConfig | None:
    """Map the raw ``ui.session_doc`` + ``ui.profiles`` dicts to a grouped
    :class:`SessionEditorConfig`.

    Returns ``None`` when there is nothing to migrate — no (non-empty)
    ``ui.session_doc`` and no (non-empty) ``ui.profiles`` in the source.
    """
    ui = raw_ui_state.get("ui")
    if not isinstance(ui, dict):
        return None

    session_doc = ui.get("session_doc")
    profiles_section = ui.get("profiles")

    has_session_doc = isinstance(session_doc, dict) and bool(session_doc)
    has_profiles = isinstance(profiles_section, dict) and bool(
        profiles_section.get("profiles") or profiles_section.get("active")
    )
    if not has_session_doc and not has_profiles:
        return None

    grouped: dict[str, Any] = {}
    if has_session_doc:
        for typed_key, target in TYPED_SESSION_DOC_TO_GROUPED.items():
            if typed_key not in session_doc:
                continue
            _set_nested(grouped, target, session_doc[typed_key])

    if has_profiles:
        grouped["profiles"] = profiles_section.get("profiles") or []
        grouped["active_profile"] = profiles_section.get("active")

    return SessionEditorConfig.model_validate(grouped)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "One-shot migration: move ui.session_doc + ui.profiles out of "
            "ui_state.yaml into the dedicated <config>/session_doc.yaml."
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
        help="Overwrite an existing session_doc.yaml",
    )
    args = parser.parse_args(argv)

    campaign_dir = Path(args.campaign_dir).expanduser().resolve()
    config_dir_path = campaign_dir / args.config_dir
    ui_state_path = config_dir_path / UI_STATE_NAME
    dest_path = config_dir_path / SESSION_DOC_FILENAME

    raw = _load_raw_ui_state(ui_state_path)
    cfg = build_grouped_config(raw)
    if cfg is None:
        print(
            f"nothing to migrate — no ui.session_doc/ui.profiles data found "
            f"in {ui_state_path}"
        )
        return 0

    if dest_path.exists() and not args.force:
        print(
            f"refusing to overwrite existing {dest_path} — pass --force to overwrite.",
            file=sys.stderr,
        )
        return 1

    save_session_editor_config(dest_path, cfg)

    path_fields_set = sum(1 for v in cfg.paths.model_dump().values() if v)
    summary_lines = [
        "migrated session-editor config",
        f"  source:       {ui_state_path}",
        f"  destination:  {dest_path}",
        f"  path fields:  {path_fields_set}",
        f"  profiles:     {len(cfg.profiles)}"
        + (f" (active: {cfg.active_profile})" if cfg.active_profile else ""),
    ]
    print("\n".join(summary_lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
