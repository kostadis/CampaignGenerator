---

description: "Task list for Optional Force for Scene Re-Extraction"
---

# Tasks: Optional Force for Scene Re-Extraction

**Input**: Design documents from `/specs/012-scene-extract-optional-force/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/extract-endpoint.md, quickstart.md (all present)

**Tests**: Included. Not requested via TDD, but `research.md` D5 identified a real coverage gap — no existing test pins `_build_reextract_cmd`'s `force` parameter at either value — and `contracts/extract-endpoint.md` documents the exact contract this feature depends on staying correct. The new tests mirror this repo's existing `test_build_reextract_cmd_omits_batch_by_default` / `test_build_reextract_cmd_forwards_batch_when_resolved_selection_true` pair in `tests/test_editor_pipeline.py`.

**Organization**: Three user stories from spec.md (P1/P2/P3). Because research.md found the entire fix is one hardcoded value in one Vue function, all three stories touch the same function (`runExtract()`) in the same file — genuine cross-story parallelism is limited, but each story is still an independently shippable increment (P1 alone already fixes issue #323's core defect; P2 restores the old full-redo capability as an explicit opt-in; P3 adds before-run clarity).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- File paths below are relative to the repository root (this worktree, `.claude/worktrees/scene-extract-optional-force/`)

## Path Conventions

Existing web-app layout (per plan.md's Project Structure): `frontend/src/views/session/SessionDocEditor.vue` (Vue 3), `server/routers/scene_editor.py` (FastAPI, docstring-only touch), `tests/test_editor_pipeline.py` (pytest) at repository root. No new files or directories. `campaignlib/scenes.py` and `session_doc/scene_extract.py` are read-only references — they already implement the correct skip/force logic (research.md D1) and are not modified by this feature.

---

## Phase 1: Setup

**Purpose**: Project initialization and basic structure

No setup tasks required. This feature modifies one existing frontend file,
touches one docstring in one existing backend file, and adds test coverage
to one existing test file — no new dependencies, no new project scaffolding,
no new console script or route (`force` is already an accepted
`GET /api/editor/extract` query param).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Lock down the backend `force` contract every user story below depends on, before any frontend change is judged against it

- [X] T001 Add two regression tests to `tests/test_editor_pipeline.py`, placed immediately after the existing `test_build_reextract_cmd_omits_batch_by_default` (around line 334), mirroring that pair's shape: `test_build_reextract_cmd_omits_force_by_default` (calls `scene_editor._build_reextract_cmd(None, cfg)` with `force` left at its default and asserts `"--force" not in cmd`) and `test_build_reextract_cmd_forwards_force_when_requested` (calls `scene_editor._build_reextract_cmd(None, cfg, force=True)` and asserts `"--force" in cmd`). Both should pass immediately with no source change — they pin already-correct behavior (research.md D1/D5, contracts/extract-endpoint.md's side-effects table).

**Checkpoint**: The `force` contract both user stories below rely on is proven and pinned — safe to build the frontend on top of it.

---

## Phase 3: User Story 1 - Fill in missing scenes without redoing finished ones (Priority: P1) 🎯 MVP

**Goal**: The Re-Extract Quotes button defaults to skip-existing (resumable) behavior — only scenes missing an extraction file are regenerated (spec.md).

**Independent Test**: In a session with N scenes where N-2 already have extraction files, click "Re-Extract Quotes" (Force isn't added until Phase 4 — there is no way to do otherwise yet). Confirm exactly 2 scenes are generated and the other N-2 files and their reviewed markers are untouched (spec.md; quickstart.md Scenario 1).

### Implementation for User Story 1

- [X] T002 [US1] In `frontend/src/views/session/SessionDocEditor.vue`'s `runExtract()`, change the hardcoded SSE call on line 473 from `connectSSE('/api/editor/extract?force=1', { ... })` to `connectSSE('/api/editor/extract?force=0', { ... })`. The comment block immediately above it (lines 466-472) is about the `batch` param, not `force` — it stays accurate as-is and needs no edit. Depends on T001 (proves `force=0` already means skip-existing server-side).
- [X] T003 [P] [US1] Fix the now-inaccurate docstrings in `server/routers/scene_editor.py`: `_build_reextract_cmd`'s docstring (was: "The UI sets this when the user clicks the Re-Extract button — clicking it should mean 'do the work.'") and `api_extract`'s docstring (was: "the UI Re-Extract button always sets this") both become false the moment T002 lands. Replace both with wording stating force defaults to skip-existing and is only set when the GM explicitly enables it. Docstring-only change — `_build_reextract_cmd`'s actual logic (the conditional `cmd.append("--force")`) is untouched. Different file from T002, no code dependency between them — can run in parallel.
  - Unplanned but required: found a *second* stale claim in the same file (`api_extract`'s own docstring, line 1457: "the UI Re-Extract button always sets this") that research.md D1 didn't call out — fixed alongside the one T003 targeted, since both describe the same caller behavior T002 just changed.

**Checkpoint**: User Story 1 is fully functional and independently testable — this alone fixes issue #323's core defect and is shippable as the MVP.

---

## Phase 4: User Story 2 - Deliberately redo every scene (Priority: P2)

**Goal**: An explicit, visible, off-by-default Force control lets the GM opt back into today's full-redo behavior (spec.md).

**Independent Test**: In a session where every scene already has an extraction file, explicitly enable the Force control and click "Re-Extract Quotes". Confirm every scene is regenerated, each changed scene's prior content is snapshotted, and every reviewed marker is cleared (spec.md; quickstart.md Scenario 3).

### Implementation for User Story 2

- [X] T004 [US2] In `frontend/src/views/session/SessionDocEditor.vue`, add `const forceReextract = ref(false)` to the reactive state block, alongside the existing `const extracting = ref(false)` (line 204).
- [X] T005 [US2] In `runExtract()`, change the URL from T002's literal `?force=0` to interpolate the ref: `` connectSSE(`/api/editor/extract?force=${forceReextract.value ? 1 : 0}`, { ... }) ``. Depends on T002 (same line) and T004 (ref must exist).
- [X] T006 [US2] Add a Force checkbox to the template's Stage 2 `stage-group` span, immediately after the "Re-Extract Quotes" `<button>`, following the `replace-toggle` pattern already used in `frontend/src/views/prep/ConnectionGraph.vue:387-390`: a `<label class="force-toggle">` wrapping `<input type="checkbox" v-model="forceReextract" />` plus visible text ("Force (redo all)"), `:disabled` under the same condition as the button (`!configReady || enhancing || extracting || narrating || planning`). Added matching scoped `.force-toggle` CSS. Depends on T004 (ref must exist to bind).

**Checkpoint**: User Stories 1 AND 2 both work independently — the old full-redo capability is back, as an explicit opt-in rather than the only option.

---

## Phase 5: User Story 3 - Understand what a run will do before it runs (Priority: P3)

**Goal**: Before clicking "Re-Extract Quotes", the GM can tell from the Force control itself whether the run will skip existing scenes or overwrite everything (spec.md).

**Independent Test**: With Force toggled on, confirm the control communicates that the next run will overwrite every scene and clear reviewed markers, before the GM commits to running it (spec.md; quickstart.md Scenario 3 step 1).

### Implementation for User Story 3

- [X] T007 [US3] Add a `title` tooltip to the Force `<label>` added in T006, stating both states explicitly — mirrors `ConnectionGraph.vue:387`'s `title="If unchecked, results merge into existing connections.json"`. Depends on T006 (the label must exist to annotate).
  - Folded into T006's edit: the `<label>` and its `title` attribute were added together in one template change, since they're the same element — no separate second edit was needed.

**Checkpoint**: All three user stories are independently functional — feature complete per spec.md.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T008 [P] (partial — see note) Manually run all four scenarios in `quickstart.md` against a `startup`-served dev instance (no automated frontend test harness exists in this repo — no `*.test.*`/`*.spec.*` files, no `test` script in `frontend/package.json` — per `CLAUDE.md`'s UI-change rule) and record the outcome.
  - **Not done**: an actual browser click-through of Scenarios 1-3 — no browser-automation tool is available in this environment (same limitation `011-extract-max-tokens/tasks.md` T011 hit), and Scenario 1/3 both require a real session with `ANTHROPIC_API_KEY` calls, which would spend real API budget for no additional confidence beyond what T001's unit tests already prove about the exact command construction.
  - **Done instead**: `npm run build` (`vue-tsc -b && vite build`) — clean typecheck and production build, confirming the new `forceReextract` ref, its template bindings, and the `.force-toggle` scoped CSS are all syntactically and type-correct. Scenario 4 (the raw-`curl`, no-browser-needed sanity check) is covered by T001/T009 at the unit level: `_build_reextract_cmd`'s behavior at both `force` values is what Scenario 4 is actually probing.
- [X] T009 [P] Run `python -m pytest tests/test_editor_pipeline.py` and the full suite (`python -m pytest tests/`) to confirm T001's new tests pass and nothing else regressed.
  - `tests/test_editor_pipeline.py`: all pass, including the two new T001 tests.
  - Full suite: 3687 passed, 174 skipped, 3 failed — the 3 failures (`test_gate2_rpg_retrieval`, `test_cli_parallel_fully_cached`, `test_search_hierarchical_on_fresh_palace_falls_back`) are the same pre-existing, environment-dependent failures (RLM index / mempalace live service / subprocess env) already documented in `011-extract-max-tokens/tasks.md` T010 as present on `main` — unrelated to this feature, which touches none of those subsystems.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No tasks.
- **Foundational (Phase 2)**: No dependencies beyond Setup — BLOCKS Phase 3 (T002 depends on T001 having proven the contract).
- **User Story 1 (Phase 3)**: Depends on Phase 2 (T001).
- **User Story 2 (Phase 4)**: Depends on Phase 3 (T002 — same line of code, T005 builds directly on it).
- **User Story 3 (Phase 5)**: Depends on Phase 4 (T006 — the label T007 annotates).
- **Polish (Phase 6)**: Depends on Phases 3-5 all being complete.

Unlike the template's default assumption, these user stories are **not**
independently parallelizable across different developers — T002 → T005 →
T006 → T007 form a single chain of edits to the same function and its
immediately surrounding template in one file. Priority order (P1 → P2 → P3)
is both the dependency order and the recommended execution order. T003 is
the one genuine exception (different file, no code dependency).

### Within Phase 2

- T001 has no dependencies — can start immediately.

### Within Phase 3

- T001 → T002 (T002's `force=0` default is only correct because T001 already proved the backend treats it as skip-existing).
- T002 → T003 (T003's docstring fix describes the state T002 creates; no code dependency, but sequencing keeps the docstring accurate to what actually shipped).

### Within Phase 4

- T002 → T005 (T005 edits the exact line T002 introduced).
- T004 → T005 (T005 references the ref T004 declares).
- T004 → T006 (T006 binds `v-model="forceReextract"`, which needs T004's ref to exist).
- T005 and T006 touch different regions of the same file (script block vs. template) and could be done in either order once T004 lands, but both must land before Phase 5.

### Within Phase 5

- T006 → T007 (T007 adds a `title` attribute to the element T006 creates).

### Parallel Opportunities

- T002 and T003 (Phase 3) — different files, no code dependency.
- T008 and T009 (Phase 6) — independent activities (manual browser QA vs. automated test run).
- No other parallel pairs: everything else in Phases 4-5 is a dependency chain within the same file.

---

## Parallel Example: Phase 3 and Phase 6

```bash
# Phase 3, run together:
Task: "Flip runExtract()'s hardcoded force=1 to force=0 in SessionDocEditor.vue"
Task: "Fix the now-inaccurate _build_reextract_cmd docstring in scene_editor.py"

# Phase 6, run together:
Task: "Manually validate quickstart.md's four scenarios against a running dev server"
Task: "Run python -m pytest tests/ to confirm no regressions"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 2: Foundational (T001) — pins the contract.
2. Complete Phase 3: User Story 1 (T002, T003) — one line changed, one stale docstring fixed.
3. **STOP and VALIDATE**: quickstart.md Scenario 1 (and 2) — confirms exactly the missing scenes regenerate and reviewed scenes are untouched. This alone closes issue #323's stated defect and is deployable on its own.

### Incremental Delivery

1. Foundational (T001) → contract proven.
2. User Story 1 (T002-T003) → default is safe → deploy/demo (MVP, fixes #323).
3. User Story 2 (T004-T006) → explicit Force control restores full-redo → deploy/demo.
4. User Story 3 (T007) → before-run clarity via tooltip → deploy/demo.
5. Polish (T008-T009) → manual + automated verification → ship.

### Notes

- Nearly every task after T001 edits the same frontend file in a strict
  dependency chain — expected for a fix this narrow (research.md found the
  entire defect was one hardcoded query value), not a sign the breakdown is
  wrong. T003 is the one real parallel opportunity, since it's a docstring
  fix in a different, untouched-by-logic backend file.
- Commit after each phase (or as one small PR — the whole feature is a
  handful of short, largely sequential edits to one file plus a docstring
  and two test functions; this repo has no stated convention requiring one
  commit per task).
- T003 exists because leaving `_build_reextract_cmd`'s docstring as-is after
  T002 would actively mislead the next person to read it about when force
  actually gets set — accuracy here matters per this repo's own documented
  scar (`CLAUDE.md`'s "campaignlib.py is the API surface" section holds
  every public function to a docstring that's actually true).
