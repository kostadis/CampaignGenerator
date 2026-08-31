# Implementation Plan: Thread UI Consistency and Overflow Access

**Branch**: `018-align-thread-ui` | **Date**: 2026-08-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/018-align-thread-ui/spec.md`

> This plan is a model-produced draft. The architecture and file scope require
> human review before `$speckit-tasks` may use them.

## Summary

Bring the Threads surface into the established Catppuccin Mocha application
visual language and make all oversized content reachable at normal browser
zoom. The implementation is intentionally frontend-local: make
`frontend/src/views/grounding/Threads.vue` the two-axis scroll owner already
required by the application's overflow-hidden shell, replace its undefined
legacy color variables and light-theme fallbacks with the tokens defined in
`frontend/src/style.css`, and add explicit styling for every existing loading,
empty, error, workflow, and semantic status state. Browser-native
`overflow: auto` supplies and recalculates horizontal access as content and
viewport size change, without JavaScript observers or changes to thread data,
routes, or workflows.

## Technical Context

**Language/Version**: TypeScript 5.9, Vue 3.5 single-file components with
`<script setup>`; CSS custom properties

**Primary Dependencies**: Vue 3, Vue Router, the existing global Catppuccin
Mocha design tokens in `frontend/src/style.css`; no new dependency

**Storage**: N/A — existing thread registry/proposal files and API payloads are
unchanged; presentation state is transient

**Testing**: `pytest` source-contract guards for durable styling/overflow
invariants, `npm --prefix frontend run build` for TypeScript/Vue compilation,
and manual desktop-browser acceptance for actual overflow, resize, and visual
comparison (the repository has no Vue component or browser-test harness)

**Target Platform**: The existing Linux-hosted FastAPI/Vue web application in
supported desktop browsers at 100% zoom

**Project Type**: Web application; this feature changes only the Vue frontend
face of an existing CLI/server capability

**Performance Goals**: Horizontal access appears on the same browser layout
cycle when content or viewport width changes; no additional network request,
timer, observer, or application state is introduced

**Constraints**: Preserve all thread data, decisions, routes, actions, and
verbatim evidence; never create a global scrollbar or change non-Threads page
layout; show horizontal chrome only when content is wider than its page
container; keep simultaneous vertical and horizontal navigation usable

**Scale/Scope**: One Threads route with empty, loading, error, populated,
expanded-form, streaming-output, and maintenance states; desktop viewports and
content sets large enough to exceed the available width

## Constitution Check

*GATE: evaluated before Phase 0 research and re-checked after Phase 1 design.
All thirteen principles are assessed as required by Governance.*

| # | Principle | Verdict | Design evidence |
|---|---|---|---|
| I | Disk is Truth, the Model is a Draft | **PASS** | The feature changes presentation only. Existing disk-backed registry and proposal data remain authoritative, and this plan is explicitly held for human review before task generation. |
| II | The Human Checkpoint is Non-Negotiable | **PASS** | No LLM call, automated ruling, scope choice, ordering choice, or attribution choice is added. Every existing GM confirmation remains intact. |
| III | Retrieval and Render are Separated | **N/A / PASS** | No retrieval or LLM render function changes; the feature only styles already-rendered Vue state. |
| IV | Verbatim is Sacred | **PASS** | Evidence quotes and error text are neither transformed nor rewritten; only their container styling changes. |
| V | One Seam per Boundary | **PASS** | No external dependency or integration seam is added or changed. Existing frontend API clients remain untouched. |
| VI | CLI is the Engine, UI is a Face | **PASS** | No thread behavior moves into the UI. The page continues to invoke the existing routes/CLI-backed workflows and changes only its face. |
| VII | Extract Once, Synthesize Deliberately | **N/A / PASS** | No extraction or synthesis pass is involved. |
| VIII | State is Discoverable | **PASS** | Existing loading, error, empty, proposal, registry, and workflow states remain visible; oversized content becomes reachable instead of silently clipped. No browser-only durable state is introduced. |
| IX | The UI Mechanizes; Claude Converses | **PASS** | The feature does not expand the UI's judgment role; it only restores access to existing controls and evidence. |
| X | Selection is Explicit; There Is No Silent "All" | **PASS** | Candidate filters, per-candidate rulings, and corpus selection behavior are unchanged; no bulk or implicit selection is added. |
| XI | Parity is Bidirectional; Every CLI Capability Has a Face | **PASS** | No CLI capability or flag is introduced or removed. Existing Threads capabilities remain reachable through the same controls. |
| XII | One Spelling per Option; No Configuration Drift | **PASS** | No option, default, config field, or CLI spelling changes. |
| XIII | Breaking State Changes Migrate Out of Band | **N/A / PASS** | No persisted state or schema changes, so no migration or migration document is required. |

**Pre-design gate result**: PASS. There are no violations requiring a
Complexity Tracking exception.

### Post-design re-evaluation

Phase 1 retains the same narrow boundary: one UI contract, no data or API
contract change, no new dependency, and no persistent state. The test strategy
guards the page-local scroll owner and token usage while reserving actual
visual/scroll behavior for human browser acceptance. All thirteen verdicts
remain unchanged. **Post-design gate result: PASS.**

## Project Structure

### Documentation (this feature)

```text
specs/018-align-thread-ui/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── ui.md
├── checklists/
│   └── requirements.md
└── tasks.md                    # Created only by $speckit-tasks after review
```

### Source Code (repository root)

```text
frontend/src/
├── App.vue                     # Existing overflow-hidden shell; reference only
├── style.css                   # Authoritative global palette/components; no change
└── views/grounding/
    ├── ProjectionSections.vue  # Established peer-page visual reference; no change
    └── Threads.vue             # Page scroll ownership + complete visual alignment

tests/
├── test_threads_ui_absences.py # Existing behavior/precision guard; must remain green
└── test_threads_ui_style.py    # New source-contract guards for feature 018
```

**Structure Decision**: Keep the change inside the existing frontend view.
`App.vue` deliberately prevents document-level overflow and established views
own their scrolling; changing the shell would affect every page and violate
FR-013. `style.css` already defines the shared palette, typography, buttons,
and scrollbar appearance, so Threads consumes it rather than creating a new
theme layer. No server, route, store, or domain-model file belongs in scope.
