---

description: "Task list for Model Selection Resolution"
---

# Tasks: Model Selection Resolution

**Input**: Design documents from `/specs/003-model-selection-resolution/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md — all present

**Tests**: Targeted, not blanket TDD. Three kinds of test task appear below and each is load-bearing rather than ceremonial: (a) the **reversal** of three tests that assert behaviour this feature deliberately changes (research.md R8), (b) a **structural guard** against the cross-service read that caused the defect, mirroring the existing `tests/test_retrieve_render_isolation.py` precedent, and (c) **characterization** of the 22 endpoints, since "the backend reaches every router" is otherwise unprovable. Tests that merely restate a schema are not included.

**Organization**: By user story, so each is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 / US2 / US3 — user story phases only
- Paths are repo-relative, per plan.md's source tree

**Working tree**: branch `003-model-selection-resolution`, worktree at `/home/kroussos/src/CampaignGenerator-003-model-selection-resolution`.

---

## Phase 1: Setup

**Purpose**: Make the worktree trustworthy to test in, and pin down what "before" looks like.

- [X] T001 Verify the editable install resolves to **this worktree** and not the main checkout: run `python -c "import campaignlib, server; print(campaignlib.__file__, server.__file__)"` and confirm both paths start with the worktree root. If they point at `/home/kroussos/src/CampaignGenerator`, re-install with `uv pip install -e . --python "$VIRTUAL_ENV/bin/python"` from the worktree. **A green test run in a worktree whose imports resolve to main proves nothing** — do not proceed past this task until the paths are correct.
- [X] T002 [P] Add `tests/test_selection_characterization.py` recording today's behaviour for all 22 token-spending endpoints (15 `/run/*` + 6 session-editor + 1 connections): for each, assert whether the built command carries `--model` and `--backend`. This is a snapshot of the defect, not a spec — it will be inverted in Phase 3 and deleted in Phase 6. It exists so SC-001 ("100% of endpoints honour the backend", today 2 of 6 routers) is measurable rather than asserted.

**Checkpoint**: Imports verified against the worktree; the "before" state is captured in a runnable form.

> **T001 deviation — did NOT re-install.** The `.pth` does hardcode the main checkout, and from a
> neutral CWD `import campaignlib` resolves to `/home/kroussos/src/CampaignGenerator`. But the
> server is **live** (pid 39635, serving out-of-the-abyss) under that same `~/.venv`, so
> re-installing editable from this worktree would silently re-point a running system's imports at
> this branch. Instead: run pytest from the worktree root, where CWD precedence puts the worktree
> first — verified, and the full-suite failure set matches main exactly (7 failed / 5 errors, all
> environmental: missing `dgxlib`, unconfigured `fivetools_data`, live MemPalace).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the single seam and the platform field. Every user story calls into this.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete. All five resolution sites (research.md R1) are replaced from here.

- [X] T003 Define the `ModelSelection` shape (`backend: str | None`, `model: str | None`, both defaulting to `None`, `extra="forbid"`) in `server/platform_config_shared.py`, per data-model.md § *Entity: ModelSelection*. An empty selection MUST be indistinguishable from an absent one.
- [X] T004 [P] Implement `compatible(model, backend) -> bool` in `server/platform_config_shared.py` per the table in `contracts/resolution.md` § *Compatibility predicate*: `anthropic`/`claude-code` require a `claude-` prefix, `dgx` forbids it, `openrouter` requires a `/`. Carry forward the rationale comment from `server/routers/ensemble.py:160-166` verbatim — membership of `server/config.py`'s `MODELS` is explicitly **not** the test, because that list is a hand-maintained snapshot and would reject a legitimate new Claude id the day it ships.
- [X] T005 Add `default_backend: Literal["anthropic","dgx","openrouter","claude-code"] = "anthropic"` to `PlatformRuntime` in `server/platform_config_shared.py:109`. Default `anthropic` reproduces today's effective behaviour (`backend_cli_args` returns `[]` for anthropic — `server/backend_forwarding.py:32`). Note `PlatformRuntime` is `extra="forbid"`, so T008's migration is mandatory, not optional.
- [X] T006 Implement `resolve_selection(request_model, request_backend, service, platform) -> ResolvedSelection` in `server/platform_config_service.py`, replacing `resolve_default_model` (`:137`). Implements the one rule from data-model.md, including **the pairing rule**: model and backend come from the same tier when that tier supplies either. Returns `model_origin`/`backend_origin` and a `refusal` when `compatible()` is false. Never substitutes (FR-011).
- [X] T007 Define the refusal path: an `IncompatibleSelection` exception in `server/platform_config_service.py` and a FastAPI handler in `server/main.py` rendering the **409 Conflict** body from `contracts/resolution.md` § *Refusal* — including `service` and `remedy: "clear_override"`, which are what let T042 offer the fix at the point of refusal. 409 not 400: the request is well-formed; the stored state conflicts.
- [X] T008 Extend `server/migrate_platform_config.py` to copy `session_doc.yaml`'s `backends.active` into `platform.yaml`'s `runtime.default_backend`. Per data-model.md § *Migration*: **leave `session_doc.yaml`'s `backends` block intact** — it remains the Session Doc Editor's own override under the new rule; only its role as the app-wide value moves. Single-user deployment: migrate and delete, no dual-location probe.
- [X] T009 Accept `default_backend` in `PUT /api/config/runtime` (`server/routers/config_routes.py`), validating against the four literals (unknown → 422). This becomes the **only** write path for the app-wide backend.
- [X] T010 [P] Extend `GET /api/models` (`server/routers/config_routes.py:136`) to return `backends` and `default_backend` alongside `models`/`default`, per `contracts/api.md` § 1. Keep `models` Anthropic-specific — DGX and OpenRouter ids are free-form and not enumerable from this repo.

**Checkpoint**: One resolver exists and is callable. Nothing uses it yet. `python -m pytest tests/` still passes — the old sites are untouched. ✅ Verified: 1746 passed, same 7 failed / 5 errors as baseline.

> **T008 deviation — new file, not an extension.** The task said to extend
> `server/migrate_platform_config.py`, but that script's input is `ui_state.yaml`, which
> `docs/config/ui-state-retirement.md` deleted. Bolting a session_doc→platform copy onto a CLI
> whose own source file no longer exists would leave one script with two premises, one dead. Wrote
> `server/migrate_default_backend.py` instead — same idempotence contract, verified end to end
> (dry-run → apply → no-op re-run, with `session_doc.yaml`'s `backends` block preserved).

---

## Phase 3: User Story 1 — The platform choice reaches every run (Priority: P1) 🎯 MVP

**Goal**: The operator's model and backend picks reach all 22 endpoints. Selecting a local backend stops billing the metered API on four routers that silently ignore it today.

**Independent Test**: Set each backend in turn; run one action per router; confirm every persisted command in `logs/` carries the selected `--backend` and exactly one `--model`. Fully testable with no override mechanism existing (quickstart V1, V2).

**Why this is the MVP**: it is the money bug. Four routers spend metered tokens after the operator chose local hardware, and nothing reports it.

### Implementation for User Story 1

- [X] T011 [US1] Delete `_backend_flags` from `server/routers/grounding.py:72` — its `SessionEditorConfigService` construction is FR-005's violation and the cause of the two-owner command (research.md R2). Route its five endpoints (`:202`, `:238`, `:295`, `:348`, `:386`) through `resolve_selection`, emitting exactly one `--model` and one `--backend`.
- [X] T012 [P] [US1] Replace `_backend_args` in `server/routers/ensemble.py:117` with a `resolve_selection` call across all five endpoints (extract, bundle, recent-events, threads, synthesize). **Drop the inline `claude-` guard at `:170`** — its rule now lives in `compatible()` (T004) and its silent-substitution behaviour is what FR-011 forbids. Keep the per-stage service tier: `ensemble.yaml`'s `EnsembleBackend` is passed as `service`.
- [X] T013 [P] [US1] Replace `_model_args` in `server/routers/scene_editor.py:554` with a `resolve_selection` call across **all six** session-editor token-spending endpoints — `/enhance`, `/extract`, `/narrate/{n}`, `/scrub/{n}`, `/scrub-all`, `/plan` — passing the active `BackendProfile` as `service`. Note `_model_args` has 7 call sites and `_backend_flags` 6, across `_build_enhance_cmd`, `_build_reextract_cmd`, `_build_narrate_cmd`, `_build_consistency_cmd`, `_build_plan_cmd` and the four `api_*` handlers; every one must route through the seam. Preserve the existing exclusion noted at `:563-566` — scrub passes `--model` through as an OpenAI-compat override, so the resolved pair must not be double-applied.
- [X] T014 [P] [US1] Route `server/routers/prep.py` (`:60`, `:85`, `:117` — session-prep, npc-table, query) through `resolve_selection` with `service=None`, and **add `--backend` forwarding, which these endpoints have never emitted**. This is one of the four routers that silently bills the metered API today.
- [X] T015 [P] [US1] Route `server/routers/setup.py` (`:42`/`:55`, `:71`/`:78` — dnd-sheet, make-tracking) through `resolve_selection` with `service=None`, adding `--backend` forwarding. Remove the now-redundant double assignment (`model = resolve_default_model(...)` then `cmd += ["--model", model]`).
- [X] T016 [P] [US1] Route `server/routers/connections.py:452` through `resolve_selection` with `service=None`. This one calls `stream_api` in-process rather than shelling out, so the resolved backend must reach `make_client`/`stream_api` as arguments rather than CLI flags — verify against `campaignlib/api/client.py:43`.
- [X] T017 [US1] Re-point the sidebar BACKEND toggle in `frontend/src/components/layout/AppSidebar.vue:20` (`setBackend`) from `PUT /api/editor/config` to `PUT /api/config/runtime`, and read `currentBackend` (`:16`) from `runtime.default_backend`. Update `frontend/src/stores/config.ts` to carry `default_backend` on the runtime object and stop writing the editor config for this purpose.
- [X] T018 [US1] Allow a free-text model id in the sidebar MODEL control (`AppSidebar.vue:147-152`) when the selected backend is `dgx` or `openrouter`. **Without this the platform pair cannot be made valid**: the `<select>` is populated from the Anthropic-only `MODELS` list, so choosing DGX with any listed model yields an incompatible pair and T007 would refuse every run. Keep the dropdown for `anthropic`/`claude-code`.
- [X] T019 [US1] **Reverse the three tests that assert the behaviour this feature changes** (research.md R8): `test_synthesize_ignores_stale_model_for_anthropic` (`tests/test_ensemble_gates.py:83`), `test_bundle_...` (`:107`), `test_extract_...` (`:129`). Rewrite each to assert a **409 refusal** instead of silent substitution, and rename them accordingly (e.g. `test_extract_refuses_stale_model_for_anthropic`). Update the docstring reference in `tests/test_synthesis_capable_registry.py:130`. ⚠️ **If these pass unchanged, the reversal has been silently undone** — treat that as a failure, not a pass.
- [X] T020 [US1] Invert `tests/test_selection_characterization.py` (T002): every one of the 22 endpoints must now carry the resolved `--backend` and exactly **one** `--model`. This is the executable form of SC-001 and contract guarantee C1.
- [X] T021 [P] [US1] Extend `tests/test_default_model_resolution.py` to cover the backend dimension and the pairing rule. The existing assertions must keep passing unchanged — they encode the explicit-→platform-→literal chain this feature preserves.
- [X] T022 [P] [US1] Complete `tests/test_selection_isolation.py` (T002's sibling guard): assert no router module imports another service's config service — specifically that `server/routers/grounding.py` does not import `SessionEditorConfigService`. Model it on `tests/test_retrieve_render_isolation.py`, which is the repo's precedent for a structural constitutional guard (quickstart V3, SC-009).

> **T002/T020/T048 collapsed — no throwaway characterization file.** The plan had T002 write a
> snapshot of the broken behaviour, T020 invert it, and T048 delete it. The "before" state is
> already captured with file:line evidence in research.md R1/R2, so the temporary artefact would
> have added a step without adding proof. The permanent assertions were written directly in
> `tests/test_selection_isolation.py` (51 tests: one-`--model`, backend-reaches-every-endpoint,
> platform-model-reaches-every-endpoint, refusal-on-every-endpoint, plus the structural
> no-cross-service-read guard). T048 therefore has nothing to delete.
>
> **The reversal was bigger than R8 predicted.** R8 named 3 tests; 21 needed rewriting:
> 3 in `test_ensemble_gates.py` (substitution → 409), 3 in `test_ensemble_config_defaults.py`
> (R8 missed these entirely), 10 in `test_grounding_backend.py` (they seeded the *Session Doc
> Editor* to test grounding — the cross-service read, encoded as desired behaviour), 3 in
> `test_editor_pipeline.py` + 2 in `test_editor_service_integration.py` (helper signatures), and
> 1 in `test_synthesis_capable_registry.py` (whose premise was literally the dropped model).
>
> **Two design bugs found by those tests, both fixed:**
> 1. *The pairing rule was implemented wrong.* Model and backend were resolved independently and
>    only paired for the compatibility check, so a service that picked `dgx` with no model
>    inherited the platform's *Claude* id and then got refused — turning two valid choices into a
>    manufactured conflict. Now a tier that picks a different backend does not inherit the tier
>    above's model; no `--model` is emitted and the tool's own default applies.
> 2. *The 409 only existed in `server/main.py`'s app.* Several test fixtures mount routers on a
>    bare `FastAPI()`, which got an unhandled 500 instead of a refusal. `IncompatibleSelection`
>    now subclasses `HTTPException(409)`, so it renders wherever the router is mounted with no
>    registration to forget.

**Checkpoint**: US1 is independently deliverable. The backend toggle works app-wide, no command carries two `--model` flags, and no router reads another service's config. Overrides do not exist yet — every service inherits the platform, which is correct behaviour, not a gap.

---

## Phase 4: User Story 2 — A service can deliberately override (Priority: P2)

**Goal**: The five config-owning services can each diverge from the platform default, affecting only their own runs.

**Independent Test**: Set an override on one service, leave the rest unset, run an action in each of the ten services; only the overriding one diverges (quickstart V4, V5).

**Scope note**: Exactly five services get an override — Ensemble, Session Doc Editor, Grounding, Party, Planning — because they already own a YAML document. Setup, Session Prep, NPC Table, Query and Connection Graph get **nothing**, preserving D1's "stateless by decision" ruling. **This phase must create no new config file** (FR-004); if a task seems to need one, the scope decision has been misread.

### Implementation for User Story 2

- [X] T023 [P] [US2] Add `selection: ModelSelection` to `GroundingConfig` in `server/grounding_config_shared.py:149`, defaulting to an empty selection. The document is `extra="forbid"`, so also confirm existing campaign `grounding.yaml` files still load.
- [X] T024 [P] [US2] Add `selection: ModelSelection` to the party config schema in `server/party_config_shared.py` / `server/party_config_service.py`.
- [X] T025 [P] [US2] Add `selection: ModelSelection` to the planning config schema in `server/planning_config_shared.py` / `server/planning_config_service.py`.
- [X] T026 [US2] Pass the owning service's selection into `resolve_selection` from `server/routers/grounding.py`: `grounding.yaml`'s for distill / campaign-state / build-dossiers, `party.yaml`'s for `/run/party`, `planning.yaml`'s for `/run/planning`. Three different service tiers behind one router — this is why the resolver takes `service` as a parameter rather than deriving it.
- [X] T027 [P] [US2] Re-express `EnsembleBackend` (`server/ensemble_config_shared.py:62`) in terms of the shared `ModelSelection` core, **keeping `endpoints` (plural)**. Per data-model.md, the plural/singular split is load-bearing: extract fans out across both Sparks. This is a refactor toward the shared shape, not a merge.
- [X] T028 [P] [US2] Re-express `BackendProfile` (`server/session_editor_config_shared.py:73`) in terms of the shared core, **keeping `endpoint` (singular)**. Note this model is `extra="allow"` unlike its ensemble twin — preserve that, or justify tightening it separately.
- [X] T029 [P] [US2] Add `GET`/`PUT`/`DELETE /api/grounding/selection` in `server/routers/grounding.py` per `contracts/api.md` § 2. `DELETE`, or `PUT` with both fields null, MUST restore platform inheritance (FR-013).
- [X] T030 [P] [US2] Add `GET`/`PUT`/`DELETE /api/party/selection` in `server/routers/party_routes.py`.
- [X] T031 [P] [US2] Add `GET`/`PUT`/`DELETE /api/planning/selection` in `server/routers/planning_routes.py`.
- [X] T032 [US2] Add per-service override controls to the Grounding, Party and Planning pages in `frontend/src/`, each showing the inherited platform value when unset and offering an explicit clear action.
- [X] T033 [P] [US2] Test: an override on one service changes only that service's runs, and clearing restores inheritance (SC-004, SC-007, quickstart V4/V5). New file `tests/test_service_selection_override.py`.
- [X] T034 [P] [US2] Test: **no override surface exists** for Setup, Session Prep, NPC Table, Query or Connection Graph, and no new config file was created — assert `setup.yaml` does not exist (FR-004, quickstart V10). Add to `tests/test_service_selection_override.py`.
- [X] T035 [P] [US2] Verify `tests/test_ensemble_config_defaults.py::TestModelResolution` and `tests/test_editor_service_integration.py::TestO3ModelResolution` still pass unchanged — they encode the two services whose override reach must not narrow (spec Assumptions).

**Checkpoint**: US1 and US2 both work independently. Five services can override; five cannot and correctly inherit.

---

## Phase 5: User Story 3 — See what a run will use before spending (Priority: P3)

**Goal**: Before starting a run, the operator sees the model, the backend, and where each came from — and any incompatibility is visible rather than discovered from output.

**Independent Test**: With various platform/override combinations, read each service's run surface and confirm the displayed values and origins match what the run actually uses (quickstart V8).

### Implementation for User Story 3

- [X] T036 [P] [US3] Add `GET /api/grounding/selection/resolved` returning the `ResolvedSelection` (model, backend, both origins, `compatible`, `refusal`) without starting a run, per `contracts/api.md` § 3.
- [X] T037 [P] [US3] Add the same `/selection/resolved` endpoint for party and planning in `server/routers/party_routes.py` and `server/routers/planning_routes.py`.
- [X] T038 [P] [US3] Add `/selection/resolved` for ensemble (`server/routers/ensemble.py`) and the session editor (`server/routers/scene_editor.py`). Ensemble's is per-stage, since its selection is.
- [X] T039 [P] [US3] Add `/selection/resolved` for the three inheriting routers — `server/routers/prep.py`, `server/routers/setup.py`, `server/routers/connections.py`. These always report `model_origin: "platform"`, which is exactly what the operator needs to see; omitting them would leave the four historically-silent routers still opaque.
- [X] T040 [US3] Display the resolved model, backend and origin on each service's run surface in `frontend/src/`, reading from `/selection/resolved`. Origin must be visible, not just the value — "claude-sonnet-4-6 (platform default)" vs "(this service)".
- [X] T041 [US3] Surface an incompatible selection **before** the run, on each service's run surface in `frontend/src/`, with the reason — US3 acceptance scenario 3. The Run control is disabled while incompatible, matching the decision recorded in spec Clarifications.
- [X] T042 [US3] Offer "Clear override" and "Edit" directly at the point of refusal in `frontend/src/` (the same components as T041), driven by the `service` and `remedy` fields of the 409 body (FR-010). The operator must not have to go hunting for which service holds the stale value.
- [X] T043 [P] [US3] Test: `/selection/resolved` reports correct values and origins for all ten services across platform-only, override, and incompatible states (SC-005). New file `tests/test_selection_preview.py`.

**Checkpoint**: All three user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T044 [P] Update `docs/config/service-cut.md`: gap #3 ("Duplicated backend/model selection — not closed; relocated, not unified") moves to **closed**, and the "four independently-configured selectors" language in the *Where the monolith shows* table and the *stated plainly* section is replaced with the single-seam description. This doc is cited by the spec as the feature's origin; leaving it stale would misreport the system.
- [X] T045 [P] Update `docs/config/values.md`'s `platform.yaml` section with `runtime.default_backend` — reader, writer, and the resolution chain it feeds.
- [X] T046 [P] Update `docs/config/schema.md` and `docs/config/crud.md` with the `selection` field on `grounding.yaml` / `party.yaml` / `planning.yaml` and the new `/selection` routes.
- [X] T047 Document the resolution rule once in `docs/config/values.md` (FR-015) and replace every other mention — in `docs/config/service-cut.md`, `docs/config/schema.md`, `docs/config/crud.md`, `CLAUDE.md` — with a link to it rather than a restatement. The five-way divergence this feature removes was mirrored by the same rule being described in several docs at once.
- [X] T048 Delete `tests/test_selection_characterization.py` — its inverted form (T020) is now the permanent assertion, and keeping the snapshot would freeze a description of the old behaviour.
- [X] T049 Confirm FR-014 needs no code: verify the run log at `<campaign>/logs/<timestamp>_<script>.md` already carries the resolved `--model`/`--backend` on its `command` line with no API key present (quickstart V9, research.md R7). This is inherited from `specs/002` — the task is verification, not implementation.
- [X] T050 Run the full V1–V10 suite from `specs/003-model-selection-resolution/quickstart.md` end to end against a real campaign workspace and record results in that file.
- [X] T051 Run `python -m pytest tests/` and confirm green, with `tests/test_retrieve_render_isolation.py` among the passes. Re-confirm T001's import check first — a green run whose imports resolved to the main checkout proves nothing about this branch.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup. **Blocks all user stories** — every story calls `resolve_selection`.
- **US1 (Phase 3)**: depends on Foundational. No dependency on US2 or US3.
- **US2 (Phase 4)**: depends on Foundational. Independently testable, but in practice lands after US1 since US1 wires the routers US2 feeds a service tier into.
- **US3 (Phase 5)**: depends on Foundational. Reads the same resolver; displays more when US2 exists but does not require it.
- **Polish (Phase 6)**: depends on the stories you intend to ship.

### Critical path

T006 (the seam) is the single blocking task. T004 and T005 feed it; T003 feeds T004. Everything after T007 fans out.

### Within each story

- Backend before frontend (T011–T016 before T017–T018).
- Schema before route before UI (T023–T025 → T029–T031 → T032).
- T019 must land in the same change as T012 — the ensemble tests break the moment the router stops substituting.

---

## Parallel Opportunities

**Phase 2**: T004 and T010 are parallel with the rest; T003 → T004 → T006 is the serial spine.

**Phase 3** — the six router rewrites touch six different files:

```bash
Task: "T012 ensemble.py -> resolve_selection, drop the claude- guard"
Task: "T013 scene_editor.py -> resolve_selection"
Task: "T014 prep.py -> resolve_selection + backend forwarding"
Task: "T015 setup.py -> resolve_selection + backend forwarding"
Task: "T016 connections.py -> resolve_selection (in-process, not CLI flags)"
```

T011 (grounding) is deliberately *not* in that set — it also deletes `_backend_flags`, which T026 later re-enters for the service tier.

**Phase 4** — the three schema additions are parallel, as are the three route sets:

```bash
Task: "T023 grounding.yaml selection field"
Task: "T024 party.yaml selection field"
Task: "T025 planning.yaml selection field"
```

**Phase 5**: T036–T039 are four independent routers; T043 is parallel with the frontend tasks.

**Phase 6**: T044–T046 are three separate docs.

---

## Implementation Strategy

### MVP: User Story 1 only

1. Phase 1 (Setup) — **T001 is not optional**; the worktree import trap invalidates every later test result.
2. Phase 2 (Foundational) — the seam.
3. Phase 3 (US1) — routers, sidebar, the reversal.
4. **STOP and VALIDATE**: quickstart V1, V2, V3, V7.

That alone closes the money bug (SC-006) and the cross-service leak (SC-009). Overrides can follow later without rework, because the resolver already takes a `service` parameter — US2 fills in an argument that US1 passes as `None`.

### Incremental delivery

1. Setup + Foundational → the rule exists.
2. + US1 → the platform choice reaches every run. **Shippable.**
3. + US2 → services can diverge. **Shippable.**
4. + US3 → the operator can see it before spending. **Shippable.**

### Notes

- Commit after each task or logical group.
- The three reversed tests (T019) are an intended behaviour change recorded in spec Assumptions. Do not "fix" them back to green by restoring substitution.
- `server/backend_forwarding.py` is deliberately untouched — it already separates *formatting* flags from *resolving* them, and only the resolving half is broken.
- No new config file is created by any task in this list. If one appears necessary, re-read the scope decision in spec Clarifications before writing it.

---

## Implementation status (2026-07-25)

**51 of 51 complete.** Suite at the pre-003 baseline (7 failed / 5 errors, all environmental —
missing `dgxlib`, unconfigured `fivetools_data`, live MemPalace) with **1872 passed, +128 over
baseline**. Frontend builds clean. Quickstart V1–V10 executed against a booted server; results and
evidence recorded in `quickstart.md`.

### Defects found by implementing, not predicted by planning

| Found by | Defect |
|---|---|
| Writing T013 | The endpoint count was 17; it is **22**. The Session Doc Editor has six token-spending endpoints, not two — T013 as written would have left four on the old chain (research.md R10). |
| Running the reversed tests | The pairing rule was implemented wrong: model and backend resolved independently, so a service picking `dgx` with no model inherited the platform's *Claude* id and was then refused — a conflict manufactured from two valid choices. |
| A bare-`FastAPI()` test fixture | The 409 only existed for apps built by `server/main.py`. `IncompatibleSelection` now subclasses `HTTPException`. |
| Writing T033 | `party.yaml`/`planning.yaml` round-tripped `selection` to nothing — loader *and* saver hand-build their dicts, so a new field is dropped unless named in both. PUT returned 200, GET came back empty. |
| The T043 preview sweep | Ensemble never honoured the platform backend. `EnsembleBackend.backend` defaults to the literal `"anthropic"` and `_backend_args` passed it as the *request* tier, pinning every unconfigured stage to Anthropic — a direct FR-008 violation. |
| **Running V10 live** | The migration moved the backend but not the model, leaving a local backend paired with the Anthropic default. Seven of eight services reported `compatible: false`; a working DGX campaign would have been wholly blocked. The unit test passed throughout — it asserted the migration did what it was written to do, and it did; the specification was wrong. |

The reversal was also 7× larger than research.md R8 predicted: **21 tests**, not 3.

### Deviations from the task list, all deliberate

- **T001** — did *not* re-install the editable package. The `.pth` hardcodes the main checkout and
  the live server (pid 39635, out-of-the-abyss) runs under that same venv, so re-installing would
  have re-pointed a running system at this branch. Ran pytest from the worktree root instead, where
  CWD precedence resolves correctly; the failure set matches `main` exactly.
- **T002/T020/T048** — collapsed. The throwaway characterization file would have added a step
  without adding proof; the "before" state is already captured with file:line evidence in
  research.md R1/R2. Permanent assertions were written directly.
- **T008** — new CLI (`server/migrate_default_backend.py`) rather than extending
  `migrate_platform_config.py`, whose `ui_state.yaml` input no longer exists.
- **T050** — run against a scratch campaign, not a live one, and the subprocess it spawned resolved
  to the main checkout's console script (the same `.pth` shadowing). The command the *router built*
  is branch code and is what V1/V2 assert; the script that ran it is not.
