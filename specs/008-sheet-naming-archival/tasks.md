---

description: "Task list for Roster-Named Sheets & Level Archival"
---

# Tasks: Roster-Named Sheets & Level Archival

**Input**: Design documents from `specs/008-sheet-naming-archival/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: INCLUDED. Not speculative TDD — `plan.md` names the test files as deliverables, and this repo has standing guard suites (`test_layering.py`, `test_retrieve_render_isolation.py`) that a change in these directories can break. Two behaviours here are *only* provable by test: the hand-built-saver round-trip (D9) and the convert-before-mutate ordering (D7).

**Organization**: Grouped by user story. Note the deliberate priority inversion — see [Dependencies](#dependencies--execution-order).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 (archival), US2 (naming), US3 (player), US4 (UI)
- All paths are repo-relative unless marked `~/campaigns/` (a **different git repo**)

---

## Phase 1: Setup

**Purpose**: Establish that what you test is what you changed.

- [X] T001 Verify `campaignlib` resolves from this worktree, not the main checkout: run `python -c "import campaignlib; print(campaignlib.__file__)"` from the worktree root and confirm the path contains `.claude/worktrees/feat-dnd-sheet-party-names`. If it does not, prefix every later test command with `PYTHONPATH="$PWD"` (D12 — a green run against main's copy proves nothing)
- [X] T002 [P] Record a baseline: run `python -m pytest tests/ -q` and note any pre-existing failures, so this feature is never blamed for them

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared parser and the attribution primitive both US1 and US2 build on, plus the CLI's mode switch.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 Create `campaignlib/sheet_identity.py` and MOVE `SheetParseError`, `_H1_RE`, `_IDENTITY_HEADING_RE`, `_NEXT_HEADING_RE`, `_FIELD_RE`, `_KNOWN_IDENTITY_KEYS`, `_find_identity_block`, `parse_identity_fields` and `sheet_name` into it from `pipelines/content_ingest/sheet_frontmatter.py`, preserving behaviour exactly (D3). This module must import nothing from `server` or `pipelines`
- [X] T004 Re-point `pipelines/content_ingest/sheet_frontmatter.py` at the moved names via `from campaignlib.sheet_identity import ...`, keeping every public name importable from their old location so existing callers are unaffected (depends on T003)
- [X] T005 [P] Confirm `python -m pytest tests/test_sheet_frontmatter.py -q` passes with **no edits to that test file** — the move is behaviour-preserving or it is wrong (depends on T004)
- [X] T006 Add `AmbiguousLevelError`, `read_class_level(text) -> str | None` (frontmatter `class_level` first via `campaignlib.textproc.split_frontmatter`, then the `## Identity` `class & level` value) and `parse_level(phrase) -> int` (single trailing integer only; raise on absent, non-numeric, or multi-segment) to `campaignlib/sheet_identity.py` (D4, depends on T003)
- [X] T007 Create `campaignlib/sheet_naming.py` with `AttributionError` and `attribute(extracted_name, characters)` — lowercase + strip both sides, require exactly one hit, raise carrying the extracted name and the full roster name list. **No prefix, token, edit-distance or similarity fallback may exist in this module** (D2, FR-002/FR-002a)
- [X] T008 [P] Write `tests/test_sheet_naming.py` covering attribution: exact hit, case/whitespace variance, zero hits, two entries sharing a name, empty roster. Assert the error text lists the available roster names (depends on T007)
- [X] T009 Add `--party-config PATH` to `pipelines/content_ingest/dnd_sheet.py`'s parser, load it with `campaignlib.party_config.load_party_config_arg`, and flip `--output-dir`'s default from `"doc"` to `None`, falling back to `doc` only outside roster mode. Implement the three-way mode selection from `contracts/cli-dnd-sheet.md` and print the FR-017/FR-018 notices (D1, D11)
- [X] T010 [P] Confirm `python -m pytest tests/test_layering.py tests/test_retrieve_render_isolation.py -q` passes — `campaignlib` must not import `server`/`pipelines`, and `pdf_to_markdown` must not gain a retrieval call (depends on T003, T007, T009)

**Checkpoint**: The parser is shared, attribution works, and the CLI knows which mode it is in — but still writes exactly where it does today.

---

## Phase 3: User Story 2 - Sheets named by the canonical character name (Priority: P2)

**Goal**: A converted sheet lands at `<roster sheet dir>/<char-name>.md`, or the run refuses with the one-line roster fix.

**Independent Test**: Convert a PDF for a roster character who has **no** existing sheet. The output filename comes from the roster, not the PDF. Then point the roster at a differently-cased filename and confirm the refusal prints the exact replacement `sheet:` line. No archival is exercised.

**Why this phase comes first**: US1 is the higher-priority outcome but cannot resolve a destination without this. See [Dependencies](#dependencies--execution-order).

### Tests for User Story 2

- [X] T011 [P] [US2] Add destination cases to `tests/test_sheet_naming.py`: `destination_for` returns `<declared sheet parent>/<name>.md`; a roster basename that disagrees raises; a case-only difference (`soma.md` vs `Soma.md`) is detected rather than silently treated as equal (FR-007)
- [X] T012 [P] [US2] Create `tests/test_dnd_sheet.py` with a stubbed converter (monkeypatch `pdf_to_markdown`, no API call): a matched PDF writes to the roster path; an unmatched PDF writes nothing and exits `1`; a three-PDF run with one bad PDF still writes the other two and exits `1` (FR-004)
- [X] T013 [P] [US2] Add legacy-mode tests to `tests/test_dnd_sheet.py`: no `--party-config` writes `<pdf-stem>.md` under `doc/`; `--output` with `--party-config` skips roster naming and prints the FR-017 notice

### Implementation for User Story 2

- [X] T014 [US2] Implement `destination_for(character, base)` in `campaignlib/sheet_naming.py` — resolve the character's authored `sheet` against `base`, take its parent, and return `parent / f"{character.name}.md"` (FR-005)
- [X] T015 [US2] Implement `RosterFilenameMismatch` in `campaignlib/sheet_naming.py`, raised when the declared `sheet` basename differs from the derived filename, carrying both paths and the exact replacement `sheet:` line for the message (FR-006, D6). Comparison must be case-sensitive so a case-only difference still refuses (FR-007)
- [X] T016 [US2] Wire the happy path into `pipelines/content_ingest/dnd_sheet.py`'s per-PDF loop: convert → `attribute` → `destination_for` → write, printing `Matched roster entry: <name>` for every file written (FR-002b)
- [X] T017 [US2] Implement the refusal output in `pipelines/content_ingest/dnd_sheet.py` for no-match, ambiguous-match and filename-mismatch, matching `contracts/cli-dnd-sheet.md` verbatim — each names the file, the values that disagree, the fix, and ends "Nothing was written or moved" (FR-003, FR-003a, FR-006)
- [X] T018 [US2] Make refusals per-PDF, not per-run, in `pipelines/content_ingest/dnd_sheet.py`: continue to the next PDF and exit `1` if any were skipped (FR-004)

**Checkpoint**: Roster-named output works end to end for characters with no existing sheet, and every disagreement refuses cleanly.

---

## Phase 4: User Story 1 - Re-convert a levelled-up character without losing the old sheet (Priority: P1) 🎯 MVP

**Goal**: An existing sheet at the destination is moved to `old/level/<N>/<char-name>.md` before the new one is written.

**Independent Test**: Convert a PDF for a character whose sheet exists and records level 5. The level-5 sheet is readable at its archive location, the new sheet is at the roster's path, and every roster reference still resolves. Re-running the same conversion refuses instead of overwriting.

### Tests for User Story 1

- [X] T019 [P] [US1] Add level cases to `tests/test_sheet_naming.py` (or a level-focused block in `tests/test_sheet_identity.py`): `"Monk 8"` → `8`; `"Druid 5"` → `5`; `"Fighter 9 / Bard 2"` raises `AmbiguousLevelError`; a sheet with **no frontmatter** still yields a level from its `## Identity` block; a sheet with neither raises (FR-013, D4)
- [X] T020 [P] [US1] Add archive cases to `tests/test_sheet_naming.py`: `archive_path` returns `<dir>/old/level/<N>/<char-name>.md`; the archived filename is roster-shaped even when the displaced file was named differently; an occupied destination raises rather than overwriting or suffixing (FR-014, D5)
- [X] T021 [P] [US1] Add an ordering test to `tests/test_dnd_sheet.py`: with the converter stubbed to raise, assert the existing sheet is still at its original path and no archive directory was created — proving no filesystem mutation precedes the API call (FR-015, D7)

### Implementation for User Story 1

- [X] T022 [US1] Implement `archive_path(destination, level, char_name)` in `campaignlib/sheet_naming.py` returning `destination.parent / "old" / "level" / str(level) / f"{char_name}.md"` (D5)
- [X] T023 [US1] Implement `ArchiveSlotOccupied` in `campaignlib/sheet_naming.py`, raised when the archive path already exists — never overwrite, never suffix (FR-014)
- [X] T024 [US1] Add the archival step to `pipelines/content_ingest/dnd_sheet.py`: when the destination exists, read its class-and-level via `read_class_level`/`parse_level`, compute the archive path, check the slot, `mkdir(parents=True)`, and move — strictly between destination resolution and the write (FR-011, FR-012)
- [X] T025 [US1] Enforce the operation order in `pipelines/content_ingest/dnd_sheet.py` — the API call completes before the first filesystem mutation, so every refusal leaves the tree untouched and no crash can leave a character sheet-less (FR-015, D7)
- [X] T026 [US1] Add the level and archive refusal messages to `pipelines/content_ingest/dnd_sheet.py` per `contracts/cli-dnd-sheet.md`: unreadable level, multiclass level, occupied slot (FR-013, FR-014)
- [X] T027 [US1] Print the `Archived: <from> -> <to>  (level N)` line for every move, omitted when nothing was displaced (FR-016)

**Checkpoint**: The full level-up round trip works. This is the MVP — US1 + its US2 prerequisite deliver the feature's core value without any player or UI work.

---

## Phase 5: User Story 3 - The player behind the character survives a re-export (Priority: P3)

**Goal**: `party.yaml` records who plays each character, and the conversion writes that value over the downloader's name in both channels of the sheet.

**Independent Test**: Convert a PDF whose player field holds the GM's name, for a character whose roster entry names someone else. Both the frontmatter `player:` and the `## Identity` `- **Player:**` line show the roster's value. Convert again — it does not revert.

### Tests for User Story 3

- [X] T028 [P] [US3] Add a round-trip test to `tests/test_party_config.py`: build a `PartyConfig` with `player` set, `save_party_config` it, `load_party_config` it back, assert the value survived. **This is the guard for D9** — all three sites hand-build their output, and the failure mode is a save that succeeds and persists nothing
- [X] T029 [P] [US3] Add a test asserting a roster with **no** `player` anywhere still loads and saves unchanged, and that `PATH_FIELDS`/`missing_files` are unaffected by the new field (FR-008a)
- [X] T030 [P] [US3] Add player-substitution cases to `tests/test_sheet_naming.py`: both channels are rewritten; a sheet missing frontmatter still has its Identity line rewritten; an empty roster player empties both rather than carrying the downloaded value forward (FR-009, FR-010a)

### Implementation for User Story 3

- [X] T031 [US3] Add `player: str | None = None` to `PartyCharacter` **and** `ResolvedCharacter` in `campaignlib/party_config.py`, then name it explicitly in all three hand-built sites: the `PartyCharacter(...)` construction in `load_party_config`, the `entry` dict in `save_party_config`, and the `ResolvedCharacter(...)` construction in `resolve_party_config` (D9). Do not add it to `PATH_FIELDS`
- [X] T032 [US3] Implement `apply_roster_player(markdown, player)` in `campaignlib/sheet_naming.py` — rewrite the frontmatter `player:` value and the `- **Player:**` line of the `## Identity` block, trimming the value; leave every other field untouched (FR-010a, D8)
- [X] T033 [US3] Call `apply_roster_player` in `pipelines/content_ingest/dnd_sheet.py` after conversion and before the write, and print `Player: <old> -> <new>  (from party.yaml)` (FR-008, FR-010)
- [X] T034 [US3] Handle the no-player case in `pipelines/content_ingest/dnd_sheet.py`: write an empty player in both channels and print the FR-009 line explaining the downloaded value names the downloader, not the player. **Never** carry the downloaded value forward

**Checkpoint**: The roster owns the player name, and a re-export no longer destroys it.

---

## Phase 6: User Story 4 - Run the whole thing from the web UI (Priority: P2)

**Goal**: The full flow — attribute, name, archive, report — is reachable from `/setup/dnd-sheet`, and the roster editor can set the player.

**Independent Test**: From the browser alone, re-convert a character who already has a sheet; the archive move happens, the streamed output names the matched roster entry, and a refusal shows its reason. Separately, set a player in the roster editor and confirm it reaches `party.yaml` on disk.

**Note**: T038/T041 depend on US3's T031. The run-page tasks (T035–T037) do not, and can ship against US1+US2 alone.

### Tests for User Story 4

- [X] T035 [P] [US4] Add a router test asserting `GET /api/setup/run/dnd-sheet` forwards `--party-config` when given, and that it sends `--output-dir` **only** when the caller set it — a synthesised default makes roster mode unreachable (D11, FR-021). Assert no sheet-path or directory literal appears in `server/routers/setup.py`

### Implementation for User Story 4

- [X] T036 [US4] Add `party_config: str = ""` to `run_dnd_sheet` in `server/routers/setup.py` and forward it as `--party-config` when non-empty. Confirm the existing `elif output_dir.strip()` guard never synthesises a value (FR-020, FR-021)
- [X] T037 [US4] Add a party-config `PathField` (`resolve-base="campaign"`) to `frontend/src/views/setup/DndSheet.vue`, include `party_config` in `runParams`, and add a notice stating which mode the current inputs select — roster mode needs a party config and no output path (FR-019, FR-021)
- [X] T038 [US4] Add `player` to `frontend/src/components/shared/PartyConfigEditor.vue` in all four places: the `PartyChar` interface, the blank-row factory, the load mapping (`player: c.player ?? ''`), and a column in the table (FR-023, depends on T031)
- [X] T039 [US4] Add the help text carrying D8's constraint to both `PartyConfigEditor.vue`'s player field and `--party-config`'s CLI help: this is the **Zoom display name**, not a legal name — `normalize_vtt_speakers` matches speaker prefixes exactly and a near-miss silently drops that character's lines
- [X] T040 [US4] Confirm refusals reach the browser as the CLI's own stderr text through `RunPanel`, unmodified and unsummarised — no new plumbing should be needed (FR-022, FR-025)
- [X] T041 [P] [US4] Add a round-trip test to `tests/test_party_routes.py`: `PUT /api/party/characters` with `player` set, then `GET`, returns it — and assert it reached `party.yaml` on disk, since a `200` is not proof (depends on T031)
- [X] T042 [US4] Reinstall into the server's venv so `console_script("dnd_sheet")` resolves the new signature: `uv pip install -e . --python "$VIRTUAL_ENV/bin/python"`. No server restart needed; skipping this shows as `Stream error — check terminal.`

**Checkpoint**: Every user story is reachable from both surfaces, producing identical files.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T043 [P] Amend `docs/design/PartyRosterCanonicalFormat.md` to record the FR-008 reversal — the roster, not the sheet, is authoritative for `player`, because the export stamps the downloader's name into every sheet. The document currently asserts the opposite and must not be left contradicting shipped behaviour
- [X] T044 [P] Document the feature in `docs/cli/cli_tools.md`: `--party-config`, the three modes, the archive layout, and each refusal
- [X] T045 [P] Update the `dnd_sheet` module docstring in `pipelines/content_ingest/dnd_sheet.py` — its usage examples still show only the pre-feature invocations
- [X] T046 Run the full suite: `python -m pytest tests/ -q`, compared against T002's baseline
- [X] T047 Migrate Phandalin's roster in the **separate `~/src/campaigns` repo**: renamed `docs/party/{soma,brewbarry,valphine}.md` to their roster-shaped names and updated the `sheet:` lines in `config/party.yaml`. The `Valphine` / `Valphine Sotorra` disagreement was settled by GM ruling 2026-08-15 — the roster widens to the sheet's fuller name. Done on branch `feat/roster-player-and-sheet-names`, commits `60db8835` + `6fb8f5e0`; **not pushed, no PR**. out-of-the-abyss got the same treatment (`d3c004eb`) since it had the identical lowercase-filename mismatch
- [ ] T048 Record each campaign's `player` values in its `config/party.yaml` (`~/src/campaigns`), using Zoom display names per T039 — **2 of 5 done** (Phandalin, out-of-the-abyss: sheet values confirmed against each campaign's own transcript). Hillsfar needs none (every sheet reads `Player: Not specified`, the documented placeholder). **stormgiants and toee are blocked on a GM ruling**, not on lookup: their Zoom names are short forms and a handle (`Wade`, `Dave`, `Jared`, `ncroussos`) that disagree with the sheets' long legal names, so copying the sheet value would silently drop that player's lines; and toee's `calmer` is played by the GM, which is either correct or the FR-009 empty case
  - **Superseded by feature 009 (2026-08-22).** `party.yaml` has no `player`
    field any more — the key is refused, not ignored — and who plays a character
    is recorded in `players.yaml` instead (`docs/config/players-isolation.md`).
    The remaining work is the same ruling in a different file: stormgiants' and
    toee's Zoom names are short forms and a handle, and only the GM can say which
    person each belongs to. Carry it to feature 009's task list rather than doing
    it here.

- [ ] T049 Execute `quickstart.md` end to end, including the six-refusal matrix with `git status` clean after each, and tick its Definition of Done

---

## Phase 8: Amendment — declared sheet names & multiclass levels (2026-08-22)

Two rulings taken after the feature shipped, on Daein's first real level-up and on
the two Hillsfar sheets whose printed names are wrong. Both amend `spec.md` rather
than extending it: FR-002c is new, and FR-013 reverses D4.

- [X] T050 Add `sheet_name` to `PartyCharacter` and `ResolvedCharacter`, with the
      `_blank_is_absent` validator for the API path and a loader refusal for a blank
      declaration in YAML (`campaignlib/party_config.py`)
- [X] T051 Add `match_name` and route `attribute` through it, and show a declaring
      entry as `Akritas (sheet: Akrita)` in refusals (`campaignlib/sheet_naming.py`)
- [X] T052 Total a complete multiclass phrase in `parse_level`; keep a segment with
      no level of its own a refusal (`campaignlib/sheet_identity.py`)
- [X] T053 Rewrite the two affected refusals in `pipelines/content_ingest/dnd_sheet.py`
      — the attribution one now names three ordered fixes, the level one no longer
      says "more than one class"
- [X] T054 [US4] Add the `sheet_name` input to `PartyConfigEditor.vue`, with help text
      saying what it is for and what it is not
- [X] T055 [P] Amend `spec.md` (FR-002c, FR-013, FR-025, Key Entities), `research.md`
      (D4's revision), the requirements checklist, and
      `docs/design/PartyRosterCanonicalFormat.md`
- [X] T056 [P] Amend `data-model.md`, `contracts/cli-dnd-sheet.md`,
      `contracts/http-api.md` and `quickstart.md` — all four still described the
      shipped behaviour, and two of them still documented `player`
- [X] T057 Tests for both rulings: declared-alias attribution, the alias reaching
      nothing but attribution, blank handling on both paths, multiclass totalling,
      and a segment with no level
- [ ] T058 Re-run §3b and the refusal matrix of `quickstart.md` against the amended
      behaviour (folds into T049 — the matrix changed under it)

---

## Deliberately not done (2026-08-14)

Four tasks are left open on purpose, not forgotten. Each needs something an
implementation pass should not decide by itself.

- **T042 — `uv pip install -e .` into the server's venv.** Run from *this
  worktree* it would repoint the shared editable install away from
  `/home/kroussos/src/CampaignGenerator`, so the running server and every other
  session would start executing this branch. That is a change to the live
  environment, not to the feature. Run it after merge, from the main checkout —
  or knowingly, from here, to click through the UI.
- **T047 / T048 — the `~/src/campaigns` migration.** *Mostly done* on branch
  `feat/roster-player-and-sheet-names` (commits `60db8835`, `d3c004eb`):
  Phandalin and out-of-the-abyss have roster-shaped sheet filenames and a
  `player:` per character, each verified against that campaign's own Zoom
  speaker labels and re-checked through the engine (all references resolve, no
  filename mismatch, archive slots free). Not pushed, no PR.

  The earlier claim that T048 "needs Zoom display names nobody else knows" was
  wrong: the names are recoverable by comparing each sheet's `- **Player:**`
  against the speaker prefixes in that campaign's transcript. Doing exactly that
  is what showed the remaining three campaigns are **not** mechanical:

  | Campaign | State |
  |---|---|
  | Phandalin | done — sheet values match the 20260729 VTT exactly |
  | out-of-the-abyss | done — match the 2025-10-27 VTT exactly |
  | stormgiants | **blocked.** Zoom shows short forms (`Wade`, `Dave`, `Jared`); the sheets carry `Wade Brown`, `David Mendenhall`, `Jared Rossof`. Copying the sheet value would silently drop that player's lines. Its transcripts are from early 2025, so which form is current is a GM call. Also: `Thistle.md` exists but is not in the roster, and a `Gary` speaks who is not a roster character. |
  | toee | **blocked.** `sequioa`'s sheet says `Nicholas Roussos`, Zoom shows `ncroussos` — the sheet value would not match. And `calmer`'s player is `Kostadis Roussos`, the GM: either correct (a GM-run recruited PC, per the entity-registry notes) or the FR-009 "no player recorded" case. That is a ruling, not a lookup. |
  | Hillsfar | nothing to record — every sheet says `Player: Not specified`, the documented placeholder. FR-008a covers it. |

  **Sheet-title disagreements: settled** (GM ruling 2026-08-15, commit
  `6fb8f5e0`). Where a sheet and its roster entry disagreed, the sheet's fuller
  name wins: `Valphine` → `Valphine Sotorra`, `Thorin` → `Thorin Giantfriend`.
  The third was not a disagreement but a roster misspelling — the character is
  **Gyrgum**, and the sheet had it right; an earlier "typo fix" in this branch
  had corrected it the wrong way and was reverted. All eight characters across
  both campaigns now attribute without refusing.

  **Registry divergence, deliberately left — tracked as campaigns#172.**
  `docs/entity_registry.yaml` is the declared authority for entity identity and
  now disagrees with both rosters: Phandalin's canonical is `Valphine` with
  `Valphine Sotorra` as an *alias* (the reverse of the roster), and
  out-of-the-abyss's is the misspelled `Grygum`, plus derived entries
  (`the Grygumite triangle`, `The Grygumite School`) and several notes.

  The oota half is bigger than it looks: **1608 files use `Grygum` against 75
  using `Gyrgum`**, so the wrong spelling is the corpus majority and this is a
  `spell_canon.py` pass, not an edit. Two raw `*.transcript.vtt` are among them
  and must not be hand-edited. Reconciling has its own blast radius
  (projections, dedup), so it wants a deliberate pass rather than a drive-by.

  **Note the repo is `~/src/campaigns`** — `~/campaigns` is a stale second copy
  (its Phandalin roster still has the pre-#291 config-relative paths). And a
  Phandalin recording is misfiled under
  `out-of-the-abyss/summaries/transcriptions/2025-11-05/` — its speakers are
  Phandalin's players and its filename duplicates Phandalin's chapter-19 file.
  Unrelated to this feature, but it will mislead the next person who checks a
  speaker name there.
- **T049 — the quickstart end to end.** Its unit and guard sections are green
  and its refusal matrix is covered by `tests/test_dnd_sheet.py`. The rest needs
  real PDFs, an API key, T047's migration and a browser.

**A finding worth carrying forward, from T046:** in a worktree, `pytest tests/`
was reporting green against the *main checkout's* `campaignlib`. The venv's
`pytest` entry point puts neither the cwd nor `PYTHONPATH` on `sys.path`, only
`tests/`, so the editable install's `.pth` won; `tests/benchmarks/` is collected
first, imports `campaignlib` with no repo-root insert, and poisons `sys.modules`
for everything after it. `tests/conftest.py` now inserts the repo root once, so
the D12 hazard is closed for the whole suite instead of per-module. The
`PYTHONPATH="$PWD"` workaround in `quickstart.md` §0 does **not** work here and
is no longer needed.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup — **blocks every user story**
- **Phase 3 (US2)** → **Phase 4 (US1)**: strictly sequential
- **Phase 5 (US3)** and **Phase 6 (US4, run page only)**: depend on Foundational; independent of each other
- **Polish (Phase 7)**: depends on the stories you intend to ship

### The deliberate priority inversion

US1 is P1 and US2 is P2, but **US2 is implemented first**. US1's acceptance criteria require the new sheet to land "at the path the roster names" — it cannot resolve a destination without US2's naming rule. Delivery order follows the dependency, not the priority number. The MVP is therefore Phase 2 + Phase 3 + Phase 4.

### Cross-story dependencies (the only ones)

- T038 (roster editor player column) and T041 (route round-trip test) depend on **T031** (the model field, US3)
- Everything else in US4 is independent of US3

### Within each story

- Tests before implementation where they are the guard (T028 for D9, T021 for D7)
- `campaignlib` primitives before the `dnd_sheet` orchestration that calls them
- CLI before the router that forwards to it; router before the Vue page

---

## Parallel Opportunities

```bash
# Phase 2, after T003/T004 land:
Task: "T006 level parsing in campaignlib/sheet_identity.py"
Task: "T008 attribution tests in tests/test_sheet_naming.py"

# Phase 3 tests, all independent files/blocks:
Task: "T011 destination cases in tests/test_sheet_naming.py"
Task: "T012 orchestration tests in tests/test_dnd_sheet.py"
Task: "T013 legacy-mode tests in tests/test_dnd_sheet.py"

# Phase 4 tests:
Task: "T019 level cases"
Task: "T020 archive cases"
Task: "T021 ordering/crash-safety case"

# Phase 7 docs, three separate files:
Task: "T043 amend docs/design/PartyRosterCanonicalFormat.md"
Task: "T044 document in docs/cli/cli_tools.md"
Task: "T045 update the dnd_sheet module docstring"
```

Phases 5 and 6 can run concurrently once Phase 4 is done, provided T031 lands before T038/T041.

---

## Implementation Strategy

### MVP (Phases 1–4)

1. Setup → Foundational
2. US2 (naming) → **validate**: a character with no existing sheet converts to a roster-named file; a mismatch refuses with the exact fix
3. US1 (archival) → **validate**: the level-up round trip archives and writes; a re-run refuses on the occupied slot
4. **Stop here and use it.** This is the whole hand procedure automated. `player` and the UI add reach, not core value

### Incremental delivery

1. MVP as above
2. US3 → the roster owns the player name; re-exports stop destroying corrections
3. US4 → the same flow from the browser
4. Polish → docs amended, campaigns migrated, quickstart executed

### Notes

- `~/campaigns` is a **different repo**: T047 and T048 are a separate branch and PR there
- Never commit directly to `main` in either repo
- Expect Phandalin to refuse twice on first real run (T047) — that is the design working
- Commit after each task or logical group; every checkpoint is a safe stopping point
