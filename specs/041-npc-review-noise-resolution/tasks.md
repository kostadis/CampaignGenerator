---
description: "Task list for 041 NPC review noise resolution (#621)"
---

# Tasks: NPC Review Noise Resolution

**Input**: Design documents from `specs/041-npc-review-noise-resolution/`

**Prerequisites**: plan.md, spec.md, research.md (R1–R13), data-model.md, contracts/cli-review-noise.md, contracts/noise-diagnostic.md, quickstart.md

**Tests**: REQUIRED. FR-019 and every user story's Independent Test call for fixture tests. Write each story's tests first, and confirm they fail before implementing.

**Repos**:
- **CG** = this worktree, branch `041-npc-review-noise-resolution`.
- **MT** = `~/src/mytools`, worked in its own worktree on branch `041-noise-class-cards`. Never on `main`, which has unrelated uncommitted edits.

**Environment rule (every CG test command)**: `PYTHONPATH=<CG worktree> ~/.venv/bin/python -m pytest …` (`~/.venv` is the server venv; `~/.venvs/main` has no pytest) (research R13). A green run without the pinned `PYTHONPATH` proves nothing about this branch.

**Hard invariants (check in every task)**:
- No model call anywhere in this feature (FR-018).
- No GM verdict is ever inferred. Unmarked stays unmarked (FR-016, FR-017).
- Nothing writes to `~/storm-giant/stormgiants`.
- A genuinely unsupported number, ordinal or status word still reaches the GM (FR-019).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US4 from spec.md

---

## Phase 1: Setup

- [X] T001 Verify that `PYTHONPATH=<CG worktree> ~/.venv/bin/python -c "import pipelines; print(pipelines.__file__)"` prints the worktree path, and that `python -m pytest tests/test_summary_native_review_verification_adapter.py tests/test_summary_native_npc_verify.py -q` passes on the unmodified branch. Record the pass count in `specs/041-npc-review-noise-resolution/validation.md`.
- [X] T002 Create the MT worktree: `git -C ~/src/mytools worktree add -b 041-noise-class-cards <scratchpad>/mt041 origin/main`. Then run its existing kit tests, `python -m pytest dotfiles/claude/skills/_shared/review-artifact/tests -q`, and record the result in `specs/041-npc-review-noise-resolution/validation.md`.

---

## Phase 2: Foundational (blocks US1–US4)

**Purpose**: the pure `noise` module, the reviewed tables and the store enum. See research R2–R8 and data-model.md.

- [X] T003 [P] Create `pipelines/summary_native/data/ordinal_idioms.yaml`. It is a top-level YAML list of exact lowercase phrases: "first time", "at first", "third person", "first of all", "at first light", "second-hand", "second nature", "third party". Add a header comment saying it is a reviewed table, changed only by PR, with no model edits.
- [X] T004 [P] Create `pipelines/summary_native/data/status_synonyms.yaml`. It maps **every** word in `npc_verify.STATUS_WORDS` (alive, dead, died, killed, slain, missing, departed, captured, freed) to the list of evidence forms that support it. Include at least: departed → depart/departs/departing/leave/leaves/left/leaving; died → die/dies/dead/death/killed/slain; dead → died/dies/death/killed/slain. Use the same reviewed-table header comment.
- [X] T005 Create `pipelines/summary_native/noise.py` with the table loaders `load_ordinal_idioms()` and `load_status_synonyms()`. Resolve paths with `Path(__file__).resolve().parent / "data" / …`, as `npc_forms.WORDLIST_PATH` does. Validate the shape: a non-empty list of non-blank lowercase strings, or a mapping whose keys equal `STATUS_WORDS` exactly. Raise `ValueError` naming the file on any violation. There is no default fallback. Add the module docstring stating it is deterministic and makes no model call.
- [X] T006 In `pipelines/summary_native/noise.py`, add `split_sentences(line) -> list[str]` and `sentence_claims(draft_text) -> list[SentenceClaim]`, per research R2 and the data-model `SentenceClaim`. Never split inside `[...]` brackets, and never after the abbreviations St., Mr., Mrs., Dr., vs., e.g., i.e., ch. Citations come from `npc_check.citation_parts(sentence)`; when a sentence has none, it inherits `citation_parts(line)` and sets `inherited=True`. `claim` is the sentence with `npc_check.BRACKET_RE` removed.
- [X] T007 In `pipelines/summary_native/noise.py`, add `tokens(claim) -> list[Token]` per research R3 and R4:
  - comma-grouped numbers `\d{1,3}(?:,\d{3})+` are one cardinal;
  - `\d+(st|nd|rd|th)` and ordinal words are ordinals;
  - a spelled-cardinal parser covers units, teens, tens, hyphenated tens, hundred/thousand/million and the article forms "a hundred" and "a thousand". A phrase it cannot fully convert gets `value=None` and keeps its surface;
  - label detection: a token after chapter(s)/ch/ch./scene(s)/session(s), including an `N–M` or `N-M` range; a `\d{3}\.\d{2}` scene id; or a leading list numeral;
  - idiom detection against `load_ordinal_idioms()`: an exact phrase containing the token.

  Only the token attached to a label word is a label.
- [X] T008 In `pipelines/summary_native/noise.py`, define:
  - `CLASSES = ("label", "idiom", "negated-status", "spelled-number", "synonym", "other-citation")`, in precedence order;
  - `legacy_code(noise_class) -> "noise-<class>"`;
  - frozen dataclasses `NoiseRecord` and `CheckAccounting` as in data-model.md. `CheckAccounting` has `examined`, `supported`, `noise` (a dict over all six classes, zero-filled) and `findings`, and a `check()` method asserting `examined == supported + sum(noise.values()) + findings`;
  - `to_dict()` and `from_dict()` on both.
- [X] T009 [P] Add `CLASSIFIED_NOISE = "classified_noise"` to `FindingCategory` in `pipelines/summary_native/review/models.py`. It is additive only: no existing member changes, and no `SCHEMA_VERSION` bump (research R8).
- [X] T010 [P] Add `"noise"` to the AST-guarded no-LLM module set in `tests/test_summary_native_no_llm.py`, both in the list and in the asserted set.
- [X] T011 Write `tests/test_summary_native_noise.py`, covering T005–T008:
  - the loaders reject a malformed or missing table;
  - sentence splitting edge cases: abbreviations, brackets, a line with one trailing citation;
  - tokens: "5,000" is one token; "5, 6 and 7" is three; "five"=5, "a thousand"=1000, "twenty-five"=25; "three hundred and twelve" either converts to 312 or has `value=None`, never silently 3;
  - labels: "Chapter 036", "chapters 028–064", "ch 12-14", "1. ", "036.04"; and in "lost 36 hit points in Chapter 36", only the second 36 is a label;
  - idioms: "for the first time" is an idiom, "the third giant to fall" is not;
  - the `CheckAccounting` invariant.

**Checkpoint**: `PYTHONPATH=… pytest tests/test_summary_native_noise.py tests/test_summary_native_no_llm.py -q` passes.

---

## Phase 3: User Story 1 — Labels, idioms and number spellings are not flagged (P1) 🎯 MVP

**Goal**: chapter/scene labels, curated idioms, spelled-out numbers and comma-grouped numbers stop producing number/ordinal findings, and each becomes a classified-noise review item.

**Independent Test**: a fixture draft containing each pattern plus one genuinely unsupported number yields exactly one GM-facing number/ordinal finding. Every other occurrence is a noise item under its class.

### Tests (write first, confirm they fail)

- [ ] T012 [P] [US1] In `tests/test_summary_native_review_verification_adapter.py`, add fixture tests built with the file's existing `SelectedNpcVerification` helpers, one per spec US1 acceptance scenario (1–6):
  - "In Chapter 036, Blasius warns the party [ch 036 / 036.04]" → a `noise-label` item, no number finding;
  - "five gold pieces" vs evidence "5 gp" → `noise-spelled-number`;
  - "a thousand giants" vs "1,000 giants" → matches;
  - "5,000 gold" unsupported → the finding's `details.tokens == ["5,000"]`;
  - "for the first time" → `noise-idiom`;
  - "the third giant to fall", unsupported → an `ordinal-inconsistency` finding is still raised.

  Assert that each noise item has exactly one diagnostic, `legacy_code` `noise-<class>`, `categories == {CLASSIFIED_NOISE}`, `severity` ADVISORY and `blocking` False.

### Implementation

- [ ] T013 [US1] In `pipelines/summary_native/noise.py`, add `classify_numbers(draft_text, evidence) -> (findings, noise_records, accounting)`. `evidence` is an `npc_check.EvidenceIndex`. For each `SentenceClaim` and each non-label… token: label → `label`; inside an idiom → `idiom`; otherwise compare `(kind, value)`, or the surface when `value` is None, against the tokens of every cited occurrence (`evidence.items_at(chapter, scene)`). The token outcome is one of:
  - `supported`;
  - `spelled-number`: it matched only via normalisation, where either side is spelled;
  - `other-citation`: see US2, implemented in T017;
  - a finding.

  Apply the precedence from `CLASSES`. A finding is an `npc_verify.Finding` with code `ordinal-inconsistency` when the token is an ordinal, else `number-inconsistency`. Its `text` is the sentence. Its `detail` is the FR-011 message: `draft says "<token>"; no scene this sentence cites contains it (cited: <scenes>)`. When a sentence has several unsupported tokens, produce one finding per sentence listing them all in order.
- [ ] T014 [US1] In `pipelines/summary_native/review/verification.py`, replace the body of `_deterministic_semantic_advisories` so it calls `noise.classify_numbers`, and delete `_markers`, `_MARKER_RE` and `_ORDINAL_WORDS` if nothing else uses them (check with grep). Keep `same-citation-inconsistency`, but compute its marker sets with `noise.tokens(...)`, excluding labels and idioms, so labels and "5,000" stop creating false conflicts (research R11). Return the noise records alongside the findings.
- [ ] T015 [US1] In `pipelines/summary_native/review/verification.py`, emit noise items in `adapt_selected_verifications`. Add an `_noise_item(...)` sibling of `_item` with group `"noise"`, that sets:
  - `legacy_code=noise.legacy_code(cls)`, `blocking=False`, `severity=ADVISORY`, `assignment_basis=MECHANICAL`;
  - `categories={CLASSIFIED_NOISE}`, `proposed_action.action="review_classified_noise"` with `details.legacy_code`;
  - Diagnostic `details` = `NoiseRecord.to_dict()` plus `line`;
  - the message from contracts/noise-diagnostic.md;
  - `claim_text` = the exact draft line (custody binding is unchanged);
  - evidence = the excerpt of the resolving scene where one exists.

  Item ids come from the existing `_stable_payload` fingerprint. In `_categories`, `_severity`, `_basis` and `_action`, map every `noise-*` code explicitly; the generic `"number"` substring branch must not catch them.
- [ ] T016 [US1] In `pipelines/summary_native/review/verification.py`, add the structured fields `check`, `tokens`, `sentence` and `cited_scenes` (contracts/noise-diagnostic.md) to the GM-facing number/ordinal diagnostics' `details`, by extending `_item` for those codes. `_evidence` for these codes binds the cited occurrence of the finding's **sentence**, not the line.

**Checkpoint**: T012 passes, and the existing adapter tests still pass, or are updated only where they asserted the old whole-line message. List every such update in `validation.md` with the reason.

---

## Phase 4: User Story 2 — Numbers are checked against every scene the sentence cites (P1)

**Goal**: a number found in any scene the sentence cites is supported. Absent from all of them, it is one finding naming the token, sentence and scenes.

**Independent Test**: a sentence cites A and B and contains "200" (only in A) and "40" (in neither). Exactly one finding is raised, for "40", naming both A and B. "200" is `noise-other-citation`.

- [ ] T017 [P] [US2] In `tests/test_summary_native_review_verification_adapter.py`, add the US2 acceptance scenarios 1–3:
  - the 085.07/085.08 "200" case → `noise-other-citation` with `resolved_by == "ch 085 / 085.07"`;
  - "40" in neither → one finding with `details.tokens == ["40"]` and both scenes in `cited_scenes`, its message matching FR-011;
  - a three-sentence paragraph → each finding's `details.sentence` is its own sentence only.

  Add an accounting test: `examined == supported + noise + findings` for a mixed fixture.
- [ ] T018 [US2] In `noise.classify_numbers` (`pipelines/summary_native/noise.py`):
  - present in every cited occurrence → `supported`;
  - present in at least one but not all → `other-citation`, with `resolved_by` = the first scene (in citation order) containing it;
  - in none → a finding.

  A sentence with a single citation can never produce `other-citation`.

**Checkpoint**: T012 and T017 pass.

---

## Phase 5: User Story 3 — Status words accept reviewed synonyms and ignore negated statements (P1)

**Goal**: `status-claim-unsupported` stops firing on table synonyms and not-established sentences. The remaining findings name the word, sentence and cited scenes.

**Independent Test**: a draft with "departed" (evidence: "leaves"), "No further status (alive, dead) is established", and "captured" (unsupported) yields exactly one status finding, for "captured".

- [ ] T019 [P] [US3] In `tests/test_summary_native_npc_verify.py`, add the US3 acceptance scenarios 1–4:
  - departed/leaves → `synonym`, with `resolved_by == "leaves"`;
  - "No further status (alive, dead, escaped) is established" → two `negated-status` records;
  - "Belg was captured" with no synonym → one finding whose detail names "captured" and whose text is the sentence;
  - an off-table synonym → flagged.

  Also test the negation edge case: "he did not flee; he died", with "died" unsupported, is still flagged.
- [ ] T020 [US3] In `pipelines/summary_native/noise.py`, add:
  - `is_not_established(sentence) -> str | None`, using the closed pattern set from research R7 and returning the matched phrase;
  - `classify_status(draft_text, sections, evidence_text) -> (findings, noise_records, accounting)`. It keeps today's scope (the Last-State section plus the first MAP section) and today's comparison against the whole evidence text (spec Assumptions), but works per sentence. Each status word lands in exactly one of: inside a not-established sentence → `negated-status`; literal word in the evidence → `supported`; a table synonym in the evidence → `synonym` (`resolved_by` = that word); otherwise → a finding. The finding's text is the sentence and its detail is `draft says "<word>"; neither it nor a listed synonym appears in the evidence (sentence cites: <scenes>)`.
- [ ] T021 [US3] In `pipelines/summary_native/npc_verify.py`:
  - make `check_status_words` delegate to `noise.classify_status`;
  - add `noise: tuple[NoiseRecord, ...] = ()` and `accounting: dict = {}` to `ScopedCheckResult` and `VerificationResult`;
  - serialise them in `to_dict`/`from_dict`. A cached result without the keys loads as empty; cached results are regenerated by re-verifying, and this is not a back-compat probe of a retired location;
  - make `verify_scoped` and `verify` carry them through.
- [ ] T022 [US3] In `pipelines/summary_native/npc_verify.py`, make `render_verify_md` emit a `## Classified noise` section. It holds per-class counts in `CLASSES` order, one line per record (`- [<class>] line <n>: "<token>" — <sentence> (resolved by: <x>)`), and the accounting line `examined N = supported a + noise b + findings c`. The section is omitted only when `examined == 0`.
- [ ] T023 [US3] In `pipelines/summary_native/review/verification.py`, make `adapt_selected_verifications` turn `selection.result.noise` (status noise) into noise items, through the same `_noise_item` as T015. Give status findings' diagnostics the same structured `details` as T016 (`check: "status"`).

**Checkpoint**: T019 passes, and the npc_verify and adapter suites are green.

---

## Phase 6: User Story 4 — The GM can audit classified noise and decide a class at once (P1)

**Goal**: `review noise` lists noise by class with occurrences. `review noise decide` records one GM class verdict as one decision per occurrence. `review policy` auto-approves a class unchanged. There is a UI route.

**Independent Test**: on a fixture review with every class, `review noise --json` lists the classes in precedence order with correct counts. A `decide --write` on one class decides only that class, each with the class-verdict note. A single-class policy approves only that class.

### Tests (write first)

- [ ] T024 [P] [US4] Create `tests/test_summary_native_review_noise_cli.py`, following the review-creation fixtures in `tests/test_summary_native_review_delegated.py`. Cover every row of contracts/cli-review-noise.md:
  - JSON shape, classes in precedence order, zero-count classes listed;
  - a dry run writes nothing (the event count is unchanged);
  - `--write` decides only undecided items of that class, each with the `GM class verdict on batch card [noise-<class>] (<k> occurrences): <note>` note;
  - reject → `reject_action`;
  - the refusals `REVIEW_NOISE_UNKNOWN_CLASS`, `REVIEW_NOISE_NOTHING_TO_DECIDE`, `REVIEW_NOISE_NOTE_REQUIRED` and `REVIEW_NOISE_NOTE_TOO_LONG`, and argparse failing without `--class`;
  - already-decided items are skipped and listed, never overwritten;
  - an unmarked class leaves every item undecided in `review status`.
- [ ] T025 [P] [US4] In `tests/test_summary_native_review_delegated.py`, add a policy-compatibility test: the policy file `{noise-label: "labels"}` via `plan_policy` approves exactly the `noise-label` items, with the policy note, and no other class (FR-015, SC-006).
- [ ] T026 [P] [US4] In `tests/test_summary_native_review_http.py`, add route tests for `GET /{review_id}/noise` and `POST /{review_id}/noise/decide`, asserting the argv they build (the CLI is shelled out) and the error-code status mapping. Follow the file's existing route-test pattern.

### Implementation

- [ ] T027 [US4] In `pipelines/summary_native/review/delegated.py`, add:
  - `list_noise(root, review_id) -> dict`, which reads `read_review_state` and groups items whose single legacy_code starts with `noise-`, in `noise.CLASSES` order, with the decision state per occurrence;
  - `plan_noise_class(root, review_id, *, noise_class, verdict, note) -> dict`, modelled on `plan_policy`. It raises `ReviewStoreError` with the four `REVIEW_NOISE_*` codes, builds decisions with `_decision(...)` (approve → `accept_no_change`, reject → `reject_action`), validates with `_validate_action_decision`, and enforces `max_note_chars` on the prefixed note.

  Writing goes through the existing `submit_decisions`. Add no new write path.
- [ ] T028 [US4] In `pipelines/summary_native/review/cli.py`, add the `noise` subparser, with the positional `review` and a `decide` sub-subcommand taking `--class` (required, choices = `noise.CLASSES`), `--verdict {approve,reject}` (required), `--reviewer` (required), `--note` (required), `--write`, and `_scope_args`. Reuse the delegated epilog wording. Wire dispatch beside `carry`/`policy`: dry run by default, `--write` submits, text and `--json` outputs as in the contract.
- [ ] T029 [US4] In `server/routers/review_routes.py`, add `GET /{review_id}/noise` and `POST /{review_id}/noise/decide`, with a pydantic request model `{noise_class, verdict, reviewer, note, write: bool = False}`. Build argv and call `_run(root, "noise", …)`. Put no logic in the router (Principle VI). Map the `REVIEW_NOISE_*` codes in `_status_for` to 400 or 409, consistent with the existing codes.

**Checkpoint**: T024–T026 pass.

---

## Phase 7: User Story 4 face — class cards in the review-artifact kit (MT, own branch)

**Goal**: the GM's actual review page shows one card per noise class, and one verdict becomes a decision per occurrence on read-back (GM ruling, plan.md XI). All paths are relative to the MT worktree.

- [X] T030 [P] [US4] In `dotfiles/claude/skills/_shared/review-artifact/tests/test_npc_review_items.py`, add tests:
  - noise items (legacy_code `noise-*`) render one card per class, with card id `noise-class:<class>`, a body listing every occurrence (NPC, token, sentence, cited scenes, resolved_by) and the count;
  - classes the review has already fully decided (for example by policy) render no card;
  - non-noise items render exactly as before.
- [X] T031 [P] [US4] Create `dotfiles/claude/skills/_shared/review-artifact/tests/test_read_decisions.py`, or extend the existing kit tests. A saved page with Approve on `noise-class:label` must produce one decision per member item id, each carrying the card note. Undecided or Discuss on a class card must produce no decision for any member. A page whose class membership differs from the items file must exit 2, the same stale-page rule as today.
- [X] T032 [US4] Edit `dotfiles/claude/skills/_shared/review-artifact/npc_review_items.py` to group `noise-*` items into class cards placed in their own "Classified noise" group, ahead of the per-NPC groups. The card text says: "One verdict here applies to every listed occurrence; each gets its own decision record." Record the member item ids on the card in the items JSON.
- [X] T033 [US4] Edit `dotfiles/claude/skills/_shared/review-artifact/read_decisions.py` to expand a class-card verdict into the member item ids from the items file. It never infers a verdict for any item not on a decided card.
- [X] T034 [US4] Update `dotfiles/claude/skills/_shared/review-artifact/CONTRACT.md` with the class-card shape and the expansion rule. Run the kit test suite, and record the result in CG's `specs/041-npc-review-noise-resolution/validation.md`.

---

## Phase 8: Baseline oracle (SC-001, SC-002, SC-004, SC-005, SC-007)

- [X] T035 Inspect, **read-only**, `~/storm-giant/stormgiants/docs/reviews/npc-review-6ee694eebf5b/requests/gm-number-noise-*.json` and `gm-status-synonym-*.json` (top-level keys `request_sha256`, `result`). Also inspect the review's `items/`, `sources/` and `manifest.json`, and `docs/npcs/summary_native/ch001-086/`. Document in `specs/041-npc-review-noise-resolution/validation.md` how to recover, for each GM-ruled noise item, its draft path, line and flagged token, and how to get each draft's exact draft and evidence bytes. Never write to that checkout.
- [ ] T036 Create `tests/test_summary_native_noise_baseline.py`. It is skipped unless the env var `STORMGIANTS` points at an existing checkout. It replays every draft of `npc-review-6ee694eebf5b` through `noise.classify_numbers` and `noise.classify_status`, and asserts:
  - SC-001: GM-facing number/ordinal findings ≤ 100;
  - SC-002: zero status findings on GM-ruled synonym items;
  - SC-004: every token the GM did **not** rule as noise is still a GM-facing finding (print any misses);
  - SC-005: the accounting invariant holds for every draft;
  - SC-007: at most 6 noise classes appear.

  It opens files read-only. Run it, and record the actual numbers in `validation.md`.

---

## Phase 9: Polish & cross-cutting

- [ ] T037 [P] Document `review noise`, `review noise decide`, the six classes with their precedence, and the policy keys `noise-<class>` in `docs/cli/summary_native_review.md`. Add a "Reading classified noise" note, pointing at the `verify.md` section and `review noise`, to `docs/cli/npc_dossiers_howto.md`.
- [ ] T038 [P] Add `review noise` to the review command table in `CLAUDE.md` only if that table lists the other review verbs. Otherwise skip it, and say so in `validation.md`.
- [ ] T039 Run the full suite, `PYTHONPATH=<CG worktree> ~/.venv/bin/python -m pytest tests/ -q`, and the frontend checks only if any frontend file changed (none is planned). Record the results in `validation.md`.
- [ ] T040 Walk through quickstart.md sections 1–4 and record each outcome in `validation.md`.

---

## Dependencies & Execution Order

- **Setup (T001–T002)** → **Foundational (T003–T011)** → user stories.
- **US1 (T012–T016)** is the MVP. **US2 (T017–T018)** extends `classify_numbers` and depends on US1's T013–T015. **US3 (T019–T023)** depends only on Foundational, plus T015's `_noise_item`, and T023 runs after T015. **US4 CLI (T024–T029)** needs noise items to exist (T015 or T023). **Kit (T030–T034)** needs only the item JSON shape from contracts/noise-diagnostic.md, so it can start once T015 lands.
- **Baseline (T035–T036)** needs US1, US2 and US3.
- **Polish** comes last.

### Parallel opportunities

- T003, T004, T009 and T010 touch different files.
- The test-writing tasks T012, T017, T019, T024, T025, T026, T030 and T031 are each in their own file, or in separate test functions written by one agent per file.
- After Foundational: US3 (T019–T022) can proceed in parallel with US1 and US2 (they touch `npc_verify.py`, not `verification.py`), until T023.
- The kit phase (MT) runs in parallel with the US4 CLI phase (CG). They are different repos.

## Implementation Strategy

1. **MVP** = Phases 1–3: labels, idioms and spelled/comma numbers resolved, with noise items in the store. This alone addresses about 281 of the 400 noise findings.
2. Add US2 for the other-citation share (about 119), then US3 for status.
3. Add US4 (CLI and route), then the kit faces, so the GM sees about 6 class cards in place of about 400.
4. Run the baseline oracle to prove SC-001, SC-002, SC-004, SC-005 and SC-007 on the real stormgiants data.
5. Open two PRs, one for CG (`041-npc-review-noise-resolution` → main) and one for MT (`041-noise-class-cards` → main), cross-linking each other and #621. **Never merge without the GM's go-ahead.**
