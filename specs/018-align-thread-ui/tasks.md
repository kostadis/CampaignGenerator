---

description: "Dependency-ordered implementation tasks for Thread UI consistency and overflow access"
---

# Tasks: Thread UI Consistency and Overflow Access

**Input**: Approved design documents from `specs/018-align-thread-ui/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`,
`contracts/ui.md`, and `quickstart.md`

**Tests**: Required by the approved plan and UI contract. Source-contract tests
must be written before the corresponding Vue changes. Rendered-browser checks
remain explicit GM checkpoints because the repository has no component or
browser-test harness.

**Organization**: Tasks are grouped by user story. Edits are intentionally
serialized because every story touches `frontend/src/views/grounding/Threads.vue`
and/or `tests/test_threads_ui_style.py`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel after its stated prerequisite because it does
  not edit the same files as the paired task.
- **[Story]**: Maps the task to User Story 1, 2, or 3.
- Every task names concrete repository-relative paths.

## Phase 1: Setup (Baseline)

**Purpose**: Prove the current behavioral guards and frontend build state
before changing the Threads view.

- [X] T001 Run the pre-change baseline with `python -m pytest tests/test_threads_ui_absences.py -q` and `npm --prefix frontend run build`, attributing any existing failure before editing `frontend/src/views/grounding/Threads.vue`

---

## Phase 2: Foundational (Shared Test Infrastructure)

**Purpose**: Create the source-contract harness used by all three user stories.

**⚠️ CRITICAL**: Complete this phase before adding any story-specific test or
implementation.

- [X] T002 Create shared helpers in `tests/test_threads_ui_style.py` to read `frontend/src/views/grounding/Threads.vue`, isolate its template and scoped style, and collect the custom properties defined by `frontend/src/style.css`

**Checkpoint**: The test harness can express page-root, template, palette, and
forbidden-pattern assertions without changing application code.

---

## Phase 3: User Story 1 - Reach all oversized page content (Priority: P1) 🎯 MVP

**Goal**: Give the Threads route one bounded page-level scroll owner so every
wide item and action is reachable at 100% zoom, while content that fits does
not show a forced horizontal scrollbar.

**Independent Test**: Load wide Threads content at 100% zoom, scroll to and use
a control beyond the initial right edge, then widen the viewport until content
fits and confirm the unnecessary horizontal control disappears.

### Tests for User Story 1

> Write T003 first and confirm its new assertions fail against the current
> `.threads { max-width: 60rem; }` implementation before T004.

- [X] T003 [US1] Add failing page-scroll contract tests in `tests/test_threads_ui_style.py` requiring the `.threads` root in `frontend/src/views/grounding/Threads.vue` to have `height: 100%`, `box-sizing: border-box`, and two-axis `overflow: auto` rather than forced `overflow-x: scroll`

### Implementation for User Story 1

- [X] T004 [US1] Implement the bounded Threads page scroll owner and established grounding-page padding/maximum width in `frontend/src/views/grounding/Threads.vue`, leaving `frontend/src/App.vue` and `frontend/src/style.css` unchanged
- [X] T005 [P] [US1] Run `python -m pytest tests/test_threads_ui_style.py tests/test_threads_ui_absences.py -q` against `tests/test_threads_ui_style.py` and `frontend/src/views/grounding/Threads.vue` after T004
- [X] T006 [P] [US1] Obtain explicit GM browser acceptance for the static overflow and fit cases in `specs/018-align-thread-ui/quickstart.md` section 4 against `frontend/src/views/grounding/Threads.vue`; do not infer acceptance from source tests

**Checkpoint**: User Story 1 is independently usable: wide content and controls
are reachable, simultaneous vertical navigation remains available, and fitting
content does not receive a permanently forced horizontal bar.

---

## Phase 4: User Story 2 - Experience one consistent application design (Priority: P2)

**Goal**: Make every Threads state use the same page, typography, control,
surface, border, and semantic-color conventions as established grounding
pages, without changing the meaning or behavior of thread states.

**Independent Test**: Compare empty, loading, error, populated, expanded-form,
and maintenance states with State Projection and at least one other established
page; confirm shared elements match and each semantic status remains named and
distinguishable.

### Tests for User Story 2

> Write T007 first and confirm the new assertions fail on the current undefined
> variables, light fallbacks, missing loading presentation, and legacy control
> classes before T008/T009.

- [X] T007 [US2] Add failing visual-contract tests in `tests/test_threads_ui_style.py` that require every Threads CSS variable to be defined in `frontend/src/style.css`, reject `--muted`, `--border`, `--chip`, `--panel` and the legacy light fallback palette, and require standard header/control classes, a rendered `loading` state, and text-bearing semantic status class bindings in `frontend/src/views/grounding/Threads.vue`

### Implementation for User Story 2

- [X] T008 [US2] Align the Threads template header, loading/empty/error presentations, shared button classes, and proposal/thread semantic status bindings with the approved UI contract in `frontend/src/views/grounding/Threads.vue`, preserving all existing request handlers, confirmations, labels, and verbatim evidence
- [X] T009 [US2] Replace the remaining legacy scoped styles in `frontend/src/views/grounding/Threads.vue` with the page spacing, typography, inputs/selects, panels, borders, focus/hover/disabled states, code/output treatment, and standard Catppuccin semantic tokens defined by `frontend/src/style.css` and exemplified by `frontend/src/views/grounding/ProjectionSections.vue`
- [X] T010 [P] [US2] Run `python -m pytest tests/test_threads_ui_style.py tests/test_threads_ui_absences.py -q` and `npm --prefix frontend run build` after T009, validating `tests/test_threads_ui_style.py` and `frontend/src/views/grounding/Threads.vue`
- [X] T011 [P] [US2] Obtain explicit GM visual acceptance for `specs/018-align-thread-ui/quickstart.md` sections 3 and 6 across `frontend/src/views/grounding/Threads.vue`, `frontend/src/views/grounding/ProjectionSections.vue`, and one additional established page; do not infer acceptance from token assertions

**Checkpoint**: User Story 2 is independently reviewable in every named UI
state, semantic meaning is not color-only, and non-Threads pages remain
unchanged.

---

## Phase 5: User Story 3 - Keep access after content and window changes (Priority: P3)

**Goal**: Keep the Threads scroll owner correctly bounded as content expands or
collapses and the viewport resizes, using browser-native layout rather than
JavaScript width state.

**Independent Test**: Begin with fitting content, reveal a wide form/evidence
value without reloading, resize narrower and wider while horizontally scrolled,
and confirm the scroll range appears, updates, and disappears with layout while
far-right controls remain usable.

### Tests for User Story 3

> Write T012 first. After User Story 1 it must still fail on the final flex
> containment assertions, then pass only after T013.

- [X] T012 [US3] Add failing dynamic-layout contract tests in `tests/test_threads_ui_style.py` requiring `width: 100%` and `min-width: 0` on the `.threads` root and forbidding `ResizeObserver`, `MutationObserver`, resize listeners, or persisted width/scroll state in `frontend/src/views/grounding/Threads.vue`

### Implementation for User Story 3

- [X] T013 [US3] Add final flex containment for dynamic content and viewport resizing in `frontend/src/views/grounding/Threads.vue` while retaining one browser-native `overflow: auto` page owner and adding no watcher, observer, timer, or scroll persistence
- [X] T014 [P] [US3] Run `python -m pytest tests/test_threads_ui_style.py tests/test_threads_ui_absences.py -q` and `npm --prefix frontend run build` after T013, validating `tests/test_threads_ui_style.py` and `frontend/src/views/grounding/Threads.vue`
- [X] T015 [P] [US3] Obtain explicit GM browser acceptance for dynamic expansion, collapse, resize, simultaneous two-axis overflow, and a far-right workflow action in `specs/018-align-thread-ui/quickstart.md` section 5 against `frontend/src/views/grounding/Threads.vue`; do not infer acceptance from CSS structure

**Checkpoint**: All three stories work independently, and dynamic access is a
browser-derived presentation fact rather than new application state.

---

## Phase 6: Polish & Cross-Cutting Validation

**Purpose**: Run the complete automated regression gates after all desired
stories and preserve the approved one-view implementation boundary.

- [ ] T016 [P] Run the full Python regression suite with `python -m pytest tests/ -q`, including `tests/test_threads_ui_absences.py` and `tests/test_threads_ui_style.py`
- [X] T017 [P] Run the final production frontend validation with `npm --prefix frontend run build` for `frontend/src/views/grounding/Threads.vue` and verify `git diff -- frontend/src/App.vue frontend/src/style.css frontend/src/views/grounding/ProjectionSections.vue` is empty

---

## Dependencies & Execution Order

### Dependency Graph

```text
T001 baseline
  └─> T002 shared test harness
        └─> US1: T003 -> T004 -> {T005 || T006}
              └─> US2: T007 -> T008 -> T009 -> {T010 || T011}
                    └─> US3: T012 -> T013 -> {T014 || T015}
                          └─> Polish: {T016 || T017}
```

`||` means the paired read-only validation tasks can run in parallel after the
preceding implementation task has completed.

### Phase Dependencies

- **Setup (Phase 1)**: No dependency; establishes the pre-change baseline.
- **Foundational (Phase 2)**: Depends on T001 and blocks all story tests.
- **User Story 1 (Phase 3)**: Depends on T002; delivers the MVP scroll owner.
- **User Story 2 (Phase 4)**: Logically presentation-independent of US1, but
  follows it because both its tests and implementation edit the same two files.
- **User Story 3 (Phase 5)**: Depends on US1's scroll owner and follows US2 to
  avoid concurrent edits to `Threads.vue` and the shared test file.
- **Polish (Phase 6)**: Depends on every story selected for delivery.

### User Story Dependencies

- **US1 (P1)**: No dependency on another story; independently testable after
  the shared test harness.
- **US2 (P2)**: No semantic dependency on US1, but task IDs serialize the
  shared-file edits. Its browser acceptance does not rely on overflow cases.
- **US3 (P3)**: Extends US1's page scroll owner with final flex containment and
  dynamic/resize validation; it does not depend on US2's visual choices.

### Within Each User Story

- Add the story's source-contract tests first and observe the specified failure.
- Make Vue template changes before the scoped-style changes that depend on the
  new classes.
- Never edit `Threads.vue` and `test_threads_ui_style.py` concurrently.
- Run automated checks and seek explicit GM browser acceptance only after the
  story implementation is complete.
- A timeout, silence, or default selection is not GM acceptance; leave T006,
  T011, or T015 unchecked until an explicit response is received.

### Parallel Opportunities

- After T004: T005 (automated source tests) and T006 (US1 browser acceptance).
- After T009: T010 (automated/build validation) and T011 (US2 visual review).
- After T013: T014 (automated/build validation) and T015 (US3 browser review).
- After all stories: T016 (full Python suite) and T017 (frontend build/scope
  check).
- No implementation edits are marked parallel because the feature deliberately
  has one Vue owner and one shared source-contract test file.

---

## Parallel Example: User Story 1

```text
# After T004 completes:
Task T005: Run the focused Python source-contract suites.
Task T006: GM validates static overflow and fit behavior in a browser.
```

## Parallel Example: User Story 2

```text
# After T009 completes:
Task T010: Run focused Python tests and the frontend build.
Task T011: GM compares all Threads states with two established pages.
```

## Parallel Example: User Story 3

```text
# After T013 completes:
Task T014: Run focused Python tests and the frontend build.
Task T015: GM validates expansion, collapse, resize, two-axis scroll, and action use.
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete T001–T002.
2. Write and fail T003.
3. Implement T004.
4. Run T005 and obtain explicit T006 browser acceptance.
5. Stop: the clipping defect is independently fixed and reviewed before visual
   polish or dynamic-containment work continues.

### Incremental Delivery

1. **Foundation**: baseline plus reusable source-contract helpers.
2. **US1**: static reachability at normal zoom — MVP.
3. **US2**: application-wide visual consistency for every Threads state.
4. **US3**: dynamic content and resize containment.
5. **Polish**: full repository tests, production build, and scope verification.

Each increment has its own source-contract and human browser checkpoint. A
passing source test never substitutes for the rendered behavior judgment.

### Parallel Team Strategy

The implementation edits are intentionally single-owner because all stories
converge on the same Vue and test files. Parallelize only the read-only
automated and browser validation pairs listed above; otherwise follow task ID
order to avoid conflicting or silently overwritten changes.

---

## Notes

- Tests T003, T007, and T012 must be observed failing before their respective
  implementation tasks begin.
- T006, T011, and T015 require explicit GM confirmation and must never be
  auto-checked from elapsed time, source inspection, or a recommended default.
- `frontend/src/App.vue`, `frontend/src/style.css`, and
  `frontend/src/views/grounding/ProjectionSections.vue` are references, not
  implementation targets.
- No server, API, CLI, data-model, migration, dependency, or persistent-state
  task belongs in this feature.
- Stop at any story checkpoint to validate the increment independently.
