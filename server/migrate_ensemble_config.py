"""One-shot migration CLI — Phase 5 of ``docs/config/ensemble-isolation.md``.

Moves the pre-Phase-5 ``ui.ensemble`` fragment out of
``<campaign>/<config-dir>/ui_state.yaml`` into the dedicated
``<campaign>/<config-dir>/ensemble.yaml`` that ``EnsembleConfigService`` now
owns exclusively.

Usage::

    python -m server.migrate_ensemble_config --campaign-dir DIR [--config-dir config] [--force]

``ui_state.yaml`` is read RAW via ``yaml.safe_load`` — deliberately NOT
through the typed ``UIState`` model, since ``UISection`` no longer declares an
``ensemble`` field and would silently drop it on load, exactly the data this
CLI exists to rescue. Mirrors ``server/migrate_session_doc.py``.

Four shape changes happen here, each one a thing the old loose section let
drift (see the design doc's "Current state"):

* ``chapters_glob`` moves under ``paths``.
* ``extract``/``synthesize`` gain a plural ``endpoints`` list. A pre-plural
  campaign stored a singular ``endpoint`` string; it is lifted into a
  one-element list. If both are present the plural wins — it is what the
  shipped frontend and both run routes have actually used.
* The six ``planning_*`` keys move into the typed ``planning`` group. Four of
  them were stored as newline-joined **strings** (the UI bound them to
  ``<textarea>``s) and become the lists the schema declares.
* ``campaign_dir`` is dropped. It is platform-tier, owned by
  ``PlatformConfigService``, and no ensemble run ever read the copy stored
  here (Phase 0).

Anything else found under ``ui.ensemble`` — the section was ``extra="allow"``,
so a stale key from an older build can be sitting there — is reported as
skipped rather than silently discarded, and never written: ``EnsembleConfig``
is strict, and quietly dropping a key the operator may still care about is the
failure mode this whole effort exists to remove.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from server.config_service import UI_STATE_NAME
from server.ensemble_config_shared import (
    ENSEMBLE_CONFIG_FILENAME,
    EnsembleConfig,
    save_ensemble_config,
)

# ui.ensemble key -> location in the grouped EnsembleConfig shape. Keys whose
# value needs reshaping (the backends and the planning_* string blobs) are
# handled explicitly in build_ensemble_config instead.
SCALAR_REMAP: dict[str, tuple[str, ...]] = {
    "chapters_glob": ("paths", "chapters_glob"),
    "chapters_selected": ("chapters_selected",),
    "known_names": ("known_names",),
    "aliases_path": ("aliases_path",),
}

# ui.ensemble planning_* key -> field in the `planning` group, with a flag for
# whether the stored value was a newline-joined string that must become a list.
PLANNING_REMAP: dict[str, tuple[str, bool]] = {
    "planning_synth_mode": ("synth_mode", False),
    "planning_depth": ("depth", False),
    "planning_npc": ("npc", True),
    "planning_arc_scores": ("arc_scores", True),
    "planning_context": ("context", True),
    "planning_force_include": ("force_include", True),
}

# Deliberately not migrated. campaign_dir is platform-tier (Phase 0); listing
# it here keeps it out of the "unrecognised keys" warning, since dropping it is
# an intended outcome rather than something the operator should review.
DROPPED_KEYS = frozenset({"campaign_dir"})


def _set_nested(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cur = target
    for key in path[:-1]:
        cur = cur.setdefault(key, {})
    cur[path[-1]] = value


def _as_list(value: Any) -> list[str]:
    """Newline-joined textarea string (or an already-list) -> list of lines."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [line.strip() for line in value.split("\n") if line.strip()]
    return []


def _backend(raw: Any) -> dict[str, Any] | None:
    """Lift a stored BackendProfile into the EnsembleBackend shape."""
    if not isinstance(raw, dict) or not raw:
        return None
    out: dict[str, Any] = {}
    if raw.get("backend"):
        out["backend"] = raw["backend"]
    if raw.get("model"):
        out["model"] = raw["model"]
    # Plural is the shipped shape; singular is the pre-migration one.
    if isinstance(raw.get("endpoints"), list) and raw["endpoints"]:
        out["endpoints"] = [str(e).strip() for e in raw["endpoints"] if str(e).strip()]
    elif raw.get("endpoint"):
        out["endpoints"] = [str(raw["endpoint"]).strip()]
    return out or None


def _load_raw_ui_state(path: Path) -> dict[str, Any]:
    """Load ``ui_state.yaml`` as a plain dict — no typed validation, so a
    pre-Phase-5 file's ``ui.ensemble`` key survives even though the current
    ``UISection`` model no longer declares it."""
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def build_ensemble_config(
    raw_ui_state: dict[str, Any],
) -> tuple[EnsembleConfig | None, list[str]]:
    """Map a raw ``ui.ensemble`` dict to a grouped :class:`EnsembleConfig`.

    Returns ``(config, skipped_keys)``. ``config`` is ``None`` when there is
    nothing to migrate; ``skipped_keys`` lists any unrecognised keys found in
    the source so the caller can surface them for review.
    """
    ui = raw_ui_state.get("ui")
    if not isinstance(ui, dict):
        return None, []

    section = ui.get("ensemble")
    if not isinstance(section, dict) or not section:
        return None, []

    grouped: dict[str, Any] = {}
    skipped: list[str] = []

    for key, value in section.items():
        if key in DROPPED_KEYS:
            continue
        if key in SCALAR_REMAP:
            # Preserve falsy-but-meaningful values (an empty chapters_selected
            # is Principle X's "nothing selected", not "unset").
            if value is not None:
                _set_nested(grouped, SCALAR_REMAP[key], value)
        elif key in PLANNING_REMAP:
            field, needs_split = PLANNING_REMAP[key]
            if value is None or value == "":
                continue
            _set_nested(
                grouped, ("planning", field), _as_list(value) if needs_split else value
            )
        elif key in ("extract", "synthesize"):
            profile = _backend(value)
            if profile:
                grouped[key] = profile
        else:
            skipped.append(key)

    if not grouped:
        return None, skipped
    return EnsembleConfig.model_validate(grouped), skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "One-shot migration: move ui.ensemble out of ui_state.yaml into "
            "the dedicated <config>/ensemble.yaml."
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
        help="Overwrite an existing ensemble.yaml",
    )
    args = parser.parse_args(argv)

    campaign_dir = Path(args.campaign_dir).expanduser().resolve()
    config_dir_path = campaign_dir / args.config_dir
    ui_state_path = config_dir_path / UI_STATE_NAME
    dest_path = config_dir_path / ENSEMBLE_CONFIG_FILENAME

    raw = _load_raw_ui_state(ui_state_path)
    cfg, skipped = build_ensemble_config(raw)
    if cfg is None:
        print(f"nothing to migrate — no ui.ensemble data found in {ui_state_path}")
        if skipped:
            print(f"  unrecognised keys left in place: {', '.join(sorted(skipped))}")
        return 0

    if dest_path.exists() and not args.force:
        print(
            f"refusing to overwrite existing {dest_path} — pass --force to overwrite.",
            file=sys.stderr,
        )
        return 1

    save_ensemble_config(dest_path, cfg)

    print("\n".join([
        "migrated ensemble config",
        f"  source:       {ui_state_path}",
        f"  destination:  {dest_path}",
        f"  chapters:     {len(cfg.chapters_selected)} selected",
        f"  known names:  {len(cfg.known_names)} source(s)",
        f"  backends:     extract={cfg.extract.backend}, "
        f"synthesize={cfg.synthesize.backend}",
    ]))
    if skipped:
        print(
            f"  SKIPPED (unrecognised, left in ui_state.yaml for review): "
            f"{', '.join(sorted(skipped))}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
