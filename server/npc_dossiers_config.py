"""NPC dossiers configuration service (spec 032, T048): owns ``<config>/npc_dossiers.yaml``.

The strict model, its loader and its saver are in ``pipelines/summary_native/npc_config.py``
so the CLI reads the same definition (the engine layer may not import ``server``); this
module is the web side: the service, mirroring ``party_config_service.py`` and
``GroundingConfigService``.

Model and backend: ``draft.backend`` / ``draft.model`` are the defaults for ``npc-draft``; the
optional top-level ``selection`` is this service's override (feature 003) and beats them. A
request value beats both.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from campaignlib.selection import ModelSelection
from pipelines.summary_native.npc_config import (  # noqa: F401  (re-exported for the router and tests)
    NPC_DOSSIERS_CONFIG_FILENAME,
    NpcDossiersConfig,
    NpcDraftBlock,
    load_npc_dossiers_config,
    save_npc_dossiers_config,
)


class NpcDossiersConfigService:
    """Owns ``<config>/npc_dossiers.yaml``.

    Takes the config directory rather than a platform, like ``GroundingConfigService``:
    the one thing it needs from the platform is where the file lives.
    """

    def __init__(self, config_path_base: Path | str) -> None:
        self.config_path_base = Path(config_path_base)

    @property
    def path(self) -> Path:
        return self.config_path_base / NPC_DOSSIERS_CONFIG_FILENAME

    def resolved(self) -> NpcDossiersConfig:
        try:
            return load_npc_dossiers_config(self.path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Failed to load NPC dossiers config: {exc}") from exc

    get_config = resolved

    def put_config(self, cfg: NpcDossiersConfig) -> NpcDossiersConfig:
        try:
            save_npc_dossiers_config(self.path, cfg)
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"Failed to save NPC dossiers config: {exc}") from exc
        return cfg

    # ── Model/backend selection (feature 003) ──────────────────────────
    def get_selection(self) -> ModelSelection:
        """This service's override: the top-level ``selection`` when set, else the
        ``draft`` block's backend/model pair."""
        cfg = self.resolved()
        return cfg.selection if not cfg.selection.is_empty() else cfg.draft.selection()

    def set_selection(self, selection: ModelSelection) -> ModelSelection:
        cfg = self.resolved()
        self.put_config(cfg.model_copy(update={"selection": selection}))
        return selection
