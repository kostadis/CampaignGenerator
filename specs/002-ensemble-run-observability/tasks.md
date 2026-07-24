---

description: "Task list for Ensemble Run Observability"
---

# Tasks: Ensemble Run Observability

**Input**: Design documents from `/specs/002-ensemble-run-observability/`

**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/run-stream.md ✓, quickstart.md ✓

**Tests**: Targeted tests ARE included for the high-risk engine changes (process-group kill, grace→force timing, atomic cache writes, secret-safety, explicit-selection) — the plan/quickstart call for `tests/test_subprocess_abort.py` and these are correctness-critical (Constitution I/IV/X). The already-working stream/UI surfaces are covered by verification tasks + quickstart, not new unit tests.

> **Revision note**: This revision folds in `/speckit-analyze` findings — **I1** (EventSource reconnect must not restart a metered run), **I2** (the shared-seam disconnect-kill is a deliberate global change — reconcile + regression-test a non-ensemble route), **U1/U2** (hoist captured state in the `finally`; validate the grace window on the *disconnect* path), and **C1** (explicit-selection coverage for FR-012).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 / US2 / US3 / US4
- Exact file paths are included in each task.

## Path notes

Web-over-CLI layout (plan.md "Structure Decision"). Shared seam: `server/subprocess_runner.py`. Engine: `ensemble_merge.py`, `facts_to_state.py`, `campaignlib.py`. Router: `server/routers/ensemble.py`. Frontend: `frontend/src/api/sse.ts`, `frontend/src/views/ensemble/*`.

⚠️ `server/subprocess_runner.py` and `frontend/src/views/ensemble/useEnsembleRun.ts` (and `frontend/src/api/sse.ts`) are each edited by multiple stories — those edits are **sequential** (never marked [P] against each other), even across phases.

⚠️ **Shared-seam blast radius (I2)**: `stream_subprocess` is used by `grounding.py`, `prep.py`, `session_workflow.py`, `scene_editor.py`, etc. The termination changes (T019–T021) change disconnect behavior for **every** SSE route, not just ensemble. This is intended (no route should leak a runaway process), and T031 regression-tests one non-ensemble route to prove it's safe.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Shared utilities and the test scaffold that later phases build on.

- [X] T001 [P] Add `atomic_write_text(path, text)` and `atomic_write_json(path, obj)` to `campaignlib.py` — write to a temp file in the **same directory** as the destination, then `os.replace` onto the destination (atomic same-filesystem rename). Docstring states the FR-014 guarantee (no partial file ever at the trusted path).
- [X] T002 [P] Create test scaffold `tests/test_subprocess_abort.py` with pytest fixtures: a helper to drive `server.subprocess_runner.stream_subprocess` against a short-lived child script, plus a fixture spawning a long-running child that itself spawns a grandchild (to prove process-group kill on both explicit-abort and disconnect paths).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Run-record result semantics (shared by US3 + US4) and an explicit decision on the shared-seam blast radius (I2) before any termination code is written.

**⚠️ CRITICAL**: US3 and US4 depend on T003/T004; T005 governs T019–T021. US1/US2 do not depend on this phase.

- [X] T003 In `server/subprocess_runner.py`, add a pure helper `classify_result(returncode) -> str` → `"succeeded"` (rc == 0), `"failed"` (rc > 0), `"aborted"` (rc is None or rc < 0, i.e. signal). Reference R5 in the docstring.
- [X] T004 In `server/subprocess_runner.py`, extend `_save_run_log` to record a `result` line (from `classify_result`) alongside returncode/duration/cwd, so the persisted Run record (data-model.md) distinguishes succeeded/failed/aborted.
- [X] T005 **(I2 reconciliation)** In `server/subprocess_runner.py` module docstring, document that disconnect-driven group-kill (added in T019) applies to **all** SSE routes intentionally — no route may leak a runaway/orphaned process — and update `plan.md` "Constraints" so the "non-ensemble routes untouched" wording reads "non-ensemble routes' request/response shapes unchanged; they additionally gain disconnect-driven cleanup." (Doc-only; pairs with the T031 regression test.)

**Checkpoint**: Run record carries an unambiguous outcome; the global-behavior decision is recorded. Build the stories.

---

## Phase 3: User Story 1 — See the exact command, and reuse it (Priority: P1) 🎯 MVP

**Goal**: A dedicated, copyable, secret-free command surfaces for every UI-launched run, reflects the explicitly selected inputs, and reproduces the run when pasted into a workspace terminal.

**Independent Test**: Launch a stage; a copy-able command box shows the full invocation reflecting the selected inputs/backend; pasting it in a workspace terminal runs the same op; no API key appears anywhere; the command never shows an expanded glob when the selection was explicit (quickstart Scenario A).

- [X] T006 [US1] In `server/subprocess_runner.py` `stream_subprocess`, emit a distinct SSE event `event: command\ndata: <json-string>` as the FIRST event, carrying the secret-free invocation (existing `cmd_display` = non-secret env prefix + `python … --flags`). Keep the legacy inline `$ …` data chunk for back-compat (contracts/run-stream.md §Response).
- [X] T007 [P] [US1] In `frontend/src/api/sse.ts`, add an optional `onCommand(cmd: string)` callback to `SSECallbacks` and an `es.addEventListener('command', …)` handler that parses the JSON string and invokes it.
- [X] T008 [US1] In `frontend/src/views/ensemble/useEnsembleRun.ts`, add reactive `command` state, reset it in `run()`/`clear()`, and populate it from `onCommand`. (Sequential with later US4 edits to this file.)
- [X] T009 [P] [US1] Create `frontend/src/components/shared/RunCommandBar.vue` — renders the `command` string in a monospace box with a copy-to-clipboard button (and a placeholder when empty).
- [X] T010 [US1] Wire `RunCommandBar` into `frontend/src/views/ensemble/EnsembleExtract.vue` above `StreamOutput`, bound to the composable's `command`.
- [X] T011 [P] [US1] In `tests/test_subprocess_abort.py`, add a secret-safety + reproducibility test: run a stage with an OpenRouter/DGX-style `env_extra`; assert the `command` event and the persisted record contain the backend/model but NO `*_API_KEY` value (SC-002, FR-003) and reflect the passed inputs (FR-001).
- [X] T012 [P] [US1] **(C1 — FR-012)** In `tests/test_subprocess_abort.py` (or extend T011), assert the displayed command + run record contain **exactly the explicitly-passed chapter selection** and never a wildcard/expanded glob; and reference the existing empty-selection refusal in `tests/test_ensemble_chapters.py` as the companion guarantee that an empty selection is refused, never expanded (FR-012, Principle X).

**Checkpoint**: US1 fully functional — copyable, reproducible, secret-free, explicit-selection-faithful command. Shippable MVP.

---

## Phase 4: User Story 2 — Watch the command progress as it runs (Priority: P1)

**Goal**: Output streams incrementally with a clear in-progress indicator, on every stage.

**Independent Test**: Run a multi-chapter stage; lines appear while running (not only at the end); the page shows a running state (quickstart Scenario B).

- [X] T013 [US2] Verify incremental streaming in `server/subprocess_runner.py` (chunk flush on `>=20` bytes or newline) still delivers per-chapter lines live after the T006 `command` event; adjust only if the new first event regressed flush timing.
- [X] T014 [P] [US2] In `frontend/src/views/ensemble/EnsembleBundle.vue` and `EnsembleSynthesize.vue`, ensure a visible "running" affordance (button → `Running…` / spinner) driven by the shared composable `status === 'running'`; add it where missing so US2 holds for every stage (spec "Scope across stages").

**Checkpoint**: Every stage shows live progress + running state.

---

## Phase 5: User Story 3 — Know it finished, see final output + durable record (Priority: P1)

**Goal**: Unambiguous success/failure finished state, full final output, readable precondition errors, and a persisted record recoverable after the browser closes.

**Independent Test**: Run to success and to failure; states are distinct; nothing-selected gives a readable refusal; `logs/` holds the record after closing the browser (quickstart Scenario C).

- [X] T015 [US3] In `frontend/src/views/ensemble/EnsembleBundle.vue` and `EnsembleSynthesize.vue`, ensure the finished state distinguishes success (`returnCode === 0`) from failure (`> 0`) with distinct labels/colors, matching `EnsembleExtract.vue` (FR-006, SC-004).
- [X] T016 [US3] Verify precondition refusals (empty selection via existing `sse_error_stream`) render their `done.error` text to the operator in the stage views, not a generic "Stream error" (FR-011); fix the `onDone(error)` rendering path in `useEnsembleRun.ts`/views if the message is dropped.
- [X] T017 [P] [US3] In `tests/test_subprocess_abort.py`, assert `_save_run_log` writes a recoverable record (command + full output + `result` + returncode + duration) for a success exit AND a non-zero failure exit, with `result` = succeeded / failed respectively (FR-007, SC-006; uses T003/T004).

**Checkpoint**: Finished/failed outcomes unambiguous; durable record verified.

---

## Phase 6: User Story 4 — Abort a running command (Priority: P2)

**Goal**: Operator (or a lost connection) can stop a run; termination is graceful→force, kills the whole worker group, preserves completed work, never corrupts the resume cache, and a network drop never silently restarts the run.

**Independent Test**: Start a long extraction, click Abort → stops within seconds, "aborted" shown, no orphaned `ensemble_extract` workers, re-run skips completed chapters, mid-flight `merged.json` is complete-or-absent; closing the tab or dropping the network stops the run and does NOT restart it (quickstart Scenarios D & E).

### Engine: atomic cache writes (FR-014) — independent, parallelizable

- [X] T018 [P] [US4] In `ensemble_merge.py` (~line 363), replace `output_path.write_text(json.dumps(...))` for the per-chapter `merged.json` with `campaignlib.atomic_write_json(output_path, merged)` so a force-kill never leaves a truncated `merged.json` at the resume-trusted path (FR-014).
- [X] T019 [P] [US4] In `facts_to_state.py` `write_dossier` (~line 361), replace `dest.write_text(...)` with an atomic write via `campaignlib.atomic_write_text(dest, …)` (the dossier path is trusted by the resume `exists()` check) (FR-014).

### Seam: termination (FR-008, FR-013) — all in subprocess_runner.py, sequential

- [X] T020 [US4] In `server/subprocess_runner.py` `stream_subprocess`, launch the child with `start_new_session=True` (own session/process group) so the whole worker tree is signalable (R1).
- [X] T021 [US4] **(incorporates U1/U2)** In `server/subprocess_runner.py`, **hoist `captured`, `started`, and `proc` above** the read loop, then wrap the loop in `try/except (asyncio.CancelledError, GeneratorExit)/finally`. In `finally`, terminate the process **group**: `os.killpg(os.getpgid(proc.pid), SIGTERM)` → `await asyncio.wait_for(proc.wait(), GRACE)` (add `GRACE = 4.0`, ~3–5 s per FR-008) → `os.killpg(..., SIGKILL)` on `TimeoutError`. The finally MUST run `_save_run_log(... captured ...)` and `on_complete(returncode)` on **every** exit path (normal, explicit-abort, disconnect) so the `_RUNNING` lock is always released and the record (incl. `aborted`) is always written. Note in a comment: the grace `await` must survive async-generator teardown (it runs during `aclose()`), so do not `yield` inside the finally.
- [X] T022 [US4] In `server/subprocess_runner.py`, when termination was abort/disconnect-initiated, include `"aborted": true` in the `done` event payload (best-effort if the connection is still open) and rely on `classify_result` (negative rc) for the persisted record (R5, contracts §done).
- [X] T023 [US4] In `server/routers/ensemble.py`, confirm `_run_locked`'s `_release` (discards the `_RUNNING` key) is driven by the `on_complete` now fired in the T021 `finally`, so an abort/disconnect releases the per-stage lock; add a regression comment. No new endpoint (abort = connection close, contracts §Abort).

### Frontend: abort control, aborted state, and reconnect safety (I1)

- [X] T024 [US4] In `frontend/src/views/ensemble/useEnsembleRun.ts`, add `'aborted'` to the `status` union, keep the `EventSource` handle returned by `connectSSE`, and add `abort()` that calls `es.close()` and sets `status = 'aborted'` (valid only from `'running'`). (Sequential with T008.)
- [X] T025 [US4] **(I1 — reconnect must not restart a metered run)** In `frontend/src/api/sse.ts` and `useEnsembleRun.ts`, treat an `onerror` while `status === 'running'` as **terminal**: call `es.close()` (preventing EventSource's automatic reconnect, which would re-issue the GET and start the run again) and set `status = 'aborted'` with a "connection lost — run stopped" note. A network drop thus behaves identically to an explicit abort (FR-013) and never silently restarts the run.
- [X] T026 [US4] In `frontend/src/views/ensemble/EnsembleExtract.vue` (and `EnsembleBundle.vue`, `EnsembleSynthesize.vue`), add an **Abort** button shown while `status === 'running'`, wired to `abort()`, plus an `aborted` status label distinct from Done/Error (FR-009), and surface the "connection lost" note from T025.

### Tests for US4

- [X] T027 [P] [US4] In `tests/test_subprocess_abort.py`: process-group kill test — start the long child-with-grandchild fixture, then (a) cancel the generator to simulate **explicit abort** and (b) drop the connection to simulate **disconnect**; in BOTH cases assert child AND grandchild PIDs are gone within grace+ε (FR-008, FR-013, R1; covers U2's disconnect path).
- [X] T028 [P] [US4] In `tests/test_subprocess_abort.py`: grace→force timing test — a child that ignores SIGTERM is SIGKILLed within ~GRACE seconds and the run record records `result: aborted` (FR-008, SC-005, R5).
- [X] T029 [P] [US4] In `tests/test_subprocess_abort.py`: atomicity + lock test — kill a writer mid-`atomic_write_json`/`atomic_write_text` and assert the destination is either absent or a complete valid file, never truncated (FR-014); and assert `_RUNNING` is released after an aborted run (FR-010 resumability precondition).

**Checkpoint**: Abort + disconnect stop the whole tree within seconds, never restart it, completed work survives, cache never corrupts.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T030 [P] Update `docs/web/web_ui.md` (ensemble page: copyable command, abort button, aborted + "connection lost" states) and add an "Observability & abort" note to `docs/cli/ensemble_workflow.md` (disconnect = implicit abort; reconnect does not restart; per-run logs under `logs/`).
- [X] T031 **(I2 regression)** Add a regression test (e.g. in `tests/test_subprocess_abort.py` or a sibling) that a **non-ensemble** SSE route's run (a `grounding.py`-style invocation through `stream_subprocess`) is also group-killed on disconnect and leaves no orphan — proving the shared-seam change is safe app-wide, not just for ensemble.
- [X] T032 Run `python -m pytest tests/` — confirm green, especially `tests/test_retrieve_render_isolation.py` (no retrieval/render mixing introduced) and existing `tests/test_ensemble_*.py` (no regression).
- [X] T033 Execute `quickstart.md` Scenarios A–E manually against a real campaign workspace; confirm SC-001…SC-006 (Scenario E now also asserts no auto-restart after the tab is closed / network dropped). — validated by the operator (2026-07-24); this was the gate on Phase 3 of `docs/config/ensemble-isolation.md`.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)**: no deps. T001 unblocks T018/T019; T002 unblocks all test tasks.
- **Foundational (P2)**: T003 → T004; T005 is doc-only. Blocks US3 result assertions (T017) and US4 record/aborted classification (T021/T022). Does NOT block US1/US2.
- **US1 (P3)**, **US2 (P4)**, **US3 (P5)**, **US4 (P6)**: each depends only on Setup (+ Foundational for US3/US4). US1/US2 can start right after Setup.
- **Polish (P7)**: after the stories you intend to ship; T031 depends on T020–T021.

### Story independence

- **US1**: T006 (seam) → T007/T008/T010 (frontend) → T011/T012 (tests); T009 [P]. Independently shippable MVP.
- **US2**: verification (T013/T014); independent of US1.
- **US3**: depends on Foundational (T003/T004) for the record's `result`; otherwise independent.
- **US4**: atomic-writes (T018/T019) independent + parallel; termination (T020→T021→T022→T023) sequential in `subprocess_runner.py`; frontend (T024→T025→T026) sequential with T008.

### Critical sequential chains

- `subprocess_runner.py`: T003/T004 → T006 → T020 → T021 → T022 (same file; one editor at a time).
- `useEnsembleRun.ts`: T008 → T024 → T025 (same file).
- `sse.ts`: T007 → T025 (same file).

### Parallel opportunities

- T001 ∥ T002 (Setup).
- T018 ∥ T019 (different engine files) — and both ∥ the seam/frontend US4 work.
- T011 ∥ T012, and T027 ∥ T028 ∥ T029 (independent test functions; coordinate edits to the shared test file or write sequentially).
- Across stories: once Setup is done, US1 and US2 can proceed in parallel with the US4 atomic-write tasks (different files).

---

## Parallel Example: User Story 4 engine vs frontend

```bash
# Engine atomic-write hardening (independent files):
Task: "T018 atomic per-chapter merged.json write in ensemble_merge.py"
Task: "T019 atomic write_dossier in facts_to_state.py"

# Meanwhile, frontend abort + reconnect-safety (sequential within their files):
Task: "T024 abort()/aborted status in useEnsembleRun.ts"
Task: "T025 reconnect-as-abort in sse.ts + useEnsembleRun.ts"
Task: "T026 Abort button + connection-lost note in EnsembleExtract/Bundle/Synthesize"
# NOTE: termination tasks T020–T023 are sequential in subprocess_runner.py — not parallel.
```

---

## Implementation Strategy

### MVP first (User Story 1 only)

1. Phase 1 Setup (T001–T002).
2. Phase 3 US1 (T006–T012) — copyable, reproducible, secret-free, explicit-selection-faithful command.
3. **STOP & VALIDATE** quickstart Scenario A. Ship: the escape-hatch (Principle IX) is delivered.

### Incremental delivery

1. Setup → US1 (MVP) → US2 (live progress, all stages) → US3 (durable record + Foundational) → **US4 (abort + reconnect safety)** — the largest, highest-risk slice last, fully test-covered.
2. Each story is independently testable per its quickstart scenario.

### Notes

- [P] = different files, no incomplete-task dependency.
- The two genuinely new capabilities are US4's abort/disconnect termination (with reconnect safety, I1) and FR-014 atomic writes; US1–US3 mostly harden existing plumbing — sequence accordingly and don't over-invest in US2.
- The termination change is app-wide (shared seam); T005 records the decision and T031 proves it safe for non-ensemble routes (I2).
- Commit after each task or logical group; keep `tests/test_retrieve_render_isolation.py` green throughout.
