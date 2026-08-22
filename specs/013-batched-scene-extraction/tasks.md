---
description: "Task list for 013-batched-scene-extraction"
---

# Tasks: Batched Scene Extraction

**Input**: Design documents from `specs/013-batched-scene-extraction/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: INCLUDED. The plan names two new test files, the Constitution Check
gates this feature on measured verification (Principle IV), and
[quickstart.md](./quickstart.md) is built around `pytest` plus the deterministic
quote verifier. Tests are part of the deliverable here, not optional.

**Organization**: Grouped by user story. Note that US1–US3 are all **P1** — the
token saving is a regression unless partial-response survivability and verbatim
fidelity both hold, so none of the three ships alone (see spec §User Scenarios).
US1 is the MVP *increment*, not the MVP *release*.

**Execution**: **Opus orchestrates, Sonnet implements** (plan.md §Execution
Model). One Sonnet subagent per phase — or per parallel group within a phase —
each given its task IDs, the contract sections those tasks cite, the files it
may touch, and the tests it must leave green. Opus reviews each returned diff at
the phase checkpoint before opening the next phase; a subagent's report is a
claim, not evidence.

Tasks marked **(Opus)** are NOT delegated — they are judgement calls whose error
would be inherited downstream rather than caught: the batched prompt (Constitution
IV), the fidelity gate and its STOP decision, and the D13 write-up.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable — different file, no dependency on incomplete work
- **[Story]**: US1 / US2 / US3 / US4 for user-story phases

## Path Conventions

Repo root is the worktree `/home/kroussos/src/CampaignGenerator-token-util`.
Engine in `campaignlib/`, CLI in `session_doc/`, server in `server/`, UI in
`frontend/src/`, tests in `tests/`.

---

## Phase 1: Setup

**Purpose**: Confirm the worktree actually runs its own code before anything is measured.

**Delegation**: Opus runs this phase directly. It is three commands, and T001's
result decides whether every later measurement on this branch means anything.

- [X] T001 Verify the worktree's checkout shadows nothing: run `python -c "import campaignlib, pathlib; print(pathlib.Path(campaignlib.__file__).parent)"` from the repo root and confirm it prints the worktree path, not `/home/kroussos/src/CampaignGenerator` (the editable-install `.pth` hardcodes MAIN — a green test run in the wrong tree proves nothing)
- [ ] T002 **DEFERRED to Phase 7** (only console scripts need it; unit tests resolve via `tests/conftest.py`, and this repoint is global — see the warning). Install the package into the server's venv so console scripts resolve: `uv pip install -e . --python "$VIRTUAL_ENV/bin/python"`, per `CLAUDE.md`. ⚠️ **This is global**: the editable `.pth` currently points at the main checkout, so this repoints the running server and every console script — including for unrelated work on `main` — at worktree code. T063 restores it
- [ ] T003 **DEFERRED to immediately before Phase 5** (it is a real subscription run costing ~15 min of quota, and nothing before the fidelity gate consumes it). Capture the per-scene baseline into an **immutable** path — `/tmp/sx_perscene_baseline`, never regenerated — running `scene_extract` in per-scene mode on `~/Phandalin/Phandalin/summaries/20260811`, recording wall-clock, transmitted-token count and scene count. This is the single comparison corpus for SC-002 (observation) and SC-003/SC-004 (the fidelity gate); later scenarios must diff against it, never re-run it, or the gate compares against a different non-deterministic corpus than the one that was timed

**Checkpoint**: the worktree runs its own code and a per-scene baseline exists.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The pure functions and declarations every user story builds on. All
are side-effect-free and independently unit-testable.

**⚠️ CRITICAL**: no user story work begins until this phase is complete.

**Delegation**: three Sonnet subagents in parallel, on disjoint files —
**S-A** projection + grouping (T004–T007, `campaignlib/scenes.py`),
**S-B** wire protocol (T008–T012, `campaignlib/scenes.py` + `tests/test_batched_split.py`),
**S-C** config (T016–T017, `server/session_editor_config_shared.py` + its test).
T013–T015 (prompts) are **Opus's** — see below.

⚠️ S-A and S-B both edit `campaignlib/scenes.py`. Run S-A first, then S-B on the
result, or hand S-B `tests/test_batched_split.py` plus a named insertion point.
Do not run them concurrently against the same file.

### Projection and grouping (data-model §3–§4)

- [X] T004 [P] Declare the projection constants `OUTPUT_CHARS_PER_BODY_CHAR = 4.2` and `CHARS_PER_TOKEN = 4.0` as named module-level constants in `campaignlib/scenes.py`, each with a comment citing research D4 (median of 15 measured scenes, r = 0.784, range 2.4–6.5) and the reason the median is used rather than a conservative bound (symmetric error cost) — do NOT inline these at call sites
- [X] T005 [P] Implement `project_scene_output(entry) -> float` in `campaignlib/scenes.py` returning estimated output tokens from `len(entry["body"].strip())` per data-model DM-5
- [X] T006 Implement `group_scenes(entries, ceiling_tokens) -> list[SceneGroup]` in `campaignlib/scenes.py`: one group when the total projection fits (DM-7); otherwise greedy contiguous packing into the fewest groups each fitting (DM-8); never an empty group, and a single over-ceiling scene forms a group alone (DM-9); pure and deterministic (DM-10); order never changed (DM-11)
- [X] T007 [P] Unit-test grouping in `tests/test_scene_extract.py`: fits-in-one, splits-at-boundary, single-scene-over-ceiling-forms-its-own-group, determinism across repeated calls, and order preservation

### Wire protocol (contracts/wire-protocol.md)

- [X] T008 Implement the sentinel constants and `render_batched_user_prompt(entries) -> str` in `campaignlib/scenes.py`, emitting one indexed request block per scene using `{i:02d}` from `plan_scene_extraction` (never a re-derived index — DM-1)
- [X] T009 Implement `split_batched_response(text, entries) -> SplitResult` in `campaignlib/scenes.py` per contracts/wire-protocol.md §2: scan BEGIN markers, match each to its same-index END, classify every requested scene as `complete` / `empty` / `incomplete` / `absent`, and discard all text outside marker pairs
- [X] T010 Implement reconciliation failures in `split_batched_response` per contracts/wire-protocol.md §3: `UNKNOWN_INDEX`, `DUPLICATE_INDEX`, `NAME_MISMATCH`, `NESTED_SECTION`, `NO_SECTIONS` each fail the whole group (DM-14). Name comparison normalises whitespace ONLY — never case-fold, strip punctuation, or similarity-score (DM-13)
- [X] T011 [P] Create `tests/test_batched_split.py` covering every outcome in contracts/wire-protocol.md §4 and every failure in §3, plus: a scene name containing `<<<CG-SCENE`, duplicate scene names across two indices, a continuation seam landing mid-body, and a seam landing inside a sentinel line (must degrade to `incomplete`, never mis-split)
- [X] T012 [P] Assert in `tests/test_batched_split.py` that `empty` and `incomplete` stay distinguishable — an `empty` section is a finished result (the transcript holds nothing for that scene) while `incomplete` is unfinished work, and conflating them makes the next run's skip-if-exists treat unfinished work as done

### Prompts (research D9)

- [X] T013 [P] Create `config/agents/scene_extract_batched.md`: copy EVERY verbatim ground rule from `config/agents/scene_extract.md` intact — no merged utterances, no editorial insertions inside a `> "…"` span, no repairing transcript garbles, the transcript owns its own mistakes — restated as applying *within each scene*, plus the sentinel obligations in contracts/wire-protocol.md §6 (one pair per scene, in order, index and name copied verbatim, nothing outside the pairs, emit an empty-bodied pair rather than omitting a scene) **(Opus)**
- [X] T014 [P] Create `config/agents/scene_extract_batched_user.md` rendering the per-scene request blocks and restating the sentinel output format **(Opus)**
- [X] T015 [P] Verify `config/agents/scene_extract.md` and `scene_extract_user.md` are byte-unchanged (FR-009) — `git diff --exit-code` on both **(Opus)**

### Config (data-model §7, research D7)

- [X] T016 Add `batch_scenes: bool | None = None` and `batch_tokens: int = 32000` to `ExtractKnobs` in `server/session_editor_config_shared.py`, leaving `tokens: int = 8192` untouched; docstring must record why `batch_scenes` is tri-state (`None` = follow the backend, genuinely different from `False` = per-scene even on the subscription)
- [X] T017 [P] Extend `tests/test_session_editor_config_service.py`: the new defaults round-trip and persist, `batch_tokens` and `tokens` are independent (DM-17), and the existing `test_extract_tokens_defaults_to_scene_extract_cli_default` still passes unmodified

**Checkpoint**: projection, grouping, splitting, prompts and config exist and are unit-tested. No behaviour has changed yet.

---

## Phase 3: User Story 1 — One transcript, one call (Priority: P1) 🎯 MVP increment

**Goal**: A subscription re-extract transmits the transcript once per group instead of once per scene, writing the same files the per-scene mode writes.

**Independent test**: Run a full re-extract of the 8-scene 20260811 session on the subscription; the run reports one transmission and writes 8 files structurally identical to the per-scene run.

**Delegation**: one Sonnet subagent for the engine (T018–T023, sequential — one
file, one function), then two in parallel: CLI (T024–T026) and server
(T027–T030). Tests T031–T034 fan out once the engine lands.

**Brief the engine subagent explicitly on T019.** It is the task most likely to
be implemented in the shape that looks right and is wrong — see the task text.

### Engine

- [X] T018 [US1] Implement `run_batched_scene_extraction(client, *, vtt_text, scenes, extract_dir, model, ...)` in `campaignlib/scenes.py` as a sibling of `run_scene_extraction` (research D1 — do NOT add a `batched` flag to the existing function), reusing `plan_scene_extraction`, `build_scene_extraction_system_prompt`, `format_scene_output` and `snapshot_scene_for_rerun` unchanged
- [X] T019 [US1] **Filter by skip-if-exists BEFORE building the request** in `run_batched_scene_extraction` (DM-2, FR-008a): `entries = plan if force else [p for p in plan if not p["exists"]]`, and pass only `entries` into projection, grouping and the request. Already-extracted scenes must not be sent, projected, or counted toward group sizing
- [X] T020 [US1] Return early with zero calls when the filtered set is empty (DM-3, FR-008b) — today's free no-op must not become a paid one
- [X] T021 [US1] Issue one `stream_api(client, system_prompt, user_prompt, model, max_tokens=ceiling, cache_system=…)` call per group, with the system prompt built ONCE outside the group loop so the transcript is assembled a single time
- [X] T022 [US1] Write each `complete` section through the shared path — `format_scene_output(entry["name"], entry["body"], section.body)` then `snapshot_scene_for_rerun(...)` — never a bespoke writer (guarantees SC-006 and FR-014 without reimplementation)
- [X] T023 [US1] Export `run_batched_scene_extraction`, `group_scenes`, `split_batched_response` and `project_scene_output` from `campaignlib/__init__.py`, adding each to `__all__`

### CLI (contracts/cli-surface.md)

- [X] T024 [US1] Add `--batch-scenes` / `--no-batch-scenes` (shared dest, default off) and `--batch-max-tokens` (default `32000`) to `session_doc/scene_extract.py`; leave `--max-tokens` at `8192` applying to the per-scene loop only (FR-017b)
- [X] T025 [US1] Route `main()` in `session_doc/scene_extract.py` to `run_batched_scene_extraction` when `--batch-scenes` is set, keeping the existing live per-scene branch and the `--batch` Message-Batches branches untouched. **Refuse `--batch` + `--batch-scenes` together with exit 1** before any work (contracts/cli-surface.md §2): the `if not args.batch:` gate at `:478` would otherwise silently ignore `--batch-scenes` and pay the transcript N times while reporting success
- [X] T026 [US1] Note in the `--batch-max-tokens` help and in `session_doc/scene_extract.py`'s module docstring that `--batch` and `--batch-scenes` are different things that compose (contracts/cli-surface.md §1) — one is the 50%-discount submission, the other removes transcript repetition

### Server

- [X] T027 [US1] Add `batch_scenes: int | None = None` to `api_extract` in `server/routers/scene_editor.py`; absent means "resolve per DM-18", present means the GM's explicit per-run choice wins
- [X] T028 [US1] Implement the DM-18 resolution order in `server/routers/scene_editor.py` — explicit request value, else `cfg.extract.batch_scenes` when not `None`, else `cfg.backends.active == "claude-code"` — and expose the result as a **top-level** read-only `batch_scenes_effective: bool` on `ResolvedEditorConfig` (`server/session_editor_config_service.py`), beside `genre`/`model`/`work_dir`. **Not under `extract`**: that field IS the persisted `extra="forbid"` `ExtractKnobs`, so a derived field there would become persisted and PUT-able (contracts/editor-api.md §2)
- [X] T029 [US1] Forward the resolved value from `_build_reextract_cmd` as an EXPLICIT flag (`--batch-scenes` or `--no-batch-scenes`) plus `--batch-max-tokens {cfg.extract.batch_tokens}` (DM-19), so the streamed command line is fully explicit and copyable **Also narrows `tests/test_backend_seam_guardrails.py::test_batch_flag_only_built_by_selection_cli_args`**, which substring-matched `"--batch"` in `server/routers/*.py` and therefore fired on `--batch-scenes`/`--no-batch-scenes`/`--batch-max-tokens`. That guard protects the Message-Batches flag (resolved from `ModelSelection`); scene batching is a different feature resolved from `extract.batch_scenes` + backend, and DM-19 *requires* the router to emit it literally. The check now matches `--batch` as a whole token, with a comment forbidding a re-broadening — a prefix match would push the next author to rename a good flag to dodge a test
- [X] T030 [US1] Include `batch_scenes` in the `_record_activity` knobs dict alongside `batch` and `force`

### Tests

- [X] T031 [P] [US1] Test in `tests/test_scene_extract.py` that a batched run over N scenes makes exactly **one** `stream_api` call for a fitting projection, and — on a separate fixture forced to split by a low `--batch-max-tokens` — that the system prompt is byte-identical across all group calls (transcript assembled once). Also assert call count as a function of the ceiling on a fixed fixture, so SC-009 has automated coverage rather than only quickstart Scenario 6
- [X] T032 [P] [US1] Test the force/skip matrix in `tests/test_scene_extract.py` (SC-005a–d): 5-of-8 present + no force ⇒ request contains exactly 3 and the projection is computed over 3 only; all present + no force ⇒ zero calls; force ⇒ all 8 requested and `.prev` written only where content differs; a session half-extracted per-scene then finished batched converges on the same file set
- [X] T033 [P] [US1] Test that batched output files are structurally identical to per-scene files above `## Verbatim moments` (SC-006), and that no scene's content lands under another scene's path (SC-007)
- [X] T034 [P] [US1] Create `tests/test_scene_extract_isolation.py` asserting the metered path is untouched (SC-008): `run_scene_extraction` unchanged in call count and `cache_system`, `_build_pending_requests` unchanged, `extract.tokens` still `8192`. Add one assertion that the batched path also refuses a summary with no `## Scenes` section, so FR-019 (the Stage 1→2 gate) has a test rather than only "unchanged behaviour"

**Checkpoint**: batched extraction works end-to-end for a complete response. US1 is independently demonstrable.

---

## Phase 4: User Story 2 — A short response does not destroy the run (Priority: P1)

**Goal**: Scenes that arrived are kept, scenes that did not are named, and a re-run requests only those.

**Independent test**: Feed the pass a response covering the first K of N scenes; K files written, N−K named, exit 3, and a re-run without `--force` requests exactly those N−K.

**Delegation**: one Sonnet subagent for T035–T040 (write/skip/report decisions
and exit codes are one coherent change), tests T041–T042 in parallel after.

- [ ] T035 [US2] Write every `complete` non-empty section even when later scenes are missing (FR-010), and skip `incomplete` sections entirely — never write a half-formed file (FR-011)
- [ ] T036 [US2] Skip `empty` sections without writing, recording them separately as "returned no moments" (FR-006) — writing one would make the next run's skip-if-exists treat unfinished work as done
- [ ] T037 [US2] Fail a group whose response is unreconcilable, writing NOTHING from that group (FR-005, DM-14), and report which reconciliation rule fired
- [ ] T038 [US2] Add exit codes `3` (partial run — some scenes written, some missing) and `4` (group failed reconciliation) to `session_doc/scene_extract.py` per contracts/cli-surface.md §4, keeping `0`/`1`/`2` as they are; exit 3 is a resumable state with valid files on disk, not a refusal
- [ ] T039 [US2] Name every missing scene in the run output and add the "Re-run without --force to request only those" line (FR-012, contracts/cli-surface.md §3)
- [ ] T040 [US2] Surface exit 3 in the editor as **partial**, not failed, in `server/routers/scene_editor.py` and `frontend/src/views/session/SessionDocEditor.vue` — the GM must not read a resumable partial as a failure
- [ ] T041 [P] [US2] Test the partial path in `tests/test_batched_split.py` and `tests/test_scene_extract.py` (SC-005): 5 complete + 1 incomplete + 2 absent ⇒ 5 files, 3 named, exit 3; then a re-run without force requests exactly those 3
- [ ] T042 [P] [US2] Test that a reconciliation failure writes nothing from the failing group and exits 4, and that a group failure does not discard successfully-written scenes from OTHER groups

**Checkpoint**: batched mode is resumable and never worse than the per-scene loop on failure.

---

## Phase 5: User Story 3 — Verbatim fidelity does not regress (Priority: P1) 🚦 SHIP GATE

**Goal**: Evidence — not assurance — that batching did not compress, paraphrase, or drop quotes.

**Independent test**: Extract 20260811 both ways; the quote verifier's **exact** rate holds within 5 points and no scene loses > 20% of its moments.

**⚠️ This phase discharges the Constitution Check's one conditional (Principle IV). It is not optional polish.**

**Delegation**: **Opus runs T043–T047 directly.** Reading the verifier output is
a scope decision — exact-vs-`near`, uniform loss vs tail thinning — and T047 is
an explicit STOP. Handing "did fidelity hold?" to the same class of agent that
generated the output is how a failed gate gets reported as a passed one. Only the
static guards T048–T049 are delegated.

- [ ] T043 [US3] Extract the 20260811 session in batched mode into `/tmp/sx_batched` on the subscription backend, alongside the T003 per-scene baseline **(Opus)**
- [ ] T044 [US3] Run `sd_verify_quotes` over both extractions and record the **`verified` (exact)** rates — read the exact rate, NOT the total: a run converting `verified` quotes into `near` ones is a regression even at identical counts, because `near` means "an edit happened", never "safe" (research D10) **(Opus)**
- [ ] T045 [US3] Compare per-scene moment counts **in request order** between the two runs (SC-004) and check specifically for tail thinning — a uniform 10% drop and a 40% drop concentrated in the last scenes are different failures, and only the second indicts batching **(Opus)**
- [ ] T046 [US3] Record the measurement in `specs/013-batched-scene-extraction/research.md` as a new D13 (both rates, per-scene deltas, the session used), so the gate's evidence lives with the design rather than in a terminal **(Opus)**
- [ ] T047 [US3] If the exact rate drops more than 5 points or the tail thins: STOP, and tighten `config/agents/scene_extract_batched.md` (per-scene budget guidance, explicit "do not summarise later scenes") before re-measuring — do not proceed to Phase 6 on a failed gate **(Opus)**
- [ ] T048 [P] [US3] Assert in `tests/test_scene_extract.py` that the batched system prompt contains every verbatim ground rule present in the per-scene prompt (FR-016) — a regression guard against the batched prompt drifting apart from `scene_extract.md`
- [ ] T049 [P] [US3] Assert no **alias-map-derived** normalizer reaches the batched path (FR-015): aliases arrive only as roster knowledge via `format_npc_roster`, never as a rewrite — PR #231 fixed this once and it must not come back. The test must NOT assert byte-identity with the VTT file: `normalize_vtt_speakers` legitimately runs first (`scene_extract.py:427`, FR-015a) and the batched path keeps it

**Checkpoint**: fidelity is measured, recorded, and gated. Only now is batching shippable.

---

## Phase 6: User Story 4 — Visible results (Priority: P2)

**Goal**: The GM can read what batching bought, and the projection constants become re-tunable from evidence.

**Independent test**: A completed run states scenes requested, returned, groups used, and transmissions.

**Delegation**: one Sonnet subagent for T050–T053.

- [ ] T050 [US4] Implement the `RunReport` fields from data-model §6 in `session_doc/scene_extract.py` — scenes total / skipped / requested / written, empty, missing (named), groups used, transmissions, `ceiling_exceeded`
- [ ] T051 [US4] Render the report in the format in contracts/cli-surface.md §3, including the `Transcript sent: Nx (per-scene mode would have sent Mx)` line — this is what makes SC-001 checkable from run output instead of by instrumenting the backend
- [ ] T052 [US4] When the projection forced a split, say so and name the lever: "projection exceeds ceiling; raise --batch-max-tokens for one call" (FR-006d)
- [ ] T053 [P] [US4] Test the report's counts against a fixture with known skipped/written/missing scenes in `tests/test_scene_extract.py`

**Checkpoint**: every success criterion is observable from the run itself.

---

## Phase 7: Polish & Cross-Cutting

**Delegation**: two Sonnet subagents in parallel — **S-UI** (T054–T056,
`frontend/src/`) and **S-DOCS** (T057–T058, `docs/`). T059–T061 are verification
and stay with Opus. T062 is the review itself.

- [ ] T054 [P] Add the "Batch scenes into one call" checkbox to `frontend/src/views/session/SessionDocEditor.vue`, following the `forceReextract` pattern (`:205`), initialised from `extract.batch_scenes_effective` and sending `batch_scenes` in the URL **only when the GM has touched it** (contracts/editor-api.md §4) — absent-vs-present is what keeps the pre-selection overridable in both directions
- [ ] T055 [P] Add the "Batched token limit" field to Stage ② of `frontend/src/components/scene-editor/KnobDrawer.vue` bound to `extract.batch_tokens` with `min="1000"` matching the sibling inputs at `:239`/`:271` (that floor is a UI affordance — no token knob in this repo carries a server-side pydantic constraint, and this one must not become the exception), and clarify the existing "Token limit" help to say **per-scene mode** so the two ceilings are not confusable
- [ ] T056 [P] Fix the stale help text at `frontend/src/components/scene-editor/KnobDrawer.vue:229` (research D12): it still claims "The Re-Extract button always forwards `--force`", which stopped being true with #323 / spec 012. Leaving a false claim about force semantics beside a new force-sensitive control is how the next reader gets it wrong
- [ ] T057 [P] Document batched mode in `docs/cli/session_doc_pipeline.md`: what it is, why the subscription needs it and the metered path does not, the two ceilings, the grouping rule, and the exit-3 partial state
- [ ] T058 [P] Add `--batch-scenes` / `--batch-max-tokens` to `docs/cli/cli_tools.md`, with the `--batch` vs `--batch-scenes` distinction table from contracts/cli-surface.md §1
- [ ] T059 Run the full regression: `python -m pytest tests/ -q`, watching `tests/test_retrieve_render_isolation.py`, `tests/test_no_prefix_identity.py` and `tests/test_layering.py`. **The baseline is NOT green** — 4 tests fail on this branch before any implementation, inherited from `main` (research D13). "No regression" means those four and no others; do not read a pre-existing failure as this feature's doing, and do not "fix" one silently **(Opus)**
- [ ] T060 Walk every scenario in [quickstart.md](./quickstart.md) end-to-end, including Scenario 8's editor wiring checks (checkbox pre-selected on `claude-code`, unchecked on `anthropic`, override reaches the subprocess) **(Opus)**
- [ ] T061 Record SC-002 as an **observation**: wall-clock for both modes against the T003 baseline, alongside the D13 fidelity numbers. There is no time threshold and time parity is acceptable (GM ruling) — the committed measure is SC-001's transmitted-token reduction. Do not reintroduce a time target without first measuring the prefill/decode split **(Opus)**

---

## Phase 8: Adversarial Review

**Purpose**: A fresh read of the whole branch by an agent that did not write it.

- [ ] T062 Run `/code-review medium` over the full branch diff, triage every finding, and either fix it or record why it stands **(Opus)**
- [ ] T063 Restore the shared venv to the main checkout — `uv pip install -e . --python "$VIRTUAL_ENV/bin/python"` from `/home/kroussos/src/CampaignGenerator` — undoing T002's global repoint so unrelated `main` work is not silently running worktree code **(Opus)**

This runs **after** the phase gates, not instead of them. The gates ask "does this
phase meet its requirements"; the review asks "is this code correct". The second
question is not answerable by the agents that answered the first — each Sonnet
subagent saw one phase, and Opus reviewed each diff already holding the belief
that the design was sound. `medium` is the right level for a branch whose
structure has already been gated seven times: fewer, higher-confidence findings,
not a broad uncertain sweep.

**Definition of done for the branch**: T062's findings are resolved, the full
suite is green, and the D13 fidelity numbers plus the SC-001 token reduction and
the SC-002 timing observation are recorded in `research.md`.

---

## Dependencies

```
Phase 1 (Setup)
   └─> Phase 2 (Foundational)  ← BLOCKS everything
          ├─> Phase 3 (US1)    ← MVP increment
          │      └─> Phase 4 (US2)   ← needs the engine to exist
          │             └─> Phase 5 (US3) 🚦 SHIP GATE
          │                    └─> Phase 6 (US4)
          │                           └─> Phase 7 (Polish)
                                              └─> Phase 8 (/code-review medium)
```

**Story dependencies** — unusually, these are *not* independent, and that is
recorded deliberately:

- **US1** needs Phase 2 only. Demonstrable alone (complete response ⇒ files written).
- **US2** needs US1's engine. Its logic is the non-`complete` half of the same write loop.
- **US3** needs US1 + US2 to produce a real extraction to measure. **It gates the release**, not just its own phase.
- **US4** needs the engine to have counts worth reporting.

**None of US1–US3 ships alone.** A token saving without resumability is a
regression on failure; a token saving without measured fidelity is unverified
where it matters most.

## Parallel Opportunities

**Phase 2** — the widest fan-out. T004/T005 (projection), T013/T014 (prompts),
T016 (config) touch disjoint files:

```
T004, T005, T013, T014, T015, T016  →  all parallel
T007, T011, T012, T017              →  parallel once their subjects land
```

T006 depends on T004/T005; T009 depends on T008; T010 depends on T009.

**Phase 3** — tests parallelise once the engine lands: `T031, T032, T033, T034`.
Engine tasks T018→T022 are sequential (one file, one function). CLI (T024–T026)
and server (T027–T030) are parallel with each other.

**Phase 4** — `T041, T042` parallel after T035–T039.

**Phase 5** — `T048, T049` (static guards) parallel with the measurement run
T043–T046.

**Phase 7** — `T054, T055, T056, T057, T058` all parallel (disjoint files); T059–T061 sequential at the end.

## Implementation Strategy

**Increment 1 — Phases 1+2.** Pure functions, fully unit-tested, zero behaviour
change. Safe to land on its own.

**Increment 2 — Phase 3 (US1).** Batching works for the happy path. Demonstrable
value: one transmission instead of eight. **Not yet shippable** — a short
response would still lose the tail.

**Increment 3 — Phase 4 (US2).** Now batching is never worse than the loop it
replaces. This is the first point the feature could ship if fidelity were free.

**Increment 4 — Phase 5 (US3). 🚦** The measurement. If the exact-quote rate
drops or the tail thins, the answer is prompt work and re-measurement — not
shipping with a caveat. This is where a feature that saves tokens by quietly
degrading quotes gets caught.

**Increment 5 — Phases 6+7.** Observability, UI, docs.

**Increment 6 — Phase 8.** `/code-review medium` over the branch, findings
triaged.

**Delegation shape across all of it**: Opus opens a phase, briefs a Sonnet
subagent with that phase's task IDs and the contract sections they cite, reviews
the returned diff at the checkpoint, and only then opens the next phase. The
phases with no Sonnet subagent at all — Phase 1, the prompts in Phase 2, the
fidelity gate in Phase 5, the verification tail of Phase 7 — are the ones where
the work IS the judgement.

**Suggested MVP scope**: Phases 1–5. US4 and the polish phase are genuinely
deferrable; US2 and US3 are not, despite US1 being the only phase that delivers
the headline saving.

## Format Validation

All 63 tasks carry: `- [ ]` checkbox · sequential `TNNN` id (T001–T063) · `[P]`
where parallelisable · `[USn]` on every user-story-phase task and on no other ·
an explicit file path or a named artefact to produce.

13 tasks are marked **(Opus)** — retained in the main thread rather than
delegated. The marker sits inside the description, so the checklist format is
unchanged and the tasks remain machine-parseable.
