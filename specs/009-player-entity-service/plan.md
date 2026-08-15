# Implementation Plan: Player Entity & Config Service

**Branch**: `009-player-entity-service` | **Date**: 2026-08-15 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/009-player-entity-service/spec.md`

## Summary

Model the **human at the table** as a first-class entity for the first time, in one
per-campaign document owned by one service, and make every consumer of player
information read it instead of reconstructing the person from four other files.

`docs/design/PlayerIdentity.md` (CG#314) measured the present state: five join keys
across fourteen stores, and a clean split — **everything that fails loudly is a path
or an exact-match refusal; everything that fails silently is a name approximately
matched**. This feature acts on that split rather than merely adding a store. Three
GM rulings during `/speckit-specify` set the scope, and five more during
`/speckit-clarify` closed the remaining ambiguity.

The technical approach follows from the finding, not from taste:

1. **A new configuration service**, `players.yaml`, built to the pattern the repo has
   already cut five times (strict pydantic models in `campaignlib`, a service and
   router in `server/`, a one-shot migration, a lenient-save/reporting-read contract).
2. **Two more declared paths per character** — `voice` and `examples` join
   `PATH_FIELDS` in `party.yaml`. This converts the last two silent joins into loud
   ones by reusing `missing_files`, which already exists.
3. **Deletion, not supplementation.** The first-name-prefix rule
   (`routes_to`, `_resolve_voice_key`) and both duplicate rosters
   (`party.yaml`'s `player:`, `session_doc.yaml`'s `roster.*`) are removed. A guard
   test asserts they are gone, which is what makes SC-006 countable.

Phase 0 measurement found a **second live instance of the defect class**, previously
unknown: stormgiants' `thistl.md` routes to nobody, reaches all four narrators, and
`Thistle` gets no examples — silent, in a second campaign (research M3).

## Technical Context

**Language/Version**: Python 3.11+ (backend, CLIs); TypeScript + Vue 3 (frontend)

**Primary Dependencies**: pydantic v2 (`extra="forbid"`), PyYAML, FastAPI, Vue 3 +
Pinia + Vue Router. No new dependency.

**Storage**: YAML files on disk. New: `<campaign>/config/players.yaml`. Modified:
`<campaign>/config/party.yaml` (two per-character path fields, one root list; loses
`player:`), `<campaign>/config/session_doc.yaml` (loses the `roster` group).

**Testing**: pytest. Five new suites, seven changed, one guard test.
See research D15.

**Target Platform**: Linux (WSL2), single-operator local web app + CLIs.

**Project Type**: Web application — FastAPI backend shelling out to CLI engines,
Vue 3 frontend. Constitution VI: the CLI is the engine, the UI is a face.

**Performance Goals**: None. Six campaigns, ≤4 players each, documents under 2 KB
(research D18). Stated so the plan does not invent a requirement.

**Constraints**:
- `tests/test_layering.py` — `campaignlib`, `pipelines`, `session_doc`,
  `entity_registry`, `provenance` may not import `server`. This drives D1, D6 and D10.
- No LLM call is added anywhere in this feature.
- Migrate-and-delete: no dual-location probes, no legacy shims (spec FR-036).
- The editable install shadows a worktree (research D16) — a green worktree suite is
  not by itself evidence.

**Scale/Scope**: 6 campaigns, ~24 people, 5 pipelines touched, ~10 backend files,
1 new frontend page, 2 CLIs (1 new console script, 1 new one-shot module).

## Constitution Check

*GATE: evaluated before Phase 0 and re-evaluated after Phase 1. Version 1.2.0.*

| # | Principle | Verdict | Evidence |
|---|---|---|---|
| I | Disk is Truth, the Model is a Draft | **PASS** | `players.yaml` is hand-authored YAML on disk. No database, no cache, no index. Nothing generated feeds back in — FR-023 forbids reading player identity out of a sheet or a generated document. |
| II | The Human Checkpoint is Non-Negotiable | **PASS** | No LLM call is added. Adoption **reports** conflicts and refuses to resolve them (FR-032) — that is the checkpoint. Replacing a prefix match with a declaration *moves a decision from inference to the human*, which is the principle applied to configuration rather than to a prompt. |
| III | Retrieval and Render are Separated | **PASS (N/A)** | No retrieval call and no render call is added or moved. `tests/test_retrieve_render_isolation.py` is unaffected. |
| IV | Verbatim is Sacred | **PASS, and strengthened** | Speaker attribution is precision data (#223). FR-021a rules that the game-master label wins precisely so NPC and narration speech is never attributed to a player character. FR-019 forbids similarity-based identity assertion. Nothing in this feature edits transcript text. |
| V | One Seam per Boundary | **PASS** | One service owns `players.yaml` exclusively (FR-007). One function builds the speaker map (research D9). One CLI seam, `--players-config`, replaces per-attribute flags (D8). No new external dependency, so no new boundary. |
| VI | CLI is the Engine, UI is a Face | **PASS** | The Players page calls routes that call the service; nothing is reimplemented in the router. `players check` is a console script the UI does not need. `scene_editor.py` keeps building argv and shelling out. |
| VII | Extract Once, Synthesize Deliberately | **PASS (N/A)** | No extraction or synthesis pass is touched. |
| VIII | State is Discoverable | **PASS, and improved** | An un-adopted campaign refuses and names what is missing (SC-008). `players check` answers "is this campaign coherent" from disk. The orphan report (FR-030b) makes a file nothing declares *visible* rather than silently inert — three of the six campaigns have one today and none of them knows it. |
| IX | The UI Mechanizes; Claude Converses | **PASS** | FR-018: everything the page does is doable at the CLI and by editing the file, and the file is the interchange. The page holds no state that is not on disk. No judgment is absorbed — the page edits a table; the rulings (a name conflict, which character owns a file) stay with the GM. |
| X | Selection is Explicit; No Silent "All" | **PASS, and extended** | No batch operation is added, so the concrete clause does not bind. The *principle* does: FR-030a removes the fall-through by which an undeclared example file silently became "shared with everyone". Today that is 51,073 characters in toee and 7,285 in stormgiants, reaching every narrator because nobody chose it. Explicit `shared_examples` is Principle X applied to prompt inputs. |

**Gate result: PASS, no deviations to record.** The Complexity Tracking table is
therefore omitted.

**Re-evaluated after Phase 1 design** (data model, contracts, quickstart written):
still PASS. The design added no LLM call, no database, no second location for any
fact, and no capability the CLI lacks. The one judgment call it makes on the GM's
behalf — that adoption never picks between two conflicting values — is a refusal,
which is the safe direction under Principle II.

## Project Structure

### Documentation (this feature)

```text
specs/009-player-entity-service/
├── spec.md                     # /speckit-specify + /speckit-clarify output
├── plan.md                     # This file
├── research.md                 # Phase 0 — M1–M5 measurements, D1–D19 decisions
├── data-model.md               # Phase 1 — entities, fields, validation, transitions
├── quickstart.md               # Phase 1 — runnable end-to-end validation
├── checklists/
│   └── requirements.md         # spec quality checklist (16/16)
├── contracts/
│   ├── players.yaml.md         # the new document's shape
│   ├── party.yaml.md           # the changed document's shape
│   ├── http.md                 # /api/players/* routes
│   ├── cli.md                  # --players-config seam, players check, adoption
│   └── measure.py              # the Phase 0 measurement script, kept runnable
└── tasks.md                    # /speckit-tasks output — NOT created here
```

### Source Code (repository root)

```text
campaignlib/
├── players_config.py          # NEW — PlayersConfig, Player, load/save, speaker_map
├── party_config.py            # CHANGED — +voice/+examples in PATH_FIELDS,
│                              #           +shared_examples root key, −player
├── npc.py                     # CHANGED — player_map_from_config reads the entity;
│                              #           normalize_vtt_speakers loses gm_player
└── party.py                   # unchanged (load_pc_names — see research D14/M2)

server/
├── players_config_service.py  # NEW — owns <config>/players.yaml
├── migrate_players_config.py  # NEW — one-shot adoption; strips roster.* and player:
├── session_editor_config_shared.py  # CHANGED — the Roster group is deleted
├── routers/
│   ├── players_routes.py      # NEW — /api/players/*
│   ├── party_routes.py        # CHANGED — voice/examples fields flow through
│   └── scene_editor.py        # CHANGED — argv from the roster + players service,
│                              #           _load_examples/_load_voice_dir pre-flights
└── main.py                    # CHANGED — one include_router line

session_doc/
├── voice.py                   # CHANGED — prefix rule deleted (research D7)
├── examples.py                # CHANGED — routes_to + detector deleted
├── roster.py                  # CHANGED — player from the entity, not the sheet
├── sd_narrate.py              # CHANGED — --players-config; --characters deleted
├── scene_extract.py           # CHANGED — --players-config; --gm-player deleted
├── enhance_summary.py         # CHANGED — same
└── sd_agent.py                # CHANGED — --gm-player forwarding deleted

pipelines/
├── workspace/players.py       # NEW — `players check` console script
└── content_ingest/dnd_sheet.py # CHANGED — player stamp from the entity

frontend/src/
├── router.ts                  # CHANGED — /setup/players
├── views/setup/Players.vue    # NEW — the page
├── components/shared/
│   ├── PlayersEditor.vue      # NEW — the table
│   └── PartyConfigEditor.vue  # CHANGED — player column out, voice/examples in,
│                              #           cross-link to the Players page
└── views/SetupTools.vue       # CHANGED — nav entry

pyproject.toml                 # CHANGED — one [project.scripts] entry: players

tests/                         # 5 new suites, 7 changed, 1 guard (research D15)
docs/config/players-isolation.md  # NEW — the service's own isolation doc
```

**Structure Decision**: the existing four-layer split is kept exactly as it is —
`campaignlib` (models and pure logic), `pipelines` + `session_doc` (CLI engines),
`server` (thin routers over services), `frontend` (a face). The layering test forces
the placement of every new file: anything a CLI reads goes in `campaignlib`, anything
that must read `session_doc.yaml` goes in `server`. No new top-level package is
introduced, so `ENGINE_PACKAGES` in `tests/test_layering.py` is unchanged.

## Risks and how the plan answers them

| Risk | Answer |
|---|---|
| Deleting the prefix rule breaks Phandalin, whose four voice files resolve **only** through step (c) (research M4) | Adoption proposes every declaration before the rule is deleted, and the two land in build order 2 then 4 (research D17). The quickstart verifies Phandalin explicitly. |
| Four campaigns have no `player:` to harvest, so adoption looks broken (M1) | The migration says so in its output, as `migrate_grounding_config` does. |
| obelisk's `party.yaml` is not a roster (M2) | Adoption refuses that campaign by name (D12). It is a GM ruling, not a merge rule. |
| No shim means a half-migrated campaign fails | It fails **loudly and by name** — the designed behaviour (FR-024, SC-008). Build order keeps it from being a state anyone ships through. |
| A green worktree test run is not evidence (#286, D16) | The quickstart runs the real loaders against real campaign directories, not only pytest. |
| Four NPC voice files become orphans (M4) | Reported by `players check`, not rescued (D11) — no narrator reaches them today. |
