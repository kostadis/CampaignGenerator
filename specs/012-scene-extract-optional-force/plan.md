# Implementation Plan: Optional Force for Scene Re-Extraction

**Branch**: `012-scene-extract-optional-force` | **Date**: 2026-08-16 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/012-scene-extract-optional-force/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

The Session Doc Editor's Stage 2 "Re-Extract Quotes" button always hardcodes
`?force=1`, so every click regenerates every scene — even ones already
extracted and reviewed — burning LLM calls and clearing reviewed markers
that shouldn't have been touched (issue #323). Research (see
`research.md` D1) found that every layer below the button — the FastAPI
route's `force: int = 0` default, `_build_reextract_cmd`'s conditional
`--force`, `run_scene_extraction`'s skip-if-exists loop, and the CLI's own
`--force` flag — already implements "default = skip existing, explicit
force = redo everything" correctly. The fix is therefore narrow: stop
hardcoding `force=1` in `SessionDocEditor.vue`, add a visible, unchecked-by-
default Force checkbox next to the button (mirroring the existing
`replace-toggle` pattern in `ConnectionGraph.vue`), and let its state decide
the query param per run.

## Technical Context

**Language/Version**: Python ≥3.9 (backend/CLI, per `pyproject.toml`); TypeScript + Vue 3.5 / Vite 8 (frontend)

**Primary Dependencies**: FastAPI (existing `/api/editor/extract` SSE route, unchanged); Vue 3 reactive `ref` + the existing `connectSSE` client helper — no new dependency

**Storage**: Filesystem only — per-scene `.md` files, `.prev` snapshots, and `.reviewed` markers under the session's `scene_extractions_dir`; on-disk semantics unchanged by this feature (see `data-model.md`)

**Testing**: pytest (`tests/test_editor_pipeline.py` and related) for the backend default and knob-recording behavior; the frontend has no automated test harness in this repo (no `*.test.*`/`*.spec.*` files, no `test` script in `frontend/package.json`), so per `CLAUDE.md`'s UI-change rule, verification is a manual dev-server pass through `quickstart.md`'s scenarios

**Target Platform**: Existing local FastAPI + Vue SPA (Session Doc Editor), served via `startup`

**Project Type**: Web application (existing `frontend/` + `server/` pair — Option 2 structure)

**Performance Goals**: N/A — the feature *reduces* LLM call volume for the common case; no new performance target

**Constraints**: Must not modify `campaignlib/scenes.py::run_scene_extraction` or `session_doc/scene_extract.py`'s force/skip-if-exists logic — both are already correct (Constitution VI, CLI is the Engine). The fix changes only what value the UI sends for the already-optional `force` parameter, never the engine's own decision logic.

**Scale/Scope**: One frontend call site (`SessionDocEditor.vue:473`, `runExtract()`) plus one new checkbox control and its backing reactive ref; zero required changes to `server/routers/scene_editor.py`'s command-building or execution logic (its `force` param and knob recording are already correct — see `research.md` D1/D3); one backend test addition to pin the default-off path, which today has no coverage (`research.md` D5).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Verdict |
|---|---|---|
| I. Disk is Truth, the Model is a Draft | No change to what's on disk vs. what's a draft; per-scene files remain the truth, LLM output remains a draft until reviewed | PASS |
| II. The Human Checkpoint is Non-Negotiable | Force is a per-run, explicit human toggle (not inferred, not automatic); no LLM output feeds another LLM call as a result of this feature | PASS |
| III. Retrieval and Render are Separated | Not touched — no retrieval call is introduced or modified | PASS |
| IV. Verbatim is Sacred | Not touched — no change to how quotes are extracted or rendered, only to which scenes a run is allowed to touch | PASS |
| V. One Seam per Boundary | Not touched — no new external dependency; the Anthropic API is still reached only via `campaignlib` | PASS |
| VI. CLI is the Engine, UI is a Face | Central to this fix: the skip/force decision logic already lives in `campaignlib/scenes.py` and `scene_extract.py`; this feature explicitly avoids adding a second implementation in the router or frontend — it only changes which existing, already-correct value the UI forwards | PASS |
| VII. Extract Once, Synthesize Deliberately | Not touched — no change to extraction pass structure or count per scene | PASS |
| VIII. State is Discoverable | Improves this: the existing per-scene skip/generate stream lines and the `knobs.force` record become meaningful (today they're always the force-path text and always `true`) | PASS (improves) |
| IX. The UI Mechanizes; Claude Converses | The Force checkbox mechanizes an existing CLI capability (`--force`); no new judgment is delegated to the UI — the GM still reviews per-scene output before marking anything reviewed | PASS |
| X. Selection is Explicit; There is No Silent "All" | This is the principle the fix directly restores: default becomes the narrow, explicit-safe scope (skip-existing); "regenerate everything" requires a visible, non-persisted, explicit toggle — never a default | PASS (restores) |

No violations. Complexity Tracking is not needed.

**Post-Phase-1 re-check**: `research.md`, `data-model.md`, and
`contracts/extract-endpoint.md` confirm the design adds no new engine logic,
no new persisted data, and no new external dependency — the table above
holds unchanged after design.

## Project Structure

### Documentation (this feature)

```text
specs/012-scene-extract-optional-force/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/
│   └── extract-endpoint.md  # Phase 1 output — fixes the `force` contract of the existing route
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
frontend/src/views/session/SessionDocEditor.vue   # runExtract() — remove the hardcoded
                                                   # `?force=1`; add a `forceReextract` ref and a
                                                   # checkbox control next to the Re-Extract Quotes
                                                   # button (pattern: frontend/src/views/prep/
                                                   # ConnectionGraph.vue's `replace-toggle`)

server/routers/scene_editor.py                    # api_extract() / _build_reextract_cmd() — already
                                                   # correct (force: int = 0 default, conditional
                                                   # --force, knobs.force recording); touched only if
                                                   # the new test in tests/test_editor_pipeline.py
                                                   # surfaces a gap

campaignlib/scenes.py                             # run_scene_extraction() — already correct
                                                   # skip-if-exists / force / snapshot / clear-marker
                                                   # logic; NOT modified by this feature

session_doc/scene_extract.py                      # --force CLI flag and its own skip-if-exists
                                                   # default; already correct; NOT modified

tests/test_editor_pipeline.py                     # add coverage for the default-off (`force=0`)
                                                   # path through api_extract / _build_reextract_cmd,
                                                   # which today has no pinning test (research.md D5)
```

**Structure Decision**: Existing web application layout (`frontend/` + `server/` + root-level
`campaignlib/`/`session_doc/` CLI code), unchanged by this feature. This is a
single-repo fix confined to one Vue view and one pytest file; no new
directories, services, or project-structure options are introduced.

## Complexity Tracking

*No Constitution Check violations — table not applicable.*
