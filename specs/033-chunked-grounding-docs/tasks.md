---
description: "Task list for 033 — Chunked, Code-Checked Grounding Documents"
---

# Tasks: Chunked, Code-Checked Grounding Documents

**Input**: Design documents from `specs/033-chunked-grounding-docs/`: plan.md, spec.md, research.md (R1–R14), data-model.md, contracts/cli.md, contracts/http.md, contracts/session-prep.md, quickstart.md (S1–S7).

**Tests**: Included. The plan names each test file, and the repo enforces its rules with guard tests (no-LLM AST walks, the Secrets canary, router default-literal guards, the no-credential gate). Write each story's tests before its implementation and confirm they fail first.

**Organization**: One phase per user story, in spec priority order. Each story ships its own CLI flags, route parameters and page controls (Principle XI: a capability lands with its face).

**Reference implementation**: the experiment's prototype, `experiments/20261007-chunked-state-docs/`, maps onto the new modules:
- `chunked_state.py` → `notes.py` + `extract.py` + `state_sections.py`
- `npcs_from_dossiers.py` → `key_npcs.py`
- `annotate.py` and the `fixpass.py` detectors → `annotate.py` (the model fixer is **not** ported)
- `prompts/*.md` → `pipelines/summary_native/prompts/state.*.md`

Port behaviour, not structure: the prototype's shortcuts (module globals, hard-coded paths, an OOTA-only range) do not carry over.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US7 from spec.md
- Paths are repo-relative. Read `contracts/*.md` and `data-model.md` for exact shapes before implementing a task that cites them.

## Conventions every task must follow

- **Model calls:** only through `campaignlib` (`client_from_args`, `stream_api`). Never import `anthropic`.
- **Atomic writes:** every write goes through `campaignlib.util.atomic_write_text`.
- **Determinism:** deterministic artifacts use sorted keys and sorted file order, with no timestamps or absolute paths inside code-owned sections (031 `corpus.py` rules).
- **Defaults:** declared once, in `pipelines/summary_native/schema.py`, surfaced via `server/grounding_config_shared.py` (Principle XII). No default literal in `server/routers/summary_native.py`.
- **Exit codes:** 0 ok, 1 blocking validation, 2 refusal, 3 incomplete, 4 model failure.
- **Worktree caveat:** in a worktree, `import campaignlib` may resolve to the main checkout through the editable install. Run tests with `PYTHONPATH=$PWD python -m pytest …`.
- **No API-key probe** anywhere (`tests/test_no_credential_gate.py`).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Constants, prompts and fixtures every story uses.

- [X] T001 Add the 033 constants to `pipelines/summary_native/schema.py`:
  - citation targets `SECTION_TARGETS` (heading → key: Memorable Moments→`moment`, NPCs→`npcs`, Locations→`locations`, Items→`items`, Spells→`spells`, Abilities→`abilities`, Session-End State→`end`) and `STATE_CITE_RE` (research R3);
  - note grammar `THREAD_TAGS`, `WORLD_TAGS`, `STATUSES`, `MAP_SECTIONS` (Events, Concluded, Threads, NPC Status, World, Party);
  - `DEFAULT_EXTRACT_PARALLEL = 6`, `DEFAULT_PROSE_BACKEND = "claude-code"`, `DEFAULT_PROSE_MODEL = "claude-sonnet-5-5"`, `DEFAULT_PROSE_EFFORT = "medium"`;
  - `DEFAULT_WORLD_BUDGETS` (Party 700, Factions and Powers 450, Key NPCs 900, Locations 450, Items and Artifacts 450, Active Threats and Open Pressures 600);
  - `DEFAULT_AUDIT_CANDIDATES = 3`, `STATE_DIR = "state"`, `TIMELINE_FILE = "canon_events_timeline.md"`;
  - the annotation markers `LATER = "⚠ later:"`, `SINCE = "ℹ since:"`, `UNVERIFIED = "⚠ unverified:"`.
- [X] T002 [P] Create `pipelines/summary_native/prompts/state.extract.system.md` from `experiments/20261007-chunked-state-docs/prompts/map.system.md`. **Remove the Audit section entirely** (research R11), and keep the citation-form and verbatim-quote rules.
- [X] T003 [P] Create `pipelines/summary_native/prompts/state.prose.system.md` and `state.prose_world.system.md` from the experiment's `reduce.system.md` / `reduce_world.system.md`. Add the quotation rule: "quotation marks only around words spoken or written in the summaries, never around note text" (research R8).
- [X] T004 [P] Create `pipelines/summary_native/prompts/state.npc_lines.system.md` (from the experiment) and `state.audit.system.md`. The audit prompt covers one item, its candidate chapters only, and a SHOWN/NOT SHOWN answer, where SHOWN requires `[ch NNN / target]` plus a verbatim quoted span.
- [X] T005 [P] Extend the fixtures under `tests/fixtures/summary_native/`:
  - a 4-chapter range where chapter 4 makes an NPC's chapter-2 status stale;
  - a mentioned NPC whose status changes after the citing claim;
  - a player character named in a fixture `players.yaml`;
  - a registry with a two-form NPC (`Ilvara` / `Ilvara Mizzrym`);
  - one published dossier (`docs/npcs/<slug>.md` with a `verify: pass` provenance header and a `## Secrets` section holding the canary `SECRET-CANARY-033`), and one NPC with no dossier;
  - a two-item `docs/tracking/tracking.txt`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared primitives and config every story depends on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T006 Generalise `make_chunks` in `pipelines/summary_native/npc_chunked.py` to accept any sequence of objects with `.number` and `.text`. Existing NPC callers must be unchanged: run `tests/test_summary_native_npc_chunked.py` and keep it green.
- [X] T007 Create `pipelines/summary_native/notes.py` (deterministic) with the shared primitives:
  - `load_chapters(summaries_dir, since, until)`, giving `.number`, `.text` and `.targets` (scene ids plus section keys present);
  - `cites(text)`, with heading-text → key normalisation, any case, exact lookup, unknown headings invalid;
  - `cite_problem(text, allowed)`;
  - `bad_span(text, hay)`, reusing `npc_check.SPAN_RE` / `strip_quote_marks` / `_contains`;
  - `claims_of(text)`, splitting after each citation bracket;
  - `first_chapter(text)`.

  Port from the prototype's `chunked_state.py` and `fixpass.py`.
- [X] T008 [P] Add `extract` and `prose` blocks to `SummaryNativeRun` in `server/grounding_config_shared.py`:
  - `extract: {backend, model, chunk_chars}` and `prose: {backend, model, effort, budgets}`;
  - strict (`extra="forbid"`), with defaults from T001's constants;
  - **no `endpoints` and no `fallback_npc_lines` keys**.

  Expose them via `pipelines/summary_native/resolve.py`, with precedence flag > config > schema.
- [X] T009 [P] Extend `pipelines/summary_native/freshness.py` with `check_notes_fresh(range_dir, …)`. It compares `state/notes/manifest.json` against the corpus manifest, registry and `players.yaml` sha256, and returns a refusal message naming the command to re-run. Also add `check_audit_fresh(range_dir, track_files)`: `state/audit/items.json` against the track files' sha256 and the notes manifest. A changed track file makes `synth campaign_state` refuse to render a stale Audit section, naming `summary_native audit`. Dossiers are deliberately not hashed: `synth world_state` reads them live at build time, and the run record keeps their sha256 for comparison.
- [X] T010 [P] Add `notes`, `state_sections`, `key_npcs`, `annotate` and `audit_select` to `GUARDED` in `tests/test_summary_native_no_llm.py`, and assert `extract`, `synth` and `audit` are not guarded (they are the model steps).
- [X] T011 [P] Extend `tests/test_summary_native_config_defaults.py`:
  - the new blocks' defaults equal the `schema.py` constants;
  - `extract.endpoints` and `fallback_npc_lines` are refused as unknown keys;
  - the router contains no default literal for the new parameters.

**Checkpoint**: Foundation ready. User stories can now start.

---

## Phase 3: User Story 1 - Build both documents from checked notes (Priority: P1) 🎯 MVP

**Goal**: `extract` writes code-checked notes, and `synth world_state|campaign_state` builds both drafts from them: code-owned timeline, completed list and NPC status table, plus model prose per section.

**Independent Test**: quickstart S1–S2 on the OOTA copy, plus the fixture tests below. Re-running from cached notes produces byte-identical code-owned sections.

### Tests for User Story 1

- [X] T012 [P] [US1] `tests/test_summary_native_notes.py`:
  - each drop reason (uncited, invalid-citation, outside-chunk, quoted-span-not-found, missing-thread-tag, missing-world-tag, malformed-row, nested-bullet);
  - `[ch 031 / NPCs]` accepted as `npcs`, and `[ch 031 / Factions]` rejected;
  - the outlier-chunk flag (>3× median and ≥20 drops);
  - cache keys change when any input changes.
- [X] T013 [P] [US1] `tests/test_summary_native_state_sections.py`:
  - timeline in chapter order, deduplicated;
  - `Ilvara` + `Ilvara Mizzrym` → one row, Dead (latest known);
  - a later `Unknown` shown beside the known status;
  - a PC row dropped;
  - a form claimed by two entities left unresolved and marked ⚠;
  - byte-identical output across two runs.
- [X] T014 [P] [US1] `tests/test_summary_native_extract.py`, with a fake client returning canned chunk outputs:
  - prompts contain no audit list;
  - each chunk is written to `state/notes/`;
  - a failed chunk gives exit 3, and the next run re-extracts only it;
  - a cached run makes zero calls.
- [X] T015 [P] [US1] Extend `tests/test_summary_native_synth.py` and `tests/test_summary_native_cli.py`:
  - `synth world_state` without notes refuses (exit 2), naming the `extract` command;
  - `--parts` refuses for world_state and campaign_state;
  - `--audit` refuses for campaign_state, naming `summary_native audit`;
  - party and planning keep the one-shot path;
  - a missing prose section writes `*.incomplete.md` (exit 3).

### Implementation for User Story 1

- [X] T016 [US1] Implement the code check in `pipelines/summary_native/notes.py`:
  - `check_chunk(raw, chunk) -> CheckedChunk` (kept notes by kind, drops, status rows);
  - `render_drops_md(...)`, with the outlier flag;
  - `cache_key(...)`;
  - routing helpers `stitched(results, kind, tag=None)` and `thread_ledger(results)`.

  Shapes are in data-model.md (Note, Drop record).
- [X] T017 [US1] Implement `pipelines/summary_native/extract.py` (model step), in single-endpoint form first. It:
  - builds chunks via `npc_chunked.make_chunks`;
  - renders the prompt from `state.extract.system.md`;
  - calls through `client_from_args`/`stream_api` with one retry;
  - writes `chunkNN.{aaa-bbb}.{user,out}.md`, `.checked.json`, `drops.md` and `manifest.json`;
  - writes `state/runs/<stamp>/record.json`;
  - supports `--dump-only` and `--force`.
- [X] T018 [US1] Implement in `pipelines/summary_native/state_sections.py`:
  - `timeline_md(results)` and `completed_md(results)`;
  - `npc_status_table(results, forms, pcs) -> (table_md, report_md)`, with registry identity loaded via `campaignlib.registry` (exact casefolded name/alias, ambiguous forms unresolved) and PCs via `campaignlib.players_config`;
  - `npc_status_report.md`.

  Port from the prototype's `npc_table` / `load_identity`.
- [X] T019 [US1] Add the chunked path to `pipelines/summary_native/synth.py` for world_state and campaign_state:
  - load and freshness-check the notes;
  - build the code-owned sections;
  - route notes to the prose sections (research R8), one prose call per section via `render_part`;
  - check each output with `check_outline`;
  - assemble the drafts into `state/drafts/`, with `*.incomplete.md` on a missing section.

  Party and planning keep the one-shot path.
- [X] T020 [US1] Wire the CLI in `pipelines/summary_native/cli.py`:
  - add the `extract` subcommand with flags per `contracts/cli.md` (backend family via `add_backend_args`, `--chunk-chars --max-tokens --dump-only --force`);
  - route `synth world_state|campaign_state` to the chunked path;
  - add the `--parts` / `--audit` refusals;
  - print the per-chunk progress lines and the totals.
- [X] T021 [US1] Add `GET /run/extract` to `server/routers/summary_native.py`, with params per `contracts/http.md` (range, `chunk_chars`, `max_tokens`, `dump_only`, `force`, model selection). Update `GET /run/synth/{doc}` to reject `parts` / `audit` for these two docs with the CLI's message. Extend `/state` with the `extract` block and `/drafts` with `drops.md` and `npc_status_report.md`.
- [X] T022 [US1] Add an "Extract" step to `frontend/src/views/grounding/SummaryNative.vue`: run / dump-only / force, per-chunk kept and dropped counts, outlier chunks highlighted, a link to `drops.md`. Wire the synth steps to the new behaviour.
- [X] T023 [P] [US1] Extend `tests/test_summary_native_routes.py`: the `/run/extract` argv, and the 400s for `parts` / `audit` on the two docs.

**Checkpoint**: Both drafts build from checked notes. This is the MVP.

---

## Phase 4: User Story 2 - A world_state that fits beside the other prep documents (Priority: P1)

**Goal**: world_state prose within per-section budgets; every note kept verbatim in reference files; the timeline in its own file; the reading contract first.

**Independent Test**: quickstart S2's world_state checks: budgets, reference links, the timeline file, and the contract first.

### Tests for User Story 2

- [X] T024 [P] [US2] Extend `tests/test_summary_native_state_sections.py`:
  - reference files hold every kept note verbatim, grouped by subject, sorted;
  - the timeline is a separate file and world_state's section points to it;
  - the reading contract is the first block and names the markers and paths.
- [X] T025 [P] [US2] Extend `tests/test_summary_native_synth.py`:
  - a budget overrun is reported in the run record and the text is not truncated;
  - budgets are read from config, then schema;
  - the world_state prose prompt carries `WORD BUDGET` and the quotation rule.

### Implementation for User Story 2

- [X] T026 [US2] Add `reference_files(results) -> {kind: md}` and `reading_contract(range, paths) -> md` to `pipelines/summary_native/state_sections.py`, and write `drafts/reference/{factions,npcs,locations,items,threats,threads}.md` and `drafts/canon_events_timeline.md` (FR-013, including the thread ledger). The reading contract lists all six files. campaign_state's two thread sections point to `reference/threads.md`. Port the contract text from the prototype's `annotate.py`, with "not verbatim" wording (research R10).
- [X] T027 [US2] In `pipelines/summary_native/synth.py`:
  - use `state.prose_world.system.md` with per-section budgets for world_state;
  - count words excluding citations, and record overruns;
  - append each section's `_Full notes: reference/<kind>.md_` pointer;
  - put the contract at the top of world_state.
- [X] T028 [US2] Extend the `/drafts` listing in `server/routers/summary_native.py` with the timeline and `reference/*.md`. Add links to them in `frontend/src/views/grounding/SummaryNative.vue`, and show the budget report after a world_state synth.

**Checkpoint**: world_state is loadable for session prep.

---

## Phase 5: User Story 3 - Key NPCs come from the published dossiers (Priority: P2)

**Goal**: world_state's Key NPCs is rendered from published, verified dossiers. The build refuses by default when one is missing, and `--fallback-npc-lines` writes code-built lines instead (GM ruling, 2026-10-07).

**Independent Test**: quickstart S3, plus the Secrets canary.

### Tests for User Story 3

- [X] T029 [P] [US3] `tests/test_summary_native_key_npcs.py`:
  - selection uses 031 rules, and PCs are never selected;
  - `published_view()` returns only the name, header facts, Identity and Last Observed State;
  - `entry` citations map to `npcs`;
  - a failing model line falls back to the dossier's first cited sentence;
  - an extra or reordered line from the model is discarded;
  - each line ends `→ docs/npcs/<slug>.md`;
  - the refusal message names each NPC as `not drafted` / `failed verification (<checks>)` / `drafted, not published`;
  - `--fallback-npc-lines` writes a code-built line ending `(no published dossier — from checked notes)` with only checked-note citations.
- [X] T030 [P] [US3] `tests/test_state_docs_no_secrets.py`: `SECRET-CANARY-033` appears in no draft, no reference file and no `state/runs/*/*.md`. A static check asserts `key_npcs.py` never reads past `## Last Observed State` into `## Secrets` (no code path names the Secrets heading).

### Implementation for User Story 3

- [X] T031 [US3] Implement `pipelines/summary_native/key_npcs.py` (deterministic):
  - `published_dossiers(campaign, range)`, which reads the provenance header (`source: summary_native`, range, `verify: pass`);
  - `published_view(path)`;
  - `select_key_npcs(...)`, via `select.select_dossiers` over global NPCs;
  - `missing_dossier_states(...)`, from `<npc_root>/<range>/draft/*.verify.md` and `<npc_root>/publish_log.json`. `<npc_root>` is resolved in `pipelines/summary_native/cli.py` by the existing `_npc_root(args, root, config_path)` (`--npc-root` > `npc_dossiers.yaml npc_root` > `schema.DEFAULT_NPC_ROOT`) and passed into `key_npcs` as an argument. `key_npcs` never reads config itself. `synth world_state` therefore also accepts `--npc-root`, with the same spelling as the `npc-*` commands;
  - `verify_line(...)`, `fallback_from_dossier(...)` and `fallback_from_notes(...)`.

  Port from the prototype's `npcs_from_dossiers.py`.
- [X] T032 [US3] In `pipelines/summary_native/synth.py` (world_state):
  - refuse (exit 2) with the missing-dossier list, unless `--fallback-npc-lines`;
  - make one Key NPCs model call (`state.npc_lines.system.md`), then check and substitute lines;
  - report substitutions and fallbacks.
- [X] T033 [US3] Add `--fallback-npc-lines` (world_state only) to `pipelines/summary_native/cli.py`. Add the `fallback_npc_lines` route param to `/run/synth/{doc}` in `server/routers/summary_native.py` (400 for other docs). In `frontend/src/views/grounding/SummaryNative.vue`, add the unpersisted checkbox (reset on load) and render the refusal's NPC list with a link to the NPC dossiers page.

**Checkpoint**: Key NPCs is dossier-sourced, with no silent gaps.

---

## Phase 6: User Story 4 - Stale lines are annotated, never rewritten (Priority: P2)

**Goal**: The detectors append later evidence under a line. Code removes only a player character in an NPC section, and no model rewrites anything.

**Independent Test**: quickstart S4.

### Tests for User Story 4

- [X] T034 [P] [US4] `tests/test_summary_native_annotate.py`:
  - stale → `⚠ later:` with the later note verbatim;
  - a per-claim status change → `ℹ since:` (caught even when another claim on the line cites a later chapter);
  - **no** flag when the mentioned NPC has no earlier status row;
  - cross-section → `⚠ later: see …`;
  - non-verbatim quote / invalid citation → `⚠ unverified:`;
  - a PC in Key NPCs/Companions is removed;
  - Key NPCs and the code-owned sections (Completed, NPC Current States, Audit) produce no annotations, even when a later note exists for their subjects;
  - `annotations.md` lists every hit;
  - `--dry-run` writes nothing.
- [X] T035 [P] [US4] `tests/test_annotate_never_rewrites.py`: for every non-removed line, the annotated document's line text equals the pre-annotation line, and re-annotating replaces the old sub-bullets rather than stacking them.

### Implementation for User Story 4

- [X] T036 [US4] Implement `pipelines/summary_native/annotate.py` (deterministic). It ports the prototype's `fixpass.detect` and `annotate.annotations_for`, drops the reviewer and fixer, and provides `parse_entries`, `detect`, `apply_annotations` (replacing existing annotation sub-bullets) and `render_report`. **Skip list (FR-019):** `parse_entries` yields no entries from world_state's Key NPCs or from the code-owned sections (Canon Events Timeline pointer, Completed Encounters & Quests, NPC Current States, Audit: Tracking Claims). The player-character removal still applies to Party's Companions group.
- [X] T037 [US4] Call `annotate` at the end of the chunked `synth` in `pipelines/summary_native/synth.py`. Add the standalone `annotate world_state|campaign_state [--dry-run]` subcommand to `pipelines/summary_native/cli.py`.
- [X] T038 [US4] Add `GET /run/annotate/{doc}` to `server/routers/summary_native.py` (`dry_run`), plus `annotations` counts in `/state` and `annotations.md` in `/drafts`. Add an "Annotate" action with a dry-run preview to `frontend/src/views/grounding/SummaryNative.vue`.

**Checkpoint**: Drafts carry their own corrections as evidence.

---

## Phase 7: User Story 5 - Choose where each step runs (Priority: P2)

**Goal**: Separate backends for extraction and prose; several Spark endpoints on one queue with preflight; resumable caching; nothing gated on an API key.

**Independent Test**: quickstart S1 with two endpoints, then a prose-only rebuild with zero extraction calls.

### Tests for User Story 5

- [X] T039 [P] [US5] Extend `tests/test_summary_native_extract.py`:
  - shared queue across two fake endpoints: every chunk runs exactly once, and a slow endpoint takes fewer chunks;
  - preflight refuses an unreachable endpoint and one serving another model, before any call;
  - `--endpoints` with a non-dgx backend refuses;
  - the record names each chunk's endpoint.
- [X] T040 [P] [US5] Extend `tests/test_summary_native_synth.py`:
  - the prose backend, model and effort resolve flag > `grounding.yaml summary_native.prose` > schema;
  - `--claude-code-effort` is passed through;
  - a prose-only rebuild makes no extraction call.
- [X] T041 [P] [US5] Confirm `tests/test_no_credential_gate.py` still passes, and add `extract`, `synth` and `audit` to whatever module list it scans.

### Implementation for User Story 5

- [X] T042 [US5] Add the multi-endpoint shared queue to `pipelines/summary_native/extract.py`: per-endpoint worker threads pulling from one queue, `preflight(endpoints, model)` against `/v1/models`, and endpoint recording. Add `--endpoints` (same spelling as `facts_to_state`) and `--parallel` to `extract` in `pipelines/summary_native/cli.py`. Port from the prototype's `run_pool` / `preflight`.
- [X] T043 [US5] Resolve the extraction and prose backends from the config blocks in `pipelines/summary_native/resolve.py`, and use them in `extract.py` and `synth.py`. The prose step uses the backend family (`--backend --model --claude-code-effort`).
- [X] T044 [US5] Add `endpoints: list[str]` and `parallel` to `/run/extract`, and prose model and effort selection to `/run/synth/{doc}`, in `server/routers/summary_native.py`. In `frontend/src/views/grounding/SummaryNative.vue`, add a multi-entry endpoints field and workers to the Extract step, and model and effort to the synth steps.
- [X] T045 [P] [US5] Extend `tests/test_summary_native_routes.py`: the `endpoints` argv as `--endpoints A B`, `parallel`, and the prose selection argv.

**Checkpoint**: The experiment's split (Spark extraction, hosted prose) is the configured default.

---

## Phase 8: User Story 6 - The tracking audit is its own step (Priority: P3)

**Goal**: `summary_native audit`: code picks candidate chapters, the model judges one item at a time, and code accepts SUPPORTED only with a cited verbatim span.

**Independent Test**: quickstart S5.

### Tests for User Story 6

- [X] T046 [P] [US6] `tests/test_summary_native_audit.py`:
  - items numbered from `- ` lines;
  - candidate chapters picked by registry forms and non-generic tokens, at most `--candidates`, deterministic;
  - no candidates → NOT FOUND (no-candidates) with zero calls;
  - SUPPORTED with a citation outside the candidates, or a non-verbatim span → `unverified`, counted NOT FOUND;
  - verdicts cached per item;
  - campaign_state's Audit section renders from `audit.json`, or reads "Audit not run for this range.".

### Implementation for User Story 6

- [X] T047 [US6] Implement `pipelines/summary_native/audit_select.py` (deterministic): `load_items(track_files)`, `candidate_chapters(item, chapters, forms, wordlist, n)` (using `npc_forms.load_wordlist` for generic words), `check_verdict(...)` and `render_audit_md(...)`.
- [X] T048 [US6] Implement `pipelines/summary_native/audit.py` (model step). It makes one call per item via `client_from_args`/`stream_api`, using the extraction backend family and the multi-endpoint queue from T042, with per-item cache keys, `state/audit/{items,audit}.json` and `audit.md`, and a run record.
- [X] T049 [US6] Add the `audit` subcommand to `pipelines/summary_native/cli.py`, with `--track-file` (repeatable, same spelling as `campaign_state`), `--candidates`, the backend family, `--endpoints --parallel --dump-only --force`, defaulting to `grounding.yaml campaign_state.track_files`. Render the Audit section from `audit.json` in `pipelines/summary_native/state_sections.py`.
- [X] T050 [US6] Add `GET /run/audit` to `server/routers/summary_native.py`, plus an `audit` block in `/state` and `audit.md` in `/drafts`. Add an "Audit" step to `frontend/src/views/grounding/SummaryNative.vue` (track files prefilled from config and editable per run, candidates, model, run / dump-only / force).
- [X] T051 [P] [US6] Extend `tests/test_summary_native_routes.py`: the `/run/audit` argv, including repeated `--track-file`.

**Checkpoint**: The audit is accurate and out of the extraction step.

---

## Phase 9: User Story 7 - Session prep reads the documents as an index (Priority: P3)

**Goal**: The documents satisfy `contracts/session-prep.md`; the contract is documented for the gm-assistant skill.

**Independent Test**: quickstart S7.

- [X] T052 [US7] Add a test in `tests/test_summary_native_state_sections.py` asserting the guarantees from `contracts/session-prep.md` on the fixture drafts: every line of both documents carries at least one resolving citation; world_state's contract names the markers, citation grammar, timeline and reference paths; and every Key NPCs line has a dossier pointer or the fallback mark.
- [X] T053 [US7] Write the operator-facing session-prep contract section in `docs/cli/summary_native_howto.md`, linking `specs/033-chunked-grounding-docs/contracts/session-prep.md` and the draft skill `experiments/20261007-chunked-state-docs/skills_variant/gm-session-prep-pointer/SKILL.md`.
- [X] T054 [US7] File the gm-assistant follow-up issue ("adopt the docs-as-index contract in gm-session-prep") with the GitHub MCP tools, and record its URL in `specs/033-chunked-grounding-docs/plan.md` under Follow-ups.

**Checkpoint**: Every story is independently functional.

---

## Phase 10: Polish & Cross-Cutting Concerns

- [X] T055 [P] Update `docs/cli/summary_native_howto.md`: the four-step chunked build (extract → synth → annotate → audit), every refusal and exit code from `contracts/cli.md`, the missing-dossier ruling, and promotion (copying the drafts, the timeline and `reference/` into `docs/`).
- [X] T056 [P] Update `docs/core/architecture.md` (the `state/` layout and the four steps) and `docs/README.md` (index entry).
- [X] T057 [P] Add a short "Grounding docs are an index; summaries are the authority" rule to the Critical rules of `CLAUDE.md`, citing the annotation markers and `tests/test_annotate_never_rewrites.py`.
- [X] T058 [P] Create `tests/test_state_docs_no_live_writes.py` (FR-028; same idea as 032's `test_no_writes_to_authored.py`). On a copy of the fixture campaign, run `extract`, `synth world_state`, `synth campaign_state`, `annotate` (both docs) and `audit` with a fake model client. Assert that the whole live `docs/` tree (including `docs/npcs/`) and the 031 corpus files (`manifest.json`, `chronology.md`, `memorable_moments.md`, `dossiers/`) are byte-identical before and after, and that every new file is under `<range>/state/`.
- [X] T059 [P] Add Playwright coverage in `frontend/e2e/summary-native-state.spec.ts` (the plan's Testing section), with the routes mocked:
  - the Extract, Audit and Annotate steps render and issue the documented route parameters (including repeated `endpoints` and `track_file`);
  - the "Write fallback lines" checkbox is unchecked on load and resets after a reload;
  - a missing-dossier refusal renders its list of NPCs and states with a link to the NPC dossiers page.

  Use the same browser-path workaround #504 needed if the installed headless shell's version differs.
- [X] T060 Run the full suite (`PYTHONPATH=$PWD python -m pytest tests/`). Any failures must be only the pre-existing ones on main.
- [X] T061 Run quickstart S1–S7 on the OOTA copy and record the measured results against SC-001…SC-009 in `specs/033-chunked-grounding-docs/quickstart.md` under `## Validation`.
- [ ] T062 After merge, reinstall the console script into the server venv (`uv pip install -e . --python ~/.venv/bin/python`) so the page's new routes find `summary_native`'s subcommands.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: depends on Setup and blocks every story.
- **US1 (Phase 3)**: depends on Foundational. It is the MVP; all later stories build on its notes and drafts.
- **US2 (Phase 4)**: depends on US1 (it shapes world_state's assembly).
- **US3, US4, US5 (Phases 5–7)**: each depends on US1. They are independent of each other, apart from the shared files noted below.
- **US6 (Phase 8)**: depends on US1 (notes freshness, campaign_state assembly), and reuses US5's queue (T042).
- **US7 (Phase 9)**: depends on US2–US4 (the guarantees it asserts come from them).
- **Polish (Phase 10)**: after the desired stories.

### Shared files (serialise edits)

- `pipelines/summary_native/synth.py`: T019, T027, T032, T037, T043
- `pipelines/summary_native/cli.py`: T020, T033, T037, T042, T049
- `server/routers/summary_native.py`: T021, T028, T033, T038, T044, T050
- `frontend/src/views/grounding/SummaryNative.vue`: T022, T028, T033, T038, T044, T050

### Within each story

Tests first, and they must fail before implementation. Then the deterministic module, then the model-step module, then the CLI, then the route, then the page.

---

## Parallel Examples

```text
# Phase 1, together
T002 extract prompt · T003 prose prompts · T004 npc-lines + audit prompts · T005 fixtures

# Phase 2, together after T006/T007
T008 config blocks · T009 freshness · T010 no-LLM guard · T011 config-defaults test

# User Story 1 tests, together
T012 notes · T013 state_sections · T014 extract · T015 synth/cli

# After US1: US3, US4 and US5 can proceed in parallel; their new modules (key_npcs, annotate, extract queue)
# are separate files, and only their synth/cli/router/page edits are serialised.
```

---

## Implementation Strategy

### MVP first (User Story 1, then 2)

1. Phases 1–2.
2. US1: both drafts from checked notes, with code-owned precision sections. **Stop and validate** with quickstart S1–S2.
3. US2: makes world_state loadable for prep. Together with US1, this is the first useful delivery.

### Incremental delivery

- **US3** (dossier Key NPCs) and **US4** (annotations) close the accuracy gaps the experiment found.
- **US5** turns on the measured fast configuration (Spark extraction, hosted prose).
- **US6** fixes the audit.
- **US7** documents the contract for session prep.
- Each story is validated by its own quickstart scenario before the next starts.

## Notes

- Every task names its files; [P] tasks touch different files with no incomplete dependency.
- Commit after each task or logical group, on the feature branch. Never commit to main.
- The prototype is evidence, not code to copy wholesale. Port its behaviours with their tests, and leave the model fixer behind.
