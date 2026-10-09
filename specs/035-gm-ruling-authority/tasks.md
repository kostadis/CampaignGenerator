# Tasks: GM Rulings and Authority Tiers

**Input**: Design documents from `specs/035-gm-ruling-authority/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md, migration.md

**Tests**: Required because the specification defines regeneration, transaction recovery, audience isolation, cache freshness, migration/adoption, and CLI/UI parity acceptance fixtures.

**Model routing**: GPT-5.6 Sol orchestrates; GPT-6 Astra planned the specification/design/task decomposition; GPT-5.6 Terra implements these tasks.

**Organization**: Tasks are grouped by user story. Shared safety infrastructure is foundational so no story can bypass source authority, human approval, audience filtering, transaction recovery, or immutable history.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it uses different files and has no dependency on another incomplete task in its phase
- **[Story]**: User story from `spec.md`
- Every task names its exact target path

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish representative fixtures and the operator documentation landing point without changing runtime behavior.

- [X] T001 Create the authority fixture workspace with summaries, exact anchored sections, registries, mixed classifications, external/symlink notes, and all four projection inputs in `tests/fixtures/summary_native/authority/`
- [X] T002 [P] Add the authority workflow document outline and links to the feature contracts in `docs/cli/summary_native_authority.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Implement strict on-disk models, immutable mutation history, recoverable locking, allowed-source guards, audience-safe input snapshots, and policy-aware cache identity before any story can mutate or render campaign data.

**⚠️ CRITICAL**: No user story work begins until this phase passes. US1 source apply is unsafe without every foundational gate.

- [X] T003 [P] Add strict ledger, ruling/note, audience, interval, proposal, approval, event, receipt, conflict, selector, and manifest validation tests in `tests/test_summary_native_authority.py`
- [X] T004 Implement the strict duplicate-key-refusing authority models, exact identity validation, state transitions, partial precedence rules, and legacy-store separation in `pipelines/summary_native/authority.py`
- [X] T005 [P] Add planning selector schema tests for absent-field legacy behavior and configured empty/missing/unreadable/zero-match refusal in `tests/test_planning_config.py`
- [X] T006 Extend the strict planning configuration with mandatory configured exact/glob note selectors in `campaignlib/planning_config.py`
- [X] T007 [P] Add crash-point, lock, unexpected-digest, idempotent recovery, immutable-event, and all-mutation-history tests in `tests/test_summary_native_authority_transactions.py`
- [X] T008 Implement shared/exclusive campaign authority locking, durable journals, immutable snapshots/events, per-file atomic replacement orchestration, coherent read snapshots, and forward-only recovery in `pipelines/summary_native/authority_apply.py`
- [X] T009 [P] Add allowed summary-root, unique-span, digest, generated-file, registry/thread-authority, external-write, and claimed-verbatim refusal tests in `tests/test_summary_native_authority_sources.py`
- [X] T010 Implement the replacement-only maintained-summary source adapter and exact source/digest/verbatim guards in `pipelines/summary_native/authority_sources.py`
- [X] T011 [P] Add GM-default grants, global non-GM generation/preview refusal until US3, exact character identity, filtered-payload, sibling-cache, and manifest freshness tests in `tests/test_summary_native_authority_audience.py`
- [X] T012 Implement digest-bound anchored section resolution, default GM-only policy, selection snapshots, AuthorityInputManifest construction, and the fail-closed non-GM availability gate in `pipelines/summary_native/authority_inputs.py`
- [X] T013 Extend extraction cache keys and sibling-range cache admission with audience, filtered payload, policy/schema, record revision, source, and selection membership digests in `pipelines/summary_native/notes.py` and `pipelines/summary_native/extract.py`
- [X] T014 Add `authority init`, `validate`, and `status` parsing, stable numeric exits, JSON envelopes, pending-transaction refusal, fail-closed non-GM command refusal, and exact next-command errors in `pipelines/summary_native/cli.py`

**Checkpoint**: Strict authority state, complete history, safe source boundaries, coherent readers, and cache admission are enforceable before story code. GM is the only enabled render/preview target; every non-GM command refuses until US3 connects the filter to all downstream surfaces.

---

## Phase 3: User Story 1 - Preserve a Reviewed Correction (Priority: P1) 🎯 MVP

**Goal**: Let the GM stage, inspect, digest-approve, apply, regenerate, recover, and safely withdraw one maintained-summary correction without editing generated Markdown.

**Independent Test**: In the GM-only MVP, apply the Earthstone responsible-actor correction to one authoritative summary, force rebuild/extract/all four synth commands, verify consistent world/campaign/planning truth and complete provenance, then request and apply a safe reversal without losing later unrelated edits.

### Tests for User Story 1

- [X] T015 [P] [US1] Add proposal/apply tests for post-propose ledger binding, separate approval events, stale digest refusal, incompatible source proposals, receipt digest acyclicity, and exact source replacement in `tests/test_summary_native_authority_apply.py`
- [X] T016 [P] [US1] Add Earthstone all-projection regeneration, force rebuild, source-authority, provenance, and no-generated-patch integration tests in `tests/test_summary_native_authority_regeneration.py`
- [X] T017 [P] [US1] Add withdrawal/reversal tests for preserved unrelated edits, changed-passage refusal, retained history, and stale dependent outputs in `tests/test_summary_native_authority_withdrawal.py`
- [X] T018 [P] [US1] Add CLI contract tests for record stage/apply/retire, propose/apply/withdraw/recover, stable exits/JSON, and `--force` safety in `tests/test_summary_native_authority_cli.py`

### Implementation for User Story 1

- [X] T019 [US1] Implement immutable record stage/apply/retire, proposal creation, separate digest-bound approval, source apply, receipt commit, incompatible-proposal refusal, and recovery transitions in `pipelines/summary_native/authority_apply.py`
- [X] T020 [US1] Implement reversal-request and current-source-digest-safe withdrawal proposal generation in `pipelines/summary_native/authority_apply.py`
- [X] T021 [US1] Integrate authority/source generations, proposal/receipt provenance, post-model manifest recheck, and stale dependent artifact handling in `pipelines/summary_native/freshness.py` and `pipelines/summary_native/synth.py`
- [X] T022 [US1] Add record stage/apply/retire, list/show/history, propose/apply/withdraw/recover command handlers and exact shared option spellings in `pipelines/summary_native/cli.py`
- [X] T023 [US1] Add CLI-backed authority init/status/record/history/proposal/apply/withdraw/recovery JSON and SSE endpoints in `server/routers/summary_native.py`
- [X] T024 [US1] Add initialization, record revision, exact diff, digest-bound apply, receipt/history, stale projection, withdrawal, and recovery controls in `frontend/src/views/grounding/SummaryNative.vue`
- [X] T025 [US1] Add end-to-end parity coverage for init, stage/apply/retire, source correction, forced regeneration status, withdrawal, recovery, and one ordinary GM correction flow completed in no more than five user actions in `frontend/e2e/summary-native-state.spec.ts`

**Checkpoint**: Foundation + US1 is the GM-only MVP. Source correction is usable through both CLI and UI, survives regeneration, fails closed on crashes, stale bytes, or any non-GM target, and preserves complete history.

---

## Phase 4: User Story 2 - Use Campaign Notes in Planning (Priority: P2)

**Goal**: Resolve explicitly selected classified notes into a reviewed snapshot and make planning use their scoped precedence, future status, provenance, and freshness.

**Independent Test**: Using the GM target, select exact files and globs containing every classification and audience metadata shape, review concrete membership, generate planning, verify `OVERLAY` over `PREP`, unresolved `OPEN`, stale-future warnings, complete run records, and refusal after note or glob membership changes.

### Tests for User Story 2

- [X] T026 [P] [US2] Add deterministic exact/glob resolution, symlink dedupe, external disclosure, selection reason, zero-match refusal, and membership drift tests in `tests/test_summary_native_authority_selection.py`
- [X] T027 [P] [US2] Add CANON/TABLE supersession, OVERLAY/PREP ordering, equal-overlay blocking, OPEN non-settlement, and disjoint-interval evolution tests in `tests/test_summary_native_authority_precedence.py`
- [X] T028 [P] [US2] Add planning run-record completeness, note metadata freshness, stale-future warning, and legacy cache/run refusal tests in `tests/test_summary_native_authority_freshness.py`
- [X] T029 [P] [US2] Add planning selector persistence and CRUD tests in `tests/test_planning_config_service.py`

### Implementation for User Story 2

- [X] T030 [US2] Implement exact/glob materialization, canonical-path dedupe, external disclosure, stable section selection, preview digest, and changed-membership refusal in `pipelines/summary_native/authority_inputs.py`
- [X] T031 [US2] Integrate GM-target classified note routing, scoped planning precedence, stale-future warnings, reviewed selection digest, and full authority input manifest into planning synthesis, and add `authority notes preview`, `--authority-selection`, and GM-only `--audience` command handling in `pipelines/summary_native/context.py`, `pipelines/summary_native/synth.py`, and `pipelines/summary_native/cli.py`
- [X] T032 [US2] Persist note selectors, expose selector CRUD/preview inputs through the planning owner, and forward reviewed selection plus GM audience to CLI-backed synthesis in `server/planning_config_service.py`, `server/routers/planning_routes.py`, and `server/routers/summary_native.py`
- [X] T033 [US2] Add note selector editing, concrete membership preview, classifications, audiences, reasons, external markers, warnings, and selection digest to `frontend/src/views/grounding/SummaryNative.vue`
- [X] T034 [US2] Add end-to-end planning selection, membership drift, classification display, warning, CLI/UI digest parity, and SC-006 validation of select → preview → review/apply correction → inspect impact in at most five actions per interface in `frontend/e2e/summary-native-state.spec.ts`

**Checkpoint**: Planning notes are first-class, explicitly selected, reproducible GM inputs without becoming completed history or silently expanding scope. Non-GM preview/generation still refuses until US3.

---

## Phase 5: User Story 3 - Keep Knowledge Audiences Separate (Priority: P3)

**Goal**: Enforce GM/player/all-character/named-character grants before every extraction, render, reference, fallback, preview, export, diagnostic, and cache lookup.

**Independent Test**: Starting from the US2 selection snapshots and fixture drafts, enable GM/player/character targets over sentinel secrets and verify zero unauthorized content in filtered input, cache, prompts, outputs, references, fallbacks, diagnostics, errors, and UI previews; player grants do not imply character grants.

### Tests for User Story 3

- [X] T035 [P] [US3] Add full-payload sentinel tests covering prompt jobs, deterministic references, fallbacks, diagnostics, errors, external note metadata, and incomplete section coverage in `tests/test_summary_native_authority_leaks.py`
- [X] T036 [P] [US3] Add cross-audience cache rejection and policy/record/source revision invalidation tests in `tests/test_summary_native_authority_cache.py`
- [X] T037 [P] [US3] Add exact player/all-character/named-character registry resolution and historical interval audience tests in `tests/test_summary_native_authority_audience.py`

### Implementation for User Story 3

- [X] T038 [US3] Apply the audience-filtered evidence collection before checked-note extraction, prompt jobs, references, fallbacks, previews, exports, and diagnostics in `pipelines/summary_native/extract.py`, `pipelines/summary_native/state_sections.py`, and `pipelines/summary_native/synth.py`
- [X] T039 [US3] Replace the foundational non-GM refusal with exact player/character `--audience` support across every audience-aware sibling command, retain the US2 `--authority-selection` contract, and refuse unclassified required support in `pipelines/summary_native/cli.py`
- [X] T040 [US3] Forward audience and reviewed selection fields through CLI-backed Summary Native routes without exposing forbidden response details in `server/routers/summary_native.py`
- [X] T041 [US3] Add audience selection, coverage refusal, filtered preview, and safe diagnostic presentation in `frontend/src/views/grounding/SummaryNative.vue`
- [X] T042 [US3] Add end-to-end GM/player/character isolation and cross-audience cache non-reuse tests in `frontend/e2e/summary-native-state.spec.ts`

**Checkpoint**: Unauthorized knowledge is absent before model and cache boundaries, and UI/CLI expose identical audience behavior.

---

## Phase 6: User Story 4 - Review Conflicts and History (Priority: P4)

**Goal**: Surface deterministic structured conflicts and human-recorded prose contradictions with complete history, while recognizing legitimate time-separated world evolution.

**Independent Test**: Create overlapping incompatible structured claims and a later human-identified contradiction, verify both sources/projections and blocking behavior, resolve explicitly, and confirm disjoint intervals remain valid evolution and prose candidates receive no machine verdict.

### Tests for User Story 4

- [X] T043 [P] [US4] Add structured claim-key/value/interval/projection, exact-anchor, disjoint evolution, equal-overlay, and no-recency-winner conflict tests in `tests/test_summary_native_authority_conflicts.py`
- [X] T044 [P] [US4] Add human-identified/prose-candidate, resolve/dismiss, supersession-cycle, and immutable conflict-history tests in `tests/test_summary_native_authority_history.py`
- [X] T045 [P] [US4] Add conflict list/resolve/history CLI and JSON contract tests in `tests/test_summary_native_authority_cli.py`

### Implementation for User Story 4

- [X] T046 [US4] Implement structured and exact-anchor conflict detection, temporal overlap, human candidate recording, resolution status, and supersession validation in `pipelines/summary_native/authority.py`
- [X] T047 [US4] Add conflict list/resolve commands, explicit resolution-record staging, immutable history output, and blocking exit behavior in `pipelines/summary_native/cli.py`
- [X] T048 [US4] Add CLI-backed conflict list/resolve and history endpoints with stable HTTP/error mapping in `server/routers/summary_native.py`
- [X] T049 [US4] Add conflict comparison, source/projection display, human resolution staging, prose-candidate labeling, and history inspection in `frontend/src/views/grounding/SummaryNative.vue`
- [X] T050 [US4] Add end-to-end structured conflict, legitimate evolution, prose-candidate, resolution, and history parity tests in `frontend/e2e/summary-native-state.spec.ts`

**Checkpoint**: Structured contradictions never resolve silently; narrative judgment remains human; history explains why runs differ.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Complete adoption behavior, documentation, traceability, and repository-wide validation.

- [X] T051 [P] Add adoption tests proving summary-only workspaces remain valid, configured empty selections refuse, legacy cache/run schemas require regeneration, and all three narrow stores remain byte-identical in `tests/test_summary_native_authority_adoption.py`
- [X] T052 Implement legacy authority-aware cache/run version refusal and actionable regeneration messages in `pipelines/summary_native/freshness.py`
- [X] T053 Update the end-to-end Summary Native operator workflow, existing option family, recovery, adoption, and narrow-store boundaries in `docs/cli/summary_native_howto.md` and `docs/cli/summary_native_authority.md`
- [X] T054 Add operator-facing authority documentation to the repository index in `docs/README.md`
- [X] T055 Run the focused and full Summary Native pytest suites from `quickstart.md` and record command/results in `specs/035-gm-ruling-authority/validation.md`
- [X] T056 Run the frontend production build and Summary Native Playwright suite from `quickstart.md`, then record command/results in `specs/035-gm-ruling-authority/validation.md`
- [X] T057 Execute every post-implementation acceptance scenario in `specs/035-gm-ruling-authority/quickstart.md` against the disposable fixture and record pass/fail evidence in `specs/035-gm-ruling-authority/validation.md`

---

## Dependencies & Execution Order

### Phase dependencies

```text
Phase 1 Setup
    ↓
Phase 2 Foundation (blocks all stories)
    ↓
Phase 3 US1 (GM-only MVP source correction)
    ↓
Phase 4 US2 (GM planning notes)
    ↓
Phase 5 US3 (audience views)

US1 + US2 + US3
    ↓
Phase 6 US4 (cross-record conflict review and history)
    ↓
Phase 7 Polish and full validation
```

### User story dependencies

- **US1** starts after Foundation. It owns safe source mutation and MVP CLI/UI parity. It does not depend on US2 or US3 because Foundation already makes all applied source data audience/cache safe.
- **US2** starts after US1 because authoring classified note records reuses record staging/application and history from T019 and T022. Its independent test uses note records without requiring an applied source correction. Selection-domain test drafts may run alongside US1 in separate files, but the US2 checkpoint requires the completed shared record workflow.
- **US3** starts after US2 because audience enablement consumes US2 selection snapshots and CLI/router fields. Its integration tasks serialize with US2 where both touch `extract.py`, `synth.py`, `cli.py`, routes, and the Vue page.
- **US4** starts after US1, US2, and US3 so its conflict/history UI can compare applied corrections, classified planning notes, audiences, and projections. Basic incompatible source-proposal refusal is already required in US1.

### Within each story

- Write the listed acceptance/contract tests first and confirm they fail for the intended missing behavior.
- Implement domain behavior before CLI handlers, routes, and UI.
- CLI behavior must exist before its FastAPI face; route parity must exist before the UI calls it.
- Finish the story's end-to-end parity test before its checkpoint.

## Parallel Opportunities

- T002 can run with T001.
- Foundation test tasks T003, T005, T007, T009, and T011 touch different files and can be drafted in parallel before their paired implementations.
- US1 tests T015-T018 can be drafted in parallel after Foundation.
- US2 tests T026-T029 can be drafted in parallel; T030 and T032 can then proceed in parallel because they touch different owners.
- US3 tests T035-T037 can be drafted in parallel.
- US4 tests T043-T045 can be drafted in parallel.
- T051 can run independently of documentation tasks after all story behavior exists.
- Tasks sharing `authority_apply.py`, `synth.py`, `cli.py`, `server/routers/summary_native.py`, `SummaryNative.vue`, or the same E2E file are intentionally serialized and do not carry `[P]`.

## Parallel Example: User Story 1

```text
Task T015: Proposal/apply safety tests in tests/test_summary_native_authority_apply.py
Task T016: All-projection fixture tests in tests/test_summary_native_authority_regeneration.py
Task T017: Withdrawal tests in tests/test_summary_native_authority_withdrawal.py
Task T018: CLI contract tests in tests/test_summary_native_authority_cli.py
```

## Parallel Example: User Story 2

```text
Task T026: Selection resolution tests in tests/test_summary_native_authority_selection.py
Task T027: Classification precedence tests in tests/test_summary_native_authority_precedence.py
Task T028: Run-record/freshness tests in tests/test_summary_native_authority_freshness.py
Task T029: Planning service tests in tests/test_planning_config_service.py
```

## Parallel Example: User Story 3

```text
Task T035: Full leak-surface sentinel tests in tests/test_summary_native_authority_leaks.py
Task T036: Cross-audience cache tests in tests/test_summary_native_authority_cache.py
Task T037: Audience identity/interval tests in tests/test_summary_native_authority_audience.py
```

## Parallel Example: User Story 4

```text
Task T043: Structured conflict tests in tests/test_summary_native_authority_conflicts.py
Task T044: Human-candidate/history tests in tests/test_summary_native_authority_history.py
Task T045: Conflict CLI tests in tests/test_summary_native_authority_cli.py
```

## Requirements and Success-Criteria Traceability

| Coverage | Tasks |
|---|---|
| FR-001–FR-003, FR-011, FR-021, FR-024–FR-025 | T003-T014, T019, T022-T025 |
| FR-004, FR-019–FR-020; SC-001, SC-007 | T015-T025 |
| FR-005–FR-008, FR-012–FR-016; SC-002, SC-003, SC-009 | T026-T034 |
| FR-009–FR-010; SC-004 | T011-T013, T035-T042 |
| FR-017–FR-018, FR-026; SC-005 | T015, T027, T043-T050 |
| FR-022; SC-008 | T051-T054 |
| FR-023; SC-006 | T018, T022-T025, T029, T032-T034, T039-T042, T045, T047-T050 |
| Full acceptance | T055-T057 |

## Implementation Strategy

### MVP first

1. Complete Setup T001-T002.
2. Complete every Foundation task T003-T014; do not weaken or defer safety gates.
3. Complete US1 T015-T025, including GM-only CLI/UI parity, source recovery, cache/freshness invalidation, and safe withdrawal; keep non-GM commands refused.
4. Stop and run the US1 independent test. This is the smallest safe MVP.

### Incremental delivery

1. Foundation + US1: replayable reviewed source correction.
2. Add US2: explicitly selected classified planning notes.
3. Add US3: complete audience-isolated inputs and views.
4. Add US4: richer conflict resolution and history.
5. Complete adoption docs and full quickstart validation.

## Notes

- `[P]` never appears on tasks that modify a shared source file or depend on unfinished behavior in the same phase.
- Existing `canon.yaml`, provenance corrections, and transcript corrections retain their semantics.
- V1 changes maintained summary Markdown through exact replacement only; it does not add a generic patch engine or source-annotation grammar.
- Do not create issue #547's adjudication platform, group C promotion/checker, or group D scheduler.
- No implementation task may add a model call for authority, selection, audience, conflicts, apply, recovery, or freshness.
