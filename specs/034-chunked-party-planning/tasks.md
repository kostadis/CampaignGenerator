---
description: "Task list for 034 — Chunked, Code-Checked Party and Planning Documents"
---

# Tasks: Chunked, Code-Checked Party and Planning Documents

**Input**: Design documents from `specs/034-chunked-party-planning/`:
- plan.md and spec.md;
- research.md (R1–R16) and data-model.md;
- contracts/cli.md and contracts/http.md;
- quickstart.md (S0–S7).

**Tests**: Included. The repo enforces its rules with guard tests (no-LLM AST walks, the Secrets canary, never-rewrites, router default-literal guards, the no-credential gate). Write each story's tests first and confirm they fail.

**Organization**: one phase per user story. **Phase order is US1 → US3 → US2 → US4 → US5 → US6**, because planning's Active Plots (US2) needs thread attachment (US3). Labels keep the spec's story numbers. Each story ships its own flags, routes and page controls (Principle XI).

**Process**: Opus orchestrates and reviews; a Sonnet subagent implements each phase in this worktree, and the reviewer checks it before the next phase starts.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US6 from spec.md
- Paths are repo-relative. Read `data-model.md` and `contracts/*.md` for exact shapes before implementing a task that cites them.

## Conventions every task must follow

- **Model calls:** only through `campaignlib` (`client_from_args`, `stream_api`, `synth.render_part`). Never import `anthropic`.
- **Writes:** through `campaignlib.util.atomic_write_text`.
- **Determinism:** code-owned sections are deterministic: sorted keys, stable order, no timestamps or absolute paths.
- **Defaults:** declared once in `pipelines/summary_native/schema.py` and surfaced via `server/grounding_config_shared.py`. No default literal in a router.
- **Exit codes:** 0 ok, 1 blocking, 2 refusal, 3 incomplete, 4 model failure.
- **Identity:** exact casefolded name or alias only (registry `forms`, `norm_title`). No similarity matching anywhere.
- **Worktree caveat:** run tests with `PYTHONPATH=$PWD python -m pytest …`, because the editable install can resolve `campaignlib` to the main checkout. Run them with no `CG_BACKEND` in the environment.
- **Backend guard:** shell commands that mention party, planning, campaign_state or summary_native need a `CG_BACKEND=claude-code` prefix to pass the local backend-guard hook (harmless when no model is called).
- **No API-key probe** anywhere.
- **Secrets:** never read `## Secrets` into a prompt or output.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Constants, the thread-registry seam, prompts and fixtures.

- [X] T001 Add the new constants to `pipelines/summary_native/schema.py` (data-model "Defaults"):
  - `DEFAULT_PARTY_BUDGETS = {"Party Overview": 300, "Characters": 500, "Party Dynamics": 300}` (Characters is per character);
  - `DEFAULT_PLANNING_BUDGETS = {"NPC Dossiers": 1500, "Faction States": 600, "Active Plots": 1200, "DM Notes": 400}`;
  - `DEFAULT_MAX_FACTIONS = 20`, `DEFAULT_THREAD_PROPOSE_MAX_INPUT_CHARS = 150000`;
  - `PARTY_SUBJECT = "Party"`, `LEVEL_TAG = "LEVEL"`;
  - `NO_RATIFIED_THREADS = "_No ratified thread has notes in this range._"`;
  - `DORMANT_HEADING = "### Dormant threads"`;
  - `UNRATIFIED_HEADING = "### Unratified thread notes (not yet ruled on)"`;
  - `DM_NOTES_LABEL = "_Suggestions for the GM, not events._"`.

  Do **not** change `STATE_DOCS` yet; T012 does that.
- [X] T002 [P] Create `campaignlib/thread_registry.py` holding `norm_title`, `match_thread`, `find_thread`, `load_registry`, `check_registry`, `STATUSES` and `CHANGES`, **moved** from `pipelines/grounding/thread_registry.py`. Make the CLI module import them from there (no copies), and keep `tests/test_thread_registry.py` green. Add `match_threads(data, title) -> list[dict]`, which returns every thread a title or alias matches, so callers can detect ambiguity (research R4).
- [X] T003 [P] Create the prompts in `pipelines/summary_native/prompts/`:
  - `state.party.system.md`: character, overview and dynamics sections; the model writes the body only, with no `###` heading and no level line; sheet claims the notes don't support go under `Unsupported by the summaries:`; the quotation rule; the citation rule.
  - `state.planning.system.md`: faction blocks (`### Name` per faction, in the given order), active-plot entries (one `### Title` per given thread, in the given order) and DM Notes (each line cited, framed as suggestions).
  - `state.planning_npcs.system.md`: one `### Name` block per NPC with `Status and location:`, `Goals:` and `Relationships:` lines, citing only that NPC's dossier.
  - `state.arc.system.md`: lines of the form `- <event> [cite] — trigger: "<verbatim trigger>"`; never a value, total or threshold.
  - `state.thread_propose.system.md`: JSON output `{"groups":[{"kind":"new","title":…,"members":[ids]},{"kind":"continues","thread":id,"members":[ids]}]}`; group only notes about the same thread; leave a note out rather than guess.

  Mirror `state.prose_world.system.md`'s evidence rules.
- [X] T004 [P] Extend `tests/fixtures/summary_native/` (research R16):
  - **checked-note set:** party notes for two player characters, one companion (`Ront`), one unattributed (`Dazz`), `**Party**` notes, `[LEVEL] **Party** — 9` whose cited scene says "the party reaches 9th level", and a `[LEVEL]` row citing only "a 4th-level slot";
  - **thread notes:** two that name one thread differently, plus a resolved one;
  - **`docs/thread_registry.yaml`:** two ratified threads, one with an alias, and one thread GM-set to `resolved`;
  - **`config/planning.yaml`:** one tracked NPC with an arc-score mechanic file, and one trackless faction;
  - **`config/party.yaml`:** two characters, one with an arc score, one trackless;
  - **a published dossier** with `## Personality and Motivations`, `## Relationships` and a `## Secrets` holding `SECRET-CANARY-034`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The party grammar, note ids, the per-document contract, and routing party/planning into the chunked synth. Every story needs these.

- [X] T005 Write failing tests in `tests/test_summary_native_notes.py`:
  - a party bullet without a leading `**Subject**` drops with `missing-party-subject`;
  - `- **Daz** — …` keeps with `subject == "Daz"`;
  - `- [LEVEL] **Party** — 9 [cite]` keeps with `level == 9` when the cited text has "9th level", "level 9", "ninth level" or "level nine";
  - it also keeps when the cited text has "Party levels to 9" or "the party levels up to 9";
  - the same row drops `level-not-in-cited-text` when the cited text only has "4th-level slot" or "9th-level spell";
  - `note_id` is stable for identical (first_chapter, kind, text) and differs otherwise.
- [X] T006 Implement in `pipelines/summary_native/notes.py`:
  - party-subject parsing (reuse `_SUBJECT_RE`'s shape: optional `[LEVEL]` tag, then `**Subject**`);
  - `Note.subject` / `Note.tag` / `Note.level` for party notes;
  - the level confirmation: digit, word or ordinal forms of N, in `level N` / `Nth level` / `Nth-level` / `levels? (?:up )?to N` / `reach(?:es|ed)? (?:level )?N`, not followed by `spell`, `spells` or `slot`, searched within the cited sections' text;
  - the drop reasons `MISSING_PARTY_SUBJECT` and `LEVEL_NOT_IN_CITED_TEXT`;
  - `note_id(note) = "n-" + sha1(f"{first_chapter:03d}|{kind}|{text}")[:10]`, exposed on `Note` (research R6).

  Keep `stitched("party")` returning the same text form, so world_state and campaign_state are unchanged.
- [X] T007 Rewrite the `## Party` section of `pipelines/summary_native/prompts/state.extract.system.md` to the R1 grammar: `- **Subject** — fact [cite]`, where Subject is one character's name or exactly `Party`, and level as `- [LEVEL] **Subject** — N [cite]`. Then add a test in `tests/test_summary_native_extract.py` that the cache key changes when this prompt changes (no stale reuse, FR-002).
- [X] T008 [P] Add `freshness.check_party_grammar(range_dir)` in `pipelines/summary_native/freshness.py`. It compares the notes manifest's extraction-prompt sha with the current prompt and returns the contracts/cli.md refusal text ("the party notes predate the subject grammar; run `summary_native extract …`"). Test it in `tests/test_summary_native_notes.py`.
- [X] T009 Generalise `state_sections.reading_contract(rng, paths, doc)` in `pipelines/summary_native/state_sections.py` (research R13):
  - the dossier paragraph names `## Key NPCs` (world_state) or `## NPC Dossiers` (planning), and is omitted for party and campaign_state;
  - a planning-only paragraph covers the ratified and unratified layers of Active Plots and where the proposals queue lives;
  - the reference list names only that document's files: party → `reference/party.md`; planning → `reference/{factions,npcs,threads}.md`; world_state → as today.

  Update the existing callers. Extend `tests/test_summary_native_state_sections.py`: world_state's contract is byte-identical to before, and the party/planning contracts are as specified.
- [X] T010 [P] Add `party_budgets` and `planning_budgets` to `SummaryNativeProse` in `server/grounding_config_shared.py`. Both are strict: keys must come from the schema defaults, values must be ≥ 1, and the defaults come from `schema`. Extend `tests/test_summary_native_config_defaults.py`.
- [X] T011 [P] Add `key_npcs.planning_view(path)` in `pipelines/summary_native/key_npcs.py`. It uses the same one-pass held-heading parser as `published_view`, with the take-set `("## Identity", "## Personality and Motivations", "## Last Observed State", "## Relationships")`, and raises `NotPublished` likewise. Extend `tests/test_state_docs_no_secrets.py`: `planning_view` of the canary dossier contains no `SECRET-CANARY-034`, and `## Secrets` is absent from every take-set.
- [X] T012 Route party and planning through `run_state_synth` in `pipelines/summary_native/synth.py`:
  - in `schema.py`, set `STATE_DOCS = DOCS`, and make `draft_dir` return `state/drafts` for every document;
  - in `run_state_synth`, dispatch to per-document section builders (`_party_jobs`, `_planning_jobs`, to be filled in by US1/US2) and pass the doc to `reading_contract`;
  - call `check_party_grammar` before building party or planning.

  The one-shot body stays in place but unreachable until T048 deletes it. Update `tests/test_summary_native_synth.py` expectations for the draft path.

**Checkpoint**: notes carry a party subject and checked levels; party/planning reach the chunked synth (sections still empty); world_state and campaign_state tests are green.

---

## Phase 3: User Story 1 - Build party from checked notes (Priority: P1) 🎯 MVP

**Goal**: `synth party` writes a reading contract, one section per configured player character (code-built level line, body from that character's notes and sheet only), Party Overview and Party Dynamics, `reference/party.md` and `party_report.md`.

**Independent Test**: the spec US1 test. On fixtures: one `###` per `party.yaml` character in config order; `Level: 9 [cite]`; Ront only in Companions; `Dazz` listed unattributed; a character with no notes says so; a rebuild leaves the code-built lines byte-identical.

### Tests for User Story 1

- [X] T013 [P] [US1] `tests/test_summary_native_party.py` — `party_notes.attribute`:
  - `Party` → party-wide; a PC subject → that PC; `Daz and Zalthir` (no such entity) → both PCs; a registry entity named `Topsy and Turvy` → one companion, not split;
  - a registry-known NPC → companion; an unknown subject → unattributed with a reason;
  - a subject claimed by two entities → unattributed ("claimed by more than one entity");
  - `party.yaml` names and `players.yaml` `plays` both count as player characters.
- [X] T014 [P] [US1] `tests/test_summary_native_party.py` — `level_line`:
  - the latest `[LEVEL]` row wins, and a character row beats a Party row in the same chapter;
  - with no row: `Level: not recorded in the summaries (sheet says N)`, or `sheet gives none`.
- [X] T015 [P] [US1] `tests/test_summary_native_party.py` — `synth party` end to end with the fake client:
  - section order and headings; the model's text appears under each code-built heading and level line;
  - the prompt for one character contains no other character's notes;
  - `reference/party.md` groups: each PC, Companions, Unattributed;
  - the draft opens with the party contract;
  - with `--dump-only`, no call is made.

### Implementation for User Story 1

- [X] T016 [US1] Create `pipelines/summary_native/party_notes.py` (deterministic, no model):
  - `attribute(results, identity, party_names) -> list[Attribution]` (data-model "Party attribution");
  - `level_line(name, results, attributions, sheet_text) -> str`;
  - `reference_md(results, attributions) -> str` (`## <PC>` groups in `party.yaml` order, then `## Companions`, `## Unattributed`; notes verbatim, in chapter order);
  - `report_md(...)` (unattributed subjects with text and citation, companions by name, the level source per character).

  Add the module to `GUARDED` in `tests/test_summary_native_no_llm.py`.
- [X] T017 [US1] Add a structured party loader in `pipelines/summary_native/context.py`: `load_party(path, root) -> list[ResolvedCharacter]` with name, sheet text, backstory text, arc_score path and trackless flag. It keeps the existing `DocConfigError` messages and stops rendering a prompt block. Leave `party_config_block` in place until T048.
- [X] T018 [US1] Implement `_party_jobs` in `pipelines/summary_native/synth.py` (research R9):
  - one call per character: that character's attributed notes, plus the party-wide notes from the last chunk, sheet and backstory; brief from `state.party.system.md`; budget `party_budgets["Characters"]`;
  - one call each for Party Overview and Party Dynamics (party-wide notes plus the latest two notes per character), within budgets.

  **Assembly:**
  - `## Characters` is built from code-built `### {name}` headings and level lines, followed by each model body and `_Full notes: reference/party.md_`;
  - a character with no notes gets the code line "The summaries in this range record nothing for {name}." and no call;
  - a missing body makes the draft incomplete (exit 3).

  **Outputs:** write `reference/party.md` and `party_report.md`; record the budgets in the run record.
- [X] T019 [US1] Wire the `synth party` flags in `pipelines/summary_native/cli.py`:
  - `--party-config` (default `<config>/party.yaml`);
  - prose backend defaults as world_state (flag > `grounding.yaml summary_native.prose` > schema);
  - budgets from `party_budgets`.

  Refuse `--name`, `--recent-chapters`, `--recurring-min` and `--fallback-npc-lines` for party with the contracts/cli.md messages. Extend `tests/test_summary_native_cli.py`.
- [X] T020 [US1] Route parameters for party in `server/routers/summary_native.py` (`/run/synth/party`): prose model and effort via `resolve_selection(... service="summary_native.prose")`; a 400 with the CLI text for the party-refused params. Extend `tests/test_summary_native_routes.py`.

**Checkpoint**: party builds from checked notes on fixtures; US1's independent test passes.

---

## Phase 4: User Story 3 - Thread proposals the GM can ratify (Priority: P1)

**Goal**: code attaches thread notes to ratified threads by exact title or alias; `summary_native thread-propose` writes code-checked group proposals; `thread_registry ratify|rule --key` ratifies, splits and rejects them; the Threads page drives it.

**Independent Test**: the spec US3 test. On fixtures:
- every unattached note is in exactly one proposal;
- a fake model output with a bogus id, a double-claimed note and a missing `continues` target is corrected as specified;
- ratifying a group adds its aliases, and the next attach run attaches those notes with no model call;
- a rejected group's notes come back as `single`.

### Tests for User Story 3

- [X] T021 [P] [US3] `tests/test_summary_native_threads.py` — `thread_attach.attach`:
  - exact title or alias match attaches; a name matching two threads → ambiguous, unattached, reported;
  - open/closed: a GM status other than `open` wins, otherwise the latest attached tag decides;
  - Active Plots order is newest activity first;
  - an empty or absent registry means everything is unattached.
- [X] T022 [P] [US3] `tests/test_summary_native_threads.py` — `thread_check.check_groups`:
  - unknown member removed; attached member removed; a note in two groups is removed from both;
  - a `continues` with a missing thread is dropped; a group left empty is dropped;
  - every leftover unattached note becomes `single`;
  - keys are `g-` + sha of sorted member ids;
  - existing rulings are preserved on merge; rejected members are excluded from model input and re-offered as `single`.
- [X] T023 [P] [US3] `tests/test_thread_registry_groups.py`:
  - `ratify --key --emit-plan` returns `derive_plan` from the members (log rows in chapter order, change from tag, `cite`, `aliases_add`);
  - `ratify --key --plan` writes the thread or log rows plus aliases in one write;
  - a subset plan leaves the remainder as a new pending group;
  - `rule --key --status rejected` persists;
  - an alias colliding with another thread's title is refused;
  - an AST/grep guard: only the `thread_registry` verbs open the registry for writing, and `thread_propose` never does.
- [X] T024 [P] [US3] `tests/test_summary_native_threads.py` — `thread-propose` end to end with the fake client:
  - batching splits at `--max-input-chars` in chapter order, and no batch prompt contains another batch's output (only checked notes and ratified threads);
  - prompts and outputs land in `state/threads/`; the record is written;
  - `--dump-only` makes no call; the registry is untouched.

### Implementation for User Story 3

- [X] T025 [US3] Create `pipelines/summary_native/thread_attach.py` (deterministic):
  - `attach(results, registry) -> Attachment`, which holds per-note thread id, ambiguous names, per-thread latest note and open flag, and the unattached notes;
  - `threads_report_md(att, rng)`;
  - writes `state/threads/attach.json`.

  Use `campaignlib.thread_registry.match_threads`. Add the module to `GUARDED`.
- [X] T026 [US3] Create `pipelines/summary_native/thread_check.py` (deterministic): `check_groups(raw_json, unattached, registry, prior_proposals) -> (groups, report_lines)` and `merge_proposals(path, groups, source)` (data-model "Thread proposal"). It preserves rulings by `key`, writes the new entry shape beside the name-keyed entries, and writes atomically. Add the module to `GUARDED`.
- [X] T027 [US3] Create `pipelines/summary_native/thread_propose.py` (the model step, research R5):
  - builds `id | ch | tag | name | text` lines for the unattached, non-rejected notes, plus the ratified threads (id, title, aliases, latest note);
  - batches by `--max-input-chars`; every batch sees only ratified threads (no model output is fed to a later call);
  - calls through `render_part`, parses the JSON (a parse failure means that batch's notes all become `single`, reported), and checks via `thread_check`;
  - writes `state/threads/propose.{user,out}.md` per batch, `propose_report.md` and `runs/<stamp>/record.json`;
  - prints the contracts/cli.md summary line;
  - never writes the registry.
- [X] T028 [US3] Add the `thread-propose` subcommand to `pipelines/summary_native/cli.py`: `--since --until --max-input-chars --max-tokens --dump-only` plus the backend flags, with prose defaults. It resolves the registry and proposals paths from `projections.yaml` (`campaignlib.projection_config`), and exits with the contracts/cli.md codes. Extend `tests/test_summary_native_cli.py`.
- [X] T029 [US3] Extend `pipelines/grounding/thread_registry.py` (research R7):
  - `ratify --key` with `--emit-plan` / `--plan`, a group `derive_plan`, split by member subset, and `continues` appending log rows and aliases to an existing thread;
  - `rule --key`;
  - the validation from contracts/cli.md before the single write;
  - an optional `cite` on log rows, accepted by `check_registry`.

  `--norm` behaviour stays unchanged, and `tests/test_thread_registry.py` stays green.
- [X] T030 [US3] Routes in `server/routers/projections.py`:
  - `GET /threads/run/group-propose` streams `summary_native thread-propose`; `since` and `until` are required (400 without); backend/model/effort via `resolve_selection(... service="summary_native.prose")`;
  - `GET /threads/plan?key=` returns `--emit-plan`;
  - `POST /threads/ratify` accepts `key` plus a plan, with route-edge validation that `members` is non-empty and a subset, and that the log chapters are integers ≥ 1;
  - `POST /threads/rule` accepts `key`;
  - `GET /threads/proposals` returns group entries.

  Extend the Threads route tests.
- [X] T031 [US3] Extend `frontend/src/views/grounding/Threads.vue`:
  - a "Propose groupings" step: range prefilled from the summary-native page's current range, model/effort, Run / Dump-only, the SSE log, and a refresh;
  - group proposal cards showing kind, title or target thread, and members (chapter, tag, name, text, citation);
  - a ratify editor seeded from `/threads/plan`: editable title, status, member checkboxes (an unticked member means a split) and aliases. There is no one-click accept;
  - Reject / Defer by `key`.

  Add a Playwright test in `frontend/e2e/` for propose → edit → ratify → refresh.

**Checkpoint**: on fixtures, notes attach to ratified threads; proposals are checked and ratifiable; the page drives it.

---

## Phase 5: User Story 2 - Build planning from checked notes and published dossiers (Priority: P1)

**Goal**: `synth planning` writes the Threat Tracker (code), NPC Dossiers (published dossiers), Faction States, Active Plots (ratified threads, then unratified notes) and DM Notes.

**Independent Test**: the spec US2 test on fixtures:
- the threat table matches `planning.yaml`;
- Active Plots lists exactly the open ratified threads, newest first, then the unratified notes verbatim;
- the GM-resolved thread is absent;
- every NPC block ends with its dossier pointer;
- the canary appears nowhere;
- a missing dossier refuses unless `--fallback-npc-lines`;
- an empty registry still builds.

### Tests for User Story 2

- [X] T032 [P] [US2] `tests/test_summary_native_planning.py` — sections:
  - **Threat Tracker:** one row per configured non-trackless score, or the sentinel when none;
  - **factions:** selection (config ∪ `[FACTION]` subjects, canonical by `forms`), newest first, capped at `DEFAULT_MAX_FACTIONS` with the rest named;
  - **Active Plots:** a model output that drops, adds or reorders a thread is replaced by the latest attached note verbatim and reported; a thread the GM set to `dormant` appears only under `DORMANT_HEADING` as its title plus latest attached note, verbatim, with no model call; a registry status of `open` defers to the latest note's tag; the unratified block holds every unattached note verbatim, in chapter order, with its count; an empty registry gives `NO_RATIFIED_THREADS`;
  - **DM Notes:** begins with `DM_NOTES_LABEL`.
- [X] T033 [P] [US2] `tests/test_summary_native_planning.py` — NPC Dossiers:
  - selection is the tracked NPCs ∪ recent/recurring ∪ `--name`;
  - a block citing another dossier, or quoting non-verbatim, is replaced by the dossier's first Last Observed State sentence and reported;
  - the pointer `→ docs/npcs/<slug>.md` is present;
  - the missing-dossier refusal names the NPC and its state; `--fallback-npc-lines` gives the marked line;
  - the canary is absent from prompts and outputs.

### Implementation for User Story 2

- [X] T034 [US2] Add a structured planning loader to `pipelines/summary_native/context.py`: `load_planning(path, root, explicit)` returning tracked NPCs and factions with arc_score path and trackless flag. An absent default file means none configured; an explicit missing file refuses. The existing `DocConfigError` messages are kept.
- [X] T035 [US2] In `pipelines/summary_native/state_sections.py`, add:
  - `threat_tracker_md(entries, candidates_by_subject)` (code table, or `NO_ARC_SENTINEL`);
  - `select_factions(results, forms, configured, cap)`;
  - `active_plots_md(attachment, bodies)`, which assembles the ratified entries (model bodies, or replacements), then the code-built dormant block, then the unratified block (data-model "Active Plots section").
- [X] T036 [US2] In `pipelines/summary_native/key_npcs.py`, add the planning entries:
  - `plan_planning_npcs(...)`, reusing `select_key_npcs` and `plan_key_npcs` with the tracked NPCs added as named;
  - `planning_prompt(plan, per_npc_words)`;
  - `verify_planning_block(block, view, hay)` (heading, three labelled lines, citations only from that dossier, verbatim quotes);
  - `assemble_planning(...)` with the fallback and pointer;
  - `planning_report_md(...)` → `planning_npcs_report.md`.

  The refusal and `missing_dossiers.json` follow world_state's shape, with `doc: planning`.
- [X] T037 [US2] Implement `_planning_jobs` in `pipelines/summary_native/synth.py`:
  - **Threat Tracker:** code only.
  - **NPC Dossiers:** one call through `state.planning_npcs.system.md`.
  - **Faction States:** one call with per-faction note groups in code order; the heading set and order are checked, and a failure substitutes the latest note.
  - **Active Plots:** one call with the open ratified threads in code order, each with its attached notes; checked as T032.
  - **DM Notes:** one call with the open threads' latest notes, the NPC status table and the last chunk.

  Each section gets its budget, the reference pointers and the outline order. Write `threads_report.md` and `planning_npcs_report.md`, and add the thread registry sha and config files to the run record.
- [X] T038 [US2] Wire the `synth planning` flags in `pipelines/summary_native/cli.py`: `--planning-config`, `--name`, `--recent-chapters`, `--recurring-min`, `--fallback-npc-lines` (now world_state and planning) and the prose defaults. A registry failing `check_registry` refuses (exit 2). Extend `tests/test_summary_native_cli.py`.
- [X] T039 [US2] Route and page:
  - in `server/routers/summary_native.py`, accept `fallback_npc_lines` for planning; extend `/state` with the planning `missing_dossiers` and the `threads` counts from `state/threads/attach.json` and the proposals file; extend `/drafts` with the new reports (including party's `party_report.md` and `reference/party.md`);
  - in `frontend/src/views/grounding/SummaryNative.vue`, give the planning step the fallback checkbox (per run, never persisted), the thread counts and a link to the Threads page.

  Extend the route tests and add a Playwright test.

**Checkpoint**: planning builds on fixtures with both thread layers, dossier-sourced NPCs and a code-built threat tracker.

---

## Phase 6: User Story 4 - Candidate arc-score events, checked (Priority: P2)

**Goal**: for each configured, non-trackless arc score, the model lists candidates; code keeps only those that are cited, verbatim and value-free.

**Independent Test**: on fixtures, the PC score's candidates appear under the character's `#### Candidate Arc Score Events`, and the NPC score's in the Threat Tracker cell. Paraphrased triggers, value statements and foreign citations are dropped with reasons in `arc_report.md`. The trackless character has none.

- [X] T040 [P] [US4] `tests/test_summary_native_arc.py`: `arc_check.check_candidates`. Its reasons are `cite-not-in-notes`, `trigger not verbatim` and `states a value` (the R10 pattern). Include near-misses that are not values, e.g. "level 3 spell" in the event text with no score words.
- [X] T041 [US4] Create `pipelines/summary_native/arc_check.py` (deterministic, R10): `check_candidates(text, subject_cites, mechanic_text) -> (kept, drops)` and `arc_report_md(...)`. Add it to `GUARDED`.
- [X] T042 [US4] In `pipelines/summary_native/synth.py`, add one arc call per configured non-trackless score, through `state.arc.system.md`:
  - the subject's checked notes are the PC's attributed party notes, or an NPC/faction's notes by canonical subject;
  - the mechanic file text is attached;
  - the result is checked, then placed into the party character section (`#### Candidate Arc Score Events`) or the planning Threat Tracker cell;
  - `arc_report.md` is written.

  Extend `tests/test_summary_native_party.py` and `tests/test_summary_native_planning.py`.

**Checkpoint**: arc candidates appear only when checked; trackless entities get none.

---

## Phase 7: User Story 5 - Annotation, reading contract and run record (Priority: P2)

**Goal**: the annotators run over party and planning exactly as over the other two documents; no line is ever reworded.

**Independent Test**: on fixtures, a party line mentioning a companion whose status changed later gains `ℹ since:`. A non-verbatim quote gains `⚠ unverified:`. The planning NPC blocks, Threat Tracker and unratified block are not scanned. The never-rewrites test passes for both documents.

- [X] T043 [P] [US5] Extend `tests/test_annotate_never_rewrites.py` and `tests/test_summary_native_annotate.py` to party and planning drafts. Cover the skip list, and confirm the PC-in-NPC removal fires in `## Faction States` but never inside party's `## Characters`.
- [X] T044 [US5] In `pipelines/summary_native/annotate.py`:
  - add `## Threat Tracker` and `## NPC Dossiers` to `SKIP_SECTIONS`;
  - skip the lines under `DORMANT_HEADING` and `UNRATIFIED_HEADING` inside `## Active Plots`;
  - make sure `parse_entries` handles the `###` sub-entries of Characters, Faction States and Active Plots, giving each entry its `###` name as subject;
  - make `run_annotate` (the `annotate <doc>` command) accept party and planning.
- [X] T045 [US5] Run annotation at the end of `synth party|planning` in `pipelines/summary_native/synth.py` (the same block as for world_state), and write `annotations.md` / the counts. Add the annotation counts to the run record.

**Checkpoint**: both documents annotate; the guards are green.

---

## Phase 8: User Story 6 - One build surface, one-shot path removed (Priority: P3)

**Goal**: every document builds one way. The retired flags refuse with their replacement, and the page has no one-shot controls.

**Independent Test**:
- all four documents build from one extraction with no extraction call after the first;
- `--parts`, `--world-state` and `--campaign-state` refuse with the contracts/cli.md messages, from the CLI and the routes alike;
- the page has no Parts control.

- [X] T046 [P] [US6] Extend `tests/test_summary_native_cli.py` and `tests/test_summary_native_routes.py`: every retired flag or parameter is refused (exit 2 / 400) with the replacement message, and one-shot prompt files and functions no longer exist (an import/AST check).
- [X] T047 [P] [US6] Extend `tests/test_summary_native_synth.py`: build all four documents from one fixture extraction, and assert that the fake extraction client is called zero times by `synth`.
- [X] T048 [US6] Delete the one-shot path:
  - in `pipelines/summary_native/synth.py`, the `run_synth` one-shot body after the state dispatch, `split_parts` (if unused), `check_threat_tracker` (if no longer needed) and the `--parts` plumbing;
  - in `pipelines/summary_native/context.py`, `build_context`, the upstream-draft blocks, and the prompt-block renderers `party_config_block` / `planning_config_block`;
  - in `pipelines/summary_native/prompts/`, `party.system.md` and `planning.system.md`;
  - in `schema.py`, `DEFAULT_PARTS` and the `STATE_PARTS_REFUSAL` wording, replaced by the retired-flag refusals.

  Then add the contracts/cli.md refusals in `pipelines/summary_native/cli.py`. Run `rg` for the removed names across `pipelines/ server/ frontend/ tests/ docs/` and fix every reference.

  Two more follow-ups came out of the Phase 2 review:
  - **Delete the skipped tests.** Remove the `RETIRED_ONE_SHOT` set and its skip fixture from `tests/test_summary_native_synth.py`, along with every test it skips. Rewrite the generic behaviours on the chunked path (run-id suffixing, the record written on failure, the previous draft kept on an incomplete build) instead of deleting them, unless 033's tests already cover them. Do the same for the skipped seam test in `tests/test_summary_native_routes.py`.
  - **`--npc-root` for planning.** Accept `--npc-root` for `synth planning`, as for world_state; today it is refused for planning. Found in the Phase 5 review.
  - **Faction substitutions.** Write them to a report file on disk (e.g. a "Faction States" section in `planning_npcs_report.md`, renamed `planning_report.md` if that reads better), not only to stdout and the run record. Found in the Phase 5 review.
  - **`check-pointers`.** `pointers.check_paths` expects all six reference files plus the timeline. Make it check only the files a document's reading contract names (its `summary_native pointers:` comment), so it works on promoted party and planning bundles, and add a test.
- [X] T049 [US6] Router and page cleanup:
  - `server/routers/summary_native.py`: remove the `parts`, `world_state` and `campaign_state` params (a request carrying them gets a 400 with the CLI text);
  - `frontend/src/views/grounding/SummaryNative.vue`: party and planning use the same step component as world_state/campaign_state, and the Parts control and upstream-draft pickers are removed.

  Update the Playwright tests in `frontend/e2e/`.

**Checkpoint**: one build path per document, at the CLI and in the UI.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T050 [P] `docs/cli/summary_native_howto.md`:
  - replace "Step 6 — the other two documents" with the chunked party and planning builds;
  - document the party grammar and the re-extract, the level rows, attribution and `party_report.md`;
  - add planning's sections and the two Active Plots layers, and the thread proposal workflow (`thread-propose` → Threads page → ratify, split, reject);
  - document arc-score candidates: the `#### Candidate Arc Score Events` subsection, the Threat Tracker cell, `arc_report.md` and the three drop reasons;
  - document the annotation scope for party and planning: prose lines are scanned too; the Threat Tracker, NPC Dossiers, dormant and unratified blocks and the candidates subsection are skipped; a Faction States block named for a player character is removed;
  - document the planning companions and the companion notes in Party Overview and Dynamics;
  - list every new refusal and exit code;
  - state the session-prep contract for all four documents (FR-025).
- [ ] T051 [P] `docs/cli/state_projection_howto.md`: group proposals on the Threads page, ratifying a group (edit, split), rejection persistence, and where summary-native proposals come from.
- [ ] T052 [P] `docs/core/architecture.md`: four documents, one chunked build; thread identity from the registry; the new `state/threads/` and reports. Also update `CLAUDE.md`'s "Grounding docs are an index" paragraph to cover party and planning.
- [ ] T053 Run quickstart **S0 from main** (before this branch merges) and record the one-shot baseline sizes in `specs/034-chunked-party-planning/quickstart.md`. Adjust `DEFAULT_PARTY_BUDGETS` / `DEFAULT_PLANNING_BUDGETS` in `schema.py` if S6 shows the new drafts larger.
- [ ] T054 Run quickstart S1–S7 on the OOTA copy and record the results under "Validation" in `specs/034-chunked-party-planning/quickstart.md`: extraction drops, level, attribution, proposal counts, ratification round trip, planning layers, the canary, sizes, citations and timing. Ask the GM before ratifying anything in the real campaign; S3 ratifies only in the copy.
- [ ] T055 Run `PYTHONPATH=$PWD python -m pytest tests/` and `cd frontend && npx playwright test`. Then list the follow-ups (campaign_state threads from the registry; #512; #515; retiring the ensemble harvest) under "Follow-ups" in `specs/034-chunked-party-planning/plan.md`, and file the campaign_state-threads issue with the GitHub MCP tools.
- [ ] T056 Remove `parts: 0` from Out of the Abyss's `config/grounding.yaml` (line 73) in the kostadis/campaigns repo, on a branch with a PR, merged before or with this feature. After this feature the key is refused at load. The line is harmless to the old code, so removing it first is safe. Ask the GM before touching the campaigns repo, and check the other campaigns' `grounding.yaml` for the same key. Found in the Phase 8 review.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (1)** → **Foundational (2)**, which blocks every story.
- **US1 (3)** depends on Foundational only.
- **US3 (4)** depends on Foundational and T002. It is independent of US1.
- **US2 (5)** depends on US3 (`thread_attach` for Active Plots) and on T011 (`planning_view`).
- **US4 (6)** depends on US1 and US2 (it places candidates into their sections).
- **US5 (7)** depends on US1 and US2.
- **US6 (8)** depends on US1 and US2 being able to build: the one-shot path is deleted only once its replacement works.
- **Polish (9)**: T053 (S0) must run from **main** before US6's deletion reaches main. It can run any time before the merge.

### Within each story

Tests first (they fail), then deterministic modules, then model steps and synth wiring, then CLI, then routes, then the page.

### Parallel opportunities

- **Setup:** T002, T003 and T004 in parallel.
- **Foundational:** T008, T010 and T011 in parallel with each other. T005 → T006 → T007 run in sequence; T009 and T012 follow T006.
- **US1 ∥ US3** after Foundational: different modules (`party_notes` vs `thread_*`), but `cli.py` and `synth.py` are shared, so serialise T019 against T028.
- **Tests:** within a story, the test tasks marked [P] run together.
- **Polish:** T050–T052 in parallel.

## Parallel Example: User Story 3

```text
T021 thread_attach tests  ∥  T022 thread_check tests  ∥  T023 registry group-verb tests  ∥  T024 propose e2e tests
then T025 thread_attach.py  ∥  T026 thread_check.py   (different files)
then T027 thread_propose.py → T028 cli → T029 thread_registry verbs → T030 routes → T031 page
```

## Implementation Strategy

### MVP first

Setup → Foundational → US1 gives a chunked party draft that a GM can review: the level is correct, companions are separated, and nothing is invented from a sheet. Validate it on the OOTA copy (S1–S2) before continuing.

### Incremental delivery

1. **US1:** party (MVP).
2. **US3:** thread proposals. The GM can start ratifying OOTA threads in the copy while planning is being built.
3. **US2:** planning with both Active Plots layers.
4. **US4:** arc candidates (OOTA configures none, so it is verified on a scratch config).
5. **US5:** annotation.
6. **US6:** delete the one-shot path, after T053's baseline.
7. **Polish:** docs and full validation.

### Orchestration

For each phase, Opus briefs one Sonnet subagent with:
- the phase's tasks;
- the conventions above;
- the relevant contract and data-model sections.

Opus then reviews the diff and runs the tests, then commits the phase on `worktree-034-chunked-party-planning`. No merge to main without the GM's go-ahead.
