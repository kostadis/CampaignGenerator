# Planning Configuration Isolation Design

## Overview
This document describes the design for isolating the planning configuration in CampaignGenerator, moving it from the shared configuration service to a dedicated planning service with its own API and data model.

## Current State
- Planning data is stored in `<config-dir>/planning.yaml` (hand-edited YAML)
- UI state for planning (`ui.planning`) is stored as a loose section in the shared `<config-dir>/ui_state.yaml`
- Both are managed through the generic `CampaignConfigService` mechanism
- HTTP endpoints: `GET/PUT /planning-yaml` (returns full planning blob)

## Problems with Current Approach
1. **Coupling**: Planning config shares persistence mechanism with all other UI sections
2. **Blast radius**: Changes to planning config risk corrupting other service configs
3. **Inefficiency**: Frontend must send/receive entire planning blob for any change
4. **Lack of ownership**: No clear service boundary for planning domain

## Proposed Solution
Create a dedicated `PlanningConfigService` that exclusively owns `planning.yaml` and provides a resource-oriented API for managing NPCs and factions.

### 1. Service Layer (`server/planning_config_service.py`)
```python
class PlanningConfigService:
        def __init__(self, campaign_dir: str, config_dir: str = "config"):
            self.campaign_dir = Path(campaign_dir)
            self.config_dir = config_dir
            self.planning_path = self.campaign_dir / self.config_dir / "planning.yaml"
    
    # NPC Operations
    def get_npcs(self) -> List[NPC]: ...
    def get_npc(self, name: str) -> NPC: ...
    def create_npc(self, npc: NPC) -> NPC: ...
    def update_npc(self, name: str, npc: NPC) -> NPC: ...
    def delete_npc(self, name: str) -> None: ...
    
    # Faction Operations (mirrored)
    def get_factions(self) -> List[Faction]: ...
    def get_faction(self, name: str) -> Faction: ...
    def create_faction(self, faction: Faction) -> Faction: ...
    def update_faction(self, name: str, faction: Faction) -> Faction: ...
    def delete_faction(self, name: str) -> None: ...
```

### 2. Shared Loading Logic (`server/planning_config_shared.py`)
Refactored from `pipelines/grounding/planning.py` to provide:
- `load_planning_config(path: Path) -> PlanningConfig`
- `save_planning_config(path: Path, config: PlanningConfig) -> None`
- Data models: `PlanningConfig`, `NPC`, `Faction`, `PlanningEntry`

### 3. New API Endpoints (`server/routers/planning_routes.py`)
```python
router = APIRouter(prefix="/api/planning", tags=["planning"])

# NPCs
@router.get("/npcs", response_model=List[NPC])
def list_npcs(...)

@router.post("/npcs", response_model=NPC, status_code=201)
def create_npc(...)

@router.get("/npcs/{name}", response_model=NPC)
def get_npc(...)

@router.put("/npcs/{name}", response_model=NPC)
def update_npc(...)

@router.delete("/npcs/{name}", status_code=204)
def delete_npc(...)

# Identical endpoints for factions under /factions/*
```

### 4. Data Model (JSON)
```json
{
  "name": "string (required)",
  "dossier": "string (optional, path to dossier file)",
  "arc_score": null | string | undefined
  // null = trackless=True (explicitly untracked)
  // undefined/absent = trackless=False, no track (key omitted in YAML)
  // string = path/to/tracking/file.md (tracked against file)
}
```

## Implementation Steps

### Phase 1: Service Creation
1. Create `server/planning_config_shared.py` with loading/saving logic and data models
2. Create `server/planning_config_service.py` implementing the service interface
3. Create `server/routers/planning_routes.py` with the new API endpoints
4. Update app startup to initialize and register `PlanningConfigService`

### Phase 2: Integration
1. Remove `/planning-yaml` GET/PUT endpoints from `config_routes.py`
2. Update `pipelines/grounding/planning.py` CLI to use the shared loading functions (maintain backward compatibility)
3. Add dependency injection for `PlanningConfigService` in route handlers

### Phase 3: Documentation
1. Update `values.md`: Remove planning YAML read/write mappings
2. Update `subsystems.md`: Reflect planning service as isolated subsystem
3. Update `service-cut.md`: Show planning service under Services section
4. Add new API documentation to planning isolation doc

## Benefits
1. **True isolation**: Planning service exclusively owns `planning.yaml`
2. **Resource-oriented API**: Standard REST semantics (GET, POST, PUT, DELETE)
3. **Better error handling**: Proper HTTP status codes (404, 409, 400)
4. **Frontend efficiency**: Partial updates possible (update single NPC)
5. **Maintainability**: Clear separation between planning domain and generic config
6. **CLI compatibility**: Existing `pipelines/grounding/planning.py` continues to work via shared logic

## Migration Considerations
- **Frontend impact**: Requires updating planning UI to use new endpoints
- **Backwards compatibility**: Old `/planning-yaml` endpoints removed (breaking change acceptable per user)
- **Testing**: All planning-related tests must migrate to use new service/API
- **Data migration**: None required - same `planning.yaml` format used

## Dependency Impact
From code-graph analysis:
- `pipelines/grounding/planning.py`: Only called by its own `main()` and tests - safe to refactor
- `config_routes.py`: Only callers are tests - safe to replace endpoints
- No direct dependencies on old planning-yaml endpoints in core application flow
- Tests will need updating (expected for major revision)

## Open Questions
1. Should we maintain read-only access to planning data via the old endpoint during transition?
   - No, user indicated breaking change is acceptable for major revision
2. Should the service support batch operations?
   - Start with individual resource operations; batch can be added later if needed
3. How to handle validation errors?
   - Return 400 with descriptive message for invalid input
   - Return 409 for conflicts (e.g., duplicate NPC name)
