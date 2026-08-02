"""Service owning the State Projection workflow's configuration slice.

Phase 6 of ``specs/006-state-projection-service`` (User Story 4). Storage is
a dedicated ``<config>/projections.yaml`` this service owns exclusively — a
projections write cannot corrupt ``ui_state.yaml``, ``platform.yaml``,
``grounding.yaml`` or ``ensemble.yaml``.

Shaped after ``GroundingConfigService`` (``server/grounding_config_service.py``),
field for field: same ``_deep_merge`` semantics, same ``resolved()`` seam, same
"a directory, not a whole platform" constructor for the same reason — the
projections router is cwd-rooted like grounding's and ensemble's, so demanding
a live ``PlatformConfigService`` would make read-only routes 503 in contexts
that never needed one. In a booted server the two paths are identical
(``main`` chdirs to ``campaign_dir``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from campaignlib.projection_config import (
    PROJECTION_CONFIG_FILENAME,
    ProjectionConfig,
    load_projection_config,
    save_projection_config,
)
from campaignlib.selection import ModelSelection


def _deep_merge(base: dict[str, Any], partial: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``partial`` into ``base``; returns a new dict.

    Same semantics as ``GroundingConfigService``'s copy — a nested partial
    like ``{"stores": {"events": "docs/alt/events.jsonl"}}`` updates one
    field rather than replacing the whole ``stores`` group. Lists are
    replaced wholesale, not concatenated — nothing in ``ProjectionConfig``
    is a list today, but the rule is stated here once so it does not need
    rediscovering the day one is added.
    """
    out = dict(base)
    for key, value in partial.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class ProjectionConfigService:
    """Owns ``<config>/projections.yaml``."""

    def __init__(self, config_path_base: Path | str) -> None:
        self.config_path_base = Path(config_path_base)

    @property
    def projection_config_path(self) -> Path:
        return self.config_path_base / PROJECTION_CONFIG_FILENAME

    # ── Read ──────────────────────────────────────────────────────────

    def get_config(self) -> ProjectionConfig:
        """The stored config. Paths stay relative to the campaign dir, which
        is what the three State Projection CLIs expect (each one runs with
        ``cwd == campaign_dir``, mirroring every other console script)."""
        try:
            return load_projection_config(self.projection_config_path)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid projections config: {exc}"
            ) from exc

    # ── Model/backend selection (feature 003) ──────────────────────────

    def get_selection(self) -> ModelSelection:
        return self.get_config().selection

    def set_selection(self, selection: ModelSelection) -> ModelSelection:
        """Persist this service's own override. An empty selection means
        "inherit" — that is how clearing works (FR-013)."""
        self.update_config({"selection": selection.model_dump()})
        return selection

    def resolved(self) -> ProjectionConfig:
        """What the router builds commands from.

        Currently identical to :meth:`get_config`; a distinct name so a
        later change (layering in platform defaults, say) needn't touch
        every call site — mirrors ``GroundingConfigService.resolved``.
        Returns the strict model rather than a dict so a typo in a route is
        an ``AttributeError`` at test time, not a silently-missing flag.
        """
        return self.get_config()

    # ── Write ─────────────────────────────────────────────────────────

    def update_config(self, partial: dict[str, Any]) -> ProjectionConfig:
        """Merge a grouped, possibly-nested ``partial`` and persist it.

        Raises ``HTTPException(400)`` if the merged result fails validation —
        which, because the schema is ``extra="forbid"``, includes an unknown
        key, and (via ``ProjectionOutput``'s field validator) an
        ``output.draft`` missing the ``{doc}`` placeholder.
        """
        current = self.get_config().model_dump(mode="json")
        merged = _deep_merge(current, partial)
        try:
            validated = ProjectionConfig.model_validate(merged)
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid projections config: {exc}"
            ) from exc
        save_projection_config(self.projection_config_path, validated)
        return validated
