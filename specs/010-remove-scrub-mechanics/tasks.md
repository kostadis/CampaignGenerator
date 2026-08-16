# Tasks: Remove scrub_mechanics.py (superseded by the /scrub skill)

**Input**: Design documents from `specs/010-remove-scrub-mechanics/` (spec.md, plan.md)

**Tests**: Existing tests are the safety net for this feature (it's a removal,
not new functionality) — task groups below update/delete tests alongside the
code they cover, and a full-suite run gates completion. No new tests are added
beyond what already exists, per FR-012.

**Organization**: Grouped by user story from spec.md, in priority order. Story
3 (CLI deletion + `split_frontmatter_raw` relocation) is sequenced before
Story 2's config cleanup is *verified* complete only in the sense that both are
independent files — no hard ordering dependency exists between stories, but
within this task list the *relocation* (T010) must land before the *deletion*
(T012) of the file it's extracted from.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

---

## Phase 1: Foundational (blocking prerequisite for Story 3)

**Purpose**: Relocate the shared utility before anything deletes the file it
currently lives in.

- [X] T001 [Foundational] Add `split_frontmatter_raw()` to
      `campaignlib/textproc.py`, placed immediately after `split_frontmatter()`,
      with its existing docstring adapted to point at its new sibling location
      (drop the self-referential "use `session_doc.scrub_mechanics.
      split_frontmatter_raw` instead" line in `split_frontmatter`'s own
      docstring and replace with a same-file cross-reference).

**Checkpoint**: `python -c "from campaignlib.textproc import split_frontmatter_raw"` succeeds.

---

## Phase 2: User Story 3 - CLI deletion + console-script + dedicated test removal (Priority: P2, sequenced first for dependency reasons)

**Goal**: `scrub_mechanics.py` and everything that exists solely to name/run it
are gone; the frontmatter helper it used to own now lives in `textproc.py` and
every importer follows.

**Independent Test**: `python -m pytest tests/` collects cleanly with no
`ModuleNotFoundError` for `session_doc.scrub_mechanics`; the file doesn't exist;
`pyproject.toml` has no `scrub_mechanics` script entry.

- [X] T002 [P] [US3] Update `tests/test_frontmatter_parsers.py`: change the
      import from `from session_doc.scrub_mechanics import split_frontmatter_raw`
      to `from campaignlib.textproc import split_frontmatter_raw`; update the
      module docstring's description of the two parsers' locations to match
      (both now live in `campaignlib.textproc`).
- [X] T003 [P] [US3] Delete `tests/test_scrub_mechanics.py` (its
      `split_frontmatter_raw` coverage already lives in
      `test_frontmatter_parsers.py`; its `--batch`/`scrub_batch`/`scrub_one`/
      `main()` coverage tests code being deleted in T004).
- [X] T004 [US3] Delete `session_doc/scrub_mechanics.py` (depends on T001, T002
      having relocated/repointed `split_frontmatter_raw` first).
- [X] T005 [US3] Remove the `scrub_mechanics = "session_doc.scrub_mechanics:main"`
      line from `pyproject.toml`'s `[project.scripts]` table.
- [X] T006 [US3] Update `tests/test_batch_flag_uniformity.py`: remove
      `"session_doc/scrub_mechanics.py"` from `REGISTRAR_CLIS`.
- [X] T007 [US3] Update `session_doc/assemble.py`'s module docstring: replace
      "the latter produced by `scrub_mechanics`" with wording that doesn't name
      a now-deleted CLI (e.g. "the latter produced by a scrub pass, e.g. the
      `/scrub` Claude Code skill") — logic in `collect_scene_files` /
      `--no-prefer-scrubbed` untouched.
- [X] T008 [US3] Update `docs/cli/cli_tools.md`: remove `scrub_mechanics` from
      the batch-shape CLI list (the "Shape per CLI" paragraph).

**Checkpoint**: `session_doc/scrub_mechanics.py` no longer exists; grep for
`scrub_mechanics` in `pyproject.toml` returns nothing; `test_frontmatter_parsers.py`
passes against the relocated function.

---

## Phase 3: User Story 2 - Backend routes, config knob, migration-map (Priority: P1)

**Goal**: No route shells out to the deleted CLI; the config schema has no
`scrub` group; an existing on-disk `session_doc.yaml` with a legacy `scrub:`
block still loads.

**Independent Test**: `GET /api/editor/scrub/1` and `GET /api/editor/scrub-all`
are 404 (route not registered); `GET /api/editor/config` has no `scrub` key;
a `session_doc.yaml` fixture with a top-level `scrub:` block loads without
raising.

- [X] T009 [US2] In `server/routers/scene_editor.py`: delete the
      `GET /scrub/{n}` route (`api_scrub`) and the `GET /scrub-all` route
      (`api_scrub_all`), and remove the `"scrub": cfg.scrub.model_dump(),` line
      from `_serialize_resolved()`.
- [X] T010 [US2] In `server/session_editor_config_shared.py`: delete the
      `ScrubKnobs` class; remove the `scrub: ScrubKnobs = Field(default_factory=
      ScrubKnobs)` field from `SessionEditorConfig`; remove the
      `"scrub_enabled": ("scrub", "enabled")` and `"scrub_tokens": ("scrub",
      "tokens")` entries (with their explanatory comments) from
      `TYPED_SESSION_DOC_TO_GROUPED`, following the file's existing precedent
      comments for `roleplay_dir`/`narration_genre`/`characters`/`gm_player`.
- [X] T011 [US2] In `server/session_editor_config_shared.py`: add
      `RETIRED_SESSION_DOC_FIELDS: tuple[str, ...] = ("scrub",)` and a
      `@model_validator(mode="before")` `_drop_retired_fields` classmethod on
      `SessionEditorConfig`, mirroring `EditorPaths._drop_retired_fields` /
      `NarrateKnobs._drop_retired_fields` exactly (strip before `extra="forbid"`
      sees it, print a stderr notice naming what was dropped and why).
- [X] T012 [US2] In `server/session_editor_config_service.py`: remove the
      `ScrubKnobs` import, the `scrub: ScrubKnobs` field on
      `ResolvedEditorConfig`, and the `scrub=cfg.scrub` line in
      `resolved_editor_config()`.
- [X] T013 [P] [US2] Update `tests/test_editor_pipeline.py`: remove the
      `ScrubKnobs` import and the `scrub=ScrubKnobs()` kwarg from the `_cfg()`
      helper's `ResolvedEditorConfig(...)` construction.
- [X] T014 [P] [US2] Update `tests/test_editor_verify_routes.py`: remove the
      `scrub=base.scrub` kwarg from `_status_for()`'s `ResolvedEditorConfig(...)`
      construction.
- [X] T015 [P] [US2] Update `tests/test_editor_profiles_routes.py`: remove
      `"scrub"` from the expected top-level key set asserted against the
      profile-activate response body.
- [X] T016 [US2] Update `tests/test_editor_service_integration.py`: remove
      `"scrub"` from the expected key set in `TestGetEditorConfig.
      test_returns_grouped_shape`; delete or rewrite
      `test_put_editor_config_backend_and_scrub_fields` (drop the `scrub`
      portion, keep the backend-fields coverage if it has independent value,
      otherwise delete the whole test since the backend-field PUT is already
      covered by `test_put_editor_config_persists_through_service`); update
      `test_put_editor_config_grouped_body_merges_multiple_groups` to merge two
      groups that both still exist (e.g. `narrate` + `paths`) instead of
      `scrub` + `narrate`.
- [X] T017 [US2] Add a regression test (in `tests/test_editor_service_integration.py`
      or `tests/test_session_editor_config_shared.py` if one exists, otherwise
      alongside the other retired-field tests in `server/session_editor_config_shared.py`'s
      test coverage) asserting that a `session_doc.yaml` containing a top-level
      `scrub: {enabled: true, tokens: 8000}` block loads via
      `load_session_editor_config` without raising, and that the loaded config
      has no `scrub` attribute — proving FR-005/SC-003 rather than just hoping
      T011 works.
- [X] T018 [US2] Update `tests/test_migrate_session_doc.py`: change
      `assert cfg.scrub.enabled is True` (line ~99) to assertions matching the
      established pattern for a retired migration target (e.g.
      `assert not hasattr(cfg, "scrub")` and `"scrub" not in cfg.model_dump_json()`),
      with a comment explaining why, mirroring the existing `roleplay_dir`/
      `narration_genre`/`roster` comment blocks in the same test. Leave
      `scrub_enabled: true` in the `OLD_UI_STATE` fixture itself — the fixture
      represents legacy raw input, which realistically still contains this key.
- [X] T019 [US2] Update `docs/config/schema.md`: remove the `scrub` row from
      the `SessionEditorConfig` field table.
- [X] T020 [P] [US2] Update `docs/config/values.md`: remove the
      `scrub.enabled, scrub.tokens` row from the value-level read/write map.
- [X] T021 [P] [US2] Update `docs/config/master.md`: drop `scrub` from the
      `session_doc.yaml` field-group list in the master map table.
- [X] T022 [P] [US2] Update `docs/config/service-cut.md`: drop `scrub` from the
      "narrate/scrub CLI" column for the Session Doc Editor row.

**Checkpoint**: Backend fully clean of `scrub` route/config surface; existing
`session_doc.yaml` files with a legacy `scrub:` block still load; docs describing
the config schema no longer mention it.

---

## Phase 4: User Story 1 - Frontend action surface removal (Priority: P1)

**Goal**: No clickable Scrub / Scrub All control anywhere in the UI; scrub
*status* display (dot, badge) is untouched.

**Independent Test**: `grep -n scrub frontend/src/views/session/SessionDocEditor.vue
frontend/src/components/scene-editor/ExtractionEditor.vue` shows no button/ref/
handler remaining; `SceneList.vue` and `ReviewAssemble.vue` are unmodified (or
modified for unrelated reasons only).

- [X] T023 [US1] In `frontend/src/views/session/SessionDocEditor.vue`: remove
      the `scrubbing` ref, the `scrubScene()` and `scrubAll()` functions, the
      "Scrub All" `<button>` (Stage 4½ group), the `:scrubbing="scrubbing"` prop
      and `@scrub="scrubScene"` listener passed to `<ExtractionEditor>`.
- [X] T024 [US1] In `frontend/src/components/scene-editor/ExtractionEditor.vue`:
      remove the `scrubbing: boolean` prop, the `'scrub': []` emit declaration,
      and the "Scrub" `<button>` in the toolbar.
- [X] T025 [P] [US1] In `frontend/src/components/scene-editor/KnobDrawer.vue`:
      update the backend-selector label from "Backend (also applies to Stage 2,
      Narrate, Scrub)" to drop the now-inaccurate ", Scrub" (e.g. "Backend (also
      applies to Stage 2, Narrate)").
- [X] T026 [P] [US1] In `frontend/src/stores/config.ts`: update the stale
      comment listing `editorConfig`'s shape ("paths/narrate/scrub/roster/
      backends/...") to drop `scrub/` (leave the pre-existing `roster/` drift
      alone — unrelated to this feature).
- [X] T027 [US1] Confirm (no edit expected) that
      `frontend/src/components/scene-editor/SceneList.vue`'s `has_scrubbed`
      dot and `frontend/src/views/session/ReviewAssemble.vue`'s
      `lifecycle.scrub` badge are untouched by the above edits.

**Checkpoint**: UI has no path to trigger a scrub action; status display intact.

---

## Phase 5: User Story 4 - Live reference docs (Priority: P3)

**Goal**: The two named live docs plus root `CLAUDE.md` describe the system as
it exists after this change; named historical docs are untouched.

**Independent Test**: `grep -i scrub docs/web/session_doc_editor.md
docs/cli/cli_tools.md CLAUDE.md` shows only forward-pointing (`/scrub` skill) or
clearly historical (#151) references, no live-button/live-CLI instructions;
`git diff --stat` shows none of the six explicitly-excluded historical files.

- [X] T028 [US4] Update `docs/web/session_doc_editor.md`: remove the header
      ASCII-diagram's `[Scrub All]` button, the numbered-workflow step
      mentioning "optionally Scrub", the per-scene "(Optional) Scrub" step, the
      "### Stage 4½ — Scrub All" section (replace with a short note that
      mechanical scrubbing now happens via the `/scrub` Claude Code skill,
      run outside the web UI, and that the `.scrubbed.md` output contract is
      unchanged), the activity-timeline line naming "Scrub" as a tracked stage
      (drop it — the action no longer runs through this app so nothing appends
      that activity-log line any more), the directory-tree comment
      "# Stage 4½ scrub output" (reword to not claim a specific stage number
      tied to a removed UI stage — e.g. "produced by the `/scrub` skill,
      outside this app"), and the CLI-list bullet `scrub_mechanics.py — Stage
      4½ scrub`.
- [X] T029 [US4] Update `docs/cli/cli_tools.md`: confirm no standalone
      `scrub_mechanics` CLI entry remains beyond the batch-list mention already
      handled in T008.
- [X] T030 [US4] Update root `CLAUDE.md`'s "LLM renders, humans decide" /
      quote-verification paragraph (~line 288): reword "the GM applies fixes in
      Claude (`scrub_mechanics`/#151 is the scar)" so it no longer names
      `scrub_mechanics` as if it were a live command — e.g. "the GM applies
      fixes in Claude (the `/scrub` skill now owns this; #151, the
      spell-stripping incident, is the scar that retired the old autonomous
      CLI)" — while keeping the #151 lesson intact.

**Checkpoint**: Docs match the post-removal system; historical docs untouched
(verify via `git diff --stat` against the explicit exclusion list).

---

## Phase 6: Full-suite validation & commit

**Purpose**: Prove FR-012/SC-002 and land the change.

- [X] T031 Run `python -m pytest tests/` from the repo root; fix any failure
      not already anticipated by T002–T022 (there should be none, but this is
      the actual gate, not the task list's prediction of it).
- [X] T032 [P] Best-effort: `cd frontend && npm run build` (or the repo's
      documented equivalent) to sanity-check the Vue changes compile; note in
      the final report if the environment can't run it rather than blocking on
      it.
- [X] T033 Final repo-wide sanity sweep: `grep -rniI scrub_mechanics` over
      `server/`, `session_doc/`, `frontend/src/`, `pyproject.toml` and confirm
      every remaining hit is one of the accounted-for docstring/comment
      mentions (T007), not a live import/route/script entry.
- [X] T034 `git add` the touched files and commit on branch
      `010-remove-scrub-mechanics` (local only — no push, no PR, per the task's
      explicit instruction).

---

## Dependencies & Execution Order

- **Phase 1 (T001)** blocks **T004** (can't delete the file before its export
  is relocated) but nothing else — T002/T003 can proceed in parallel with T001
  since they touch different files, though T002 logically depends on T001 having
  landed the new import target.
- **Phase 2 (US3)** has no dependency on Phase 3/4/5 — independently completable
  and independently testable per spec.md.
- **Phase 3 (US2)** has no file-level dependency on Phase 2, but is sequenced
  after it in this list because the router (`server/routers/scene_editor.py`)
  references `console_script("scrub_mechanics")`, which becomes dead once T004
  lands — removing the routes (T009) makes that reference moot either order,
  but doing US3 first means there's never a moment where a live route points at
  a deleted script.
- **Phase 4 (US1)** has no backend dependency — the frontend buttons can be
  removed independent of the backend routes being gone (though obviously both
  must land together for the feature to be complete; per spec.md each story is
  independently testable, not independently *shippable* alone).
- **Phase 5 (US4)** should land last among the content phases since it
  describes the end state of Phases 2–4.
- **Phase 6** depends on all prior phases.

### Parallel Opportunities

- T002, T003 [P] (different files from T001/T004)
- T013, T014, T015 [P] (three different test files, no shared state)
- T020, T021, T022 [P] (three different doc files)
- T025, T026 [P] (two different frontend files, independent of T023/T024's files)
- T032 [P] (independent of T031/T033, can run alongside them)
