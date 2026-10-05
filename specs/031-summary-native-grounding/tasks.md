---
description: "Task list for 031 summary-native grounding docs"
---

# Tasks: Summary-Native Grounding Docs

**Input**: Design documents from `specs/031-summary-native-grounding/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli.md, contracts/http.md, quickstart.md

**Tests**: Included. The spec's acceptance scenarios and success criteria are test-defined (byte-stability, all-errors-in-one-pass, no-LLM guard, defaults guard), and the repo convention is that every feature ships pytest coverage. Within a story, write the tests first.

**Organization**: tasks are grouped by user story (spec.md US1–US5).

**Delivery protocol** (plan.md, "Implementation Phases & Delivery Process"):
- Each phase is coded by an Agent subagent with `model: "sonnet"` (Sonnet 5.5). Opus 5.5 orchestrates and reviews.
- Each `COMMIT` task is followed by a `REVIEW` task: run `/code-review` on that commit, then fix confirmed findings in a follow-up commit before the next phase starts.
- Branch: `031-summary-native-grounding`. Never commit to `main`. The PR waits for the user's go-ahead.
- Run `python -m pytest tests/ -q` before every commit. Report failures as they are, without hiding them.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1…US5 from spec.md

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 Create the package skeleton `pipelines/summary_native/__init__.py` (docstring: a fourth rendering path that parses reviewed summaries and imports nothing from `pipelines/ensemble/`), an empty `pipelines/summary_native/prompts/` dir, and an empty `tests/fixtures/summary_native/`
- [X] T002 Add `summary_native = "pipelines.summary_native.cli:main"` to `[project.scripts]` in `pyproject.toml`, create a stub `pipelines/summary_native/cli.py` whose `main()` builds an argparse parser with the subcommands `validate|build|synth|compare`, then reinstall with `uv pip install -e . --python "$VIRTUAL_ENV/bin/python"` and confirm `summary_native --help` runs

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ No user story starts until this phase is done.**

- [X] T003 Write `pipelines/summary_native/schema.py` with:
  - recognised H2 names: `Scenes`, `NPCs`, `Locations`, `Items`, `Spells`, `Abilities`, `Memorable Moments`, `Session-End State`;
  - `ENTITY_CATEGORIES = {"NPCs": "npc", "Locations": "location", "Items": "item", "Spells": "spell", "Abilities": "ability"}`;
  - `CATEGORY_REGISTRY_TYPE = {"npc": "npc", "location": "location", "item": "item"}` (spell and ability have no registry type);
  - the finding-code constants from research.md R2 (`no-numeric-prefix`, `duplicate-chapter`, `missing-title`, `title-chapter-mismatch`, `missing-scenes`, `empty-scenes`, `bad-scene-id`, `scene-chapter-mismatch`, `duplicate-scene-id`, `unknown-section`, `range-gap`), each marked blocking or non-blocking;
  - the regexes: prefix `^(\d+)[-_.]`, title `^#\s+Chapter\s+(\d+)\b`, H2/H3/H4 anchored without a deeper `#`, scene id `^(\d{3})\.(\d{2})\s+(.+)$`.
- [X] T004 [P] Write `pipelines/summary_native/parse.py` with frozen dataclasses `Entry(heading, body, line)`, `Section(name, body, entries)`, `Scene(source_scene_id, title, synopsis, body, line)` and `SummaryFile(path, chapter, title_chapter, date, sections)`.
  - `parse_file(path, campaign_root) -> ParsedFile` never raises on content. It returns the parsed structure plus the raw facts validation needs: the prefix match, the title match, and the scene-heading matches with line numbers.
  - Synopsis is the `####` lines joined with " / ". If there are none, use the first non-heading paragraph, verbatim.
  - Paths are relative to the campaign root.
- [X] T005 [P] Create fixture corpora under `tests/fixtures/summary_native/`, each file 30–60 lines in the OOTA format (`# Chapter N`, `Date:`, `## Scenes`, `### NNN.SS Title` + `####` synopsis, `## Memorable Moments`, `## NPCs`/`## Locations`/`## Items`/`## Spells`):
  - `clean/`: chapters 002, 003, 005 (gap at 004). 7 scenes total. "Manshoon" appears in 002 and 005.
  - `multi_error/`: 5 files, one instance of each blocking code, including one file with two different errors.
  - `out_of_range/`: `clean` plus an `008-…md` whose title says Chapter 6.
  - `aliases/`: "Manshoon" / "Manshoon (Simulacrum)" / "Manshon" in NPCs across several files, "Staff of Power" in both Items and Spells, plus a tiny `entity_registry.yaml` with one npc alias.
  - `dup_chapter/`: two files with prefix 003.
- [X] T006 Write `tests/test_summary_native_parse.py`: scene ids are kept verbatim, synopsis is verbatim, section bodies are exact, line numbers are 1-based, and an entity H3 outside any scene gets `source_scene_id=None`.

**Checkpoint**: parsing works on all fixtures.

- [X] T007 COMMIT "summary_native: package skeleton, schema, parser" (Co-Authored-By trailer per session attribution)
- [X] T008 REVIEW `/code-review` on T007's commit. Fix confirmed findings and commit.

---

## Phase 3: User Story 1 — Validate and parse a corpus into a lossless evidence corpus (P1) 🎯 MVP

**Goal**: validate the whole directory in one pass with an optional chapter range, then build the deterministic corpus.

**Independent Test**: quickstart Q2–Q5. On the fixtures: `validate` reports every seeded problem in one run; `build` twice gives byte-identical trees; every dossier loads through `read_dossiers`.

### Tests for User Story 1 (write first)

- [X] T009 [P] [US1] `tests/test_summary_native_validate.py`:
  - `test_all_errors_one_pass`: the `multi_error` fixture gives every code and both errors of the double-error file in one report.
  - `test_title_mismatch_blocks_no_override`.
  - `test_scene_chapter_mismatch_blocks`.
  - `test_duplicate_chapter_blocks_even_outside_range`.
  - `test_out_of_range_errors_listed_not_blocking`: `out_of_range` with `--until 5`.
  - `test_range_bound_without_file_refused_lists_present`.
  - `test_start_after_end_refused`.
  - `test_gaps_reported_not_errors`: 004 in `clean`.
  - `test_empty_dir_refused`.
  - `test_report_md_grouped_by_file_with_summary_counts`.
- [X] T010 [P] [US1] `tests/test_summary_native_corpus.py`:
  - `test_build_byte_stable`: build twice into two tmp dirs and `filecmp` every file.
  - `test_chronology_order_and_ids`.
  - `test_memorable_moments_verbatim`.
  - `test_dossier_observation_provenance_fields`.
  - `test_dossiers_load_via_read_dossiers`: import `pipelines.ensemble.synthesise_world_state.read_dossiers`, expect `n_missing == 0`.
  - `test_range_excludes_out_of_range_content`.
  - `test_refuses_ensemble_out_dir`: dir with `merged.json` / `state_dossiers/`.
  - `test_refuses_existing_without_force`.
  - `test_no_absolute_paths_in_artifacts`.
  - `test_absent_optional_sections_in_manifest`.
  - `test_unknown_section_preserved_and_reported`.
- [X] T011 [P] [US1] `tests/test_summary_native_no_llm.py`: AST-walk `parse.py`, `validate.py`, `corpus.py`, `duplicates.py`, `select.py`, `context.py` and `compare.py`. Fail if any of them imports `campaignlib.api`/`anthropic`, or calls `stream_api`, `call_api`, `make_client` or `client_from_args`. Model on `tests/test_block_model_no_llm.py`.
- [X] T012 [P] [US1] `tests/test_summary_native_cli.py` (validate/build part): exit codes 0/1/2 per `contracts/cli.md`; `validate` writes only `validation_report.{md,json}`; the range dir name is `ch002-005`.

### Implementation for User Story 1

- [X] T013 [US1] `pipelines/summary_native/validate.py`:
  - Write `ChapterRange.resolve(present, since, until)`, which raises `RangeError` with the present chapters on a bad bound, since > until, or an empty range, and computes the gaps.
  - Write the `Finding` and `ValidationReport` dataclasses (`blocking_count`, `files_failing`, `to_json()`, `to_markdown()`). The markdown has in-range findings grouped by file, then "Outside range — not blocking", then summary counts.
  - Write `scan(summaries_dir, campaign_root, since, until) -> ValidationReport`, which runs every check on every file and never stops early.
  - `duplicate-chapter` is checked across the whole directory and always blocks.
  - Refuse input that lives under a `docs/ensemble/` path.
- [X] T014 [US1] `pipelines/summary_native/corpus.py`:
  - `guard_out_dir(range_dir, force)` refuses: an ensemble marker (`merged.json`, `state_dossiers/`, `merged_dossiers/`, `facts_*.json`, `extract_*.md`); a manifest of another `kind`; a non-empty dir with no manifest; an existing summary-native manifest without `force`.
  - `build_observations(files, aliases_fn)`.
  - `render_chronology`, `render_memorable_moments`, `write_dossiers` (frontmatter per data-model.md: `subject`, `type`, `n_facts`, `chapters: lo-hi`, `source_kind`, `headings`, `grouped_by`; one block per observation; sha suffix on slug collision) and `write_manifest` (no timestamps; sha256 per file; counts).
  - Write every file through `campaignlib.util.atomic_write_text`.
  - For US1, group by identical heading within a category only; US3 adds exact same-type registry aliases.
- [X] T015 [US1] Wire up `validate` and `build` in `pipelines/summary_native/cli.py` with the shared flags `--summaries-dir --since --until --out-root --registry --canon --dup-threshold --config --force`. Defaults for `--out-root` and `--dup-threshold` come from `grounding.yaml summary_native` (plain YAML read until T047), falling back to the defaults declared **once** as constants in `pipelines/summary_native/schema.py` (`DEFAULT_OUT_ROOT`, `DEFAULT_RECENT_CHAPTERS`, `DEFAULT_RECURRING_MIN`, `DEFAULT_DUP_THRESHOLD`, `DEFAULT_PARTS`).
  - Resolve config after `parse_args` via `find_default_config()`. If `--summaries-dir` is absent, read `grounding.yaml summary_native.summaries_dir` (a plain YAML read, so this works before US5's model exists); error if neither is set.
  - Print the report to stdout; exit codes per contract.
  - `build` runs `scan` first and refuses on blocking findings.
- [X] T016 [US1] Run T009–T012 and the full suite until green. Then run quickstart Q2 against the real OOTA directory (read-only; the 070 file is still unfixed) and record the report summary in the commit message.
- [X] T017 [US1] COMMIT "summary_native: whole-directory validation, chapter range, deterministic corpus build"
- [X] T018 [US1] REVIEW `/code-review` on T017's commit. Fix and commit.

**Checkpoint**: MVP. The GM can validate and build a corpus from the CLI with no tokens spent.

---

## Phase 4: User Story 2 — Draft world state and campaign state (P1)

**Goal**: render outline-checked drafts from a built corpus, keeping prompts, the selection and a run record; plus the compare report.

**Independent Test**: quickstart Q7 (with `--dump-only` in CI, and a real backend by hand). With a fake client: the drafts land in `drafts/`, the live docs are untouched, unsupported audit claims are labelled, and an incomplete output gives exit 3.

### Tests for User Story 2 (write first)

- [X] T019 [P] [US2] `tests/test_summary_native_select.py`:
  - recent is counted from `range_end`, not from the newest dossier;
  - recurring uses `>= recurring_min`;
  - `named` force-includes;
  - `selection.json` records the reason, `last_chapter` and `n_observations`;
  - the corpus files are unchanged after selection.
- [X] T020 [P] [US2] `tests/test_summary_native_synth.py`, with a fake client injected by monkeypatching `client_from_args`/`stream_api` in `pipelines.summary_native.synth`:
  - `test_dump_only_writes_prompts_no_call`;
  - `test_draft_written_when_outline_complete`;
  - `test_incomplete_when_heading_missing_exit3`;
  - `test_parts_one_call_per_part_joined_in_order`;
  - `test_world_state_input_only_from_explicit_flag`: no auto-pickup of `drafts/world_state.draft.md`;
  - `test_audit_files_fenced_as_questions`: the prompt contains the audit block label, and the system prompt requires the `## Audit: Tracking Claims` section with `NOT FOUND IN SUMMARIES`;
  - `test_never_writes_live_docs`: snapshot `docs/*.md` before and after;
  - `test_existing_draft_needs_force`;
  - `test_synth_refuses_stale_corpus`: edit a summary after `build` and expect exit 2;
  - `test_record_json_fields`.
- [X] T021 [P] [US2] Extend `tests/test_summary_native_cli.py` with the `synth`/`compare` argument contract (`add_backend_args` flags present; unknown doc refused) and `compare` (writes `.vs-live.diff`, reads both inputs only).

### Implementation for User Story 2

- [X] T022 [P] [US2] `pipelines/summary_native/select.py`: `select_dossiers(dossiers, range_end, recent_chapters, recurring_min, named) -> Selection` and `Selection.to_json()`. Read dossiers by parsing their frontmatter. Do not import from `pipelines.ensemble`.
- [X] T023 [P] [US2] Prompts:
  - `pipelines/summary_native/prompts/world_state.system.md` and `world_state.outline.yaml`, adapting the section structure of the OOTA promoted draft. Read it from the experiments branch with `git show experiments/oota-ensemble-summary-prototype:experiments/20261004-oota-ensemble-summary-prototype/summary_native/world_state_synthesis_prompt.md.system.md`.
  - `campaign_state.system.md` and `campaign_state.outline.yaml`, including the required `## Audit: Tracking Claims` section and its `SUPPORTED (ch N, scene X)` / `NOT FOUND IN SUMMARIES` tagging rule.
  - Each system prompt states: drafts only, cite chapter and scene ids, never import audit or module claims as history.
- [X] T024 [US2] `pipelines/summary_native/context.py`: `build_context(doc, range_dir, selection, upstream: dict[str, Path], audit: list[Path], extra: dict) -> (system, user)`. It only concatenates strings. The audit block is fenced and labelled "AUDIT QUESTIONS — NOT EVIDENCE"; the chronology and memorable moments are included whole.
- [X] T025 [US2] `pipelines/summary_native/synth.py`:
  - `load_outline(doc)`;
  - `check_outline(text, outline) -> list[str]` (missing or empty headings, order);
  - `render_part(client, system, user, model, max_tokens)` calls `stream_api`;
  - `run_synth(args)` writes `runs/<doc>/part-k.{system,user,out}.md` and `record.json`, then `drafts/<doc>.draft.md` with a provenance comment, or `.incomplete.md` and exit 3;
  - `--parts N` splits the outline headings into N contiguous groups.
  - The context-building and model-calling functions stay separate, so `tests/test_retrieve_render_isolation.py` passes.
- [X] T026 [P] [US2] `pipelines/summary_native/compare.py`: `compare(draft, live) -> CompareReport` (bytes, lines, heuristic highest chapter labelled as a heuristic), plus a unified diff written to `drafts/<doc>.vs-live.diff`.
- [X] T027 [US2] Wire `synth <doc>` and `compare <doc>` into `cli.py`.
  - Flags: `--world-state --campaign-state --audit --recent-chapters --recurring-min --name --parts --dump-only --force`, plus `add_backend_args(parser)`, `--model`, `--max-tokens`, with model resolution via `resolve_cli_model` as in `synthesise_world_state.main`.
  - `synth` refuses unless the range dir has a summary-native manifest. It then re-runs `validate.scan` and compares every in-range file's sha256 with `manifest.json`; on mismatch it exits 2 with "summaries changed since build — run `summary_native build --force`".
  - `--audit` defaults to `grounding.yaml campaign_state.track_files`.
  - Accept only `world_state` and `campaign_state` until US4.
- [X] T028 [US2] Make T019–T021 and the full suite green, including `tests/test_retrieve_render_isolation.py`. Run `synth world_state --dump-only` on a fixture build and inspect the prompts.
- [X] T029 [US2] COMMIT "summary_native: world/campaign state drafts with outline check and run records"
- [ ] T030 [US2] REVIEW `/code-review` on T029's commit. Fix and commit.

---

## Phase 5: User Story 3 — Find duplicate headings so the GM can fix the summaries (P2)

**Goal**: group headings only by identical text or exact same-type registry alias; list likely duplicates with `file:line` as non-blocking fix-at-source findings; read `not_duplicates` rulings from `canon.yaml`. Never merge, rename or alias a misspelling.

**Independent Test**: quickstart Q6 on the `aliases` fixture.

### Tests for User Story 3 (write first)

- [ ] T031 [P] [US3] `tests/test_summary_native_duplicates.py`:
  - `test_registry_exact_same_type_alias_groups_and_keeps_headings` (npc);
  - `test_registry_first_token_inference_not_applied`;
  - `test_spells_never_registry_grouped`: a registry entry naming a spell string has no effect on the `spell` category;
  - `test_no_cross_category_grouping_or_flag`: Staff of Power item vs spell;
  - `test_typo_listed_with_all_file_lines_not_merged`: Manshon/Manshoon;
  - `test_qualifier_pair_listed`: "Manshoon (Simulacrum)"/"Manshoon";
  - `test_possible_duplicate_is_non_blocking`: validate exits 0 when duplicates are the only findings;
  - `test_fixing_source_clears_finding`: edit a tmp copy of the fixture and re-scan;
  - `test_not_duplicates_ruling_suppresses`;
  - `test_registry_distinct_and_rejected_aliases_suppress`;
  - `test_canon_yaml_rejects_merge_keys`: `accepted:`, `aliases:` or any key other than `not_duplicates` is refused with exit 2;
  - `test_stale_ruling_reported`;
  - `test_dup_threshold_flag_changes_listing`: a pair at ratio ~0.85 is listed at `--dup-threshold 0.8` and not at the default;
  - `test_canon_yaml_never_written`: bytes and mtime unchanged after validate and build.
- [ ] T032 [P] [US3] Test for `Registry.explicit_aliases_by_type()` in the existing registry test file (find it via codebase-memory-mcp `search_graph name_pattern="test_.*alias_to_canonical"`). It returns exact names and aliases only, keyed `{type: {casefold(alias): canonical}}`, with no first-token entries.

### Implementation for User Story 3

- [ ] T033 [US3] Add `Registry.explicit_aliases_by_type()` to `campaignlib/registry.py`, next to `alias_to_canonical`. Its docstring must say first-token inference is excluded because grouping here must be exact (spec FR-013, research R7). Do not add a spell type to the registry (GM ruling).
- [ ] T034 [US3] `pipelines/summary_native/duplicates.py`:
  - `load_rulings(path) -> Rulings`: strict, `not_duplicates` is the only key, and any other key exits 2 with "canon.yaml records not-a-duplicate rulings only; fix duplicates in the summary files";
  - `make_grouper(registry) -> Callable[[category, heading], (canonical, grouped_by)]`, which allows identical text and exact same-type registry aliases only, with no registry for `spell`/`ability`;
  - `find_possible_duplicates(observations, registry, rulings, threshold)` (the default 0.88 comes only from `SummaryNativeRun.dup_threshold` / `--dup-threshold`, never a literal here; the report header records the value used) -> list[Finding]`, using the difflib ratio within a category plus a parenthetical-qualifier strip, with `locations` listing every `file:line` per spelling, excluding ruled pairs and the registry's `distinct`/`rejected_aliases`;
  - `stale_rulings(rulings, headings) -> list[Finding]`.
- [ ] T035 [US3] Wire the US3 functions into the US1 code:
  - `validate.scan` now also parses entity sections of in-range files and appends `possible-duplicate` (non-blocking) and `stale-ruling` (non-blocking) findings.
  - `validation_report.md` gains a "Possible duplicates — fix in the summaries" section.
  - Replace US1's identity grouper in `corpus.build_observations` with `duplicates.make_grouper`.
  - Record `grouped_by` in the dossier frontmatter, and the registry and canon sha256 in the manifest.
  - Add `possible-duplicate` and `stale-ruling` to `schema.py`.
  - Re-run T010 (byte-stability still holds).
- [ ] T036 [US3] Green the suite.
- [ ] T037 [US3] COMMIT "summary_native: fix-at-source duplicate detection"
- [ ] T038 [US3] REVIEW `/code-review` on T037's commit. Fix and commit.

---

## Phase 6: User Story 4 — Party and planning drafts (P3)

**Goal**: party and planning drafts, with no invented arc scores.

**Independent Test**: fake-client tests. Planning with an empty `planning.yaml` gives an empty Threat Tracker; a score line in it fails the run.

- [ ] T039 [P] [US4] Tests in `tests/test_summary_native_synth.py`:
  - `test_party_reads_party_config_and_sheets`, with a fixture `config/party.yaml` built via `campaignlib.party_config` types;
  - `test_planning_no_arc_scores_prompt_states_empty`;
  - `test_planning_threat_tracker_score_line_fails`: output with a score line under `## Threat Tracker` gives exit 3 with a named reason;
  - `test_party_planning_require_explicit_upstream_flags`.
- [ ] T040 [P] [US4] Prompts and outlines `pipelines/summary_native/prompts/{party,planning}.system.md` and `{party,planning}.outline.yaml`, adapted from the OOTA prototype prompts on the experiments branch (`git show …party_synthesis_prompt.md.system.md`, `…planning_synthesis_prompt.md.system.md`). Planning's outline includes `## Threat Tracker`.
- [ ] T041 [US4] Extend `context.py` and `synth.py`:
  - party context: `load_party_config_arg(--party-config)` → sheets + backstories;
  - planning context: `campaignlib.planning_config.load_planning_config` (arc scores, NPC/faction mappings);
  - the planning NPC selection reuses `select_dossiers` restricted to `npc`;
  - post-check: Threat Tracker must be empty when no arc scores are configured;
  - enable `party` and `planning` in the `synth` choices with `--party-config` / `--planning-config`.
- [ ] T042 [US4] Green the suite.
- [ ] T043 [US4] COMMIT "summary_native: party and planning drafts"
- [ ] T044 [US4] REVIEW `/code-review` on T043's commit. Fix and commit.

---

## Phase 7: User Story 5 — Web UI (P3)

**Goal**: every CLI capability is reachable from a Grounding page; there is no silent "all".

**Independent Test**: quickstart Q8, plus the route tests.

### Tests for User Story 5 (write first)

- [ ] T045 [P] [US5] `tests/test_summary_native_config_defaults.py`: `SummaryNativeRun` defaults (`out_root=docs/summary_native`, `recent_chapters=4`, `recurring_min=10`, `dup_threshold=0.88`, `parts=0`); an existing `grounding.yaml` without the group loads; an unknown key gives 400. Add a source scan of `server/routers/summary_native.py` that fails on default literals such as `"docs/summary_native"`, `= 4`, `= 10`, `0.88`, or `backend: str = "anthropic"`, modelled on `tests/test_ensemble_config_defaults.py`.
- [ ] T046 [P] [US5] `tests/test_summary_native_routes.py`, modelled on the existing grounding route tests found via codebase-memory-mcp:
  - every run route builds argv from `console_script("summary_native")`, with stored-config resolution and explicit-request precedence (`_pick` semantics);
  - unset range gives 400 "choose a chapter range";
  - unset `summaries_dir` gives 400;
  - unknown doc gives 400;
  - synth argv carries `--name`, `--dump-only`, `--max-tokens`, `--recent-chapters`, `--recurring-min` when supplied, and never carries `--registry`, `--canon` or `--out-root` (the CLI-only ruling in contracts/http.md);
  - `/chapters` lists prefixes and duplicates without parsing content;
  - `/report` and `/drafts` read files only (404 when absent).

### Implementation for User Story 5

- [ ] T047 [US5] Add `class SummaryNativeRun(BaseModel)` (strict) to `server/grounding_config_shared.py`, with the fields from `contracts/http.md`. Its field defaults MUST import the `DEFAULT_*` constants from `pipelines/summary_native/schema.py`, never re-spell them (Principle XII: one declaration), and `summary_native: SummaryNativeRun = Field(default_factory=SummaryNativeRun)` on `GroundingConfig`. Do not add it to `GROUNDING_DOCS`: it is a pipeline, not a fifth promotable doc. Update the `cli.py` config read (T015) to use `load_grounding_config` for the `summaries_dir` default.
- [ ] T048 [US5] `server/routers/summary_native.py`: argv builders for validate/build/synth/compare (the synth backend/model come via the existing `selection_cli_args(resolve_selection(...))` pattern used in `server/routers/grounding.py`), the read-only routes, SSE via the same `stream_subprocess` helper. Mount it in `server/main.py` with `prefix="/api/grounding/summary-native"`.
- [ ] T049 [P] [US5] `frontend/src/views/grounding/SummaryNative.vue`:
  - summaries-dir field;
  - range picker fed by `/chapters`, with an "All chapters" button that writes the first and last chapters explicitly;
  - Validate / Build (dup-threshold) / Synth (doc select, upstream draft paths, audit files, named subjects, recent-chapters, recurring-min, parts, max-tokens, dump-only, force) / Compare buttons, streaming output via the existing grounding run composable (`frontend/src/composables/useGroundingRun.ts`);
  - panels for the validation report (with its possible-duplicates section) and the drafts list;
  - no promote button and no rulings editor;
  - persist field values through `PUT /api/grounding/config`.
- [ ] T050 [P] [US5] `frontend/src/router.ts`: add the child route `summary-native` → `SummaryNative.vue` under `/grounding`. In `frontend/src/components/layout/AppSidebar.vue`, widen the `RenderingPath.id` union and add a fourth path `{ id: 'summary-native', label: 'Summary-native', description: 'Parses reviewed session summaries directly — no extraction pass.', usesSharedExtraction: false, matchPrefixes: ['/grounding/summary-native'], items: [{ label: 'Summary-native', path: '/grounding/summary-native' }] }`. Update the comment that says "three rendering paths".
- [ ] T051 [US5] `cd frontend && npm run build` (type-check must pass). Green the pytest suite, explicitly confirming the existing grounding/ensemble/projection route tests and any sidebar tests still pass unchanged (FR-028). Run quickstart Q8 by hand via the `run` skill or Chrome tools and report what was seen.
- [ ] T052 [US5] COMMIT "summary_native: Grounding UI page and routes"
- [ ] T053 [US5] REVIEW `/code-review` on T052's commit. Fix and commit.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T054 [P] Write `docs/cli/summary_native_howto.md` (user directive). Cover:
  - what the path is and how it differs from the other three;
  - the input format with a minimal example file;
  - `validate` (the one-pass report, every finding code and how to fix each, the out-of-range section, gaps);
  - choosing a range;
  - `build` and the output layout;
  - possible duplicates: fix the summary files, or record a `not_duplicates` ruling in `canon.yaml`, then re-run; why `canon.yaml` cannot merge;
  - `synth` per doc (upstream flags, `--audit`, `--parts`, `--dump-only`, the backend flags, what `.incomplete.md` means);
  - `compare` and promoting by hand (`cp` after review);
  - every refusal and exit code decoded;
  - a worked OOTA example.
- [ ] T055 [P] Add the how-to to the docs index and the architecture doc:
  - `docs/README.md`: link it in the CLI section;
  - `CLAUDE.md`: add a "Detailed docs" table row for `docs/cli/summary_native_howto.md` and a project-structure line for `pipelines/summary_native/`;
  - `docs/core/architecture.md`: add the fourth rendering path and a "common task → start here" row.
- [ ] T056 Run quickstart Q1–Q6 against the real OOTA corpus. Record the results (timings, counts vs 67/409, byte-stable yes/no) in `specs/031-summary-native-grounding/session-log.md`. Do not edit any summary file. If 070 is still unfixed, report it rather than working around it.
- [ ] T057 COMMIT "docs: summary_native CLI how-to and index links"
- [ ] T058 REVIEW `/code-review` on T057's commit. Fix and commit.
- [ ] T059 Push the branch and open a PR to `main` via `mcp__github__create_pull_request`, linking #499. The body summarises SC status and lists SC-008 as pending GM judgment. Do not merge; wait for the user.

---

## Dependencies & Execution Order

- Setup (T001–T002) → Foundational (T003–T008) → US1 (T009–T018).
- US2 (T019–T030) depends on US1 (it needs a built corpus).
- US3 (T031–T038) depends on US1 only. It touches `validate.py` and `corpus.py`, so run it **after** US2 commits, not concurrently, to keep diffs reviewable.
- US4 (T039–T044) depends on US2 (`context.py`/`synth.py`).
- US5 (T045–T053) — **moved up to run immediately after US2** (orchestrator decision, 2026-10-05). US2's `add_backend_args` makes `summary_native` a model-bearing surface, so the backend-seam guardrails (`tests/test_backend_seam_guardrails.py`, `tests/test_codex_cli_family.py`) require its inventory row and UI-reachability mapping. Those land with the UI face in US5. US3/US4 then extend the page with their own controls.
- Polish (T054–T059) is last.
- Every COMMIT is followed by its REVIEW before the next phase's coding begins.

### Parallel opportunities

- Foundational: T004 ∥ T005 (different files). T006 follows both.
- US1: the tests T009 ∥ T010 ∥ T011 ∥ T012 (one Sonnet agent can write all four, or four agents in one message).
- US2: T019 ∥ T020 ∥ T021 tests; T022 ∥ T023 ∥ T026 implementation.
- US3: T031 ∥ T032.
- US4: T039 ∥ T040.
- US5: T045 ∥ T046 tests; T049 ∥ T050 frontend (separate files from T047/T048).
- Polish: T054 ∥ T055.

### Parallel example (US2)

```text
Agent(model=sonnet): "Write tests T019–T021 per tasks.md; do not implement"
Agent(model=sonnet): "Implement T022 select.py and T026 compare.py"
Agent(model=sonnet): "Write prompts/outlines T023"
→ orchestrator reviews, then one agent does T024–T027 against the tests
```

## Implementation Strategy

- **MVP = US1** (T001–T018): validation, range and the deterministic corpus. It is useful alone (a reviewed chronology and dossiers, zero tokens) and settles the format question with the GM's real corpus before any prompt work.
- **Then US2**: world and campaign state, the core of #499.
- **Then US3**: the duplicate list lets the GM clean the summaries, which improves every later run.
- **Then US4 and US5.**
- Stop after any checkpoint and demo it. SC-008 (GM judgment against the #499 goldens) is assessed by the GM after US2, never claimed by an agent.
