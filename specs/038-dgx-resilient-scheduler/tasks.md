# Tasks: Resilient DGX Work Scheduler

**Input**: Design documents from `/specs/038-dgx-resilient-scheduler/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Required by FR-024 and SC-009. Write focused tests before each implementation and prove the intended failure before changing production code.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files and has no dependency on an unfinished task
- **[Story]**: Maps the task to a user story in spec.md

## Phase 1: Setup and Cross-Repository Contract

**Purpose**: Establish the companion registry contract and feature test seams.

- [X] T001 Record the companion `/home/kostadis/src/dgx-fun` revision and delivery order for `/home/kostadis/src/dgx-fun/dgxlib/registry.py`, `/home/kostadis/src/dgx-fun/dgxlib/models.yaml`, and `/home/kostadis/src/dgx-fun/tests/test_registry.py` in `specs/038-dgx-resilient-scheduler/implementation-notes.md`
- [X] T002 [P] Add shared deterministic fake endpoint, injected clock, and no-sleep model-call fixtures for this feature in `tests/conftest.py` and `tests/fixtures/summary_native/scheduler/`

---

## Phase 2: Foundational Scheduler Contracts

**Purpose**: Implement common types, failure classification, persistence, and queue mechanics required by all scheduler-backed stories.

**Critical**: Finish this phase before US2–US5. US1's pure concurrency resolver can begin after T001, but integration into run records depends on this foundation.

- [X] T003 [P] Add failing unit tests for stable item ordering, independent endpoint bounds, generation-safe late results, endpoint identity collisions, and finite per-item endpoint attempts in `tests/test_summary_native_scheduler.py`
- [X] T004 [P] Add failing unit tests for run-record deterministic serialization, atomic progress repair, redaction, and compatible v1 reading in `tests/test_summary_native_scheduler_records.py`
- [X] T005 [P] Add failing tests for public post-retry transport versus model/protocol failure classification in `tests/test_campaignlib_pipeline.py`
- [X] T006 Expose the public final-call failure classification seam without changing campaignlib retry counts in `campaignlib/api/client.py` and `campaignlib/api/__init__.py`
- [X] T007 Implement WorkItem, EndpointState, AttemptRecord, FailureEnvelope, endpoint-event, and telemetry projection models from `data-model.md` in `pipelines/summary_native/scheduler.py`
- [X] T008 Implement the bounded deterministic queue, one-attempt-per-item-endpoint rule, assignment generations, canonical commit callback, and local executor support in `pipelines/summary_native/scheduler.py`
- [X] T009 Implement independent preflight, quarantine, injected-interval probe/rejoin, graceful no-healthy-endpoint refusal, and shutdown/interruption handling in `pipelines/summary_native/scheduler.py`
- [X] T010 Implement schema-v2 atomic run journaling, validated resume selection, artifact-authority reconciliation hooks, URL redaction, and v1 compatibility in `pipelines/summary_native/scheduler.py`
- [X] T011 Add stable operational/verifier taxonomy constants and explicit existing-code mappings in `pipelines/summary_native/schema.py`
- [X] T012 Run and make green the foundational scheduler/campaignlib suites in `tests/test_summary_native_scheduler.py`, `tests/test_summary_native_scheduler_records.py`, and `tests/test_campaignlib_pipeline.py`

**Checkpoint**: A fake adapter can survive endpoint failure, recover, resume from validated artifacts, and produce deterministic records without importing a provider SDK.

---

## Phase 3: User Story 1 - Use the Served Model's Capacity (Priority: P1) MVP

**Goal**: Resolve omitted DGX concurrency from dgxlib, preserve explicit override/fallback, and expose provenance.

**Independent Test**: Fake dgxlib declares 8; omitted extract/audit uses 8 per endpoint, absence uses 6, explicit 3 wins, invalid presence refuses, and record/start text names source.

### Tests for User Story 1

- [X] T013 [P] [US1] Add failing resolver tests for explicit, dgxlib 8, absent fallback 6, invalid declaration, non-DGX fallback, and resolved model identity in `tests/test_summary_native_concurrency.py`
- [X] T014 [P] [US1] Add failing CG boundary tests for a fake `resolve_model_config().max_concurrency` in `tests/test_dgx_registry.py`
- [X] T015 [P] [US1] Add companion dgxlib tests for optional positive `max_concurrency`, invalid values, and `qwen3.8-flash-next == 8` in `/home/kostadis/src/dgx-fun/tests/test_registry.py`

### Implementation for User Story 1

- [X] T016 [US1] Add optional `max_concurrency` to `/home/kostadis/src/dgx-fun/dgxlib/registry.py` and set `qwen3.8-flash-next: 8` in `/home/kostadis/src/dgx-fun/dgxlib/models.yaml`
- [X] T017 [US1] Implement explicit > dgxlib selected-model > fallback resolution and stable provenance in `pipelines/summary_native/concurrency.py`
- [X] T018 [US1] Change extract/audit parser defaults to `None`, resolve after actual backend/model selection, and record/print value plus source in `pipelines/summary_native/cli.py`, `pipelines/summary_native/extract.py`, and `pipelines/summary_native/audit.py`
- [X] T019 [US1] Update default ownership/source assertions and run-record expectations in `tests/test_summary_native_config_defaults.py`, `tests/test_summary_native_extract.py`, and `tests/test_summary_native_audit.py`

**Checkpoint**: Issue #539 works independently for extract/audit before failover is enabled.

---

## Phase 4: User Story 2 - Finish Through Endpoint Failure (Priority: P1)

**Goal**: Adapt remote operations to shared bounded dispatch, endpoint quarantine, cross-endpoint retry, and recovery.

**Independent Test**: A two-endpoint fixture loses one host mid-run, completes eligible work on the survivor, rejoins the recovered host, never exceeds either bound, and exhausts only after all endpoints attempted the item.

### Tests for User Story 2

- [X] T020 [P] [US2] Add failing extract adapter tests for partial preflight, failover, no duplicate lower transport retry, content rejection without quarantine, recovery, and bounds in `tests/test_summary_native_extract.py`
- [X] T021 [P] [US2] Add equivalent audit adapter tests with stable verdict behavior in `tests/test_summary_native_audit.py`
- [X] T022 [P] [US2] Add NPC draft multi-endpoint selection/failover/bounds tests for one-shot and chunked modes in `tests/test_summary_native_npc_draft.py`

### Implementation for User Story 2

- [X] T023 [US2] Replace `extract._run_pool`/all-or-nothing preflight with scheduler adapter callbacks while preserving chunk cache validation and canonical finalization in `pipelines/summary_native/extract.py`
- [X] T024 [US2] Separate transport exhaustion from model-output validation and remove the extra same-endpoint transport retry in `pipelines/summary_native/extract.py` and `pipelines/summary_native/audit.py`
- [X] T025 [US2] Adapt audit items/results to scheduler dispatch, quarantine, and cross-endpoint attempt records in `pipelines/summary_native/audit.py`
- [X] T026 [US2] Add explicit endpoints/parallel to NPC draft CLI/config resolution and adapt selected NPC calls, including chunked map/reduce item identities, in `pipelines/summary_native/cli.py`, `pipelines/summary_native/npc_draft.py`, and `pipelines/summary_native/npc_chunked.py`
- [X] T027 [US2] Make all four operation selections explicit and stable before execution, including `npc-verify` local items, in `pipelines/summary_native/cli.py`
- [X] T028 [US2] Run and make green failure/recovery/bound suites in `tests/test_summary_native_scheduler.py`, `tests/test_summary_native_extract.py`, `tests/test_summary_native_audit.py`, and `tests/test_summary_native_npc_draft.py`

**Checkpoint**: Remote work continues across an endpoint loss and recovery; current deterministic verification remains model-free.

---

## Phase 5: User Story 3 - Resume from Durable Work (Priority: P1)

**Goal**: Resume exact selections from operation-owned caches/artifacts and durable journals without a competing checkpoint truth.

**Independent Test**: Interrupt each operation, resume exact run, send only unfinished compatible work, repair record/artifact crash races, and make zero calls on completed runs.

### Tests for User Story 3

- [X] T029 [P] [US3] Add failing resume matrix for cache success/missing record, record success/missing artifact, incomplete cache, changed inputs, topology-only changes, completed run, and ambiguous run in `tests/test_summary_native_scheduler_records.py`
- [X] T030 [P] [US3] Add operation-specific extraction/audit resume and stable cache-key tests in `tests/test_summary_native_extract.py` and `tests/test_summary_native_audit.py`
- [X] T031 [P] [US3] Add NPC draft and deterministic verification resume/staleness tests in `tests/test_summary_native_npc_draft.py` and `tests/test_summary_native_npc_verify.py`

### Implementation for User Story 3

- [X] T032 [US3] Implement shared `--resume [RUN_ID]` parsing, invalid flag combinations, compatible-run selection, and no-silent-fresh-run refusal in `pipelines/summary_native/cli.py`
- [X] T033 [US3] Implement extraction/audit cache authority reconciliation and status repair callbacks in `pipelines/summary_native/extract.py` and `pipelines/summary_native/audit.py`
- [X] T034 [US3] Implement NPC draft artifact/key reconciliation and per-NPC verification result journaling/resume without adding model calls in `pipelines/summary_native/npc_draft.py`, `pipelines/summary_native/npc_verify.py`, and `pipelines/summary_native/cli.py`
- [X] T035 [US3] Run and make green all resume matrices and verify resumed completed fixtures make zero client calls in `tests/test_summary_native_scheduler_records.py`, `tests/test_summary_native_extract.py`, `tests/test_summary_native_audit.py`, `tests/test_summary_native_npc_draft.py`, and `tests/test_summary_native_npc_verify.py`

**Checkpoint**: Every named operation can resume exact compatible work from disk and cannot mistake a record for a valid artifact.

---

## Phase 6: User Story 4 - Stable Results and Actionable Reporting (Priority: P2)

**Goal**: Guarantee timing-independent outputs and reconciled per-endpoint/failure reports aligned with #523.

**Independent Test**: Serial, parallel/reversed-delay, failed-over, and resumed fixtures produce identical content bytes/hashes while reports separate every operational and verifier category and reconcile telemetry.

### Tests for User Story 4

- [X] T036 [P] [US4] Add cross-mode deterministic byte/hash and late-result tests for extract/audit/draft in `tests/test_summary_native_scheduler.py`
- [X] T037 [P] [US4] Add operational/shared-verifier taxonomy mapping fixtures including all #523 categories and legacy detailed codes in `tests/test_summary_native_npc_verify.py`
- [X] T038 [P] [US4] Add per-endpoint latency/retry/usage-unavailable/quarantine reconciliation tests in `tests/test_summary_native_scheduler_records.py`

### Implementation for User Story 4

- [X] T039 [US4] Enforce canonical ordinal assembly and one-generation commit across extraction, audit, and draft finalizers in `pipelines/summary_native/extract.py`, `pipelines/summary_native/audit.py`, and `pipelines/summary_native/npc_draft.py`
- [X] T040 [US4] Emit two-axis operational/verifier failure envelopes while preserving existing mechanical findings in `pipelines/summary_native/npc_verify.py`, `pipelines/summary_native/audit.py`, and `pipelines/summary_native/scheduler.py`
- [X] T041 [US4] Complete per-endpoint/run telemetry derivation and stable JSON/Markdown final report rendering in `pipelines/summary_native/scheduler.py`
- [X] T042 [US4] Run deterministic/taxonomy/telemetry suites and compare fixture hashes across all execution modes in `tests/test_summary_native_scheduler.py`, `tests/test_summary_native_scheduler_records.py`, and `tests/test_summary_native_npc_verify.py`

**Checkpoint**: Content is byte-stable across timing/topology, and every outcome tells the operator whether to review content or recover infrastructure.

---

## Phase 7: User Story 5 - Operate and Recover in the UI (Priority: P2)

**Goal**: Expose full CLI start/resume/status capability through existing Summary Native and NPC pages with durable reload-safe state.

**Independent Test**: Start explicit work in UI, observe quarantine, reload, reconstruct identical state, resume in at most three actions, and see categorized results; empty scope remains refused.

### Tests for User Story 5

- [X] T043 [P] [US5] Add failing extract/audit route argv, invalid combination, resolved concurrency status, and malformed-record safety tests in `tests/test_summary_native_routes.py`
- [X] T044 [P] [US5] Add failing NPC draft/verify endpoints/parallel/resume/status and explicit-selection tests in `tests/test_npc_dossiers_routes.py`

### Implementation for User Story 5

- [X] T045 [US5] Add extract/audit resume parameters and disk-backed scheduler status projection routes without scheduler policy in `server/routers/summary_native.py`
- [X] T046 [US5] Add NPC draft remote scheduler flags, NPC verify local resume/parallel, and disk-backed status projection routes in `server/routers/npc_dossiers.py`
- [X] T047 [US5] Replace hard-coded blank=6 hints, show resolved source, add resume, endpoint health, telemetry, and categorized outcome panels in `frontend/src/views/grounding/SummaryNative.vue`
- [X] T048 [US5] Add equivalent draft/verify controls and durable status rendering to `frontend/src/views/npcs/NpcDossiers.vue`
- [X] T049 [US5] Verify empty selection/materialized Select all and reload behavior across both pages, updating shared UI types/helpers in `frontend/src/views/grounding/SummaryNative.vue` and `frontend/src/views/npcs/NpcDossiers.vue`
- [X] T050 [US5] Run route tests and `npm run build` from `frontend/package.json`, then manually execute quickstart UI reload scenario against fake endpoints

**Checkpoint**: CLI/UI parity is complete and browser reload loses no durable progress.

---

## Phase 8: Polish and Cross-Cutting Validation

**Purpose**: Documentation, regressions, compatibility, and final issue evidence.

- [X] T051 [P] Document concurrency precedence/source, endpoint health, resume identity, failure groups, and recovery in `docs/cli/summary_native_howto.md`
- [X] T052 [P] Document NPC draft scheduling and current deterministic/model-free verification semantics in `docs/cli/npc_dossiers_howto.md`
- [X] T053 [P] Add release/operator note for dgxlib companion requirement and changed omitted-parallel behavior in `specs/038-dgx-resilient-scheduler/implementation-notes.md`
- [X] T054 Audit `--endpoints`, `--parallel`, and `--resume` spelling/default ownership across the four operations and update drift guards in `tests/test_summary_native_config_defaults.py`
- [X] T055 Run the complete `specs/038-dgx-resilient-scheduler/quickstart.md`, full `pytest -q`, frontend build, and companion dgxlib tests; record exact commands/results in `specs/038-dgx-resilient-scheduler/implementation-notes.md`

---

## Dependencies and Execution Order

### Phase dependencies

- Setup starts immediately. T001 gates companion implementation; T002 may run independently.
- Foundation depends on test fixture availability as needed and blocks US2–US5.
- US1 can begin its pure resolver/companion tests after T001, then integrates with foundational records.
- US2 depends on Foundation and US1's effective concurrency contract.
- US3 depends on Foundation and operation adapters from US2.
- US4 depends on US2 and US3 so it can compare failover/resume outputs.
- US5 depends on stable CLI/record contracts from US1–US4.
- Polish depends on all delivered stories.

### Story graph

```text
US1 concurrency -> US2 resilient dispatch -> US3 resume -> US4 stable reporting -> US5 UI parity
```

Each checkpoint is independently demonstrable, although the full parent issue requires the sequence.

### Parallel opportunities

- T002 can run while T001 resolves the companion repo.
- T003–T005 are parallel test tasks; T007 model work can begin once their contracts are understood.
- Within each story, `[P]` test tasks touch separate test modules.
- Documentation T051–T053 can run in parallel after behavior is stable.

## Parallel Examples

### User Story 1

```text
Task T013: resolver tests in tests/test_summary_native_concurrency.py
Task T014: boundary tests in tests/test_dgx_registry.py
Task T015: companion dgxlib tests in the T001-recorded path
```

### User Story 2

```text
Task T020: extract failure/recovery tests
Task T021: audit failure/recovery tests
Task T022: NPC draft failure/recovery tests
```

### User Story 5

```text
Task T043: Summary Native route tests
Task T044: NPC dossier route tests
```

## Implementation Strategy

### MVP first

1. T001–T019 deliver issue #539 as the first independently verifiable increment.
2. Validate `qwen3.8-flash-next` omitted parallel resolves to 8 and explicit/fallback behavior remains correct.
3. Continue through resilient scheduling rather than publishing #549 complete at this checkpoint.

### Incremental delivery

1. Foundation supplies reusable deterministic scheduling primitives.
2. US1 establishes authoritative capacity.
3. US2 makes multi-endpoint runs survive failures.
4. US3 makes interrupted work recover without repeat spend.
5. US4 makes outputs/reports deterministic and actionable.
6. US5 completes CLI/UI parity and reload recovery.

## Notes for the Terra Implementation Agent

- Keep current `npc-verify` deterministic. Do not add a model call to satisfy scheduler wording; use local item execution and align the report contract for a future #523 verifier adapter.
- Do not import provider SDKs or dgxlib from `scheduler.py`; resolve capacity in `concurrency.py` and classify final call failures through campaignlib.
- Existing content-validation retries must be named/tested separately from transport retries. Never repeat campaignlib's exhausted transport loop on the same endpoint.
- Treat operation artifacts as completion truth and run records as attempt/health truth. Tests must cover both crash-race directions.
- Do not claim #539 complete until the companion dgx-fun/dgxlib field is actually delivered and pinned/tested.
