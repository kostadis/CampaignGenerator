"""Service for managing isolated planning configuration.

This service provides exclusive access to planning.yaml through a 
resource-oriented API, separating planning configuration from the 
general-purpose CampaignConfigService.
"""

from fastapi import HTTPException
from pathlib import Path
from typing import List
from .planning_config_shared import PlanningConfig, PlanningEntry, load_planning_config, save_planning_config


class PlanningConfigService:
    """Service for managing planning configuration with exclusive ownership of planning.yaml."""
    
    def __init__(self, campaign_dir: str):
        self.campaign_dir = Path(campaign_dir)
        self.planning_path = self.campaign_dir / "planning.yaml"
    
    def _load(self) -> PlanningConfig:
        """Load planning configuration, returning empty config if file doesn't exist."""
        if not self.planning_path.exists():
            return PlanningConfig(npcs=[], factions=[])
        try:
            return load_planning_config(self.planning_path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to load planning config: {str(e)}")
    
    def _save(self, config: PlanningConfig) -> None:
        """Save planning configuration."""
        try:
            save_planning_config(self.planning_path, config)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to save planning config: {str(e)}")
    
    # ============================================================================
    # NPC Operations
    # ============================================================================
    
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