# Tasks: The block document model, and a reviewer that works on a phone

**Input**: Design documents from `/specs/029-block-document-model/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/block-model.md](./contracts/block-model.md),
[quickstart.md](./quickstart.md)

**Tests**: included. This layer's whole claim is that it is deterministic and calls no model, and
both are properties that only exist if something checks them. The round-trip property (P1) and
the no-model guard (X1) are build-breakers, not niceties.

## Format: `[ID] [P?] [Story] Description`

- **[P]** — parallelizable: different files, no dependency on an incomplete task
- **[US1]–[US6]** — the user story from [spec.md](./spec.md)

## Path Conventions

Single project, existing layout. New modules under `session_doc/`; the reviewer is a static asset
at `session_doc/review/reviewer.html`; tests in `tests/`. The read-only corpus is
`experiments/20260907-phandalin-gm-gaps-confirm/`.

## Story order deviates from strict priority, deliberately

Priority is US1 (P1), US2 (P1), US4 (P1), US3 (P2), US5 (P2), US6 (P2). The phases below run
**US1 → US2 → US3 → US4 → US5 → US6**, moving US3 ahead of US4.

US3 is the only P2 story that lives in `reviewer.html`, the same file as US1 and US2. Ordering by
priority alone would mean opening that file, closing it, building the record layer, and opening
it again. Each story stays independently testable; only the sequence changes.

---

## Phase 1: Setup

- [X] T001 Confirm the corpus this feature is validated against is present and unchanged: `experiments/20260907-phandalin-gm-gaps-confirm/{brewbarry,soma,valphine,vukradin}/response.md` carrying 6, 12, 4 and 9 markers — 31 in total
- [X] T002 [P] Create the package skeleton: `session_doc/blocks.py`, `session_doc/authored.py`, `session_doc/compose.py` and `session_doc/review/` with no logic, so later tasks land in known files

**Checkpoint**: the corpus is verified and the files exist.

---

## Phase 2: Foundational — the parser everything reads through

**⚠️ Blocking.** Every story depends on this. Nothing starts until T007's checkpoint is green.

**⚠️ T004 is the load-bearing test in the feature.** A parser that loses a blank line makes every
composed document differ from its narration *everywhere*, and the diff reads as compose
misbehaving rather than as a parse bug.

- [X] T003 Define the marker constant and the block model in `session_doc/blocks.py`: one `GAP_MARKER` string, a frozen `Block` dataclass with `id`, `kind`, `anchor`, `text`, and the `{kind}-{ordinal}` id rule from [data-model.md](./data-model.md)
- [X] T004 Implement `parse_blocks(text)` and `join_blocks(blocks)` in `session_doc/blocks.py`. A gap block is a paragraph consisting solely of the marker; a prose block is the **run** of paragraphs between two gaps (research D1). `join_blocks(parse_blocks(t)) == t` for any input
- [X] T005 [P] Create `tests/test_block_model.py` with contract P: round-trip on all four corpus scenes (**not** a fixture), the expected block and gap counts (13/6, 25/12, 9/4, 18/9), stable ids across two parses (P3), and a marker-free narration yielding one prose block (P4)
- [X] T006 [P] Create `tests/test_gap_marker_pairing.py` (contract X2): the `GAP_MARKER` constant appears in `config/agents/session_doc/narrate/gm_attribution_gap.md`. `26ec5b0` deleted a prompt and left its stripper, its tests and three out-of-repo skills standing with nothing failing — this layer has **two** consumers, so the exposure is worse
- [X] T007 [P] Create `tests/test_block_model_no_llm.py` (contract X1): an AST walk over `session_doc/blocks.py`, `authored.py`, `compose.py` for an imported or called API client, after `tests/test_provenance_no_llm.py`. A grep would be fooled by a docstring

**Checkpoint**: T005 green on all four scenes. The parser is trustworthy; nothing consumes it yet.

---

## Phase 3: User Story 1 — Rule a scene's gaps from a phone, with no network (P1) 🎯 MVP

**Goal**: a GM opens a page already on their phone, pastes a scene, and rules every gap offline.

**Independent test**: export one scene, open the reviewer with networking disabled, paste, rule
every gap. Delivers the whole review step with no other part of this feature built.

### Tests for User Story 1

- [ ] T008 [P] [US1] Create `tests/test_review_export.py`: the export carries `version`, `narration`, `generated_sha256`, the scene stat line, blocks with the **same ids the record uses** (FR-018), and the source GM turns; one scene stays in the 14–26 KB band measured in research D9
- [ ] T009 [P] [US1] Create `tests/test_reviewer_selfcontained.py` (contract W1): `session_doc/review/reviewer.html` contains no external `src`/`href`, no `fetch`, no remote import. This is what makes "works offline on a phone" a property rather than a hope

### Implementation for User Story 1

- [ ] T010 [US1] Define the export schema in `session_doc/review/schema.py`: a strict Pydantic model with `version: int = 1` and a validator refusing an unknown version, mirroring `campaignlib/transcript_corrections.py`'s `_known_version`
- [ ] T011 [US1] Implement the source-GM-turn reader in `session_doc/review/export.py` — line, label, context note and quote from the scene extraction, which is what the reviewer's foot table renders (FR-014)
- [ ] T012 [US1] Implement `sd_review export` in `session_doc/sd_review.py`: one scene per file by default (FR-013), `--all-scenes` to opt into a whole session, `--out` for the path. 82 KB is not what gets pasted on a phone
- [ ] T013 [US1] Register `sd_review` in `pyproject.toml` `[project.scripts]` and reinstall editable, or the web UI's `console_script()` resolution and the CLI both fail on a fresh venv
- [ ] T014 [US1] Build `session_doc/review/reviewer.html` — one self-contained file, no build step. Paste box; on load, validate `version` and report a mismatch rather than rendering (W3); report a truncated or malformed paste rather than rendering half a scene (W4)
- [ ] T015 [US1] Render the scene in `reviewer.html`, reproducing the reviewed page's UX: sticky bar with the scene stat line, prose and gaps interleaved in one reading column, each gap in a well with its text and four ruling controls, and the full source GM turns in a `<details>` at the foot
- [ ] T016 [US1] Implement the **two** progress figures in `reviewer.html` (W5, SC-002a): *ruled* and *written*, shown separately. A single number would understate a finished triage or overstate an unfinished chapter — this is the whole of the GM's triage-then-write workflow
- [ ] T017 [US1] Implement persistence in `reviewer.html`, and the honest warning when it is unavailable (FR-016). See the open risk in research: `localStorage` under `file://` is inconsistent across mobile browsers, so the warning stays until verified on the GM's own device

**Checkpoint**: T008 and T009 green; a scene can be exported and ruled offline on a phone.

---

## Phase 4: User Story 2 — Take a gap to another model, and bring the prose back (P1)

**Goal**: copy from the reviewer, draft in any chat, paste the prose back into the gap.

**Independent test**: rule a gap, copy, and confirm the clipboard holds enough for a model with no
other context to draft that passage.

- [ ] T018 [P] [US2] Add a copy-as-prompt test to `tests/test_review_export.py`: the payload names the scene, includes the prose so far, and for each outstanding gap its text and its source GM turns
- [ ] T019 [US2] Implement *Copy as prompt* in `session_doc/review/reviewer.html` (W7): scene so far, gaps ruled the GM's to write, and the GM turns behind each. It must read as a request to draft, not as a data structure (US2 scenario 2)
- [ ] T020 [US2] Implement *Copy review* in `session_doc/review/reviewer.html`: the record's content, for the GM to place by hand. Two payloads because the workflow has two moments — drafting on the train, and landing the result
- [ ] T021 [US2] Confirm a passage pasted into a gap's field is recorded as `authored`, indistinguishable from one typed directly (US2 scenario 3) — the model's involvement is the GM's business, not the record's

**Checkpoint**: the mobile loop is complete end to end, with the result on the clipboard.

---

## Phase 5: User Story 3 — The model's prose is editable, and the edit is recorded as an edit (P2)

**Goal**: the GM changes a sentence the model wrote, and the record says model-written-and-edited.

**Independent test**: edit one prose block; confirm the record distinguishes it from an untouched
block and from a gap the GM authored.

- [ ] T022 [P] [US3] Add the `edited` disposition to the export and record schemas in `session_doc/review/schema.py` and `session_doc/authored.py`, applying to a `prose` block where the others apply to a `gap`
- [ ] T023 [US3] Make every prose block editable in `session_doc/review/reviewer.html` (W6) — #418's own framing, because the seam is where a sentence usually needs a tweak
- [ ] T024 [P] [US3] Test in `tests/test_block_model.py` that an untouched prose block produces **no** record entry (R4), and an edited one produces an `edited` entry carrying only the human's text
- [ ] T025 [P] [US3] Test that a prose block edited to empty is recorded as `edited` with empty text, not as untouched — deleting the model's paragraph is a legitimate editorial act and must be distinguishable

**Checkpoint**: the reviewer is complete. `reviewer.html` is not opened again after this phase.

---

## Phase 6: User Story 4 — The authored work is a file, and generated files are never hand-edited (P1)

**Goal**: rulings and prose live in one hand-authored file per scene; the composed document is
generated from it and the narration.

**Independent test**: author a record by hand, compose, and confirm the output carries the GM's
prose in the right places and is reproducible.

### Tests for User Story 4

- [ ] T026 [P] [US4] Add contract R to `tests/test_block_model.py`: `extra="forbid"` naming the offending key (R1), an unknown `version` refused (R2), two entries for one block id refused (R3), `mine` and `authored` stored distinctly rather than inferred (R5), a `critique` changing nothing (R6)
- [ ] T027 [P] [US4] Add contract C to `tests/test_block_model.py`: composing twice is byte-identical (C1), each disposition composes per the data-model table (C2), a digest mismatch refuses naming both (C3), the output carries a generated-file marker (C4), an empty record reproduces the narration (C5)

### Implementation for User Story 4

- [ ] T028 [US4] Implement the `.authored.yaml` schema in `session_doc/authored.py` — strict, `version: int = 1`, `narration`, `generated_sha256`, and `blocks[]` of `id` / `disposition` / optional `text` / optional `critique` / optional `note` / `anchor` / `recorded` / `recorded_by`
- [ ] T029 [US4] Enforce in `session_doc/authored.py` that `unruled` is the **absence** of an entry (research D6) — the record stores only what the human contributed, and a part-way record stays small
- [ ] T030 [US4] Implement `compose(narration, record)` in `session_doc/compose.py`: `authored` and `edited` place the human's text, `cut` removes the block, `mine` and absent leave the gap standing
- [ ] T031 [US4] Refuse in `session_doc/compose.py` when the record's `generated_sha256` does not match the narration, naming both digests. This is the whole of v1's staleness handling — the same self-invalidating property `transcript_corrections`' `was` check gives the tape
- [ ] T032 [US4] Write `anchor` values into the record without matching on them (research D2), so a record authored today survives into #456's matcher without a migration
- [ ] T033 [US4] Implement `sd_compose` in `session_doc/sd_compose.py` — one scene or a narration directory — and register it in `pyproject.toml` `[project.scripts]`

**Checkpoint**: a hand-authored record composes deterministically and refuses when stale.

---

## Phase 7: User Story 5 — A chapter is never assembled with open gaps in it (P2)

**Goal**: assembly refuses on a scene still holding a marker, and names every scene responsible.

**Independent test**: assemble a session where one scene has an unanswered gap; the refusal names
that scene.

- [ ] T034 [P] [US5] Create `tests/test_assemble_gate.py` with contract G: the gate refuses on a marker (G1), names **every** scene rather than the first (G2), and is off by default so today's behaviour is unchanged (G4)
- [ ] T035 [P] [US5] Add contract V to `tests/test_assemble_gate.py`: one stem with both `.scrubbed.md` and `.composed.md` refuses naming both (V1), `--use` resolves it (V2), and the message distinguishes this from #429's collision (V3)
- [ ] T036 [US5] Implement `--require-composed` in `session_doc/assemble.py`, reading the **assembled documents** for markers rather than consulting any record (research D3) — so the gate holds for a scene composed by hand, by #456, or by anything else
- [ ] T037 [US5] Make `collect_scene_files` in `session_doc/assemble.py` raise the existing `SceneCollision` for a scrubbed/composed variant clash, reusing `--use` rather than adding a second flag with the same meaning (research D4, Principle XII)
- [ ] T038 [US5] Word the two collision messages in `session_doc/assemble.py` so they are not confused: #429's is *two scenes with one number*, this one is *one scene with two final variants*

**Checkpoint**: a marker cannot reach an assembled chapter, and no variant is chosen by sort order.

---

## Phase 8: User Story 6 — Re-narrating never silently destroys authored work (P2)

**Goal**: re-running narration over a scene with authored content refuses.

**Independent test**: author a record, re-run narration, confirm the refusal names the file.

- [ ] T039 [P] [US6] Create `tests/test_narrate_authored_refusal.py` with contract N: a record with authored content blocks a re-run naming the record (N1), `--reroll` lifts it and states what becomes of the record **before** acting (N2), an empty record does not block (N3)
- [ ] T040 [US6] Implement the refusal in `session_doc/sd_narrate.py` before any model call — spending tokens and then refusing to write is the worst ordering
- [ ] T041 [US6] Implement `--reroll` in `session_doc/sd_narrate.py` as a refusal-lift, **not** a merge. Anchor matching is deferred whole (research D2); merge review is #456's, with its UX

**Checkpoint**: the only hand-written thing in this pipeline cannot be destroyed by accident.

---

## Phase 9: Polish

- [ ] T042 [P] Document the workflow in `docs/cli/session_doc_pipeline.md`: the three files, the reviewer and how it reaches a phone, the two progress figures, the gate, and that the round trip stops at the clipboard
- [ ] T043 [P] Write `docs/cli/gap_review_howto.md` — task-oriented, in the style of `player_identity_howto.md`: get the reviewer onto a phone, review a scene at work, land the result, and every refusal decoded
- [ ] T044 [P] Add the `CLAUDE.md` note: the record is the source of truth and `.composed.md` is output, `unruled` is an absent entry, the gate reads documents not records, and nothing in this layer may call a model
- [ ] T045 [P] Add the reviewer's version-agreement test to `tests/test_reviewer_selfcontained.py` (W2): the schema version the page declares equals `session_doc/review/schema.py`'s constant. This is the guard that exists *because* the page is no longer regenerated per session
- [ ] T046 Run the full suite (`python -m pytest tests/`) and confirm no regression beyond the known environmental `test_configure_mcp.py::test_git_root_returns_path_itself_when_not_in_a_repo`

### On a real device — the part no test covers

- [ ] T047 Save `session_doc/review/reviewer.html` to a phone, put the device in airplane mode, paste a corpus scene export, and rule every gap. Confirm the render, the foot table, and the two progress figures
- [ ] T048 **Reload `session_doc/review/reviewer.html` mid-review on the device.** Either the rulings survive or the warning was shown before work began (FR-016). Do this **first** of the device checks — research names it the open risk, and a GM who loses twenty rulings will not use this twice
- [ ] T049 From `session_doc/review/reviewer.html` on the device, copy as prompt and paste into a chat that is not Claude; and confirm it reads as a request to draft. That the reviewer is not tied to one vendor is the reason it is not an artifact

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1** → **Phase 2** → everything. T004's round-trip is the gate.
- **Phases 3–5 (US1, US2, US3)** all live in `reviewer.html` and run in sequence.
- **Phase 6 (US4)** needs only Phase 2. It is independent of the reviewer and could run in parallel with Phases 3–5 by a second person.
- **Phase 7 (US5)** needs Phase 6 for a composed document to exist, though T036 reads documents rather than records and could be tested against a hand-made file.
- **Phase 8 (US6)** needs Phase 6 for a record to exist.
- **Phase 9** needs all of it; T047–T049 need Phases 3–5.

```
Phase 2 ──┬── US1 ── US2 ── US3        (reviewer.html, one file, in sequence)
          │
          └── US4 ──┬── US5            (gate)
                    └── US6            (re-narrate refusal)
```

### Parallel opportunities

- T005, T006, T007 — three test files, no overlap
- T008, T009 — export tests and reviewer tests
- T024, T025 — both in `test_block_model.py`, so sequential in practice despite the concern being distinct
- T026, T027 — contract R and contract C
- T034, T035 — same file; distinct contracts
- T042, T043, T044, T045 — four files, no overlap
- **US4 alongside US1–US3** — the largest real parallelism, if two people are working

---

## Implementation Strategy

### MVP

**Phase 1 + Phase 2 + Phase 3 (US1).** A GM can export a scene, open the reviewer on a phone with
no network, and rule every gap. That is the entire review step, and it is useful before anything
can write the result back.

This is deliberately ahead of the record layer. Building US4 first produces a file with nothing
able to fill it, and the ruling that the round trip stops at the clipboard means the record is
hand-edited anyway.

### Incremental delivery

1. **Phases 1–3** — review a scene on a phone, offline
2. **Phase 4** — draft the passages with any model
3. **Phase 5** — edit the model's prose too; the reviewer is done
4. **Phase 6** — the record composes into a finished scene
5. **Phase 7** — a marker cannot reach a chapter
6. **Phase 8** — authored work cannot be destroyed
7. **Phase 9** — docs, guards, and the device checks

### What to watch

**T004**, because everything downstream inherits it, and its failure mode is misattributed —
a lost blank line looks like compose misbehaving.

**T048**, because it is the only task whose failure would change the design rather than the code.
If rulings do not survive a reload on the GM's actual device, the reviewer needs a different
persistence story, and that is worth knowing before Phases 6–8 are built on top of it.
