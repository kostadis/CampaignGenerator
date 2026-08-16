---

description: "Task list for Scene Extraction Token Limit from the UI"
---

# Tasks: Scene Extraction Token Limit from the UI

**Input**: Design documents from `/specs/011-extract-max-tokens/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/editor-config-api.md, quickstart.md (all present)

**Tests**: Included. `plan.md`'s Technical Context and `data-model.md`'s validation rules already name the exact files/cases to extend (`tests/test_session_editor_config_service.py`, `tests/test_editor_pipeline.py`), mirroring this repo's existing coverage of the sibling `narrate`/`scrub` knobs.

**Organization**: One user story (spec.md has a single P1 story — this feature has no independently-shippable slices smaller than "the knob works end to end").

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1 — the only one)
- File paths below are relative to the repository root (this worktree, `.claude/worktrees/011-extract-max-tokens/`)

## Path Conventions

Existing web-app layout (per `plan.md`'s Project Structure): `server/` (FastAPI backend), `frontend/src/` (Vue 3), `tests/` at repository root. No new files or directories beyond the ones already listed.

---

## Phase 1: Setup

**Purpose**: Project initialization and basic structure

No setup tasks required. This feature only modifies five existing files
(`server/session_editor_config_shared.py`, `server/session_editor_config_service.py`,
`server/routers/scene_editor.py`, `frontend/src/components/scene-editor/KnobDrawer.vue`,
`frontend/src/views/session/SessionDocEditor.vue`) plus two existing test
files — no new dependencies, no new project scaffolding, no new console
script (`scene_extract`'s `--max-tokens` flag already exists).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The schema/model layer every other change in this feature depends on

**⚠️ CRITICAL**: `cfg.extract.tokens` must exist on `ResolvedEditorConfig`
before the router change (Phase 3) can read it, and before either test file
can exercise it.

- [X] T001 [P] Add `ExtractKnobs` model (`tokens: int = 8192`, `extra="forbid"`, per data-model.md) to `server/session_editor_config_shared.py`, placed alongside `NarrateKnobs`/`ScrubKnobs`
- [X] T002 Add `extract: ExtractKnobs = Field(default_factory=ExtractKnobs)` to `SessionEditorConfig` in `server/session_editor_config_shared.py` (depends on T001, same file)
- [X] T003 [P] Add `extract: ExtractKnobs` field to the `ResolvedEditorConfig` dataclass in `server/session_editor_config_service.py`
- [X] T004 Populate `extract=cfg.extract` in `SessionEditorConfigService.resolved_editor_config()` in `server/session_editor_config_service.py`, alongside the existing `narrate=cfg.narrate, scrub=cfg.scrub` (depends on T001, T003, same file)

**Checkpoint**: `ResolvedEditorConfig.extract.tokens` resolves correctly (default `8192`, overridable via stored config) — verifiable with a quick `python -c` round-trip before moving on.

---

## Phase 3: User Story 1 - Set a per-scene output cap before extracting (Priority: P1) 🎯 MVP

**Goal**: A GM can set an Extract-stage token limit in the Config drawer, have it persist, and have it actually cap the next `scene_extract` run — mirroring the Narrate stage's existing token-limit control exactly (spec.md).

**Independent Test**: Open the Config drawer, find the Extract section's token-limit field, change it, save, run Stage 2 (Extract/Re-Extract), and confirm the run used the configured value rather than the tool's built-in default (spec.md's own Independent Test criterion; scripted step-by-step in `quickstart.md`).

### Implementation for User Story 1

- [X] T005 [US1] Add `"extract": cfg.extract.model_dump()` to `_serialize_resolved()` in `server/routers/scene_editor.py`, alongside the existing `"narrate"`/`"scrub"` entries (depends on T004 — needs `ResolvedEditorConfig.extract` to exist)
- [X] T006 [US1] Forward the value in `_build_reextract_cmd()` in `server/routers/scene_editor.py`: append `["--max-tokens", str(cfg.extract.tokens)]` to `cmd`, mirroring how `_build_narrate_cmd()` forwards `cfg.narrate.tokens` as `--narrate-tokens` (depends on T004; same file as T005, sequential)
- [X] T007 [P] [US1] Add a "Token limit" number input to the "② Extract" section of `frontend/src/components/scene-editor/KnobDrawer.vue` — new `extractTokens: number` prop, new `update:extractTokens` emit, `<input type="number" min="1000" step="500">` bound the same way as Stage ④'s existing "Token limit" field (lines ~251-262 in the same file)
- [X] T008 [US1] Wire `extractTokens` end-to-end in `frontend/src/views/session/SessionDocEditor.vue`: new `extractTokens = ref(8192)`; seed it from `ec?.extract?.tokens` in `loadConfigFields()`; include it in the `watch([...])` list that triggers `scheduleApply()`; add `extract: { tokens: extractTokens.value || undefined }` to `buildEditorConfigPayload()`; pass `v-model:extract-tokens="extractTokens"` to `<KnobDrawer>` — every step mirrors the existing `narrateTokens` wiring in the same file (depends on T007 for the prop/emit names)

### Tests for User Story 1

- [X] T009 [P] [US1] Add `ExtractKnobs` coverage to `tests/test_session_editor_config_service.py`: default value is `8192`, an unknown field under `extract` is rejected (`extra="forbid"`), and a set value round-trips through `load_session_editor_config`/`save_session_editor_config` — mirroring the file's existing `NarrateKnobs`/`ScrubKnobs` cases (depends on T001-T004)
- [X] T010 [P] [US1] Add `--max-tokens` forwarding assertions to `tests/test_editor_pipeline.py`: `_build_reextract_cmd()` includes `["--max-tokens", "8192"]` by default and `["--max-tokens", "12000"]` when `cfg.extract.tokens` is set, mirroring the file's existing batch-forwarding test pattern (there was no pre-existing narrate-tokens assertion to mirror, as originally assumed — verified while implementing) (depends on T005, T006)
  - Unplanned but required: `ResolvedEditorConfig` gained a new required field (T003), so every test that constructs it directly needed updating — fixed `_cfg()` in `tests/test_editor_pipeline.py` and `_status_for()` in `tests/test_editor_verify_routes.py` (both now pass `extract=`)
  - Unplanned but required: two contract-shape tests asserted the exact `GET /api/editor/config` key set and didn't expect `"extract"` — updated `tests/test_editor_profiles_routes.py::test_activate_profile_mirrors_knobs_into_resolved_config` and `tests/test_editor_service_integration.py::TestGetEditorConfig::test_returns_grouped_shape`
  - Full suite verified: `python3 -m pytest tests/` → 3696 passed, 174 skipped, 3 failed — the 3 failures (`test_gate2_rpg_retrieval`, `test_cli_parallel_fully_cached`, `test_search_hierarchical_on_fresh_palace_falls_back`) are pre-existing and environment-dependent (RLM index / mempalace live service / subprocess env), confirmed identical on `main`

**Checkpoint**: User Story 1 is fully functional and independently testable — this phase is also the entire feature (single-story), so completing it completes the feature.

---

## Phase 4: Polish & Cross-Cutting Concerns

- [X] T011 (partial — see note) Validate `quickstart.md`'s scenarios (depends on all of Phase 2 and Phase 3):
  - Steps 1-2 (default visibility, persistence across reload) verified against the **real FastAPI route layer** (`TestClient` over `GET`/`PUT /api/editor/config`, fresh app instance per "reload") — confirmed `extract.tokens` defaults to 8192, a `PUT` of 12000 persists to `session_doc.yaml`, and a second app instance reading the same campaign dir sees it.
  - Step 3 (effect on a real extraction) and Step 4 (no change for pre-feature campaigns) verified via `_build_reextract_cmd`'s unit tests (T010) — confirms the exact subprocess command line, not the model output.
  - **Not done**: an actual `scene_extract` subprocess run against the live Anthropic API (would spend real API budget for no additional confidence beyond the command-construction proof above), and a manual browser click-through of the Config drawer (no browser-automation tool available in this environment). Frontend correctness was instead verified via a clean `vue-tsc --noEmit` typecheck and a clean production `vite build`.
  - `python3 -m pytest tests/` (full suite): 3696 passed, 174 skipped, 3 pre-existing/environment-dependent failures unrelated to this feature (confirmed identical on `main`).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: None — no tasks.
- **Foundational (Phase 2)**: No dependencies beyond Setup — BLOCKS Phase 3 and Phase 4.
- **User Story 1 (Phase 3)**: Depends on Phase 2 completion (T001-T004).
- **Polish (Phase 4)**: Depends on Phase 3 completion.

### Within Phase 2

- T001 → T002 (same file, `SessionEditorConfig` needs `ExtractKnobs` to already be defined)
- T001, T003 → T004 (`resolved_editor_config()` needs both the model and the dataclass field to exist)
- T003 has no dependency on T001/T002 and can run in parallel with them

### Within Phase 3

- T004 → T005, T006 (router needs `ResolvedEditorConfig.extract` to exist)
- T005 and T006 touch the same file (`server/routers/scene_editor.py`) — sequential, not parallel
- T007 has no backend dependency and can start as soon as Phase 2 is done
- T007 → T008 (SessionDocEditor.vue's `v-model:extract-tokens` needs KnobDrawer's prop/emit names to exist first)
- T005, T006 → T010; T001-T004 → T009

### Parallel Opportunities

- T001 and T003 (Phase 2, different files)
- T007 (frontend) and T005/T006 (backend) once Phase 2 is done — different files, no shared dependency between them beyond T004
- T009 and T010 (different test files) once their respective implementation tasks land

---

## Parallel Example: Phase 2 → Phase 3

```bash
# Phase 2, run together:
Task: "Add ExtractKnobs model to server/session_editor_config_shared.py"
Task: "Add extract field to ResolvedEditorConfig dataclass in server/session_editor_config_service.py"

# Once Phase 2 lands, these can proceed in parallel:
Task: "Forward --max-tokens in _build_reextract_cmd (server/routers/scene_editor.py)"
Task: "Add Token limit field to KnobDrawer.vue's Extract section"
```

---

## Implementation Strategy

### MVP First (and only)

1. Complete Phase 2: Foundational (T001-T004) — the schema layer.
2. Complete Phase 3: User Story 1 (T005-T010) — this **is** the MVP; there is
   no smaller independently-valuable slice for this feature.
3. Complete Phase 4: run `quickstart.md` (T011) to confirm end-to-end.
4. Ship as a single PR — the feature is additive, backward-compatible
   (spec FR-004), and too small to usefully split further.

### Notes

- [P] tasks touch different files with no unfinished dependency between them.
- Commit after Phase 2, after Phase 3's backend half, after Phase 3's
  frontend half, and after tests — or as one commit if preferred; this repo
  has no stated convention requiring one commit per task.
- Every implementation task above names the existing sibling code
  (`NarrateKnobs`, `_build_narrate_cmd`, `narrateTokens`) it mirrors —
  when in doubt about a detail this file doesn't spell out, match that
  sibling exactly rather than inventing a new shape.
