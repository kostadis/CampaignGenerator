# Tasks: Incremental Campaign Grounding and NPC Updates

**Input**: Design documents from `specs/039-incremental-campaign-updates/` (plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md)

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included. The spec's Success Criteria SC-001 to SC-009 are verification requirements, and the plan names a test module per seam, so test tasks are part of each story. They are not optional for this feature.

**Organization**: Tasks are grouped by user story (priority order from spec.md: US1–US4 are P1, US5 is P2) so each story can be implemented and tested independently.

**Execution model** (from plan.md "Execution Strategy"): Sonnet subagents implement tasks, Opus orchestrates and enforces phase gates, one code-review pass runs after the final phase, and remaining problems become GitHub issues.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US5, only in user story phases
- Every description includes the exact file path

## Path Conventions

Engine: `pipelines/summary_native/`. Server: `server/`. Frontend: `frontend/src/`. Tests: `tests/`. Feature docs: `specs/039-incremental-campaign-updates/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Package skeleton, guards, and the synthetic fixture that every story test depends on.

- [X] T001 Create package skeleton `pipelines/summary_native/delta/__init__.py` with an empty public surface and a module docstring that names Principle II checkpoints
- [X] T002 [P] Create synthetic campaign fixture `tests/fixtures/delta/campaign/` with `config/config.yaml`, `docs/` stubs, and `docs/summaries/` containing chapters 01–03 (one forge restart, one faction offer, one passing mention, one new NPC). No private campaign data.
- [X] T003 [P] Create `tests/fixtures/delta/campaign/docs/npcs/summary_native/publish_log.json` and two published dossier files (one at horizon ch02, one at ch01) matching the fixture's baseline
- [X] T004 [P] Create Principle V guard `tests/test_no_anthropic_in_delta.py`: AST walk failing on any `import anthropic` or `from anthropic` under `pipelines/summary_native/delta/`
- [X] T005 [P] Extend `tests/test_retrieve_render_isolation.py` so its scan includes `pipelines/summary_native/delta/`
- [X] T006 [P] Create `tests/test_delta_no_llm_in_records.py`: AST guard that `delta/plan.py`, `delta/sources.py`, `delta/census.py`, `delta/run.py`, `delta/receipt.py`, `delta/grounding_check.py` (the non-model part) make no `stream_api`/`call_api` calls, except the explicitly named propose functions

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared primitives every story uses: explicit source selection, full/sparse evidence types, run state, receipts, and the full-mode regression baseline. No user story work starts until this phase passes its gate.

**Gate**: `python -m pytest tests/ -k "delta_foundation or golden_full"` passes and the full-mode golden is byte-identical to the pre-change capture.

- [X] T007 Capture full-mode verifier golden outputs before any change: write `tests/test_verifier_golden_full.py` that runs `npc_verify.verify` over the fixture in full mode and compares against `tests/fixtures/delta/golden/verify_full.md` (generate that file now from the unmodified code)
- [X] T008 [P] Create `pipelines/summary_native/delta/plan.py`: `DeltaPlan` model per data-model.md (plan_id, operation_version, campaign_identity, products, stopping_point, sources, models, revision). An empty `sources` list raises a refusal with exit code 2 (Principle X). Test in `tests/test_delta_plan.py`.
- [X] T009 [P] Create `pipelines/summary_native/delta/sources.py`: explicit source ingestion. Returns a `SourceSelection` with `role` and `read_count` per role (parsed_new, parsed_historical, reused_artifact, integrity_only, model_input). Test in `tests/test_delta_sources.py`.
- [X] T010 Extend `pipelines/summary_native/validate.py` `scan()` with an optional `sources` argument (list of paths). When given, only those paths are parsed; when absent, existing behavior is unchanged. Refuse an empty list. Update `tests/test_validate*.py` if present; add the parse-count assertion to `tests/test_delta_sources.py`.
- [X] T011 Extend `pipelines/summary_native/corpus.py` `build_corpus()` to accept the same explicit `sources` list, reusing T010's selection (depends on T010).
- [X] T012 [P] Create `pipelines/summary_native/delta/evidence.py`: `FullEvidence` (wraps `CorpusIndex`) and `SparseEvidence` (explicit span list; `targets` contains exactly those spans, never chapter-membership entries). Test in `tests/test_delta_evidence.py`, including the case that a `[ch 001 / entry]` citation fails under `SparseEvidence` when no entry span is supplied.
- [X] T013 Refactor `pipelines/summary_native/npc_verify.py`: the citation check (`check_citations`, around lines 262–285) and any other `corpus_index.targets` consumers take an evidence-index abstraction. Full mode passes `FullEvidence`, which must reproduce current output exactly (depends on T007, T012).
- [X] T014 Run `tests/test_verifier_golden_full.py` and confirm the golden is unchanged. If it differs, stop and fix T013; do not update the golden (depends on T013).
- [X] T015 [P] Create `pipelines/summary_native/delta/run.py`: versioned run state file (`RunState`: stages, artifacts with sha256, status enum, members, counts). Use `scheduler.atomic_write_record` for writes and `scheduler.read_record` for reads. Test in `tests/test_delta_run_state.py`.
- [X] T016 [P] Create `pipelines/summary_native/delta/receipt.py`: completion receipt model (data-model.md Receipt). Assert no capability URL or token field exists. Test in `tests/test_delta_receipt.py`.
- [X] T017 [P] Extend `pipelines/summary_native/freshness.py` with a per-item dependency graph: `DependencyGraph` mapping nodes (draft, evidence, composition, shared source, identity ruling, rule, association) to consuming items. A change to a node yields exactly its consumers. Test in `tests/test_delta_freshness_graph.py`.
- [X] T018 Add the `delta` subcommand family to `pipelines/summary_native/cli.py` with shared flags only: `--campaign-dir`, `--config`, `--json`, `--force`, repeatable `--source` (no default). Every subcommand is registered as a stub that exits 2 with "not implemented" (XII: one spelling across the family). Test in `tests/test_delta_cli_family.py`.
- [X] T019 [P] Create `server/routers/summary_native_delta.py`: argv builder helper using `console_script("summary_native")`, bounded JSON via `run_bounded_json`, and SSE streaming helper. No pipeline logic in this file (Principle VI). Register the router in `server/main.py`. Test in `tests/test_delta_router_argv.py`.
- [X] T020 Add `server/routers/summary_native_delta.py` defaults from the owning config model only (no literals), following `server/ensemble_config_shared.py`. Add `tests/test_delta_config_defaults.py` that fails on a literal default in the router (Principle XII).

**Checkpoint**: Foundation ready. User stories can start. US1 and US2 may proceed in parallel after this point.

---

## Phase 3: User Story 1 - Update the Four Documents From One Reviewed Session (Priority: P1) 🎯 MVP

**Goal**: From the adopted Chapter 2–74 baseline and one selected chapter, produce four complete grounding candidates and a native complete-bundle preview, without parsing historical summaries.

**Independent Test**: Quickstart steps 2, 4, 5, 12 on the fixture. Parsed-historical count is 0 (SC-001). Untouched baseline bytes are identical (SC-002). Inherited citations resolve through baseline custody (SC-009).

### Tests for User Story 1

- [X] T021 [P] [US1] Write `tests/test_delta_baseline.py`: grounding baseline binds generation id and the four origin/live digests; a newer directory is never selected; drift is listed; unreviewed drift blocks use (FR-002, FR-003, G4)
- [X] T022 [P] [US1] Write `tests/test_delta_grounding_edits.py`: stable target IDs; rejection of unknown, duplicate, overlapping, and stale-before-digest edits; untouched bytes preserved; heading, table-width, and citation checks catch an accidentally deleted repeated heading (SC-002)
- [X] T023 [P] [US1] Write `tests/test_delta_grounding_e2e.py`: complete native grounding delta on the fixture with an inherited citation and a nested reference; a removed inherited support blocks with a targeted repair message; no synthetic full-corpus record written (SC-009)
- [X] T024 [P] [US1] Write `tests/test_delta_gate_delta_record.py`: the new delta record satisfies the complete-bundle gate only when every member is inherited-with-custody or produced-and-checked; `synth_record_complete` behavior is unchanged (FR-016, R6)

### Implementation for User Story 1

- [X] T025 [US1] Create `pipelines/summary_native/delta/baseline.py`: `GroundingBaseline` binding from the active generation's manifest and the four documents' origin and live sha256. Read identity from `pipelines/summary_native/promotion/history.py` and `manifest.py`; never choose by directory name (FR-002)
- [X] T026 [US1] Add per-member coverage to `delta/baseline.py`: timeline, reference tree, and reading-contract records each carry `coverage_through` and `gaps`; live prose coverage does not raise an inherited member's coverage (data-model.md GroundingBaseline)
- [X] T027 [US1] Implement adoption in `delta/baseline.py`: `adopt(resolve=...)` writes a new adoption record listing each drift hunk and its disposition. It never rewrites earlier generation or receipt files (FR-003, data-model.md "States")
- [X] T028 [US1] Create `pipelines/summary_native/delta/grounding_edits.py` (host side only): assign stable line IDs to the bound baseline, compute before-digests, validate proposals, and reconstruct documents from accepted edits while leaving untouched lines byte-identical (FR-006, FR-007, G1)
- [X] T029 [US1] Add the model step `propose_edits()` to `delta/grounding_edits.py`, separate from reconstruction. It calls `campaignlib.stream_api` only, takes numbered baseline lines and selected-source spans, and returns proposals with category and rationale. Its output is never applied directly (Principle II, R3)
- [X] T030 [US1] Implement decisions in `delta/grounding_edits.py`: `decide(proposal_id, decision)` writes a revisioned decision file. Unset or `discuss` blocks reconstruction (data-model.md EditProposal)
- [X] T031 [US1] Create `pipelines/summary_native/delta/grounding_check.py`: deterministic heading, table-width, and citation-target checks, plus a bounded consistency call through `campaignlib` that returns findings only. A model verdict never sets an approval (FR-015)
- [X] T032 [US1] Extend `pipelines/summary_native/claims/selection.py`: `_discovered_rows` and `mandatory_source_closure` accept an inherited-custody resolver so inherited citations resolve through baseline custody, not the Chapter-75-only corpus (G3, FR-016)
- [X] T033 [US1] Create `pipelines/summary_native/delta/lineage.py`: the `delta` record model (new model, not a subclass of `StrictPromotionModel`; research R8) with its completeness rule
- [X] T034 [US1] Extend `pipelines/summary_native/promotion/gates.py` with the `delta` record kind and its completeness rule. Leave `synth_record_complete` unchanged (R6)
- [X] T035 [US1] Extend `pipelines/summary_native/promotion/manifest.py` `_record_and_dependencies` to read a delta lineage record by pointer, without adding fields to any strict model (R8)
- [X] T036 [US1] Create `pipelines/summary_native/delta/grounding_publish.py`: digest-bound preview and apply that delegate to the existing `promotion/publish.py` and whole-generation activation. Apply requires a preview hash match (FR-020, FR-021)
- [X] T037 [US1] Wire the US1 CLI verbs into `pipelines/summary_native/cli.py`: `delta baseline status`, `delta baseline adopt`, `delta grounding propose|decide|check|preview|apply`, following `contracts/cli.md` exit codes (depends on T008–T036)
- [X] T038 [US1] Route the US1 endpoints in `server/routers/summary_native_delta.py`: `/plans/{id}/baseline`, `/plans/{id}/baseline/adopt`, `/plans/{id}/grounding/*`, per `contracts/http.md`. Each route only builds argv (depends on T019, T037)
- [X] T039 [US1] Add a `delta` plan creation path for grounding products with explicit `--source` selection and `--stop` in `delta/plan.py` and the `delta plan` CLI verb (depends on T008, T037)

**Checkpoint**: US1 is independently testable on the fixture. This is the MVP.

---

## Phase 4: User Story 2 - Update Only the Affected NPCs (Priority: P1)

**Goal**: Update only materially changed NPCs, draft new NPCs, attest passing mentions, and block stale or sparse-as-full candidates.

**Independent Test**: Quickstart steps 6 and 7 on the fixture. The changed NPC keeps its historical bytes. The passing mention is attested and its dossier is byte-identical. Freshness is scoped per dossier (SC-004, SC-005).

### Tests for User Story 2

- [X] T040 [P] [US2] Write `tests/test_delta_npc_baseline.py`: per-subject baseline from `publish_log.json`; an unpublished newer draft is ignored; broken publication-to-draft lineage produces a `repair_required` status (N1)
- [X] T041 [P] [US2] Write `tests/test_delta_census.py`: every fixture subject has one disposition; the passing mention is `mentioned_unchanged`; an unknown name is `unresolved`, never absent; an unregistered name and a deliberate exclusion are distinct (N1)
- [X] T042 [P] [US2] Write `tests/test_delta_associations.py`: approved associations only enter drafting evidence; `rejected` and `discuss` never do; a scoped short name never adds a global alias to the registry (N4)
- [X] T043 [P] [US2] Write `tests/test_delta_attest.py`: attestation binds the exact published sha256; the dossier file is byte-identical after attestation; a missing reason is refused (N5, #585)
- [X] T044 [P] [US2] Write `tests/test_delta_freshness.py`: changing B's evidence stales B and not A; changing the shared source stales both; changing a draft requires a new exact-draft sign-off (SC-005, N3)
- [X] T045 [P] [US2] Write `tests/test_delta_secrets.py`: Secrets canary strings appear in no drafting prompt, intermediate artifact, or player-facing output; a player-audience request touching GM evidence is refused before content is exposed (SC-007, FR-012)
- [X] T046 [P] [US2] Write `tests/test_delta_npc_e2e.py`: changed, new, mention, and mixed-horizon cases complete through public operations with no sign-off override (SC-004)

### Implementation for User Story 2

- [X] T047 [US2] Create `pipelines/summary_native/delta/npc_baseline.py`: per-subject baseline selection from `publish_log.json` and each published file's header digest (`npc_publish.published_body_sha`); `repair_required` for a hand-edited target, missing evidence, or broken lineage (N1, data-model.md NpcBaseline)
- [X] T048 [US2] Create `pipelines/summary_native/delta/census.py`: disposition for each subject (`changed`, `new`, `mentioned_unchanged`, `absent_from_selected`, `deferred`, `excluded`, `unresolved`) computed from the selected new sources and the registry. Indirect references are flagged for review, never treated as presence (N1, FR-011)
- [X] T049 [US2] Create `pipelines/summary_native/delta/associations.py`: model proposes scoped associations (campaignlib call only); `decide()` records approve, reject, discuss, or unresolved with a revision. The registry is never written by this module (N4, R3)
- [X] T050 [US2] Create `pipelines/summary_native/delta/npc_update.py`: builds drafting input from exact reused historical blocks, selected new evidence, and manual material, and never from published composition bytes. Calls the existing `npc_draft.run_draft` and `_resume_draft_record` so resume and dispatch are reused (FR-012, R7)
- [X] T051 [US2] Wire sparse verification into `npc_update.py`: run the existing `npc_verify.verify` with `SparseEvidence` (from T012/T013) built from the selected spans. Caller-supplied PASS is rejected (N2, FR-005)
- [X] T052 [US2] Create `pipelines/summary_native/delta/attest.py`: records an unchanged attestation bound to the publication sha256, added sources, rulings, and reason. Never edits the dossier (N5, FR-013)
- [X] T053 [US2] Extend `pipelines/summary_native/npc_publish.py` `_current_draft_signoff` to consult the per-item dependency graph (T017) so only actual consumers are stale (N3, FR-014)
- [X] T054 [US2] Extend `pipelines/summary_native/npc_publish.py` `publish()` with per-member outcome receipts and a reconciliation step for a crash between target write and publish-log update. Document the semantics as independent members, not a batch (FR-019, C1)
- [X] T055 [US2] Add US2 CLI verbs to `pipelines/summary_native/cli.py`: `delta census`, `delta associate propose|decide`, `delta npc draft|verify|attest|publish`, per `contracts/cli.md`. `publish` takes explicit `--member` and has no "all" option (Principle X)
- [X] T056 [US2] Route US2 endpoints in `server/routers/summary_native_delta.py` per `contracts/http.md` (depends on T019, T055)

**Checkpoint**: US2 is independently testable. US1 and US2 can run in parallel after Phase 2.

---

## Phase 5: User Story 3 - Review and Apply the Exact Intended Update (Priority: P1)

**Goal**: The GM reviews concrete candidates and the publication effect. Each approval scope is distinct, and a change to any bound input invalidates the affected approval.

**Independent Test**: Quickstart step 7 and the review-binding tests. Change one bound input before apply; apply is refused as stale (SC-005).

### Tests for User Story 3

- [X] T057 [P] [US3] Write `tests/test_delta_review_binding.py`: binding hashes match the candidate, plan, evidence, and rules; a change to any of them makes the binding stale; approval scopes (draft, attestation, association, publication) cannot substitute for each other (FR-017)
- [X] T058 [P] [US3] Write `tests/test_delta_review_diff.py`: diffs for existing prose, full prose for new dossiers, evidence, exact hashes, coverage, and inherited findings all render; a Discuss or unsaved decision blocks the affected action (Story 3 acceptance 1, 3)

### Implementation for User Story 3

- [X] T059 [US3] Create `pipelines/summary_native/delta/review_binding.py`: `ReviewBinding` record (data-model.md) with exact candidate, plan, evidence, and rule hashes; decision revision; approval scope; inherited and outstanding findings (FR-017)
- [X] T060 [US3] Create `pipelines/summary_native/delta/diff_view.py`: renders existing-prose diffs, full new-dossier prose, evidence, hashes, coverage, and findings as one review document. Used by both the CLI and the page (FR-017, Principle IX)
- [X] T061 [US3] Integrate with `pipelines/summary_native/review/cli.py`: when scope is known, create a single combined review handoff that reuses prior valid authorizations (`_create_verified_dossier_review`, `_npc_signoff_items`) and requires fresh review only for affected changes
- [X] T062 [US3] Make apply and publish check the binding: `delta/grounding_publish.py` and `delta/npc_update.py` refuse with exit code 3 when a bound hash has changed (FR-020, SC-005)
- [X] T063 [US3] Add `delta review show` and `delta review handoff` CLI verbs in `pipelines/summary_native/cli.py`, per `contracts/cli.md`
- [X] T064 [US3] Route `GET /plans/{id}/review` and `POST /plans/{id}/review/handoff` in `server/routers/summary_native_delta.py` (depends on T019, T063)

**Checkpoint**: US3 is independently testable. Approvals are scoped and stale-aware.

---

## Phase 6: User Story 4 - Resume and Publish With Honest Outcomes (Priority: P1)

**Goal**: Interrupt at any durable boundary and resume without duplicate approvals or publications. Report partial and held outcomes honestly.

**Independent Test**: Failure injection at each boundary in research R7, then `delta run resume`. Completed compatible stages make zero model calls, and no content write happens on an identical replay (SC-006).

### Tests for User Story 4

- [X] T065 [P] [US4] Create `tests/support/delta_faults.py`: an injection harness that raises at named boundaries (evidence write, model output, verify, review creation, sign-off, first publish, target-before-log, log-before-receipt, receipt creation)
- [X] T066 [P] [US4] Write `tests/test_delta_run_resume.py`: for each injected boundary, `resume` reuses completed compatible stages by digest, performs zero model calls for them, creates no duplicate approval, and reconciles target-before-log (SC-006)
- [X] T067 [P] [US4] Write `tests/test_delta_batch_invariance.py`: changing batch size does not change selected subjects or semantic outcomes (FR-018, Story 4 acceptance 6)
- [X] T068 [P] [US4] Write `tests/test_delta_partial_outcome.py`: a held NPC keeps its old publication; a required held dependency blocks grounding publication; a mixed result is `partial`, never `complete`; an identical completed replay performs no content write (Story 4 acceptance 4)

### Implementation for User Story 4

- [X] T069 [US4] Implement stage execution in `pipelines/summary_native/delta/run.py`: each stage records its inputs' digests and reuses a completed stage whose inputs are unchanged, without a model call (FR-018)
- [X] T070 [US4] Materialize work batches from the plan before dispatch in `delta/run.py`. Dispatch goes through the existing `scheduler.Scheduler` and `reconcile_items`, not a new engine (FR-018, R7)
- [X] T071 [US4] Map grounding activation recovery onto the existing `promotion/recovery.py` by operation identity in `delta/grounding_publish.py`. An ambiguous activation is inspected and recovered, never re-run blindly (FR-019, Story 4 acceptance 2)
- [X] T072 [US4] Implement `partial` and `recovery_required` status derivation in `delta/run.py` from per-member outcomes, with dependency-hold blocking (FR-019, Story 4 acceptance 4–5)
- [X] T073 [US4] Add `delta run status`, `delta run resume`, and `delta receipt` CLI verbs in `pipelines/summary_native/cli.py`, per `contracts/cli.md`
- [X] T074 [US4] Generate the completion receipt in `delta/receipt.py` from run state: selected chapters, inherited coverage and gaps, changed/new/carried/held subjects, publication hashes, checks, decisions, read and call counts, recovery state (FR-024)
- [X] T075 [US4] Route `GET /plans/{id}/status`, `POST /plans/{id}/resume`, `GET /plans/{id}/receipt` in `server/routers/summary_native_delta.py` (depends on T019, T073)

**Checkpoint**: US4 is independently testable. The run is recoverable and honest after restart.

---

## Phase 7: User Story 5 - Use the Workflow Without Local Glue (Priority: P2)

**Goal**: The same update runs from the CLI or the application with the same durable state. Worktree transfer preserves campaign identity, and review decisions survive a server restart.

**Independent Test**: Parity test (SC-008) and a restart test (FR-023). The page shows the same status as `delta run status`.

### Tests for User Story 5

- [X] T076 [P] [US5] Write `tests/test_delta_parity.py`: each `contracts/http.md` route's argv equals its `contracts/cli.md` command; the same inputs produce identical plan, decision, and receipt records after timestamps are removed (SC-008, Principle XI)
- [X] T077 [P] [US5] Write `tests/test_delta_restart.py`: saved decisions and the status banner survive a server restart; no capability URL or token appears in any response or receipt (FR-023)
- [X] T078 [P] [US5] Write `tests/test_delta_transfer.py`: a verified worktree or artifact transfer preserves canonical campaign identity without editing `campaign.json` or the moved-campaign guard (FR-022, Story 5 acceptance 2)
- [X] T079 [P] [US5] Create `frontend/src/views/grounding/DeltaRun.test.ts` (Vitest): stepper renders stages from `/status`; "select all" writes every resolved chapter into the explicit list and sends no implicit set (Principle X); status banner shows stale, partial, and recovery states on load

### Implementation for User Story 5

- [X] T080 [US5] Create `pipelines/summary_native/delta/transfer.py`: verified canonical and worktree binding that checks campaign identity and refuses an unverified transfer (FR-022)
- [X] T081 [US5] Add `delta transfer verify|bind` CLI verbs in `pipelines/summary_native/cli.py`
- [X] T082 [US5] Complete `server/routers/summary_native_delta.py` so every operation in `contracts/http.md` exists and returns the CLI record (depends on T038, T056, T064, T075)
- [X] T083 [US5] Create the page `frontend/src/views/grounding/DeltaRun.vue`: stage stepper, explicit chapter picker, census, decisions, and receipt. Each stage shows the files it produced (Principle VIII). The page holds no state the CLI cannot read (Principle IX).
- [X] T084 [US5] Add the `/grounding/delta` route in `frontend/src/router.ts` and the delta API client module in `frontend/src/` (depends on T083)
- [X] T085 [US5] Add a link from `frontend/src/views/GroundingDocs.vue` to `/grounding/delta`

**Checkpoint**: All user stories are complete. The CLI and the page are at parity.

---

## Final Phase: Polish & Cross-Cutting Concerns

**Purpose**: Documentation correction, full validation, and the single code-review pass.

- [X] T086 Correct outdated operator text in `docs/cli/grounding_docs.md` and `docs/cli/summary_native_howto.md` that describes manual grounding copying. Distinguish three paths: existing cache or full-range rerender, native delta generation and publication, and explicit local editable-live correction (spec, Implementation section)
- [X] T087 [P] Write `docs/cli/delta_howto.md`: task-oriented guide for one reviewed session, a changed NPC, a passing mention, a new NPC, adoption, and recovery, with every refusal and exit code decoded
- [X] T088 [P] Update `docs/README.md` index to include `docs/cli/delta_howto.md`
- [X] T089 Run `python -m pytest tests/` and confirm no regression from the Phase 2 golden (quickstart step 1)
- [X] T090 Run `cd frontend && npm test && npm run build` (quickstart step 11 and the page tests)
- [X] T091 Run quickstart steps 2–8, 10, 11, 12 on the synthetic fixture and record results in `specs/039-incremental-campaign-updates/validation.md`
- [X] T092 [P] Verify Principle compliance by searching the diff: no `import anthropic` under `delta/` (T004), no literal defaults in `server/routers/summary_native_delta.py` (T020), no `--all` or implicit-all option in any `delta` command (Principle X)
- [ ] T093 Manual acceptance (not CI): replay quickstart step 9 against the reference Chapter 75 inputs in a worktree and record the outcome in the PR description. Do not commit campaign data.
- [X] T094 Single code-review pass over the completed implementation. Fix real findings in that pass. Every problem that remains is filed as a GitHub issue linked to this spec, not left as a comment or a task note (user direction, 2026-11-06).

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup; blocks every story. T007 must run before T013.
- **US1 (Phase 3)**: depends on Phase 2. This is the MVP.
- **US2 (Phase 4)**: depends on Phase 2. Independent of US1 except the shared gate code (T034) is not needed by NPC work.
- **US3 (Phase 5)**: depends on US1 and US2 (it binds their candidates).
- **US4 (Phase 6)**: depends on US1 and US2 (it resumes their stages).
- **US5 (Phase 7)**: depends on all stories it exposes (T082 needs T038, T056, T064, T075).
- **Polish (Final)**: depends on all stories.

### Story dependencies

- **US1**, **US2**: independent after Phase 2
- **US3**, **US4**: depend on US1 and US2
- **US5**: depends on US1–US4

### Within each story

Tests first (they should fail), then models and records, then services, then CLI verbs, then routes.

### Parallel opportunities

- Setup: T002, T003, T004, T005, T006 in parallel
- Foundational: T008, T009, T012, T015, T016, T017, T019 in parallel; T010 then T011; T007 then T013 then T014
- US1 tests T021–T024 in parallel; US2 tests T040–T046 in parallel
- US1 and US2 implementation can run in parallel by two Sonnet subagents once Phase 2 passes
- US4 tests T065–T068 in parallel
- US5 tests T076–T079 in parallel

---

## Parallel Example: User Story 1

```text
# Tests for US1 together:
Task: "T021 tests/test_delta_baseline.py"
Task: "T022 tests/test_delta_grounding_edits.py"
Task: "T023 tests/test_delta_grounding_e2e.py"
Task: "T024 tests/test_delta_gate_delta_record.py"
```

---

## Implementation Strategy

### MVP first (User Story 1 only)

1. Phase 1 (Setup), then Phase 2 (Foundational), with the gate passing
2. Phase 3 (US1)
3. **Stop and validate**: quickstart steps 2, 4, 5, 12 pass on the fixture
4. Only then start US2

### Incremental delivery

1. Foundation, then US1 (MVP: grounding delta from one session)
2. Add US2 (NPC updates), validated by quickstart steps 6–7
3. Add US3 and US4 (review and resume), validated by quickstart step 8
4. Add US5 (parity and page), validated by quickstart step 11
5. Polish, then the single review pass (T094)

### Ordering note

The spec orders stories by priority (US1 grounding, then US2 NPC). plan.md's delivery order runs the NPC path before the grounding path. This file follows the spec's priority order. The two are independent after Phase 2, so the order can be changed without rework if the user prefers the plan's sequence.

---

## Completion Summary

- **Total tasks**: 94
- **Setup**: 6 (T001–T006)
- **Foundational**: 14 (T007–T020)
- **US1 (grounding, P1)**: 19 (T021–T039), MVP
- **US2 (NPC, P1)**: 17 (T040–T056)
- **US3 (review, P1)**: 8 (T057–T064)
- **US4 (resume, P1)**: 11 (T065–T075)
- **US5 (workflow, P2)**: 10 (T076–T085)
- **Polish**: 9 (T086–T094)

### Format validation

Every task starts with `- [ ]`, has a sequential ID, carries `[P]` only where it is parallelizable, carries a `[USn]` label only in story phases, and names a file path. Tasks T001–T006 and T007–T020 carry no story label, as required for Setup and Foundational. The Polish tasks carry no story label.
