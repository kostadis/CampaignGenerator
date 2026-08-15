---

description: "Task list for Player Entity & Config Service"
---

# Tasks: Player Entity & Config Service

**Input**: Design documents from `/specs/009-player-entity-service/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: Included. The plan requests them by name (research D15), and one of them —
the prefix-matching guard — is what turns SC-006 from a claim into an assertion.

**Organization**: Grouped by user story so each is independently implementable and
testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete work)
- **[Story]**: US1–US5, mapping to the spec's user stories
- Exact file paths in every description

## Path Conventions

Repository root is the worktree at
`/home/kroussos/src/CampaignGenerator/.claude/worktrees/009-player-entity-service`.
Layers, per [plan.md](./plan.md): `campaignlib/` (models, pure logic),
`pipelines/` + `session_doc/` (CLI engines), `server/` (thin routers over services),
`frontend/src/` (the face), `tests/` at root.

**Campaign data lives in a different repository** — `~/src/campaigns`. Phase 9's
rollout tasks change that repo and need their own branch and PR there.

> ⚠️ **Build order is not priority order.** The phases below follow the spec's
> value priority (P1…P5). The *code* can land in that order on one branch. The
> **data** rollout cannot: adoption (US4) must run in a campaign before that
> campaign's consumers are switched over, or it breaks — loudly, by design, but not
> a state to ship through. See research D17 and Phase 9.

---

## Phase 1: Setup

**Purpose**: Establish that you are testing this branch, and take the baseline every
later measurement is compared against.

- [X] T001 Confirm the worktree resolves this branch's code and not the main checkout — run `python -c "import campaignlib, sys; print(campaignlib.__file__)"` from the repo root and verify the path contains `009-player-entity-service`; if it does not, re-read `tests/conftest.py`'s `REPO_ROOT` insertion and research D16 before continuing
- [X] T002 [P] Capture the baseline reading by running `python3 specs/009-player-entity-service/contracts/measure.py` and saving its output to `specs/009-player-entity-service/contracts/baseline.txt` — this is the "before" column of quickstart.md's final table and the evidence for SC-002 and SC-004

**Checkpoint**: You know which code you are running, and you have a recorded starting state.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The player model and its document I/O. Every user story reads it.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 [P] Write `tests/test_players_config.py` covering the whole contract in `specs/009-player-entity-service/contracts/players.yaml.md`: round-trip fidelity, absent file → empty config, empty file → empty config, non-mapping top level, duplicate `id`, a display name under two players, unknown key, defaults omitted on save — **run it and confirm it fails**
- [X] T004 Create `campaignlib/players_config.py` with `PLAYERS_CONFIG_FILENAME = "players.yaml"`, the `Player` model (`id`, `name`, `display_names`, `plays`, `gm`, `active`, `dndbeyond_id`) and the `PlayersConfig` root, both `ConfigDict(extra="forbid")`, per data-model.md §1
- [X] T005 Add `load_players_config(path)` and `save_players_config(path, cfg)` to `campaignlib/players_config.py` — atomic via `campaignlib.util.atomic_write_text`, hand-built dict at **both** ends, defaults omitted; copy the "a field named in only one end round-trips to nothing" warning comment from `campaignlib/party_config.py:246`
- [X] T006 Add the four refusals to `campaignlib/players_config.py`: blank/missing `id`, blank/missing `name`, duplicate `id` naming both entries, a display name held by two players naming both players and the value (FR-005a, FR-005b)
- [X] T007 [P] Export `Player`, `PlayersConfig`, `load_players_config`, `save_players_config`, `PLAYERS_CONFIG_FILENAME` from `campaignlib/__init__.py`, following the block at lines 59–61 and 171–173
- [X] T008 Run `python -m pytest tests/test_players_config.py tests/test_layering.py -q` — the model tests pass and the layering guard still passes (nothing in `campaignlib` may import `server`)

**Checkpoint**: The document exists, loads, saves, and refuses. Nothing reads it yet.

---

## Phase 3: User Story 1 — Say who is at the table, once (Priority: P1) 🎯 MVP

**Goal**: A Players page and a service that owns `<campaign>/config/players.yaml`.
Purely additive — no existing behaviour changes.

**Independent Test**: On a campaign with no player document, open Setup → Players,
add three players with display names and character bindings, reload, and confirm the
values came back in the order authored. Break the file by hand and confirm the page
names what is wrong. Nothing else in the app behaves differently.

### Tests for User Story 1

> **Write these first; confirm they fail.**

- [X] T009 [P] [US1] Write `tests/test_players_config_service.py` mirroring `tests/test_party_config_service.py`: `get_players` on a missing file returns `[]` (not a 400), `replace_all` is one atomic write, duplicate `id` → 409, duplicate display name → 409, an unloadable document → 400 naming the entry
- [X] T010 [P] [US1] Write `tests/test_players_routes.py` mirroring `tests/test_party_routes.py`: every route in `contracts/http.md`, the `problems` array shape, and an assertion that the router does **not** set its own `prefix=` (the `/api/players/api/players/*` bug `party_routes.py` records)

### Implementation for User Story 1

- [X] T011 [US1] Create `server/players_config_service.py` — `PlayersConfigService(platform)` deriving its path from `platform.config_path_base / PLAYERS_CONFIG_FILENAME`, with `get_players`, `get_player`, `create_player`, `update_player`, `delete_player`, `replace_all`; model it on `server/party_config_service.py` including its 404/409/400 contract and its `replace_all` docstring rationale
- [X] T012 [US1] Add `_with_problems(player)` to `server/players_config_service.py` — attaches `unknown_character` and `no_display_name` findings by cross-reading `party.yaml`, and **never blocks a write** (FR-017); mirrors `PartyConfigService._with_missing`
- [X] T013 [US1] Create `server/routers/players_routes.py` with the seven routes in `specs/009-player-entity-service/contracts/http.md`, per-request DI via `require_platform`, and **no `prefix=` on the router** — leave the `/check` route returning 501 until T054
- [X] T014 [US1] Register the router in `server/main.py` beside its siblings: `app.include_router(players_routes.router, prefix="/api/players", tags=["players"])`
- [X] T015 [P] [US1] Create `frontend/src/components/shared/PlayersEditor.vue` — a table edited as a unit with add/remove/reorder, saved through one `PUT /api/players/players`; model it on `frontend/src/components/shared/PartyConfigEditor.vue`
- [X] T016 [P] [US1] Create `frontend/src/views/setup/Players.vue` hosting `PlayersEditor`, showing each row's `problems` inline
- [X] T017 [US1] Add the route `{ path: 'players', name: 'players', component: () => import('./views/setup/Players.vue') }` under the `/setup` children in `frontend/src/router.ts` (research D4)
- [X] T018 [US1] Add the nav entry for Players in `frontend/src/views/SetupTools.vue`
- [X] T019 [US1] Add a cross-link from the roster editor in `frontend/src/components/shared/PartyConfigEditor.vue` to `/setup/players`, so the two halves of "who is at my table and what do they play" are one click apart (research D4)
- [X] T020 [US1] Run `python -m pytest tests/test_players_config_service.py tests/test_players_routes.py -q` and walk quickstart.md Scenario 1 in a browser, including the timing check for SC-007

**Checkpoint**: US1 is complete and demonstrable on its own. `players.yaml` exists and is authored; nothing reads it.

---

## Phase 4: User Story 2 — Every consumer reads the entity (Priority: P2)

**Goal**: The roster prompt line, transcript speaker normalisation, the game-master
label and the sheet stamp all resolve through the service. `party.yaml` loses
`player:`.

**Independent Test**: Change one player's display name in `players.yaml`. Without
touching any other file and without re-converting a sheet, run speaker normalisation
over a transcript using the new label and confirm the lines resolve to that player's
character.

### Tests for User Story 2

> **Write these first; confirm they fail.**

- [X] T021 [P] [US2] Write `tests/test_players_speaker_map.py` for `speaker_map`: two display names for one player both resolve; longest key wins for `Mike` / `Mike Hall`; **a person who is both GM and PC gets the game-master label on every line and the character label on none** (FR-021a); an inactive player's display names still resolve
- [X] T022 [P] [US2] Update `tests/test_roster.py` — `roster_from_config` takes the person's name from the entity, excludes inactive players (FR-019), and still reads `species`/`class_level`/`subclass` from the sheet
- [X] T023 [P] [US2] Update `tests/test_prep.py` for `normalize_vtt_speakers` losing its `gm_player` parameter, and add a case where a character has no bound player → the caller refuses by name (FR-024)
- [X] T024 [P] [US2] Update `tests/test_party_config.py` and `tests/test_party_config_service.py` — `player` is gone from `PartyCharacter`, and a document still carrying it is refused naming the character and the retired field (FR-013)

### Implementation for User Story 2

- [X] T025 [US2] Add `speaker_map(players, party) -> dict[str, str]` to `campaignlib/players_config.py` — player display names first, then game-master display names **last so they overwrite** (research D9, FR-021a)
- [X] T026 [US2] Drop the `gm_player` parameter from `normalize_vtt_speakers` in `campaignlib/npc.py:345`; it now takes the finished map. Longest-key-first matching is unchanged
- [X] T027 [US2] Rewrite `player_map_from_config` in `campaignlib/npc.py:294` to build from the players config instead of `frontmatter.get("player")` at line 331 (research D13)
- [X] T028 [US2] Rewrite the player half of `roster_from_config` in `session_doc/roster.py:136` — the person's name comes from the entity, inactive players are excluded, and the sheet is still read for `species`/`class_level`/`subclass`
- [X] T029 [US2] Remove `player` from `PartyCharacter` and `ResolvedCharacter` in `campaignlib/party_config.py`, remove it from `load_party_config` and `save_party_config`, and add a **detection-and-refusal** for a document that still carries it, with the adoption command in the message
- [X] T030 [P] [US2] Add `--players-config PATH` to `pipelines/content_ingest/dnd_sheet.py` and source the value passed to `apply_roster_player` at line 387 from the bound player's `name` (FR-022)
- [X] T031 [P] [US2] Add `--players-config PATH` to `session_doc/scene_extract.py` and **delete `--gm-player`** (lines 286, 416–430); build the speaker map from the two configs
- [X] T032 [P] [US2] Add `--players-config PATH` to `session_doc/enhance_summary.py` and **delete `--gm-player`** (lines 272, 112–114, 357); the expected-speaker pre-flight now draws its set from the entity
- [X] T033 [P] [US2] Delete the `--gm-player` argument and its forwarding from `session_doc/sd_agent.py` (lines 245–246, 301)
- [X] T034 [P] [US2] Add `--players-config PATH` to `session_doc/sd_narrate.py` and pass it through to `roster_from_config`
- [X] T035 [US2] Remove `gm_player` from the `Roster` model in `server/session_editor_config_shared.py:324` and its entry from `TYPED_SESSION_DOC_TO_GROUPED` at line 397, so a stale key is **reported as unrecognised** rather than migrated
- [X] T036 [US2] In `server/routers/scene_editor.py`, replace the `--gm-player` construction at lines 1086–1090 with `--players-config`, resolved from `platform.config_path_base`
- [X] T037 [US2] Remove the player column from `frontend/src/components/shared/PartyConfigEditor.vue` and point its help text at the Players page
- [X] T038 [US2] Run `python -m pytest tests/ -q` and walk quickstart.md Scenario 3 against a scratch copy of a real campaign

**Checkpoint**: One edit in one place reaches every consumer. SC-001 is demonstrable.

---

## Phase 5: User Story 3 — A character's voice and examples arrive because it named them (Priority: P3)

**Goal**: Two declared paths per character plus a campaign-level shared list. The
first-name-prefix rule is **deleted**, not supplemented.

**Independent Test**: Replay the out-of-the-abyss state — roster says `Gyrgum`, files
are named `grygum` — and confirm the run refuses before the first API call, naming
both the character and the path. Confirm toee's six house-style files still reach
every narrator, and that nothing is reported as mis-routed.

### Tests for User Story 3

> **Write these first; confirm they fail.**

- [X] T039 [P] [US3] Write the guard test `tests/test_no_prefix_identity.py` — assert that `routes_to`, `examples_routing_problems` and `_resolve_voice_key` do not exist in `session_doc.examples` / `session_doc.voice`, and that no module in the render path resolves an identity via `startswith`; this is what makes SC-006 countable (research D15)
- [X] T040 [P] [US3] Update `tests/test_sd_narrate.py` — per-character voice and examples come from declared paths; an absent declared path refuses before the first API call; `shared_examples` is the only source of the global block; there is no fall-through
- [X] T041 [P] [US3] Update `tests/test_editor_pipeline.py` — its `Roster(characters=…)` fixtures (lines 27–44, 736–755) and the three `--characters` forwarding assertions (lines 240–272, 796–812) reflect argv built from the roster
- [X] T042 [P] [US3] Add cases to `tests/test_party_config.py` for `voice`/`examples` in `PATH_FIELDS`, `shared_examples` round-tripping through **both** loader and saver, and `missing_files` reporting an absent declared file

### Implementation for User Story 3

- [X] T043 [US3] Add `voice` and `examples` as optional `AuthoredPath` fields on `PartyCharacter` in `campaignlib/party_config.py`, and extend `PATH_FIELDS` to `("sheet", "backstory", "dossier", "arc_score", "voice", "examples")` so `missing_files` reports them with no new code
- [X] T044 [US3] Add the `shared_examples: list[str]` root key to `PartyConfig` in `campaignlib/party_config.py`, naming it in **both** `load_party_config` and `save_party_config`
- [X] T045 [US3] Add `voice`, `examples` and resolved `shared_examples` to `ResolvedCharacter` / `ResolvedPartyConfig` and to `resolve_party_config` in `campaignlib/party_config.py`
- [X] T046 [US3] In `session_doc/voice.py`: **delete `_resolve_voice_key`**, rewrite `get_voice_note` as an exact character-name lookup over declared files, rewrite `voice_resolution_problems` to report "declared file missing", and **keep `load_voice_files` and `extract_contrast_sample` untouched** — `pipelines/ensemble/polish.py` and the orphan check still enumerate a directory (research D7)
- [X] T047 [US3] In `session_doc/examples.py`: **delete `routes_to` and `examples_routing_problems`** (this closes #315 by removing the detector along with the fall-through it failed to detect), rewrite `get_char_examples` as an exact lookup, and keep `example_files`
- [X] T048 [US3] Rewrite `_load_examples` in `session_doc/sd_narrate.py:162` to read each character's declared `examples` path and to build the global block **only** from `shared_examples` — no fall-through (FR-030a)
- [X] T049 [US3] Delete the `--characters` argument from `session_doc/sd_narrate.py:224` and its consumers at lines 333 and 448–468
- [X] T050 [US3] In `server/routers/scene_editor.py`: rebuild the narrate argv (lines 760–815, 827–873) to pass `--party-config`, drop `--voice-dir`/`--examples`/`--characters`, and change both pre-flights to check declared paths; source `sd_plan --characters` at line 1651 from `party.yaml`'s character names
- [X] T051 [US3] Remove `characters` from the `Roster` model in `server/session_editor_config_shared.py:318`, delete the now-empty `Roster` class and its field on `SessionEditorConfig:367`, and remove its `TYPED_SESSION_DOC_TO_GROUPED` entry at line 396
- [X] T052 [US3] Add `voice` and `examples` columns and a `shared_examples` list editor to `frontend/src/components/shared/PartyConfigEditor.vue`, rendering the `missing_files` report per row
- [X] T053 [US3] Run `python -m pytest tests/ -q` and walk quickstart.md Scenarios 4 and 5 (the Gyrgum replay in all three variants, plus toee and obelisk shared examples)

**Checkpoint**: Zero identity joins in the render path resolve by name prefix. #315 is closed by deletion.

---

## Phase 6: User Story 4 — Adopt six existing campaigns (Priority: P4)

**Goal**: A one-shot per campaign that drafts the roster from what already exists and
**reports every conflict rather than resolving it**.

**Independent Test**: Run it against a campaign whose stores are known to disagree
and confirm both values and their sources are listed and neither is written. Run it
twice and confirm the second run refuses without `--force`.

### Tests for User Story 4

> **Write these first; confirm they fail.**

- [X] T054 [P] [US4] Write `tests/test_migrate_players_config.py` mirroring `tests/test_migrate_grounding_config.py`: harvest from all four sources; a conflict is reported and **not** written; `--force` is required to overwrite; placeholder values become "no display name"; unrecognised keys are reported; a bare-name-list `party.yaml` refuses that campaign by name

### Implementation for User Story 4

- [X] T055 [US4] Create `server/migrate_players_config.py` reading the four sources in `contracts/cli.md` §4 — `party.yaml`'s `player:`, each sheet's frontmatter `player`, `session_doc.yaml`'s `roster.gm_player`, and the `voice_dir`/`examples_dir` listings; read `session_doc.yaml` **raw** via `yaml.safe_load`, not through the typed model, since the fields are being deleted (the rationale `server/migrate_grounding_config.py` records)
- [X] T056 [US4] Add conflict detection and reporting to `server/migrate_players_config.py` — when two sources disagree about a person, print both values with their origins and write neither (FR-032)
- [X] T057 [US4] Apply the placeholder vocabulary from `campaignlib/npc.py:231` in `server/migrate_players_config.py` so `(Not specified)` / `N/A` / `tbd` become "no display name", never a person (FR-034)
- [X] T058 [US4] Propose `voice` and `examples` declarations in `server/migrate_players_config.py` by applying the *outgoing* prefix rule once, and **list every file it attributed to nobody** as a `shared_examples` candidate for the GM to rule on (FR-035)
- [X] T059 [US4] Write the three outputs from `server/migrate_players_config.py`: create `players.yaml`, add declarations and `shared_examples` to `party.yaml` and remove its `player:`, remove the `roster` group from `session_doc.yaml`
- [X] T060 [US4] Add the two refusals to `server/migrate_players_config.py`: an existing `players.yaml` without `--force`, and a `party.yaml` whose `characters:` entries carry no `sheet:` — the obelisk shape, refused by name rather than crashed on (research D12, M2)
- [X] T061 [US4] Make `server/migrate_players_config.py` state plainly when it harvested little — four of six campaigns record no player at all (research M1), and an almost-empty result there is correct, not a failure
- [X] T062 [US4] Run `python -m pytest tests/test_migrate_players_config.py -q` and walk quickstart.md Scenario 2 against scratch copies of out-of-the-abyss, toee, Hillsfar and obelisk

**Checkpoint**: A campaign can be adopted without retyping, and every conflict reaches the GM.

---

## Phase 7: User Story 5 — Drift is reported before a run (Priority: P5)

**Goal**: A deterministic, model-free, read-only check.

**Independent Test**: Replay the `Gyrgum` state and confirm the check names it. Point
a campaign at a transcript from a different campaign and confirm each absent display
name is named — including when only one of four is absent.

### Tests for User Story 5

> **Write these first; confirm they fail.**

- [X] T063 [P] [US5] Write `tests/test_players_check.py` covering all six report sections in `contracts/cli.md` §3, exit 0 clean / 1 with findings, a character played only by an **inactive** player not reported as unplayed, and the one-of-four-absent transcript case

### Implementation for User Story 5

- [X] T064 [US5] Create `pipelines/workspace/players.py` with a `check` subcommand and a `collect_findings()` function returning the structure in `contracts/http.md`; it must import nothing from `server` (research D1, D10)
- [X] T065 [US5] Implement the four config-only sections in `pipelines/workspace/players.py`: characters no **active** player plays, `plays` entries with no matching character, players with no display name, declared files that are absent
- [X] T066 [US5] Implement orphan detection in `pipelines/workspace/players.py` — files in `voice_dir`/`examples_dir` that no character and no `shared_examples` entry declares; this is what a rename produces, and research M3/M4 says three campaigns have one today
- [X] T067 [US5] Implement `--vtt FILE` in `pipelines/workspace/players.py`, reporting **each** expected display name absent from the transcript, not only the all-absent case the existing pre-flight covers (FR-039)
- [X] T068 [US5] Add `players = "pipelines.workspace.players:main"` to `[project.scripts]` in `pyproject.toml` and reinstall with `uv pip install -e . --python "$VIRTUAL_ENV/bin/python"` — console scripts resolve relative to the server's python, not `$PATH`
- [X] T069 [US5] Replace the 501 stub with the real `GET /api/players/check` in `server/routers/players_routes.py`, reusing `collect_findings()` so the page and the CLI cannot disagree
- [X] T070 [US5] Run `python -m pytest tests/test_players_check.py -q` and walk quickstart.md Scenario 6

**Checkpoint**: Every failure mode the spec records as silent now has a named report.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T071 [P] Write `docs/config/players-isolation.md` in the shape of `docs/config/planning-isolation.md` — ownership, the strict document, the lenient-save contract, the adoption step, and the decisions from research.md
- [X] T072 [P] Add the Players row to the per-service config table in `CLAUDE.md`, and a short rule under it stating that player identity is authored in one place and every other copy is rendered — the shape of the existing genre-rulebook rule
- [X] T073 [P] Add `docs/config/players-isolation.md` to the doc index in `docs/README.md` and the service to the subsystem map in `docs/core/architecture.md`
- [ ] T074 [P] Add a status note to `docs/design/PlayerIdentity.md` recording which of its five open questions this feature answered, and add research M3's stormgiants finding to its "Measured drift" section
- [X] T075 [P] Update `docs/cli/session_doc_pipeline.md` for the deleted `--characters` and `--gm-player` flags and the new `--players-config`
- [X] T076 Run the whole suite: `python -m pytest tests/ -q`, including `tests/test_layering.py` and `tests/test_no_prefix_identity.py`

---

## Phase 9: Campaign data rollout (repository `~/src/campaigns`)

**Purpose**: Move the six campaigns onto the new shape. **This is a different
repository** — branch it and open its own PR. Research D17's ordering governs here:
adopt a campaign before relying on it.

- [X] T077 Adopt Phandalin — `python -m server.migrate_players_config --campaign-dir ~/src/campaigns/Phandalin`, rule on each conflict, and confirm the four `*_new_pipeline.md` voice files are now declared; they resolve **only** through the deleted prefix rule today (research M4), so this campaign is the one that proves the ordering
- [X] T078 Adopt out-of-the-abyss — run the migration, rule on conflicts, and verify `vizeran_voice.md` is reported as an orphan rather than silently carried
- [X] T079 Adopt stormgiants and rule on two findings research M3/M5 surfaced: `examples/thistl.md` is a typo that reaches every narrator while `Thistle` gets nothing, and **`Thistle` is missing from `party.yaml` entirely** (3 characters listed, 4 voice files). Both are GM rulings about campaign data
- [X] T080 [P] Adopt toee — declare all six house-style files in `shared_examples`, and record `kostadis` as `gm: true` with `plays: [Calmer]` so FR-021a is exercised on real data
- [X] T081 [P] Adopt Hillsfar — expect nothing harvested (0 of 4 record a player) and confirm the placeholder values became "no display name", not a person named `N/A`
- [ ] T082 File an issue against CampaignGenerator for the obelisk blocker: `config/party.yaml` is a PC-name exclusion list read by `campaignlib.party.load_party_names` and a roster read by `load_party_config`, two contracts over one filename, and which wins is a GM ruling (research M2, D12)
- [X] T083 Run `players check` against all five adopted campaigns and confirm each exits 0, or that every finding is a recorded, accepted state

---

## Phase 10: Close-out

- [ ] T084 Run the full quickstart at `specs/009-player-entity-service/quickstart.md`, all seven scenarios
- [X] T085 Re-run `python3 specs/009-player-entity-service/contracts/measure.py` and diff against `contracts/baseline.txt` from T002; the after-column of quickstart.md's final table must hold — no undeclared global block, every orphan reported
- [ ] T086 Comment on and close CampaignGenerator #315 — the detector is deleted along with the fall-through it could not see (T047)
- [ ] T087 Open the CampaignGenerator PR from `009-player-entity-service`, referencing `docs/design/PlayerIdentity.md` (#314), #315, #312 and #293, and open the companion PR in `~/src/campaigns`

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 (Setup)**: no dependencies
- **Phase 2 (Foundational)**: depends on Phase 1 — **blocks every user story**
- **Phase 3 (US1)**: depends on Phase 2
- **Phase 4 (US2)**: depends on Phase 2; T025 needs T004–T006
- **Phase 5 (US3)**: depends on Phase 2. Independent of US2 in code — it touches
  `party.yaml`'s path fields and the routing rule, not the player model — **except**
  that T029 (US2) and T043–T045 (US3) edit `campaignlib/party_config.py`, and
  T035 (US2) and T051 (US3) edit `server/session_editor_config_shared.py`. Same-file
  conflicts, so do not run those two pairs concurrently.
- **Phase 6 (US4)**: depends on Phase 2 for the model, and on the **shapes** US2 and
  US3 define. Writing it before them means writing against a moving target; the tests
  (T054) can be written any time after Phase 2.
- **Phase 7 (US5)**: depends on Phase 2 and on US3's declared fields (T043–T045),
  since three of its six sections report on declarations
- **Phase 8 (Polish)**: depends on Phases 3–7
- **Phase 9 (Rollout)**: depends on Phase 8, and **per campaign** on US4 having run
  there before that campaign is used
- **Phase 10 (Close-out)**: depends on Phase 9

### User story dependencies

| Story | Depends on | Independently testable? |
|---|---|---|
| US1 (P1) | Foundational only | **Yes** — the page and file work with nothing else changed |
| US2 (P2) | Foundational | **Yes** — with a hand-written `players.yaml` fixture |
| US3 (P3) | Foundational | **Yes** — with a hand-written `party.yaml` fixture; needs no player data |
| US4 (P4) | US2 + US3 shapes | **Yes** — against scratch campaign copies |
| US5 (P5) | US3's declared fields | **Yes** — against fixtures |

### Within each user story

- Tests are written first and confirmed failing
- Models (`campaignlib`) → services (`server`) → routes → frontend
- Engine CLIs (`session_doc`, `pipelines`) before the argv builder in `scene_editor.py`
- Checkpoint task last

### Parallel opportunities

- T002 alongside T001
- All four Phase 2 test/export tasks marked [P]
- T009 and T010 together; T015 and T016 together
- **US2's five CLI edits, T030–T034, are five different files** — the widest parallel
  block in the feature
- All four US3 test tasks, T039–T042, together
- Five of the six Phase 8 documentation tasks
- T080 and T081 (two campaigns with nothing to harvest)

---

## Parallel Example: User Story 2

```bash
# The four test files first — different files, no dependencies:
Task: "Write tests/test_players_speaker_map.py"                    # T021
Task: "Update tests/test_roster.py"                                # T022
Task: "Update tests/test_prep.py"                                  # T023
Task: "Update tests/test_party_config.py + test_party_config_service.py"  # T024

# Then the five CLI seams — five separate files:
Task: "--players-config in pipelines/content_ingest/dnd_sheet.py"  # T030
Task: "--players-config in session_doc/scene_extract.py"           # T031
Task: "--players-config in session_doc/enhance_summary.py"         # T032
Task: "drop --gm-player from session_doc/sd_agent.py"              # T033
Task: "--players-config in session_doc/sd_narrate.py"              # T034
```

---

## Implementation Strategy

### MVP first (User Story 1 only)

1. Phase 1 — Setup
2. Phase 2 — Foundational (blocks everything)
3. Phase 3 — US1
4. **Stop and validate**: quickstart Scenario 1. The Players page works, the document
   persists, the refusals fire. Nothing else in the app changed.

This is a genuine standalone increment: a legible answer to "who is at my table and
what do they play" existed nowhere before, and it is worth having on its own.

### Incremental delivery

| Increment | Adds | Demonstrates |
|---|---|---|
| MVP (US1) | the page, the service, the document | the fact is written down once |
| +US2 | consumers read it | **SC-001** — one edit, every consumer, no re-conversion |
| +US3 | declared routing | **SC-005, SC-006** — the Gyrgum replay refuses; zero prefix joins |
| +US4 | adoption | **SC-003** — six campaigns, every conflict ruled on |
| +US5 | the check | **SC-004** — every silent failure gets a name |

### Parallel team strategy

With three developers after Phase 2: US1 (full stack, frontend-heavy), US2 (CLI
seams, the widest parallel block), US3 (the deletion). Reserve
`campaignlib/party_config.py` and `server/session_editor_config_shared.py` — US2 and
US3 both edit them, and those are the only two same-file conflicts in the feature.

---

## Notes

- **[P] means different files.** The two exceptions are called out above.
- **Every deletion is a deletion.** T029, T035, T046, T047, T049, T051 remove fields
  and functions rather than deprecating them. That is FR-036 and it is what makes
  T039's guard test meaningful.
- **A green worktree suite is not sufficient evidence** (research D16, #286). Every
  checkpoint pairs pytest with a quickstart scenario against a real campaign
  directory.
- **Two repositories.** Phases 1–8 and 10 change CampaignGenerator; Phase 9 changes
  `~/src/campaigns` and needs its own branch and PR.
- **Never commit to `main`** in either repository. Feature branch, PR, and wait for
  the go-ahead before merging.
- Commit after each task or logical group. Stop at any checkpoint to validate.
