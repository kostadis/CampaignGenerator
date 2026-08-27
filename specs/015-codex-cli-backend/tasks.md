---

description: "Dependency-ordered implementation tasks for the Codex CLI subscription backend"
---

# Tasks: Codex CLI Subscription Backend

**Input**: Design documents from `/specs/015-codex-cli-backend/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`,
`contracts/`, and `quickstart.md`

**Tests**: The specification defines explicit acceptance and regression criteria,
so test tasks are included and precede their corresponding implementation tasks.

**Organization**: Tasks are grouped by user story so each increment can be
implemented and tested independently. User Stories 1 and 2 are both P1 and form
the safe MVP; the subscription backend is not releasable without its isolation
contract.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it changes different files and does not
  depend on an incomplete task in the same phase.
- **[Story]**: Maps the task to a user story from `spec.md`.
- Every task names the exact file or files it changes or validates.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the compatibility and regression baseline before changing
the shared backend seam.

- [X] T001 Run the focused pre-change regression suite named in `specs/015-codex-cli-backend/quickstart.md` and reconcile any result that differs from its recorded 37-pass baseline
- [X] T002 Verify the installed `codex exec` command and feature inventory against every fixed option in `specs/015-codex-cli-backend/contracts/adapter.md`, stopping if the CLI is incompatible rather than weakening the contract

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish the new external-boundary types and separate the shared
credential policy from provider-specific thinking support.

**⚠️ CRITICAL**: No user-story implementation begins until this phase passes.

- [X] T003 [P] Add failing request-shape, response-wrapper, and one-chunk stream facade tests for the new adapter in `tests/test_codex_cli_backend.py`
- [X] T004 [P] Add failing regression coverage that treats Codex CLI as keyless without forwarding Anthropic thinking options in `tests/test_no_credential_gate.py`
- [X] T005 Implement `CodexCliError`, strict single-user-turn text normalization, response extraction compatibility, and one-chunk stream wrappers in `campaignlib/api/codex_cli.py`
- [X] T006 Split `_KEYLESS_CLIENTS` from `_THINKING_EXTRA_CLIENTS`, add Codex to only the keyless policy, and preserve existing provider behavior in `campaignlib/api/client.py`
- [X] T007 Export the Codex client/error symbols through `campaignlib/api/__init__.py` and `campaignlib/__init__.py`
- [X] T008 Run the foundational tests in `tests/test_codex_cli_backend.py` and `tests/test_no_credential_gate.py` and confirm all pre-existing provider assertions still pass

**Checkpoint**: The shared facade can represent Codex requests and errors without
credential gating or thinking-option drift.

---

## Phase 3: User Story 1 — Run the canonical audit with a Codex subscription (Priority: P1) 🎯

**Goal**: Let an authenticated GM select `codex-cli`, preserve the auditor's
developer/user prompt boundary and exact assembled user content, and receive the
normal printed, counted, and optionally saved Markdown report.

**Independent Test**: Mock one successful Codex child execution, run
`check_consistency.py --backend codex-cli` with canonical and repeated explicit
context, and verify the separate developer instructions, byte-identical ordered
stdin, one complete stream chunk, report printing, issue count, and saved file.

### Tests for User Story 1

- [X] T009 [P] [US1] Add failing successful-process contract tests for separate developer instructions, byte-identical stdin, temporary final-message output, create/stream parity, and exactly one child invocation in `tests/test_codex_cli_backend.py`
- [X] T010 [P] [US1] Add failing shared selection, model-forwarding, and CLI-choice tests for `codex-cli` in `tests/test_openrouter_seam.py` and `tests/test_backend_seam_guardrails.py`
- [X] T011 [P] [US1] Add a failing mocked end-to-end consistency test covering canonical prompt assembly, repeated context ordering, output persistence, and issue counting in `tests/test_check_consistency_codex.py`

### Implementation for User Story 1

- [X] T012 [P] [US1] Implement the no-shell `codex exec` success path, separate `developer_instructions`, stdin transport, isolated final-message file reading, and single-process result conversion in `campaignlib/api/codex_cli.py`
- [X] T013 [P] [US1] Add `codex-cli` to `make_client`, `add_backend_args`, and `client_from_args` while preserving existing backend defaults in `campaignlib/api/client.py`
- [X] T014 [P] [US1] Change the consistency parser's omitted-model sentinel, retain `DEFAULT_MODEL` for existing providers, route Codex through the shared facade, and preserve existing report behavior in `session_doc/check_consistency.py`
- [X] T015 [US1] Run the User Story 1 tests in `tests/test_codex_cli_backend.py`, `tests/test_check_consistency_codex.py`, `tests/test_openrouter_seam.py`, and `tests/test_backend_seam_guardrails.py`

**Checkpoint**: User Story 1 is independently functional with a mocked successful
subscription response, but release remains blocked on the P1 isolation story.

---

## Phase 4: User Story 2 — Keep subscription audits isolated and unmetered (Priority: P1)

**Goal**: Guarantee saved ChatGPT-login execution without API keys, repository
instructions, user-configured plugins/MCP, executable tools, web search,
subagents, writes, persistence, retries, or provider fallback.

**Independent Test**: Seed the parent environment with both API keys and mock a
repository containing instructions plus user-configured extensions; assert the
actual child argv/environment/cwd enforce the full adapter policy, all temporary
material is removed on every outcome, and failures start no fallback process.

### Tests for User Story 2

- [X] T016 [P] [US2] Add failing assertions for credential removal, forced ChatGPT login, strict config, repository/rule isolation, read-only sandboxing, disabled tools/features/web/subagents, private external cwd, ephemeral execution, and cleanup in `tests/test_codex_cli_backend.py`
- [X] T017 [P] [US2] Add failing missing-executable, authentication, nonzero-exit, and no-provider-fallback CLI tests in `tests/test_check_consistency_codex.py`
- [X] T018 [US2] Add failing adapter-level bounded-diagnostic and no-retry tests for missing executable, authentication failure, and nonzero exit in `tests/test_codex_cli_backend.py`

### Implementation for User Story 2

- [X] T019 [US2] Build the complete fail-closed argv policy from `contracts/adapter.md`, sanitize the child environment, create a private external temporary cwd, and guarantee cleanup in `campaignlib/api/codex_cli.py`
- [X] T020 [US2] Classify missing executable, saved-login/authentication failure, and nonzero exits as bounded actionable `CodexCliError` diagnostics with no retry eligibility in `campaignlib/api/codex_cli.py` and `campaignlib/api/client.py`
- [X] T021 [US2] Catch only `CodexCliError`, print its actionable diagnostic, return nonzero, and avoid a successful report on subscription failure in `session_doc/check_consistency.py`
- [X] T022 [US2] Run the User Story 2 security/error tests in `tests/test_codex_cli_backend.py` and `tests/test_check_consistency_codex.py`, including assertions on the actual subprocess argv, environment, and cwd

**Checkpoint**: User Stories 1 and 2 together form the safe MVP and satisfy all P1
requirements.

---

## Phase 5: User Story 3 — Get predictable model, timeout, and error behavior (Priority: P2)

**Goal**: Resolve models using explicit value → `CG_CODEX_MODEL` → Codex default,
reject incompatible Claude models, bound execution with `CG_CODEX_TIMEOUT`,
distinguish timeout/process/empty-result errors, and refuse provider batching.

**Independent Test**: Exercise every precedence and validation branch plus an
expired process, partial nonzero output, whitespace-only success, and
`--batch --backend codex-cli`; verify exact selection/refusal, no saved report,
and zero fallback attempts.

### Tests for User Story 3

- [X] T023 [P] [US3] Add failing table-driven CLI model-precedence tests for explicit model, `CG_CODEX_MODEL`, omitted model, empty override, and explicit/environment `claude-*` rejection in `tests/test_check_consistency_codex.py`
- [X] T024 [P] [US3] Add failing timeout parsing/expiry, partial nonzero output, bounded stderr, and missing/whitespace final-result tests in `tests/test_codex_cli_backend.py`
- [X] T025 [P] [US3] Extend the non-Anthropic Batch API refusal tests to cover `codex-cli` before client execution in `tests/test_backend_seam_guardrails.py` and `tests/test_check_consistency_batch.py`

### Implementation for User Story 3

- [X] T026 [P] [US3] Implement model normalization and precedence, incompatible-provider rejection, positive finite timeout parsing with a 600-second default, timeout termination, and empty-result handling in `campaignlib/api/codex_cli.py`
- [X] T027 [P] [US3] Display the Codex subscription default distinctly from the inherited Claude default and preserve concise typed failure output in `session_doc/check_consistency.py`
- [X] T028 [P] [US3] Keep provider batching Anthropic-only and ensure the shared refusal names `codex-cli` without constructing its child client in `campaignlib/api/client.py`
- [X] T029 [US3] Run the User Story 3 tests in `tests/test_codex_cli_backend.py`, `tests/test_check_consistency_codex.py`, `tests/test_backend_seam_guardrails.py`, and `tests/test_check_consistency_batch.py`

**Checkpoint**: The complete CampaignGenerator backend contract is functional and
independently testable without live subscription usage.

---

## Phase 6: User Story 4 — Use the Codex consistency workflows end to end (Priority: P2)

**Goal**: Route both installed consistency workflows through the canonical
CampaignGenerator `codex-cli` audit while preserving their report review,
approval, fix, phase-ordering, and HTML batch-review behavior.

**Independent Test**: Resolve each installed skill symlink, invoke both workflows
against a representative safe session with a mocked subscription result, and
confirm their generated commands select `codex-cli` while all post-report human
checkpoints remain unchanged.

### Tests for User Story 4

- [X] T030 [P] [US4] Prepare and execute the `consistency-check` acceptance cases defined in `specs/015-codex-cli-backend/contracts/skills.md` against `/home/kroussos/src/mytools/dotfiles/codex/skills/consistency-check/SKILL.md`
- [X] T031 [P] [US4] Prepare and execute the `staged-consistency` acceptance cases defined in `specs/015-codex-cli-backend/contracts/skills.md` against `/home/kroussos/src/mytools/dotfiles/codex/skills/staged-consistency/SKILL.md`

### Implementation for User Story 4

- [X] T032 [P] [US4] After obtaining permission for the external repository, replace the hard-coded Claude Code audit backend with `codex-cli` and document saved-login/error behavior in `/home/kroussos/src/mytools/dotfiles/codex/skills/consistency-check/SKILL.md`
- [X] T033 [P] [US4] After obtaining permission for the external repository, update Codex-backend compatibility prose while preserving delegation, stage ordering, and HTML review behavior in `/home/kroussos/src/mytools/dotfiles/codex/skills/staged-consistency/SKILL.md`
- [X] T034 [US4] Re-run both skill acceptance workflows from `specs/015-codex-cli-backend/contracts/skills.md` and verify the installed `/home/kroussos/.codex/skills/consistency-check` and `/home/kroussos/.codex/skills/staged-consistency` symlinks resolve to the edited canonical sources

**Checkpoint**: Both intended day-to-day skill entry points use the new backend
without changing human review boundaries.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Complete operator documentation, security review, and regression
validation across all stories.

- [X] T035 [P] Document installation/login prerequisites, `codex-cli` usage, CLI-only scope, and Batch API refusal in `README.md` and `docs/cli/cli_tools.md`
- [X] T036 [P] Document `CG_CODEX_MODEL`, `CG_CODEX_TIMEOUT`, the no-key subscription boundary, and component placement in `docs/core/configuration.md`, `docs/system/component-campaigngenerator.md`, and `docs/system/index.md`
- [X] T037 Audit the final implementation against every argv, environment, cleanup, output, and failure assertion in `specs/015-codex-cli-backend/contracts/adapter.md` and every constitution ruling in `specs/015-codex-cli-backend/plan.md`
- [X] T038 Run the complete mocked regression suite from `specs/015-codex-cli-backend/quickstart.md`, including `tests/test_retrieve_render_isolation.py`, and resolve all feature-caused regressions
- [X] T039 Perform the intentional authenticated no-key smoke test from `specs/015-codex-cli-backend/quickstart.md` using a safe document and verify the source/context bytes remain unchanged
- [X] T040 Run final formatting and worktree checks for all paths listed in `specs/015-codex-cli-backend/plan.md`, confirm no frontend/server selector or migration changes were introduced, and record any unrelated pre-existing failures in `specs/015-codex-cli-backend/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies; establishes the baseline and CLI
  compatibility floor.
- **Foundational (Phase 2)**: Depends on Setup and blocks all stories.
- **User Story 1 (Phase 3)**: Depends on Foundational; implements the successful
  canonical audit path.
- **User Story 2 (Phase 4)**: Depends on User Story 1's process seam; completes
  the mandatory P1 security identity. US1 + US2 is the safe MVP.
- **User Story 3 (Phase 5)**: Depends on the US1 process seam and US2 failure
  boundary; adds model, timeout, and batch predictability.
- **User Story 4 (Phase 6)**: Depends on User Stories 1–3 so the skills adopt a
  complete backend contract; its two external skill edits can proceed in parallel.
- **Polish (Phase 7)**: Depends on all selected stories and both repository
  delivery units being available.

### User Story Dependency Graph

```text
Setup -> Foundation -> US1 -> US2 -> US3 -> US4 -> Polish
                              \------ safe MVP ------/
```

US2 and US3 test authoring may begin after Foundation, but their implementation
and acceptance build on the US1 process boundary. US4 is behaviorally separate
after report generation, yet deliberately waits for the backend contract it
adopts.

### Within Each User Story

- Write the listed tests first and confirm they fail for the intended missing
  behavior.
- Implement shared/domain behavior before CLI integration.
- Run the story's focused suite before crossing its checkpoint.
- Do not weaken a fixed isolation option to make an incompatible Codex version
  pass; fail the compatibility task instead.
- Never substitute a live subscription call for deterministic mocked tests.

### Parallel Opportunities

- T003 and T004 can run together in Foundation.
- T009, T010, and T011 can run together for User Story 1.
- T016 and T017 can run together for User Story 2 after the US1 seam exists;
  T018 follows T016 in the same adapter test file.
- T023, T024, and T025 can run together for User Story 3.
- T030 and T031 can prepare separate skill acceptance cases in parallel; after
  they expose the expected failures, T032 and T033 can edit the two external
  skill files in parallel.
- T035 and T036 can update separate documentation groups in parallel.

---

## Parallel Example: User Story 1

```text
Task T009: Add the successful Codex subprocess/facade tests in tests/test_codex_cli_backend.py
Task T010: Add shared backend-selection tests in tests/test_openrouter_seam.py and tests/test_backend_seam_guardrails.py
Task T011: Add canonical audit integration tests in tests/test_check_consistency_codex.py
```

## Parallel Example: User Story 2

```text
Task T016: Assert child isolation and cleanup in tests/test_codex_cli_backend.py
Task T017: Assert actionable CLI failures and no fallback in tests/test_check_consistency_codex.py
```

## Parallel Example: User Story 3

```text
Task T023: Add CLI model-resolution tests in tests/test_check_consistency_codex.py
Task T024: Add timeout/process/output tests in tests/test_codex_cli_backend.py
Task T025: Add Batch API guard tests in tests/test_backend_seam_guardrails.py and tests/test_check_consistency_batch.py
```

## Parallel Example: User Story 4

```text
Task T030/T032: Validate and update /home/kroussos/src/mytools/dotfiles/codex/skills/consistency-check/SKILL.md
Task T031/T033: Validate and update /home/kroussos/src/mytools/dotfiles/codex/skills/staged-consistency/SKILL.md
```

---

## Implementation Strategy

### Safe MVP First (User Stories 1 and 2)

1. Complete Setup and Foundation.
2. Complete User Story 1 and prove the canonical success path.
3. Complete User Story 2 and prove the subscription/isolation identity.
4. **STOP AND VALIDATE** the combined P1 suite before any live audit.
5. Demonstrate one safe subscription audit; do not release an US1-only slice.

### Incremental Delivery

1. Setup + Foundation → stable shared seam.
2. US1 + US2 → safe P1 MVP.
3. US3 → dependable model, timeout, failure, and batch semantics.
4. US4 → installed workflows adopt the complete backend.
5. Polish → operator documentation, full regression, and live smoke validation.

### Delivery-Unit Strategy

1. Implement and test CampaignGenerator code/docs in this worktree.
2. Obtain write permission for the canonical dotfiles repository before T032–T033.
3. Track/commit the two skill edits separately; do not treat `~/.codex` symlinks
   as CampaignGenerator deliverables.
4. Validate both delivery units together through the skill acceptance contract.

---

## Notes

- Tasks marked [P] use separate files or independent test sections; shared-file
  exceptions are called out in the parallel examples.
- No task adds a frontend/server backend selector because issue #348 supplies the
  explicit Constitution Principle XI exemption recorded in `plan.md`.
- No migration task is present because the feature changes no persistent state
  shape.
- Commit after each task or coherent task group, preserving unrelated existing
  worktree changes.
