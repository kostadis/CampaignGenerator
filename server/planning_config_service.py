"""Service for managing isolated planning configuration.

This service provides exclusive access to planning.yaml through a
resource-oriented API, separating planning configuration from the
general-purpose platform config. Composes ``PlatformConfigService``
(``docs/config/platform-isolation.md``) for ``config_path_base`` rather than
resolving campaign_dir/config_dir itself — the same shape
``SessionEditorConfigService`` uses.
"""

from fastapi import HTTPException
from typing import List

from campaignlib.selection import ModelSelection
from campaignlib.planning_config import (
    PLANNING_CONFIG_FILENAME,
    PlanningConfig,
    PlanningEntry,
    load_planning_config,
    save_planning_config,
)


class PlanningConfigService:
    """Service for managing planning configuration with exclusive ownership of planning.yaml."""

    def __init__(self, platform) -> None:
        self.platform = platform
        self.planning_path = self.platform.config_path_base / PLANNING_CONFIG_FILENAME

    def _load(self) -> PlanningConfig:
        """Load planning configuration; a missing or empty file is an empty config.

        The emptiness special-case that used to live here — a raw
        ``yaml.safe_load`` pre-check, because the CLI loader treated an empty
        file as a hard error — is gone: ``campaignlib.planning_config``'s
        loader returns an empty config for a missing/empty document, and the
        CLI keeps its strict behavior in its own wrapper where it belongs
        (Phase 1 of ``docs/config/grounding-isolation.md``).

        Entries come back with paths **as authored**, not resolved. The old
        loader resolved to absolute paths on read and ``save_planning_config``
        wrote those absolutes straight back, so every edit through this service
        rewrote the GM's relative references as machine-specific ones.
        """
        try:
            return load_planning_config(self.planning_path)
        except ValueError as e:
            raise HTTPException(
                status_code=400, detail=f"Failed to load planning config: {e}"
            ) from e

    def _save(self, config: PlanningConfig) -> None:
        """Save planning configuration (atomic — see ``save_planning_config``)."""
        try:
            save_planning_config(self.planning_path, config)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to save planning config: {str(e)}")
    
    # ============================================================================
    # NPC Operations
    # ============================================================================
    
    # ── Model/backend selection (feature 003) ──────────────────────────
    # This service's own override. Empty means "defer to the platform".
    # Kept as a pair of small accessors rather than exposing the whole
    # document, so the selection routes never have to touch unrelated keys.

    def get_selection(self) -> ModelSelection:
        return self._load().selection

    def set_selection(self, selection: ModelSelection) -> ModelSelection:
        """Persist this service's override. An empty selection is a legitimate
        value meaning "inherit" — that is how clearing works (FR-013)."""
        cfg = self._load()
        self._save(cfg.model_copy(update={"selection": selection}))
        return selection

    def get_npcs(self) -> List[PlanningEntry]:
        """Get all NPCs."""
        return self._load().npcs
    
    def get_npc(self, name: str) -> PlanningEntry:
        """Get a specific NPC by name."""
        config = self._load()
        for npc in config.npcs:
            if npc.name == name:
                return npc
        raise HTTPException(status_code=404, detail=f"NPC '{name}' not found")
    
    def create_npc(self, npc: PlanningEntry) -> PlanningEntry:
        """Create a new NPC."""
        config = self._load()
        if any(n.name == npc.name for n in config.npcs):
            raise HTTPException(status_code=409, detail=f"NPC '{npc.name}' already exists")
        config.npcs.append(npc)
        self._save(config)
        return npc
    
    def update_npc(self, name: str, npc: PlanningEntry) -> PlanningEntry:
        """Update an existing NPC."""
        if name != npc.name:
            raise HTTPException(status_code=400, detail="NPC name mismatch between URL and body")
        config = self._load()
        for i, n in enumerate(config.npcs):
            if n.name == name:
                config.npcs[i] = npc
                self._save(config)
                return npc
        raise HTTPException(status_code=404, detail=f"NPC '{name}' not found")
    
    def delete_npc(self, name: str) -> None:
        """Delete an NPC by name."""
        config = self._load()
        original_count = len(config.npcs)
        config.npcs = [n for n in config.npcs if n.name != name]
        if len(config.npcs) == original_count:
            raise HTTPException(status_code=404, detail=f"NPC '{name}' not found")
        self._save(config)
    
    # ============================================================================
    # Faction Operations (mirrored)
    # ============================================================================
    
    def get_factions(self) -> List[PlanningEntry]:
        """Get all factions."""
        return self._load().factions
    
    def get_faction(self, name: str) -> PlanningEntry:
        """Get a specific faction by name."""
        config = self._load()
        for faction in config.factions:
            if faction.name == name:
                return faction
        raise HTTPException(status_code=404, detail=f"Faction '{name}' not found")
    
    def create_faction(self, faction: PlanningEntry) -> PlanningEntry:
        """Create a new faction."""
        config = self._load()
        if any(f.name == faction.name for f in config.factions):
            raise HTTPException(status_code=409, detail=f"Faction '{faction.name}' already exists")
        config.factions.append(faction)
        self._save(config)
        return faction
    
    def update_faction(self, name: str, faction: PlanningEntry) -> PlanningEntry:
        """Update an existing faction."""
        if name != faction.name:
            raise HTTPException(status_code=400, detail="Faction name mismatch between URL and body")
        config = self._load()
        for i, f in enumerate(config.factions):
            if f.name == name:
                config.factions[i] = faction
                self._save(config)
                return faction
        raise HTTPException(status_code=404, detail=f"Faction '{name}' not found")
    
    def delete_faction(self, name: str) -> None:
        """Delete a faction by name."""
        config = self._load()
        original_count = len(config.factions)
        config.factions = [f for f in config.factions if f.name != name]
        if len(config.factions) == original_count:
            raise HTTPException(status_code=404, detail=f"Faction '{name}' not found")
        self._save(config)