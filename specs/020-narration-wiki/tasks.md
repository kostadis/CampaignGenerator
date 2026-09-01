# Tasks: Persistent Narration Wiki

**Input**: Design documents from `/specs/020-narration-wiki/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: The specification requires independent acceptance tests, deterministic byte-level results, failure/recovery coverage, CLI/UI parity, and automated resize/scroll verification. Test tasks are included and must be written and observed failing before their corresponding implementation tasks.

**Organization**: Tasks are grouped by the five user stories in specification order. The three P1 stories build the complete safe engine; the two P2 stories add browser parity and portable cross-campaign reuse.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: May run in parallel with other ready tasks because it edits different files and has no dependency on unfinished work.
- **[Story]**: Maps the task to a user story in `spec.md`.
- Every task names the exact file or directory it changes.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Register the engine package and browser-test infrastructure without implementing domain behavior.

- [X] T001 Create the `session_doc.narration_wiki` package skeleton and register the `narration_wiki = "session_doc.narration_wiki.cli:main"` console script in `session_doc/narration_wiki/__init__.py`, `session_doc/narration_wiki/cli.py`, and `pyproject.toml`
- [X] T002 [P] Pin `@playwright/test`, add the `test:e2e` script, and configure a Chromium project with an exact 1280x720 viewport in `frontend/package.json`, `frontend/package-lock.json`, and `frontend/playwright.config.ts`
- [X] T003 [P] Create deterministic fixture-copy, hash, canonical-JSON, and subprocess assertion helpers in `tests/narration_wiki_helpers.py` and document fixture ownership in `tests/fixtures/narration_wiki/README.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish shared scope resolution, exact-byte persistence, state contracts, recovery, and CLI behavior required by every story.

**⚠️ CRITICAL**: No user-story implementation begins until this phase passes.

### Tests

- [X] T004 [P] Add failing exact-byte atomic-write tests covering sibling temporary files, fsync, binary preservation, cleanup, and replacement failure in `tests/test_atomic_write.py`
- [X] T005 Implement binary-safe and text/JSON-compatible atomic writers without changing existing callers in `campaignlib/util.py`
- [X] T006 [P] Add failing authoritative-guidance tests for configured rulebook, voice, example, and checker paths; no legacy fallback; no directory creation; and no cross-campaign borrowing in `tests/test_narration_context.py` and `tests/test_session_editor_config_service.py`
- [X] T007 Implement the read-only `NarrationGuidance` resolver and migrate the session editor service to that single seam in `campaignlib/narration_context.py` and `server/session_editor_config_service.py`
- [X] T008 [P] Add failing base-model and path-policy tests for stable IDs, normalized slugs, canonical JSON, relative POSIX paths, explicit session containment, escaping intermediate/final symlinks, and configured mutation targets in `tests/test_narration_wiki_models.py`
- [X] T009 Implement shared enums, `CampaignScope`, `WikiIteration`, status/recovery projections, canonical serializers, hashes, and state-transition guards in `session_doc/narration_wiki/models.py`
- [X] T010 Implement strict campaign/session resolution, symlink-component refusal, relative-path serialization, and authorized-target checks in `session_doc/narration_wiki/paths.py`
- [X] T011 [P] Add failing canonical persistence, campaign `flock`, journal-phase, idempotent-recovery, and `needs_attention` tests in `tests/test_narration_wiki_storage.py`
- [X] T012 Implement canonical JSON/Markdown/byte I/O, campaign locks, hash-bound transaction journals, atomic replacement, and recovery entry points in `session_doc/narration_wiki/storage.py`
- [X] T013 Add failing common CLI contract tests for explicit scope, one spelling per option, empty-selection refusal, JSON/human envelopes, safe diagnostics, and exit codes 0/2/3/4/5/6/70 in `tests/test_narration_wiki_cli.py`
- [X] T014 Implement the shared `argparse` scope owner, command dispatcher, output renderers, error classification, and read-only disk-derived `status` skeleton in `session_doc/narration_wiki/cli.py`

**Checkpoint**: The package can resolve exactly one safe session, read authoritative campaign guidance, persist canonical state under a lock, recover journals, and expose a stable CLI envelope.

---

## Phase 3: User Story 1 - Promote Durable Patterns Through Human Gate (Priority: P1) 🎯 MVP

**Goal**: Collect one explicitly selected session, persist deterministic baseline measurement, resolve seed conflicts, and record independent Gate 1 rulings before publishing durable patterns.

**Independent Test**: Collect a fixture session, measure its baseline, attempt and fail to accept a conflict-blocked pattern, record the GM conflict ruling, accept that pattern and reject another, then verify only the accepted page/index entry exists and every raw session artifact is unchanged.

### Tests for User Story 1

- [X] T015 [US1] Create flat-old, directory-middle, and current-layout evidence plus measurement, pattern-draft, and seed-conflict fixtures under `tests/fixtures/narration_wiki/layouts/` and `tests/fixtures/narration_wiki/gate1/`
- [X] T016 [P] [US1] Add failing manifest-schema, three-layout, fixed-depth, stable-order/hash, explicit-missing-row, immutable-input, corpus-ID, and duplicate-iteration tests in `tests/test_narration_wiki_collect.py`
- [X] T017 [P] [US1] Add failing collection boundary tests for empty selection, campaign-root selection, traversal, unrelated sessions, outside paths, and escaping file/directory symlinks in `tests/test_narration_wiki_isolation.py`
- [X] T018 [P] [US1] Add failing compatibility tests for the structured `d4-v1` checker registry while preserving legacy `voice_lint` CLI messages in `tests/test_voice_lint.py`
- [X] T019 [P] [US1] Add failing baseline tests for every D4 category, skipped reasons, guidance/corpus binding, cross-narrator reuse, deterministic bytes, pre-ruling remeasurement, and post-ruling drift refusal in `tests/test_narration_wiki_measure.py`
- [X] T020 [P] [US1] Add failing pattern-page and index tests for required sections, phrase-only refusal, normalized slug collisions, cross-tier collisions, named-content tier defaults, and deterministic diagnostics in `tests/test_narration_wiki_indexes.py`
- [X] T021 [P] [US1] Add failing seed-conflict tests for two-source validation, no automatic source preference, durable baseline-bound GM rulings, and affected-pattern blocking in `tests/test_narration_wiki_conflicts.py`
- [X] T022 [US1] Add failing Gate 1 transaction tests for one-pattern-at-a-time accept/reject, required baseline, resolved conflict references, campaign publication, portable handoff, duplicate rulings, and no batch approval in `tests/test_narration_wiki_storage.py`
- [X] T023 [US1] Add failing CLI integration tests for `status`, `collect`, `measure --phase before`, `index-check`, `conflict-rule`, and `pattern-rule` with contract-shaped output and unchanged-byte refusals in `tests/test_narration_wiki_cli.py`

### Implementation for User Story 1

- [X] T024 [US1] Add `TraceManifest`, `MeasurementSnapshot`, `BaselineBinding`, `PatternDraft`, `SeedConflictDraft`, `ConflictRuling`, and `Gate1Ruling` models and invariants in `session_doc/narration_wiki/models.py`
- [X] T025 [P] [US1] Implement fixed-depth allowlisted discovery for three historical layouts, raw-byte hashing, missing-role rows, immutable manifests, and corpus identity in `session_doc/narration_wiki/collect.py`
- [X] T026 [US1] Refactor checker definitions into one structured `d4-v1` registry while preserving legacy API and CLI projections in `session_doc/voice_lint.py`
- [X] T027 [US1] Implement corpus loading, eligible-prose segmentation, structured D4 checks, maximal three-plus-word cross-narrator reuse, guidance hashing, and canonical baseline snapshots in `session_doc/narration_wiki/measure.py`
- [X] T028 [P] [US1] Implement pattern/frontmatter parsing, slug ownership, page/index rendering, required-section checks, tier policy, and deterministic validation diagnostics in `session_doc/narration_wiki/indexes.py`
- [X] T029 [US1] Implement journaled conflict rulings and per-pattern Gate 1 publication/rejection with baseline drift checks, durable conflict references, campaign index/log updates, and portable promotion handoffs in `session_doc/narration_wiki/storage.py`
- [X] T030 [US1] Wire `collect`, baseline `measure`, `index-check`, `conflict-rule`, and `pattern-rule` into the state machine and result envelopes in `session_doc/narration_wiki/cli.py`

**Checkpoint**: User Story 1 is independently functional and is the safe MVP boundary.

---

## Phase 4: User Story 2 - Accept or Reject One Atomic Rule Change Safely (Priority: P1)

**Goal**: Stage exactly one authorized hash-bound guidance edit, apply it for comparison, measure the same corpus, and finish Gate 2 by retaining accepted bytes or restoring rejected bytes while preserving durable evidence.

**Independent Test**: Stage one confirmed-pattern proposal, verify the target is unchanged, apply it for comparison, measure after, reject it, and prove exact byte restoration plus one Rejected impact entry; then prove an equivalent recurrence is blocked before staging unless canonical new evidence or a GM override qualifies.

### Tests for User Story 2

- [X] T031 [US2] Create valid, unauthorized, multi-target, stale-hash, reconsideration, and non-UTF-8 proposal fixtures under `tests/fixtures/narration_wiki/proposals/`
- [X] T032 [P] [US2] Add failing proposal tests for one authorized target, no renderer/prompt/outside target, no symlink component, exact snapshots/hashes, complete generated diff, and staging without target mutation in `tests/test_narration_wiki_patches.py`
- [X] T033 [P] [US2] Add failing reconsideration tests for deterministic fingerprints, same-digest/new-path refusal, affected-rule bindings, current-manifest membership, mutually exclusive evidence/override, and pre-staging rejection in `tests/test_narration_wiki_reconsideration.py`
- [X] T034 [P] [US2] Add failing Gate 2 tests for comparison apply, same-corpus after measurement, accept/retain, reject/restore, late evidence/override refusal, duplicate decisions, crash points, and exact impact entries in `tests/test_narration_wiki_gate2.py`
- [X] T035 [US2] Add failing CLI integration tests for `proposal-stage`, `proposal-apply`, `measure --phase after`, and `proposal-rule` including invalid transitions, stale state, and no partial writes in `tests/test_narration_wiki_cli.py`
- [X] T036 [US2] Add a failing end-to-end rejection-asymmetry test proving the confirmed wiki lesson survives, target bytes restore exactly, one ledger record remains, and an equivalent next proposal is suppressed in `tests/test_narration_wiki_patches.py`

### Implementation for User Story 2

- [X] T037 [US2] Add `AtomicProposal`, `CanonicalEvidenceBinding`, `ImpactEntry`, proposal fingerprint, and reconsideration models and invariants in `session_doc/narration_wiki/models.py`
- [X] T038 [US2] Implement proposal parsing, confirmed-pattern eligibility, exact target authorization, prior-rejection equivalence, canonical new-evidence validation, stage-time GM override, snapshots, hashes, and unified diff generation in `session_doc/narration_wiki/proposals.py`
- [X] T039 [US2] Implement compare-and-swap application of exact after-snapshot bytes and hash-checked exact before-snapshot restoration without executing diff text in `session_doc/narration_wiki/proposals.py`
- [X] T040 [US2] Implement after-phase measurement preconditions for active proposal, comparison hash, original corpus ID, and original measurement profile in `session_doc/narration_wiki/measure.py`
- [X] T041 [US2] Implement journaled Gate 2 finalization across target bytes, `gate2.json`, and the append-only `skill-impact.md` ledger with idempotent accept/retain and reject/restore behavior in `session_doc/narration_wiki/storage.py`
- [X] T042 [US2] Wire `proposal-stage`, `proposal-apply`, after `measure`, and `proposal-rule` with staged-basis-only Gate 2 validation into `session_doc/narration_wiki/cli.py`

**Checkpoint**: User Story 2 safely completes one atomic proposal lifecycle without losing the durable lesson.

---

## Phase 5: User Story 3 - Measure and Audit the Loop Deterministically (Priority: P1)

**Goal**: Make the complete evidence, index, ledger, duplicate-refusal, and recovery loop deterministic and mechanically auditable without allowing a measurement to decide a human Gate.

**Independent Test**: Repeat collection/status/index/measurement on unchanged bytes and obtain identical output; inject failures at every journal boundary and recover idempotently; verify duplicate ledger/index identities refuse without changing bytes.

### Tests for User Story 3

- [X] T043 [P] [US3] Expand deterministic measurement tests for stable row ordering, no timestamps/host paths, exact observed/budget/verdict fields, skipped cases, maximal reuse spans, and evidence-only breaches in `tests/test_narration_wiki_measure.py`
- [X] T044 [P] [US3] Expand index audit tests for duplicate slugs, broken links, tier/page mismatches, malformed required sections, unresolved promotion state, and sorted actionable errors in `tests/test_narration_wiki_indexes.py`
- [X] T045 [P] [US3] Add failure-injection tests for every conflict/Gate 1/Gate 2 journal phase, duplicate impact keys, unexpected live hashes, restart status, and idempotent recovery in `tests/test_narration_wiki_storage.py`
- [X] T046 [US3] Add a failing full CLI audit-loop test covering deterministic read-only reruns, invalid-state refusal, recovery status, and measurement breaches that never advance a Gate in `tests/test_narration_wiki_cli.py`

### Implementation for User Story 3

- [X] T047 [US3] Complete deterministic measurement ordering, maximal reuse selection, skipped-result explanations, and byte-identical repeat behavior in `session_doc/narration_wiki/measure.py`
- [X] T048 [US3] Complete campaign/portable `index-check` auditing and deterministic problem rendering without repair side effects in `session_doc/narration_wiki/indexes.py`
- [X] T049 [US3] Complete duplicate-ledger refusal, transaction failure injection points, restart recovery, and `needs_attention` handling across all mutation types in `session_doc/narration_wiki/storage.py`
- [X] T050 [US3] Integrate recovery projection, complete audit-state transitions, and evidence-only failure output into `session_doc/narration_wiki/cli.py`

**Checkpoint**: All P1 engine behavior is deterministic, recoverable, and independently auditable.

---

## Phase 6: User Story 4 - Reach the Same Workflow from CLI and UI (Priority: P2)

**Goal**: Expose every public command through a thin FastAPI adapter and one existing-style Vue page, with disk-derived state, streamed progress, cancellation, and usable scrolling at the supported dimensions.

**Independent Test**: Execute every public command through CLI and UI against equivalent fixture copies and obtain identical feature artifacts and refusal behavior; at exactly 1280x720 resize every declared panel to 320x160 and prove both-axis scrolling plus keyboard-reachable Gate controls.

### Tests for User Story 4

- [X] T051 [P] [US4] Add failing shared-runner tests for bounded JSON execution, timeout/output limits, `save_run_log=True` compatibility, narration-wiki `False` behavior, redaction, process-group cancellation, and terminal return codes in `tests/test_subprocess_runner.py`
- [X] T052 [US4] Implement the bounded JSON helper and backward-compatible `save_run_log` option solely in `server/subprocess_runner.py`
- [X] T053 [P] [US4] Add failing router tests for derived campaign/session paths, fixed argument vectors, status JSON mapping, all eight POST-SSE actions, return-code categories, disconnect cleanup, no arbitrary argv, and no direct process launch in `tests/test_narration_wiki_routes.py`
- [X] T054 [US4] Implement strict request models, fixed CLI builders, bounded status adaptation, and streamed action endpoints in `server/routers/narration_wiki.py`
- [X] T055 [US4] Mount the narration-wiki router exactly once at `/api/narration-wiki` in `server/main.py`
- [X] T056 [P] [US4] Add failing static UI contract tests for route/step/sidebar presence, all nine public capabilities, no browser-authoritative state, existing token/control reuse, no feature color literals, page overflow ownership, and shared resize rules in `tests/test_narration_wiki_ui.py`
- [X] T057 [P] [US4] Create Playwright request mocks and selected/empty/recovery/long-evidence/wide-table/large-diff fixture states in `frontend/e2e/fixtures/narrationWiki.ts`
- [X] T058 [US4] Add failing Playwright scenarios for POST-SSE arbitrary chunks, nonzero completion, AbortController cancellation, status reload after every outcome, human Gate controls, exact 1280x720 viewport, exact 320x160 panels, both-axis scroll, and keyboard reachability in `frontend/e2e/narration-wiki.spec.ts`

### Implementation for User Story 4

- [X] T059 [US4] Add POST-capable fetch/ReadableStream SSE parsing and typed status plus all action adapters in `frontend/src/api/sse.ts` and `frontend/src/api/narrationWiki.ts`
- [X] T060 [US4] Register `/workflow/wiki`, workflow step 7, and sidebar `③ Narration Wiki` using existing navigation conventions in `frontend/src/router.ts`, `frontend/src/views/SessionWorkflow.vue`, and `frontend/src/components/layout/AppSidebar.vue`
- [X] T061 [P] [US4] Implement one-conflict-at-a-time source comparison, resolution, rationale, and ruling controls in `frontend/src/components/narration-wiki/ConflictRulingCard.vue`
- [X] T062 [P] [US4] Implement observed/budget/verdict/skipped measurement evidence with intrinsic table width and panel-owned scrolling in `frontend/src/components/narration-wiki/MeasurementTable.vue`
- [X] T063 [P] [US4] Implement one-pattern-at-a-time Problem/Root Cause/Corrective Strategy/evidence/tier Gate 1 controls in `frontend/src/components/narration-wiki/PatternGateCard.vue`
- [X] T064 [P] [US4] Implement staged reconsideration evidence, complete non-wrapping diff, before/after measurements, and explicit Gate 2 controls in `frontend/src/components/narration-wiki/ProposalGatePanel.vue`
- [X] T065 [US4] Assemble disk-reloading selection, dependency, collection, baseline, conflict, pattern, proposal, recovery, history, cancellation, and streamed-output workflow in `frontend/src/views/session/NarrationWiki.vue`
- [X] T066 [US4] Reuse existing colors, typography, controls, focus states, spacing, radii, and scrollbar skin while adding page overflow ownership and the shared 320x160 resizable-panel contract in `frontend/src/style.css` and `frontend/src/views/session/NarrationWiki.vue`

**Checkpoint**: Every CLI capability has a UI face with identical disk results and no relocated human judgment.

---

## Phase 7: User Story 5 - Seed Shared Knowledge Without Rule Forks (Priority: P2)

**Goal**: Read compatible companion-owned portable knowledge without writing it, keep named canon and guidance campaign-scoped, and persist explicit GM rulings when seed sources disagree.

**Independent Test**: Seed portable craft knowledge plus distinct Phandalin and OOTA guidance, verify neutral knowledge is visible in both contexts, named/caps/canon/targets never cross campaigns, incompatible capability metadata blocks completion, and narration rendering is byte-identical whether wiki directories exist or not.

### Tests for User Story 5

- [X] T067 [US5] Create valid/missing/malformed/incompatible companion manifests, portable pages/indexes, pending promotions, and distinct Phandalin/OOTA campaign guidance under `tests/fixtures/narration_wiki/portable/` and `tests/fixtures/narration_wiki/campaigns/`
- [X] T068 [P] [US5] Add failing companion contract tests for YAML/schema validation, source repository/revision, contract version 1, `campaign-resolved` guidance, both roles, read-only behavior, explicit dependency status, and campaign-local collection/measurement availability when the dependency is incomplete in `tests/test_narration_wiki_companion.py`
- [X] T069 [P] [US5] Add failing cross-campaign tests proving rulebook, narrator names, caps, examples, canon, evidence, and authorized proposal targets never leak between Phandalin and OOTA in `tests/test_narration_wiki_isolation.py`
- [X] T070 [P] [US5] Add failing renderer-isolation tests proving render modules never import/read either wiki tier and rendered bytes remain identical with wiki directories present or absent in `tests/test_narration_wiki_renderer_isolation.py`
- [X] T071 [P] [US5] Add failing portable-index tests for neutral visibility, named-content campaign defaults, explicit portable override, cross-tier slug ownership, immutable promotion handoffs, and pending synchronization in `tests/test_narration_wiki_indexes.py`

### Implementation for User Story 5

- [X] T072 [US5] Add `CompanionCapabilityManifest` parsing and exact deployed-manifest hashing without copied-guidance fallback in `session_doc/narration_wiki/models.py` and `session_doc/narration_wiki/indexes.py`
- [X] T073 [US5] Implement read-only portable page/index validation, campaign-local promotion handoffs, named-content routing safeguards, and derived `pending_portable_sync` reconciliation in `session_doc/narration_wiki/indexes.py` and `session_doc/narration_wiki/storage.py`
- [X] T074 [US5] Restrict proposal visibility and target resolution to compatible portable craft knowledge plus the selected campaign's authoritative guidance in `session_doc/narration_wiki/proposals.py` and `campaignlib/narration_context.py`
- [X] T075 [US5] Expose capability revision/roles, incompatibility reasons, pending promotions, and pattern ownership through CLI status/index results and the existing UI dependency panel in `session_doc/narration_wiki/cli.py` and `frontend/src/views/session/NarrationWiki.vue`

**Checkpoint**: Portable knowledge is reusable without repository writes, rule forks, campaign leakage, or renderer coupling.

---

## Phase 8: Polish and Cross-Cutting Validation

**Purpose**: Finish operator documentation, contract validation, full regression coverage, and persisted acceptance evidence.

- [X] T076 [P] Document every command, option, lifecycle state, exit category, artifact path, recovery action, and CLI example in `docs/cli/narration-wiki.md`
- [X] T077 [P] Document the prospective post-session workflow, companion deployment prerequisite, UI route, and issue #360 deferral in `docs/README.md` and reconcile executable acceptance steps in `specs/020-narration-wiki/quickstart.md`
- [X] T078 [P] Add contract tests that validate representative manifests, measurements, conflict rulings, capability manifests, and usability results against `specs/020-narration-wiki/contracts/*.schema.json` in `tests/test_narration_wiki_contracts.py`
- [X] T079 Run the complete backend suite after contract tests are present and fix any determinism, security, renderer-isolation, legacy-CLI, or subprocess regressions in `tests/`, `session_doc/narration_wiki/`, `campaignlib/`, and `server/`
- [X] T080 [P] Run `vue-tsc`, the production frontend build, and Playwright; fix any SSE, parity, established-style, 1280x720, 320x160, scrollbar, clipping, or keyboard failures in `frontend/src/` and `frontend/e2e/narration-wiki.spec.ts`
- [X] T081 Complete the timed isolated-fixture exercise, verify the deployed companion manifest names a compatible source repository/revision and both roles, and perform the final immutability audit from `specs/020-narration-wiki/quickstart.md`; then persist schema-valid Gate references, ruling path, 1280x720 viewport, 320x160 panel size, total/model/active seconds, and pass result in `specs/020-narration-wiki/validation/usability-result.json`

---

## Dependencies and Execution Order

### Phase Dependencies

- **Phase 1 — Setup**: Starts immediately.
- **Phase 2 — Foundational**: Depends on Setup and blocks every user story.
- **Phase 3 — US1 (P1)**: Depends on Foundational; establishes collection, baseline measurement, conflicts, and confirmed-pattern inputs.
- **Phase 4 — US2 (P1)**: Depends on US1's confirmed patterns and baseline measurement.
- **Phase 5 — US3 (P1)**: Depends on US1 and US2 so it can audit and recover the complete two-Gate loop.
- **Phase 6 — US4 (P2)**: Depends on all P1 public commands so bidirectional parity can be tested end to end.
- **Phase 7 — US5 (P2)**: Its fixture and isolation work may start after US1, but final status/UI integration depends on US4.
- **Phase 8 — Polish**: Depends on every story selected for release.

### User Story Dependency Graph

```text
Setup -> Foundation -> US1 -> US2 -> US3 -> US4 -> Polish
                                             /
                          --------> US5 -----
```

- **US1** is the independently testable MVP and includes the clarified baseline/conflict prerequisites.
- **US2** consumes confirmed patterns and the baseline measurement but has its own atomic lifecycle test.
- **US3** audits the completed P1 loop and has independent deterministic/recovery criteria.
- **US4** follows the engine because every final CLI capability must have a UI face.
- **US5** can develop backend isolation after US1; its UI dependency presentation integrates after US4.

### Within Each User Story

- Write the listed tests first and confirm they fail for the intended missing behavior.
- Add story-specific models before services that consume them.
- Complete deterministic read-only operations before mutations that consume their artifacts.
- Revalidate scope, hashes, lifecycle state, and explicit human ruling at every mutation boundary.
- Complete the story's independent test before advancing a dependent story.

---

## Parallel Execution Examples

### User Story 1

After T015, write the independent contract suites together:

```text
T016 collection/manifest tests
T017 scope and symlink tests
T018 legacy checker compatibility tests
T019 baseline measurement tests
T020 page/index tests
T021 seed-conflict tests
```

After their tests fail, T025 collection and T028 index parsing may proceed in parallel; T026 then unblocks T027, and T029/T030 integrate the Gate.

### User Story 2

After T031, run:

```text
T032 proposal authorization and snapshot tests
T033 reconsideration-basis tests
T034 Gate 2 transaction tests
```

T038 and T039 stay sequential because they edit `proposals.py`; T040 and the storage portion of T041 can proceed once the proposal hashes are stable.

### User Story 3

Run T043, T044, and T045 in parallel because they extend separate test files. Then implement T047, T048, and T049 in separate engine modules before T050 integrates CLI status.

### User Story 4

Backend and frontend characterization can overlap:

```text
T051-T052 shared subprocess seam
T053-T055 HTTP adapter and mount
T056 static UI contract
T057-T058 Playwright fixtures and scenarios
```

After T059/T060 establish API and navigation, T061-T064 implement four independent components in parallel before T065 assembles the page.

### User Story 5

After T067, run T068, T069, T070, and T071 in parallel. T072-T074 then implement capability, tier, and proposal isolation before T075 exposes the combined status.

---

## Implementation Strategy

### MVP First

1. Complete Setup and Foundational phases.
2. Complete US1 collection, baseline measurement, seed-conflict ruling, and per-pattern Gate 1 behavior.
3. Stop and run US1's independent test.
4. Demonstrate one explicitly selected session publishing one reviewed campaign pattern, rejecting another, and leaving every raw source unchanged.

### Incremental Delivery

1. **MVP — US1**: Safe collection, baseline evidence, conflict adjudication, and durable-pattern promotion.
2. **Atomic safety — US2**: One-file comparison with exact accept/retain or reject/restore behavior.
3. **Audit — US3**: Deterministic repeatability, index validation, duplicate refusal, and crash recovery.
4. **Access — US4**: Full CLI/UI parity with streamed progress and resize-safe existing-style UI.
5. **Reuse — US5**: Companion-owned portable knowledge with strict campaign and renderer isolation.

### Guardrails Retained Across All Phases

- Disk artifacts remain canonical; browser and model state never become authoritative.
- Baseline measurement precedes Gate 1, and both Gates require explicit human rulings.
- Empty session selection refuses and never means all sessions.
- Raw evidence is immutable, and proposal rejection restores exact bytes.
- The renderer never imports or reads either wiki tier.
- CampaignGenerator never writes the companion-owned portable deployment.
- Every UI capability uses established CampaignGenerator colors and controls.
- The page and every declared resizable panel own visible scrolling when content exceeds 1280x720 or 320x160.
- Wiki state is additive and prospective; no legacy workspace is silently migrated or probed.
- The general UI-style/scrolling constitution change remains tracked separately in issue #360 and is not part of this implementation.

---

## Notes

- `[P]` marks tasks that may run concurrently only after their stated prerequisite is complete.
- Companion maintainer/proposer model behavior remains outside this repository; fixtures and the read-only capability contract represent that boundary.
- Commit each logical red/green task pair separately.
- Stop at every checkpoint and run the independent story test before starting a dependent story.
