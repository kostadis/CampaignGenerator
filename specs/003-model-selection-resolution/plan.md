# Implementation Plan: Model Selection Resolution

**Branch**: `003-model-selection-resolution` | **Date**: 2026-07-25 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-model-selection-resolution/spec.md`

## Summary

Enforce one model/backend resolution rule — *explicit request → service override → platform default
→ literal* — across all 17 token-spending endpoints, replacing the five independent spellings that
exist today. The platform tier gains `default_backend` so the sidebar's two controls are owned by
the same thing; the five config-owning services (Ensemble, Session Doc Editor, Grounding, Party,
Planning) hold overrides in documents they already own; the five stateless services inherit and
gain no config surface. An override that cannot run on the resolved backend refuses the run with a
409 rather than being silently substituted — reversing the ensemble's current documented behaviour.

The technical approach is a single seam (`resolve_selection`) that every router calls and no router
duplicates, with a backend-declared compatibility predicate and a pre-run preview endpoint. No new
config file, no database, no new persistence: the record of what a run used is the existing run log
from `specs/002`.

## Technical Context

**Language/Version**: Python 3.13 (server + CLI); TypeScript / Vue 3 (frontend)

**Primary Dependencies**: FastAPI, Pydantic v2 (`extra="forbid"` schemas), PyYAML, Vue 3 + Pinia

**Storage**: YAML documents in the campaign workspace — `platform.yaml` (platform tier),
`ensemble.yaml`, `session_doc.yaml`, `grounding.yaml`, `party.yaml`, `planning.yaml` (service tier).
No database.

**Testing**: pytest — `python -m pytest tests/`

**Target Platform**: Linux (WSL2), single-user local server on `:5000`

**Project Type**: Web application — FastAPI backend + Vue 3 frontend over a CLI engine

**Performance Goals**: Resolution is request-scoped and in-memory; no measurable budget. The real
metric is economic: zero metered API spend when a local backend is selected (SC-006).

**Constraints**: Single user, so migrate-and-delete — no dual-location probes, no back-compat
shims. The CLI must stay independently invocable (Principle VI). `PlatformRuntime` is
`extra="forbid"`, so adding a field requires a migration.

**Scale/Scope**: 6 routers, 17 token-spending endpoints, 5 override-capable services, 5 inheriting
services, 1 platform tier. 5 existing resolution implementations collapse to 1. 3 existing tests
are deliberately reversed.

## Constitution Check

*GATE: evaluated before Phase 0 and re-evaluated after Phase 1 design. Constitution v1.2.0 — all
ten principles, per Governance ("every spec and plan is tested, by name, against all ten").*

| # | Principle | Verdict | Basis |
|---|---|---|---|
| I | Disk is Truth, the Model is a Draft | **PASS** | Selections live in YAML on disk; `ResolvedSelection` is computed per request and explicitly never persisted (data-model.md). No new cache or database. |
| II | The Human Checkpoint is Non-Negotiable | **PASS — strengthened** | The feature *adds* a checkpoint. Choosing a model is a scope decision about token spend; the 409 refusal (FR-009) stops the system from making it on the operator's behalf. No LLM call is added by this feature. |
| III | Retrieval and Render are Separated | **PASS — not engaged** | No retrieval and no render call is added or moved. `tests/test_retrieve_render_isolation.py` must stay green (quickstart V-suite). |
| IV | Verbatim is Sacred | **PASS — not engaged** | No transcript or quote path is touched. |
| V | One Seam per Boundary | **PASS — the point of the feature** | Five resolution sites collapse to one (`resolve_selection`). This principle *is* the design: "when you need to change how CG talks to X, there must be exactly one file to open." |
| VI | CLI is the Engine, UI is a Face | **PASS — see justification** | The refusal is server-side only; CLI behaviour is unchanged, including `backends.py`'s substitution. The server decides *what to invoke*, which it already does, not *how the pipeline behaves*. See Complexity Tracking. |
| VII | Extract Once, Synthesize Deliberately | **PASS — not engaged** | No pass is added, removed or merged. |
| VIII | State is Discoverable | **PASS — strengthened** | `GET /…/selection/resolved` makes the effective selection and its origin discoverable rather than tribal; FR-014 is satisfied by the on-disk run log. Today the effective backend of a Grounding run is genuinely undiscoverable without reading source. |
| IX | The UI Mechanizes; Claude Converses | **PASS** | No judgment is absorbed. The 409 hands a decision *back* to the operator. Every selection remains equally settable at the CLI via `--model`/`--backend`, so the operator loses nothing by dropping out of the UI. |
| X | Selection is Explicit; No Silent "All" | **PASS — direct application** | This is Principle X applied to model choice instead of chapter choice. "Never silently substitute a selection the operator did not make" (FR-011) is the same law as "an empty selection is refused, not expanded". |

**Gate result: PASS.** No unjustified violations. One item carried to Complexity Tracking for the
record.

**Post-Phase-1 re-evaluation**: re-checked against the generated design. No verdict changed. The
design added one thing worth noting — the 409 refusal path — which strengthens II and X rather than
straining any principle. Confirmed the design creates no new database, daemon, cache or LLM call,
so the "Architecture is Destiny" recurring-tax test is satisfied with nothing to justify.

## Project Structure

### Documentation (this feature)

```text
specs/003-model-selection-resolution/
├── plan.md              # This file
├── research.md          # Phase 0 — 9 findings, all NEEDS CLARIFICATION resolved
├── data-model.md        # Phase 1 — entities, the one rule, migration
├── quickstart.md        # Phase 1 — 10 runnable validations
├── contracts/
│   ├── resolution.md    # The seam: signature, callers, guarantees, predicate, refusal
│   └── api.md           # HTTP surface: platform field, selection sub-resources, 409
├── checklists/
│   └── requirements.md  # Spec quality checklist (16/16)
└── tasks.md             # Phase 2 — NOT created by /speckit-plan
```

### Source Code (repository root)

```text
server/
├── platform_config_shared.py       # PlatformRuntime += default_backend
├── platform_config_service.py      # resolve_default_model -> resolve_selection (THE SEAM)
├── migrate_platform_config.py      # + backends.active -> runtime.default_backend
├── backend_forwarding.py           # unchanged — flag builder, not resolver
├── config.py                       # MODELS registry, unchanged
├── grounding_config_shared.py      # += selection: ModelSelection
├── party_config_service.py         # += selection
├── planning_config_service.py      # += selection
├── ensemble_config_shared.py       # EnsembleBackend already conformant
├── session_editor_config_shared.py # BackendProfile already conformant
└── routers/
    ├── grounding.py                # DELETE _backend_flags (cross-service read); call seam
    ├── ensemble.py                 # _backend_args -> seam; drop inline claude- guard
    ├── scene_editor.py             # _model_args -> seam
    ├── prep.py                     # + backend forwarding (has none today)
    ├── setup.py                    # + backend forwarding (has none today)
    ├── connections.py              # + backend forwarding (has none today)
    ├── party_routes.py             # + /selection sub-resource
    ├── planning_routes.py          # + /selection sub-resource
    └── config_routes.py            # PUT /runtime accepts default_backend; /models extended

frontend/src/
├── components/layout/AppSidebar.vue  # BACKEND toggle -> PUT /api/config/runtime
├── stores/config.ts                  # runtime.default_backend; drop editor-config write
└── components/**                     # per-service override + pre-run resolved display

tests/
├── test_default_model_resolution.py     # extend to backend + service tier
├── test_ensemble_gates.py               # REVERSE the 3 stale-model tests (R8)
├── test_ensemble_config_defaults.py     # TestModelResolution must stay green
├── test_editor_service_integration.py   # TestO3ModelResolution must stay green
└── test_selection_isolation.py          # NEW — no router reads another service's config
```

**Structure Decision**: Existing web-application layout, unchanged. This feature adds no directory
and no file outside `tests/`. The work is concentrated in `server/platform_config_service.py` (the
new seam) and the six routers that call it; the three service schemas gain one field each in
documents they already own. `server/backend_forwarding.py` is deliberately left alone — it already
draws the correct line between *resolving* a selection and *formatting* it as flags, and this
feature only fixes the resolving half.

## Complexity Tracking

> One item recorded for the audit trail. It is a justified divergence, not an unjustified violation.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| The server refuses a run the CLI would accept (Principle VI asymmetry) | The UI resolves from *stored* state on the operator's behalf, so it can produce a pair the operator never chose. A GM typing `--model X --backend Y` is making an explicit act — Principle X's own carve-out for a typed glob. Blocking that would break the CLI-as-engine escape hatch Principle IX guarantees. | Enforcing refusal inside the CLI scripts was rejected: it would break direct CLI use and duplicate the rule into every script, recreating the fragmentation this feature exists to remove. Enforcing it in `subprocess_runner` was rejected: by then the command is built and the structured reason is lost, so the operator gets a stream error instead of an actionable 409 — exactly the failure mode `specs/002` was built to eliminate. |

**Not** recorded as complexity, having been considered and found clean: the three reversed tests
(R8) are an intended behaviour change recorded in the spec's Assumptions, not scope creep; and the
`ModelSelection` / `EnsembleBackend` / `BackendProfile` triple is not duplication — the endpoint
plurality that distinguishes them is load-bearing (two-Spark fan-out vs single host).
