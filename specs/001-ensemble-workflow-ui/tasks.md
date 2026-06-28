---

description: "Task list for Ensemble Grounding-Doc Workflow UI"
---

# Tasks: Ensemble Grounding-Doc Workflow UI

**Input**: Design documents from `specs/001-ensemble-workflow-ui/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md, contracts/cli.md, quickstart.md

**Tests**: Targeted tests are included where the contracts specify behavior (the OpenRouter seam contract test, gate/promote guards, the Anthropic-path regression). This is not full TDD — it matches the constitution's "tested by name" expectation and the CI isolation guard.

**Organization**: Tasks are grouped by user story. This feature is an **extension of the existing Vue app + FastAPI server** (same `./startup`, same nav) — not a new application. The existing `/grounding` (Anthropic per-tool) path is left untouched.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3 / US4

## Path Conventions

Web app over a CLI engine. Backend: `server/`, root-level CLI scripts, `campaignlib/`. Frontend: `frontend/src/`. Tests: `tests/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Minimal scaffolding for an additive feature in a mature codebase.

- [X] T001 Document the `OPENROUTER_API_KEY` env var and confirm the `openai` SDK is importable, updating the Dependencies section of `CLAUDE.md` (parity with the existing `ANTHROPIC_API_KEY` note)
- [X] T002 [P] Create the frontend stage-component directory `frontend/src/views/ensemble/` and an empty backend router stub `server/routers/ensemble.py` (module + `router = APIRouter()`, mirroring the header of `server/routers/grounding.py`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared kernel every user story builds on — config schema, router mount, frontend route + shell + nav.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 Add an `EnsembleSection` Pydantic model (campaign_dir, chapters_glob, per-stage `extract`/`synthesize` backend profiles, known_names, aliases_path — per data-model.md §"Config schema addition") to `server/config_models.py` and register `"ensemble"` in `UI_SECTION_NAMES`
- [X] T004 Mount the ensemble router at `/api/ensemble` via `app.include_router(...)` in `server/main.py` (alongside the existing routers; do not modify any existing registration)
- [X] T005 Add the `/ensemble` route tree to `frontend/src/router.ts` and create `frontend/src/views/EnsembleWorkflow.vue` as a `WizardShell` host with the stage steps (Setup → Extract → Bundle → Synthesize → Review), mirroring `frontend/src/views/SessionWorkflow.vue`
- [X] T006 [P] Add an "Ensemble Workflow" entry to the app's primary navigation in `frontend/src/App.vue`, placed beside the existing "Grounding Docs" link (which stays unchanged)
- [X] T007 [P] Add shared router helpers to `server/routers/ensemble.py`: an `_sse_response()` and `_cmd_opt/_cmd_multi/_cmd_flag` set (copy the pattern from `server/routers/grounding.py`) and a `_resolve_ensemble_path()` that confines paths to the campaign workspace

**Checkpoint**: The new page is reachable and empty; the router is mounted; config persists. User stories can begin.

---

## Phase 3: User Story 1 - Walk the ensemble pipeline from a single UI surface (Priority: P1) 🎯 MVP

**Goal**: Step the operator through extract → bundle → synthesize → review from one page, with stage status derived from disk and each step's output streamed. Works with the **existing** backends (DGX/Anthropic); OpenRouter arrives in US2.

**Independent Test**: With a campaign that has chapter files, run extraction from the page, see per-chapter artifacts appear, run bundling, reach synthesis — without typing a command; reload and confirm completed stages are still shown complete.

### Tests for User Story 1

- [X] T008 [P] [US1] Integration test: `GET /api/ensemble/status` reports `extract` as current with no run, then `extract: complete` once `docs/ensemble/per_chapter/*/merged.json` exist — in `tests/test_ensemble_status.py` (quickstart Validation 3)

### Implementation for User Story 1

- [X] T009 [US1] Implement disk-derived `GET /api/ensemble/status` (completion predicates per contracts/api.md §Status; no caching) in `server/routers/ensemble.py`
- [X] T010 [US1] Implement `GET /api/ensemble/files` and `GET /api/ensemble/file` (list/read artifacts, mirror `grounding.py:/extracts`) in `server/routers/ensemble.py`
- [X] T010a [US1] **(M4)** Implement a per-campaign, per-stage in-flight lock helper in `server/routers/ensemble.py` (lock file or in-process registry keyed by campaign+stage). ALL `/run/*` endpoints (T011–T013a) MUST acquire it on launch and return HTTP 409 "stage already running" if held — preventing concurrent writers from corrupting `per_chapter/` cache (the `ensemble_workflow.md` orphaned-worker trap). Released on stream completion.
- [X] T011 [US1] Implement stage runner `GET /api/ensemble/run/extract` (builds `ensemble_batch.py`, SSE via `stream_subprocess`, resumable; acquires the T010a lock) in `server/routers/ensemble.py`
- [X] T012 [US1] Implement stage runner `GET /api/ensemble/run/bundle` (builds `facts_to_state.py`, including `list=true` → `--list` no-model mode) in `server/routers/ensemble.py`
- [X] T013 [US1] Implement stage runners `GET /api/ensemble/run/recent-events` (`build_recent_events.py`) and `GET /api/ensemble/run/synthesize` (dispatch on `doc` to the four synthesis scripts; reject `output` that targets a live doc) in `server/routers/ensemble.py`
- [X] T013a [US1] **(M1)** Implement stage runner `GET /api/ensemble/run/threads` (builds `facts_to_state.py --types thread --render-only`, deterministic/no-model, writes `docs/ensemble/threads.md`) in `server/routers/ensemble.py`, symmetric with `/run/recent-events`. This is the chronological-spine input fed to `/run/synthesize --threads` (contracts/api.md, data-model.md §Stage). Surface it in `EnsembleBundle.vue` (T016).
- [X] T014 [P] [US1] Build `frontend/src/views/ensemble/EnsembleSetup.vue` — campaign dir + chapter glob inputs **plus known-names (multi-path) and aliases-path inputs (M2)**, all persisted via `config.updateSection('ensemble', …)`. The bundle endpoint (T012) and the US3 alias gate (T036) read `known_names`/`aliases_path` from this config.
- [X] T015 [P] [US1] Build `frontend/src/views/ensemble/EnsembleExtract.vue` — run `/run/extract` via `connectSSE`/`RunPanel`, stream progress, list produced artifacts, reflect status
- [X] T016 [P] [US1] Build `frontend/src/views/ensemble/EnsembleBundle.vue` — run `/run/bundle` (and the `--list` scope view), stream output, list dossiers
- [X] T017 [P] [US1] Build `frontend/src/views/ensemble/EnsembleSynthesize.vue` — run `/run/synthesize` per doc, write `*_draft.md`, list drafts
- [X] T018 [US1] Wire the `WizardShell` steps in `EnsembleWorkflow.vue` to `GET /api/ensemble/status` so stage completion (disk-derived) drives step state and survives reload

**Checkpoint**: A full extract→bundle→synthesize→draft walk is doable from the page using DGX/Anthropic. MVP complete.

---

## Phase 4: User Story 2 - Choose the backend per stage, including OpenRouter (Priority: P2)

**Goal**: Make extraction/aggregation and synthesis backend-selectable independently among DGX, Anthropic, and **OpenRouter** — OpenRouter reached only through the single `campaignlib` seam (Principle V).

**Independent Test**: With the local box unreachable, select OpenRouter for extraction, run it, then select Anthropic for synthesis and complete a refresh; each artifact records the backend used.

### Tests for User Story 2

- [X] T019 [P] [US2] Contract test `tests/test_openrouter_seam.py`: `make_client(backend="openrouter")` returns the OpenRouter client; missing `OPENROUTER_API_KEY` raises; no module outside `campaignlib/api` constructs it (contracts/cli.md §Seam)
- [X] T019a [P] [US2] **(M5)** Integration test `tests/test_backend_retry_resume.py`: fail a stage partway on backend A, retry on backend B, and assert (1) prior-stage artifacts intact, (2) the failed stage resumes (skip-if-exists) rather than restarts, (3) no empty/partial `merged.json` counts as complete (locks SC-003; also exercises the M3 guard from T027a)

### Implementation for User Story 2

- [X] T020 [US2] Implement `_OpenRouterClient` in `campaignlib/api/backends.py` (OpenAI SDK at `https://openrouter.ai/api/v1`, real `OPENROUTER_API_KEY`, model id passed verbatim — no dgxlib lookup, `OPENROUTER_BASE_URL` override, Anthropic-shaped `.messages` façade). **(M3 prevention)** Honors a no-thinking request extra (per-call and via `DGX_NO_THINKING`/equivalent env) so extraction can suppress reasoning traces — the dgxlib `thinking_default: false` safety net does not apply on this path.
- [X] T021 [US2] Add the `backend == "openrouter"` branch to `make_client()` in `campaignlib/api/client.py` (precedence: claude-code → openrouter → dgx endpoint → Anthropic default) — depends on T020
- [X] T022 [P] [US2] Add `--backend {anthropic,dgx,openrouter}` + `--endpoint` flags to `synthesise_world_state.py` and thread them into its `make_client(...)` call (default `anthropic` ⇒ unchanged)
- [X] T023 [P] [US2] Add the same `--backend`/`--endpoint` flags to `campaign_state.py`, threaded into `make_client(...)`
- [X] T024 [P] [US2] Add the same `--backend`/`--endpoint` flags to `party.py`, threaded into `make_client(...)`
- [X] T025 [P] [US2] Add the same `--backend`/`--endpoint` flags to `planning.py`, threaded into `make_client(...)`
- [X] T026 [US2] Verify the extraction/aggregation scripts reach OpenRouter via `CG_BACKEND=openrouter` + an OpenRouter `--model` (no script edit expected for `ensemble_batch.py`/`facts_to_state.py`); add a `--backend` pass-through only if needed for symmetry
- [ ] T027 [US2] Stamp backend+model provenance into LLM-produced outputs (synthesis drafts and `facts_to_state.py` dossiers) where each script already records metadata (FR-008) — sequential, touches the synthesis scripts + `facts_to_state.py`
- [X] T027a [US2] **(M3 detection)** Add an empty-output guard in the seam (`campaignlib/api`: treat empty/whitespace `content` from any backend as an error, not a result) and ensure the extraction/aggregation/synthesis scripts fail loudly (non-zero exit) and write NO empty/partial artifact when output is empty — so a silently-empty run never flips disk-derived status (FR-002) to "complete" (spec edge case; FR-009). Covered by T019a.
- [X] T028 [US2] Add `backend`/`endpoint`/`model` query params to all `/api/ensemble/run/*` endpoints and inject `ANTHROPIC_API_KEY`/`OPENROUTER_API_KEY` via `stream_subprocess` `env_extra` (never as query params) in `server/routers/ensemble.py`
- [X] T029 [US2] Add a synthesis-capability allow-list to `server/config.py` and surface a non-fatal warning in `/api/ensemble/run/synthesize` when a sub-Sonnet model is chosen for synthesis (FR-014, R6) in `server/routers/ensemble.py`
- [X] T030 [P] [US2] Add per-stage backend selectors (extract + synthesize, independent) to `frontend/src/views/ensemble/EnsembleSetup.vue`, persist to `ui.ensemble`, and display the recorded backend on produced artifacts

**Checkpoint**: Each LLM stage runs on any of the three backends, mixable; OpenRouter lives only in the seam.

---

## Phase 5: User Story 3 - Drop to Claude or the CLI for the judgment between steps (Priority: P2)

**Goal**: Represent the human-judgment checkpoints (scope review, alias correction, diff-before-promote) as blocking gates satisfied in Claude/CLI; files are the interchange; the UI never auto-advances past a precision boundary and never auto-overwrites a live doc.

**Independent Test**: At the scope gate, an alias edit made outside the UI is reflected on return without re-running any LLM step; at the promote gate, a draft reaches a live doc only via the explicit promote action.

### Tests for User Story 3

- [X] T031 [P] [US3] Integration test: `/api/ensemble/run/synthesize` rejects an `output` pointing at a live grounding doc; `PUT /api/ensemble/file` to a live doc is rejected; `POST /api/ensemble/promote` is the only writer of live docs — in `tests/test_ensemble_gates.py` (quickstart Validation 6/7)

### Implementation for User Story 3

- [X] T032 [US3] Implement `PUT /api/ensemble/file` (path-validated, confined to workspace, **rejects live grounding docs**) in `server/routers/ensemble.py`
- [X] T033 [US3] Implement `GET /api/ensemble/diff` (unified diff draft vs live, read-only) in `server/routers/ensemble.py`
- [X] T034 [US3] Implement `POST /api/ensemble/promote` (copy reviewed draft → live; restricted to the four known grounding docs) in `server/routers/ensemble.py`
- [X] T035 [P] [US3] Add the scope-review gate to `frontend/src/views/ensemble/EnsembleBundle.vue` — show the `--list` output, block advancement to aggregation until the operator confirms
- [X] T036 [US3] Add the alias-correction gate to `frontend/src/views/ensemble/EnsembleBundle.vue` — edit `aliases.json` via the file endpoints (or hand off to CLI/chat) and reflect external edits without re-running an LLM step — same file as T035, sequential
- [X] T037 [P] [US3] Add the diff-before-promote gate to `frontend/src/views/ensemble/EnsembleSynthesize.vue` — render the `/diff`, expose an explicit **Promote** button calling `/promote`, never auto-write
- [X] T038 [US3] Reflect gate confirmation state in `EnsembleWorkflow.vue` so the wizard cannot skip an unsatisfied gate

**Checkpoint**: Aggregation never consumes extraction output until scope/alias are confirmed; promotion is always explicit.

---

## Phase 6: User Story 4 - Keep the existing Anthropic workflow available (Priority: P3)

**Goal**: Guarantee the existing per-tool Anthropic grounding-doc path (the `/grounding` page) is unchanged and independently usable.

**Independent Test**: After this feature ships, the `/grounding` page behaves identically and the synthesis scripts with no new flags produce the same commands/output.

### Tests for User Story 4

- [X] T039 [P] [US4] Regression test: each synthesis script invoked with **no** `--backend`/`--endpoint` constructs the same `make_client()` (Anthropic) path and output as before — in `tests/test_synthesis_backend_default.py` (SC-006)

### Implementation for User Story 4

- [X] T040 [US4] Confirm `tests/test_retrieve_render_isolation.py` passes with the new router (the router must contain no retrieval/render calls) and run the full `pytest tests/` suite
- [X] T041 [US4] Verify by inspection that `server/routers/grounding.py` and `frontend/src/views/GroundingDocs.vue` (and its nested views) are untouched by this feature; record the diff scope

**Checkpoint**: New workflow and old workflow coexist; no regression.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T042 [P] Run all 8 validations in `quickstart.md` end-to-end and record results
- [X] T043 [P] Update `docs/web/web_ui.md` to document the new Ensemble Workflow page and add a "run this from the UI" pointer near the top of `docs/cli/ensemble_workflow.md`
- [X] T044 Consistency/cleanup pass on `server/routers/ensemble.py` (helper reuse, error messages match the fast-fail contract in FR-009)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup; **blocks all user stories**.
- **US1 (Phase 3)**: depends on Foundational. The MVP.
- **US2 (Phase 4)**: depends on Foundational. Builds on US1's run endpoints (adds backend params) and Setup page (adds selectors), but the seam/CLI work (T019–T027) is independent of US1 and can proceed in parallel with Phase 3.
- **US3 (Phase 5)**: depends on Foundational and on US1's bundle/synthesize endpoints + step components (it adds gates to them).
- **US4 (Phase 6)**: depends on US2 (the `--backend` defaults it asserts) and on the new router existing; otherwise independent.
- **Polish (Phase 7)**: after the desired stories are complete.

### Story-level notes

- **US2's seam + CLI tasks (T019–T027)** touch `campaignlib/` and root scripts — fully independent of the US1 UI and can be built first or in parallel.
- **US3** extends `EnsembleBundle.vue` / `EnsembleSynthesize.vue` created in US1, so it follows US1 for those files.

### Within `server/routers/ensemble.py`

Tasks T007, T009–T013, **T010a, T013a**, T028, T029, T032–T034 all edit this one file → they are **sequential** with respect to each other (no `[P]`), even across stories. Plan to serialize router edits. Note T010a (the in-flight lock) must land before/with the `/run/*` endpoints since they acquire it.

---

## Parallel Opportunities

- **Setup**: T002 [P].
- **Foundational**: T006, T007 [P] (different files: `App.vue`, `ensemble.py`).
- **US1 frontend**: T014, T015, T016, T017 [P] (four distinct `.vue` files). T008 [P] (test).
- **US2 CLI**: T022, T023, T024, T025 [P] (four distinct scripts); T019, T019a [P] (tests); T030 [P] (frontend).
- **US3**: T031 [P] (test); T035 and T037 [P] (different `.vue` files); T036 follows T035 (same file).
- **US4**: T039 [P] (test).
- **Polish**: T042, T043 [P].

### Parallel example — US1 frontend

```bash
# After the run/status endpoints exist, build the four step components together:
Task: "Build EnsembleSetup.vue"      # T014
Task: "Build EnsembleExtract.vue"    # T015
Task: "Build EnsembleBundle.vue"     # T016
Task: "Build EnsembleSynthesize.vue" # T017
```

### Parallel example — US2 CLI flags

```bash
# Independent scripts, same flag addition:
Task: "Add --backend/--endpoint to synthesise_world_state.py"  # T022
Task: "Add --backend/--endpoint to campaign_state.py"          # T023
Task: "Add --backend/--endpoint to party.py"                   # T024
Task: "Add --backend/--endpoint to planning.py"                # T025
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → Phase 2 Foundational.
2. Phase 3 US1.
3. **STOP and VALIDATE**: walk extract→bundle→synthesize→draft from the page on DGX/Anthropic (quickstart Validations 3–4). Demo.

### Incremental Delivery

1. Setup + Foundational → page reachable.
2. + US1 → walk the pipeline (MVP).
3. + US2 → OpenRouter and per-stage backends (the headline ask; ship the seam test first).
4. + US3 → blocking gates and explicit promotion.
5. + US4 → regression guard locks the old path.

### Recommended early track

Because US2's seam (T019–T021) is the riskiest, novel surface (a new LLM vendor through the one seam) and is UI-independent, build and test it **in parallel with US1** even though it's P2 — it de-risks the headline requirement without blocking the MVP.

---

## Notes

- `[P]` = different files, no incomplete dependency. All `server/routers/ensemble.py` edits are mutually sequential.
- Every backend choice is a CLI flag first (Principle VI); the UI only sets it.
- Drafts only; `POST /promote` is the sole live-doc writer (Principle I).
- Gates block auto-advance (Principle II); files are the interchange (Principle IX).
- Commit after each task or logical group; stop at any checkpoint to validate a story independently.

---

## Remediation Log (from `/speckit-analyze`)

MEDIUM findings resolved into tasks (suffixed IDs avoid renumbering):

| Finding | Decision | Task(s) |
|---|---|---|
| M1 — `threads.md` had no producer | B: dedicated endpoint | T013a |
| M2 — Setup UI lacked known-names/aliases inputs | A: add to Setup | T014 (expanded) |
| M3 — empty-output trap on OpenRouter path | A: prevention + detection | T020 (prevention), T027a (detection) |
| M4 — no concurrent-run guard | A: server-side lock | T010a |
| M5 — backend-retry-without-loss untested | A: integration test | T019a |

LOW findings (A1, L1–L4, C1) were accepted as-is; see the analysis report. C1 (the pre-existing `ensemble_merge.py` embedding client outside the seam) is explicitly **not** extended by this feature — OpenRouter chat goes only through `campaignlib/api`.

---

## Post-implement enhancement — chapter picker (operator request)

The single chapters-glob text field was too blunt: the operator needs to **select
all / select one / pick a subset / sort** the chapters before extraction, not just
type a glob. Resolved additively, CLI-first:

| Layer | Change |
|---|---|
| Engine | `ensemble_batch.py --chapters` now `nargs="+"` — unions one or more globs/paths, de-dupes, sorts. Single-glob callers unchanged (Principle VI: the engine gains the capability). |
| API | `GET /api/ensemble/chapters?glob=…` resolves globs → sorted file list with a disk-derived `extracted` flag (Principle I); `GET /run/extract` `chapters` is now a list (select-all = the glob, subset = the picked paths). |
| Config | `EnsembleSection.chapters_selected: list[str]` — the explicit chosen set; empty == nothing selected. No secrets. |
| UI | New `ChapterPicker.vue` (glob + Resolve, Select all / Select none / "only", natural sort ▲▼, per-chapter `extracted`/`pending` badge) wired into both Setup and Extract. |
| Tests | `test_ensemble_chapters.py` (resolution, multi-glob union/dedupe, empty, workspace-confinement, **empty-selection refusal**), `test_ensemble_batch_chapters.py` (nargs contract). +7 passing, zero regressions. |

### Constitution amendment — Principle X (operator-elevated)

The operator ruled, as a matter of UX design, that **"there is no 'select all' that isn't explicit."** This was elevated to the constitution as **Principle X — Selection is Explicit; There is No Silent "All"** (v1.1.0 → **1.2.0**, MINOR). The chapter picker is now its concrete clause:

- `chapters_selected == []` means *nothing selected* — it no longer falls back to the glob.
- `GET /api/ensemble/run/extract` **refuses** an empty selection (SSE error, returncode 1) instead of expanding to "all"; the Run button is disabled until ≥1 chapter is picked.
- "Select all" **materializes** every resolved path into `chapters_selected` — it is a deliberate act, not a default.
- The CLI engine (`ensemble_batch.py`) is exempt: a glob typed at the CLI is itself explicit. The UI must never manufacture that act for the human.
