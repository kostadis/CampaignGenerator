# Implementation Plan: Bundled Narration Generation

**Branch**: `narration-bundle` | **Date**: 2026-09-05 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/022-bundle-narration/spec.md`

## Summary

Add an opt-in `sd_narrate --batch-scenes` path that prepares an explicit set of reviewed plan scenes, sends their shared context once in one model exchange, reconciles the response by stable scene index, and writes the existing per-scene narration files. The existing unadorned sequential loop and current-scene editor action remain unchanged. The Session Doc Editor gains an explicit “Narrate all in one call” review dialog and SSE route that materializes every selected plan index, preserves each scene's raw/smoothed source choice, and records successful, partial, or unreconcilable outcomes on disk.

## Technical Context

**Language/Version**: Python 3.9+; TypeScript 5.9; Vue 3.5

**Primary Dependencies**: Existing `campaignlib` backend facade and batch client; argparse; FastAPI/Pydantic; Vue/Pinia; native EventSource SSE

**Storage**: Existing Markdown narration files and knob sidecars; YAML editor configuration; JSON bundle run report; append-only JSONL editor activity log

**Testing**: pytest; Vue type checking/Vite production build; Playwright for the new editor interaction

**Target Platform**: Linux CLI and locally hosted web UI in a modern browser

**Project Type**: Python CLI engine with FastAPI adapter and Vue web client

**Performance Goals**: A selected narration set that fits the configured bundle ceiling uses exactly one model exchange and transmits shared party, style, genre, roster, and campaign context once rather than once per scene.

**Constraints**: Bundling is opt-in; the selected set must be explicit and non-empty; a bundle never auto-splits; provider Message Batches remains a separate composable choice; `--narrator` remains available to sequential mode but is refused with `--batch-scenes`; every scene keeps its plan identity, narrator-specific guidance, existing file shape, and human review boundary; no fuzzy reconciliation; mixed base/override editor sources must remain intact.

**Scale/Scope**: One campaign session at a time, normally several plan scenes and narrators; all currently supported text backends; no new service, database, or migration.

## Constitution Check

*GATE: Passed before Phase 0 research; re-checked after Phase 1 design.*

| Principle | Pre-design gate | Post-design result |
|---|---|---|
| I. Disk is Truth, the Model is a Draft | Pass if bundle output remains ordinary draft files and the run outcome is durable. | Pass. Existing per-scene files remain canonical drafts; an atomic JSON report and editor activity row preserve the run outcome. |
| II. The Human Checkpoint is Non-Negotiable | Pass if the reviewed plan and extractions define scope/order and no downstream stage auto-runs. | Pass. The UI materializes the reviewed plan indices, and bundle completion never approves or assembles. |
| III. Retrieval and Render are Separated | Pass if no retrieval enters the narration render call. | Pass. The new path consumes the same already-resolved files as sequential narration and adds no retrieval. |
| IV. Verbatim is Sacred | Conditional: bundled prompts must preserve every current quoted-speech rule and validation must include a representative sequential/bundle comparison. | Pass with a ship gate. Bundle-specific prompt contract tests preserve the load-bearing rules; quickstart validation checks source quotes, narrator attribution, continuity, and tail-scene completeness before release. |
| V. One Seam per Boundary | Pass if all model calls remain behind the existing client facade. | Pass. Bundled live generation uses `stream_api`; provider batch pricing uses one `run_single_batch` item. |
| VI. CLI is the Engine, UI is a Face | Pass if parsing, prompt construction, reconciliation, and file writes remain in CLI-owned modules. | Pass. The router only resolves files, builds argv, streams it, and records results. |
| VII. Extract Once, Synthesize Deliberately | Pass if consolidation is limited to one rendering job and quality is validated. | Pass. Reviewed extractions remain separate inputs; the feature consolidates only narration rendering and retains per-scene recovery. |
| VIII. State is Discoverable | Pass if outputs and partial state survive leaving the page. | Pass. Per-scene files plus the run report name written, missing, and rejected scenes. |
| IX. The UI Mechanizes; Claude Converses | Pass if the UI selects, invokes, streams, and reloads files without owning prose state. | Pass. The dialog materializes scope and the editor refreshes disk-backed scene state after the CLI exits. |
| X. Selection is Explicit; There Is No Silent “All” | Pass if the UI sends literal scene indices and empty selection refuses. | Pass. The all-scenes dialog lists the set and sends every index; the endpoint refuses absent, empty, duplicate, or invalid indices. |
| XI. Parity Is Bidirectional | Pass if the editor action is a reproducible CLI invocation in the same feature. | Pass. The SSE command event shows the exact `sd_narrate --batch-scenes --scene ...` command. |
| XII. One Spelling per Option | Pass if existing multi-scene batching vocabulary is reused and defaults have one owner. | Pass. `--batch-scenes` and `--batch-max-tokens` match `scene_extract`; `NarrateKnobs.batch_tokens` owns the UI default. |
| XIII. Breaking State Changes Migrate Out of Band | Pass if configuration changes are additive. | Pass. The optional `narrate.batch_tokens` field has a default; no existing state shape or path is replaced. |

No constitutional violation requires a complexity exception.

## Project Structure

### Documentation (this feature)

```text
specs/022-bundle-narration/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli-surface.md
│   ├── editor-api.md
│   ├── run-report.md
│   └── wire-protocol.md
└── tasks.md
```

### Source Code (repository root)

```text
config/agents/session_doc/narrate/
├── base.md                  # existing sequential prompt, unchanged in behavior
├── bundle_base.md           # shared bundle rules and continuity contract
└── bundle_scene.md          # one indexed scene packet

session_doc/
├── narrate.py               # bundle input model, prompt builders, parser wrapper
└── sd_narrate.py            # CLI flags, full-set preflight, one call, writes/report

server/
├── session_editor_config_shared.py  # NarrateKnobs.batch_tokens
└── routers/scene_editor.py           # bundle argv builder and SSE endpoint

frontend/src/
├── components/scene-editor/
│   ├── ExtractionEditor.vue         # retain current-scene action; open bundle flow
│   ├── NarrationBundleDialog.vue    # exact scope/replacement review
│   └── KnobDrawer.vue               # bundle ceiling and corrected batch explanation
└── views/session/SessionDocEditor.vue # dialog state, SSE run, full refresh

tests/
├── test_narration_bundle_split.py
├── test_narration_bundle_cli.py
├── test_narration_bundle_report.py
├── test_sd_narrate.py
├── test_narrate_input_delivery.py
├── test_narrate_template_contract.py
├── test_editor_pipeline.py
├── test_editor_service_integration.py
├── test_session_editor_config_service.py
└── test_backend_seam_guardrails.py

frontend/e2e/
└── session-narration-bundle.spec.ts

docs/
├── cli/session_doc_pipeline.md
├── cli/cli_tools.md
├── web/session_doc_editor.md
└── system/flow-post-session.md
```

**Structure Decision**: Keep the established CLI/server/frontend split. Pure narration input preparation and protocol validation live beside existing prompt builders in `session_doc/narrate.py`; `sd_narrate.py` remains the CLI engine and owns calls and disk output. The server and UI only expose that engine. Reuse the proven scene sentinel splitter through a narration-specific validator rather than introduce a second parser or an external dependency.

## Phase 0 — Research

**Status**: Complete → [research.md](./research.md)

Research resolved option naming, prompt factorization, within-response continuity, source override handling, deterministic splitting, partial outcomes, provider-batch composition, output sizing, durable audit state, editor interaction, and regression boundaries. No `NEEDS CLARIFICATION` remains.

## Phase 1 — Design & Contracts

**Status**: Complete → [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

The CLI first resolves the full-plan indices, all exact extraction sources, narrator guidance, shared context, output paths, replacement set, and projected output. It refuses before client creation if any scene is invalid, if `--narrator` is combined with bundle mode, or if the projection exceeds `--batch-max-tokens`. One bundle-specific prompt carries shared material once and ordered scene packets after it. Before invoking the existing deterministic splitter, a raw-marker preflight verifies marker identity, matching BEGIN/END indices, nesting, duplication, and encounter order so normalization cannot hide protocol corruption. Complete sections are atomically written through the same formatting helper as sequential mode. Any structurally valid response short of the full set, including zero complete sections, exits partial and retains existing files; identity/protocol corruption writes none. Once the report destination is initialized, every attempt finalizes an atomic report, including refusals and backend failures.

For editor runs, the route creates a nonce-scoped session-local report path and passes it through `--run-report`. It wraps `stream_subprocess(..., emit_done=False)`, validates that exact report after process completion, applies report-derived sidecars/activity, and emits one route-specific terminal `done` event containing status, K/N counts, missing scenes, and the raw return code. This prevents concurrent or stale “latest” reports from being presented as the current run.

## Complexity Tracking

No constitution violations require justification. The new prompt templates, response validator, and run-report artifact are necessary parts of the one-exchange contract: they keep shared context from being repeated, prevent cross-scene attribution, and make partial UI outcomes auditable.
