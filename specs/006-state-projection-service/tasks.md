---

description: "Task list for 006-state-projection-service"
---

# Tasks: State-Projection Rendering as its own service

**Input**: Design documents from `/specs/006-state-projection-service/`

**Prerequisites**: plan.md, spec.md, research.md (D1–D15), data-model.md, contracts/, quickstart.md

**Tests**: INCLUDED. The plan names five test files as deliverables, and research D9 lists the
enforcement tests that gate this work. Guard tests here are not optional extras — `test_layering`,
`test_config_location` and the no-literals guard are what stop the defects this feature closes from
returning.

**Organization**: Grouped by user story. Each story is independently testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1–US4 from spec.md
- Exact file paths in every description

## Path Conventions

Web app over a CLI engine (plan.md → Structure Decision): `campaignlib/` (shared models),
`pipelines/grounding/` (engine), `server/` (routers + service), `frontend/src/views/grounding/`
(page), `tests/` at repo root.

---

## Phase 1: Setup

**Purpose**: Establish the baseline this feature is measured against, and rule out the one
environment trap that makes a green run meaningless.

- [X] T001 Verify the editable install resolves to this worktree: `python -c "import campaignlib; print(campaignlib.__file__)"` must print a path under `CampaignGenerator-phase1`, not `CampaignGenerator` (research: Environment notes)
- [X] T002 Capture the pre-change baseline in `~/out-of-the-abyss/out-of-the-abyss`: `grounding_sections list --doc campaign_state` and `--doc planning` to `/tmp/before_list.txt`, and `sha256sum docs/*_draft.md > /tmp/before.sha` (quickstart §2, §3)
- [X] T003 [P] Record the current full-suite result as the regression baseline: `python -m pytest tests/ -q | tail -5`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The config document every story reads. Nothing else can start until this exists.

**⚠️ CRITICAL**: US1, US3 and US4 all consume `ProjectionConfig`.

- [X] T004 Create `campaignlib/projection_config.py` with `PROJECTION_CONFIG_FILENAME = "projections.yaml"`, strict (`extra="forbid"`) pydantic models `ProjectionStores`, `ProjectionInputs`, `ProjectionOutput`, `ProjectionConfig` (with `selection: ModelSelection`), and `load_projection_config` / `save_projection_config` (atomic via `campaignlib.util.atomic_write_text`), modelled field-for-field on `campaignlib/planning_config.py` — fields per data-model.md §1
- [X] T005 Add the `output.draft` validator to `campaignlib/projection_config.py`: the value must contain `{doc}` or raise (data-model.md §1 validation rule 2)
- [X] T006 [P] Write `tests/test_projection_config.py`: unknown key → `ValidationError`; missing/empty file → all-defaults; malformed YAML → `ValueError`; paths round-trip as authored; `output.draft` without `{doc}` rejected
- [X] T007 Add the D6 guard to `tests/test_projection_config.py`: assert `ProjectionConfig` has **no** `corpus` field and **no** `sections`/`specs` field anywhere, so a later "completion" of the schema fails loudly (research D6 → FR-013; FR-014 keeps the section map in code)
- [X] T008 Add `"projections.yaml"` to `CONFIG_FILENAMES` in `tests/test_config_location.py` and confirm the suite stays green — proof the new document has exactly one declared location
- [X] T009 Confirm `python -m pytest tests/test_layering.py` passes with the new module — `campaignlib` may not import `server` (research D5)

**Checkpoint**: The document exists and is enforced. Stories can begin.

---

## Phase 3: User Story 1 — Run every rendering service without losing work (P1) 🎯 MVP

**Goal**: The three rendering services write to separate directories, so running one never destroys
another's output.

**Independent Test**: Produce documents with each service in turn, in any order; every document
produced by the other two is byte-identical afterwards (SC-001).

### Tests for User Story 1

- [X] T010 [P] [US1] Write `tests/test_projection_isolation.py::test_run_leaves_other_services_untouched`: build a fixture campaign with drafts from all three services, run State Projection, assert the other two services' drafts and `grounding.yaml`/`ensemble.yaml` are byte-identical
- [X] T011 [US1] Add `tests/test_projection_isolation.py::test_legacy_draft_gate`: with a pre-move `docs/<doc>_draft.md` present, `grounding_sections build --doc <doc>` exits non-zero, names the file, and **does not move or delete it**; after the file is removed the build proceeds (FR-007b)

### Implementation for User Story 1

- [X] T012 [US1] In `pipelines/grounding/grounding_sections.py`, replace the `SECTIONS_DIR` module constant and the inline `Path(f"docs/{args.doc}_draft.md")` in `main()` with values resolved from `output.sections_dir` and `output.draft` (contracts/cli.md)
- [X] T013 [US1] Implement the legacy-draft gate in `pipelines/grounding/grounding_sections.py`: before writing a draft, `stat` the resolved `output.legacy_draft` for that doc and exit non-zero with the message in contracts/cli.md if present
- [X] T014 [US1] Declare `drafts_dir: str = "docs/ensemble/drafts"` on `EnsemblePaths` in `server/ensemble_config_shared.py`, and have the draft half of the `GROUNDING_DOCS` map in `server/routers/ensemble.py:66-69` compose from `resolved().paths.drafts_dir` at the route edge. **Do not put the literal in the router** — `"docs/ensemble"` is in `TestNoDrift.FORBIDDEN` (`tests/test_ensemble_config_defaults.py:92-96`, a substring scan of every router line) and the repo rule in `CLAUDE.md` forbids default literals there (research D13)
- [X] T015 [US1] Re-point the auto-stage in `pipelines/grounding/campaign_state.py:130` at Dossier Synthesis's new draft location so it keeps reading a real file (FR-007a) — this is the one place US1 touches Per-Tool Rendering
- [X] T016 [US1] Clear the legacy gate first (quickstart §2 — move the pre-move drafts aside), then run quickstart §4 against `~/out-of-the-abyss/out-of-the-abyss`: `sha256sum -c /tmp/before.sha` passes and new output appears only under `docs/projections/`. The gate fires on a no-op build too — `main()` assembles unconditionally unless `--no-assemble` — so the order matters

**Checkpoint**: The three services no longer collide. US1 is demonstrable on its own.

---

## Phase 4: User Story 2 — Extract once, render twice (P2)

**Goal**: Both renderers consume the shared service's output; neither requires the other to have run.

**Independent Test**: From a state where only extraction and bundling have run, each renderer
completes and produces its documents (SC-003).

### Tests for User Story 2

- [X] T017 [P] [US2] Write `tests/test_fact_record_contract.py`: assert every key `event_spine.rows_from_corpus` and `thread_registry` propose read (`type`, `fact`, `subject`, `scene_index`, `quote_offset`, `source_quote`, `quote_verified`, `source`) is present in a fixture emitted by `ensemble_merge`, and that a matching `type` yields a row — an upstream rename must fail here, not shrink the spine (research D3, FR-004, SC-010)
- [X] T018 [US2] Add `tests/test_projection_isolation.py::test_no_cross_service_config_read`: no module under `pipelines/grounding/` imports `EnsembleConfig` or `GroundingConfig` (FR-003)
- [X] T019 [P] [US2] Add a dossier-absent case to `tests/test_grounding_sections.py`: with no `merged_dossiers/` and no `state_dossiers/`, `build --doc world_state --backend …` skips all four synthesis sections with `no dossiers matched` and exits zero

### Implementation for User Story 2

- [X] T020 [US2] In `pipelines/grounding/grounding_sections.py`, resolve the dossier directory from `inputs.dossiers`, falling back to `inputs.dossiers_fallback`, replacing the hardcoded fallback in `outlook_inputs` (`:267`)
- [X] T021 [US2] Report which dossier set was used in the `list` and `build` output and in the section body's provenance line — silent fallback is the failure this fixes (FR-024a; Phandalin runs entirely on the fallback)
- [X] T022 [US2] Run quickstart §6 against `~/Phandalin/Phandalin` and confirm the fallback is used *and named*

**Checkpoint**: Either renderer runs from the shared state alone, and which dossier set fed a section is visible.

---

## Phase 5: User Story 3 — Change where things live without editing code (P2)

**Goal**: Every location the service reads or writes is declared once and honoured by every consumer.

**Independent Test**: Redirect one store in configuration; both the freshness check and the render
follow it together (SC-005).

### Tests for User Story 3

- [X] T023 [P] [US3] Add `tests/test_projection_isolation.py::test_no_docs_literals`: no `docs/`-shaped or `summaries`-shaped string literal survives in `grounding_sections.py`, `event_spine.py`, `thread_registry.py`, `build_recent_events.py` (the `tests/test_ensemble_config_defaults.py` shape)
- [X] T024 [US3] Add `tests/test_projection_isolation.py::test_redirected_store_is_honoured_by_hash_and_read`: point `stores.events` at a copy, assert the section goes **stale** and re-renders — the regression test for the three-site split (research D1, FR-009)

### Implementation for User Story 3

- [X] T025 [US3] Add config resolution to `pipelines/grounding/event_spine.py`: load once in `main()` via `config_path(Path.cwd(), PROJECTION_CONFIG_FILENAME)`; `--store` and `--output` become `default=None` resolving to `stores.events` / `output.recent_events`; **`--corpus` stays `required=True`** (research D6, D14)
- [X] T026 [P] [US3] Same conversion in `pipelines/grounding/thread_registry.py`: `--registry` → `stores.thread_registry`, `--out` → `stores.thread_proposals`; `--corpus` stays required
- [X] T027 [US3] In `pipelines/grounding/grounding_sections.py`, resolve `stores.events` **once** and thread it through `section_inputs` (`:116`), `render_spine` (`:150`) and `render_tracking` (`:355`) so the hash input and the read cannot diverge
- [X] T028 [US3] Replace the remaining literals in `pipelines/grounding/grounding_sections.py` with config lookups: `stores.thread_registry` (`:118`), `stores.thread_proposals` (SPECS `:98`), `stores.tracking` (`:124`), `inputs.narrative_importance` (`:254`), and the `SPECS` `source=` paths (`:87`, `:101`, `:104`) → `inputs.{party,planning_notes,speculations}`. **`SPECS`'s section list stays in code** (FR-014)
- [X] T029 [US3] Convert `pipelines/grounding/build_recent_events.py` to resolve `--output`/`--window`/`--store` from `output.recent_events`, `output.recent_events_window` and `stores.events` (research D15)
- [X] T030 [US3] Delete `recent_events_out` from `EnsemblePaths` and `recent_events_window` from `EnsembleTuning` in `server/ensemble_config_shared.py`, **with no compatibility shim**, and ensure the resulting load error names the offending key so the GM knows what to delete (research D15)
- [X] T031 [US3] Remove the recent-events route and its argv builder from `server/routers/ensemble.py`, and its control from the ensemble Vue page **including the typed `recent_events_out`/`recent_events_window` fields in `frontend/src/views/ensemble/useEnsembleRun.ts`** (otherwise `vue-tsc` fails later, in a different story). Recent-events is CLI-only until T037 restores a route under `/api/projections` — a deliberate one-story gap, single user
- [X] T032 [US3] Update the ensemble guard tests alongside T030/T031, or T048's "zero new failures" cannot pass: in `tests/test_ensemble_config_defaults.py` remove `"docs/recent_events"` from `TestNoDrift.FORBIDDEN` (`:95`) — otherwise `test_the_defaults_are_declared_where_they_belong` (`:118-124`) fails once the literal leaves `ensemble_config_shared.py` — and delete `test_recent_events_uses_configured_output` (`:222`) and `test_threads_and_recent_events_get_no_model` (`:402`); in `tests/test_ensemble_config_shared.py` delete the `recent_events_out` / `recent_events_window` assertions (`:46`, `:58`, `:70-71`)
- [X] T033 [US3] Hand-edit `config/ensemble.yaml` in both live campaigns to remove `paths.recent_events_out` (and `tuning.recent_events_window` if present); confirm `GET /api/ensemble/config` returns 400 before and 200 after (quickstart §8b)

**Checkpoint**: Every location is declared once. Redirecting one takes effect everywhere.

---

## Phase 6: User Story 4 — See what is stale and rebuild just that, from the UI (P3)

**Goal**: Section staleness is visible and a single section can be rebuilt, from the browser.

**Independent Test**: From the UI alone, identify an out-of-date section and rebuild only it,
producing the same file the CLI would and leaving every other section untouched.

### Tests for User Story 4

- [X] T034 [P] [US4] Write `tests/test_projection_routes.py`: `GET/PUT /api/projections/config` round-trip, `400` on unknown key, deep-merge leaves untouched groups intact, and a projections write cannot alter `grounding.yaml`/`ensemble.yaml`/`platform.yaml`
- [X] T035 [US4] Add `tests/test_projection_routes.py::test_build_rejects_empty_sections`: `GET /api/projections/run/build` with no `sections` returns `400`, never "all" (Constitution X, FR-013)
- [X] T036 [US4] Add `tests/test_projection_routes.py::test_no_literals_in_router`: no `docs/`-shaped literal in `server/routers/projections.py`; every path comes from `resolved()` (the `test_ensemble_config_defaults.py` rule)

### Implementation for User Story 4

- [X] T037 [US4] Add `--json` to `grounding_sections list` in `pipelines/grounding/grounding_sections.py`, emitting `{doc, sections:[{name, mode, state, inputs[], provenance}]}` per contracts/cli.md. **T038/T040 are not implementable without it** — the current output is a fixed-width text table with no input paths, and parsing it in the router would put logic in the server (FR-023, Constitution VI). Add `per-npc` to the state enum for the outlook section the table prints as `-`
- [X] T038 [US4] Create `server/projection_config_service.py` mirroring `GroundingConfigService`: constructed from a config directory, `_deep_merge` for grouped partial writes, `resolved()` as the single read seam, `get_selection`/`set_selection` for feature 003
- [X] T039 [US4] Create `server/routers/projections.py` with `GET/PUT /config`, `GET /sections`, `GET /run/build` (SSE) and `GET /run/recent-events` (the route moved in from ensemble, research D15); sentinels only, resolved at the route edge; selection through `platform_config_service.resolve_selection` (contracts/api.md)
- [X] T040 [US4] Mount the router at `/api/projections` in `server/main.py`
- [X] T041 [US4] Add the `provenance` field to the `GET /sections` response — which dossier set and importance list fed each section, read-only (FR-024a, contracts/api.md)
- [X] T042 [US4] Create `frontend/src/views/grounding/ProjectionSections.vue`: staleness table, per-section rebuild, provenance column, and the shared `SelectionPanel` so any cost-bearing run is an explicit choice (FR-019)
- [X] T043 [US4] Register the nested route in `frontend/src/router.ts` under `/grounding` and add the nav entry
- [X] T044 [US4] Run `cd frontend && npx vue-tsc --noEmit && npx vite build`

**Checkpoint**: All four stories independently functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T045 [P] Write `docs/config/projection-isolation.md` in the series idiom (status stamp, current state, problems, tracks, phases, tests, invariants, out-of-scope, decisions) — including the dependent-layer framing so the next reader does not mistake the renderers for peers
- [X] T046 [P] Reconcile the cross-cutting config docs: `docs/config/README.md` (index row), `schema.md` (a `projections.yaml → ProjectionConfig` section **and** the removal of the two retired `ensemble.yaml` fields), `crud.md`, `values.md`, `service-cut.md` (a State Projection row in both service tables), `master.md`
- [X] T047 [P] Update `docs/system/flow-state-projections.md`: the `planning.py` / `grounding_sections.py` "do not run both" seam is **closed**, and the draft location moved
- [X] T048 [P] Update `docs/core/architecture.md` if issue #215 has not already landed — this feature changes the router table and the on-disk layout it documents
- [X] T049 Run the full quickstart.md sequence end to end against both live campaigns
- [X] T050 Run `python -m pytest tests/` and compare against the T003 baseline — zero new failures

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: needs Setup — **blocks every story** (all three consuming stories read `ProjectionConfig`)
- **US1 (Phase 3)**: needs Foundational. Consumes only the `output` group
- **US2 (Phase 4)**: needs Foundational. Consumes only the `inputs` group — independent of US1
- **US3 (Phase 5)**: needs Foundational. Consumes the `stores` group — independent of US1/US2
- **US4 (Phase 6)**: needs Foundational **and US3** — the router resolves the same document the CLIs do, and T039 restores the route T031 removed
- **Polish (Phase 7)**: needs all desired stories

### The one cross-story dependency, stated plainly

US4 depends on US3. Everything else is independent because the stories were scoped to disjoint
config groups: US1 owns `output`, US2 owns `inputs`, US3 owns `stores`. That split is what makes
them separately testable despite sharing one document.

### Parallel Opportunities

- T003 in Setup. T006/T007 share `tests/test_projection_config.py`, so they are sequential, not [P]
- T010 and T011 both write `tests/test_projection_isolation.py` — sequential. T014 touches `server/`, so it is independent of T012/T013
- T017 and T019 are [P] (different files); T018 shares the isolation file with T010/T011
- T023/T024 share the isolation file — sequential. T026 is [P] against T025 (different file)
- T034–T036 all write `tests/test_projection_routes.py` — sequential
- The entire polish doc set (T045–T048) together
- With one developer: US1 → US2 → US3 → US4 in priority order. With several: US1, US2, US3 in parallel after Phase 2, US4 after US3.

---

## Parallel Example: User Story 3

```bash
# Tests first — both fail before implementation:
Task: "test_no_docs_literals in tests/test_projection_isolation.py"
Task: "test_redirected_store_is_honoured_by_hash_and_read in tests/test_projection_isolation.py"

# Then the two independent CLI conversions:
Task: "event_spine.py config resolution (T025)"
Task: "thread_registry.py config resolution (T026)"
```

---

## Implementation Strategy

### MVP (User Story 1 only)

Phase 1 → Phase 2 → Phase 3, then **stop and validate**: run all three rendering services in any
order and confirm none clobbers another. That alone closes a live data-loss defect and is worth
shipping before anything else.

### Incremental Delivery

1. Setup + Foundational → the document exists and is enforced
2. **US1** → outputs separated, legacy gate in place → validate → ship
3. **US2** → sibling independence provable, dossier fallback visible → ship
4. **US3** → every location declared once; the `events.jsonl` split closed → ship
5. **US4** → the interface → ship

### Notes

- T031 removes the recent-events route and T039 restores it under the new prefix. If US4 is not
  going to follow soon, run `build_recent_events` from the CLI in the meantime.
- T030 and T033 are a deliberate breaking change: both campaigns' ensemble pages return `400` until
  their `config/ensemble.yaml` is hand-edited. Expected, per research D15.
- Commit after each task or logical group; stop at any checkpoint to validate a story on its own.
