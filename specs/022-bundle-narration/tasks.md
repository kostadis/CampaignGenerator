---

description: "Dependency-ordered implementation tasks for bundled narration generation"
---

# Tasks: Bundled Narration Generation

**Input**: Design documents from `specs/022-bundle-narration/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: The specification defines independent tests and measurable acceptance scenarios, so each story includes tests written before its implementation.

**Organization**: Tasks are grouped by user story so the CLI engine, editor face, quality safeguards, and recovery behavior can be implemented and validated as distinct increments.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel after its stated prerequisites because it targets different files and does not depend on another incomplete task in the same group.
- **[Story]**: Maps the task to the corresponding user story in [spec.md](./spec.md).
- Every task names the exact file or directory it changes.

## Phase 1: Setup (Shared Test Inputs)

**Purpose**: Establish one deterministic corpus shared by protocol, CLI, server, and UI tests.

- [X] T001 Create reviewed multi-scene plan, raw/smoothed extraction, narrator guidance, complete response, partial response, and malformed response fixtures in `tests/fixtures/narration_bundle/`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build and lock down the shared prompt, protocol, output, report, and configuration primitives required by every story.

**⚠️ CRITICAL**: No user story implementation begins until this phase passes.

### Foundational tests

- [X] T002 [P] Write failing raw-marker and sentinel reconciliation tests for complete, empty, incomplete, absent, duplicate-name, unknown-index, duplicate-index, nested, stray-END, mismatched-BEGIN/END, name-mismatch, continuation-seam, and raw out-of-order responses in `tests/test_narration_bundle_split.py`
- [X] T003 [P] Write failing shared filename/frontmatter/atomic-write and version-1 run-report serialization tests covering run IDs, `base|override` source provenance, zero-write partials, refusals, and backend failures in `tests/test_narration_bundle_report.py`
- [X] T004 [P] Write failing default, round-trip, and legacy-config compatibility tests for `narrate.batch_tokens` in `tests/test_session_editor_config_service.py`

### Foundational implementation

- [X] T005 Implement `NarrationScene`, `BundleSelection`, parsed section states, and a raw-marker preflight for matching END identity and encounter order before calling `campaignlib.scenes.split_batched_response` in `session_doc/narrate.py`
- [X] T006 [P] Add bundle-wide rules/continuity and indexed per-scene packet templates in `config/agents/session_doc/narrate/bundle_base.md` and `config/agents/session_doc/narrate/bundle_scene.md`
- [X] T007 Implement shared-context-once and narrator-scoped bundle prompt builders using the new templates in `session_doc/narrate.py`
- [X] T008 Add the independently defaulted `batch_tokens: int = 32000` field and validation to `NarrateKnobs` in `server/session_editor_config_shared.py`
- [X] T009 Extract one shared narration path/frontmatter formatter, atomic writer, and atomic `NarrationBundleRunReport` serializer/finalizer that derives explicit-path `run_id` from the filename stem, records `base|override` source provenance, and covers success, partial, unreconcilable, refusal, and backend-failure paths in `session_doc/sd_narrate.py`

**Checkpoint**: Protocol, prompt construction, output formatting, run-report serialization, and config defaults pass without invoking a model.

---

## Phase 3: User Story 1 — Generate a full narration set in one exchange from the CLI (Priority: P1) 🎯 MVP

**Goal**: An operator explicitly bundles all or selected reviewed plan scenes into one model exchange and receives the normal per-scene files.

**Independent Test**: Run the same multi-scene fixture sequentially and with `--batch-scenes`; bundled mode makes exactly one backend call, reports the explicit ordered scope, and writes the complete expected per-scene file set.

### Tests for User Story 1

- [X] T010 [P] [US1] Write failing CLI tests for `--batch-scenes`, `--no-batch-scenes`, `--batch-max-tokens`, full-plan/subset selection, plan-order normalization, duplicate/range refusals, bundled `--narrator` refusal with unchanged sequential narrator filtering, replacement display, repeated exact-source overrides with `base|override` report provenance, zero-call capacity refusal, and atomic refusal/failure reports in `tests/test_narration_bundle_cli.py`
- [X] T011 [P] [US1] Write failing call-matrix and input-delivery tests proving N sequential live calls, N sequential provider-batch items, one bundled live call, and one bundled provider-batch item in `tests/test_narrate_input_delivery.py`

### Implementation for User Story 1

- [X] T012 [US1] Add the bundled CLI options, retain the existing sequential defaults, and generalize `--scene-extraction-file` to validated repeatable bundle overrides in `session_doc/sd_narrate.py`
- [X] T013 [US1] Preflight every selected scene, refuse bundled `--narrator`, normalize subsets to full-plan order, project the total output, refuse oversized bundles before client creation, print the exact source/destination/replacement scope, and finalize an atomic refusal report in `session_doc/sd_narrate.py`
- [X] T014 [US1] Dispatch one bundled `stream_api` call, reconcile the response, atomically write complete sections through the shared writer, catch backend failures, and finalize success/unreconcilable/failed reports and exit states in `session_doc/sd_narrate.py`
- [X] T015 [US1] Compose bundled content with one `run_single_batch` item when provider `--batch` is active and persist both mode states, exchange count, run ID, requested/source set, and written outputs in the JSON report in `session_doc/sd_narrate.py`
- [X] T016 [US1] Document the CLI option matrix, explicit selection, ceiling refusal, source overrides, exit codes, and provider-batch distinction in `docs/cli/session_doc_pipeline.md` and `docs/cli/cli_tools.md`

**Checkpoint**: User Story 1 works from the CLI with one exchange and ordinary reviewable files; omitting `--batch-scenes` retains the current path.

---

## Phase 4: User Story 2 — Generate all narration in one exchange from the editor (Priority: P1)

**Goal**: The Session Doc Editor displays an exact all-scene/replacement scope and invokes the same bundled CLI through the existing streamed subprocess boundary.

**Independent Test**: Open a ready fixture session, review the bundle dialog, start it, confirm the streamed command contains every explicit scene index and preferred source, and observe all affected scene states refresh after one exchange.

### Tests for User Story 2

- [X] T017 [P] [US2] Write failing command-builder tests for explicit indices, bundle ceiling, provider-batch composition, unique nonce-scoped report path, and mixed raw/smoothed repeated source overrides in `tests/test_editor_pipeline.py`
- [X] T018 [P] [US2] Write failing SSE route tests for absent/duplicate/out-of-range selection refusal, full-set preflight, copyable command emission, nonce/run-ID/selection/return-code report validation, concurrent identical selections, report-derived custom `done` payloads, knob sidecars, and activity metadata in `tests/test_editor_service_integration.py`
- [X] T019 [P] [US2] Add mocked scene-list, bundle-report, command, success, cancellation, and replacement-scope fixtures plus failing browser scenarios in `frontend/e2e/fixtures/sessionNarrationBundle.ts` and `frontend/e2e/session-narration-bundle.spec.ts`

### Implementation for User Story 2

- [X] T020 [US2] Extract shared narration argv construction, generate a unique per-request report nonce/path, and add `_build_narrate_bundle_cmd` plus the explicit `GET /api/editor/narrate-bundle?scene=...` SSE route in `server/routers/scene_editor.py`
- [X] T021 [US2] Wrap `stream_subprocess(..., emit_done=False)`, validate the exact report's version/run ID/selection/return code, write knob sidecars only for report-written scenes, append bundle metadata to `.cg/activity.jsonl`, and then emit a report-derived route-specific terminal `done` payload in `server/routers/scene_editor.py`
- [X] T022 [P] [US2] Build the ordered scene/count/narrator/new-or-replace confirmation surface in `frontend/src/components/scene-editor/NarrationBundleDialog.vue`
- [X] T023 [P] [US2] Retain the current-scene button and add a clearly separate bundle action event in `frontend/src/components/scene-editor/ExtractionEditor.vue`
- [X] T024 [US2] Integrate `narrate.batch_tokens` load/save and drawer binding, dialog state, dirty-raw save-before-run, explicit repeated scene query parameters, SSE progress, report-derived terminal K/N/missing status, and full scene/pipeline reload in `frontend/src/views/session/SessionDocEditor.vue`
- [X] T025 [P] [US2] Add the bundled narration ceiling control and distinguish content bundling from provider Message Batches in `frontend/src/components/scene-editor/KnobDrawer.vue`

**Checkpoint**: User Story 2 reproduces the CLI command visibly, never treats an absent selection as all, and leaves the current-scene action available.

---

## Phase 5: User Story 3 — Preserve narration quality, ordering, and review boundaries (Priority: P2)

**Goal**: Bundling sends shared material once while preserving per-scene narrator guidance, verbatim rules, plan order, continuity, exact attribution, and the human gate before assembly.

**Independent Test**: Compare bundled and sequential outputs for the same reviewed session, verify each file against its plan/source/narrator, inspect adjacent transitions and tail-scene completeness, and confirm nothing is approved or assembled automatically.

### Tests for User Story 3

- [X] T026 [P] [US3] Write failing template contract tests for all load-bearing first-person, verbatim, prose-mode, scene-boundary, narrator-scope, marker, and within-response continuity instructions in `tests/test_narrate_template_contract.py`
- [X] T027 [P] [US3] Write failing prompt-delivery tests proving shared party/roster/NPC/genre/history blocks occur once and each voice/example/source block occurs only in its assigned indexed scene packet in `tests/test_narrate_input_delivery.py`
- [X] T028 [P] [US3] Write failing guardrail tests proving bundle generation stays behind the existing model seam, performs no retrieval, writes no protocol markers, and never invokes approval or assembly in `tests/test_backend_seam_guardrails.py` and `tests/test_narration_wiki_renderer_isolation.py`

### Implementation for User Story 3

- [X] T029 [US3] Harden bundle templates and builders for narrator-specific isolation, scene-local grounding, prior-section prose handoff, trailing audit-comment exclusion, and shared-context deduplication in `config/agents/session_doc/narrate/bundle_base.md`, `config/agents/session_doc/narrate/bundle_scene.md`, and `session_doc/narrate.py`
- [X] T030 [US3] Enforce exact plan-order reconciliation, strip transport markers, and run per-scene unknown-name warnings before atomic writes in `session_doc/narrate.py` and `session_doc/sd_narrate.py`
- [X] T031 [US3] Run the representative sequential-versus-bundled quality gate from `quickstart.md` and record file-shape, attribution, quote, voice, continuity, and tail-completeness evidence in `specs/022-bundle-narration/validation.md`

**Checkpoint**: User Story 3 passes structural tests and recorded human review; any attribution, quote, voice-flattening, continuity, or tail-compression regression blocks release.

---

## Phase 6: User Story 4 — Keep single-scene and sequential recovery available (Priority: P2)

**Goal**: Existing narration modes remain stable, and a short bundled response retains complete work while letting the operator rerun only affected scenes.

**Independent Test**: Feed a response with K complete scenes and an incomplete tail, verify exactly K new files survive, then regenerate one missing scene through the unchanged current-scene path without touching other files.

### Tests for User Story 4

- [X] T032 [P] [US4] Expand sequential regression tests for no-flag defaults, generated-tail handoff threading, per-scene/provider-batch call counts, exact-source single-scene use, filenames/frontmatter, and individual reruns in `tests/test_sd_narrate.py`
- [X] T033 [P] [US4] Write failing bundle recovery tests for empty/incomplete/absent sections, K-of-N and structurally valid zero-of-N writes, preservation of pre-existing missing-scene files, exit `3`, missing-scene report data, and smaller-scope reruns in `tests/test_narration_bundle_cli.py`
- [X] T034 [P] [US4] Write failing server/browser tests for report-derived partial K/N and missing names, zero-write partial and unreconcilable status copy, report-derived sidecars, full scene refresh, and current-scene recovery in `tests/test_editor_service_integration.py` and `frontend/e2e/session-narration-bundle.spec.ts`

### Implementation for User Story 4

- [X] T035 [US4] Add partial-response exit `3` for every structurally valid shortfall including zero writes, preserve complete sections and all non-returned existing files, name recovery indices, and keep the sequential loop isolated from bundle branches in `session_doc/sd_narrate.py`
- [X] T036 [US4] Map report-derived exits `3` and `4` to distinct editor outcomes with K/N and missing names, apply sidecars/activity only to report-written files, and keep the bundle dialog/current-scene recovery available after refresh in `server/routers/scene_editor.py` and `frontend/src/views/session/SessionDocEditor.vue`
- [X] T037 [US4] Audit the current-scene route and toolbar integration after shared refactors, correcting any behavior drift while retaining `/api/editor/narrate/{n}` and its one-scene contract in `server/routers/scene_editor.py` and `frontend/src/components/scene-editor/ExtractionEditor.vue`

**Checkpoint**: User Story 4 proves both legacy modes and targeted recovery remain usable after bundled generation.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Align documentation, structural guards, and final validation across the completed stories.

- [X] T038 [P] Update editor and system documentation for the all-scenes dialog, one-exchange flow, partial recovery, unchanged review gate, and provider-batch distinction in `docs/web/session_doc_editor.md`, `docs/web/web_ui.md`, and `docs/system/flow-post-session.md`
- [X] T039 [P] Update narration reachability and structural expectations for the new route/templates without weakening existing isolation assertions in `tests/test_backend_seam_guardrails.py`, `tests/test_retrieve_render_isolation.py`, `tests/test_no_prefix_identity.py`, and `tests/test_layering.py`
- [X] T040 Run the focused pytest, structural pytest, frontend build, Playwright bundle scenario, and full pytest commands from `specs/022-bundle-narration/quickstart.md`, recording exact commands and outcomes in `specs/022-bundle-narration/validation.md`
- [X] T041 Perform the final FR-001–FR-021, SC-001–SC-009, four-story, and post-design constitution audit and record any residual limitations or follow-up issues in `specs/022-bundle-narration/validation.md`

---

## Dependencies & Execution Order

### Phase Dependencies

```text
Phase 1 Setup
    ↓
Phase 2 Foundation
    ↓
US1 CLI MVP
    ├──────────────► US2 Editor parity
    ├──────────────► US3 Quality/review safeguards
    └──────────────► US4 CLI recovery
                         ▲
US2 Editor parity ───────┘  (editor recovery portion)
    ↓
Polish + final validation (after all selected stories)
```

- **Phase 1** has no dependencies.
- **Phase 2** depends on T001 and blocks every user story.
- **US1** depends on all foundational tasks and is the runnable MVP.
- **US2** depends on US1 because the editor must invoke the completed CLI engine.
- **US3** depends on US1; its test authoring can overlap late US2 work after the bundle prompt/protocol stabilize.
- **US4** CLI recovery depends on US1; its editor recovery work also depends on US2.
- **Phase 7** depends on every story included in the release.

### Within Each User Story

- Write the story's failing tests before its implementation tasks.
- Build/validate pure data and prompt behavior before call orchestration.
- Complete CLI behavior before exposing it through the server and UI.
- Parse and validate a response before the first file write.
- Persist the run report before process exit; consume it before writing UI provenance.
- Stop at each checkpoint and run that story's independent test before continuing.

### Parallel Opportunities

- T002, T003, T004, and T006 can proceed together after T001.
- T010 and T011 can proceed together after the foundation is stable.
- T017, T018, and T019 can define server, integration, and browser expectations together; T022, T023, and T025 can then implement separate UI files in parallel after the contract is settled.
- T026, T027, and T028 cover separate quality surfaces and can proceed together.
- T032, T033, and T034 cover separate legacy, CLI-recovery, and editor-recovery surfaces and can proceed together.
- T038 and T039 can proceed together after all story behavior stabilizes.

---

## Parallel Example: User Story 1

```text
Task T010: Define CLI selection/source/capacity/report expectations in tests/test_narration_bundle_cli.py
Task T011: Define live/provider-batch call counts and prompt delivery in tests/test_narrate_input_delivery.py
```

## Parallel Example: User Story 2

```text
Task T017: Define bundle argv behavior in tests/test_editor_pipeline.py
Task T018: Define SSE/report/activity behavior in tests/test_editor_service_integration.py
Task T019: Define dialog and streamed-run behavior in frontend/e2e/session-narration-bundle.spec.ts

After the route contract stabilizes:
Task T022: Build frontend/src/components/scene-editor/NarrationBundleDialog.vue
Task T023: Add the bundle action event in frontend/src/components/scene-editor/ExtractionEditor.vue
Task T025: Add bundle ceiling/help in frontend/src/components/scene-editor/KnobDrawer.vue
```

## Parallel Example: User Story 3

```text
Task T026: Lock bundle template rules in tests/test_narrate_template_contract.py
Task T027: Lock private/shared input delivery in tests/test_narrate_input_delivery.py
Task T028: Lock render/retrieval/review boundaries in structural guard tests
```

## Parallel Example: User Story 4

```text
Task T032: Protect existing sequential/single-scene behavior in tests/test_sd_narrate.py
Task T033: Define partial CLI recovery in tests/test_narration_bundle_cli.py
Task T034: Define partial editor recovery in server integration and Playwright tests
```

---

## Implementation Strategy

### MVP First: User Story 1

1. Complete the fixture and foundational phases.
2. Complete US1's failing tests and CLI implementation.
3. Run the US1 checkpoint: one bundled call, correct files, explicit scope, default sequential behavior unchanged.
4. Stop here for a CLI-only internal demo if needed; this is the smallest useful token-saving increment.

### Incremental Delivery

1. **Foundation**: deterministic protocol, prompt builders, shared writer/report, and config default.
2. **US1**: CLI one-exchange narration becomes usable and measurable.
3. **US2**: the editor exposes the same invocation with explicit scope.
4. **US3**: quality, continuity, attribution, and review gates are proven.
5. **US4**: partial recovery and legacy-mode guarantees complete the safe operational path.
6. **Polish**: documentation, complete regression suite, and requirement/constitution audit.

### Team Execution

After Phase 2, one contributor should own `session_doc/sd_narrate.py` through US1 to avoid conflicting edits. Server tests, browser fixtures, and quality contract tests can be prepared in parallel. Once the CLI contract stabilizes, server and UI implementation can proceed concurrently in separate files, followed by integration and recovery work.

---

## Notes

- `[P]` tasks target independent files or test surfaces; honor the dependency notes before starting them.
- User-story labels provide traceability to [spec.md](./spec.md).
- Tests precede implementation because this specification explicitly defines independent acceptance scenarios and protocol failure behavior.
- Do not repair the unrelated first-line `tokens: N` implementation gap as part of these tasks.
- Do not add automatic grouping, a combined canonical narration file, fuzzy scene matching, automatic approval, or automatic assembly.
- Commit after each task or coherent test/implementation pair.
