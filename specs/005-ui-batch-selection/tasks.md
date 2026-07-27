# Tasks: Batch as a UI Selection Option

**Input**: Design documents from `/specs/005-ui-batch-selection/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included. The contracts specify enforced invariants (no router emits `--batch`; batch never silently dropped) and this feature edits the resolution seam every service depends on, so regression cover is not optional here.

**Organization**: Grouped by user story — US1 (P1, batch reachable and discounted), US2 (P2, one rule everywhere), US3 (P2, honoured or refused).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable (different files, no dependency on an incomplete task)
- Repo conventions apply throughout: worktree on branch `005-ui-batch-selection`; `cd <worktree> && env -u PYTHONPATH ~/.venvs/main/bin/python -m pytest -q`; never commit to main.

## Which services may *set* a selection (established during planning)

Feature 003 split services into two classes, and this feature must preserve the split:

| Class | Services | Batch control |
|---|---|---|
| **Settable** (has `PUT /api/{svc}/selection`) | grounding, party, planning, editor; ensemble via its own per-stage config | Displays **and** sets batch |
| **Inheriting** (preview only, no write endpoint — 003 FR-004) | setup, prep | Displays inherited batch, read-only — **must not gain a write endpoint** |
| **Excluded** (FR-013) | connections | No batch anywhere; preview omits the fields |

---

## Phase 1: Setup

- [X] T001 Create worktree + branch `005-ui-batch-selection` off `main`; copy gitignored `config/wiring.yaml` from the main checkout into the worktree

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: A trustworthy guardrail, then the resolution seam every story consumes.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 Fix the broken route-table assertions in `tests/test_service_selection_override.py::test_inheriting_services_have_no_selection_endpoint` (currently 3 failing parametrizations). Root cause found during planning: routers mount as `_IncludedRouter` objects, so `{getattr(r,"path",None) for r in app.routes}` never contains flattened paths like `/api/prep/selection/resolved`. Both assertions are therefore wrong — the "preview exists" half fails despite the endpoint working (verified: returns 200 JSON), and the "no write endpoint" half passes **vacuously** and would not catch a violation. Rewrite to enumerate real paths (`app.openapi()["paths"]`, or recurse `_IncludedRouter` children, or probe with `TestClient` and assert on content-type to defeat the SPA catch-all). This guard must genuinely work before this feature edits selection endpoints.
- [X] T003 Add `batch: bool = False` and `batch_origin: str = "platform"` to `ResolvedSelection` in `server/platform_config_service.py`, including `as_dict()`, per `contracts/selection-api.md`
- [X] T004 Implement batch tier resolution in `resolve_selection()` (`server/platform_config_service.py`): precedence request → service → platform, matching backend; the model/backend pairing rule does **not** extend to batch (research D2)
- [X] T005 Implement batch refusal in `resolve_selection()`: when `batch` resolves true but the resolved backend is not `anthropic` (or the service's capability is `incompatible`), populate the **existing** `refusal` with a message naming batch as the cause, so `compatible` becomes false — run routes raise `incompatible_selection`, preview routes return it. No downgrade path exists (FR-006). Origin-independent (research D3).
- [X] T006 Emit `--batch` from `selection_cli_args()` in `server/platform_config_service.py` when `resolved.batch` is true — the only place the flag is ever built
- [X] T007 Add `default_batch: bool = False` to the platform runtime schema in `server/platform_config_shared.py` and its write path
- [X] T008 [P] Add the static per-service batch capability map (`full` / `degraded` / `incompatible` / `excluded`) per `data-model.md`, in `server/platform_config_service.py` alongside the resolver that consumes it
- [X] T009 [P] Resolution tests in `tests/test_platform_config_service.py` (or the nearest existing selection test module): precedence across all three tiers; `null` service value defers while `false` does not; batch true + anthropic is compatible; batch true + dgx/openrouter/claude-code refuses with a batch-naming message; refusal is identical whether batch came from service or platform
- [X] T010 [P] Guardrail test (mirroring spec 004's `messages.batches` grep guard): no module under `server/routers/` appends `"--batch"` or reads a batch setting directly — every occurrence must originate in `selection_cli_args`

**Checkpoint**: resolution + flag emission correct and covered; the FR-004 guard actually guards.

---

## Phase 3: User Story 1 — Choose batch for a run from the page that runs it (Priority: P1) 🎯 MVP

**Goal**: On a settable service page, turn batch on, run, and have the work execute at the batch rate with the same artifact.

**Independent Test**: quickstart §1 — on Distill World State, batch on → run → streamed output opens with `Batch submitted: …`, progress lines follow, normal draft artifact appears, billing shows the batch rate.

- [ ] T011 [US1] Add `batch: bool | null` to the per-service selection store schema (the model/backend selection shape in `server/platform_config_shared.py`), where `null` means defer to platform
- [ ] T012 [US1] Accept and persist `batch` on `PUT /api/{service}/selection` for the settable services (grounding, party, planning, editor) — stored even when currently unsatisfiable, so the operator's intent stays visible and fixable (`contracts/selection-api.md`)
- [ ] T013 [US1] Include `batch` and `batch_origin` in every settable service's `GET /api/{service}/selection/resolved` payload
- [ ] T014 [US1] Add the batch control to `frontend/src/components/shared/SelectionPanel.vue`: effective state, origin label using the existing origin vocabulary, and the shipped copy *"Use Anthropic Message Batches (50% off list price; replaces streaming with poll-progress)"*
- [ ] T015 [P] [US1] Server tests: `--batch` appears in the built command for a grounding run when batch resolves true, and is absent when false (`tests/test_grounding_*.py` or nearest)
- [ ] T016 [P] [US1] Frontend gate: `cd frontend && npm run build` passes with the new control

**Checkpoint**: the P1 cost saving is reachable from at least one page, end to end.

---

## Phase 4: User Story 2 — One batch choice, resolved by the same rule everywhere (Priority: P2)

**Goal**: Set batch once app-wide; every service inherits it; services that can override do; every page shows the value and its origin before running.

**Independent Test**: quickstart §2–§3 — batch on app-wide shows as inherited on every in-scope page; overriding one service changes only that service; app-wide changes don't disturb the overrider.

- [ ] T017 [US2] Add the app-wide batch control to `frontend/src/components/layout/AppSidebar.vue` alongside the existing model and backend pickers, writing the platform tier through the existing app-wide write path
- [ ] T018 [P] [US2] Surface batch state on the **inheriting** services' previews (`server/routers/prep.py`, `server/routers/setup.py`) — read-only display only. **Do not add a `PUT /selection` route to either** (003 FR-004; T002's guard now enforces this)
- [ ] T019 [P] [US2] Render the inherited batch value read-only wherever `SelectionPanel` appears on an inheriting service's page, so the operator can see it without being offered a control that cannot exist
- [ ] T020 [US2] Add per-stage `batch` to the ensemble tier: schema in `server/ensemble_config_shared.py` (`extract` / `synthesize`), passed through the existing `resolve_selection(service=…)` call in `server/routers/ensemble.py`
- [ ] T021 [US2] Add the per-stage batch control to `frontend/src/views/ensemble/EnsembleSetup.vue` and the config plumbing in `frontend/src/views/ensemble/useEnsembleRun.ts`
- [ ] T022 [P] [US2] Tests: `--batch` forwarded on the ensemble run routes per stage (`tests/test_ensemble_gates.py`); inheriting-service previews expose batch without exposing a write path
- [ ] T023 [P] [US2] Store `config.ts` platform batch state in `frontend/src/stores/config.ts` and confirm the sidebar↔page round trip

**Checkpoint**: SC-002 met for every in-scope surface; origin visible everywhere.

---

## Phase 5: User Story 3 — Honoured or refused, never silently downgraded (Priority: P2)

**Goal**: A batch selection that cannot be honoured refuses the run with a stated reason and a remedy — it never runs at full price.

**Independent Test**: quickstart §4 — batch + a non-Claude backend blocks the Run button with a batch-naming reason; attempting the run anyway fails with `incompatible_selection`; the offered remedy restores the run; identical behaviour whether batch was inherited or overridden.

- [ ] T024 [US3] Ensure the batch refusal renders through the existing refusal block in `frontend/src/components/shared/SelectionPanel.vue` (reason + `compatible` emit that disables the parent's Run button) with no new UI mechanism
- [ ] T025 [US3] Extend the existing refusal remedy actions in `SelectionPanel.vue` to offer clearing the batch selection (alongside the existing clear-override remedy), per FR-006a
- [ ] T026 [US3] Add the degradation notice for `degraded`-capability services (session prep, sd_narrate): state before the run that steps run one at a time — slower for the same discount (FR-010)
- [ ] T027 [P] [US3] Tests: a run route with batch + a non-anthropic backend raises `incompatible_selection` and spawns **no subprocess**; the refusal message names batch; the same holds for platform-inherited batch
- [ ] T028 [P] [US3] Test that no code path exists which strips batch and runs anyway — assert `selection_cli_args` emits `--batch` for every compatible batch-true selection, and that no route builds a command from a batch-true-but-incompatible selection

**Checkpoint**: SC-004 met — no run can execute at full price after batch was selected.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T029 Retire the bespoke batch control (FR-011): remove `useBatch` and the `?batch=1` URL construction from `frontend/src/views/session/SessionDocEditor.vue`, the checkbox from `frontend/src/components/scene-editor/KnobDrawer.vue`, and the `batch` query parameter from the extract/enhance routes in `server/routers/scene_editor.py` — those runs now take batch from the resolved selection. Verify the two stages behave exactly as they did before (research D6).
- [ ] T030 [P] Add the `batch: bool` forwarding parameter to `backend_cli_args` in `server/backend_forwarding.py` **only if** an implementation need appears; otherwise update its spec-004 NOTE to record that batch joins at `selection_cli_args` instead. Do not leave the NOTE stale.
- [ ] T031 [P] Docs: document the UI batch control in `docs/web/web_ui.md` (where it appears, tiering, refusal + remedy, degraded services, the Connection Graph exclusion and why)
- [ ] T032 Full gate from the worktree: `env -u PYTHONPATH ~/.venvs/main/bin/python -m pytest -q` (the 3 `test_service_selection_override` failures must now be **fixed**, not tolerated — T002) plus `cd frontend && npm run build`; then run quickstart §1–§8 against a live campaign and record results in the PR body

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (T001)**: none
- **Foundational (T002–T010)**: after T001 — **blocks all stories**. Internal order: T002 first (a broken guard must not be trusted while editing what it guards) → T003 → T004/T005 → T006/T007/T008 → T009/T010
- **US1 (T011–T016)**: after Phase 2. T011 → T012/T013 → T014; T015/T016 parallel after
- **US2 (T017–T023)**: after Phase 2; independent of US1 except that T014's control is what T019 renders read-only. T018/T019/T022/T023 parallel; T020 → T021
- **US3 (T024–T028)**: after Phase 2 for the server half (T027/T028), after T014 for the display half (T024/T025)
- **Polish (T029–T032)**: T029 after US1+US2 (the unified control must exist before the bespoke one is removed); T032 last

### Parallel Opportunities

- Phase 2: T008, T009, T010 after T006
- US1: T015, T016 after T014
- US2: T018, T019, T022, T023 in one wave — the widest fan-out
- US3: T027, T028 (server) in parallel with T024–T026 (frontend)

### Parallel Example: User Story 2

```bash
Task: "T018 inheriting-service previews expose batch (prep, setup) — no write route"
Task: "T019 read-only batch rendering on inheriting-service pages"
Task: "T022 ensemble per-stage --batch forwarding tests"
Task: "T023 platform batch state in the config store"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 + Phase 2 (guard fixed, resolution + flags correct)
2. Phase 3 (US1) → **STOP and VALIDATE**: quickstart §1 with a real `distill` run; confirm batch-rate billing
3. That alone makes the saving reachable from the UI

### Incremental Delivery

1. US1 → validate → PR-able MVP
2. US2 → uniformity across every surface → SC-002/SC-003
3. US3 → refusal semantics → SC-004
4. Polish → migration + docs + full gate → PR; merge only on explicit go-ahead

### Notes

- Constitution gates riding along: T006+T010 (V — one seam, one flag emitter), T024 (VI — no batch logic in the frontend), T005+T028 (I — no silent full-price run, the *Optimistic Lies* clause applied to money)
- FR-011 regression bar: with batch off, every run behaves exactly as today — T032 enforces
- T002 is not housekeeping. It is a prerequisite: this feature edits selection endpoints, and the guard that is supposed to stop an inheriting service gaining a write endpoint currently cannot fail.
