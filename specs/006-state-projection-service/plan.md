# Implementation Plan: State-Projection Rendering as its own service

**Branch**: `006-state-projection-service` *(spec directory; the working git branch is `feat/213-phase1-source-lineage` — no branch hook is registered)* | **Date**: 2026-08-01 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-state-projection-service/spec.md`

## Summary

Give the State Projection service (`event_spine`, `thread_registry`, `grounding_sections`) a strict
config document of its own, its own output namespace, and a UI covering section staleness plus
per-section rebuild — without touching the two other rendering services beyond the one cross-service
input that must follow its producer.

Technical approach: lift the pattern the config series has already run five times. A new strict
pydantic document `<config>/projections.yaml` modelled in `campaignlib/projection_config.py` (engine
layer, so both the CLIs and the eventual service can read it); the three CLIs resolve it through
`campaignlib.constants.config_path()` and take `None` argparse sentinels; outputs move to
`docs/projections/`; a `ProjectionConfigService` plus `/api/projections/*` routes that shell out via
`subprocess_runner`; one Vue page. Every location currently declared 2–4 times collapses to one
field, which is what closes the `events.jsonl` hash-vs-read divergence.

## Technical Context

**Language/Version**: Python ≥3.9 (`pyproject.toml`); TypeScript 5 / Vue 3 for the UI

**Primary Dependencies**: pydantic v2 (strict models), PyYAML, FastAPI + uvicorn (routes), Vue 3 +
Pinia + Vite (page). No new runtime dependency is introduced by this feature.

**Storage**: Files on disk — YAML config under `<campaign>/config/`, campaign data and generated
documents under `<campaign>/docs/`, JSONL for the event spine. No database.

**Testing**: pytest (`python -m pytest tests/`); `vue-tsc` + `vite build` for the frontend

**Target Platform**: Linux (WSL2), single operator, localhost server

**Project Type**: Web application over a CLI engine — FastAPI backend + Vue frontend, where the
backend never reimplements logic and shells out to installed console scripts

**Performance Goals**: Not throughput-bound. The meaningful targets are behavioural: a build whose
inputs are unchanged re-renders nothing (SC-004), and a build without an explicit backend spends zero
tokens (FR-019).

**Constraints**: One config location, no probes (`test_config_location.py`) · engine may not import
the server (`test_layering.py`) · one strict `extra="forbid"` document per service · no cross-service
config reads · no default that means "everything" (Constitution X) · content-derived freshness, never
mtime (#137)

**Scale/Scope**: 3 campaigns, ≤62 chapters, 12 sections across 3 documents, 1 operator. Three CLIs,
one new config module, one service, ~4 routes, one page.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Tested by name against `.specify/memory/constitution.md` v1.2.0.

| # | Principle | Verdict | How this design satisfies it |
|---|---|---|---|
| I | Disk is Truth, the Model is a Draft | **PASS** | Stores stay in `docs/` as truth; only pointers become config (FR-015). Every rendered document still lands as a draft the GM promotes. |
| II | The Human Checkpoint is Non-Negotiable | **PASS** | No checkpoint is removed or automated. FR-020/021 keep every proposal GM-ruled; the UI adds staleness and rebuild, which are mechanical. The only decision this feature removes from the human is "which file path" — a deployment fact, not scope, ordering or attribution. |
| III | Retrieval and Render are Separated | **PASS** | No retrieval call is added; `test_retrieve_render_isolation.py` is unaffected. |
| IV | Verbatim is Sacred | **PASS** | No prompt or quote-handling change. The spine keeps its `quote_verified` provenance untouched. |
| V | One Seam per Boundary | **PASS** | Config models live once, in `campaignlib`. No new LLM seam — rendering still goes through `campaignlib.api`. |
| VI | CLI is the Engine, UI is a Face | **PASS** | Routes build argv and shell out via `subprocess_runner`; FR-023 forbids reimplementation. All three tools are already console scripts. |
| VII | Extract Once, Synthesize Deliberately | **PASS** | Section granularity is unchanged and `SPECS` stays in code (FR-014) — no pass is widened or collapsed, which is the `ChapterExtractConsolidation_killed.md` trap. |
| VIII | State is Discoverable | **PASS** | Strengthened: staleness becomes visible per section, and FR-024a surfaces which curation inputs fed each one. |
| IX | The UI Mechanizes; Claude Converses | **PASS** | Release scope is staleness + rebuild — mechanical sequencing only. Judgment checkpoints stay at the CLI by explicit decision (spec Q2). FR-022a keeps CLI parity; every step hands off through a file. |
| X | Selection is Explicit; No Silent "All" | **PASS** | Research D6: the corpus glob stays `required=True` and gains no config default; a test asserts the field's *absence*. The UI passes the section set explicitly. |

**Architecture-is-Destiny clause**: this feature adds one YAML document and no daemon, database or
cache. The recurring tax is one strict document per campaign, justified by removing four duplicate
declarations and one live correctness bug (the `events.jsonl` hash-vs-read split).

**Gate result: PASS, no violations.** Complexity Tracking is therefore omitted.

## Project Structure

### Documentation (this feature)

```text
specs/006-state-projection-service/
├── plan.md              # This file
├── spec.md              # /speckit-specify + /speckit-clarify output
├── research.md          # Pre-seeded survey (D1–D10) + this phase's D11–D14
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output — CLI + HTTP contracts
├── checklists/
│   └── requirements.md  # 16/16 passing
└── tasks.md             # /speckit-tasks output — NOT created here
```

### Source Code (repository root)

```text
campaignlib/
├── projection_config.py          # NEW — ProjectionConfig (strict), load/save, PROJECTION_CONFIG_FILENAME
└── constants.py                  # unchanged — config_path() is the declared-location helper

pipelines/grounding/
├── grounding_sections.py         # literals → config; output namespace; legacy-draft gate
├── event_spine.py                # DEFAULT_STORE → config
├── thread_registry.py            # DEFAULT_REGISTRY / DEFAULT_PROPOSALS → config
└── build_recent_events.py        # --output/--window/--store → config (research D15)

server/
├── projection_config_service.py  # NEW — owns <config>/projections.yaml
├── routers/projections.py        # NEW — /api/projections/{config,sections,run/build,run/recent-events}
├── routers/ensemble.py           # CHANGED — recent-events route removed (moves to projections)
├── ensemble_config_shared.py     # CHANGED — recent_events_out + recent_events_window deleted, no shim
└── main.py                       # mount the router (one line)

frontend/src/views/grounding/
└── ProjectionSections.vue        # NEW — staleness table + per-section rebuild

tests/
├── test_projection_config.py     # NEW — schema, defaults, absent-corpus assertion
├── test_projection_isolation.py  # NEW — non-interference, no cross-service reads, no literals
├── test_projection_routes.py     # NEW — route contract, sentinel resolution
├── test_fact_record_contract.py  # NEW — the shared service's output contract (research D3)
└── test_config_location.py       # CHANGED — CONFIG_FILENAMES gains projections.yaml

docs/config/projection-isolation.md  # NEW — the series doc; six cross-cutting docs reconciled
```

**Structure Decision**: Web-application layout matching the repo's existing split — `campaignlib/`
(engine models importable by both layers), `pipelines/grounding/` (the CLI engine), `server/` (thin
routers plus one config service), `frontend/src/views/grounding/` (one page). No new top-level
directory. The `campaignlib` placement is forced by `test_layering.py`: the model is needed in both
places and the engine may not import the server.

**Where this feature touches another service, and why** — two places, both forced, both narrow:

| File | Change | Forced by |
|---|---|---|
| `pipelines/grounding/campaign_state.py` | auto-stage re-pointed at Dossier Synthesis's new draft location | FR-007a — the input must follow its producer or silently read nothing |
| `server/routers/ensemble.py` + `ensemble_config_shared.py` | recent-events route and its two settings removed | Research D15 — leaving them would make an ensemble route read this service's config |

An earlier draft of this plan promised Phases 1–4 would touch no file belonging to another service.
That was my framing, not a spec requirement, and D15 retired it. The spec's actual requirement is
that the other services keep working (FR-006, SC-001) — which the quickstart verifies by hashing
their outputs before and after.

## Phase 0 — Research

`research.md` was pre-seeded before this run with the codebase survey (D1–D10) and has been
**extended, not regenerated**, per the operator's instruction. Appended this phase:

- **D11** — where the shared Extraction & State service's config document lives *(spec Assumption, settled)*
- **D12** — which service owns the synthesis engine both renderers invoke *(spec Assumption, settled)*
- **D13** — the output namespace layout and the legacy-draft gate mechanism
- **D14** — how the CLIs locate and resolve the new document
- **D15** — `build_recent_events`, its two settings and its route move to this service, superseding
  D7. Forced by D14: once `--store` resolves from `projections.yaml`, an ensemble-side route
  invoking that wrapper would be a cross-service config read (FR-003). No compatibility shim —
  both campaigns' ensemble pages `400` until the retired key is hand-removed.

No `NEEDS CLARIFICATION` items remain in Technical Context.

## Phase 1 — Design & Contracts

- **`data-model.md`** — `ProjectionConfig` and its groups (`stores`, `inputs`, `output`, `selection`),
  plus the durable entities it points at (fact-corpus record, entity dossier, event-spine row, thread
  registry entry, section file, draft) with validation rules and lifecycles.
- **`contracts/cli.md`** — the flag surface of the three console scripts after sentinel conversion,
  and the `synthesise_world_state` flags State Projection depends on (the D12 contract).
- **`contracts/api.md`** — `GET/PUT /api/projections/config`, `GET /api/projections/sections`,
  `GET /api/projections/run/build`, with the sentinel-and-resolve rule at the route edge.
- **`quickstart.md`** — the runnable validation sequence, including the two live-campaign checks
  (behaviour-identical on out-of-the-abyss, dossier fallback on Phandalin) and the non-interference
  proof.

## Post-Design Constitution Re-check

Re-evaluated after the Phase 1 artifacts: **still PASS on all ten.** Two points worth recording
because the design could plausibly have broken them:

- **Principle IX** — an earlier shape put thread triage in the first UI release. The spec's Q2 answer
  pulled it out, keeping the interface mechanical and the judgment at the CLI. `contracts/api.md`
  therefore exposes no write route for proposals.
- **Principle X** — the build route takes an explicit section list and rejects an empty one rather
  than defaulting to all sections, mirroring `test_ensemble_chapters.py`.

## Complexity Tracking

Not applicable — the Constitution Check passed with no violations.
