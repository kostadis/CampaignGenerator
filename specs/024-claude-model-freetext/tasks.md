---

description: "Task list for 024-claude-model-freetext"
---

# Tasks: Hand-Entered Claude Model Ids

**Input**: Design documents from `/specs/024-claude-model-freetext/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: Included. Not because TDD was requested in the abstract, but because the
plan names three test files as deliverables and one of them (S1, the tier-check
ordering) guards a requirement that **no test of known model ids can catch**. T011
is written to fail first for exactly that reason.

**Organization**: Tasks are grouped by user story. The honest caveat, stated once:
US1, US2 and US4 are three *behaviours* delivered by one structural change to one
component. Removing the widget fork makes all three work at once — so their phases
are split by what must be *verified* separately, not by pretending the code lands
in three pieces. US3 is genuinely independent and shares no file with any of them.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- Exact file paths in every description

## Path Conventions

Web application, existing layout: `frontend/src/` (Vue SPA), `frontend/e2e/`
(Playwright), `server/` (FastAPI), `tests/` (pytest), `docs/`. No new directory.

---

## Phase 1: Setup

**Purpose**: Establish the baseline this feature must not break.

- [X] T001 Record the pre-change baseline from the repo root: `python -m pytest tests/test_synthesis_capable_registry.py tests/test_config_routes.py tests/test_platform_config_service.py -q`, then `cd frontend && npx playwright test`. Note which pass. Exactly one currently-green assertion may go red by the end of this feature — `test_retired_date_suffixed_id_is_gone`, per `contracts/synthesis-capability.md` § Test migration. Any other red is a regression.
- [X] T002 [P] Confirm the package is editable-installed into the venv the server runs under — `uv pip install -e . --python "$VIRTUAL_ENV/bin/python"` — so `./startup` can serve the manual pass in `quickstart.md` §4. Symptom of skipping this: `Stream error — check terminal`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: A pre-existing persistence defect that every frontend story's
assertions depend on.

**⚠️ Blocks US1, US2 and US4.** It does **not** block US3, which shares no file
with it — Phase 5 may start immediately, in parallel with everything here.

- [X] T003 Fix the whitespace split-brain in `setModel` in `frontend/src/components/layout/AppSidebar.vue`: trim once at function entry and use that single trimmed value for `modelMemory.value[currentBackend.value]`, for `config.model`, and for the `default_model` field of the `updateRuntime` payload. Today the memory is trimmed and the active model is not, so one paste writes two different strings for one choice (research R5, contracts C6/C7).

**Checkpoint**: persistence writes one value. Frontend stories can begin.

---

## Phase 3: User Story 1 - Adopt a newly released Claude model the day it ships (Priority: P1) 🎯 MVP

**Goal**: On the metered Anthropic backend, a Claude model id the app has never
heard of can be typed, persists, and dispatches verbatim.

**Independent Test**: Type `claude-opus-6` on the `anthropic` backend, reload, confirm it is still active, and confirm the `PUT /api/config/runtime` body carried it.

### Tests for User Story 1

- [X] T004 [P] [US1] Create `tests/test_model_selector_ui.py` with source-level guardrails over `frontend/src/components/layout/AppSidebar.vue`: assert `list="cg-model-ids"` is present, assert `<datalist` is present, assert `modelIsFreeText` is **absent**, and assert `<option v-for="m in config.models"` is **absent** (the curated list must no longer be rendered as `<select>` options). Mirror the docstring style of `tests/test_claude_code_effort_ui.py` — state plainly that source assertions prove a control exists in the file, not that it renders or persists, and point at `quickstart.md` §3/§4 for what does. (Contracts C1, C2; Principle XI.)
- [X] T005 [P] [US1] Create `frontend/e2e/model-selector.spec.ts`. Route-mock the five URLs `frontend/src/stores/config.ts::load()` fetches — `/api/config/`, `/api/config/models`, `/api/config/status`, `/api/editor/config`, `/api/grounding/config` — plus a capturing handler for `PUT /api/config/runtime` (body shape `{ values: {...} }`; note `updateRuntime` calls `refresh()` afterwards, so `/api/config/` must serve the updated value for reload assertions to mean anything). Assert: typing `claude-opus-6` on the `anthropic` backend produces exactly one PUT whose `values.default_model` and `values.default_models.anthropic` are both `"claude-opus-6"`; pasting `"  claude-opus-6  "` produces the trimmed value in **both** fields; after a reload the field still reads `claude-opus-6`. (Contracts C6, C7, C10, C11; `quickstart.md` §3 rows 1–4.)

### Implementation for User Story 1

- [X] T006 [US1] In the `model-selector` block of `frontend/src/components/layout/AppSidebar.vue`, replace the `v-if="modelIsFreeText"` `<input>` / `v-else` `<select>` fork with a single `<input class="model-select" list="cg-model-ids" :value="displayedModel" @change="setModel(($event.target as HTMLInputElement).value)">`, rendered unconditionally on all five backends (contract C1).
- [X] T007 [US1] Delete the now-unused `modelIsFreeText` computed and its explanatory comment block from `frontend/src/components/layout/AppSidebar.vue`, replacing the comment with one stating why the control is uniform. A widened condition left in place is a fork waiting to narrow again (contract C2).
- [X] T008 [US1] Add `<datalist id="cg-model-ids">` immediately after the input in `frontend/src/components/layout/AppSidebar.vue`, rendering `config.models` as `<option :value="m">`. Unconditional at this stage; T016 makes population backend-aware.
- [X] T009 [US1] Extend the per-backend `placeholder` expression on that input in `frontend/src/components/layout/AppSidebar.vue` to cover `anthropic` and `claude-code` (e.g. `e.g. claude-opus-5`), preserving the existing dgx / openrouter / codex-cli text and the `title` attribute's intent (contract C5).

**Checkpoint**: US1 delivered. T004 and T005 pass; a new Claude model is reachable
on the metered API with no code change. **This is a shippable MVP on its own.**

---

## Phase 4: User Story 2 - Same freedom on the subscription Claude backend (Priority: P2)

**Goal**: `claude-code` behaves identically to `anthropic`, per-backend memory
survives switching, and no backend has a different entry mechanism.

**Independent Test**: Type an unlisted id on `claude-code`, switch away to `dgx` and back, confirm it returns unchanged and that the `anthropic` value was untouched.

**Note**: Phase 3's structural change already makes this work — these tasks prove
it and pin it against re-forking.

- [X] T010 [US2] Extend `frontend/e2e/model-selector.spec.ts` with the parity and memory cases: typing an unlisted Claude id on `claude-code` persists it; `anthropic` → `dgx` → `anthropic` restores the typed id unchanged; switching to a backend with no remembered model leaves the field empty rather than showing another backend's model or a curated default (contracts C12, C13; `quickstart.md` §3 row 5). Sequential with T005 — same file.
- [X] T011 [P] [US2] Add a uniformity guardrail to `tests/test_model_selector_ui.py`: assert the source contains no backend name inside a conditional that selects the MODEL control's *element type* — concretely, that `list="cg-model-ids"` appears exactly once and no `v-if`/`v-else` pair wraps it. Note in the test's docstring that `.model-select` is shared with the THINKING / EFFORT / REASONING selects, so counting that class is not a valid proxy (contract C1, FR-011).

**Checkpoint**: all five backends enter a model the same way.

---

## Phase 5: User Story 3 - A new model is not mistaken for a weak one (Priority: P2)

**Goal**: the ensemble synthesis warning stops treating "unlisted" as "weak", and
keeps firing for a genuinely sub-tier model.

**Independent Test**: A `claude-code` synthesize run with `claude-opus-6` emits no warning; the same run with `claude-haiku-6` still does.

**⚠️ Fully independent of Phases 2–4 and 6** — server-side only, shares no file
with them. Start it at T001 if working in parallel.

### Tests for User Story 3

- [X] T012 [US3] Add the four new predicate cases to `tests/test_synthesis_capable_registry.py`, importing `synthesis_capable` from `server.routers.ensemble`: `claude-opus-6` is capable (the regression this feature prevents); `claude-haiku-6` is **not** capable (S1 — the tier check must beat the prefix check, and no test of *known* ids can catch a reversal); `anthropic/claude-opus-6` is capable (rule 4); and end-to-end, a `claude-code` synthesize run with an unlisted Claude model emits no `WARNING_FRAGMENT` while one with an unlisted Haiku id still does. **These must fail first** — the import does not resolve yet.

### Implementation for User Story 3

- [X] T013 [US3] Add `synthesis_capable(model: str | None) -> bool` to `server/routers/ensemble.py`, implementing the six rules of `contracts/synthesis-capability.md` **in the stated order**: falsy → True; `_SUB_SONNET_TIER` substring (case-insensitive) → False; `claude-` prefix → True; `anthropic/claude-` prefix → True; `_THIRD_PARTY_SYNTHESIS_CAPABLE` membership → True; otherwise False. Pure function, no I/O (S1–S4).
- [X] T014 [US3] Delete the `SYNTHESIS_CAPABLE` set from `server/routers/ensemble.py`, keeping `_SUB_SONNET_TIER` and `_THIRD_PARTY_SYNTHESIS_CAPABLE` as the predicate's inputs. Rewrite the module comment block above them to describe the predicate and to record *why* a derived set was removed rather than refreshed — a derived set that no longer decides anything is a second declaration of a rule that has an owner (research R3, Principle XII).
- [X] T015 [US3] Change the warning condition in the synthesize run handler of `server/routers/ensemble.py` (currently `model not in SYNTHESIS_CAPABLE`, around line 1148) to `not synthesis_capable(model)`. **Keep the `backend != "anthropic"` guard exactly as it is** — it is why this never misfired on the metered API and only ever misfired on `claude-code` (research R2).
- [X] T016 [US3] Migrate the remaining assertions in `tests/test_synthesis_capable_registry.py` off set membership and onto the predicate: re-point the five tests that still hold (registry models above Haiku are capable; the Haiku tier is excluded; frontier third-party ids survive; the platform default never warns about itself; no warning for a current registry model). Replace `test_retired_date_suffixed_id_is_gone` — under the predicate `claude-sonnet-4-20250514` *is* capable, because it is a Sonnet — with a test that a future unreleased Anthropic id is capable, which is the property the module must now guarantee and the one the old set could never satisfy. Update the module docstring to explain the snapshot → predicate change so a future reader does not read the replacement as a weakening (research R3).

**Checkpoint**: US3 delivered. The warning judges capability, not familiarity.

---

## Phase 6: User Story 4 - Keep one-click access to the models already known (Priority: P3)

**Goal**: the curated ids remain a one-click, zero-keystroke choice on the Claude
backends, and are correctly absent everywhere else.

**Independent Test**: On the `anthropic` backend, pick a curated id from the suggestion list without typing; on `dgx`, confirm no suggestions appear.

- [X] T017 [US4] Make the `<datalist>` population backend-aware in `frontend/src/components/layout/AppSidebar.vue`: render `config.models` as options when the active backend is `anthropic` or `claude-code`, and render none otherwise. An empty datalist must leave the input fully usable — no placeholder option, no disabled state (contracts C3, C4).
- [X] T018 [US4] Extend `frontend/e2e/model-selector.spec.ts`: suggestion options are present on both Claude backends and absent on `dgx` / `openrouter` / `codex-cli`; choosing a curated id applies it without typing (contract C3; SC-004). Sequential with T005 and T010 — same file.

**Checkpoint**: the common case is no slower than before the feature.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T019 [P] Update `docs/config/values.md` (~lines 178, 189) where `server/config.py::MODELS` is described as "the selectable-model list `GET /api/config/models` serves". It is now a *suggestion* list with no veto. The passage at line 178 already argues the right principle for `compatible()` — extend it to say both former gates now follow it.
- [X] T020 [P] Update `docs/config/platform-isolation.md` (~lines 475–477), which documents `SYNTHESIS_CAPABLE` as `{m for m in MODELS if "haiku" not in m}` plus frontier ids. That derivation no longer exists; describe the predicate and link `specs/024-claude-model-freetext/contracts/synthesis-capability.md`.
- [X] T021 [P] Update `docs/web/web_ui.md` to state that the sidebar MODEL control accepts a typed id on every backend and that the curated ids are suggestions. Check the line ~253 advice about switching models in "the global model selector" still reads correctly against the new control.
- [ ] T022 Decide the warning copy nit flagged in `contracts/synthesis-capability.md` § Warning text: `'<model>' is not on the synthesis-capable list` names a mechanism that no longer exists. Either keep it (and leave `WARNING_FRAGMENT` in `tests/test_synthesis_capable_registry.py` untouched) or reword to describe the judgement, updating that constant in the same change. **GM's call — not required by any FR.**
- [X] T023 Run the full suite from the repo root: `python -m pytest tests/`, then `cd frontend && npx playwright test`. Compare against the T001 baseline; the only permitted change is the one flip named there.
- [X] T024 Run `cd frontend && npm run build` to confirm `vue-tsc` type-checks the changed component — the `$event.target as HTMLInputElement` cast in T006 replaces an `HTMLSelectElement` cast and is the likeliest type error.
- [ ] T025 Walk `quickstart.md` §4 (ten manual steps) against a real campaign with `./startup`. §4.9 in particular must be run on the **Sub (`claude-code`)** backend — the warning never fires on the API backend, so testing there proves nothing.

---

## Dependencies

```
Phase 1 (T001–T002)
   │
   ├────────────────────────────────────────────┐
   │                                            │
   ▼                                            ▼
Phase 2  T003  (AppSidebar setModel)      Phase 5  US3  (server only)
   │                                       T012 → T013 → T014 → T015 → T016
   ▼                                            │
Phase 3  US1  🎯 MVP                            │
   T004 ─┐                                      │
   T005 ─┤ (parallel, new files)                │
   T006 → T007 → T008 → T009  (AppSidebar.vue, sequential)
   │                                            │
   ▼                                            │
Phase 4  US2                                    │
   T010 (e2e, seq. w/ T005)                     │
   T011 (pytest, parallel)                      │
   │                                            │
   ▼                                            │
Phase 6  US4                                    │
   T017 (AppSidebar.vue) → T018 (e2e)           │
   │                                            │
   └──────────────────┬─────────────────────────┘
                      ▼
              Phase 7  Polish
              T019–T021 parallel; T022 (decision) → T023 → T024 → T025
```

**Story independence**:

| Story | Depends on | Can ship alone? |
|---|---|---|
| US1 (P1) | Phase 2 | **Yes — the MVP** |
| US2 (P2) | US1's structural change | Yes, but it is verification of US1's change rather than new code |
| US3 (P2) | Nothing in this feature | **Yes — entirely independent** |
| US4 (P3) | US1's `<datalist>` (T008) | Yes |

## Parallel Opportunities

1. **The big one: Phase 5 (US3) runs start-to-finish alongside the entire frontend track.** Five server-side tasks, zero shared files with Phases 2/3/4/6. Two people, or two sessions, finish this feature in roughly the time of the longer half.
2. **T004 ‖ T005** — two new test files, no shared state, both writable before the component changes.
3. **T002 ‖ T001** — environment prep during the baseline run.
4. **T019 ‖ T020 ‖ T021** — three separate docs.

**Not parallel, despite appearances**: T006 → T007 → T008 → T009 → T017 all edit
`frontend/src/components/layout/AppSidebar.vue`; T005 → T010 → T018 all edit
`frontend/e2e/model-selector.spec.ts`; T012 → T016 both edit
`tests/test_synthesis_capable_registry.py`.

## Implementation Strategy

**MVP = Phase 1 + Phase 2 + Phase 3 (T001–T009).** Nine tasks, two files touched,
and the GM can run a model that shipped this morning. Everything after it is
parity, correctness of a warning, and not regressing the common case — all real,
none of it blocking the complaint that started this.

**Suggested order if working alone**: Phase 5 first. It is self-contained, it has
the one genuine fail-first test, and it is the half most likely to surface a
surprise (the `backend != "anthropic"` guard, the ordering requirement, the test
flip). Landing it first means the frontend work — which is mechanical once the
fork is gone — is not competing for attention with the subtle half.

**Do not** skip T003 on the grounds that it is unrelated to the widget. It is the
reason the trim assertion in T005 passes, and it turns a latent two-value write
into a correct one right before this feature makes every backend able to reach it.

---

## Implementation record (2026-09-07)

**23 of 25 tasks complete.** T022 and T025 are deliberately open — one is a GM
decision, one needs a human at a running app.

### Verification actually performed

| Check | Result |
|---|---|
| `pytest tests/test_model_selector_ui.py` | **9 passed** (6 failed before T006–T009, as designed) |
| `pytest tests/test_synthesis_capable_registry.py` | **31 passed** (collection error before T013, as designed) |
| `pytest tests/` (full, minus `test_dnd_sheet.py`) | **4826 passed, 56 failed** — and the identical 56 fail on a clean tree, module-for-module and count-for-count. Verified by stashing every change and re-running. **Zero regressions.** |
| `npm run build` (`vue-tsc`) | clean |
| `npx playwright test` | **could not run — see below** |

### Two environment blockers, neither introduced here

1. **Playwright cannot run on this machine.** `@playwright/test` is pinned to
   1.55.0, which wants chromium build **1187**; only **1228** is present, and its
   internal layout differs (`chrome-headless-shell-linux64/chrome-headless-shell`
   vs the expected `chrome-linux/headless_shell`), so a symlink cannot bridge it.
   `npx playwright install` refuses outright: `Playwright does not support
   chromium on ubuntu26.04-x64`. **All 13 pre-existing e2e tests were already
   failing this way before any change here** — this is not a regression and not
   something this feature can fix.

   Consequence: `frontend/e2e/model-selector.spec.ts` (T005/T010/T018, 11 tests)
   is **written but unexecuted**. It is the only proof of FR-003/FR-004
   persistence, so until it runs somewhere, `quickstart.md` §4.2–§4.4 are the
   real coverage. Fixing it means bumping `@playwright/test` to a release that
   matches build 1228 — a dependency change affecting the 13 existing specs, out
   of scope here and worth its own change.

2. **`tests/test_dnd_sheet.py` cannot be collected** — `ModuleNotFoundError: No
   module named 'fitz'` (pymupdf absent). Pre-existing, unrelated, excluded from
   the run above rather than worked around.

### Deviations from the plan

- **T011's assertion was strengthened.** The planned check ("`list=` appears once,
  no `v-if`/`v-else` pair") is in `test_datalist_is_wired_to_the_input` and
  `test_model_control_is_not_forked_by_backend`. Added on top:
  `test_no_backend_is_named_inside_the_control_markup`, which forbids *any*
  backend literal inside the extracted `model-selector` block. The plan's version
  would pass a template that re-forked on placeholder text first; this one does
  not. All structural assertions are block-scoped via a regex extractor, because
  `.model-select` is shared with three legitimate fixed-vocabulary selects in the
  same footer and file-wide counting of it proves nothing.
- **T017 landed inside T006's edit.** `suggestedModels` was written
  backend-aware from the start rather than unconditional-then-narrowed; splitting
  it would have meant writing a line to delete it two tasks later.
- **One task the plan did not have.** `from server.config import MODELS` became
  unused in `server/routers/ensemble.py` once `SYNTHESIS_CAPABLE` was deleted, and
  was removed with it.
- **`frontend/e2e/fixtures/modelSelector.ts` is new** and not named in the plan.
  The existing e2e specs keep their mocks in `e2e/fixtures/`; following that
  convention needed a file the task list did not anticipate.

### Open

- **T022** — the warning still reads `'<model>' is not on the synthesis-capable
  list`, naming a mechanism that no longer exists. Not changed: no FR requires it,
  and rewording means touching `WARNING_FRAGMENT` in the test module. GM's call.
- **T025** — `quickstart.md` §4's ten manual steps need a running server and a
  real campaign. §4.9 must be exercised on the **Sub (`claude-code`)** backend;
  the warning never fires on the API backend, so testing there proves nothing.
