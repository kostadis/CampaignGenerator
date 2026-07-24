"""Service owning the ensemble workflow's configuration slice.

Phase 2 of ``docs/config/ensemble-isolation.md``: storage is a dedicated
``<config>/ensemble.yaml`` this service owns exclusively — ``ui_state.yaml``
is never touched by an ensemble write, and an ensemble write cannot corrupt
``platform.yaml``. Composes :class:`~server.platform_config_service.
PlatformConfigService` for path resolution and platform-owned reads rather
than re-implementing them, the same ownership boundary
``SessionEditorConfigService`` and ``PlanningConfigService`` use.

The distinguishing problem this service solves, relative to its two siblings:
the ensemble *router* never read ``ui.ensemble`` at all. Its defaults were
literals in route signatures, duplicated in ``config_models.EnsembleSection``
and again in TypeScript. :meth:`resolved` is the single source Phase 3 points
all three at.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from server.ensemble_config_shared import (
    ENSEMBLE_CONFIG_FILENAME,
    EnsembleConfig,
    load_ensemble_config,
    save_ensemble_config,
)

if TYPE_CHECKING:
    from server.platform_config_service import PlatformConfigService


def _deep_merge(base: dict[str, Any], partial: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``partial`` into ``base``; returns a new dict.

    Same semantics as ``SessionEditorConfigService``'s copy — a nested partial
    like ``{"tuning": {"chapter_parallel": 6}}`` updates one field rather than
    replacing the whole ``tuning`` group. Lists are replaced wholesale, not
    concatenated: ``chapters_selected`` and ``known_names`` are selections, and
    appending to them on every save would make deselection impossible.
    """
    out = dict(base)
    for key, value in partial.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class EnsembleConfigService:
    """Owns the ensemble workflow's configuration slice.

    Storage is a dedicated ``<config>/ensemble.yaml`` (see
    :attr:`ensemble_config_path`) — a bad write here cannot corrupt
    ``ui_state.yaml`` or ``platform.yaml``.
    """

    def __init__(self, platform: "PlatformConfigService") -> None:
        self.platform = platform

    @property
    def ensemble_config_path(self) -> Path:
        return self.platform.config_path_base / ENSEMBLE_CONFIG_FILENAME

    # ── Read ──────────────────────────────────────────────────────────

    def get_config(self) -> EnsembleConfig:
        """Return the stored config. Paths are NOT resolved — they stay
        relative to the campaign dir, which is what the CLI engine expects
        (every ensemble console script runs with cwd == campaign_dir; see
        ``server/subprocess_runner.py``).
        """
        try:
            return load_ensemble_config(self.ensemble_config_path)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid ensemble config: {exc}"
            ) from exc

    def resolved(self) -> EnsembleConfig:
        """The config the router should build commands from.

        Currently identical to :meth:`get_config`; it exists as a distinct
        name because Phase 3 makes the routes depend on *this* method, and
        keeping the seam separate means a later change (layering in platform
        defaults, say) doesn't have to touch every call site. Deliberately
        returns the same strict model rather than a dict, so a typo in a route
        is an ``AttributeError`` at import-adjacent test time rather than a
        silently-missing command flag.
        """
        return self.get_config()

    # ── Write ─────────────────────────────────────────────────────────

    def update_config(self, partial: dict[str, Any]) -> EnsembleConfig:
        """Merge a grouped, possibly-nested ``partial`` into the stored config
        and persist it to ``ensemble.yaml``.

        ``partial`` may be any subset of the grouped shape, e.g.
        ``{"tuning": {"chapter_parallel": 6}}`` or
        ``{"extract": {"endpoints": ["http://spark:8001/v1"]}}``. Raises
        ``HTTPException(400)`` if the merged result fails schema validation —
        which, because the schema is ``extra="forbid"``, includes an unknown
        key. That is the point: the six ``planning_*`` keys the frontend used
        to write into an ``extra="allow"`` section would now be rejected at
        the boundary instead of accumulating unread.
        """
        current = self.get_config().model_dump(mode="json")
        merged = _deep_merge(current, partial)
        try:
            validated = EnsembleConfig.model_validate(merged)
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid ensemble config: {exc}"
            ) from exc
        save_ensemble_config(self.ensemble_config_path, validated)
        return validated
