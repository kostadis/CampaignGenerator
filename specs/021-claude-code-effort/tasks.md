---

description: "Task list for Claude Code Subscription Effort Level"
---

# Tasks: Claude Code Subscription Effort Level

**Input**: Design documents from `specs/021-claude-code-effort/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: **Included and required.** FR-025 mandates an entry-point inventory backed by a guardrail test that fails when a new Claude Code-capable surface lacks the setting, and SC-007 requires a green regression suite for every other backend. Tests are not optional here.

**Organization**: Grouped by user story. US1 (CLI) is the MVP.

**Worktree**: `~/src/CampaignGenerator/worktrees/021-claude-code-effort`, branch `021-claude-code-effort`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 (CLI selection), US2 (UI parity), US3 (reporting), US4 (omission preserved)

## Path Conventions

Web application over a CLI engine: `campaignlib/` (seam) → `pipelines/`, `session_doc/` (CLIs) → `server/` (FastAPI) → `frontend/src/` (Vue). Tests in `tests/`.

---

## Phase 1: Setup

**Purpose**: Make the worktree runnable. Neither task is optional — the first is why `/run/*` fails in a fresh worktree, the second is why a green suite there is not evidence.

- [X] T001 Editable-install the package into the server's venv from the worktree root: `uv pip install -e . --python "$VIRTUAL_ENV/bin/python"` — without it every `/run/*` action fails with `Stream error — check terminal` because `<venv>/bin/sd_narrate` does not exist
- [X] T002 [P] Record the pre-feature baseline for SC-005 by capturing a `--dump-only` claude-code invocation to `/tmp/before.txt`, per `quickstart.md` §4
- [X] T003 [P] Confirm the vocabulary against the installed CLI with `claude --help | grep -A2 -- --effort` (expect exactly: low, medium, high, xhigh, max) and note the operator's pinned `effortLevel` from `~/.claude/settings.json`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The vocabulary and the config field every story reads. No story can begin until this is complete.

**⚠️ CRITICAL**: T005–T008 are one logical change split across four files. Landing the field without all three `is_empty()` updates produces the feature's most likely silent failure — a profile carrying only an effort selection reads as "no override at all" and is dropped on save, with no error.

- [X] T004 Declare `ClaudeCodeEffort = Literal["low","medium","high","xhigh","max"]` and `CLAUDE_CODE_EFFORTS` in `campaignlib/selection.py`, beside the existing `CodexReasoningEffort` — five values, no `minimal` (research R1)
- [X] T005 Add the optional `claude_code_effort: ClaudeCodeEffort | None = None` field to `ModelSelection` in `campaignlib/selection.py` and include it in `ModelSelection.is_empty()`
- [X] T006 [P] Include `claude_code_effort` in `BackendProfile.is_empty()` at `server/session_editor_config_shared.py:98`
- [X] T007 [P] Include `claude_code_effort` in `EnsembleBackend.is_empty()` at `server/ensemble_config_shared.py:87`
- [X] T008 [P] Add `default_claude_code_effort: ClaudeCodeEffort | None = None` to the runtime model at `server/platform_config_shared.py:179`, beside `default_codex_reasoning_effort`
- [X] T009 [P] Re-export `ClaudeCodeEffort`, `CLAUDE_CODE_EFFORTS`, and `add_claude_code_effort_arg` from `campaignlib/__init__.py` (imports at line 38, `__all__` at line 168)
- [X] T010 Write `tests/test_claude_code_effort_config.py` covering the `is_empty()` trap on all three shapes: a selection carrying ONLY `claude_code_effort` must be non-empty and must survive a save/reload round trip on `ModelSelection`, `BackendProfile`, and `EnsembleBackend`

**Checkpoint**: The field exists, persists, and cannot be silently dropped. Story work can begin.

---

## Phase 3: User Story 1 — Choose an Effort Level on Every CLI Run (Priority: P1) 🎯 MVP

**Goal**: One option, spelled once, accepted by every model-bearing CLI and forwarded by every dispatcher, with the documented precedence and every refusal firing before a child process spawns.

**Independent Test**: `quickstart.md` §1–3 and §6 — the option appears on every CLI's `--help`, precedence resolves correctly, all five refusals fire with no `claude` child spawned and no artifact written, and dispatchers forward to every child.

### Tests for User Story 1 ⚠️

> Write these first and confirm they fail before implementing.

- [X] T011 [P] [US1] Write vocabulary and precedence tests in `tests/test_claude_code_effort.py`: explicit beats environment, environment beats omission, whitespace-only `CG_CLAUDE_CODE_EFFORT` is omission not an empty override, and `None` stays distinguishable from `"low"` at every tier
- [X] T012 [P] [US1] Write refusal tests in `tests/test_claude_code_effort.py` for all five cases in `contracts/cli-family.md`: bad value, empty/padded value, wrong backend, bad environment value, effort/thinking conflict — each asserting no child process was spawned
- [X] T013 [P] [US1] Write the FR-009a test in `tests/test_claude_code_effort.py`: `max` on an always-thinking model (`fable`/`mythos` marker) is accepted, not refused, and receives no clamp
- [X] T014 [P] [US1] Extend `tests/helpers/fake_codex_cli.py`'s pattern with a fake `claude` CLI helper so argv assertions do not require the real binary

### Implementation for User Story 1

- [X] T015 [US1] Add `_valid_claude_code_effort(value, *, source)` to `campaignlib/api/client.py`, mirroring `_valid_codex_effort` at line 63 — reject non-strings, empty strings, and padded strings, naming the accepted set
- [X] T016 [US1] Add `add_claude_code_effort_arg(parser)` to `campaignlib/api/client.py` with `choices=CLAUDE_CODE_EFFORTS`, `default=None`, and the help text from `contracts/cli-family.md`
- [X] T017 [US1] Call `add_claude_code_effort_arg(parser)` from inside `add_backend_args` in `campaignlib/api/client.py:350`, beside the existing `add_codex_reasoning_arg(parser)` — this is the whole of CLI parity for all 30 callers (research R8)
- [X] T018 [US1] Add `resolve_cli_claude_effort(args) -> ClaudeCodeEffortIntent` to `campaignlib/api/client.py`, mirroring `resolve_cli_reasoning` at line 73, implementing the resolution pseudocode in `contracts/cli-family.md` — note the ordering: an explicit value's backend check precedes the environment read, but an ambient `CG_CLAUDE_CODE_EFFORT` on a non-claude-code run is omission, not a refusal
- [X] T019 [US1] Add the shared conflict helper to `campaignlib/api/backends.py` — one function returning the single refusal message naming the level, both remedies, and `CG_CLAUDE_CODE_THINKING=1` literally (research R7); it must be the only source of that wording
- [X] T020 [US1] Add the edge fast-fail to `client_from_args` in `campaignlib/api/client.py` using the T019 helper, firing only when the conflict is already determined (explicit `xhigh`/`max` + clamp-eligible model + no thinking opt-in in the environment)
- [X] T021 [US1] Thread `claude_code_effort` / `claude_code_effort_source` from `client_from_args` into `make_client` in `campaignlib/api/client.py:229` and on to `_ClaudeCodeClient` at line 267 — separate kwargs from Codex's `reasoning_effort` pair, never overloaded (research R1/R5)
- [X] T022 [US1] Accept and store the effort and source on `_ClaudeCodeClient` in `campaignlib/api/backends.py`, and pass them through `_ClaudeCodeMessages.create` and `.stream` and `_ClaudeCodeStream.__init__`
- [X] T023 [US1] In `_claude_code_generate` (`campaignlib/api/backends.py:409`), make the `--effort` argv decision: an explicit or environment level replaces the `CLAUDE_CODE_NO_THINKING_EFFORT` clamp at line 486; omission preserves the existing clamp/skip logic exactly
- [X] T024 [US1] Add the hard conflict guard in `_claude_code_generate` in `campaignlib/api/backends.py` immediately before `subprocess.run`, using the T019 helper — this is the "before any model work starts" boundary the spec defines (research R2)
- [X] T025 [US1] Register the option explicitly in `pipelines/ensemble/facts_to_state.py:1112`, which declares its backend args directly rather than calling `add_backend_args` and therefore does **not** inherit T017
- [X] T026 [P] [US1] Forward `--claude-code-effort` to child argv in `pipelines/ensemble/ensemble.py:166`, mirroring the `--codex-reasoning-effort` block
- [X] T027 [P] [US1] Forward in `pipelines/ensemble/ensemble_batch.py` — import at line 40, register at line 112, forward at line 172, resolve at line 209
- [X] T028 [P] [US1] Forward in `pipelines/ensemble/ensemble_extract.py` — import at line 68, add the parameter to `_build_cmd` at line 78, forward at line 97, thread the caller at line 163
- [X] T029 [P] [US1] Forward in `session_doc/sd_agent.py` — import at line 39, forward at line 136, resolve at line 240
- [X] T030 [P] [US1] Resolve and apply in `pipelines/ensemble/polish.py` (imports at lines 25–27) and `pipelines/ensemble/facts_to_state.py` (imports at lines 52–61), which construct clients in-process rather than forwarding argv
- [X] T031 [US1] Verify forwarding reaches retry and resume children, and that a mixed-backend plan leaves non-`claude-code` stages untouched (`contracts/cli-family.md`, "Dispatcher forwarding")

**Checkpoint**: US1 is independently functional. Run `quickstart.md` §1–3 and §6. This is a shippable MVP: the CLI capability exists and is safe, even with no UI yet.

---

## Phase 4: User Story 3 — See What Effort a Run Actually Used (Priority: P1)

**Goal**: Four distinguishable sources, one banner per run, and a clamp that names itself instead of passing as the operator's choice.

**Independent Test**: `quickstart.md` §4–5 — with `effortLevel: xhigh` pinned in `~/.claude/settings.json`, a default run's own output makes three facts readable: it used `high`, the pinned `xhigh` was not used, and thinking being off is why. Today that is unanswerable.

**Depends on**: US1 (the resolved value must exist before it can be reported).

### Tests for User Story 3 ⚠️

- [X] T032 [P] [US3] Write source-classification tests in `tests/test_claude_code_effort.py` for all four sources — `explicit`, `environment`, `clamp`, `inherited` — asserting the reported source for each
- [X] T033 [P] [US3] Write the honesty test: an `inherited` run must NOT print any effort value, since `~/.claude/settings.json` is never read by this process
- [X] T034 [P] [US3] Write the bounded-output test in `tests/test_claude_code_effort.py`: a dispatcher fanning out to N children emits exactly one identity banner, not N (the #359 streamed-polish flood)

### Implementation for User Story 3

- [X] T035 [US3] Add the run-identity value object to `campaignlib/api/backends.py` carrying `effective_model`, `effort_sent`, `source`, `override_sent`, `thinking_on`, mirroring `campaignlib/api/codex_cli.py:121`
- [X] T036 [US3] Classify the source in `_claude_code_generate` in `campaignlib/api/backends.py`, distinguishing `clamp` (thinking suppressed, clamp-eligible model, nothing chosen) from `inherited` (no override sent at all) — the split that makes today's single silent omission legible
- [X] T037 [US3] Emit exactly one identity banner per run, before the child spawns, using the four wordings in `contracts/run-identity.md` — the `clamp` line must state its reason and say the operator's `settings.json` level was not used
- [X] T038 [US3] Add the effort state and source to the three sidecars that already record the effective model — `session_doc/scene_extract.py:169`, `session_doc/enhance_summary.py:217`, `pipelines/ensemble/polish.py:937` — plus `campaignlib/util.py:101` `save_log`. Add no new metadata store (FR-019)
- [X] T039 [US3] Preserve structured error identity — a refusal must stay recognisable to the existing `is_error` / non-zero-exit / non-JSON-output branches in `_claude_code_generate` and must not degrade into an untyped `RuntimeError` — `campaignlib/api/backends.py`
- [X] T040 [US3] Report the effort state in `server/routers/connections.py` graph results, mirroring the Codex handling at lines 11–13

**Checkpoint**: US1 + US3 both work. `quickstart.md` §4–5 pass, and SC-008 is demonstrable.

---

## Phase 5: User Story 2 — Choose and Reuse the Effort Level in the UI (Priority: P1)

**Goal**: Every Claude Code-capable surface exposes the control; the choice persists across reload and backend switching; the stored Codex selection is never disturbed.

**Independent Test**: `quickstart.md` §7 — on each of the four selector surfaces, the control appears only under `claude-code`, survives reload, survives a round trip through `codex-cli` with both values intact, and persists `Claude Code default` as an absent field rather than `""`.

**Depends on**: US1 (Principle VI — the UI shells out to the CLI; there is nothing to expose until the flag exists). This is a real dependency, not a staffing preference.

### Tests for User Story 2 ⚠️

- [X] T041 [P] [US2] Write tier-precedence tests in `tests/test_claude_code_effort_config.py` for `resolve_selection`: request > service > platform > environment > omission, with the correct origin reported at each tier
- [X] T042 [P] [US2] Write the isolation test in `tests/test_claude_code_effort_config.py`: setting `claude_code_effort` must not read, write, or clear `codex_reasoning_effort`, and both must persist simultaneously on one profile
- [X] T043 [P] [US2] Write the wrong-backend test in `tests/test_claude_code_effort_config.py`: an effort stored against a non-`claude-code` backend is a legal write and a refused run (storable-not-runnable), with the refusal reachable
- [X] T044 [P] [US2] Write `tests/test_claude_code_effort_ui.py` as a static source sweep over `frontend/src/**`, mirroring `tests/test_codex_reasoning_ui.py` — assert the control on each named surface and assert the vocabulary is NOT hardcoded in `config.ts`

### Implementation for User Story 2

- [X] T045 [US2] Extend `resolve_selection` in `server/platform_config_service.py` (lines 379–499) with `claude_code_effort`, its origin, and its override flag, mirroring the Codex block — including the wrong-backend refusal at line 499
- [X] T046 [US2] Carry the three new fields on `ResolvedSelection` in `server/platform_config_service.py` (lines 554–556) and its consumers
- [X] T047 [US2] Add `claude_code_efforts: list(CLAUDE_CODE_EFFORTS)` to the `/models` payload at `server/routers/config_routes.py:160` — the frontend must read the vocabulary from here, never declare it
- [X] T048 [P] [US2] Pass the flag in `_build_*_cmd()` in `server/routers/ensemble.py` (lines 46 area) and `server/routers/scene_editor.py`, taking a sentinel and resolving from the config service at the route edge — **no `claude-code`-shaped default literal in a router**
- [X] T049 [P] [US2] Add `claudeCodeEfforts` and `claudeCodeEffort` refs to `frontend/src/stores/config.ts` (mirroring lines 102–189) and the types and payload field to `frontend/src/api/client.ts`
- [X] T050 [P] [US2] Add the selector to `frontend/src/components/layout/AppSidebar.vue` (global/platform tier)
- [X] T051 [US2] Add the selector and the resolved-state display to `frontend/src/components/shared/SelectionPanel.vue`, mirroring the Codex handling at lines 57, 111, 116, 151, 215, 219, 289, 292 — gate visibility on the resolved/draft backend being `claude-code`
- [X] T052 [P] [US2] Add the selector to `frontend/src/components/scene-editor/KnobDrawer.vue`
- [X] T053 [P] [US2] Add the selector to `frontend/src/views/ensemble/EnsembleSetup.vue` and carry it into the run in `frontend/src/views/ensemble/useEnsembleRun.ts`
- [X] T054 [P] [US2] Carry the selection into launches from `frontend/src/views/session/SessionDocEditor.vue` and `frontend/src/views/session/ReviewAssemble.vue`
- [X] T055 [P] [US2] Surface the identity banner in `frontend/src/components/shared/StreamOutput.vue` and the effective model/effort in `frontend/src/views/prep/ConnectionGraph.vue`
- [X] T056 [US2] Verify `Claude Code default` persists as an **absent** YAML field, not `""` and not a copied platform value: `grep -n claude_code_effort <campaign>/config/session_doc.yaml` returns nothing after selecting it

**Checkpoint**: All three P1 stories work. `quickstart.md` §7 passes on all four surfaces.

---

## Phase 6: User Story 4 — Preserve Today's Behaviour on Omission (Priority: P2)

**Goal**: Prove the feature changed nothing for anyone who does not use it.

**Independent Test**: `quickstart.md` §4's `git stash` diff — the omission invocation is byte-identical to the pre-feature baseline captured in T002.

- [X] T057 [US4] Diff the omission invocation against the T002 baseline (`/tmp/before.txt` vs a fresh `--dump-only` capture) per `quickstart.md` §4 and confirm byte-identity apart from the new report lines (SC-005)
- [X] T058 [P] [US4] Assert in `tests/test_claude_code_effort_config.py` that loading and running a campaign whose `config/session_doc.yaml`, `config/ensemble.yaml`, and `config/platform.yaml` carry no effort value leaves all three files byte-identical on disk (FR-017)
- [X] T059 [P] [US4] Run the other-backend regression suites unchanged: `tests/test_codex_reasoning_effort.py`, `tests/test_codex_reasoning_config.py`, `tests/test_backend_seam_guardrails.py` (SC-007, FR-023)
- [X] T060 [P] [US4] Extend `tests/test_backend_seam_guardrails.py` to assert the `claude-code` isolation guarantees still hold: credential stripping, `--disallowed-tools '*'`, `--strict-mcp-config`, the `CLAUDE_CODE_MAX_OUTPUT_TOKENS` ceiling, and auto-continue detection (FR-022)
- [X] T061 [P] [US4] Extend `tests/test_subprocess_abort.py`, `tests/test_sd_agent.py`, `tests/test_ensemble_dispatch.py`, and `tests/test_platform_config_service.py` with the new field, mirroring their #359 additions

**Checkpoint**: The feature is additive and provably so.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T062 Write the FR-025 parity guardrail: extend `tests/test_claude_code_effort_ui.py` with the `data-model.md` §6 entry-point inventory so a new Claude Code-capable surface that does not accept, forward, expose, or report the setting fails the build
- [X] T063 [P] Document the option in `docs/cli/cli_tools.md`: accepted values, precedence, omission behaviour, the thinking interaction, and the meaning of each reported state (FR-024)
- [X] T064 [P] Document the config tiers in `docs/core/configuration.md`, `docs/config/schema.md`, `docs/config/values.md`, and `docs/config/platform-isolation.md`, mirroring the #359 entries
- [X] T065 [P] Document the UI location in `docs/web/web_ui.md`
- [X] T066 Open the follow-up issue research R7 recommends — a first-class thinking control (CLI flag + UI face) — cross-referencing this feature and the measurement in `campaignlib/api/backends.py`'s module comment. `xhigh`/`max` are currently reachable only via an environment variable, which is a consequence of the FR-009 ruling, not a defect in it. **Opened as [#365](https://github.com/kostadis/CampaignGenerator/issues/365)**
- [X] T067 Run `cd frontend && npm run build` and confirm the production build passes
- [X] T068 Execute `quickstart.md` end to end **from `~/src/CampaignGenerator`, not the worktree** (issue #286), with `python -m pytest tests/ -rs`, and record which files skipped. A skipped file is not a passed file
- [X] T069 Record the quickstart result in `specs/021-claude-code-effort/quickstart.md` — #359's sibling feature left this unexecuted (issues #313, #319, #335 are the same debt on three other specs)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies; T001 blocks all UI validation
- **Foundational (Phase 2)**: blocks every story
- **US1 (Phase 3)**: after Foundational — the MVP
- **US3 (Phase 4)**: after US1 — cannot report a value that does not resolve yet
- **US2 (Phase 5)**: after US1 — Principle VI: the UI shells out to the CLI, so there is nothing to expose until the flag exists
- **US4 (Phase 6)**: after US1; T002's baseline must be captured before any source change
- **Polish (Phase 7)**: after all stories

### Story Independence — stated honestly

The template's ideal is fully independent stories. Two of these are not, and pretending otherwise would produce tasks that cannot run:

- **US3 and US2 both depend on US1.** US3 reports what US1 resolves; US2 is a face on the engine US1 builds. This is Principle VI working as designed, not a decomposition failure.
- **US1 alone is a genuine shippable increment**: the CLI capability, complete and safe, with reporting and UI still to come.
- **US3 and US2 are independent of each other** and can proceed in parallel once US1 lands.

### Within Each Story

Tests first and failing → seam (`campaignlib`) → CLIs → server → frontend. The seam is always first: routers and pipelines pass values, never command lines (Principle V).

---

## Parallel Opportunities

**Phase 2** — four files, no shared edits:

```
T006  server/session_editor_config_shared.py
T007  server/ensemble_config_shared.py
T008  server/platform_config_shared.py
T009  campaignlib/__init__.py
```

**Phase 3 tests** — T011, T012, T013, T014 together.

**Phase 3 dispatcher forwarding** — T026–T030, five separate files, after T017–T024 land:

```
T026  pipelines/ensemble/ensemble.py
T027  pipelines/ensemble/ensemble_batch.py
T028  pipelines/ensemble/ensemble_extract.py
T029  session_doc/sd_agent.py
T030  pipelines/ensemble/polish.py + facts_to_state.py
```

**Phase 5 frontend** — T049, T050, T052, T053, T054, T055 are separate components; only T051 (`SelectionPanel.vue`) is serialized, being the largest surface.

**Phase 7 docs** — T063, T064, T065 together.

---

## Implementation Strategy

### MVP: US1 only

1. Phase 1 Setup → Phase 2 Foundational → Phase 3 US1
2. **Stop and validate**: `quickstart.md` §1–3, §6
3. The CLI capability is complete and safe. Reporting still shows today's silence; the UI still shows no control. Both are honest gaps, not broken states.

### Incremental delivery

1. Foundational → field exists and cannot be dropped
2. **US1** → CLI capability (MVP)
3. **US3** → the silent clamp becomes legible — the highest-value increment after the MVP, since it fixes a live defect rather than adding capability
4. **US2** → UI parity, satisfying Principle XI
5. **US4** → prove nothing else moved
6. Polish → docs, guardrail, follow-up issue

### Sequencing note

US3 before US2 is deliberate. US3 closes an existing defect (a run silently downgrading the operator's pinned level with no way to find out); US2 adds reach to a capability that already works from the CLI. If the feature is cut short, US1 + US3 is a better place to stop than US1 + US2.

---

## Notes

- `[P]` = different files, no dependency on incomplete work
- The seam is `campaignlib/api/backends.py`; no router or pipeline builds a `claude` command line (Principle V)
- One refusal message, one banner per run — both from a single source, or they drift
- Commit per task or logical group; the branch is `021-claude-code-effort` in its own worktree
- Constitution Principle XIII is not triggered: every field is additive, so there is no migrator and no `migration.md`
