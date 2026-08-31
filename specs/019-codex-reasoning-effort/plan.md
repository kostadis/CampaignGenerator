# Implementation Plan: Codex Reasoning Effort Everywhere

**Branch**: `019-codex-reasoning-effort` | **Date**: 2026-08-30 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/019-codex-reasoning-effort/spec.md`

## Summary

Add one optional `--codex-reasoning-effort` control to the shared `codex-cli`
execution path and every production command that forwards that path. The
control accepts `minimal`, `low`, `medium`, `high`, `xhigh`, or `max`, resolves
an explicit CLI/UI choice before `CG_CODEX_REASONING_EFFORT`, and otherwise
omits the Codex override. The existing isolated `codex exec` adapter remains
the only child-process boundary and adds `model_reasoning_effort` only when a
value resolves.

Extend the existing model/backend selection and command-builder seams so all
Codex-capable UI launch surfaces expose a fixed select, persist Codex-specific
memory, and forward the same CLI option. A canonical pre-launch identity line
reports model, effort, and source to terminals, SSE output, and run logs. Static
inventory tests continue to cover all 30 current production surfaces and fail
when a future Codex-capable command or UI face omits the setting.

## Technical Context

**Language/Version**: Python `>=3.9`; TypeScript `~5.9`; Vue `^3.5`
**Primary Dependencies**: Pydantic 2, FastAPI, PyYAML, Pinia 2, Vue Router 4,
Vite 8, and the external Codex CLI (`codex exec`)
**Storage**: Existing YAML configuration (`platform.yaml`, service-owned YAML
documents) and Markdown run logs/artifacts; no database or new store
**Testing**: pytest; AST/source inventory guardrails; fake Codex subprocess
fixtures; FastAPI route tests; `vue-tsc` and Vite production build
**Target Platform**: Local CampaignGenerator CLI/server on Linux or macOS with
a browser UI and an authenticated Codex subscription CLI
**Project Type**: Python CLI family plus FastAPI subprocess orchestration and a
Vue single-page UI
**Performance Goals**: Constant-time option resolution; no added model calls;
invalid local selections rejected before a Codex child starts; no measurable
change to existing orchestration or UI launch latency
**Constraints**: Preserve `--ignore-user-config`, strict fail-closed Codex
isolation, credential stripping, timeouts, cleanup, artifact integrity, human
checkpoints, no provider fallback, and exact omission semantics
**Scale/Scope**: 30 inventoried production CLI surfaces (26 direct and four
dispatchers), the shared server selection/command seam, all selector-owning UI
surfaces, and progress/result views that expose run identity

## Constitution Check

### Pre-design gate

| Principle | Plan evidence | Status |
|---|---|---|
| I. Disk is Truth, Model is Draft | Optional selections remain in owner YAML files; run identity is persisted in existing disk logs. No campaign fact or approved artifact is reclassified. | PASS |
| II. Human Checkpoint is Non-Negotiable | Effort is an operator choice and changes no scope, attribution, ordering, promotion, or approval boundary. | PASS |
| III. Retrieval and Render are Separated | No retrieval/render function is added or combined; only execution configuration is threaded through the existing render seam. | PASS |
| IV. Verbatim is Sacred | No transcript or quote transformation changes. | PASS |
| V. One Seam per Boundary | `campaignlib/api/codex_cli.py` remains the sole Codex child boundary; vocabulary and parsed-argument resolution are shared. | PASS |
| VI. CLI Engine, UI Face | UI stores and forwards the canonical CLI option through shared command builders; it never invokes Codex or reimplements inference. | PASS |
| VII. Extract Once, Synthesize Deliberately | Extraction, caches, and synthesis pass structure are unchanged. | PASS |
| VIII. The Pipeline is Self-Describing | CLI output, SSE output, resolved previews, and run logs expose model plus reasoning state and provenance. | PASS |
| IX. UI Mechanizes; Claude Converses | UI adds a bounded select and run identity only; all judgment and file handoffs remain where they are. | PASS |
| X. Selection is Explicit | Effort does not alter selected documents, scenes, chapters, retries, or empty-selection behavior. | PASS |
| XI. CLI/UI Parity is Bidirectional | Every selector-owning Codex UI face gains the setting in this feature; display-only faces show the resulting identity. | PASS |
| XII. One Spelling per Option | One flag, environment name, value tuple, resolver, and command formatter are reused across all 30 CLI surfaces. | PASS |
| XIII. Breaking State Changes Migrate Out of Band | Fields are optional and additive; old YAML remains valid and omission retains old behavior. No migration is required. | PASS |

**Gate result**: PASS. There are no constitutional violations to justify.

### Post-design re-check

Phase 1 keeps the same boundaries: the contracts route all execution through
the CLI and adapter seams, the data model makes persisted fields optional, and
the quickstart verifies checkpoints and artifact paths remain unchanged. The
design introduces no hidden browser-only state, database, new model call,
implicit scope expansion, or breaking state rewrite. All thirteen gates remain
PASS.

## Design Overview

1. **Canonical vocabulary and resolution**: add the six-value effort type and
   one shared parser/resolver. Explicit CLI/UI value wins over the trimmed
   environment fallback; whitespace environment means omission. Explicit use
   with another backend fails before work, while an ambient Codex environment
   variable is ignored by non-Codex runs.
2. **One adapter override**: thread the optional value into `_CodexCliClient`
   and the direct, streaming, and brokered message facades. The sole
   `_codex_cli_generate` boundary validates the final model/effort identity,
   prints it, and asks `_command` to append one TOML-safe
   `-c model_reasoning_effort=...` pair only when selected.
3. **Family-wide forwarding**: the shared registrar covers 26 direct commands;
   the one hand-written direct parser and four runtime dispatchers consume the
   same helper and forward explicit values unchanged. Environment fallback is
   inherited and resolved only by the final Codex adapter.
4. **Server and persistence**: extend `ModelSelection`, `PlatformRuntime`, and
   `ResolvedSelection`; make `selection_cli_args()` the only server-side
   producer of `--codex-reasoning-effort`. Additive optional fields preserve
   old documents and retain Codex values when another backend is active.
5. **UI parity and observability**: publish the canonical choices from the
   config API and use a fixed seven-option selector (Codex default plus six
   explicit values) in global, generic service, session-editor, scene-knob,
   and ensemble settings. Existing SSE/log capture carries the adapter identity
   line; the in-process Connection Graph route returns the same identity in its
   result because it has no subprocess stream.
6. **Guardrails and documentation**: extend the existing 30-surface discovery
   tests, focused adapter/dispatcher/config/route tests, operator help, CLI
   reference, and configuration documentation.

## Project Structure

### Documentation (this feature)

```text
specs/019-codex-reasoning-effort/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli-family.md
│   ├── run-identity.md
│   └── ui-selection.md
└── tasks.md                  # generated later by $speckit-tasks
```

### Source Code (repository root)

```text
campaignlib/
├── selection.py             # canonical effort type and stored selection field
└── api/
    ├── client.py            # shared parser/resolver and client construction
    └── codex_cli.py         # sole Codex argv/subprocess/identity boundary

pipelines/                   # direct commands and ensemble forwarding dispatchers
session_doc/                 # direct commands and sd_agent forwarding dispatcher

server/
├── platform_config_shared.py
├── platform_config_service.py
├── backend_forwarding.py
├── session_editor_config_shared.py
├── ensemble_config_shared.py
├── subprocess_runner.py
└── routers/                 # shared selection/command builders and run routes

frontend/src/
├── stores/config.ts
├── components/layout/AppSidebar.vue
├── components/shared/SelectionPanel.vue
├── components/scene-editor/KnobDrawer.vue
└── views/
    ├── ensemble/EnsembleSetup.vue
    ├── prep/ConnectionGraph.vue
    └── session/
        ├── SessionDocEditor.vue
        └── ReviewAssemble.vue

tests/
├── helpers/fake_codex_cli.py
├── test_codex_cli_backend.py
├── test_codex_cli_family.py
├── test_backend_seam_guardrails.py
├── test_platform_config_service.py
├── test_ensemble_dispatch.py
├── test_sd_agent.py
├── test_editor_pipeline.py
└── test_subprocess_abort.py

docs/
├── cli/cli_tools.md
├── core/configuration.md
└── config/                 # schema/value ownership documentation
```

**Structure Decision**: Extend the existing layered web application in place.
Provider vocabulary and execution remain in `campaignlib`; server code resolves
and formats selections but uses the CLI engine; Vue only edits persisted
configuration and displays execution output. No new package, service, or
storage tier is introduced.

## Complexity Tracking

No constitution violations or exceptional complexity are required.
