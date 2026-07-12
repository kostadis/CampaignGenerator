# Config Subsystems — Ensemble Workflow & Grounding Docs

Two configuration subsystems beyond the core config service: the ensemble grounding-doc
pipeline and the party / campaign_state / world_state grounding-doc system. Both mix persisted
`ui_state` sections, hand-authored YAML, and generated run artifacts.

## Ensemble workflow (extract → bundle → synthesize → review)

Router `server/routers/ensemble.py` shells out to CLI scripts; disk is truth, CLI is the engine.
Only 4 docs are promotable: `world_state`, `campaign_state`, `party`, `planning`.

```mermaid
flowchart LR
  UIE["ui.ensemble<br/>chapters, known_names, aliases, backends"] --> EX[ensemble_extract.py]
  EX -->|manifest.json + per-pass facts| WD[(run workdir)]
  WD --> MG["ensemble_merge.py<br/>merge.yaml"]
  MG --> SY[synthesise_*]
  SY -->|docs/*_draft.md| DR[(drafts)]
  DR -->|promote| LIVE["docs live: world_state, campaign_state, party, planning"]
```

| Config source | Kind | Read by | Written by |
|---|---|---|---|
| `ui.ensemble` (EnsembleSection) | ui_state.yaml (persisted) | ensemble router (`chapters_glob`, `chapters_selected[]`, extract/synthesize `BackendProfile`, `known_names[]`, `aliases_path`, `campaign_dir`) | `PUT /section/ensemble` |
| merge-config YAML (`--config merge.yaml`) | hand-authored, per-run | `ensemble_merge.py` (method, similarity, threshold) | human; precedence CLI flag > `--config` > default |
| `manifest.json` (run workdir) | generated per run | `ensemble_merge.load_manifest` / `load_pass_outputs` | `ensemble_extract.py` |
| per-pass fact JSON (workdir) | generated | `ensemble_merge.load_pass_outputs` | `ensemble_extract.py` |
| aliases file (`aliases_path`) | hand-authored | alias-correction gate (bundle stage) | human |
| known_names sources | referenced files | bundle stage / alias gate | human (selected in `ui.ensemble`) |
| GROUNDING_DOCS live/draft pairs | `docs/*.md` + `docs/*_draft.md` | ensemble router promote/diff; synthesis writes draft | synthesize writes `*_draft.md`; promote copies draft → live |

Stage/model knobs:

| Knob | Type | Rule |
|---|---|---|
| extract stage | BackendProfile | any backend; OpenRouter via env seam |
| synthesize stage | BackendProfile | warns if model not in `SYNTHESIS_CAPABLE` |
| `chapters_selected` | explicit list | empty = nothing (no silent "all"); extraction refuses to run |

## Grounding docs (party / campaign_state / world_state / planning)

```mermaid
flowchart TB
  PY[party.yaml] --> PP[party.py] --> PMD[docs/party.md]
  PLY[planning.yaml] --> PLP[planning.py] --> PLMD[docs/planning.md]
  TRK[tracking.txt] --> CS[campaign_state.py] --> CSMD[docs/campaign_state.md]
  WS[world_state.md hand + ensemble] --> WSMD[docs/world_state.md]
  PMD & PLMD & CSMD & WSMD -->|referenced by config.yaml documents[]| PREP[prep.py / mcp_server.py]
```

| File | Shape | Read by | Written by |
|---|---|---|---|
| `party.yaml` (`config/party.yaml`) | `characters[]`: name, sheet, backstory?, dossier?, arc_score (3-state), trackless | `config_routes.get_party_yaml` (UI); `party.py --party-config` | `config_routes.put_party_yaml` (UI); hand |
| `planning.yaml` | `npcs[]` + `factions[]`: name, dossier, arc_score (3-state), trackless | `PlanningConfigService` (UI); `planning.py` | `PlanningConfigService` (UI); hand |
| tracking file (`--track-file tracking.txt`) | one item per line; `#` comments ignored | `campaign_state.py` | hand |
| `world_state.md` | lore / history / canon | prep, mcp_server, ensemble (extract input) | hand (+ ensemble synthesis draft); referenced by `config.yaml` `documents[]` |
| `campaign_state.md` | completed vs currently-true state | prep, mcp_server | `campaign_state.py` (extract+synthesize from summaries; `.candidate` to avoid clobber) |
| `party.md` | party roster + arc scores | prep, mcp_server | `party.py` (from party.yaml + sheets + summaries; `.candidate` if exists) |
| `planning.md` | forward-looking dossiers / NPC notes | prep, mcp_server | `planning.py`; hand-edited |

### arc_score 3-state (party.yaml + planning.yaml)

| State | On disk | Meaning |
|---|---|---|
| absent | `arc_score` key omitted | trackless=False, no track |
| null | `arc_score: null` | trackless=True (first-class trackless PC/NPC) |
| path | `arc_score: docs/tracking/x.md` | tracked against that file |

## How they connect

`ui.ensemble` selects inputs (chapters, known_names, aliases, per-stage backends); the ensemble
CLI produces `manifest.json` + per-pass facts in a run workdir, merges them (merge-config YAML),
synthesizes `*_draft.md`, and promotes drafts into the four live grounding docs. `party.yaml` and
`planning.yaml` declare rosters/dossiers with 3-state arc tracking; `party.py` / `planning.py` /
`campaign_state.py` generate the matching `.md` docs (non-clobbering `.candidate` on conflict),
which `config.yaml` `documents[]` then references for prep and the MCP server.
