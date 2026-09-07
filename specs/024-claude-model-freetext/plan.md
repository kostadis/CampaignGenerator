# Implementation Plan: Hand-Entered Claude Model Ids

**Branch**: `024-claude-model-freetext` | **Date**: 2026-09-06 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/024-claude-model-freetext/spec.md`

## Summary

Two places in the app treat `server/config.py`'s hardcoded `MODELS` list as
authoritative rather than advisory, and both go stale the day Anthropic ships a
model:

1. **The app-wide MODEL control** (`AppSidebar.vue`) renders a closed `<select>`
   on the two Claude backends and a free-text `<input>` on the other three. A
   model absent from `MODELS` is unreachable at any price.
2. **The ensemble synthesis warning** (`ensemble.py:1148`) tells the GM their
   model "may be too weak" whenever it is not in the derived `SYNTHESIS_CAPABLE`
   set — which, on the `claude-code` backend, fires on exactly the new model this
   feature exists to enable.

The approach is the same in both places, and it is a rule the codebase already
follows elsewhere: **judge a model by the shape of its id, never by membership of
a hand-maintained list.** `campaignlib/selection.py::compatible()` already says so
in its docstring — *"testing against it would silently reject a legitimate Claude
id that simply hadn't been added yet"* — and then declines to use `MODELS`. This
feature extends that reasoning to the two consumers that did not get the memo.

The selector becomes one `<input list=…>` + `<datalist>` on every backend: typing
is always possible, the curated ids remain one click away as suggestions, and the
control stops behaving differently depending on which backend is active. The
warning swaps set membership for a predicate that keeps the one genuine judgement
(the sub-Sonnet tier is excluded) and drops the bogus inference (unknown ⇒ weak).

No config schema changes, no new runtime dependency, no migration.

## Technical Context

**Language/Version**: Python 3.11+ (FastAPI server, CLIs); TypeScript 5.9 + Vue 3.5 (SPA)

**Primary Dependencies**: FastAPI, Pydantic v2, Pinia, vue-router. **No new dependency** — the combo input is native HTML (`<input list>` + `<datalist>`); `frontend/package.json` keeps its three runtime deps.

**Storage**: `<campaign>/platform.yaml` — `runtime.default_model` (`str`) and `runtime.default_models` (`dict[Backend, OptStr]`). **Shape unchanged**; this feature only widens which strings reach them.

**Testing**: `pytest` (`tests/`) for the server and for source-level UI guardrails; Playwright (`frontend/e2e/`, Chromium, route-mocked against the Vite dev server — no backend required). There is no Vue component-test harness (issue #345), so the persistence round-trip is proven by Playwright rather than by a component test.

**Target Platform**: Linux, single-operator local web app, Chromium.

**Project Type**: Web application — FastAPI backend + Vue SPA, existing directories.

**Performance Goals**: N/A. One form control and one string predicate; nothing measurable changes.

**Constraints**: No new runtime dependency. No config schema change (Principle XIII stays unarmed). Adopting a model must need no release, reinstall, or server restart. The curated shortlist must stay reachable in one interaction (SC-004).

**Scale/Scope**: 1 operator, 5 backends, ~8 curated ids, 2 files of production change (`AppSidebar.vue`, `server/routers/ensemble.py`) plus tests.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design — see the second verdict on each row.*

| Principle | Bearing on this feature | Verdict |
|---|---|---|
| **XI — Parity is Bidirectional; Every CLI Capability Has a Face** | This feature *is* the remedy for a live violation. `--model` accepts any Claude id at the CLI (`compatible()` gates on id shape, not list membership), and the UI cannot express it. That is the Orphaned Capability the principle names: "the engine offers a choice the human cannot make." | **PASS — by repair.** Post-design: unchanged. |
| **XII — One Spelling per Option; No Configuration Drift** | Two sub-claims. (a) The MODEL control currently means two different things depending on backend — a dialect inside a single control. (b) "Is this Claude model capable enough" is inferred two ways: by id shape in `compatible()`, by set membership in `SYNTHESIS_CAPABLE`. | **PASS — by repair.** Post-design: the control becomes one widget on all five backends; the capability question becomes one predicate. The two *functions* stay separate deliberately (they answer different questions — see R4). |
| **XIII — Breaking State Changes Migrate Out of Band** | Armed only by a change in the *shape* of state. `default_model` is already a free `str` and `default_models` already a free-string map; both already hold hand-typed ids today from the three open backends. | **N/A — no migrator, no `migration.md`.** Stated explicitly so its absence is a ruling, not an omission. Post-design: confirmed — no Pydantic model is touched. |
| **VI — CLI is the Engine, UI is a Face** | No pipeline logic moves into the server. The router keeps building argv; the only server change is the text of one warning's condition. | **PASS.** Post-design: unchanged. |
| **VIII — State is Discoverable** | A hand-entered model must be as visible as a curated one: written to `platform.yaml` on disk, and reported by the resolved-selection preview with its origin. Nothing may live only in the browser. | **PASS** — `setModel` already persists through `PUT /api/config/runtime`; FR-009 pins the preview. Post-design: `contracts/model-selector-ui.md` §4 makes it explicit. |
| **IX — The UI Mechanizes; Claude Converses** | No judgement moves into the UI. The GM decides which model to run; the app stops overruling them. | **PASS.** Post-design: unchanged. |
| **I — Disk is Truth, the Model is a Draft** | Reinforced: `platform.yaml` becomes the sole authority on the active model, and the curated list is demoted to a suggestion with no veto. | **PASS.** |
| **II / III / IV / V / VII / X** | No LLM call is added or moved; no retrieval/render boundary, verbatim content, integration seam, extraction pass, or batch selection is touched. | **N/A.** |

**Gate result: PASS, no violations to justify.** Two principles are satisfied *by
repairing an existing breach* rather than by avoiding a new one, which is the
strongest form of pass available here.

## Project Structure

### Documentation (this feature)

```text
specs/024-claude-model-freetext/
├── spec.md              # Input
├── plan.md              # This file
├── research.md          # Phase 0 output — 8 decisions
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output — runnable validation
├── contracts/           # Phase 1 output
│   ├── model-selector-ui.md
│   ├── config-models-api.md
│   └── synthesis-capability.md
├── checklists/
│   └── requirements.md  # From $speckit-specify — 16/16
└── tasks.md             # Phase 2 — NOT created by $speckit-plan
```

### Source Code (repository root)

```text
frontend/
├── src/
│   ├── components/
│   │   └── layout/
│   │       └── AppSidebar.vue        # CHANGED — the whole UI half of the feature
│   └── stores/
│       └── config.ts                 # UNCHANGED — already publishes `models`
└── e2e/
    └── model-selector.spec.ts        # NEW — persistence round-trip, route-mocked

server/
├── config.py                         # UNCHANGED — MODELS stays a snapshot, now advisory
└── routers/
    ├── config_routes.py              # UNCHANGED — /api/config/models keeps its shape
    └── ensemble.py                   # CHANGED — SYNTHESIS_CAPABLE set → synthesis_capable()

campaignlib/
└── selection.py                      # UNCHANGED — the rule this feature copies

tests/
├── test_model_selector_ui.py         # NEW — source-level guardrails (Principle XI pattern)
└── test_synthesis_capable_registry.py # CHANGED — set assertions → predicate assertions
```

**Structure Decision**: The existing web-application layout is used as-is. This
feature adds no module and no directory: the UI half is one component, the server
half is one router-local predicate, and `campaignlib/` — the layer that already
holds the id-shape rule being copied — is deliberately not touched (see R4 for why
the two rules stay separate rather than being merged into one shared helper).

## Complexity Tracking

> No Constitution Check violations. Table intentionally empty.
