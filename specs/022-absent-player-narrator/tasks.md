---

description: "Task list for 022-absent-player-narrator"
---

# Tasks: A narrator must have been in the scene

**Input**: `specs/022-absent-player-narrator/` — [spec.md](./spec.md), [plan.md](./plan.md)

**Tests**: Included. SC-008 requires a regression test by name, the constitution requires every plan be tested against its principles, and every filter in this feature is a pure function over strings — testable with no API key, no network, and no model call.

**Organization**: Grouped by user story. Phase 2 is genuinely blocking: every story consumes the same three helpers.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependencies)
- **[Story]**: US1–US6 per spec.md

## Path Conventions

Single project at repository root: `campaignlib/`, `session_doc/`, `server/`, `frontend/src/`, `tests/`.

---

## Phase 1: Setup

**Purpose**: the shared fixture every later test needs.

- [ ] **T001** Add a `plan_eligibility` fixture module to `tests/conftest.py` (or a new `tests/fixtures/eligibility.py`) modelling the 20260902 shape: four roster characters, a VTT whose labels cover three players, and five scene bodies — one character with **zero** labels in every scene, one character absent from scene 3 only, and GM narration that *names* the zero-label character in prose without ever labelling him. That last detail is the fixture's whole point (plan.md D1).
- [ ] **T002** [P] Add a second fixture variant with one scene whose only label is `GM` — the uncoverable case, which 20260902 does not contain and cannot be regression-tested from.

**Checkpoint**: fixtures exist and are importable; no production code touched yet.

---

## Phase 2: Foundational (BLOCKING)

**Purpose**: the three deterministic helpers. No behaviour changes anywhere until this is done.

**⚠️ No user story can begin until Phase 2 is complete.**

### Tests first

- [ ] **T003** [P] `tests/test_plan_eligibility.py` — `speaker_labels()`: extracts `Name:`-prefixed labels from VTT text, ignores colons inside dialogue, matches the same shape `normalize_vtt_speakers` rewrites.
- [ ] **T004** [P] `tests/test_plan_eligibility.py` — `scene_speakers()`: reads `moments` only; **a prose mention is not a label** (the zero-label character named in GM narration must not be returned); drops `GM`; skips bracketed action-beat tags (`**[The Drow Spy Spotted]**`); returns `Valphine Sotorra` for scenes 1/2/4/5 and not for scene 3.
- [ ] **T005** [P] `tests/test_plan_eligibility.py` — `attending_players()` / `absent_characters()`: a player is present iff a declared `display_names` entry appears; `active: false` players are not resurrected; a character with `plays: []` is never eligible.
- [ ] **T006** `tests/test_plan_eligibility.py` — the composed pool and per-scene candidate sets over the T001 fixture: pool excludes the zero-label character; scene 3 candidates exclude the scene-3-absent character; every other scene has three candidates.

### Implementation

- [ ] **T007** Move `_read_vtt_speakers` from `pipelines/workspace/players.py:50` to `campaignlib/vtt.py` as `speaker_labels(text: str) -> set[str]` — taking **text, not a Path**, so it is testable without the filesystem. Keep the line-prefix shape and its docstring's reasoning intact (Principle V: one definition of "this label is present").
- [ ] **T008** Update `pipelines/workspace/players.py` to read the file and call `campaignlib.vtt.speaker_labels`; delete the private copy. `tests/test_players_check.py` must stay green **unmodified** — that is the proof the move changed no behaviour.
- [ ] **T009** [P] Add `attending_players(cfg: PlayersConfig, labels: set[str]) -> set[str]` and `absent_characters(cfg, roster: list[str], labels) -> set[str]` to `campaignlib/players_config.py`, beside `player_name_for`, which already owns the active/inactive rule.
- [ ] **T010** [P] Add `scene_speakers(moments: str) -> set[str]` to `session_doc/io.py`, next to `load_scene_extractions`. Anchor on `(?m)^\*\*([^*]+)\*\*`; drop `GM`; skip labels wrapped in `[...]`.
- [ ] **T011** Create `session_doc/plan_eligibility.py`: pure functions composing T009 + T010 into the narrator pool, the per-scene candidate sets, and an exclusion report structure. No file I/O, no argparse, no model call — it is handed strings and returns data.

**Checkpoint**: T003–T006 pass. Nothing in the pipeline behaves differently yet.

---

## Phase 3: User Story 1 — An absent player's PC is not offered a scene (P1) 🎯 MVP

**Goal**: a character whose player was not at the table cannot narrate anything.

**Independent Test**: run `sd_plan` on 20260902 with the VTT and `players.yaml`; assert no `narrator: Brewbarry` and every narrator in {Vukradin, Soma, Valphine Sotorra}.

- [ ] **T012** [US1] `tests/test_sd_plan_refusals.py` — no `--vtt` refuses; an empty pool refuses naming a probable wrong VTT; neither falls back to the unnarrowed roster (FR-003, FR-004, D5).
- [ ] **T013** [US1] Add `--vtt` and `--players-config` to `session_doc/sd_plan.py`, spelled and defaulted exactly as on `sd_verify_quotes` / `scene_extract` / `enhance_summary` (FR-019, Principle XII). `--characters` keeps its current meaning (D6).
- [ ] **T014** [US1] Compute the pool via `plan_eligibility` before the prompt is built, and add the two refusals from T012.
- [ ] **T015** [US1] Fix the inverted gap warning at `session_doc/sd_plan.py:165` — `missing` is computed against the **eligible** set, never the campaign roster (FR-014). This is the line that demanded the defect; leaving it would make the system complain about the correct outcome.

**Checkpoint**: SC-001 passes. The reported defect is fixed.

---

## Phase 4: User Story 2 — A narrator was in the scene they narrate (P1)

**Goal**: per-scene eligibility, and the prompt stops choosing from titles alone.

**Independent Test**: for each scene, the candidate set equals the characters with ≥1 label in that scene's extraction, and the written narrator is drawn from it.

- [ ] **T016** [US2] `tests/test_sd_plan_eligible_prompt.py` — the prompt carries per-scene candidate sets; a character absent from a scene never appears as its candidate; scene 3's set is exactly two names (SC-003).
- [ ] **T017** [US2] Replace the title-only checklist at `session_doc/sd_plan.py:140` with scene + candidate list (FR-007). `load_scene_extractions()` already returns the bodies — stop discarding them.
- [ ] **T018** [US2] Rewrite `config/agents/session_doc/plan.md`: candidates are the choice set; presence and access to the scene's discoveries outrank "most interesting perspective"; **rotation is a tiebreak among eligible candidates only** (FR-015) — delete "every character should appear if possible". Add a `pov:` line to the output format stating the presence basis.
- [ ] **T019** [US2] Confirm `parse_plan` (`session_doc/io.py:346`) tolerates the new `pov:` line — it is line-oriented and ignores unknown keys, so this should be an assertion in a test, not a change.
- [ ] **T020** [US2] Enforce eligibility on the parsed plan: a narrator outside a scene's candidate set is an error naming the scene, the narrator, and who was eligible (FR-006).

**Checkpoint**: SC-002, SC-003, SC-008 pass.

---

## Phase 5: User Story 4 — Exclusions are visible (P2)

**Goal**: no silent exclusion. Load-bearing, not cosmetic: the no-override ruling means the GM is the only correction path for a covered-PC misfire, and they cannot correct what they were not told.

- [ ] **T021** [US4] `tests/test_sd_plan_reporting.py` — a Filter A exclusion names character, player and VTT path; a Filter B exclusion names scene, character and the scene's eligible set; both print **before** the model call.
- [ ] **T022** [US4] Emit the exclusion report to stdout ahead of the API call (FR-016).
- [ ] **T023** [US4] Write the eligibility record beside `plan.md` in the narration dir — attendance with the matched label per player, per-scene candidates with line counts, and every exclusion (FR-017, Principle VIII).
- [ ] **T024** [US4] Report unrecognised speaker labels rather than dropping them, so a label arriving as `Vukradin (David)` surfaces as a visible anomaly instead of a silent loss of eligibility (plan.md Risks).

**Checkpoint**: SC-004 passes.

---

## Phase 6: User Story 3 — Uncoverable scenes become a choice (P2)

**Goal**: three plans, differing in the treatment of the scene nobody can narrate.

**Independent Test**: T002's fixture yields three plans with materially different treatments, and the next stage refuses until one is chosen.

- [ ] **T025** [US3] `tests/test_sd_plan_alternates.py` — with an uncoverable scene: three files written, **no** `plan.md`; the three are identical except the uncoverable scene and any scene a treatment explicitly absorbs it into (plan.md D3 as amended); each names the scene, the evidence, and its treatment.
- [ ] **T026** [US3] `tests/test_sd_plan_alternates.py` — with no uncoverable scene, exactly one `plan.md` and no choice requested (FR-013). This is what keeps the feature inert on ordinary sessions.
- [ ] **T027** [US3] Detect an empty candidate set; refuse outright when **every** scene is uncoverable (D5).
- [ ] **T028** [US3] Add the second, small model call proposing three treatments for the uncoverable scene, and assemble `plan.a.md` / `plan.b.md` / `plan.c.md` deterministically from the base plan plus each treatment (D3).
- [ ] **T029** [US3] Add `sd_plan --choose {a,b,c}`, writing the chosen alternate to `plan.md`. Choosing must be equivalent to `cp plan.b.md plan.md` (Principle IX).
- [ ] **T030** [US3] Reword the refusal at `server/routers/scene_editor.py:1408` so a pending choice reads as a pending choice, not as "run Plan & Check first". The gate itself already exists (D4) — do not add a second one.

**Checkpoint**: SC-006 passes.

---

## Phase 7: User Story 6 — Pass 5 knows who was unvoiced (P2)

**Goal**: the narration roster block distinguishes "in the party" from "voiced this session". Independent of Phases 4–6.

- [ ] **T031** [US6] `tests/test_roster_unvoiced.py` — the marker appears for an unvoiced character; species, class, subclass and player survive (FR-024); the marker's **text** asserts unvoiced and never absence-from-the-fiction (FR-023, D7). Assert the wording, not merely its presence.
- [ ] **T032** [US6] `tests/test_roster_unvoiced.py` — with no attendance argument, output is byte-identical to today's (FR-026). `tests/test_roster.py`'s existing ~15 cases must pass **unmodified**; that suite is the real regression guard here.
- [ ] **T033** [US6] Add an optional attendance parameter to `roster_from_config` (`session_doc/roster.py:78`), defaulting to `None` = today's behaviour. **`pipelines/ensemble/polish.py:888` is a second caller** and must stay inert.
- [ ] **T034** [US6] Add `--vtt` to `session_doc/sd_narrate.py` — it has `--players-config` but no tape — and pass the derived attendance into `roster_from_config` at line 382 (FR-025).

**Checkpoint**: SC-009 passes; `tests/test_roster.py` green unmodified.

---

## Phase 8: User Story 5 — UI parity (P2)

**Goal**: the editor and the CLI produce the same result. Confirmed in scope at review; no CLI-only exemption is claimed (Principle XI).

- [ ] **T035** [US5] `tests/test_editor_pipeline.py` — `_build_plan_cmd` passes `--vtt` and `--players-config`; `_build_narrate_cmd` passes `--vtt`; both via the existing `_vtt_path(cfg)` and players-config helpers rather than new literals.
- [ ] **T036** [US5] Wire both builders in `server/routers/scene_editor.py` (`_build_plan_cmd` at :2150, `_build_narrate_cmd` at :1379).
- [ ] **T037** [US5] Add a route to select an alternate, delegating to `sd_plan --choose` via `console_script` — the router must not reimplement the copy (Principle VI).
- [ ] **T038** [US5] Present the three plans and their treatments in `frontend/src/views/session/SessionDocEditor.vue`, and post the choice. The chosen plan is a file on disk, never browser state (Principle IX).
- [ ] **T039** [US5] Add the new choose-route to the `sd_plan` entry in `tests/test_backend_seam_guardrails.py:357`. Both `sd_plan` and `sd_narrate` already have reachability entries — extend, do not duplicate.

**Checkpoint**: SC-005 holds; UI and CLI agree.

---

## Phase 9: Polish

- [ ] **T040** [P] Document both filters, the three-plan choice, and the unvoiced marker in `docs/cli/session_doc_pipeline.md`.
- [ ] **T041** [P] Add the eligibility rule to `docs/cli/player_identity_howto.md` — the task-oriented entry point for "who is at the table", where a GM will look when a narrator they expected is missing.
- [ ] **T042** [P] Note the two filters in the repo `CLAUDE.md` beside the existing player-identity rules.
- [ ] **T043** Verify SC-005: re-run the planner on a session where everyone attended and every scene has an eligible narrator; confirm the output is comparable to today's and no new warnings appear.
- [ ] **T044** Run the full suite (`python -m pytest tests/`) — in particular `test_retrieve_render_isolation.py`, `test_no_prefix_identity.py` and `test_players_check.py`, none of which should need edits.

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2**: fixtures before helper tests.
- **Phase 2 blocks everything.** US1, US2, US3, US4 and US6 all consume `plan_eligibility`.
- **Phase 3 (US1) → Phase 4 (US2)**: both touch `sd_plan.py`'s prompt construction; sequential avoids a same-file collision.
- **Phase 5 (US4)** depends on Phases 3–4 for something to report.
- **Phase 6 (US3)** depends on Phase 4 — an uncoverable scene is defined by Filter B.
- **Phase 7 (US6)** depends only on Phase 2. It can run in parallel with Phases 3–6 by a second person; it touches `roster.py` and `sd_narrate.py`, which no other phase edits.
- **Phase 8 (US5)** depends on Phases 3, 6 and 7 — it exposes their flags and the choice.
- **Phase 9** last.

### Parallel opportunities

- T003, T004, T005 — different test functions, no shared state.
- T009, T010 — different files (`players_config.py`, `io.py`).
- Phase 7 alongside Phases 3–6, by a second person.
- T040, T041, T042 — three different docs.

---

## Implementation Strategy

**MVP (fixes the reported bug):** Phases 1, 2, 3. At that point Brewbarry cannot narrate and SC-001 passes.

**Recommended increment:** add Phase 4 (US2) and Phase 5 (US4) before shipping. US2 is the other P1 and is what stops a present-but-absent-from-this-scene narrator; US4 is what makes the no-override ruling survivable.

**Inert by design:** Phase 6 does nothing on a session where every scene has an eligible narrator, and Phase 7 does nothing on a session where everyone was voiced. Both are cost-free on ordinary sessions.

**Not optional:** Phase 8. Principle XI is explicit that "phase 2" is not an exemption, and no CLI-only ruling was granted at review.

---

## Notes

- The single highest-risk task is **T004**. A parser that reads prose instead of labels reintroduces the bug while appearing to fix it — the zero-label character is named in GM narration in four of five scenes of the real session.
- **T008** and **T032** are both "existing tests must pass unmodified" tasks. If either suite needs editing, the change did more than intended.
- Commit per task or logical group; the branch is `022-absent-player-narrator`.
