---

description: "Dependency-ordered implementation tasks for smoothed-first narration input"
---

# Tasks: Prefer Smoothed Scene Extractions for Narration

**Input**: Design documents from `/specs/018-prefer-smoothed-extractions/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/cli.md`, `contracts/editor-api.md`, and `quickstart.md`

**Tests**: Required. The specification defines independent acceptance tests and measurable 100% source-selection outcomes. Backend behavior is covered with pytest; frontend behavior is gated by `npm run build` plus the manual scenarios in `quickstart.md` because the repository has no frontend test runner.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated as an increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Safe ordering freedom because the task touches different files and has no incomplete dependency. The GPT-5.6 orchestrator still dispatches one bounded GPT-5.5 implementation task at a time.
- **[Story]**: Maps the task to User Story 1, 2, or 3 from `spec.md`.
- Every task names its exact file path or validation artifact.

## Execution Ownership and Isolation

- **GPT-5.6 orchestrates** setup, task dispatch, diff review, targeted gates, full integration, and the final constitution audit.
- **GPT-5.5 implements** every bounded test, source, frontend, and documentation task and returns its focused test/build evidence to GPT-5.6.
- All implementation and validation after Phase 1 run from `/home/kroussos/src/CampaignGenerator/worktrees/018-prefer-smoothed-extractions` on branch `018-prefer-smoothed-extractions`.
- The primary checkout `/home/kroussos/src/CampaignGenerator` remains planning/orchestration-only.
- GPT-5.5 may edit only the files named by its current task. Contract changes or scope expansion return to GPT-5.6 for a planning decision.

## Phase 1: Setup (Worktree Isolation and Baseline)

**Purpose**: Create the user-mandated isolated implementation environment and record the pre-change quality baseline.

- [X] T001 GPT-5.6 add one `worktrees/` entry, if absent, to `/home/kroussos/src/CampaignGenerator/.git/info/exclude` and verify `/home/kroussos/src/CampaignGenerator/worktrees/` is locally ignored without changing tracked `.gitignore` files.
- [X] T002 GPT-5.6 create or attach branch `018-prefer-smoothed-extractions` from `main` at `/home/kroussos/src/CampaignGenerator/worktrees/018-prefer-smoothed-extractions`, carry `/home/kroussos/src/CampaignGenerator/specs/018-prefer-smoothed-extractions/` and `/home/kroussos/src/CampaignGenerator/.specify/feature.json` into the worktree, then verify the exact `pwd`, branch, and status before dispatching GPT-5.5.
- [X] T003 GPT-5.6 run the pre-edit focused pytest set, full `tests/` suite, and `frontend/package.json` build command from `/home/kroussos/src/CampaignGenerator/worktrees/018-prefer-smoothed-extractions`, recording command outcomes and every pre-existing failing test in `specs/018-prefer-smoothed-extractions/validation-results.md`.

**Checkpoint**: The feature artifacts and active feature pointer exist inside the isolated worktree, and baseline failures are documented before any source edit.

---

## Phase 2: Foundational (Blocking Source Authority and Contracts)

**Purpose**: Establish the single file-resolution authority, guarded CLI exact-file input, and server-owned source projection required by every story.

**CRITICAL**: No user-story implementation begins until this phase passes its GPT-5.6 gate.

### Foundational tests (write first and confirm they fail)

- [X] T004 [P] GPT-5.5 add failing tests for one-scene resolution by exact identity and `NN_` prefix, ignored sibling artifacts, and scaffold-over-plain precedence in `tests/test_editor_pipeline.py`.
- [X] T005 [P] GPT-5.5 add failing parser/help and pre-model validation tests for the sole `--scene-extraction-file FILE` spelling, exactly one `--scene N`, eligible readable UTF-8 input, and scene association in `tests/test_sd_narrate.py`.
- [X] T006 [P] GPT-5.5 add failing editor-detail contract tests for the smoothed-first, raw-fallback, unreadable, and missing `narrate_source` states while preserving raw `exists` and `content` semantics in `tests/test_editor_service_integration.py`.

### Foundational implementation

- [X] T007 GPT-5.5 add a reusable per-directory scene resolver beside `scene_extraction_files()` in `session_doc/io.py` that delegates eligibility and scaffold shadowing to the existing authority, matches exact scene identity when available, then safely matches the selected two-digit `NN_` prefix.
- [X] T008 GPT-5.5 refactor `_scene_extraction_file_new()` in `server/routers/scene_editor.py` to delegate raw editor lookup to the shared resolver in `session_doc/io.py` without changing raw Save, Reload, Diff, reviewed-marker, or non-Narrate behavior.
- [X] T009 GPT-5.5 implement `--scene-extraction-file FILE` in `session_doc/sd_narrate.py`, keeping `--scene-extractions DIR` required, validating the exact file before a model call, using it for the sole selected scene and source-knowledge checks without duplication, and leaving invocations without the option unchanged.
- [X] T010 GPT-5.5 implement request-scoped `SceneSourceCandidate` and `NarrateSourceState` resolution in `server/routers/scene_editor.py`, discovering only `<current session_dir>/scene_extractions_smoothed`, retaining the configured raw directory as fallback, probing UTF-8 readability, and adding the projection to `api_get_extraction()` while its existing raw fields remain unchanged.
- [X] T011 GPT-5.6 review `session_doc/io.py`, `session_doc/sd_narrate.py`, and `server/routers/scene_editor.py` for one-authority/read-only behavior, then run the T004-T006 tests and verify the help text once in `specs/018-prefer-smoothed-extractions/validation-results.md`.

**Checkpoint**: Shared resolution, the CLI exact-file contract, and an additive server projection exist and pass focused tests; user-story work may start.

---

## Phase 3: User Story 1 — Narrate from the Smoothed Voice Layer (Priority: P1) MVP

**Goal**: A UI Narrate action consumes the selected scene's exact smoothed extraction when present, including a file created after the page opened, without mutating raw or smoothed source files.

**Independent Test**: Put distinguishable raw and smoothed content for one scene on disk, open the editor before or after creating the smoothed file, invoke Narrate, and prove the exact server-projected smoothed path supplied the rendered prompt while both sources remain unchanged.

### Tests for User Story 1 (write first and confirm they fail)

- [X] T012 [P] [US1] GPT-5.5 add failing `_build_narrate_cmd()` tests for both-layer preference, raw-directory plus exact-smoothed argument shape, smoothed-only base-directory behavior, and a smoothed file created after initial detail load in `tests/test_editor_pipeline.py`.
- [X] T013 [P] [US1] GPT-5.5 add a failing CLI execution test proving distinguishable exact-file content reaches the selected scene prompt exactly once and neither input file is rewritten in `tests/test_sd_narrate.py`.
- [X] T014 [P] [US1] GPT-5.5 add a failing API-to-Narrate integration test proving the exact `narrate_source.active_file` returned for a scene is forwarded by the subsequent Narrate SSE command in `tests/test_editor_service_integration.py`.

### Implementation for User Story 1

- [X] T015 [US1] GPT-5.5 update `_build_narrate_cmd()` and `api_narrate()` in `server/routers/scene_editor.py` to re-resolve disk at invocation, pass `--scene-extraction-file` only for a ready smoothed source, preserve the existing raw command shape for raw fallback, use the smoothed parent when the raw directory is absent, and refuse missing/unreadable state before launching the subprocess.
- [X] T016 [US1] GPT-5.5 add typed `narrate_source` state, raw-buffer dirty tracking, detail-response hydration, and the pre-Narrate refresh/conditional-raw-save flow in `frontend/src/views/session/SessionDocEditor.vue`, ensuring smoothed-active or blocked runs never auto-save raw and the server remains the selection authority.
- [X] T017 [US1] GPT-5.5 pass source availability separately from raw `hasExtraction` and enable Narrate for a ready smoothed-only scene while keeping Save, Edit, Reload, Diff, and Reviewed raw-controlled in `frontend/src/components/scene-editor/ExtractionEditor.vue` and `frontend/src/views/session/SessionDocEditor.vue`.
- [X] T018 [US1] GPT-5.6 run the US1 pytest set and `frontend/package.json` build, execute `quickstart.md` sections 3 and 5 with distinguishable/live-added input, and append the exact displayed path, command path, and unchanged-source evidence to `specs/018-prefer-smoothed-extractions/validation-results.md`.

**Checkpoint**: User Story 1 works end to end as the MVP: smoothed content is the true input and live creation requires no page reload or configuration change.

---

## Phase 4: User Story 2 — See the Source Narrate Will Use (Priority: P1)

**Goal**: Before Narrate, the UI shows the expected smoothed directory, its presence, the active layer/status, and the exact active file or blocking reason, refreshed from server-owned disk state.

**Independent Test**: View one scene without and then with a smoothed file; verify the same UI changes from Raw fallback to Smoothed, always shows the resolved smoothed directory, and refreshes after the on-disk change.

### Tests for User Story 2 (write first and confirm they fail)

- [X] T019 [US2] GPT-5.5 extend `tests/test_editor_service_integration.py` with failing assertions for every `contracts/editor-api.md` candidate and active field, the fixed smoothed directory even when absent, a custom configured raw directory, unchanged top-level raw editor fields, and refreshed projection after add/remove/rename disk events.

### Implementation for User Story 2

- [X] T020 [P] [US2] GPT-5.5 thread the complete server-returned `narrate_source` projection through scene selection, Reload, post-extraction refresh, and pre-Narrate refresh without deriving paths or layers in `frontend/src/views/session/SessionDocEditor.vue`.
- [X] T021 [P] [US2] GPT-5.5 render the expected smoothed directory with present/not-present state plus the Smoothed, Raw fallback, Missing, or Smoothed unreadable label, exact ready path, and server message in `frontend/src/components/scene-editor/ExtractionEditor.vue`.
- [X] T022 [US2] GPT-5.5 add source-banner styling that preserves usable narrow layouts and exposes full paths without hiding status in `frontend/src/components/scene-editor/ExtractionEditor.vue`.
- [X] T023 [US2] GPT-5.6 run the editor API tests and `frontend/package.json` build, manually validate `quickstart.md` sections 2, 3, and 5, and append absent/present/changed source-display evidence to `specs/018-prefer-smoothed-extractions/validation-results.md`.

**Checkpoint**: User Story 2 is independently demonstrable: the GM can identify the expected smoothed location and exact next Narrate source before spending tokens.

---

## Phase 5: User Story 3 — Continue Safely with Partial or Absent Smoothing (Priority: P2)

**Goal**: Source selection remains per scene for partial/raw-only sessions, supports smoothed-only scenes, and refuses unusable or entirely missing input without substituting another scene.

**Independent Test**: With raw scenes 1–3 and smoothed scenes 1 and 3 only, prove scenes 1/3 use their exact smoothed files and scene 2 uses raw; separately prove smoothed-only succeeds, unreadable smoothed blocks, and neither-source names both checked locations.

### Tests for User Story 3 (write first and confirm they fail)

- [X] T024 [P] [US3] GPT-5.5 add failing resolver/command tests for an empty or artifact-only smoothed directory, partial scenes 1/3, differing slugs, scaffold shadowing, custom raw location, unreadable preferred input, and neither-source messages in `tests/test_editor_pipeline.py`.
- [X] T025 [P] [US3] GPT-5.5 add failing CLI tests for partial-directory exact selection plus nonexistent, non-file, invalid UTF-8, ineligible, mismatched-scene, missing-`--scene`, and multi-`--scene` exact-file refusals before the model call in `tests/test_sd_narrate.py`.
- [X] T026 [P] [US3] GPT-5.5 add failing route/integration tests for raw-only compatibility, smoothed-only enablement, per-scene fallback, unreadable-smoothed blocking with raw present, neither-source messaging, and live removal fallback in `tests/test_editor_service_integration.py`.

### Implementation for User Story 3

- [X] T027 [US3] GPT-5.5 harden the candidate/state transitions and user-facing errors in `server/routers/scene_editor.py` so ignored artifacts never activate smoothing, present-but-unreadable smoothed never falls back, missing state names both directories, and no compact-list position can select another scene.
- [X] T028 [US3] GPT-5.5 complete smoothed-only, raw-fallback, unreadable, and missing UI behavior in `frontend/src/views/session/SessionDocEditor.vue` and `frontend/src/components/scene-editor/ExtractionEditor.vue`, keeping Narrate availability independent from raw editing and preserving a dirty raw buffer when smoothed is active.
- [X] T029 [US3] GPT-5.6 run the US3 pytest set and `frontend/package.json` build, execute `quickstart.md` sections 4, 6, and 7 against disposable files, and append per-scene input, refusal text, dirty-buffer, and no-source-write evidence to `specs/018-prefer-smoothed-extractions/validation-results.md`.

**Checkpoint**: All three stories are functional; incremental smoothing is safe and raw-only behavior remains compatible.

---

## Phase 6: Polish and Cross-Cutting Regression Gates

**Purpose**: Document the operator contract, prove Narrate-only scope, run the complete acceptance matrix, and perform the final GPT-5.6 audit.

- [X] T030 [P] GPT-5.5 document the single-scene `--scene-extraction-file` usage, validation rules, smoothed-first UI handoff, raw fallback, and blocked states in `docs/cli/session_doc_pipeline.md`.
- [X] T031 [P] GPT-5.5 add explicit regression coverage that extraction, Verify Quotes, Plan & Check, consistency, reviewed markers, raw editor routes, and `PUT /api/editor/extraction/{n}` remain raw-configured and never receive `--scene-extraction-file` in `tests/test_editor_pipeline.py` and `tests/test_editor_verify_routes.py`.
- [X] T032 GPT-5.6 run `tests/test_smoothed_claim.py`, `tests/test_retrieve_render_isolation.py`, `tests/test_editor_pipeline.py`, `tests/test_editor_verify_routes.py`, `tests/test_sd_narrate.py`, and `tests/test_editor_service_integration.py`, recording the targeted regression result in `specs/018-prefer-smoothed-extractions/validation-results.md`.
- [X] T033 GPT-5.6 run the full `tests/` suite, the build defined by `frontend/package.json`, and `git diff --check` from `/home/kroussos/src/CampaignGenerator/worktrees/018-prefer-smoothed-extractions`, compare failures with the T003 baseline, and record final outcomes in `specs/018-prefer-smoothed-extractions/validation-results.md`.
- [X] T034 GPT-5.6 execute the complete `specs/018-prefer-smoothed-extractions/quickstart.md` matrix, including source byte/mtime checks and the non-Narrate boundary, and record every scenario as pass/fail with evidence in `specs/018-prefer-smoothed-extractions/validation-results.md`.
- [X] T035 GPT-5.6 review the complete worktree diff against all thirteen constitution principles in `specs/018-prefer-smoothed-extractions/plan.md`, verify no persisted config, schema, migration, source-copy, or non-Narrate policy change exists, and write the final audit verdict in `specs/018-prefer-smoothed-extractions/validation-results.md`.

**Checkpoint**: The full suite and frontend build add no failure versus baseline, the acceptance matrix passes, documentation matches the code, and the final constitution audit is recorded.

---

## Dependencies and Execution Order

### Phase dependencies

- **Phase 1 — Setup**: Starts immediately; T001 precedes T002, and T002 precedes T003.
- **Phase 2 — Foundational**: Depends on T003 and blocks all stories. T004-T006 are the failing contract tests; T007 enables T008-T010; T009 also depends on T005 and T007; T010 depends on T006-T008; T011 closes the phase.
- **Phase 3 — US1**: Depends on T011. T012-T014 precede implementation; T015 precedes T016-T017; T018 closes the story.
- **Phase 4 — US2**: Depends on T011 and reuses the foundational projection. T019 precedes T020-T022; T023 closes the story. If delivered after US1, it also validates the exact displayed/executed handoff already wired there.
- **Phase 5 — US3**: Depends on T011. T024-T026 precede T027-T028; T029 closes the story. It may be implemented after US1/US2 for the safest incremental rollout, although its server edge cases are independently testable.
- **Phase 6 — Polish**: Depends on every story selected for release. T030 and T031 precede T032-T034; T035 is the final gate.

### User-story dependency graph

```text
Setup (T001-T003)
        |
Foundation (T004-T011)
   _____|_____________
  |         |         |
US1       US2       US3
MVP       visible   resilient
  |_________|_________|
            |
     Final gates (T030-T035)
```

- **US1 (P1)**: No dependency on another story after Foundation; it proves exact smoothed consumption.
- **US2 (P1)**: No dependency on another story after Foundation; it proves source visibility from the additive projection.
- **US3 (P2)**: No dependency on another story after Foundation; it proves safe partial, absent, smoothed-only, and blocked states.
- For the recommended single-implementer flow, execute US1 → US2 → US3 so each checkpoint expands a working vertical slice.

### Parallel opportunities

- T004, T005, and T006 are independent failing-test tasks in three different test files.
- T012, T013, and T014 are independent US1 tests in command-builder, CLI, and integration layers.
- T020 and T021 have independent file ownership once their prop/state contract from `contracts/editor-api.md` is fixed.
- T024, T025, and T026 are independent US3 edge-case tests in three different test files.
- T030 and T031 are independent documentation and regression-test tasks.
- `[P]` marks ordering freedom, not permission to bypass the requested GPT-5.6 review between bounded GPT-5.5 assignments.

## Parallel Example: User Story 1

```text
Task T012: Add command-builder tests in tests/test_editor_pipeline.py
Task T013: Add exact-content CLI test in tests/test_sd_narrate.py
Task T014: Add API-to-command integration test in tests/test_editor_service_integration.py
```

These may be prepared independently, but GPT-5.6 reviews each returned diff and failing-test evidence before dispatching the next bounded GPT-5.5 task.

## Implementation Strategy

### MVP first — User Story 1

1. Complete isolated Setup and record the baseline.
2. Complete and gate the shared Foundation.
3. Implement US1 tests before code.
4. Complete T015-T017 and close T018.
5. Stop and demonstrate that the displayed exact smoothed path is the consumed path, including live file creation.

### Incremental delivery

1. **Foundation**: One authority resolves eligible scene files; CLI and API contracts exist.
2. **US1 MVP**: Narrate consumes smoothed input from the UI.
3. **US2**: The GM can inspect the source handoff before the run.
4. **US3**: Partial, absent, smoothed-only, unreadable, and missing states are fully safe.
5. **Final gates**: Documentation, complete acceptance matrix, full tests/build, and constitution audit.

## Notes

- Tests in every phase are written first and observed failing before implementation.
- Source selection is always recomputed from disk; the browser never submits or derives a chosen path.
- `scene_extractions_smoothed` is fixed beside the current session and is never derived from the configured raw directory name.
- A present but unreadable smoothed file blocks; only absence permits raw fallback.
- `PUT /api/editor/extraction/{n}` remains raw-only, and source discovery/Narrate does not mutate either source layer.
- `--scene-extraction-file` is confined to the `sd_narrate` parser and Narrate command-builder path.
- Commit after each reviewed task or small logical group; do not mix unrelated user changes into feature commits.
