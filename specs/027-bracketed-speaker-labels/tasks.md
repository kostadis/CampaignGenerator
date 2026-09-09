---

description: "Task list for 027-bracketed-speaker-labels"
---

# Tasks: A bracketed speaker label is a speaker, not a scene tag

**Input**: Design documents from `/specs/027-bracketed-speaker-labels/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/label-grammar.md](./contracts/label-grammar.md),
[quickstart.md](./quickstart.md)

**Tests**: **Included.** Not the template's default — the spec defines its verification in
`Acceptance Scenarios` and `Success Criteria`, `quickstart.md` §2 enumerates the grammar cases
by hand, and `plan.md` names the two existing test files that must change. The repo's own
practice is a build-breaking guard for any rule that must not regress. Writing these after the
fact would leave the feature's central risk — resolution silently becoming containment —
uncovered.

**Organization**: By user story, with one honest deviation recorded in Phase 2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: `[US1]`–`[US4]`, mapping to the user stories in `spec.md`

## Path Conventions

Single project, existing layout. Library code in `session_doc/` and `campaignlib/`, tests in
`tests/`, evidence (read-only) in `experiments/20260907-phandalin-gm-gaps-confirm/inputs/`.

---

## Phase 1: Setup

**Purpose**: Capture the baseline the whole feature is measured against, before touching code.

- [X] T001 Capture the current `scene_speaker_counts` output for all four corpus files to `specs/027-bracketed-speaker-labels/baseline.json`, using the snippet in `quickstart.md` §1 — this is the SC-004 regression baseline and must be produced before any source edit
- [X] T002 [P] Record the current full-suite result (`python -m pytest tests/ -q`) in `specs/027-bracketed-speaker-labels/baseline.json` alongside the counts, so a later green run is compared against a number rather than a memory
- [X] T003 [P] Capture the current eligibility report text for `vukradin_source.md` (both unresolved-label buckets) into `specs/027-bracketed-speaker-labels/baseline.json` — the SC-008 "loud bucket did not grow" comparison needs a before

**Checkpoint**: Baseline recorded. Every success criterion now has a concrete before-value.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Move the identity rule out of the reader **without changing any behaviour**. After
this phase the suite is green and every output is byte-identical to the baseline.

**⚠️ CRITICAL**: No user story can begin until this phase is complete.

**Why this is foundational and not part of US1.** `session_doc/io.py` currently holds a
partial copy of the identity rule (`label.startswith("[")` and `label == GM_LABEL`) in a module
that cannot see the roster. Removing it and admitting bracketed labels in one step would make
bare `**GM**` an unresolved label on bare-convention sessions and break SC-004 immediately.
Splitting the move from the behaviour change keeps every intermediate commit green and makes
the diff that *does* change behaviour small enough to review.

- [X] T004 Replace `scene_speakers` / `scene_speaker_counts` in `session_doc/io.py` with a single reader returning every line-start bold label verbatim, in order, with no filtering — preserving the module docstring's "one parse" rule (FR-009) and updating it to say the reader no longer decides who a label names
- [X] T005 Add label tokenisation to `session_doc/plan_eligibility.py` per `contracts/label-grammar.md`: a bare label yields itself unmodified; a bracketed label yields one part per segment after stripping `[` `]` and splitting on `/` and `,`; empty parts are discarded
- [X] T006 Add part resolution to `session_doc/plan_eligibility.py`: fold with `campaignlib.players_config.norm_name` and compare for **equality** against the roster and `GM_LABEL` — never containment, never prefix (contract G1, G2)
- [X] T007 Wire the reader, tokeniser and resolver into `compute_eligibility` in `session_doc/plan_eligibility.py`, recognising the **bare** game-master label so bare-convention sessions are unaffected, and leaving every bracketed label unresolved for now
- [X] T008 Update `tests/test_plan_eligibility.py` and `tests/test_plan_review_regressions.py` for the moved boundary — `scene_speakers`-level assertions become eligibility-level assertions, and the one-parse invariant (FR-009) is re-asserted against the new reader
- [X] T009 Verify no behaviour change: `scene_speaker_counts` equivalents for all four corpus files match `baseline.json` exactly, and `python -m pytest tests/` matches the baseline count

**Checkpoint**: Identity logic lives in one module. Nothing behaves differently yet.

---

## Phase 3: User Story 1 — Plan a session recorded in the bracketed convention (Priority: P1) 🎯 MVP

**Goal**: A session whose speaker labels are all `**[Name]**` yields a real narrator pool
instead of refusing.

**Independent Test**: Compute eligibility for `valphine_source.md` and `vukradin_source.md`;
each scene lists the characters whose labelled turns appear in it, and the pool is non-empty.

### Tests for User Story 1

- [X] T010 [P] [US1] Create `tests/test_speaker_label_grammar.py` with the single-name rows of the worked-examples table in `data-model.md`: `[Vukradin]` → present, `[ GM ]` whitespace-insensitive, `[]` contributes nothing and is not reported as a name, and an indented `  **Brewbarry**` is not a label
- [X] T011 [P] [US1] Add the containment guard to `tests/test_speaker_label_grammar.py`: `[scene tag — Vukradin demands a meeting]` makes **nobody** present — the feature's worst failure mode and one keystroke from the correct rule (research Decision 2)
- [X] T012 [P] [US1] Create `tests/test_speaker_label_corpus.py` asserting all four corpus files yield a non-empty narrator pool (SC-001) and that the two bare-convention files still match `baseline.json` (SC-004)

### Implementation for User Story 1

- [X] T013 [US1] Admit resolved bracketed labels as presence in `session_doc/plan_eligibility.py`: a label with at least one part folding to a roster character makes each such character present, contributing exactly one turn of evidence per distinct character (FR-001, FR-005 partial, contract E1)
- [X] T014 [US1] Confirm presence remains a yes/no fact in `session_doc/plan_eligibility.py` — one labelled turn is full eligibility, and turn counts stay evidence rather than a threshold (FR-008, contract E4)

**Checkpoint**: The two dead sessions plan. `Valphine` is still unresolved in them (short form
against roster `Valphine Sotorra`) — expected and documented, not a defect.

---

## Phase 4: User Story 2 — A game master's turn is recognised however it is written (Priority: P2)

**Goal**: Every GM label form is recognised as the game master, so none creates presence for a
player character and none is reported as an unknown name.

**Independent Test**: Run eligibility over a scene containing `**GM**`, `**[GM]**` and
`**[GM, as the banker]**`; no character gains presence from any of them and none appears in the
unresolved-label report.

### Tests for User Story 2

- [X] T015 [P] [US2] Add the game-master rows to `tests/test_speaker_label_grammar.py`: `GM`, `[GM]` and `[GM, as the banker]` all classify as game master and create no presence (SC-005, contract E2)
- [X] T016 [P] [US2] Add a test to `tests/test_speaker_label_grammar.py` that `**GM**` and `**[GM]**` are treated identically, so the two conventions cannot drift apart

### Implementation for User Story 2

- [X] T017 [US2] Classify a bracketed label whose parts resolve only to the game master as a game-master turn in `session_doc/plan_eligibility.py`, so it creates no presence and is not reported as unknown (FR-004)
- [X] T018 [US2] Confirm the qualified form resolves through comma tokenisation in `session_doc/plan_eligibility.py` — `[GM, as the banker]` yields parts `GM` and `as the banker`, the first resolving and the second inert, with no special-casing of the qualifier's wording (FR-003)

**Checkpoint**: The GM is recognised in all four observed forms, including the NPC-voicing one
the contract was never written for.

---

## Phase 5: User Story 3 — A jointly labelled turn credits the character named in it (Priority: P3)

**Goal**: A turn labelled with two or more parties makes every roster character it names
present.

**Independent Test**: Give a character exactly one turn in a scene, written jointly, and confirm
they are present in it.

**GM ruling applied**: presence for **every** roster character named — option A, ruled
2026-09-08 over the conservative alternative. The permissive reading: a turn possibly spoken by
only one of the named characters can make both eligible. See `spec.md` Assumptions.

### Tests for User Story 3

- [X] T019 [P] [US3] Add the joint-label rows to `tests/test_speaker_label_grammar.py`: `[GM / Brewbarry]` → Brewbarry present; `[Brewbarry / Soma]` → both present; `[GM / Brewbarry / Valphine]` → Brewbarry and Valphine present, GM part inert (SC-007, contract E1)
- [X] T020 [P] [US3] Add a test to `tests/test_speaker_label_grammar.py` that a label naming one character twice contributes one turn, not two
- [X] T021 [P] [US3] Extend `tests/test_speaker_label_corpus.py` to assert the three real multi-character joint turns in `valphine_source.md` credit each character named

### Implementation for User Story 3

- [X] T022 [US3] Apply the every-named-character rule in `session_doc/plan_eligibility.py` so a joint label credits each resolved roster character once, and a game-master part suppresses nothing (FR-005)

**Checkpoint**: The ten joint turns in the corpus count. Nothing else changed.

---

## Phase 6: User Story 4 — A beat marker is still not a speaker (Priority: P3)

**Goal**: Scene apparatus creates no presence, and reading bracketed labels does not dilute the
one report channel the GM has to read.

**Independent Test**: Run the eligibility report for `vukradin_source.md`; beat markers create
no presence, and `[scene tag — Soma's Arcana check]` and `[scene tag — Vukradin demands a
meeting]` do **not** appear in the "looks like a roster character" bucket.

**Recommended to ship with US1.** US1 is functional without this phase, but landing US1 alone
puts 22 beat markers into the unresolved-label report, two of them into the loud bucket as
false alarms. See research Decision 3.

### Tests for User Story 4

- [X] T023 [P] [US4] Add the apparatus rows to `tests/test_speaker_label_grammar.py`: `[Reroll With Advantage]`, `[The Lead Established]`, `[scene tag — The roll]` create no presence, and a scene containing a beat marker alongside a real bracketed speaker resolves the speaker and ignores the marker
- [X] T024 [P] [US4] Add a bucketing test to `tests/test_speaker_label_grammar.py`: a bracketed label from which nothing resolved goes to the counted-not-listed bucket, while the bare `Vukradin (David)` form still goes to the listed bucket — the `#385` channel is preserved exactly (SC-008)
- [X] T025 [P] [US4] Extend `tests/test_speaker_label_corpus.py` to assert the loud bucket for `vukradin_source.md` has not grown against `baseline.json`

### Implementation for User Story 4

- [X] T026 [US4] Add the `apparatus` classification in `session_doc/plan_eligibility.py` for a bracketed label with no resolving part (data-model `LabelClass`)
- [X] T027 [US4] Route apparatus labels to the counted-not-listed bucket in `_stranger_buckets` in `session_doc/plan_eligibility.py`, leaving the bare-label containment heuristic untouched (research Decision 3)
- [X] T028 [US4] Confirm every unresolved label still reaches one bucket or the other in `report_eligibility` in `session_doc/plan_eligibility.py` — nothing is dropped silently (FR-006, SC-003, contract E3)

**Checkpoint**: All four label conventions handled. The report is no noisier than before.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T029 [P] Update the "A narrator must have been in the scene" section of `CLAUDE.md` — line 189's *"Presence is read from `moments`, anchored on `^**Name**`"* no longer describes the rule, and the two-label-space warning (Filter A resolves people, Filter B resolves characters) must survive the rewrite
- [X] T030 [P] Update the Filter B description at `docs/cli/session_doc_pipeline.md:605` with the label grammar and a pointer to `contracts/label-grammar.md`
- [X] T031 [P] ~~Note the resolved bracketed-label conventions in `docs/design/SessionDocRefactor.md`~~ — **no change needed.** The file was listed on a grep that matched "scene-anchored" at line 110, not a description of the label parse. It makes no claim this feature invalidates.
- [X] T032 Run the full `quickstart.md` validation end to end and record the result against every success criterion SC-001 to SC-008
- [X] T033 Run `python -m pytest tests/` and confirm the count matches or exceeds the baseline in `baseline.json` with no failures
- [X] T034 Comment the containment guard in `session_doc/plan_eligibility.py` with the concrete example that motivates it (`[scene tag — Vukradin demands a meeting]`), following the repo's practice of recording the defect a rule prevents
- [X] T036 Repair the stale cross-reference at `campaignlib/players_config.py:508`, which pointed Filter B at `session_doc.io.scene_speakers` — a symbol this feature removes. Unplanned; found by grep during T031.
- [X] T035 Close the loop on #453 and note in #456 that GM turns are now classified rather than discarded, which is the precondition the block editor's source panel depends on

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)** — no dependencies. Must complete before any source edit, or the SC-004 baseline is lost.
- **Foundational (Phase 2)** — depends on Phase 1. **Blocks every user story.**
- **US1 (Phase 3)** — depends on Phase 2.
- **US2 (Phase 4)** — depends on Phase 2. Independent of US1, but more useful after it.
- **US3 (Phase 5)** — depends on Phase 2 and on US1's presence path (T013).
- **US4 (Phase 6)** — depends on Phase 2. **Strongly recommended with US1**, which is what puts beat markers into the report.
- **Polish (Phase 7)** — depends on all shipped stories.

### Why the stories are less independent than usual

They are four facets of one classification function, not four features. Once the reader stops
filtering, every label form arrives at once. The phases are ordered so each intermediate state
is *safe* rather than complete: an unhandled form resolves to nobody and is reported, which
never fabricates presence. That is the property to preserve when reordering — never the phase
boundaries themselves.

### Within each story

- Tests before implementation. The grammar tests are cheap and the failure they guard is
  expensive.
- Classification before reporting.
- Corpus assertions last, once the unit-level grammar holds.

### Parallel Opportunities

- T002, T003 in Phase 1.
- Every test task within a story (T010–T012, T015–T016, T019–T021, T023–T025) — separate files
  or separate test functions.
- US2 and US4 can proceed in parallel with each other once Phase 2 is done.
- T029, T030, T031 in Phase 7 — three different documents.

---

## Parallel Example: User Story 1

```bash
# Tests first, together:
Task: "Single-name grammar rows in tests/test_speaker_label_grammar.py"
Task: "Containment guard — [scene tag — Vukradin demands a meeting] in tests/test_speaker_label_grammar.py"
Task: "Corpus pool + bare-convention regression in tests/test_speaker_label_corpus.py"

# Then implementation, sequentially — both touch plan_eligibility.py:
Task: "Admit resolved bracketed labels as presence"
Task: "Confirm presence stays yes/no"
```

---

## Implementation Strategy

### MVP (Phases 1–3, plus 6)

1. Phase 1 — capture the baseline.
2. Phase 2 — move the identity rule, change nothing.
3. Phase 3 — US1: the two dead sessions plan.
4. Phase 6 — US4: keep the report readable.
5. **STOP and VALIDATE**: `quickstart.md` §1, §3, §4. SC-001, SC-002, SC-003, SC-004, SC-008.

That is the whole defect fixed. US2 and US3 are correctness refinements on forms that are
already safe — they resolve to nobody and are reported, rather than resolving to the wrong
person.

### Incremental Delivery

1. Setup + Foundational → green, byte-identical, identity rule in one place.
2. + US1 → the defect is fixed. Demo: two sessions that could not be planned now plan.
3. + US4 → the report is no noisier than before.
4. + US2 → GM forms recognised instead of reported as unknown.
5. + US3 → the ten joint turns count.
6. Polish → docs match the code.

### Single-Developer Order

T001 → T009, then T010 → T014, then T023 → T028, then T015 → T018, then T019 → T022, then
Phase 7. Commit at every checkpoint; each one is green.

---

## Implementation record — 2026-09-08

Two deviations from this plan, both deliberate.

**Phase 2's staged no-op was collapsed into the main change.** The phase exists so a
multi-session effort keeps every intermediate commit green; implemented in one pass by one
person, the ceremony of adding a suppression flag in T007 and removing it in T013 would have
bought nothing. The guarantee Phase 2 protects was verified directly instead: the two
bare-convention sessions produce presence and counts byte-identical to `baseline.json`, which
is what SC-004 actually asks for.

**SC-004 was narrowed, and the spec records why.** It originally also demanded "no new
unrecognised labels", which contradicts FR-006 and SC-003: a bare-convention file can still
contain a bracketed beat marker, and those used to be discarded in silence. Surfacing them is
the point of FR-006, so the counted-not-listed total grows by 1 and 3 on the two bare files.
Presence, counts, and the loud report bucket are unchanged.

**Result against every success criterion**, measured over the frozen corpus:

| | Criterion | Result |
|---|---|---|
| SC-001 | All four sessions yield a narrator pool | 4, 4, 3, 3 — was 4, 4, **0**, **0** |
| SC-002 | Bracketed sessions count their turns | `vukradin` Vukradin 39 / Soma 21 / Brewbarry 13; `valphine` Brewbarry 18 / Vukradin 3 / Soma 1 |
| SC-003 | Nothing dropped silently | loud + quiet == total unresolved, all four files |
| SC-004 | Bare sessions unchanged | presence and counts identical to baseline |
| SC-005 | No GM turn credits a character | `GM` absent from every count; 40 `[GM]` and 41 `**GM**` turns inert |
| SC-006 | GM reaches a narrator choice unaided | no hand-editing of extractions required |
| SC-007 | Multi-character joints credit each | Brewbarry's 18 = 7 solo + 11 joint |
| SC-008 | Loud bucket did not grow | 0 → 0 on all four |

Suite: **5116 passed, 174 skipped**, up 46 from the 5071 baseline.
`tests/test_configure_mcp.py::test_git_root_returns_path_itself_when_not_in_a_repo` fails in
this environment and is unrelated — a stray empty `/tmp/.git` makes `git_root` walk up and
find it. Verified by A/B in one environment: it fails identically with and without this
feature's diff.

## Notes

- **The one rule that must not bend**: resolution is folded equality, never containment.
  `[scene tag — Vukradin demands a meeting]` is the test that proves it, and a false attribution
  is the most expensive failure this system produces.
- Every intermediate state must fail safe: an unhandled label form resolves to nobody, creates
  no presence, and is reported.
- `Valphine` staying unresolved in the bracketed sessions is **expected** — the short form
  against roster `Valphine Sotorra`. Out of scope by ruling, documented in `spec.md`
  Assumptions. Do not "fix" it.
- No model call, no token spend, no new flag, no state change on disk, no migration.
- Filter A (people, from the tape) and Filter B (characters, from the extraction) stay separate.
  This feature touches only Filter B.
