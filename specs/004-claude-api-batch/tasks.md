# Tasks: Claude API Batch Processing Option

**Input**: Design documents from `/specs/004-claude-api-batch/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included — the contracts mandate CI guardrails (isolation-test render list, seam guardrails), and every prior feature in this repo ships with pytest coverage. Test tasks use the repo's established fakes (`_fake_client_with_batches`, `FakeStreamAPI` two-binding monkeypatch).

**Organization**: Grouped by user story from spec.md — US1 (P1, bulk-pipeline cost win), US2 (P2, uniform parameter everywhere), US3 (P3, unambiguous failures/aborts).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable (different files, no dependency on an incomplete task)
- Repo conventions apply to every task: work happens in a worktree on branch `004-claude-api-batch`; test runs use `cd <worktree> && env -u PYTHONPATH ~/.venvs/main/bin/python -m pytest -q`; never commit to main.

---

## Phase 1: Setup

**Purpose**: Branch/worktree preparation (existing repo — no scaffolding needed)

- [X] T001 Create worktree + branch `004-claude-api-batch` off `main`; copy gitignored `config/wiring.yaml` from the main checkout into the worktree (required by `tests/test_extract_facts.py::test_cli_parallel_fully_cached`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The hardened seam + the shared flag. Every user story consumes these.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 Promote `_atomic_write_text` (tmp + `os.replace`) from `pipelines/ensemble/extract_facts.py:231` into `campaignlib/` (new `campaignlib/io_atomic.py` or the most natural existing module); re-import it in `pipelines/ensemble/extract_facts.py` so there is a single definition; unit test alongside existing atomicity tests
- [X] T003 Extend `campaignlib/api/batch.py`: `collect_batch` carries per-item `stop_reason`; `build_batch_request` accepts a content-block list as `user` (needed for `dnd_sheet` vision payloads) while keeping the string path byte-identical; update `tests/test_batch_api.py` fakes accordingly
- [X] T004 Implement `run_batch(client, requests, *, label, poll_interval, on_tick)` in `campaignlib/api/batch.py` per `contracts/batch-seam.md`: stderr `Batch submitted: <id> (<n> requests)` immediately after submit (FR-013); progress line per tick from `request_counts` (FR-007); SIGINT/SIGTERM during the poll → best-effort `batches.cancel` + outcome report + non-zero exit, handlers restored on return (FR-009); post-collect `!!!` truncation banner naming each `custom_id` with `stop_reason == "max_tokens"` (FR-010); returns all items keyed by `custom_id`, never raising on per-item failure (FR-008); export from `campaignlib/api/__init__.py`
- [X] T005 Implement `run_single_batch(client, *, system, user, model, max_tokens, cache_system=False) -> str` in `campaignlib/api/batch.py` — one-item convenience over `run_batch` for single-call CLIs, returning the text or raising `RuntimeError` with the item's error; export from `campaignlib/api/__init__.py`
- [X] T006 Add `--batch` (store_true, help text per `contracts/cli-batch-flag.md`, incl. the ensemble_batch disambiguation) to `add_backend_args` in `campaignlib/api/client.py`; `client_from_args` fails fast with a clear `SystemExit` when `--batch` is combined with any resolved non-anthropic backend, **including `CG_BACKEND`-driven selection** (FR-003)
- [X] T007 [P] Seam unit tests in `tests/test_batch_api.py` using `_fake_client_with_batches`: submission line emitted, poll-until-ended, signal → cancel called + non-zero, truncation banner on fake `stop_reason="max_tokens"`, partial-failure result set returned intact, `run_single_batch` success/failure paths
- [X] T008 [P] Guardrail tests in `tests/test_backend_seam_guardrails.py`: `--batch` present in registrar output; rejection matrix for `dgx`/`openrouter`/`claude-code` and for `CG_BACKEND` env selection; no work dispatched before rejection
- [X] T009 [P] CI guardrails: add `run_batch`/`run_single_batch` to the render-call list in `tests/test_retrieve_render_isolation.py`; new grep-level test asserting no module outside `campaignlib/api/` references `messages.batches`

**Checkpoint**: seam contract fully met and tested — user stories can start (in parallel if staffed).

---

## Phase 3: User Story 1 — Halve the API cost of a bulk pipeline run (Priority: P1) 🎯 MVP

**Goal**: A multi-unit grounding run (`distill --batch`, `planning --batch`, …) submits its independent extraction calls as one grouped batch, writes identical artifacts, and bills at 50%.

**Independent Test**: quickstart §1 — `distill --batch` from a campaign dir: one submission line with N = missing chunks, all chunk files written atomically, normal synthesize stage follows; billing console shows batch rate.

- [X] T010 [US1] `run_extract_pipeline(..., batch: bool = False)` in `campaignlib/pipelines.py`: compute missing-chunk set with the existing skip-if-exists check **before** request building; one `build_batch_request` per missing chunk (preserving `cache_system` prefix behavior); single `run_batch` call; write each success atomically via the T002 helper; return the list of failed unit ids so callers can print `FAILED <custom_id>: …` lines and exit non-zero
- [X] T011 [P] [US1] Pipeline batch tests in `tests/test_campaignlib_pipeline.py`: skip-if-exists excludes pre-populated chunks from the request set; results land at the same paths the serial loop writes; atomic write used; partial failure returns failed ids and leaves successes on disk
- [X] T012 [US1] Wire `--batch` through `pipelines/grounding/planning.py`: extract fan-out via `run_extract_pipeline(batch=args.batch)`, synthesis call via `run_single_batch` when `args.batch`; non-zero exit on any failed unit
- [X] T013 [P] [US1] Same wiring for `pipelines/grounding/distill.py`, `pipelines/grounding/party.py`, `pipelines/grounding/campaign_state.py`
- [X] T014 [US1] `session_doc/scene_extract.py`: plain `--batch` becomes the blocking `run_batch` path (submit → poll → collect in one invocation); `--submit-only`/`--collect` keep their existing detached behavior unchanged (grandfathered per FR-012); `format_scene_output` remains the single formatter so files stay byte-identical
- [X] T015 [P] [US1] CLI-level batch tests (FakeStreamAPI-style two-binding monkeypatch, patching the batch entry points) in `tests/test_planning.py`, `tests/test_distill.py`, `tests/test_campaign_state.py`: `--batch` routes through the batch seam, default path untouched (FR-011)

**Checkpoint**: the P1 cost win is fully usable on the four grounding CLIs + scene_extract.

---

## Phase 4: User Story 2 — One parameter, learned once, everywhere (Priority: P2)

**Goal**: Every LLM-bearing CLI accepts the identical `--batch` parameter and routes through the seam.

**Independent Test**: quickstart §2 — the `--help | grep -- --batch` loop over all console scripts reports no `MISSING:`; quickstart §3 — rejection is immediate for non-anthropic backends.

- [X] T016 [P] [US2] Route single-call session_doc CLIs through `run_single_batch` when `args.batch`: `session_doc/sd_plan.py`, `session_doc/sd_consistency.py`, `session_doc/check_consistency.py`, `session_doc/vtt_voice_compare.py` (`enhance_summary` already batched — align its plain `--batch` to the blocking path like T014)
- [X] T017 [P] [US2] `pipelines/session_prep/prep.py`: its 5 dependent calls become sequential one-item batches when `args.batch` (order preserved — never grouped); `pipelines/session_prep/transform.py`: single call via `run_single_batch`
- [X] T018 [P] [US2] Grounding/ingest/ensemble single-call CLIs via `run_single_batch`: `pipelines/grounding/npc_table.py`, `pipelines/grounding/make_tracking.py`, `pipelines/content_ingest/dnd_sheet.py` (content-block payload from T003), `pipelines/ensemble/synthesise_world_state.py`, `pipelines/ensemble/synthesise_polish.py`, `scabard_sdk/scabard_sync.py`
- [X] T019 [P] [US2] `pipelines/rlm/query.py`: map phase grouped into one batch submission, reduce as a one-item batch; `session_doc/scrub_mechanics.py`: per-file glob grouped into one submission
- [X] T020 [US2] `session_doc/sd_narrate.py`: degraded mode — each scene a sequential one-item batch (the `handoff`/`prev_voice_sample` chain forbids grouping); `--help` text documents the degradation and why
- [X] T021 [US2] `pipelines/ensemble/facts_to_state.py`: hand-rolled `--backend` parser gains `--batch` with registrar-identical wording; batch path groups its per-unit anthropic calls; rejection matrix applies (its DGX fan-out is unaffected)
- [X] T022 [US2] `pipelines/ensemble/extract_facts.py` + `pipelines/ensemble/polish.py`: when `--batch` + anthropic backend, replace the thread-pool fan-out with one grouped submission per run; `pipelines/ensemble/ensemble.py` forwards `--batch` to the child `extract_facts` command
- [X] T023 [P] [US2] Uniformity test (quickstart §2 as pytest): every `[project.scripts]` LLM-bearing entry point's parser accepts `--batch`, in `tests/test_backend_seam_guardrails.py` (or new `tests/test_batch_flag_uniformity.py`); sync test asserting `facts_to_state`'s flag wording matches the registrar's

**Checkpoint**: SC-002 met — 100% of LLM-bearing CLIs accept the parameter.

---

## Phase 5: User Story 3 — Failures and aborts are unambiguous and don't waste money (Priority: P3)

**Goal**: Partial failures are listed per item with non-zero exit while successes persist; abort cancels the remote batch; truncation is loud.

**Independent Test**: quickstart §4 (fake-driven partial failure), §5 (SIGTERM during a live batch → `canceling` in provider console).

- [X] T024 [P] [US3] End-to-end partial-failure tests (one succeeded + one errored + one expired item): successes written, `FAILED <custom_id>: <status> <error>` lines, exit ≠ 0 — seam-level in `tests/test_batch_api.py` plus one CLI-level case in `tests/test_distill.py`
- [X] T025 [P] [US3] Abort tests in `tests/test_batch_api.py`: SIGINT and SIGTERM delivered mid-poll each trigger exactly one `batches.cancel(batch_id)` call, an outcome report line, non-zero exit; signal handlers restored after `run_batch` returns
- [X] T026 [P] [US3] Truncation + terminal-state tests: `stop_reason="max_tokens"` item emits the banner naming its `custom_id` and still counts as succeeded (output written, warning loud); `canceled`/`expired` items reported as failures
- [X] T027 [US3] Audit and fix exit-code propagation at every call site wired in US1/US2 (grounding CLIs, scene_extract, sweep CLIs): any non-succeeded item ⇒ process exit ≠ 0, successes still on disk (FR-008); verify the SIGTERM path composes with the web UI's graceful→force abort (spec 002) — the graceful window must be long enough for the cancel request

**Checkpoint**: all three stories independently verifiable.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T028 [P] Add the drift-guard comment to `server/backend_forwarding.py` referencing spec 004 (vocabulary copy deliberately unchanged; UI exposure is a follow-up feature)
- [ ] T029 [P] Docs: document `--batch` in `docs/cli/cli_tools.md` (shared flag section) and note the batch option + degraded CLIs in `docs/cli/session_doc_pipeline.md` / `docs/cli/ensemble_workflow.md` where those CLIs are described
- [ ] T030 Full-suite gate from the worktree: `env -u PYTHONPATH ~/.venvs/main/bin/python -m pytest -q` (only known pre-existing failures allowed); then run quickstart.md §1–§3, §5–§7 live against a real campaign dir and record results in the PR description

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none
- **Foundational (Phase 2)**: after T001 — **blocks all stories**. Internal order: T002/T003 → T004 → T005/T006 → T007/T008/T009 (tests parallel once implementations exist)
- **US1 (Phase 3)**: after Phase 2. T010 → {T012, T013, T014}; T011/T015 parallel with wiring once T010 lands
- **US2 (Phase 4)**: after Phase 2 — independent of US1 except T016's enhance_summary alignment mirrors T014's pattern. T016–T019 fully parallel (disjoint files); T020–T022 parallel with each other; T023 last
- **US3 (Phase 5)**: T024–T026 need only Phase 2; T027 needs US1+US2 call sites to exist
- **Polish (Phase 6)**: after all desired stories

### Parallel Opportunities

- Phase 2: T007, T008, T009 together after T006
- US1: T011, T013, T015 together after T010/T012
- US2: T016, T017, T018, T019 in one wave (disjoint files) — the widest fan-out; a Sonnet subagent per task per the repo's orchestrate/implement convention
- US3: T024, T025, T026 together

### Parallel Example: User Story 2

```bash
# One wave of four subagents, disjoint file sets:
Task: "T016 session_doc single-call CLIs → run_single_batch"
Task: "T017 prep sequential one-item batches + transform"
Task: "T018 grounding/ingest/ensemble single-call CLIs"
Task: "T019 query map-phase + scrub_mechanics grouped batches"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 + Phase 2 (seam hardened, flag registered, guardrails green)
2. Phase 3 (US1) → **STOP and VALIDATE**: quickstart §1 with a real `distill --batch` run; confirm batch-rate billing
3. This alone delivers SC-001 on the highest-spend pipelines

### Incremental Delivery

1. US1 → validate → PR-able MVP
2. US2 → uniformity loop green → SC-002
3. US3 → failure/abort semantics verified → SC-003/SC-005
4. Polish → full suite + quickstart → PR against `main`; merge only on explicit go-ahead

### Notes

- Constitution gates riding along: T009 (Principle III render list), T002+T010 (Principle I atomic truth-on-disk), T020/T017 (Principle II — never parallelize order-dependent chains), all seam work confined to `campaignlib/api/` (Principle V)
- FR-011 regression bar: with `--batch` absent, zero behavior change — T015/T030 enforce
