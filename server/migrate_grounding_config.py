"""One-shot migration CLI — Phase 10 of ``docs/config/grounding-isolation.md``.

Moves the five pre-Phase-10 ``ui.<section>`` fragments — ``ui.grounding``,
``ui.campaign_state``, ``ui.distill``, ``ui.party``, ``ui.planning`` — out of
``<campaign>/<config-dir>/ui_state.yaml`` into the dedicated
``<campaign>/<config-dir>/grounding.yaml`` that ``GroundingConfigService`` now
owns exclusively.

Usage::

    python -m server.migrate_grounding_config --campaign-dir DIR [--config-dir config] [--force]

``ui_state.yaml`` is read RAW via ``yaml.safe_load`` — deliberately NOT through
the typed ``UIState`` model, since ``UISection`` no longer declares these
fields and would silently drop them on load, exactly the data this CLI exists
to rescue. Mirrors ``server/migrate_ensemble_config.py``.

**Expect this to migrate very little, and that is not a bug.** Two of the five
sections were *write-never*: ``CampaignState.vue`` and ``DistillWorldState.vue``
read their keys on mount but never called ``updateSection``, so unless the GM
hand-edited ``ui_state.yaml`` there is nothing stored to move. ``ui.party`` and
``ui.planning`` each persisted two fields out of the nine and twelve they read.
The output says so explicitly rather than letting an almost-empty result read
as a failure.

Shape changes handled here:

* ``ui.grounding.summaries`` becomes the root ``summaries`` pointer — the one
  value all four runs inherit when their own ``input`` is blank.
* campaign_state's ``track_file`` (singular) + ``track_files_extra``
  (newline-joined textarea) merge into ``track_files``; ``track`` becomes
  ``track_items``.
* party's ``chars``/``backstory``/``arc_scores``/``context`` and planning's
  ``npc``/``arc_scores``/``context`` were newline-joined **strings** (the UI
  bound them to ``<textarea>``s) and become the lists the schema declares.
* planning's five ``build_*``/``dossier_dir`` keys move into the nested
  ``dossiers`` group.
* Each section's ``input``/``summaries`` becomes that doc's ``input``.

Anything else found under those sections — they were ``extra="allow"``, so a
stale key from an older build can be sitting there — is reported as skipped
rather than silently discarded, and never written: ``GroundingConfig`` is
strict, and quietly dropping a key the operator may still care about is the
failure mode this whole effort exists to remove.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from server.migrate_common import UI_STATE_NAME
from server.grounding_config_shared import (
    GROUNDING_CONFIG_FILENAME,
    GroundingConfig,
    save_grounding_config,
)

#: ui.<section> key -> field name in that doc's group. Keys needing a shape
#: change (the newline-joined string blobs, the track_* merge) are handled
#: explicitly in :func:`build_grounding_config`.
_COMMON_REMAP: dict[str, str] = {
    "input": "input",
    "summaries": "input",  # each page's own timeline pointer is its input
    "output": "output",
    "extract_dir": "extract_dir",
    "split_chapters": "split_chapters",
    "chunk_size": "chunk_size",
    "no_log": "no_log",
}

#: Per-section keys that are newline-joined textareas on the wire but lists in
#: the schema.
_LIST_FIELDS: dict[str, dict[str, str]] = {
    "party": {"chars": "characters", "backstory": "backstory",
              "arc_scores": "arc_scores", "context": "context"},
    "planning": {"npc": "npc", "arc_scores": "arc_scores", "context": "context"},
    "campaign_state": {},
    "distill": {},
}

#: Scalars that survive with a rename, per section.
_EXTRA_SCALARS: dict[str, dict[str, str]] = {
    "party": {"mode": "mode", "config_path": "config_path"},
    "planning": {"synth_mode": "synth_mode", "config_path": "config_path"},
    "campaign_state": {},
    "distill": {},
}

#: planning's build-dossiers sub-form -> the nested `dossiers` group.
_DOSSIER_REMAP: dict[str, str] = {
    "build_summaries": "summaries",
    "dossier_dir": "dossier_dir",
    "build_extract_dir": "extract_dir",
    "build_split_chapters": "split_chapters",
    "build_since": "since",
}

SECTIONS = ("campaign_state", "distill", "party", "planning")


def _load_raw_ui_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SystemExit(f"migrate_grounding_config: {path}: {exc}")
    return raw if isinstance(raw, dict) else {}


def _as_list(value: Any) -> list[str]:
    """Newline-joined textarea, or an already-a-list value, to a clean list."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [line.strip() for line in value.split("\n") if line.strip()]
    return []


def build_grounding_config(
    raw_ui_state: dict[str, Any]
) -> tuple[GroundingConfig | None, set[str], dict[str, int]]:
    """Translate raw ``ui_state.yaml`` into a :class:`GroundingConfig`.

    Returns ``(config, skipped_keys, per_section_counts)``. ``config`` is None
    when there is nothing at all to migrate. ``skipped_keys`` are reported,
    never written — see the module docstring.
    """
    ui = raw_ui_state.get("ui")
    if not isinstance(ui, dict):
        return None, set(), {}

    out: dict[str, Any] = {}
    skipped: set[str] = set()
    counts: dict[str, int] = {}

    grounding = ui.get("grounding")
    if isinstance(grounding, dict):
        for key, value in grounding.items():
            if key == "summaries":
                if value:
                    out["summaries"] = value
                    counts["grounding"] = counts.get("grounding", 0) + 1
            else:
                skipped.add(f"ui.grounding.{key}")

    for section in SECTIONS:
        blob = ui.get(section)
        if not isinstance(blob, dict):
            continue
        group: dict[str, Any] = {}
        dossiers: dict[str, Any] = {}
        lists = _LIST_FIELDS[section]
        scalars = _EXTRA_SCALARS[section]

        for key, value in blob.items():
            if value in (None, "", []):
                continue
            if section == "campaign_state" and key in (
                "track_file", "track_files_extra", "track_files"
            ):
                group.setdefault("track_files", [])
                group["track_files"].extend(_as_list(value))
            elif section == "campaign_state" and key in ("track", "track_items"):
                group.setdefault("track_items", [])
                group["track_items"].extend(_as_list(value))
            elif section == "planning" and key in _DOSSIER_REMAP:
                dossiers[_DOSSIER_REMAP[key]] = (
                    value if key == "build_since" else str(value)
                )
            elif key in lists:
                group[lists[key]] = _as_list(value)
            elif key in scalars:
                group[scalars[key]] = value
            elif key in _COMMON_REMAP:
                # `input` beats `summaries` when a section somehow has both.
                target = _COMMON_REMAP[key]
                if target == "input" and group.get("input") and key == "summaries":
                    continue
                group[target] = value
            else:
                skipped.add(f"ui.{section}.{key}")

        if dossiers:
            group["dossiers"] = dossiers
        if group:
            out[section] = group
            counts[section] = len(group)

    if not out:
        return None, skipped, counts
    return GroundingConfig.model_validate(out), skipped, counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "One-shot migration: move ui.grounding / ui.campaign_state / "
            "ui.distill / ui.party / ui.planning out of ui_state.yaml into "
            "the dedicated <config>/grounding.yaml."
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
        help="Overwrite an existing grounding.yaml",
    )
    args = parser.parse_args(argv)

    campaign_dir = Path(args.campaign_dir).expanduser().resolve()
    config_dir_path = campaign_dir / args.config_dir
    ui_state_path = config_dir_path / UI_STATE_NAME
    dest_path = config_dir_path / GROUNDING_CONFIG_FILENAME

    raw = _load_raw_ui_state(ui_state_path)
    cfg, skipped, counts = build_grounding_config(raw)

    if cfg is None:
        print(f"nothing to migrate — no grounding data found in {ui_state_path}")
        print(
            "  (expected for most campaigns: ui.campaign_state and ui.distill "
            "were never written by the UI, and ui.party/ui.planning stored only "
            "2 fields each — see docs/config/grounding-isolation.md)"
        )
        if skipped:
            print(f"  unrecognised keys left in place: {', '.join(sorted(skipped))}")
        return 0

    if dest_path.exists() and not args.force:
        print(
            f"refusing to overwrite existing {dest_path} — pass --force to overwrite.",
            file=sys.stderr,
        )
        return 1

    save_grounding_config(dest_path, cfg)

    lines = [
        "migrated grounding config",
        f"  source:       {ui_state_path}",
        f"  destination:  {dest_path}",
        f"  summaries:    {cfg.summaries or '(none)'}",
    ]
    for section in SECTIONS:
        lines.append(f"  {section+':':<14}{counts.get(section, 0)} field(s)")
    print("\n".join(lines))
    if skipped:
        print(
            f"  SKIPPED (unrecognised, left in ui_state.yaml for review): "
            f"{', '.join(sorted(skipped))}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
