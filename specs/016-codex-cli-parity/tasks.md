---

description: "Dependency-ordered implementation tasks for Codex CLI parity across all production CLIs"
---

# Tasks: Codex CLI Parity Across CLIs

**Input**: Design documents from `/specs/016-codex-cli-parity/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Required by the feature specification. Test tasks appear before their corresponding implementation tasks and must fail for the intended reason before implementation begins.

**Organization**: Tasks are grouped by user story so each story can be implemented and tested as an explicit increment.

**Agent policy**: Sol owns orchestration, dependency sequencing, integration decisions, and review gates. Luna performs all coding and test implementation with non-overlapping file ownership inside each parallel wave.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Parallelizable after its stated dependencies because it owns different files.
- **[Story]**: Maps the task to a user story from `spec.md`.
- Every task names the files it changes or validates.

## Phase 1: Setup (Feature-15 Baseline and Test Fixtures)

**Purpose**: Establish the merged feature-15 adapter as the only implementation baseline and prepare deterministic Codex child fixtures.

- [X] T001 Sol integrates merged PR #350 without reimplementing it and verifies the feature-15 baseline in `campaignlib/api/codex_cli.py`, `campaignlib/api/client.py`, `session_doc/check_consistency.py`, and `tests/test_codex_cli_backend.py`
- [X] T002 [P] Luna creates a reusable fake isolated Codex executable/process harness for direct and structured turns in `tests/helpers/fake_codex_cli.py`
- [X] T003 [P] Luna adds structured response fixtures matching `contracts/brokered-turn.schema.json` in `tests/fixtures/codex_cli/direct_success.json`, `tests/fixtures/codex_cli/broker_multi_action.json`, `tests/fixtures/codex_cli/broker_invalid.json`, `tests/fixtures/codex_cli/broker_empty.json`, and `tests/fixtures/codex_cli/broker_tool_error.json`

**Checkpoint**: Feature 15 passes unchanged and later tests can exercise Codex transport without authentication or network access.

---

## Phase 2: Foundational (Canonical Vocabulary and Model Provenance)

**Purpose**: Create the shared selection and discovery seams that block every story.

**⚠️ CRITICAL**: No user-story implementation begins until this phase passes Sol review.

- [X] T004 [P] Luna writes failing canonical-backend, compatibility, explicit-versus-inherited model, empty-model, and legacy-default tests in `tests/test_default_model_resolution.py` and `tests/test_openrouter_seam.py`
- [X] T005 [P] Luna replaces the stale 22-entry assumptions with failing source-discovery assertions for the exact 30-command inventory, 26 shared registrars, four hand-written choice lists, and four runtime dispatchers in `tests/test_backend_seam_guardrails.py` and `tests/test_batch_flag_uniformity.py`
- [X] T006 Luna makes `Backend`, `BACKENDS`, and `compatible()` the canonical provider vocabulary, including case-insensitive Codex rejection of `claude-*`, in `campaignlib/selection.py` after T004
- [X] T007 Luna implements the shared omission-aware CLI model resolver, preserves each command's optional `legacy_default`, and makes `add_backend_args()` consume `BACKENDS` in `campaignlib/api/client.py` after T006
- [X] T008 Luna replaces repeated server backend literals with the canonical type without changing persisted layouts in `server/platform_config_shared.py`, `server/ensemble_config_shared.py`, and `server/session_editor_config_shared.py` after T006
- [X] T009 Sol reviews the foundation against `specs/016-codex-cli-parity/contracts/cli-family.md` and runs `tests/test_default_model_resolution.py`, `tests/test_openrouter_seam.py`, `tests/test_backend_seam_guardrails.py`, and `tests/test_batch_flag_uniformity.py`

**Checkpoint**: One vocabulary and one model-provenance rule exist, and automated discovery accounts for all 30 production commands.

---

## Phase 3: User Story 1 - Run Any CampaignGenerator CLI with a Codex Subscription (Priority: P1) 🎯 MVP

**Goal**: Every direct command and dispatcher accepts or forwards `codex-cli`, uses the saved subscription login, and fails without provider fallback.

**Independent Test**: With fake Codex child execution and metered keys removed, run one direct command from each of the four families plus both dispatcher chains; confirm normal output, correct child argv/model omission, actionable failures, and zero fallback attempts.

### Tests for User Story 1

- [X] T010 [P] [US1] Luna writes failing direct and basic brokered adapter tests for saved-login environment handling, model precedence, system text blocks, actionable failures, cleanup, and no fallback in `tests/test_codex_cli_backend.py`
- [X] T011 [P] [US1] Luna writes failing parametrized parser/help/model-resolution coverage for all 26 direct model-bearing commands in `tests/test_codex_cli_family.py`
- [X] T012 [P] [US1] Luna writes failing backend/model forwarding tests for `sd_agent` and the `ensemble_batch -> ensemble -> ensemble_extract -> extract_facts` chain in `tests/test_sd_agent.py`, `tests/test_ensemble_batch_flag.py`, and `tests/test_ensemble_dispatch.py`

### Implementation for User Story 1

- [X] T013 [US1] Luna refactors the feature-15 child runner for shared direct/structured execution, accepts ordered system text blocks, and adds the minimal brokered response facade in `campaignlib/api/codex_cli.py` after T010
- [X] T014 [US1] Luna exposes the Codex brokered-message capability and makes `call_api_with_tools()` select it provider-neutrally while preserving all other providers in `campaignlib/api/client.py` after T013
- [X] T015 [P] [US1] Luna migrates the session-document family to omission-aware model resolution and consistent Codex help in `session_doc/check_consistency.py`, `session_doc/enhance_summary.py`, `session_doc/scene_extract.py`, `session_doc/sd_consistency.py`, `session_doc/sd_plan.py`, `session_doc/sd_narrate.py`, and `session_doc/vtt_voice_compare.py` after T007 and T014
- [X] T016 [P] [US1] Luna migrates preparation, ingest, search, and integration commands to omission-aware model resolution in `pipelines/session_prep/prep.py`, `pipelines/session_prep/transform.py`, `pipelines/content_ingest/dnd_sheet.py`, `pipelines/rlm/query.py`, and `scabard_sdk/scabard_sync.py` after T007 and T014
- [X] T017 [P] [US1] Luna migrates all eight grounding commands while preserving intentional `None` defaults and opt-in synthesis behavior in `pipelines/grounding/planning.py`, `pipelines/grounding/party.py`, `pipelines/grounding/make_tracking.py`, `pipelines/grounding/distill.py`, `pipelines/grounding/campaign_state.py`, `pipelines/grounding/npc_table.py`, `pipelines/grounding/grounding_sections.py`, and `pipelines/grounding/thread_registry.py` after T007 and T014
- [X] T018 [P] [US1] Luna migrates the six direct ensemble commands, including the plural-endpoint exception, while preserving DGX-selected `None` defaults in `pipelines/ensemble/synthesise_world_state.py`, `pipelines/ensemble/synthesise_polish.py`, `pipelines/ensemble/extract_facts.py`, `pipelines/ensemble/facts_to_state.py`, `pipelines/ensemble/narrate_chapter.py`, and `pipelines/ensemble/polish.py` after T007 and T014
- [X] T019 [P] [US1] Luna forwards canonical backend and explicit-or-omitted model intent through the four runtime dispatchers in `session_doc/sd_agent.py`, `pipelines/ensemble/ensemble.py`, `pipelines/ensemble/ensemble_batch.py`, and `pipelines/ensemble/ensemble_extract.py` after T007 and T014
- [X] T020 [US1] Luna adds the four-family fake-child acceptance path and no-credential/no-fallback assertions in `tests/test_codex_cli_family.py` and `tests/test_no_credential_gate.py` after T015-T019
- [X] T021 [US1] Sol reviews every changed command against the 30-row inventory in `specs/016-codex-cli-parity/contracts/cli-family.md` and runs `tests/test_codex_cli_backend.py`, `tests/test_codex_cli_family.py`, `tests/test_no_credential_gate.py`, `tests/test_sd_agent.py`, `tests/test_ensemble_batch_flag.py`, and `tests/test_ensemble_dispatch.py`

**Checkpoint**: All 30 commands expose one Codex spelling; 26 direct callers reach the shared adapter and four dispatchers preserve selection without starting validation-only children.

---

## Phase 4: User Story 2 - Preserve Each Workflow's Established Contract (Priority: P1)

**Goal**: Changing only the backend preserves selected input, context order, stage boundaries, checkpoints, resume/caching behavior, and artifact destinations.

**Independent Test**: Compare fixed baseline and fake-Codex fixtures from each workflow family; request material/order, explicit work sets, skip/resume decisions, stage transitions, and resulting disk paths must match.

### Tests for User Story 2

- [X] T022 [P] [US2] Luna writes failing sequential, cache-marked system-prefix, streaming-shaped final-chunk, and no-extra-call parity tests in `tests/test_campaignlib_pipeline.py` and `tests/test_scene_extract.py`
- [X] T023 [P] [US2] Luna writes failing session-document artifact, skip/resume, force, issue-count, voice-comparison, and checkpoint parity tests in `tests/test_editor_pipeline.py`, `tests/test_sd_agent.py`, `tests/test_check_consistency_batch.py`, `tests/test_vtt_voice_compare_reader.py`, and `tests/test_vtt_voice_compare_batch.py`
- [X] T024 [P] [US2] Luna writes failing prep, transform, PDF ingest, query, and Scabard output-path/request-boundary tests in `tests/test_prep.py`, `tests/test_dnd_sheet.py`, `tests/test_query.py`, and `tests/test_scabard_sync.py`
- [X] T025 [P] [US2] Luna writes failing grounding selected-input, cached extraction, opt-in synthesis, and artifact-path parity tests in `tests/test_grounding_backend.py` and `tests/test_campaignlib_pipeline.py`
- [X] T026 [P] [US2] Luna writes failing ensemble fan-out, mixed-result, explicit-selection, resume, merge, synthesis-polish, narration-approval, and HTML-review boundary tests in `tests/test_ensemble_pipeline.py`, `tests/test_ensemble_chapters.py`, `tests/test_facts_to_state.py`, `tests/test_synthesise_polish.py`, and `tests/test_narrate_chapter.py`

### Implementation for User Story 2

- [X] T027 [P] [US2] Luna preserves direct/sequential request assembly and complete-final-chunk behavior without manufacturing calls in `campaignlib/pipelines.py`, `campaignlib/scenes.py`, and `campaignlib/api/client.py` after T022
- [X] T028 [P] [US2] Luna fixes any session-family parity failures while retaining normal files and human stage boundaries in `session_doc/enhance_summary.py`, `session_doc/scene_extract.py`, `session_doc/sd_agent.py`, `session_doc/sd_consistency.py`, `session_doc/sd_plan.py`, `session_doc/sd_narrate.py`, and `session_doc/vtt_voice_compare.py` after T023
- [X] T029 [P] [US2] Luna fixes any preparation, ingest, search, and Scabard parity failures without changing selected scope or output locations in `pipelines/session_prep/prep.py`, `pipelines/session_prep/transform.py`, `pipelines/content_ingest/dnd_sheet.py`, `pipelines/rlm/query.py`, and `scabard_sdk/scabard_sync.py` after T024
- [X] T030 [P] [US2] Luna fixes any grounding parity failures while preserving extract/cache/synthesize separation in `pipelines/grounding/planning.py`, `pipelines/grounding/party.py`, `pipelines/grounding/make_tracking.py`, `pipelines/grounding/distill.py`, `pipelines/grounding/campaign_state.py`, `pipelines/grounding/npc_table.py`, `pipelines/grounding/grounding_sections.py`, and `pipelines/grounding/thread_registry.py` after T025
- [X] T031 [P] [US2] Luna fixes any ensemble fan-out, dispatcher, resume, and approval-boundary failures in `pipelines/ensemble/synthesise_world_state.py`, `pipelines/ensemble/synthesise_polish.py`, `pipelines/ensemble/extract_facts.py`, `pipelines/ensemble/facts_to_state.py`, `pipelines/ensemble/narrate_chapter.py`, `pipelines/ensemble/polish.py`, `pipelines/ensemble/ensemble.py`, `pipelines/ensemble/ensemble_batch.py`, and `pipelines/ensemble/ensemble_extract.py` after T026
- [X] T032 [US2] Sol reviews request and artifact diffs against `specs/016-codex-cli-parity/spec.md` FR-007 through FR-013 and runs the US2 tests in `tests/test_campaignlib_pipeline.py`, `tests/test_scene_extract.py`, `tests/test_editor_pipeline.py`, `tests/test_prep.py`, `tests/test_grounding_backend.py`, and `tests/test_ensemble_pipeline.py`

**Checkpoint**: Codex changes transport only; existing workflow scope, disk truth, and human checkpoints remain identical.

---

## Phase 5: User Story 3 - Support Existing Interaction Shapes Safely (Priority: P1)

**Goal**: Direct text, sequential/fan-out calls, and the complete polish critique/edit loop work while every Codex child remains ephemeral, tool-free, read-only, and isolated.

**Independent Test**: Run direct, multi-action, error-feedback, finish, malformed-history, malformed-output, timeout, and repeated-turn fixtures; only parent-validated polish operations may affect the selected draft and no child receives executable capabilities.

### Tests for User Story 3

- [X] T033 [P] [US3] Luna writes failing typed transcript, ordered role/block, multiple action, opaque ID, stop-reason, usage-null, malformed JSON, unresolved ID, and direct-shape refusal tests in `tests/test_codex_cli_backend.py`
- [X] T034 [P] [US3] Luna writes a failing real-client/fake-child polish integration suite covering all declared operations, finish, tool-result replay, loop limits, and normal trace behavior in `tests/test_polish_codex.py`
- [X] T035 [P] [US3] Luna strengthens malformed, unknown, ambiguous, out-of-scope, repeated, and conflicting operation feedback assertions in `tests/test_polish.py`

### Implementation for User Story 3

- [X] T036 [US3] Luna completes strict transcript normalization, output-schema file creation, host-assigned IDs, argument-object parsing, usage facade, and fail-closed result conversion in `campaignlib/api/codex_cli.py` after T033
- [X] T037 [US3] Luna preserves provider-neutral operation dispatch, `ToolContext` scope, error feedback, trace logging, and the 40-turn limit in `campaignlib/api/client.py` and `pipelines/ensemble/polish.py` after T034-T036
- [X] T038 [US3] Luna adds regression coverage that direct Codex messages still reject images, arbitrary tools, and unsupported multi-turn input in `tests/test_codex_cli_backend.py` after T036
- [X] T039 [US3] Sol performs a security review against `specs/016-codex-cli-parity/contracts/adapter.md` and runs `tests/test_codex_cli_backend.py`, `tests/test_polish_codex.py`, and `tests/test_polish.py`, inspecting exact argv, environment, cwd uniqueness, and cleanup for every exit state

**Checkpoint**: Polish works through application-brokered operations without enabling Codex tools, persisted sessions, repository context, or out-of-scope writes.

---

## Phase 6: User Story 4 - Choose Codex Consistently in the CLI and UI (Priority: P2)

**Goal**: Manual and UI launches share one backend/model rule, every applicable selector offers Codex, and all 30 capabilities have a direct or valid transitive UI invocation.

**Independent Test**: Resolve equivalent CLI and UI selections for every configuration tier, inspect each command builder, and exercise the 30-row reachability map; argv and model intent must match, old config must load, and each new face must expose its normal disk-backed output.

### Tests for User Story 4

- [X] T040 [P] [US4] Luna writes failing request/service/platform/literal model-origin, inherited-Claude omission, explicit-model forwarding/refusal, and config API tests in `tests/test_platform_config_service.py`, `tests/test_service_selection_override.py`, and `tests/test_config_routes.py`
- [X] T041 [P] [US4] Luna writes failing old-four-profile load, default Codex profile, YAML alias, backend-specific model isolation, and round-trip tests in `tests/test_session_editor_config_service.py` and `tests/test_editor_service_integration.py`
- [X] T042 [P] [US4] Luna writes failing existing-selector and router-builder Codex forwarding tests in `tests/test_selection_preview.py`, `tests/test_selection_isolation.py`, `tests/test_grounding_backend.py`, `tests/test_ensemble_gates.py`, and `tests/test_editor_pipeline.py`
- [X] T043 [P] [US4] Luna adds a failing 30-row direct/transitive/new-face reachability guard in `tests/test_backend_seam_guardrails.py`
- [X] T044 [P] [US4] Luna writes failing scene-editor route tests for direct `check_consistency`, `vtt_voice_compare`, and post-assemble `polish` invocation and outputs in `tests/test_editor_pipeline.py` and `tests/test_editor_service_integration.py`
- [X] T045 [P] [US4] Luna writes failing Session Prep `transform` and Ensemble `synthesise_polish`/per-chapter `narrate_chapter` route tests in `tests/test_prep.py`, `tests/test_ensemble_gates.py`, `tests/test_ensemble_chapters.py`, and `tests/test_synthesise_polish.py`
- [X] T046 [P] [US4] Luna writes failing Scabard request-body secret, child-only environment, argv/log/error redaction, output, and router-mount tests in `tests/test_scabard_sync.py` and `tests/test_integrations_routes.py`

### Implementation for User Story 4

- [X] T047 [P] [US4] Luna implements origin-aware Codex resolution and canonical config exposure while leaving generic argument emitters provider-neutral in `campaignlib/selection.py`, `server/platform_config_service.py`, `server/platform_config_shared.py`, `server/backend_forwarding.py`, and `server/routers/config_routes.py` after T040
- [X] T048 [P] [US4] Luna adds the defaulted `codex_cli`/`codex-cli` editor profile and Codex-aware profile lookup without migrating old files in `server/session_editor_config_shared.py` and `server/session_editor_config_service.py` after T041
- [X] T049 [P] [US4] Luna adds canonical Codex typing, selector choice, optional model input, preview/refusal behavior, and per-backend memory to `frontend/src/stores/config.ts`, `frontend/src/components/layout/AppSidebar.vue`, `frontend/src/components/shared/SelectionPanel.vue`, and `frontend/src/views/ensemble/useEnsembleRun.ts` after T042
- [X] T050 [P] [US4] Luna makes existing grounding, setup, projection, connection, and generic run builders forward only resolved Codex arguments in `server/routers/grounding.py`, `server/routers/setup.py`, `server/routers/projections.py`, `server/routers/connections.py`, and their existing tests after T042
- [X] T051 [US4] Luna adds direct audit, voice comparison, and post-assemble polish routes and controls while preserving checkpoints in `server/routers/scene_editor.py`, `frontend/src/views/session/SessionDocEditor.vue`, `frontend/src/components/scene-editor/KnobDrawer.vue`, and `frontend/src/views/session/ReviewAssemble.vue` after T044, T048, and T049
- [X] T052 [P] [US4] Luna exposes the human-gated transform invocation in `server/routers/prep.py` and `frontend/src/views/prep/SessionPrep.vue` after T045 and T047
- [X] T053 [P] [US4] Luna exposes explicit synthesis-polish and per-chapter narration/review actions without auto-crossing approval in `server/routers/ensemble.py`, `frontend/src/views/ensemble/EnsembleSetup.vue`, `frontend/src/views/ensemble/EnsembleSynthesize.vue`, and `frontend/src/views/ensemble/EnsembleExtract.vue` after T045, T047, and T049
- [X] T054 [P] [US4] Luna teaches the Scabard CLI to accept a trimmed `SCABARD_ACCESS_KEY` fallback while preserving the manual argument contract in `scabard_sdk/scabard_sync.py` after T046
- [X] T055 [US4] Luna adds a redacting environment-override path and mounted Scabard integration endpoint in `server/subprocess_runner.py`, `server/routers/integrations.py`, and `server/main.py` after T046 and T054
- [X] T056 [US4] Luna adds the Scabard integration view and navigation entry with no browser-only result state in `frontend/src/views/integrations/ScabardSync.vue`, `frontend/src/router.ts`, and `frontend/src/components/layout/AppSidebar.vue` after T049 and T055
- [X] T057 [US4] Sol reviews all 30 reachability rows against `specs/016-codex-cli-parity/contracts/ui-selection.md`, inspects Scabard secret redaction, and runs the US4 Python tests plus `rtk npm --prefix frontend run build`

**Checkpoint**: One selection rule drives CLI and UI launches, all 30 capabilities are reachable, and no new UI state or persisted migration is introduced.

---

## Phase 7: User Story 5 - Keep Provider-Specific Controls Honest (Priority: P2)

**Goal**: Codex refuses Anthropic provider message batching before work while preserving application-level grouping, fan-out, resume/review behavior, and bounded child execution.

**Independent Test**: Combine Codex separately with provider `--batch`, `--batch-scenes`, ensemble local fan-out, resume/review, and timeout fixtures; only provider batch is refused and every timed-out child is stopped and cleaned.

### Tests for User Story 5

- [X] T058 [P] [US5] Luna writes failing pre-launch provider-batch refusal tests for shared clients, `facts_to_state`, platform resolution, `polish`, and dispatcher-only `ensemble` in `tests/test_batch_flag_uniformity.py`, `tests/test_facts_to_state.py`, `tests/test_platform_config_service.py`, and `tests/test_ensemble_batch_flag.py`
- [X] T059 [P] [US5] Luna writes failing application-batch and timeout tests for `sd_agent` batch-scenes defaults/overrides, ensemble local fan-out, positive timeout, invalid timeout, child termination, and cleanup in `tests/test_sd_agent.py`, `tests/test_editor_service_integration.py`, `tests/test_ensemble_pipeline.py`, and `tests/test_codex_cli_backend.py`

### Implementation for User Story 5

- [X] T060 [P] [US5] Luna enforces provider-batch refusal before work at the shared client, plural-endpoint command, and server resolver seams in `campaignlib/api/client.py`, `pipelines/ensemble/facts_to_state.py`, and `server/platform_config_service.py` after T058
- [X] T061 [P] [US5] Luna closes the dispatcher defect by refusing non-Anthropic provider batch before `ensemble` spawns a child and by keeping downstream parser contracts consistent in `pipelines/ensemble/ensemble.py`, `pipelines/ensemble/ensemble_batch.py`, and `pipelines/ensemble/ensemble_extract.py` after T058
- [X] T062 [P] [US5] Luna treats Codex and Claude Code consistently for default application-level batch-scenes while preserving explicit overrides and explanatory UI copy in `session_doc/sd_agent.py`, `server/session_editor_config_service.py`, `frontend/src/components/scene-editor/KnobDrawer.vue`, and `frontend/src/views/session/SessionDocEditor.vue` after T059
- [X] T063 [P] [US5] Luna applies the validated positive timeout independently to every direct or brokered child and guarantees termination/cleanup without hidden retries in `campaignlib/api/codex_cli.py` after T059
- [X] T064 [US5] Sol reviews all batch meanings and timeout exits against `specs/016-codex-cli-parity/spec.md` FR-030 through FR-033 and runs `tests/test_batch_flag_uniformity.py`, `tests/test_facts_to_state.py`, `tests/test_ensemble_batch_flag.py`, `tests/test_sd_agent.py`, and `tests/test_codex_cli_backend.py`

**Checkpoint**: Provider batching is refused uniformly, application batching retains its distinct meaning, and every subscription child has one bounded cleanup lifecycle.

---

## Phase 8: Polish and Cross-Cutting Verification

**Purpose**: Close documentation, regression, security, and contract coverage across all stories.

- [X] T065 [P] Luna documents the complete 30-command family, saved-login prerequisite, model precedence, timeout/errors, isolation, polish broker, UI reachability, and batch distinctions in `docs/cli/cli_tools.md`
- [X] T066 [P] Luna updates any stale feature-15/operator examples and test fixture documentation to the canonical family-wide behavior in `specs/016-codex-cli-parity/quickstart.md` and `tests/fixtures/codex_cli/README.md`
- [X] T067 Sol runs the focused validation commands from `specs/016-codex-cli-parity/quickstart.md`, including adapter, inventory, dispatcher, workflow, config, route, and secret-redaction suites
- [X] T068 Sol runs `rtk pytest` and `rtk npm --prefix frontend run build`, reviews failures for existing-provider regressions, and records the final verification outcome in `specs/016-codex-cli-parity/quickstart.md`
- [X] T069 Sol performs the final contract and constitution review across `specs/016-codex-cli-parity/spec.md`, `specs/016-codex-cli-parity/plan.md`, `specs/016-codex-cli-parity/contracts/adapter.md`, `specs/016-codex-cli-parity/contracts/cli-family.md`, `specs/016-codex-cli-parity/contracts/ui-selection.md`, and the completed implementation diff before declaring the feature complete

---

## Dependencies and Execution Order

### Phase Dependencies

- **Phase 1 — Setup**: Starts immediately. T001 must finish before adapter work; T002 and T003 can run in parallel.
- **Phase 2 — Foundational**: Depends on the feature-15 baseline from T001. T009 blocks every user-story phase.
- **Phase 3 — US1**: Depends on T009 and the fake-child fixtures. Establishes family-wide CLI reachability and is the suggested demo MVP.
- **Phase 4 — US2**: Depends on US1 because it compares completed Codex command paths with established workflow contracts.
- **Phase 5 — US3**: Depends on US1's brokered facade; it completes safety and operation-shape hardening. US2 and US3 may run in parallel after US1 if file ownership is partitioned carefully.
- **Phase 6 — US4**: Depends on canonical selection from Phase 2 and stable CLI paths from US1. It may start after US1 while US2/US3 continue, except where tests touch the same files.
- **Phase 7 — US5**: Depends on stable client, dispatcher, server resolver, and editor paths from US1/US4.
- **Phase 8 — Polish**: Depends on every story selected for delivery; T069 requires all preceding tasks.

### User Story Dependency Graph

```text
Setup -> Foundation -> US1
                         ├──> US2
                         ├──> US3
                         └──> US4 -> US5
US2 + US3 + US4 + US5 -> Polish/Final Review
```

### User Story Independence

- **US1 (P1)**: Independently proves saved-login Codex execution and forwarding across all four families; it depends only on shared foundation.
- **US2 (P1)**: Independently proves workflow request/artifact parity using fixed fixtures; it consumes US1 transport but does not require UI work.
- **US3 (P1)**: Independently proves safe interaction-shape support, especially polish; it consumes US1's basic broker facade but does not require new UI faces.
- **US4 (P2)**: Independently proves CLI/UI selection equivalence, persistence compatibility, and reachability; model execution can remain fake.
- **US5 (P2)**: Independently proves provider-batch refusal, application-batch preservation, and timeout cleanup.

### Within Each User Story

- Luna writes the listed tests first and confirms they fail for the intended missing behavior.
- Luna implements lower-level models/adapters before callers, dispatchers, routes, and Vue faces.
- Parallel Luna agents receive disjoint file sets; shared-file changes are serialized in task-ID order.
- Sol reviews the full phase diff and runs its checkpoint suite before releasing dependent tasks.

## Parallel Opportunities

- T002 and T003 can run together after T001 begins because they own different fixture paths.
- T004 and T005 can run together; implementation T006-T008 then proceeds by dependency.
- US1 test tasks T010-T012 can run together; family migrations T015-T019 can run together after T014 with the listed disjoint command files.
- US2 tests T022-T026 and implementation fixes T027-T031 can run by workflow family.
- US3 tests T033-T035 can run together before serialized adapter/client implementation.
- US4 tests T040-T046 can run by config, editor, router, reachability, and integration surface; implementation T047-T054 can run by their disjoint ownership constraints.
- US5 tests T058-T059 and implementation T060-T063 can run in their two waves.
- Documentation T065-T066 can run in parallel after behavior stabilizes.

## Parallel Examples by User Story

### User Story 1

```text
Luna A: T015 session-document commands
Luna B: T016 prep/ingest/search/integration commands
Luna C: T017 grounding commands
After a slot frees, Luna handles T018 ensemble direct commands and T019 dispatchers.
Sol: T021 integrated review after all family tasks land.
```

### User Story 2

```text
Luna A: T022 then T027 shared pipelines/scenes
Luna B: T023 then T028 session-document parity
Luna C: T026 then T031 ensemble parity
Remaining prep and grounding waves use T024/T029 and T025/T030.
Sol: T032 request/artifact review.
```

### User Story 3

```text
Luna A: T033 adapter transcript tests
Luna B: T034 Codex-polish integration tests
Luna C: T035 operation-refusal tests
Then one Luna owns T036-T038 serially across the shared adapter seam.
Sol: T039 isolation and security review.
```

### User Story 4

```text
Luna A: T040/T047 selection and platform config
Luna B: T041/T048 editor persistence
Luna C: T046/T054 Scabard CLI secret contract
Later waves split scene editor (T051), prep (T052), ensemble (T053), and Scabard server/UI (T055-T056).
Sol: T057 capability-map and frontend-build review.
```

### User Story 5

```text
Luna A: T058 then T060 provider-batch entry seams
Luna B: T059 then T063 timeout lifecycle
Luna C: T061 dispatcher refusal, then T062 application batch-scenes behavior
Sol: T064 batch-semantics review.
```

## Implementation Strategy

### MVP First: User Story 1

1. Complete Setup and Foundational phases.
2. Complete US1 through T021.
3. Stop and validate the four-family CLI/dispatcher acceptance path.
4. Demo saved-login execution, model omission/precedence, normal output, and no fallback.

US1 is a useful implementation MVP, but the production P1 promise is not complete until US2 preserves workflow contracts and US3 completes the safe polish loop.

### Incremental Delivery

1. **Foundation**: Feature-15 baseline, fake child, canonical vocabulary, model provenance, inventory guard.
2. **US1**: All CLI and dispatcher surfaces work through Codex.
3. **US2**: Workflow/artifact parity is certified.
4. **US3**: Brokered polish and isolation are fully certified.
5. **US4**: Server/config/UI parity and seven missing faces land.
6. **US5**: Provider controls, application batch behavior, and timeout lifecycle are certified.
7. **Polish**: Documentation, full regressions, and Sol final review.

### Sol/Luna Execution Rules

1. Sol dispatches only coding/test tasks to Luna and assigns explicit, non-overlapping file ownership.
2. Luna reports changed files, tests run, and any blocked contract to Sol; Luna does not broaden scope or change architecture unilaterally.
3. Sol resolves shared-seam conflicts, reviews every Luna diff against the design artifacts, and owns integrated test execution.
4. A failed phase review returns a bounded correction task to Luna; Sol does not silently patch implementation code.

## Notes

- `[P]` tasks are parallel only after their listed dependencies and only with the stated disjoint ownership.
- Existing unrelated worktree changes belong to the user and must be preserved.
- No live authenticated subscription run is required for deterministic completion; the optional smoke in `quickstart.md` remains operator-controlled.
- No state migration task exists because the design adds only enum acceptance and a defaulted additive profile; old documents must pass compatibility tests.
- Commit after each reviewed logical wave so Sol can isolate regressions and roll forward safely.
