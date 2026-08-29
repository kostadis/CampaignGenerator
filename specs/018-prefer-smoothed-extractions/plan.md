# Implementation Plan: Prefer Smoothed Scene Extractions for Narration

**Branch**: `018-prefer-smoothed-extractions` | **Date**: 2026-08-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/018-prefer-smoothed-extractions/spec.md`

## Summary

When a GM creates `scene_extractions_smoothed`, the Session Doc UI must show
the exact file Narrate will consume and prefer that scene's smoothed file over
the configured raw extraction. Scenes without a smoothed counterpart continue
to use raw input, and neither layer is modified merely because Narrate uses it.

The implementation keeps raw editing and Narrate-source selection separate.
The existing extraction editor continues to load and save the configured raw
file. A server-owned resolver examines disk for the selected scene, applies
the loader's established eligibility/scaffold/index rules, and returns an
additive `narrate_source` projection to the UI. The UI renders that projection,
refreshes it immediately before a run, and no longer writes the raw editor
buffer unconditionally before Narrate.

For execution, `sd_narrate` gains a narrow single-scene override:
`--scene-extraction-file FILE`, valid only with exactly one `--scene N`. The
router still supplies `--scene-extractions DIR` as the ordinary/raw context,
but supplies the exact smoothed file when it is active. This removes the
partial-directory ambiguity in the CLI's current name-then-list-index fallback
and guarantees that the path displayed by the UI is the file Narrate reads.

## Technical Context

**Language/Version**: Python >=3.9 (`pyproject.toml`); TypeScript 5.9 and Vue
3.5 (`frontend/package.json`)

**Primary Dependencies**: FastAPI, pydantic, and the existing subprocess/SSE
runner on the server; Vue, Pinia, Vue Router, Vite 8, and `vue-tsc` in the
frontend. No new dependency.

**Storage**: Markdown scene-extraction files on disk. Raw input is the
configured `paths.scene_extractions_dir`; preferred input is the conventional
`<session_dir>/scene_extractions_smoothed`. No database and no persisted
configuration field are added.

**Testing**: pytest for shared I/O, CLI, command-builder, route, and integration
coverage. The frontend has no test runner; its automated gate is
`npm run build` (`vue-tsc -b` plus Vite), followed by the manual scenarios in
`quickstart.md`.

**Target Platform**: Linux, single-operator local FastAPI service plus browser
SPA and Python CLI tools.

**Project Type**: Web application with a CLI engine: `session_doc/` contains
the file/CLI authority, `server/` exposes it to the UI, and `frontend/` renders
the file handoff and invokes it.

**Performance Goals**: Resolve and display a selected scene's source within
100 ms for a normal session. Source resolution adds at most two small
directory scans and readability probes; it adds no model call and no network
dependency.

**Constraints**: Disk is authoritative; the browser may not infer or cache the
active layer as truth. Smoothed selection is per scene. An unreadable smoothed
candidate blocks instead of silently falling back. Raw and smoothed files are
not rewritten by source discovery or Narrate invocation. Non-Narrate stages
retain the configured raw directory. The new CLI option has one spelling and
one validation rule.

**Scale/Scope**: Typically 1–30 scenes per session and two candidate
directories. Expected source impact: three Python modules, two Vue components,
three focused backend test areas, two contract documents, and one operator
documentation update. No schema migration.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

Constitution v1.3.0. Every principle is evaluated by name.

| # | Principle | Verdict | Basis |
|---|---|---|---|
| I | Disk is Truth, the Model is a Draft | **PASS / strengthened** | The active source is resolved from disk on each detail refresh and again at Narrate invocation. No database or browser-only source choice is introduced. |
| II | The Human Checkpoint is Non-Negotiable | **PASS** | The GM creates the smoothed file and the UI exposes the exact selected path before the token-spending run. Automatic precedence is the GM-requested policy, is deterministic, and makes no content or scope decision. |
| III | Retrieval and Render are Separated | **PASS (not applicable)** | No retrieval call is added or moved. File selection happens before the existing render CLI; `tests/test_retrieve_render_isolation.py` must remain green. |
| IV | Verbatim is Sacred | **PASS** | Selection never edits quotes or labels. Existing voice-smoothed-content warnings remain active, and an unreadable preferred file is surfaced rather than replaced silently. |
| V | One Seam per Boundary | **PASS** | `session_doc/io.py` remains the single authority for eligible scene files and precedence. The router projects its result and invokes `sd_narrate`; the frontend only renders the projection. |
| VI | CLI is the Engine, UI is a Face | **PASS** | Exact-file consumption is implemented in `sd_narrate` first and reached through `_build_narrate_cmd()`. The router does not parse prompts or render narration. |
| VII | Extract Once, Synthesize Deliberately | **PASS** | No extraction is repeated and no new synthesis pass is added. Existing raw and derived smoothed files are consumed as-is. |
| VIII | State is Discoverable | **STRENGTHENED** | The UI shows the smoothed directory, presence state, active layer, exact file, fallback, and blocking error. The run's true input no longer lives in operator memory. |
| IX | The UI Mechanizes; Claude Converses | **PASS** | The UI exposes file state and invocation only. Smoothing and review remain external, file-backed human work. |
| X | Selection is Explicit; There is No Silent “All” | **PASS** | Narrate continues to act on the one scene the GM selected. Layer precedence never expands scene scope; a missing scene refuses rather than selecting another file. |
| XI | Parity is Bidirectional; Every CLI Capability Has a Face | **PASS** | The exact-file CLI capability ships with its UI invocation in this feature. Direct CLI users may use the same option; the UI does not gain a private rendering path. |
| XII | One Spelling per Option; No Configuration Drift | **PASS** | The one new spelling is `--scene-extraction-file`; it is owned by `sd_narrate`, forwarded unchanged by the router, and is not duplicated in stored config. Eligibility and precedence have one shared implementation. |
| XIII | Breaking State Changes Migrate Out of Band | **PASS (not applicable)** | No schema, filename convention, or workspace layout changes. The resolver only reads existing conventional directories and writes no config or source file. No migration is required. |

### Gate decisions

The design removes two apparent shortcuts because each fails a constitutional
gate:

- Passing the entire smoothed directory whenever it exists is rejected. A
  partial directory can make the CLI's positional fallback select the wrong
  item or no item, violating Principles I, II, and X.
- Recomputing the smoothed path in Vue is rejected. It would create a second
  source-selection authority and browser-only truth, violating Principles V,
  VIII, and IX.

No unresolved violation remains, so Phase 0 may proceed.

### Post-Design Re-Check

Re-evaluated after `research.md`, `data-model.md`, `contracts/`, and
`quickstart.md` were completed. No verdict changed.

- The API contract is additive: existing raw-editor fields keep their meaning,
  while `narrate_source` is a derived, non-persisted projection.
- The CLI contract keeps `--scene-extractions` intact and adds a guarded
  single-file override. Existing multi-scene and raw-only invocations are
  unchanged.
- The frontend never selects a layer. It renders the server projection,
  refreshes it before invocation, and lets the server re-resolve at the final
  command boundary.
- The exact-file flag is what makes partial and smoothed-only scenes compatible
  with Principle X: no list-position fallback can substitute a different
  scene.

**Complexity Tracking**: not required; every gate passes without a standing
violation.

## Project Structure

### Documentation (this feature)

```text
specs/018-prefer-smoothed-extractions/
├── plan.md                         # This implementation plan
├── spec.md                         # Feature specification
├── research.md                     # Phase 0 decisions
├── data-model.md                   # Derived source-state model
├── quickstart.md                   # End-to-end validation guide
├── contracts/
│   ├── cli.md                      # sd_narrate exact-file contract
│   └── editor-api.md               # additive editor response contract
├── checklists/
│   └── requirements.md             # Specification quality checklist
└── tasks.md                        # Created later by $speckit-tasks
```

### Source Code (repository root)

```text
session_doc/
├── io.py                           # shared eligibility, precedence, and
│                                   # per-directory scene-file resolution
└── sd_narrate.py                   # --scene-extraction-file validation and
                                    # exact selected-scene consumption

server/
└── routers/
    └── scene_editor.py             # smoothed-dir discovery; active-source
                                    # projection; command re-resolution

frontend/src/
├── views/session/
│   └── SessionDocEditor.vue        # source state; dirty tracking; preflight
└── components/scene-editor/
    └── ExtractionEditor.vue        # visible layer/path/status; independent
                                    # raw-edit and Narrate enablement

tests/
├── test_editor_pipeline.py         # resolver/command/API regressions
├── test_editor_service_integration.py # route projection and refresh behavior
├── test_sd_narrate.py              # exact-file CLI contract
└── test_smoothed_claim.py          # existing eligibility/warning regression

docs/cli/
└── session_doc_pipeline.md         # exact-file single-scene usage and UI
                                    # smoothed-preference handoff
```

**Structure Decision**: Preserve the existing web-plus-CLI layout. File
eligibility belongs in `session_doc/io.py`, execution belongs in
`session_doc/sd_narrate.py`, the FastAPI router chooses and exposes the input,
and the two existing Vue components display and invoke it. No new service,
configuration model, state store, or frontend test framework is introduced.

## Execution Model and Worktree

The user-mandated split is binding for `$speckit-tasks` and
`$speckit-implement`:

- **GPT-5.6 orchestrates**: creates/enters the worktree, decomposes tasks,
  assigns one bounded task at a time, reviews every diff, runs constitution
  gates, and owns final integration.
- **GPT-5.5 implements**: edits only the files named by the assigned task and
  returns the task's targeted test/build evidence. It does not broaden scope,
  change contracts, or waive a gate.

All implementation work must happen in:

`/home/kroussos/src/CampaignGenerator/worktrees/018-prefer-smoothed-extractions`

on branch `018-prefer-smoothed-extractions`, based on `main`. The primary
checkout is planning/orchestration only. Because the requested worktree root
is nested inside that checkout and `.gitignore` does not currently ignore it,
the GPT-5.6 setup gate must add `worktrees/` to the main repository's local
`.git/info/exclude` before creating the worktree. This is local hygiene, not a
tracked feature change. The worktree is created only after `tasks.md` exists
and the plan/task artifacts have been carried into the feature branch.

### Implementation phases and review gates

| Phase | GPT-5.5 implementation scope | GPT-5.6 gate |
|---|---|---|
| 0. Isolation | No code. Create requested worktree and record clean baseline. | Confirm `pwd`, branch, clean diff, baseline targeted pytest and frontend build. |
| 1. Shared file resolution + CLI | `session_doc/io.py`, `session_doc/sd_narrate.py`, focused CLI/I/O tests. | Review one-authority rule, exact-file validation, no source writes; targeted pytest and `--help` contract pass. |
| 2. Server source projection | `server/routers/scene_editor.py`, command/API tests. | Review smoothed path is `<session>/scene_extractions_smoothed`, raw stays fallback, unreadable blocks, non-Narrate builders have zero semantic diff. |
| 3. Frontend visibility/preflight | `SessionDocEditor.vue`, `ExtractionEditor.vue`. | Review browser never derives path/layer, raw Save stays explicit, smoothed-only scene can Narrate; `npm run build` passes. |
| 4. Integration and docs | Integration tests, quickstart execution, CLI docs. | Full pytest has no new failure versus baseline; frontend build passes; quickstart acceptance matrix passes. |
| 5. Final audit | No new implementation unless a gate finds a defect. | Re-run all thirteen constitution checks against the diff and confirm no migration/config change. |

Targeted tests accelerate a task but never close a phase by themselves. The
full suite and frontend build are mandatory final gates, with any pre-existing
baseline failures recorded before implementation so the feature may not add a
new one.
