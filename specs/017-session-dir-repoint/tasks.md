---

description: "Task list for 017-session-dir-repoint"
---

# Tasks: Session Directory Re-Points Editor Paths

**Input**: Design documents from `/specs/017-session-dir-repoint/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/editor-config.md](./contracts/editor-config.md)

**Tests**: **INCLUDED.** Not the template default — required by this feature's
own gates. `plan.md`'s phase table makes "new pytest cases green; no existing
test modified to pass" the hand-off gate for Phases 2–3, and every user story
in `spec.md` states an Independent Test. Backend work is therefore test-first.
Frontend work is **not**: this repo has no frontend test runner
(`frontend/package.json` is `dev`/`build`/`preview` only), so frontend tasks
are gated on `npm run build` (`vue-tsc -b`) plus the named `quickstart.md`
section. Adding vitest is out of scope.

**Organization**: Grouped by user story so each is independently implementable
and testable.

**Execution model** (research D8): Opus orchestrates and calls the phase
gates; Sonnet implements individual tasks. Every task below therefore names
its file, its anchor, and its own acceptance check — an implementer needs no
orchestration context to execute one.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel — different files, no dependency on an incomplete task
- **[Story]**: US1–US4, mapping to the user stories in `spec.md`
- Exact file paths are in every description

## Path Conventions

Web app, per `plan.md`'s Structure Decision: backend in `server/`, frontend in
`frontend/src/`, backend tests in `tests/`. No new directory is created by this
feature.

## Standing constraints (apply to EVERY task)

- **C-A**: `server/platform_config_service.py` MUST NOT be modified.
  `resolve_path` / `relativize_path` are the seam and they are already correct.
  `git diff server/platform_config_service.py` must be empty at every gate.
- **C-B**: No `_build_*_cmd()` in `server/routers/scene_editor.py` may change.
  Run commands are built server-side from `ResolvedEditorConfig.paths` and stay
  that way. No run route gains a path parameter.
- **C-C**: No relativization logic may appear in `frontend/`.
  `frontend/src/utils/paths.ts` resolves for display only and MUST NOT gain an
  inverse (contract C-15).
- **C-D**: No existing test may be edited to make new code pass. If an existing
  test fails, the new code is wrong.
  - **One recorded exception, T009**: `TestGetEditorConfig::test_returns_grouped_shape`
    in `tests/test_editor_service_integration.py` asserts an **exhaustive** key set
    over the wire shape — a deliberate contract lock. Adding `paths_stored` and
    `warnings` is an intentional additive contract change (contract C-01..C-04), so
    the lock was grown to match and a comment records why. This is the only existing
    lock is paired with an identical one in `tests/test_editor_profiles_routes.py::
    test_activate_profile_mirrors_knobs_into_resolved_config`, since profile-activate
    shares `_serialize_resolved`. **Both had to grow in the same change** — which is
    exactly what those two locks exist to prove: the single producer has not drifted.
    These are the only two existing tests touched by this feature; neither was
    relaxed, and no assertion about an existing key was weakened.
- **C-E**: A read must never write. No task may add a `_save` call to any read
  path (FR-007).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Isolated workspace and a recorded green baseline to diff against.

- [X] T001 Create the implementation worktree off `main` at `.claude/worktrees/017-session-dir-repoint` via `git worktree add .claude/worktrees/017-session-dir-repoint -b 017-session-dir-repoint main`; all subsequent tasks run inside it. **Accept**: `git -C .claude/worktrees/017-session-dir-repoint status` reports branch `017-session-dir-repoint` and a clean tree.
- [X] T002 Record the pytest baseline by running `python -m pytest -q` from the worktree root and writing the pass/fail counts into `specs/017-session-dir-repoint/tasks.md` under Notes. **Accept**: suite is green before any change; the number is written down so a later regression is unambiguous.
- [X] T003 [P] Record the frontend baseline by running `npm run build` in `frontend/`. **Accept**: `vue-tsc -b` reports no errors and `frontend/dist/` is produced.
- [X] T004 [P] Back up the quickstart fixture campaign: copy `~/out-of-the-abyss/out-of-the-abyss/config/session_doc.yaml` and `~/out-of-the-abyss/out-of-the-abyss/config/platform.yaml` to `.bak` siblings. **Accept**: both `.bak` files exist; §3 of `quickstart.md` deliberately corrupts the originals.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The classification rule and the additive wire keys. Every user
story depends on these.

**⚠️ CRITICAL**: No user story work begins until this phase's checkpoint passes.

**Scope boundary**: this phase implements the three *benign* classification
states only — relative, in-session absolute, deliberate override. The
**stale-pin** state belongs to User Story 3 (T021) and must NOT be implemented
here; a stale pin must still behave as a deliberate override at the end of this
phase, so US3 has something to change.

- [X] T005 [P] Write failing tests for benign classification and the resolve invariant in `tests/test_session_editor_config_service.py`: for a healthy config, `paths_stored` equals the stored relative names; for every field, `paths[k] == resolve(paths_stored[k])` (data-model.md invariant); campaign-scoped fields are unaffected (FR-013). **Accept**: tests fail with `AttributeError`/`KeyError` on `paths_stored`, proving they exercise new surface.
- [X] T006 [P] Write a failing wire-shape test in `tests/test_editor_service_integration.py`: `GET /api/editor/config` returns `paths_stored` (same keys as `paths`) and `warnings` (a list, empty for a healthy config) — contract C-01, C-02, C-04. **Accept**: test fails on the missing keys.
- [X] T007 Implement `_classify_session_path(value, session_dir, campaign_dir)` in `server/session_editor_config_service.py`, below `_CAMPAIGN_PATH_FIELDS` (currently line 49-51). Returns the state and the stored form per the data-model.md table, handling only `relative` / `in_session_absolute` / `deliberate_override`; compare on `Path.resolve()` with `is_relative_to`, matching `relativize_path`'s treatment so a trailing slash or `~` is not a difference. When `session_dir` is unset, return the value untouched (preserves the existing defensive rule). **Accept**: pure function, no I/O beyond `Path` operations, no `_save` (C-E).
- [X] T008 Extend `ResolvedEditorConfig` in `server/session_editor_config_service.py:126` with `paths_stored: EditorPaths` and `warnings: list[str] = field(default_factory=list)`, then populate both in `resolved_editor_config()` (line 366) by running `_classify_session_path` over `_SESSION_PATH_FIELDS` and the existing campaign relativization over `_CAMPAIGN_PATH_FIELDS`. `paths` must be resolved **from** `paths_stored`, not independently. `get_config()` stays untouched and keeps returning the raw stored document. **Accept**: T005 passes; `get_config()` behaviour is byte-identical to before.
- [X] T009 Add `"paths_stored"` and `"warnings"` to `_serialize_resolved` in `server/routers/scene_editor.py:106`, keeping it the single producer for both `GET /api/editor/config` and the profile-activate response so the two cannot drift. **Accept**: T006 passes; no other key changes name, type, or meaning (contract: additive only).

**Checkpoint**: `python -m pytest -q` green. `git diff server/platform_config_service.py` empty (C-A). `git diff` shows no change inside any `_build_*_cmd()` (C-B). Foundation ready.

---

## Phase 3: User Story 1 - Switch sessions and start work immediately (Priority: P1) 🎯 MVP

**Goal**: Changing the session directory on Session Config re-points every
session-scoped path the Session Doc Editor shows, with no reload and no restart.

**Independent Test**: With the session directory at `summaries/20260811`, change
it to `summaries/20260825`, save, and open the Session Doc Editor without
reloading — every session-scoped path resolves under `20260825`
(`quickstart.md` §1).

### Tests for User Story 1

- [X] T010 [US1] Write a failing end-to-end test in `tests/test_editor_service_integration.py`: with relative stored paths, `PUT /api/config/runtime {"session_dir": S2}` followed by `GET /api/editor/config` returns every session-scoped path under `S2` and every campaign-scoped path unchanged (FR-001, FR-013, spec US1 scenarios 1 and 4). **Accept**: fails before T011–T013, passes after.

### Implementation for User Story 1

- [X] T011 [US1] Change `loadConfigFields()` in `frontend/src/views/session/SessionDocEditor.vue:63-88` to hydrate the seven path refs from `ec?.paths_stored` instead of `ec?.paths`, keeping the existing per-field fallbacks (`'session-summary.md'`, `'scene_extractions'`, `'narration'`). Leave `outputDir`'s `config.resolved?.runtime?.session_dir` fallback in place. **Accept**: `npm run build` clean; the drawer shows relative names with `PathField`'s `→ /abs/path` hint now rendering (it never has).
- [X] T012 [US1] Add a watcher on `config.editorConfig` in `frontend/src/views/session/SessionDocEditor.vue` (near the `onMounted` block at line 738) that re-runs `loadConfigFields()` when the slice changes, guarded so the re-hydration does not re-trigger the debounced auto-save — reuse the existing `configHydrated` flag pattern (line 741) rather than inventing a second guard. **Accept**: `npm run build` clean; switching sessions in another tab and returning shows the new paths without a reload.
- [X] T013 [US1] In `frontend/src/stores/config.ts:197`, make `updateRuntime()` additionally `await refreshEditor()` when its partial contains a `session_dir` key — and only then, so the sidebar's backend/model/batch writes do not pay a wasted round trip. `refreshEditor()` already exists at line 177 with no caller outside the store. **Accept**: `npm run build` clean; `quickstart.md` §1 passes by hand.

**Checkpoint**: User Story 1 fully functional — the reported defect is fixed. MVP deliverable.

**Implementation notes (US1)**

- **T010 passed on first run** — recorded honestly rather than presented as red-green.
  The service already re-tracked (that is what `test_session_editor_config_service.py`
  proved before this feature), so the route-level assertion was green before any
  frontend change. It still earns its place: it also pins `paths_stored`, so a future
  regression that re-points `paths` but not the value the editor binds fails here.
- **T012 deviated from the task text, deliberately.** The task said watch
  `config.editorConfig`. Implemented instead as a watch on
  `config.editorConfig?.session_dir`, because that ref is *replaced* after every
  `updateEditor()` — watching its identity would re-hydrate mid-typing and clobber
  keystrokes entered since the 350 ms debounce fired. `session_dir` changes exactly
  when the session changes, which is the real trigger, and it is still read off the
  slice this component binds (not `resolved.runtime.session_dir`), so the
  one-derivation intent of FR-010 is preserved.
- **T012 also clears a debounce armed before the switch.** Not in the task text, but
  required by FR-003: a timer scheduled pre-switch holds pre-switch values, and
  letting it fire would write the old session's paths under the new `session_dir` —
  reintroducing the exact bug through the back door.
- **T011 deliberately has no `?? ec?.paths` fallback.** A dual-location back-compat
  probe is what Principle XIII forbids; the server always sends `paths_stored`.

---

## Phase 4: User Story 2 - A session switch never pins the old session into stored config (Priority: P1)

**Goal**: No write, in any order, can leave the previous session's location in
`session_doc.yaml`.

**Independent Test**: Change the session directory, then change any drawer knob
so the config auto-saves; no session-scoped path in `session_doc.yaml` names the
previous session (`quickstart.md` §2).

**Depends on**: US1 (T011) — the editor must be holding stored values before the
write side can be made safe. Same files, different lines.

### Tests for User Story 2

- [X] T014 [US2] Write a failing round-trip test in `tests/test_editor_service_integration.py`: after `PUT /api/config/runtime` moves `session_dir` from S1 to S2, a subsequent `PUT /api/editor/config` carrying the values from `paths_stored` leaves `session_doc.yaml` with no path containing S1 (FR-002, FR-003, contract C-11). **Accept**: fails if the payload carries resolved absolutes.
- [X] T015 [US2] Extend `tests/test_editor_service_integration.py` with the ordering case: writing the editor paths and `runtime.session_dir` in either order yields the same stored result, interpreted against the new session directory (spec US2 scenario 2). Also assert the three-switches-in-a-row case (US2 scenario 3) leaves only the third session named. **Accept**: both orders converge; sequential with T014 (same file).

### Implementation for User Story 2

- [X] T016 [US2] In `buildEditorConfigPayload()` at `frontend/src/views/session/SessionDocEditor.vue:107-118`, stop calling `resolvePath()` on `session_recap`, `session_summary`, `scene_extractions_dir`, `narration_dir`, `party`, `voice_dir`, `examples_dir` — send the ref values as held (contract C-09). Leave `genre_file`'s `resolvePathWithBase(..., 'campaign')` decision to T017's review; do not delete `resolvePath` from `frontend/src/utils/paths.ts`, which `voice_file` (line 688) and `resolvePathList` still use. **Accept**: `npm run build` clean; T014 passes.
- [X] T017 [US2] In `saveConfig()` at `frontend/src/views/session/SessionConfig.vue:183-193`, move the `config.updateRuntime({ session_dir })` call **before** `persistTypedSections()`, so path fields written in the same save are relativized against the new session directory (FR-002 scenario 2, contract C-13). Update the comment at line 187-189, which currently explains the old order. **Accept**: `npm run build` clean; T015 passes; `quickstart.md` §2 passes by hand.

**Checkpoint**: User Stories 1 and 2 both work. The bug can no longer create new damage.

**Implementation notes (US2)**

- **T014/T015 passed on first run**, because they simulate the *fixed* client. The
  server was always capable of this; what changed is what the client echoes. With no
  frontend test runner in this repo, the real guarantee for FR-003 is T016/T017 plus
  `quickstart.md` §2 — the pytest suite does **not** prove US2 end to end, and should
  not be read as if it does.
- **Added a characterization test** (`test_echoing_the_resolved_paths_is_what_pinned_
  the_old_session`) that deliberately asserts the BAD outcome. It is the closest thing
  to a guard on the client obligation in contract C-09: if someone later 'simplifies'
  the client back to sending `paths`, that test documents exactly what they will get.
- **T017 grew beyond its task text, and had to.** Fixing only the write order would
  not have made FR-003 hold: `SessionConfig.vue` has the *same* round-trip hazard —
  `loadFromConfig()` read the resolved absolutes and `persistTypedSections()` wrote
  them straight back. `deriveAll()` masks it only when discovery finds a file, so on
  a session with no recap the old absolute survived and was written under the new
  `session_dir`. The two session-scoped fields there now bind `paths_stored`;
  campaign-scoped ones deliberately do not (they cannot pin a session, and their
  `PathField`s are declared `absolute`).
- **T016 retired a latent base mismatch** found while editing: `party`, `voice_dir`
  and `examples_dir` are campaign-scoped but were passed through `resolvePath()`,
  which resolves against `session_dir`. It never bit because Session Config seeded
  them absolute, but a relative `docs/party.md` would have been sent as
  `<session>/docs/party.md` and stored as `summaries/<date>/docs/party.md`.

**Out of scope, found while implementing — `narrate.context`**

`narrate.context` is a LIST of paths under `narrate`, not a field of `EditorPaths`.
It is resolved to absolute client-side (`resolvePathList`) and the server never
relativizes it, so it is a genuine second session-pinning vector: context entries
pointing into a session directory stay pinned across a switch. It is **deliberately
not fixed here** — changing its storage semantics from absolute to relative is a
schema-meaning change that needs its own migration ruling under Principle XIII, and
the spec scopes this feature to the editor's path *fields*. Worth its own issue.

---

## Phase 5: User Story 3 - An already-damaged campaign heals itself (Priority: P2)

**Goal**: A session-scoped path pinned to a *sibling* session directory is
re-pointed on read and announced; a genuine out-of-tree override is preserved.

**Independent Test**: Pin a stored path to a sibling session directory, set a
different current session, and read the config — the path resolves under the
current session, the correction is announced, and an out-of-tree override is
untouched (`quickstart.md` §3).

**Constitutional note**: this is the story `plan.md`'s Constitution Check
justifies against Principle XIII. T020 and T021 are what hold that
justification up — do not weaken either.

### Tests for User Story 3

- [X] T018 [US3] Write failing stale-pin tests in `tests/test_session_editor_config_service.py`: a stored absolute under `parent(session_dir)` but not under `session_dir` is re-pointed onto the current session (FR-004), and a **nested** value (`…/20260811/narration/pass5`) re-points to `narration/pass5`, not `pass5` (FR-008, data-model.md). **Accept**: fails while the stale-pin branch is unimplemented.
- [X] T019 [US3] Extend `tests/test_session_editor_config_service.py` with the preservation and announcement cases: an absolute outside `parent(session_dir)` is returned verbatim with **no** warning (FR-005); a re-point emits exactly one warning naming the field, the stored value, and the value now in use (FR-006). **Accept**: sequential with T018 (same file).
- [X] T020 [US3] Extend `tests/test_session_editor_config_service.py` with the two constitutional guards: (a) **no write on read** — `session_doc.yaml` mtime and bytes are unchanged across two `resolved_editor_config()` calls on a damaged config (FR-007, C-E); (b) **idempotence** — the second read returns identical `paths_stored` and an empty `warnings` is produced for an already-healthy config (FR-012). **Accept**: sequential with T019; these two tests are the Principle XIII justification in executable form.

### Implementation for User Story 3

- [X] T021 [US3] Add the `stale_pin` branch to `_classify_session_path()` in `server/session_editor_config_service.py` (from T007): absolute, not under `session_dir`, but under `parent(session_dir)` → re-point, preserving the value's path relative to *its own* session directory. Return the warning payload alongside; do not write. **Accept**: T018–T020 pass; `resolved_editor_config()` still contains no `_save` call.
- [X] T022 [US3] Echo each warning to stderr from `server/session_editor_config_service.py`, mirroring the announced-normalisation pattern of `EditorPaths._drop_retired_fields` in `server/session_editor_config_shared.py`. **Accept**: message names the field and both values; the server still boots on a damaged config (a stale pin must never be fatal).
- [X] T023 [US3] Render `editorConfig.warnings` in `frontend/src/views/session/SessionDocEditor.vue`, mirroring the existing migration banner at `frontend/src/views/Settings.vue:43-46` (`.migration-banner`, `v-for` over the list). Persistent, not a toast — the condition lasts until the next write. **Accept**: `npm run build` clean; `quickstart.md` §3 shows the banner.

**Checkpoint**: All three behavioural stories independently functional.

**Implementation notes (US3)**

- **Two guards were added to the stale-pin branch that the task text did not call for,
  and both are load-bearing.** (a) `base.parent != base`: if `session_dir` were a
  filesystem root, every absolute path on the machine would sit under its parent and
  the entire config would be 'healed' into nonsense. (b) containment in `campaign_dir`:
  FR-004 says *within the current campaign*, and a `session_dir` set outside the
  campaign has no sibling tree to reason about. Both err toward treating a value as a
  deliberate override — mistaking an override for damage silently moves a GM's
  deliberate pointer, which is the worse failure.
- **The `len(parts) == 1` case** — the stored value names a sibling session directory
  with nothing under it — heals to *unset*. The realistic instance is `output_dir`,
  which often just names the session dir, and where unset already means 'the session
  directory'. The warning text says 'cleared' rather than 're-pointed to None'.
- **T022 was already satisfied by T008b**: the stderr echo was written alongside the
  warning at that point, but was unreachable until T021 made `STALE_PIN` returnable.

---

## Phase 6: User Story 4 - The GM can see which re-pointed paths do not exist yet (Priority: P2)

**Goal**: A re-pointed path with no file behind it is visibly marked.

**Independent Test**: Switch to a session directory containing no GM-assist
recap and no session summary — both fields re-point with their names preserved
and both are marked not-found (`quickstart.md` §4).

**Scope**: **verification only — no new code is expected.** `PathField`
(`frontend/src/components/shared/PathField.vue:37-54,72-73`) and
`MultiPathField` (`frontend/src/components/shared/MultiPathField.vue:35-36,
68-69`) already probe `GET /api/config/path-status` and render per-path
existence, and all ten path inputs in `KnobDrawer.vue` are one of the two. They
report the wrong thing today only because the value they are handed is stale. If
either task below fails, treat it as a defect in Phases 3–5, not as new US4
scope.

- [ ] T024 [US4] Verify existence marking after a re-point by running `quickstart.md` §4 against `frontend/src/components/shared/PathField.vue` and `frontend/src/components/shared/MultiPathField.vue`: missing targets show ❌ not found, present ones show ✅, editing a field to an existing file clears the mark without a reload (FR-009). **Accept**: §4 passes unmodified; no source change required.
- [ ] T025 [US4] Verify that `resolvePathWithBase` in `frontend/src/utils/paths.ts:9-19` re-evaluates when `runtime.session_dir` changes — it reads a pinia ref inside a `computed`, so a switch must re-resolve and re-probe every field without a reload. This is the hinge US4 rests on. **Accept**: after a session switch, every `PathField` re-probes; if it does not, fix the reactivity here rather than adding a manual refresh in the component (C-C).

**Checkpoint**: All four user stories independently functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T026 [P] Document the read-side classification rule and the `paths_stored` / `warnings` wire keys in `docs/config/session-editor-isolation.md`, including why the write-time `_relativized_paths` choke point is retained rather than removed. **Accept**: a reader can derive the four states without opening the service.
- [ ] T027 [P] Add a byte-identity regression test to `tests/test_session_editor_config_service.py`: a campaign whose stored paths are already relative produces an identical `session_doc.yaml` after a full load-modify-save cycle (plan.md Principle XIII ground 1). **Accept**: no diff; this is the claim the constitutional justification rests on.
- [ ] T028 Verify the standing constraints at HEAD: `git diff main -- server/platform_config_service.py` is empty (C-A); the diff contains no change inside any `_build_*_cmd()` in `server/routers/scene_editor.py` (C-B); `grep -n "relativ" frontend/src/utils/paths.ts` returns nothing (C-C); no existing test was edited (C-D). **Accept**: all four hold.
- [ ] T029 Run the full regression set from `quickstart.md` §6: `python -m pytest -q`, `python -m pytest -q tests/test_retrieve_render_isolation.py` (Principle III), and `npm run build` in `frontend/`. **Accept**: green, and the pytest count is ≥ the T002 baseline.
- [ ] T030 Run `quickstart.md` end to end (§1–§5, including §5's boot-override case for FR-011), then restore the fixture campaign from the T004 backups. **Accept**: every section passes; `diff` against the `.bak` files shows the campaign restored.
- [ ] T031 Re-check `plan.md`'s Constitution Check against the delivered diff, with Principle XIII tested by name and its three grounds confirmed by T020 and T027. **Accept**: no verdict changes, or the fallback one-shot migrator path in `plan.md` is opened as a follow-up feature.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup — **blocks all user stories**.
- **US1 (Phase 3)**: depends on Foundational. No dependency on other stories.
- **US2 (Phase 4)**: depends on Foundational **and on US1's T011** — the editor must hold stored values before the write side is safe to change. Independently testable once T011 lands.
- **US3 (Phase 5)**: depends on Foundational (extends T007's function). Independent of US1/US2 on the backend; T023 alone touches the frontend.
- **US4 (Phase 6)**: depends on US1 (needs correct values to mark). Verification only.
- **Polish (Phase 7)**: depends on all desired stories.

### Within Each User Story

- Tests are written first and MUST fail before implementation.
- Backend before wire, wire before frontend — that is also the Opus/Sonnet hand-off boundary (research D8).
- A story is complete before the next priority begins.

### Parallel Opportunities

- T003, T004 in Setup.
- T005 ‖ T006 — different test files.
- T026 ‖ T027 — different files.
- **Not parallel**: T014/T015 (same test file), T018/T019/T020 (same test file), T007/T008 (same source file), T011/T012 (same source file, and T012 depends on T011's shape).
- US3's backend (T018–T022) can run alongside US1/US2's frontend work once Phase 2 closes, since they share no file.

## Parallel Example: Phase 2 Foundational

```bash
# Different test files — safe together:
Task: "T005 benign classification + resolve invariant in tests/test_session_editor_config_service.py"
Task: "T006 wire shape carries paths_stored + warnings in tests/test_editor_service_integration.py"

# Then sequentially, same source file:
Task: "T007 _classify_session_path in server/session_editor_config_service.py"
Task: "T008 ResolvedEditorConfig.paths_stored/warnings in server/session_editor_config_service.py"
```

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational (blocks everything) → 3. Phase 3 US1
4. **STOP and VALIDATE**: `quickstart.md` §1 by hand.
5. At this point the reported defect is fixed and shippable.

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. + US1 → the switch takes (**MVP**)
3. + US2 → no new damage can be created
4. + US3 → existing damage heals, announced
5. + US4 → verification that missing targets are visible
6. Polish → docs, regression, constitutional re-check

### Opus / Sonnet split (research D8)

- **Phases 2 and 4 backend, and Phase 5 backend** are fully pytest-verifiable — the safest Sonnet work. The gate is a command, not a judgment.
- **Phases 3, 4 frontend and T023** have no test runner behind them. Opus reviews the diff before calling those gates.
- **Phases 6 and 7** are verification and orchestration: Opus calls them.

## Notes

- `[P]` = different files, no dependency on an incomplete task.
- Commit after each task or logical group; the worktree from T001 is the only place work happens.
- Every checkpoint is a stop-and-validate point — the phase gates in `plan.md` match these checkpoints one for one.
- **T002 baseline (recorded 2026-08-28, worktree at `264a420`)**: `python -m pytest -q` →
  **4303 passed, 7 failed, 193 skipped** in 139s. The 7 failures are **pre-existing on
  `main` and outside this feature's blast radius**: `test_configure_mcp`,
  `test_ensemble_config_defaults`, `test_extract_facts`, `test_grounding_backend`,
  `test_mempalace_client` (live round-trip), `test_provenance_mcp` (mcp install),
  `test_selection_isolation`. None touches `session_editor_config_service`,
  `platform_config_service`, `scene_editor`, or the config routes.
  The **feature blast radius is green**: 187 passed across
  `test_session_editor_config_service.py`, `test_editor_service_integration.py`,
  `test_config_routes.py`, `test_platform_config_service.py`,
  `test_main_boot_overrides.py`, `test_editor_config_genre_multiline.py`,
  `test_editor_profiles_routes.py`. **That 187 is the regression bar, not 4310.**
