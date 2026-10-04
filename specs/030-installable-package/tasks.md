# Tasks: Installable CampaignGenerator package

**Input**: Design documents in `specs/030-installable-package/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [resource contract](./contracts/resources.md), [wiring contract](./contracts/wiring-migration.md), [quickstart.md](./quickstart.md), [migration.md](./migration.md)

**Tests**: Included because FR-012 explicitly requires a built-wheel installation regression test and FR-015/FR-016 require a safe, verifiable migration. The tests below target those observable contracts; straightforward wording and path cleanup use the integration checks.

**Organization**: Each user-story phase has a standalone outcome and acceptance check. [P] means the task may proceed alongside other ready tasks touching different files. All paths are relative to the CampaignGenerator root; `../mneme/` paths refer to the coordinated sibling repository.

## Phase 1: Setup

**Purpose**: Fix the resource inventory before changing the sites it names.

- [X] T001 Create `specs/030-installable-package/resource-audit.md` with one row for each of issue #494's 17 lookups across 16 modules, recording current use, resource class, planned owner, and verification result; reconcile any additional checkout-relative runtime lookup found by `rg` before implementation.
- [X] T002 [P] Create the importable `campaignlib/resources/__init__.py` anchor and the `campaignlib/resources/agents/` directory for byte-for-byte shipped prompt copies; leave existing campaign-owned `config/config.yaml` in its present role.

**Checkpoint**: The audit names every site and the read-only resource anchor exists.

---

## Phase 2: Foundational

**Purpose**: Make a wheel and isolated smoke harness available to every story.

- [X] T003 Update `pyproject.toml` wheel inclusion so `campaignlib/resources/**` and `session_doc/review/reviewer.html` ship, while `frontend/dist` remains outside the installed distribution; do not change the seven declared package trees unintentionally.
- [X] T004 [P] Add `tests/helpers/installed_distribution.py` to build a wheel, install it non-editably into a temporary environment, run commands from an unrelated working directory with checkout `PYTHONPATH` removed, and inspect wheel members without touching the operator's environment.

**Checkpoint**: The harness can build a wheel and expose missing resources as failures. T003 and T004 can be completed independently.

---

## Phase 3: User Story 1 — use an installed copy away from the checkout (P1) 🎯 MVP

**Goal**: A fresh non-editable installation imports and starts representative commands from an unrelated directory; shipped resources and command dispatch need no checkout path.

**Independent test**: Build/install the wheel using `tests/helpers/installed_distribution.py`, then pass all five imports, `registry --help`, `distill --help`, `sd_verify_quotes --help`, shipped-resource inventory, and an installed `new_workspace` run that writes only to a temporary workspace in `tests/test_installable_wheel.py`.

### Tests for User Story 1

- [X] T005 [US1] Add a failing `tests/test_installable_wheel.py` smoke test that checks the five package imports, three named console commands, required prompt files and `reviewer.html` in the built wheel; from unrelated CWD, run the installed `new_workspace` entry point against a temporary workspace, assert it creates `config/config.yaml` there, and compare installed package contents before and after to catch writes inside installed code.
- [X] T006 [P] [US1] Extend `tests/test_reviewer_selfcontained.py` to read the reviewer page through the installed `session_doc.review` package and fail when the wheel omits `reviewer.html`.

### Implementation for User Story 1

- [X] T007 [US1] Move all shipped `config/agents/**/*.md` prompt bytes to matching logical names under `campaignlib/resources/agents/` and move `config/system_prompt.md` to `campaignlib/resources/system_prompt.md`; verify exact byte equality against the pre-move source, keep `config/config.yaml` campaign-owned, and avoid two editable copies of each default.
- [X] T008 [US1] Change the shipped-default branches of `load_agent_prompt` and `load_repo_file` in `campaignlib/config.py` to read `campaignlib.resources` through `importlib.resources`, preserving current override calls until US2 completes the full precedence contract.
- [X] T009 [P] [US1] Read `reviewer.html` as a package resource in `session_doc/review/serve.py` and keep its existing response bytes and content type.
- [X] T010 [P] [US1] Replace sibling `.py` subprocess paths with active-interpreter module invocations in `pipelines/ensemble/ensemble_extract.py`, `pipelines/ensemble/ensemble.py`, and `pipelines/ensemble/ensemble_batch.py`; keep argument order and exit handling unchanged.
- [X] T011 [P] [US1] Replace the checkout-root subprocess target in `pipelines/grounding/grounding_sections.py` with a module or current-interpreter console entry point for `synthesise_world_state`; remove its now-unneeded root insertion.
- [X] T012 [P] [US1] Remove unused checkout-root `sys.path` insertions in `pipelines/grounding/event_spine.py`, `pipelines/grounding/thread_registry.py`, `pipelines/grounding/build_recent_events.py`, `server/routers/connections.py`, and `server/routers/scene_editor.py`, retaining normal package imports.
- [X] T013 [P] [US1] Remove the dead repo-root `.py` dispatch branch in `pipelines/rlm/mcp_server.py` and keep its current-interpreter console-script dispatch working from a wheel.
- [X] T014 [US1] Update direct source-path assertions in `tests/test_externalized_prompts.py`, `tests/test_plan_review_regressions.py`, `tests/test_gap_marker_pairing.py`, and the remaining tests found by `rg 'config/agents' tests/` for the moved prompt tree without changing approved prompt text, then run `tests/test_installable_wheel.py` and the relevant existing import/dispatch tests.

**Checkpoint**: The US1 independent test passes from a fresh wheel without the source tree on the import path. Every US1 site in `resource-audit.md` has its installed-mode result recorded.

---

## Phase 4: User Story 2 — preserve campaign prompt customization (P2)

**Goal**: Campaign overrides win, shipped defaults fill only absent overrides, and explicit missing files fail clearly.

**Independent test**: From an installed copy, place a distinct prompt at `<campaign>/config/agents/citation_rules_extract.md`, observe that it wins, remove it and observe the shipped prompt, then request an absent explicit path and receive a named error.

### Tests for User Story 2

- [X] T015 [US2] Update `tests/test_agent_prompt_loader.py` and `tests/test_config_env.py` with failing cases for nested prompt overrides, base-dir/CWD precedence, packaged fallback, strict placeholders and cache separation, existing logical `config/...` values in a workspace created by `new_workspace`, and no basename fallback for an absent explicit absolute path.
- [X] T016 [P] [US2] Update `tests/test_narrate_template_contract.py` to assert missing-prompt diagnostics name the campaign override and packaged default rather than a nonexistent wheel-adjacent checkout path.

### Implementation for User Story 2

- [X] T017 [US2] Finish `load_agent_prompt` and `load_repo_file` in `campaignlib/config.py` per `contracts/resources.md`: campaign first, packaged default second, `base_dir` ending in `config/` anchored at its parent for logical `config/...` names, strict explicit-path errors, traversal protection, and cache identity by selected origin.
- [X] T018 [US2] Update `_template_candidates` and related diagnostics in `session_doc/narrate.py` to show the actual campaign override and packaged-default logical location without changing prompt text or placeholder enforcement.
- [X] T019 [US2] Run the focused prompt and config tests in `tests/test_agent_prompt_loader.py`, `tests/test_config_env.py`, and `tests/test_narrate_template_contract.py`, then repeat the installed override/default scenario from `quickstart.md`.

**Checkpoint**: US2's two-process override/default check passes and an absent explicit file never substitutes a different shipped file.

---

## Phase 5: User Story 3 — use external wiring after installation (P2)

**Goal**: Installed commands read mneme-rendered wiring from the selected external location; upgrading old checkout wiring is deliberate, visible, and safe.

**Independent test**: Supply a distinct temporary wiring file through `MNEME_WIRING`, read it from an installed process outside the checkout, migrate a legacy file to a temporary destination, confirm the old file is gone, and confirm missing/malformed/overwrite cases refuse without lost state.

### Tests for User Story 3

- [X] T020 [US3] Add `tests/test_wiring.py` cases for explicit argument → `MNEME_WIRING` → `~/.config/campaigngenerator/wiring.yaml` precedence, optional missing default, errors for missing/malformed selected files, cache isolation, and no checkout/CWD fallback; test that checkout startup with a known retired `config/wiring.yaml` refuses it with the exact `migrate_wiring --source-checkout` instruction and leaves the file untouched, while a fresh checkout with no wiring retains optional behavior.
- [X] T021 [P] [US3] Add `tests/test_migrate_wiring.py` cases for raw mapping preservation including unknown keys, missing/malformed source refusal, existing-target refusal, deliberate `--force`, write failure leaving source intact, successful source cleanup, and an installed `migrate_wiring --help` from unrelated CWD.
- [X] T022 [P] [US3] Add `tests/test_wiring_migration_route.py` to assert the checkout route forwards explicit source, optional target and force to the CLI, refuses empty source, returns subprocess status/output, and never copies migration logic into the route.

### Implementation for User Story 3

- [X] T023 [US3] Implement the single wiring default and precedence in `campaignlib/wiring.py`, remove implicit checkout/CWD probes, and distinguish absent optional default from an invalid selected file; add a known-checkout retired-wiring refusal before normal checkout startup in `startup`, with `migrate_wiring --source-checkout DIR` in the error and no read or move of the retired file.
- [X] T024 [US3] Implement the one-shot `server/migrate_wiring.py` CLI per `contracts/wiring-migration.md`, using explicit `--source-checkout`, optional `--target`, guarded `--force`, safe target write, unknown-key reporting, and source removal only after success.
- [X] T025 [US3] Register `migrate_wiring = "server.migrate_wiring:main"` in `pyproject.toml` and confirm its installed entry point uses the current interpreter.
- [X] T026 [US3] Add `POST /api/config/wiring/migrate` in `server/routers/config_routes.py` as a thin `migrate_wiring` subprocess invocation with the contract's inputs and exit result; the route must not parse or write wiring itself.
- [X] T027 [US3] Add the explicit migration control to `frontend/src/views/Settings.vue`, showing source, destination, overwrite choice, and CLI result without running on page load.
- [X] T028 [P] [US3] In the coordinated mneme repository, change `../mneme/hypostasis.example.yaml` CampaignGenerator `config_target` and `../mneme/docs/architecture/config-wiring-graph.md` to the chosen user-config target and new precedence, and add a render/status integration assertion in `../mneme/tests/integration/test_apply.py`.
- [X] T029 [US3] Finalize `specs/030-installable-package/migration.md` against the implemented command and publish the same operator sequence in `docs/config/wiring-migration.md`, including affected checkouts, migration before installed use when no checkout reference is available, no-migration behavior, mneme target update, exact command, and verification.
- [X] T030 [US3] Run `tests/test_wiring.py`, `tests/test_migrate_wiring.py`, and `tests/test_wiring_migration_route.py`; then run a safe mneme `apply`/`status` integration check against the new target and record the result in `specs/030-installable-package/resource-audit.md`.

**Checkpoint**: The installed copy reads the same mneme-rendered values from the agreed external target, migration passes its refusal/success checks, and the checkout UI can invoke the same CLI. The mneme target change is a required cross-repository dependency before release.

---

## Phase 6: User Story 4 — keep the source-checkout workflow usable (P3)

**Goal**: Existing campaigns still start through `./start`; installed guidance accurately describes the CLI-only distribution.

**Independent test**: Run `./start --campaign-dir <existing-campaign>` from a checkout and load the normal interface; create a workspace and verify its next-step commands are usable without checkout-root Python paths; confirm installed documentation directs UI users to `./start`.

### Tests for User Story 4

- [X] T031 [US4] Update `tests/test_new_workspace_layout.py` to assert generated `config/config.yaml` retains portable logical prompt names and the next-step text uses installed console commands while labeling `./start` as checkout-only.

### Implementation for User Story 4

- [X] T032 [US4] Replace checkout-root `.py` and `startup` next-step examples in `pipelines/workspace/new_workspace.py` with declared console commands and explicit source-checkout `./start` guidance; preserve workspace output paths.
- [X] T033 [P] [US4] Write `docs/cli/installable_package.md` with non-editable installation, CLI-only scope, campaign prompt override order, wiring location and explicit override, runtime output ownership, and the `./start` checkout UI path.
- [X] T034 [US4] Remove the independent unbounded list in `requirements.txt` or make it delegate safely to the project declaration, and update its references including `docs/web/session_doc_editor.md:265` to use the chosen project dependency source; check no documented command resolves a relative `.` against the wrong directory.
- [X] T035 [US4] Run `tests/test_new_workspace_layout.py` and a checkout `./start --campaign-dir <existing-campaign>` smoke against the existing interface; record the result and exact source-checkout requirement in `specs/030-installable-package/resource-audit.md`.

**Checkpoint**: The checkout UI and workspace creation remain usable, and installed mode is documented as CLI-only.

---

## Phase 7: Polish and cross-cutting release checks

- [X] T036 Update `config/README.md`, `docs/README.md`, and `docs/core/configuration.md` to locate shipped defaults under `campaignlib/resources/`, distinguish campaign `config/agents/` overrides, link the installed-package and wiring-migration guides, and remove stale checkout-wiring claims. Update runtime advice and docstrings in `campaignlib/api/backends.py`, `campaignlib/api/client.py`, `pipelines/rlm/fivetools_catalog.py`, `pipelines/rlm/resolve_refs.py`, and `server/platform_config_service.py` to name the new wiring default or an explicit override; verify no user-facing diagnostic still directs operators to the retired checkout path.
- [X] T037 Re-run `tests/test_installable_wheel.py` against a freshly built wheel on Python 3.10 and 3.14 after all story changes, verifying five imports, three help commands, packaged prompts/reviewer page, installed migration entry point, an installed `new_workspace` write to a temporary workspace, and unchanged installed package contents. Make both Python versions required release/CI gates.
- [X] T038 Complete all 17 rows of `specs/030-installable-package/resource-audit.md` with evidence from focused tests or `quickstart.md`; refuse completion if any lookup still relies solely on checkout-relative paths.
- [X] T039 Run the relevant repository test suite under `tests/`, build the checkout frontend from `frontend/package.json`, and execute every safe local step in `specs/030-installable-package/quickstart.md`; time the documented install verification against SC-006's 10-minute target excluding environment creation/download, and report any failing gate rather than regenerating evidence to hide it.
- [X] T040 Recheck the thirteen principles in `specs/030-installable-package/plan.md` against the implemented design, especially packaged prompt bytes, CLI/UI migration parity, the one wiring accessor, and the no-fallback/no-lazy-migration rule; update the plan only if implementation changed a recorded decision.

**Checkpoint**: Wheel, checkout, migration, mneme coordination, documentation, and the 17-site audit agree.

---

## Dependencies and execution order

### Phase dependencies

- **Setup (T001–T002)** starts immediately. T002 can run alongside T001.
- **Foundational (T003–T004)** follows Setup and blocks the user-story wheel checks. T003 and T004 touch different files.
- **US1 (T005–T014)** follows Foundational and is the MVP. T005/T006 should fail before the resource implementation. T009–T013 can proceed alongside the prompt copy/loader work once Foundational is ready.
- **US2 (T015–T019)** can write its tests after Foundational, but its installed acceptance needs US1's packaged-default loader from T008.
- **US3 (T020–T030)** can develop its wiring tests and core separately after Foundational; its installed acceptance and cross-repository verification need the US1 wheel and the coordinated mneme target in T028.
- **US4 (T031–T035)** can write its tests and guidance after Foundational; its final `./start` regression check follows the resource changes from US1 and wiring change from US3.
- **Polish (T036–T040)** follows all four user-story checkpoints and mneme coordination.

### User-story dependency graph

```text
Setup → Foundational ──┬── US1 (P1, wheel MVP) ──┬── US2 installed acceptance
                      │                          ├── US3 installed acceptance
                      │                          └── US4 checkout regression
                      ├── US2 tests/core
                      ├── US3 tests/core + mneme target
                      └── US4 tests/docs
All four checkpoints + mneme apply/status → Polish/release
```

Each story's behavior can be developed and tested on its own contract. US2 and US3 use the completed US1 wheel for their final installed-mode acceptance; US4's final check protects the checkout against changes from the other stories.

### Parallel examples

- **US1**: T009 (`session_doc/review/serve.py`), T010 (`pipelines/ensemble/*.py`), T011 (`pipelines/grounding/grounding_sections.py`), T012 (root-insertion cleanup), and T013 (`pipelines/rlm/mcp_server.py`) touch separate files after Foundational. T007–T008 remain sequential for the packaged prompt path.
- **US2**: T016 (`tests/test_narrate_template_contract.py`) can be written alongside T015's loader tests; T017 and T018 follow their respective failing cases and touch different files.
- **US3**: T020–T022 create separate test files; T028 in mneme can proceed beside local wiring and migration implementation because the target contract is already fixed. T026 follows T024/T025; T027 follows the route contract.
- **US4**: T033 (`docs/cli/installable_package.md`) can proceed alongside T032 (`pipelines/workspace/new_workspace.py`); T034 follows the dependency-source decision and touches separate files.

## Implementation strategy

1. Complete Setup and Foundational, then implement US1 and pass the actual wheel smoke. This is the smallest usable increment: installed commands start away from the checkout.
2. Add US2 so existing campaign prompts retain priority over the shipped defaults. Verify both origins in separate installed processes.
3. Add US3 wiring, migration CLI/UI, and the mneme render-target change. Do not declare the external install complete before mneme `apply`/`status` agrees.
4. Add US4's workspace guidance and checkout regression proof, then run the cross-cutting release checks. Stop at each checkpoint and fix its failing contract before proceeding.

## Notes

- Tests in each story precede the implementation they guard. Existing test files may need focused edits when their assumptions intentionally change; keep prompt bytes and campaign data unchanged.
- The mneme files in T028 are a coordinated repository change, not files to create inside CampaignGenerator.
- The user explicitly chose a CLI-only installed distribution; the checkout UI still exposes the new migration capability under Constitution XI.
