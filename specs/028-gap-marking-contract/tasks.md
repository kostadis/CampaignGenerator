# Tasks: Port the gap-marking contract onto the repo's narration prompt

**Input**: Design documents from `/specs/028-gap-marking-contract/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/gap-marking.md](./contracts/gap-marking.md),
[quickstart.md](./quickstart.md)

**Tests**: included. This repo gates the guarantee in tests rather than in review — the prompt
golden, the apparatus producer binding and the ensemble default guard are all build-breakers —
and FR-005's byte-identical promise is only meaningful as an assertion.

## Format: `[ID] [P?] [Story] Description`

- **[P]** — parallelizable: different files, no dependency on an incomplete task
- **[US1]–[US4]** — the user story from [spec.md](./spec.md)

## Path Conventions

Single project, existing layout. Prompt fragments under
`config/agents/session_doc/narrate/`, prompt assembly in `session_doc/narrate.py`, the CLI in
`session_doc/sd_narrate.py`, config in `server/session_editor_config_shared.py`, the route in
`server/routers/scene_editor.py`, the UI in `frontend/src/`.

---

## Phase 1: Setup — freeze what cannot be captured later

**⚠️ T001 IS ORDER-CRITICAL.** After the first template edit the pre-feature golden can no
longer be produced, and it is the whole evidence for FR-005 / P1.

- [X] T001 Copy `tests/golden/prompts/narrate_system_matrix.json` to `specs/028-gap-marking-contract/golden_pre_feature.json` — 265 entries, taken before any template edit *(done during planning)*
- [X] T002 [P] Extract the 31 accepted markers from `experiments/20260907-phandalin-gm-gaps-confirm/*/response.md` into `specs/028-gap-marking-contract/accepted_gaps.json`, with per-arm counts *(done during planning)*
- [ ] T003 [P] Correct `experiments/20260907-phandalin-gm-gaps-confirm/FINDINGS.md`: its "What this does not establish" section still says the marked passages "have not been read against their sources, and only the GM can do that". The GM read all 31 and accepted them on 2026-09-08. Record the ruling and point at `accepted_gaps.json`; do not delete the section's other caveats, which still stand

**Checkpoint**: both fixtures on disk, `accepted_gaps.json` totalling 31 (6/12/4/9).

---

## Phase 2: Foundational — the fragments and the machinery

**⚠️ Blocking.** Every user story reads from this. No story starts until T009's checkpoint is
green.

- [ ] T004 [P] Create `config/agents/session_doc/narrate/gm_attribution_absorb.md` holding today's `writing_brief.md` ¶6 sentence **character-for-character**: `GM descriptions become experienced facts; NPC speech voiced by the GM remains NPC speech.` Byte-exactness is what makes FR-005 provable — verify with a diff against the source line, not by eye
- [ ] T005 [P] Create `config/agents/session_doc/narrate/gm_attribution_prose_absorb.md` holding today's `prose_mode.md` ¶2 sentence character-for-character: `GM descriptions become experienced facts; speech the GM supplies for an identified NPC or PC stays with that character.` Note it differs from T004's in its second clause — research D3
- [ ] T006 [P] Create `config/agents/session_doc/narrate/gm_attribution_gap.md` holding the contract, adapted from `experiments/20260907-phandalin-fable-gm-gaps/prompt.diff`. It must carry all five of its parts: no transfer of a GM passage to a character (speech, perception, memory or inference); no unmarked absorption into the narrator's voice; adjudication-only turns still dropped as table operation; the `[GM NARRATION — TO BE WRITTEN: …]` marker on its own line with the scene carried on around it; and that the markers are required output, not commentary
- [ ] T007 [P] Create `config/agents/session_doc/narrate/gm_attribution_prose_gap.md` holding **only** the compatible second clause: `Speech the GM supplies for an identified NPC or PC stays with that character.` The first clause is the one that conflicts; the second is a rule the contract does not replace
- [ ] T008 Replace the ¶6 sentence in `config/agents/session_doc/narrate/writing_brief.md` with `{gm_attribution}`, in place, mid-paragraph — and the ¶2 sentence in `config/agents/session_doc/narrate/prose_mode.md` with `{gm_attribution_prose}`. Position is load-bearing: hoisting either to its own paragraph breaks byte-identity in gap-off mode
- [ ] T009 In `session_doc/narrate.py`, declare the new placeholders on the deferred loaders — `NARRATION_WRITING_BRIEF` gains `"gm_attribution"`, `PROSE_MODE_INSTRUCTION` gains `"gm_attribution_prose"` — and load the four variants. `_load_template` checks both directions, so a declared-but-absent placeholder fails at import

**Checkpoint**: `python -c "import session_doc.narrate"` succeeds; the four fragments exist;
nothing yet consumes them.

---

## Phase 3: User Story 1 — a GM's description is marked, not reassigned (P1) 🎯 MVP

**Goal**: with the mode on, the per-scene prompt carries the contract and no instruction to
absorb GM description.

**Independent test**: build the prompt with gap marking on and confirm the contract is present
and the absorbing sentence is gone; build it off and confirm byte-identity.

### Tests for User Story 1

- [ ] T010 [P] [US1] Create `tests/test_prompt_golden_pre_feature.py`: for every gap-off combination, `build_narrate_system` output equals its entry in `specs/028-gap-marking-contract/golden_pre_feature.json`, byte for byte. Assert equality against the frozen file — a failure here is never a reason to regenerate it (research D4)
- [ ] T011 [P] [US1] Create `tests/test_gap_marking_prompt.py` with the P2/P3/P4 assertions for the per-scene path: gap on → no "GM descriptions become experienced facts"; gap on → the marker requested on its own line as required output; gap on → the adjudication-is-table-operation rule survives

### Implementation for User Story 1

- [ ] T012 [US1] In `session_doc/narrate.py`, add `gap_marking: bool = False` to `build_narrate_system` and fill the brief before interpolating it: pass `writing_brief=_fill(NARRATION_WRITING_BRIEF, gm_attribution=<gap or absorb variant>)`. `_fill` emits values verbatim without re-scanning, so the nested placeholder must be resolved before the outer fill, not by it
- [ ] T013 [US1] In the same function, apply the same treatment to `PROSE_MODE_INSTRUCTION` at the `if prose_mode:` branch, using `gm_attribution_prose`. This is the copy easiest to forget and the one US2 scenario 2 exists to catch
- [ ] T014 [US1] Add `gap_marking` to `tests/test_session_doc_prompts.py::_build_matrix` as a ninth dimension with a `_gm{0,1}` label segment, taking the matrix from 256 to 512, and regenerate `tests/golden/prompts/narrate_system_matrix.json` via `UPDATE_PROMPT_GOLDEN=1`. The regenerated golden guards future drift; T010's frozen copy is what proves this change did not move the old half

**Checkpoint**: T010 and T011 green. The prompt is correct in the per-scene path with no CLI
surface yet.

---

## Phase 4: User Story 2 — the prompt states one rule, not two (P1)

**Goal**: whichever rule is in force is the only one present, in every combination.

**Independent test**: assert the GM-attribution rule appears exactly once in the assembled
prompt, in all four combinations of gap marking × prose mode.

### Tests for User Story 2

- [ ] T015 [P] [US2] In `tests/test_gap_marking_prompt.py`, add the P6 assertion: the GM-attribution rule appears exactly **once** in the assembled prompt — not once per fragment, not once per mode with the other still present
- [ ] T016 [P] [US2] In the same file, add the gap-on × prose-on combination explicitly: the absorbing first clause is absent and `gm_attribution_prose_gap`'s second clause is present. Assert on both, since a variant that dropped the whole sentence would pass a presence-only check
- [ ] T017 [P] [US2] In `tests/test_prompt_golden_pre_feature.py`, assert byte-identity for the gap-off × prose-on combination specifically. Prose mode is the path with the second copy, and it is off by default, so it is the one a spot check would miss

### Implementation for User Story 2

- [ ] T018 [US2] Verify — and fix if needed — that T012/T013 leave no third copy of the rule anywhere in the assembled prompt. Grep the fragment set for the phrase rather than trusting the two known sites; `scene_anchored.md` and `bundle_scene.md` restated rules the brief owned once before (#435)

**Checkpoint**: T010, T011, T015–T017 green. All four gap × prose combinations correct.

---

## Phase 5: User Story 3 — the bundle path marks gaps too (P2)

**Goal**: the all-scenes render carries the contract exactly as the per-scene one does.

**Independent test**: build the bundled prompt with gap marking on and assert P2–P4 hold there
too.

**⚠️ This is the story whose behavioural evidence does not exist.** Per the Q2 ruling the bundle
path is admitted on per-scene evidence; research D7 and SC-009 record that gap, and T029 is what
closes it.

### Tests for User Story 3

- [ ] T019 [P] [US3] In `tests/test_gap_marking_prompt.py`, add P5: every P2/P3/P4 assertion holds for `build_bundled_narrate_prompts` with gap marking on, prose mode on and off
- [ ] T020 [P] [US3] In `tests/test_prompt_golden_pre_feature.py`, assert the gap-off bundled prompt is byte-identical to its pre-feature form. `bundle_base.md` interpolates `{writing_brief}` too, so it moves if T008 is wrong

### Implementation for User Story 3

- [ ] T021 [US3] In `session_doc/narrate.py`, add `gap_marking: bool = False` to `build_bundled_narrate_prompts` and fill `{writing_brief}` and `{prose_mode_block}` through the same variant selection. One contract text, two render paths — do not add a bundle-specific variant

**Checkpoint**: both render paths carry the contract; the library half is complete.

---

## Phase 6: The surfaces — CLI, config, route, UI

Not a user story of its own: it is how US1–US3 become reachable. Principle XI requires the UI
toggle in this feature, not a follow-up.

- [ ] T022 In `session_doc/sd_narrate.py`, add `--gap-marking` (store_true, default off) and thread it into both `build_narrate_system` and `build_bundled_narrate_prompts` call sites. Mirror `--prose-mode` exactly — one spelling, one meaning, one default (Principle XII)
- [ ] T023 In `session_doc/sd_narrate.py`, refuse when gap marking is on and the contract fragment cannot be read, naming the path and exiting non-zero. Deliberately the opposite of the genre file's warn-and-continue: a missing genre costs register, a missing contract costs attribution, and rendering without it is the failure this feature removes
- [ ] T024 [P] Add `gap_marking: bool = False` to `NarrateKnobs` in `server/session_editor_config_shared.py`. `extra="forbid"` makes this additive: a config written before this feature loads unchanged and takes the default, so no migration (Principle XIII)
- [ ] T025 In `server/routers/scene_editor.py`, forward the flag in `_build_narrate_cmd` beside the existing `if cfg.narrate.prose_mode: cmd += ["--prose-mode"]` at line ~1414, and in the bundle command builder. Take the value from the resolved config — never a literal at the route edge
- [ ] T026 [P] Add the toggle to the Stage-④ knobs in the UI, following `prose_mode` through all four files that carry it: `frontend/src/components/scene-editor/KnobDrawer.vue`, `frontend/src/components/scene-editor/ExtractionEditor.vue`, `frontend/src/views/session/SessionDocEditor.vue`, `frontend/src/views/session/ReviewAssemble.vue`
- [ ] T027 [P] Add a CLI test to `tests/` asserting `--gap-marking` reaches the prompt and that its absence leaves the prompt in gap-off form, plus a route test asserting `_build_narrate_cmd` forwards the flag when the config sets it and omits it otherwise

**Checkpoint**: a GM can turn the mode on from the terminal and from the editor, and a missing
contract refuses.

---

## Phase 7: User Story 4 — the render says which contract produced it (P3)

**Goal**: a finished scene states, from disk, whether gap marking was on and against which
contract text — for a terminal render as much as a UI one.

**Independent test**: render from the CLI and confirm the sidecar exists and carries the digest.

**⚠️ Research D8 names this the riskiest and most separable part.** It is a split, not a move:
`_narrate_knobs_snapshot` builds from the server's resolved config, and `status` /
`exchange_count` / `written_count` / `missing_count` / `rejected_count` are run *outcome*
computed after the subprocess exits.

- [ ] T028 [US4] In `session_doc/sd_narrate.py`, write `session_doc_scene_NN_<slug>.knobs.json` beside the narration with the render-identity fields: `model`, `backend`, `prose_mode`, `gap_marking`, `narration_genre_file` + digest, `gap_contract` + `gap_contract_sha256`, token budget. Identity by digest, never a copy of the text (#276)
- [ ] T029 [US4] In `server/routers/scene_editor.py`, stop calling `_write_knobs_sidecar` with a config snapshot at both call sites (~2277, ~2356) and **merge** the outcome fields into the file the CLI wrote. Sequential by construction — merge only after the subprocess exits. Two writers of one file is admitted only on that basis
- [ ] T030 [P] [US4] Verify `_read_knobs_sidecar` (`server/routers/scene_editor.py:~2794`) and the Review screen's `applied_knobs` still render correctly against both a new sidecar and one written before this feature, which lacks the new keys
- [ ] T031 [P] [US4] Add a test asserting a CLI render writes the sidecar with `gap_marking` and `gap_contract_sha256`, and that a second render with an edited contract file produces a different digest — the mid-session-edit case #418 promises is visible

**Checkpoint**: SC-007 holds for both launch paths.

---

## Phase 8: Polish, guards and the token spend

- [ ] T032 [P] Add the producer binding for the gap marker, modelled on `tests/test_apparatus_marker_pairing.py`: every gap-on prompt in the matrix requests `[GM NARRATION — TO BE WRITTEN:`. Do **not** add it to `APPARATUS_MARKERS` — that registry drives `strip_audit_comments`, which would delete the marker at assembly (research D5)
- [ ] T033 [P] Add a test asserting a gap marker **survives** `strip_audit_comments` and reaches the assembled document, and that it is **not** masked from `find_unknown_names` (research D6 — a proper noun appearing only inside a marker is exactly the invention that scan exists to catch)
- [ ] T034 [P] Document the mode in `docs/cli/session_doc_pipeline.md`: the flag, the refusal on a missing contract, what a marker is, and that answering one belongs to #455
- [ ] T035 [P] Add the `CLAUDE.md` note stating that the GM-attribution rule has exactly one home and is selected by mode, and that the gap marker is content rather than apparatus — the two facts a future session would otherwise re-derive or get wrong
- [ ] T036 Run the full suite (`python -m pytest tests/`) and confirm no regression beyond the known environmental `test_configure_mcp.py::test_git_root_returns_path_itself_when_not_in_a_repo`

### Re-confirmation — the only tasks that spend tokens

- [ ] T037 Re-render the four confirmation scenes per-scene into `experiments/<date>-454-reconfirm/per-scene/` with gap marking on, `claude-fable-5-1` at effort `medium`, and compare against `accepted_gaps.json`. Report individually: a gap the GM accepted that vanished, and a gap appearing where the GM ruled the scope wrong. Counts and boundaries are expected to shift and settle nothing on their own (FR-013, SC-003)
- [ ] T038 Check SC-004 and SC-005 on T037's renders under `experiments/<date>-454-reconfirm/per-scene/`: dialogue lines still outnumber narration lines two to four times over, and no GM description arrives as a player character's speech, perception, memory or inference
- [ ] T039 Re-render the same four scenes as a **bundle** with gap marking on into `experiments/<date>-454-reconfirm/bundle/` and compare marker counts against T037's. This is SC-009, and it is the evidence the Q2 ruling does not have. A bundle marking materially fewer gaps than the per-scene run is a finding to report, not a rounding error — and it reopens Q2, whose fallback (refusing the combination) stays available
- [ ] T040 Record the re-confirmation result in `specs/028-gap-marking-contract/` as this feature's own evidence file, stating what transferred, what shifted and what did not — and update the spec's status

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 (Setup)** — T001 before **everything**. T002, T003 parallel with it.
- **Phase 2 (Foundational)** — blocks all user stories. T004–T007 parallel; T008 then T009.
- **Phase 3 (US1)** — needs Phase 2. The MVP.
- **Phase 4 (US2)** — needs Phase 3 (T013 is where its subject is created).
- **Phase 5 (US3)** — needs Phase 2; independent of Phases 3–4 in principle, but T021 mirrors T012, so doing it after is cheaper.
- **Phase 6 (Surfaces)** — needs Phase 3 at minimum; T025/T026 need T024.
- **Phase 7 (US4)** — needs Phase 6 (the flag must exist before it can be recorded).
- **Phase 8** — T032/T033 need Phase 3; T037–T040 need Phases 3, 5 and 6.

### User story dependencies

```
Phase 2 ──┬── US1 (P1) ──── US2 (P1) ──┐
          │                            ├── Surfaces ── US4 (P3) ── re-confirmation
          └── US3 (P2) ────────────────┘
```

US2 is not independent of US1 in practice: T013 creates the second copy that T015–T017 assert
on. They are separate stories because they fail differently — US1 broken means no contract, US2
broken means two contradicting rules.

### Parallel opportunities

- T002, T003 alongside T001
- T004, T005, T006, T007 — four fragments, four files
- T010, T011 — two new test files
- T015, T016, T017 — same file, so sequential in practice despite [P] on distinct concerns
- T019, T020 — different files
- T024, T026 — config and UI, no overlap
- T032, T033, T034, T035 — four files, no overlap

---

## Implementation Strategy

### MVP

**Phase 1 + Phase 2 + Phase 3 (US1).** That is the contract reaching the per-scene prompt with
FR-005 proven. It is not yet reachable from the CLI, so it is an MVP in the "demonstrable and
correct" sense rather than the "usable" one — Phase 6 is what makes it usable, and it is small.

### Incremental delivery

1. **Phases 1–3** — the contract is in the prompt, and gap-off is provably unchanged
2. **Phase 4** — one rule, in all four combinations
3. **Phase 5** — the bundle path
4. **Phase 6** — reachable from terminal and editor
5. **Phase 7** — the record; separable, and the one to drop first if D8 proves invasive (that is a ruling to go back and ask for, not to take silently)
6. **Phase 8** — guards, docs, and the token spend

### The stop-and-report point

T039. Everything before it is deterministic and provable. T039 is the only task whose result
could send the design back, and the thing it would send back is a ruling the GM already made
with its cost attached. Report the finding; do not re-decide Q2 alone.
