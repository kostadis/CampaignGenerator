# Tasks: Codex Reasoning Effort Everywhere

**Input**: Design documents from `/specs/019-codex-reasoning-effort/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Test tasks are included because FR-023 and the acceptance criteria require inventory, transport, persistence, UI-reachability, and observability coverage. Write each story's tests first and confirm they fail for the missing behavior before implementing that story.

**Organization**: Tasks are grouped by user story so each capability can be implemented and verified as an incremental slice.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel after its stated prerequisites because it changes different files
- **[Story]**: Maps the task to User Story 1, 2, or 3
- Every checklist task names the exact repository file or files it changes or validates

---

## Phase 1: Setup

**Purpose**: Prepare deterministic, token-free test support for the feature.

- [X] T001 Extend the process-backed fake Codex harness with reusable assertions/helpers for exact `model_reasoning_effort` argv capture, child-start counts, and rejected-child responses in `tests/helpers/fake_codex_cli.py`

---

## Phase 2: Foundational

**Purpose**: Establish the one canonical value type and persisted selection field used by every story.

**Critical**: Complete this phase before starting any user-story implementation.

- [X] T002 Define the canonical `minimal|low|medium|high|xhigh|max` effort type/value tuple, add optional `codex_reasoning_effort` to `ModelSelection`, and make effort-only selections non-empty in `campaignlib/selection.py`

**Checkpoint**: The shared selection model can represent omission or one canonical Codex effort without changing existing YAML behavior.

---

## Phase 3: User Story 1 - Choose Reasoning Effort on Every CLI Run (Priority: P1) — MVP

**Goal**: Every one of the 30 production direct commands and dispatchers accepts or forwards the same explicit `--codex-reasoning-effort` option to the sole Codex adapter.

**Independent Test**: Run every inventoried direct command and dispatcher against the fake Codex child with `--backend codex-cli --model gpt-5.6-sol --codex-reasoning-effort max`; every applicable child must receive exactly one `model_reasoning_effort="max"` override while established work selection, outputs, retries, and checkpoints remain unchanged.

### Tests for User Story 1

- [X] T003 [P] [US1] Add failing adapter and representative-command tests for all six explicit values, `gpt-5.6-sol` plus `max`, exact TOML-safe argv, direct/streaming/brokered parity, and unchanged isolation flags in `tests/test_codex_cli_backend.py` and `tests/test_check_consistency_codex.py`
- [X] T004 [P] [US1] Extend failing AST/source inventory tests to require exactly one shared effort option across all 26 direct commands, the hand-written `facts_to_state` parser, and all four dispatchers in `tests/test_codex_cli_family.py` and `tests/test_backend_seam_guardrails.py`
- [X] T005 [P] [US1] Add failing `sd_agent` tests proving an explicit effort reaches every applicable child and never broadens the selected work set in `tests/test_sd_agent.py`
- [X] T006 [P] [US1] Add failing ensemble and hand-written-parser tests for explicit effort fan-out, mixed-backend isolation, retry/resume preservation, and omission forwarding in `tests/test_ensemble_dispatch.py`, `tests/test_ensemble_batch_flag.py`, and `tests/test_facts_to_state.py`

### Implementation for User Story 1

- [X] T007 [US1] Add the one shared argparse registrar/help text, explicit/environment/omitted resolver with provenance, wrong-backend validation, and `client_from_args()` propagation in `campaignlib/api/client.py`
- [X] T008 [US1] Thread the optional effort through `_CodexCliClient`, direct messages, streaming messages, and brokered messages, and append exactly one conditional TOML-safe `-c model_reasoning_effort=...` pair at `_command()` in `campaignlib/api/codex_cli.py`
- [X] T009 [P] [US1] Replace the hand-written effort option in `facts_to_state` with the shared parser helper and pass the resolved value through client construction in `pipelines/ensemble/facts_to_state.py`
- [X] T010 [P] [US1] Accept and forward an explicit effort to every applicable session-document child while leaving omission for the final adapter to resolve in `session_doc/sd_agent.py`
- [X] T011 [P] [US1] Accept and forward an explicit effort through every applicable ensemble child command, including fan-out, retry, resume, and multi-stage paths, in `pipelines/ensemble/ensemble.py`, `pipelines/ensemble/ensemble_batch.py`, and `pipelines/ensemble/ensemble_extract.py`

**Checkpoint**: All 30 production CLI surfaces share one option vocabulary and explicit `max` reaches every fake Codex child unchanged.

---

## Phase 4: User Story 2 - Choose and Reuse Reasoning Effort in the UI (Priority: P1)

**Goal**: Every Codex-capable UI selector offers the same server-published seven choices, persists Codex-specific values at the correct YAML scope, survives reload/backend switching, and launches the canonical CLI flag.

**Independent Test**: On global, generic service, Session Doc Editor, scene knob, and ensemble stage selectors, choose `max`, save/reload, switch away from and back to Codex, and verify the owner YAML retains `max`, another provider receives no Codex option, and the built command contains `--codex-reasoning-effort max`.

### Tests for User Story 2

- [X] T012 [P] [US2] Add failing platform/config route tests for the six-value `/api/config/models` response, additive runtime persistence, request→service→platform resolution, and CLI flag formatting in `tests/test_platform_config_service.py` and `tests/test_config_routes.py`
- [X] T013 [P] [US2] Add failing tests for effort-only service overrides, old-YAML loading without rewrite, backend-switch memory, provider isolation, and replacement PUT preservation in `tests/test_selection_isolation.py` and `tests/test_service_selection_override.py`
- [X] T014 [P] [US2] Add failing Session Doc Editor profile and command-builder tests for Codex effort hydrate/save/restore behavior in `tests/test_session_editor_config_service.py`, `tests/test_editor_service_integration.py`, and `tests/test_editor_pipeline.py`
- [X] T015 [P] [US2] Add failing ensemble/projection tests for per-stage persistence and effort retention through specialized backend-adapting command builders in `tests/test_ensemble_config_defaults.py`, `tests/test_ensemble_gates.py`, and `tests/test_projection_routes.py`
- [X] T016 [P] [US2] Add a failing static UI parity inventory that covers literal Codex selectors and dynamic `SelectionPanel` consumers, verifies the server-published vocabulary is used, and rejects free-text or duplicated value lists in `tests/test_codex_reasoning_ui.py`

### Implementation for User Story 2

- [X] T017 [P] [US2] Add optional Codex effort memory to `PlatformRuntime`, extend `ResolvedSelection` with value/origin/override fields, implement request→service→platform→environment→omission preview resolution, and emit CLI flags only for request/service/platform origins in `server/platform_config_shared.py`, `server/platform_config_service.py`, and `server/backend_forwarding.py`
- [X] T018 [US2] Publish `codex_reasoning_efforts` from the canonical Python vocabulary while preserving the existing model/backend response in `server/routers/config_routes.py`
- [X] T019 [P] [US2] Extend `BackendProfile` and `EnsembleBackend` persistence and their `is_empty()` overrides so effort-only values round-trip without migration in `server/session_editor_config_shared.py` and `server/ensemble_config_shared.py`
- [X] T020 [P] [US2] Copy the Codex profile effort in `_editor_service_selection()` and preserve it through editor command formatting and replacement updates in `server/routers/scene_editor.py`
- [X] T021 [P] [US2] Preserve the validated effort when ensemble and projection builders adapt `ResolvedSelection` for existing backend formatting in `server/routers/ensemble.py` and `server/routers/projections.py`
- [X] T022 [US2] Add typed Codex effort vocabulary, runtime/profile fields, hydration, save payloads, and compatibility handling for an older server missing the vocabulary in `frontend/src/stores/config.ts`
- [X] T023 [P] [US2] Add the global Codex-only seven-choice selector, explanatory help, omission serialization, and backend-switch retention to `frontend/src/components/layout/AppSidebar.vue`
- [X] T024 [P] [US2] Add the generic service-level Codex effort override/defer selector and preserve the field in full replacement payloads and resolved previews in `frontend/src/components/shared/SelectionPanel.vue`
- [X] T025 [P] [US2] Hydrate, edit, emit, save, and restore the Codex profile effort alongside its model in `frontend/src/components/scene-editor/KnobDrawer.vue` and `frontend/src/views/session/SessionDocEditor.vue`
- [X] T026 [P] [US2] Add one Codex effort selector per applicable ensemble stage and preserve remembered values through stage backend switches and resets in `frontend/src/views/ensemble/EnsembleSetup.vue` and `frontend/src/views/ensemble/useEnsembleRun.ts`

**Checkpoint**: Every selector-owning Codex UI surface uses the same seven choices and persists the selection at its existing server-owned YAML scope.

---

## Phase 5: User Story 3 - Preserve Defaults and Explain What Ran (Priority: P2)

**Goal**: Omission preserves Codex defaults, environment fallback is truthful, invalid input fails before work, compatibility failures never fall back, and actual model/effort identity is visible in terminals, UI output, logs, sidecars, and Connection Graph results.

**Independent Test**: Run the explicit-over-environment, environment-only, and total-omission matrix plus invalid, wrong-backend, and model-incompatible cases; verify the canonical identity/source, exact child-start count, absence of an override for omission, no successful artifact on failure, log/SSE visibility, and Connection Graph response identity.

### Tests for User Story 3

- [X] T027 [P] [US3] Add failing adapter tests for trimmed environment fallback, whitespace omission, invalid environment and explicit values, wrong-backend rejection, stable pre-child identity lines, model/effort error context, one-child compatibility failure, and no fallback in `tests/test_codex_cli_backend.py`
- [X] T028 [P] [US3] Add failing server tests for environment-origin previews without flag conversion, total omission, legacy config compatibility, canonical SSE output, Markdown run-log retention, redaction, timeout, and interruption metadata in `tests/test_platform_config_service.py` and `tests/test_subprocess_abort.py`
- [X] T029 [P] [US3] Add failing route tests for machine-readable Codex `run_identity`, provider-appropriate non-Codex responses, error propagation, and no extra child on Connection Graph extraction in `tests/test_connections.py`
- [X] T030 [P] [US3] Add failing ensemble polish trace tests requiring effort value/source anywhere a Codex model is recorded and preserving non-Codex trace schemas in `tests/test_polish_codex.py`
- [X] T031 [P] [US3] Extend the UI parity inventory with failing assertions that streamed result surfaces preserve the canonical line and Connection Graph renders returned run identity in `tests/test_codex_reasoning_ui.py`

### Implementation for User Story 3

- [X] T032 [US3] Implement immutable `CodexRunIdentity`, final model/effort provenance resolution, stable pre-child status output, last-run identity access, and model/effort context on all adapter failures without weakening cleanup or redaction in `campaignlib/api/codex_cli.py`
- [X] T033 [P] [US3] Return the actual shared-client Codex run identity from in-process extraction responses while leaving non-Codex responses provider-appropriate in `server/routers/connections.py`
- [X] T034 [US3] Type and render Connection Graph run identity beside its result/cache summary and retain it on extraction errors where returned in `frontend/src/views/prep/ConnectionGraph.vue`
- [X] T035 [P] [US3] Preserve and visibly label the canonical model/effort identity in streamed output and the session review/polish result view without inventing a second SSE event in `frontend/src/components/shared/StreamOutput.vue` and `frontend/src/views/session/ReviewAssemble.vue`
- [X] T036 [P] [US3] Add Codex reasoning effort and provenance to ensemble polish JSONL events that already record the model, without adding Codex fields to other providers, in `pipelines/ensemble/polish.py`

**Checkpoint**: Every actual Codex run truthfully reports explicit, environment, or `Codex default` state; invalid and incompatible inputs produce no fallback or successful artifact.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Complete operator guidance and run the cross-story regression gates.

- [X] T037 [P] Document the canonical flag, six values, precedence, omission semantics, model-dependent compatibility, `gpt-5.6-sol` `max`, UI locations, run identity, and YAML ownership in `docs/cli/cli_tools.md`, `docs/core/configuration.md`, `docs/config/schema.md`, `docs/config/values.md`, and `docs/config/platform-isolation.md`
- [X] T038 [P] Run and fix the deterministic adapter, 30-surface, dispatcher, server, route, persistence, logging, and UI-reachability test groups specified in `specs/019-codex-reasoning-effort/quickstart.md`
- [X] T039 Run the full `rtk pytest tests/` suite and `rtk npm --prefix frontend run build`, then reconcile any feature-caused regression with `specs/019-codex-reasoning-effort/spec.md` and `specs/019-codex-reasoning-effort/contracts/`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies; can start immediately.
- **Foundational (Phase 2)**: Depends on T001 and blocks every user story.
- **User Story 1 (Phase 3)**: Depends on T002; delivers the CLI MVP.
- **User Story 2 (Phase 4)**: Depends on T002; its persistence and command-builder slice can be tested independently, while end-to-end Codex execution uses the US1 CLI seam.
- **User Story 3 (Phase 5)**: Depends on the US1 adapter threading and US2 selection/formatter plumbing because it reports the final identity across those paths.
- **Polish (Phase 6)**: Depends on all selected user stories; T039 follows the targeted validation in T038.

### User Story Dependency Graph

```text
Setup (T001)
  -> Foundation (T002)
       -> US1: CLI propagation (T003-T011) ----+
       -> US2: UI persistence (T012-T026) -----+-> US3: defaults and identity (T027-T036)
                                                -> Polish (T037-T039)
```

### Within Each User Story

- Write the story's test tasks first and verify they fail for the intended missing behavior.
- Add shared models/resolvers before adapters, services, endpoints, or components that consume them.
- Keep `campaignlib/api/codex_cli.py` as the sole Codex child-process boundary.
- Keep `server/platform_config_service.py::selection_cli_args()` as the sole server flag producer.
- Complete the story checkpoint before relying on that story from a later phase.

### Parallel Opportunities

- **US1**: T003-T006 can be authored in parallel; after T007-T008, T009-T011 can be implemented in parallel.
- **US2**: T012-T016 can be authored in parallel; T017 and T019 can proceed in parallel; after server contracts settle, T020-T021 can proceed in parallel; after T022, T023-T026 can proceed in parallel.
- **US3**: T027-T031 can be authored in parallel; after T032, T033, T035, and T036 can proceed in parallel, with T034 following T033.
- **Polish**: Documentation T037 and targeted validation T038 can proceed in parallel; the full regression gate T039 follows both implementation and targeted checks.

---

## Parallel Example: User Story 1

```text
Task T003: Adapter and representative-command tests
Task T004: 30-surface AST/source inventory tests
Task T005: Session-document dispatcher tests
Task T006: Ensemble dispatcher and hand-written-parser tests

After T007-T008:
Task T009: facts_to_state parser integration
Task T010: sd_agent forwarding
Task T011: ensemble dispatcher forwarding
```

## Parallel Example: User Story 2

```text
Task T012: Platform/config route tests
Task T013: Selection isolation and service override tests
Task T014: Session editor persistence tests
Task T015: Ensemble/projection builder tests
Task T016: Static UI parity inventory

After T022:
Task T023: Global sidebar selector
Task T024: Generic service selector
Task T025: Session editor selectors
Task T026: Ensemble stage selectors
```

## Parallel Example: User Story 3

```text
Task T027: Adapter precedence, validation, and identity tests
Task T028: Server preview, SSE, and log tests
Task T029: Connection Graph route tests
Task T030: Polish metadata tests
Task T031: UI identity reachability tests

After T032:
Task T033: Connection Graph response identity
Task T035: Streamed UI identity display
Task T036: Polish sidecar identity
```

---

## Implementation Strategy

### MVP First: User Story 1

1. Complete T001-T002.
2. Write and fail T003-T006.
3. Implement T007-T011.
4. Run the US1 tests and verify all 30 CLI surfaces forward explicit `max` correctly.
5. Stop and review the CLI MVP before adding persistence or UI behavior.

### Incremental Delivery

1. **Foundation**: canonical optional effort representation with deterministic fake-child support.
2. **US1**: one CLI spelling, one resolver, and all-use explicit forwarding.
3. **US2**: server-owned persistence and every selector-owning UI face.
4. **US3**: truthful defaults, validation, errors, logs, sidecars, and result identity.
5. **Polish**: operator documentation and full Python/TypeScript regression gates.

### Safe Integration Rules

- Omission must never be serialized as a guessed effort or sent as an override.
- Environment-derived server previews must not be converted into explicit child flags.
- A Codex-only explicit value with another backend must fail before model work.
- A canonical but model-incompatible value must surface the Codex failure and must not retry another model, effort, or backend.
- Existing YAML without the new optional fields must load without rewrite or migration.
- Existing work selection, caches, retries, timeouts, output paths, and human-review checkpoints remain unchanged.

---

## Notes

- `[P]` tasks change different files and are safe to run concurrently once their prerequisites are complete.
- `[US1]`, `[US2]`, and `[US3]` provide traceability to the three specification stories.
- Authenticated Codex smoke tests in `quickstart.md` are optional and may spend subscription tokens; T038-T039 use only deterministic fake-child coverage.
- Commit after each task or coherent task group, and validate at every checkpoint.
