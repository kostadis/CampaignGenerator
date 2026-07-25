"""Service owning the grounding-doc workflow's configuration slice.

Phase 7 of ``docs/config/grounding-isolation.md``. Storage is a dedicated
``<config>/grounding.yaml`` this service owns exclusively — a grounding write
cannot corrupt ``ui_state.yaml``, ``platform.yaml`` or ``ensemble.yaml``.

Shaped after ``EnsembleConfigService``, and for the same reason it takes a
directory rather than a ``PlatformConfigService``: this service needs exactly
one thing from the platform — where ``grounding.yaml`` lives. The grounding
router is cwd-rooted like the ensemble one, so demanding a whole platform
would make it 503 in contexts that never needed one. In a booted server the
two are the same path anyway (``main`` chdirs to ``campaign_dir``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from server.grounding_config_shared import (
    GROUNDING_CONFIG_FILENAME,
    GroundingConfig,
    load_grounding_config,
    save_grounding_config,
)


def _deep_merge(base: dict[str, Any], partial: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``partial`` into ``base``; returns a new dict.

    Same semantics as ``EnsembleConfigService``'s copy — a nested partial like
    ``{"party": {"mode": "flat"}}`` updates one field rather than replacing the
    whole ``party`` group. Lists are replaced wholesale, not concatenated:
    ``context``, ``track_files`` and the flat-mode file lists are selections,
    and appending on every save would make removal impossible.
    """
    out = dict(base)
    for key, value in partial.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class GroundingConfigService:
    """Owns ``<config>/grounding.yaml``."""

    def __init__(self, config_path_base: Path | str) -> None:
        self.config_path_base = Path(config_path_base)

    @property
    def grounding_config_path(self) -> Path:
        return self.config_path_base / GROUNDING_CONFIG_FILENAME

    # ── Read ──────────────────────────────────────────────────────────

    def get_config(self) -> GroundingConfig:
        """The stored config. Paths stay relative to the campaign dir, which
        is what the CLI engines expect (every grounding console script runs
        with ``cwd == campaign_dir``)."""
        try:
            return load_grounding_config(self.grounding_config_path)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid grounding config: {exc}"
            ) from exc

    def resolved(self) -> GroundingConfig:
        """What the router builds commands from.

        Currently identical to :meth:`get_config`; a distinct name because
        Phase 8's routes depend on *this* seam, so a later change (layering in
        platform defaults, say) needn't touch every call site. Returns the
        strict model rather than a dict so a typo in a route is an
        ``AttributeError`` at test time, not a silently-missing flag.
        """
        return self.get_config()

    # ── Write ─────────────────────────────────────────────────────────

    def update_config(self, partial: dict[str, Any]) -> GroundingConfig:
        """Merge a grouped, possibly-nested ``partial`` and persist it.

        Raises ``HTTPException(400)`` if the merged result fails validation —
        which, because the schema is ``extra="forbid"``, includes an unknown
        key. That is the point: the keys the Vue pages used to read but never
        write would now be rejected at the boundary rather than silently
        producing a value nothing persists.
        """
        current = self.get_config().model_dump(mode="json")
        merged = _deep_merge(current, partial)
        try:
            validated = GroundingConfig.model_validate(merged)
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid grounding config: {exc}"
            ) from exc
        save_grounding_config(self.grounding_config_path, validated)
        return validated
