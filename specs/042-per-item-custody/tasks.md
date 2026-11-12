---
description: "Task list for 042 per-item source custody (#624, #633)"
---

# Tasks: Per-Item Source Custody for NPC Review

**Input**: Design documents from `specs/042-per-item-custody/`

**Prerequisites**: plan.md, spec.md, research.md (R1–R15), data-model.md, contracts/custody-refusal.md, contracts/review-status.md, contracts/publish-held.md, quickstart.md

**Tests**: REQUIRED. Every acceptance scenario has a named regression test (`test_us<N>_s<M>_…`). Write each story's tests first, and confirm they fail before implementing.

**Environment rule (every test command)**: `PYTHONPATH=<worktree> ~/.venv/bin/python -m pytest --basetemp=$HOME/.cache/pytest-042 …` (research R15). A green run without the pinned `PYTHONPATH` proves nothing about this branch. Do not use xdist.

**Hard invariants (check them in every task)**:
- Never weaker: an item whose dependency set contains a changed, missing or unreadable file is refused. There are no missed refusals (FR-002, SC-002).
- No automatic refresh, rebind or re-verify (FR-008). No model call (FR-015).
- No on-disk shape change. Dependency sets are computed, not stored (R2).
- Nothing writes to `~/storm-giant/stormgiants`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US4 from spec.md

---

## Phase 1: Setup

- [X] T001 Verify that `PYTHONPATH=<worktree> ~/.venv/bin/python -c "import pipelines; print(pipelines.__file__)"` prints the worktree path. Then run `tests/test_summary_native_review_decisions.py tests/test_summary_native_review_delegated.py tests/test_summary_native_npc_publish.py tests/test_delta_freshness.py tests/test_summary_native_review_routes.py tests/test_summary_native_review_http.py -q` on the unmodified branch. Record the pass counts in a new `specs/042-per-item-custody/validation.md`.
- [X] T002 [P] Read-only, record the stormgiants measurements in `specs/042-per-item-custody/validation.md`:
  - source counts by role: 164/164/84;
  - items per NPC: mean 4.8, max 19;
  - the 8 NPCs whose evidence names `docs/summaries/010-session-the-seer.md`;
  - the current drift against custody generation 5: 5 drafts, 1 summary, 4 evidence files.

  Use a scratch script that opens files read-only (R15).

---

## Phase 2: Foundational (blocks US1–US4)

**Purpose**: the one seam `review/custody.py`, the error detail and the shared fixture. See data-model.md and R2–R7, R12.

- [X] T003 [P] In `pipelines/summary_native/review/store.py`, extend `ReviewStoreError.__init__(self, message, code=None, *, detail=None)` to store `self.detail`. Every existing raise is unchanged. Add a test in `tests/test_summary_native_review_custody.py` that `detail` defaults to `None` and that code-prefix inference still works.
- [X] T004 [P] Create `tests/_custody_fixture.py` with `build(tmp_path) -> CustodyFixture`. It builds a **real** `npc_verification` review through `summary_native review create --kind npc_verification` with a `dossiers` selection, the same way `tests/test_summary_native_npc_publish.py::_create_real_review` does, under `docs/npcs/summary_native/ch001-003/{draft,evidence,gm}/`. Use summaries `docs/summaries/001-a.md`, `002-b.md` and `003-c.md`. Every dossier entry passes all three summaries, as the full-range build does. The NPCs are:
  - **A**: evidence names only `001-a.md`, and it has at least one finding item;
  - **B**: evidence names only `002-b.md`, and it has at least one finding item;
  - **C**: evidence names `001-a.md` and `003-c.md`, and its verification raises **no** finding, so it has a sign-off item only. This exercises the R6 layout path;
  - **D**: evidence uses `- Source: selected evidence`, the delta form, which exercises the R5 fallback.

  Expose the root, the review id, the generation, items by NPC, and helpers `touch(path)`, `restore(path)`, `delete(path)`, `decide(items, verdict, …)` (CLI `review decide --json`) and `sign(npc)` (CLI `review npc sign --json`).
- [X] T005 Write `tests/test_summary_native_review_custody.py`, the unit tests for T006–T010. They must fail now. Cover:
  - `role_of` for each prefix, and `other`;
  - `evidence_summary_paths`:
    - the stormgiants-shaped `npc_nug` text (copy its structure inline, without reading the checkout) gives `{"docs/summaries/004-session-clan-licehair.md"}`;
    - a `selected evidence` line gives `None`;
    - a `## Chapter` section with no `Source:` gives `None`;
    - a path not in custody gives `None`;
    - a frontmatter `chapters:` mismatch gives `None`;
    - one malformed `Source:` line among good ones gives `None`;
  - `npc_evidence`: bound; sibling-only; layout-only, where C has no sibling; layout path not in custody plus a sibling; neither, which gives all evidence-role sources;
  - `dependency_sets`:
    - a claim of A = {A draft, A evidence, 001};
    - C's sign-off = {C draft, C evidence, 001, 003};
    - D's items include every summary-role source;
    - a non-NPC-domain item gets bound ∪ unbound sources (R7);
    - an `other`-role source is in every set;
  - an evidence file that is not `current` makes the summary basis `fallback_all_summaries` (R2);
  - `stale_report` with an injected provider:
    - `changed`, `missing` and `unreadable` each stale exactly their dependents;
    - a change and back is `current`;
    - an empty dependency set is stale with `no_dependency`;
  - the comparison uses the custody generation's sha, not `binding.custody_sha256`. Build an item whose binding sha is older than custody's, with the file equal to custody, and expect current (R3);
  - `refusal_detail` matches contracts/custody-refusal.md: key set, sort orders, `remedy.command` spelled `summary_native review refresh <id> --expected-generation <n>`, and `remedy.note` only when a draft-role file changed;
  - `npc_label`: `registry_name` first, else the stem without `npc_`.
- [X] T006 Create `pipelines/summary_native/review/custody.py` with:
  - a module docstring: deterministic, no model call, one seam for item custody (Constitution V);
  - `SourceRole` and `role_of(source_id)` (R4);
  - `FileState`;
  - `disk_probe(root)`. It hashes each path at most once per probe, raises `ReviewStoreError("REVIEW_PATH…")` through `store._reject_symlinks` for a symlink, maps `OSError` to `unreadable`, and maps a non-file to `missing`;
  - frozen dataclasses `ChangedFile`, `DependencySet` and `StaleReport` (data-model.md).
- [X] T007 In `pipelines/summary_native/review/custody.py`, add `evidence_summary_paths(evidence_bytes, custody_paths) -> frozenset[str] | None`, implementing R5 rules 1–4 exactly. Read frontmatter with `yaml.safe_load` on the leading `---` block only. Any other shape returns `None`.
- [X] T008 In `pipelines/summary_native/review/custody.py`, add:
  - `npc_evidence(item, items, custody)`: the R6 union, returning `(source_ids, basis)`;
  - `dependency_sets(kind, custody, items, item_ids, state)`, per data-model.md "Construction". It parses an evidence file only when `state(source) is FileState.current`, reading the bytes through the probe's cached read. The non-NPC rule is R7.
- [X] T009 In `pipelines/summary_native/review/custody.py`, add:
  - `stale_report(...)`;
  - `refusal_detail(report, *, review_id, generation, operation, items) -> dict`, per contracts/custody-refusal.md;
  - `refusal_message(report)`, with the one-line `REVIEW_STALE_CUSTODY: …` text;
  - `refusal_text_lines(detail)`, for CLI text mode;
  - `stale_by_npc(report, items) -> dict`, per contracts/review-status.md;
  - `remedy(review_id, generation, has_draft)`.
- [X] T010 Move the NPC label rule into `custody.npc_label(item)`: `subject_ref.registry_name`, else `_draft_stem_name(locator.source_path)`. Make `pipelines/summary_native/review/delegated.py::_occurrence` use it, and delete the local helper (XII). Confirm that `tests/test_summary_native_review_noise_cli.py` still passes unchanged.
- [X] T011 [P] In `tests/test_summary_native_no_llm.py`, add an explicit assertion that `review/custody.py` is among the files `test_review_package_makes_no_model_call` walks (FR-015).

**Checkpoint**: `pytest tests/test_summary_native_review_custody.py tests/test_summary_native_no_llm.py tests/test_summary_native_review_noise_cli.py -q` passes.

---

## Phase 3: User Story 1 — An edit stales only what depends on it (P1) 🎯 MVP

**Goal**: a decision save and an import check only the dependency sets of the items concerned, never weaker for those items.

**Independent Test**: on the T004 fixture, change A's draft. Then deciding on B succeeds, and deciding on A is refused with nothing written.

### Tests (write first, confirm they fail)

- [X] T012 [P] [US1] In `tests/test_summary_native_review_item_custody.py`, add `test_us1_s1_other_npc_signoff_saves_after_draft_edit`. Touch A's draft, `sign("B")`, and expect exit 0 with the event written. No refresh is run.
- [X] T013 [P] [US1] In `tests/test_summary_native_review_item_custody.py`, add `test_us1_s2_edited_npc_items_refused_nothing_written`. Touch A's draft, then decide on each A item kind: claim, presentation if present, and sign-off. Expect exit 3 and `REVIEW_STALE_CUSTODY`. The event files, the ledger revision and the request receipts must be byte-identical before and after.
- [X] T014 [P] [US1] In `tests/test_summary_native_review_item_custody.py`, add `test_us1_s3_summary_change_stales_only_naming_npcs`. Touch `002-b.md`. Then B's items are refused, while A's and C's items save. Repeat with `003-c.md`: only C is refused. This shows the sign-off depends on summaries through its evidence (FR-004).
- [X] T015 [P] [US1] In `tests/test_summary_native_review_item_custody.py`, add `test_us1_s4_mixed_batch_refused_whole_and_lists_every_stale`. One batch holds a B item and two A items, after touching A's draft. Expect nothing written, and `data.stale_items` = exactly the two A item ids.
- [X] T016 [P] [US1] In `tests/test_summary_native_review_item_custody.py`, add the edge-case tests:
  - `test_deleted_dependency_is_missing_and_refuses`;
  - `test_change_and_change_back_is_current`;
  - `test_signoff_depends_on_evidence`: touch C's evidence, and C's sign-off is refused (FR-004);
  - `test_unparseable_evidence_falls_back_to_all_summaries`: touch `003-c.md`, and D's items are refused while A's save;
  - `test_noise_class_card_batch_refused_whole`, using `review noise decide --write` spanning A and B;
  - `test_n_npc_review_other_npcs_unaffected`: a 12-NPC variant of the fixture, touch one draft, and decide on every other NPC's sign-off with 0 refusals. This is the fixture-scale analogue of SC-001.
- [X] T017 [P] [US1] In `tests/test_summary_native_review_item_custody.py`, add `test_withdrawal_allowed_on_stale_item`. Approve an A item, touch A's draft, then `review retract`. Expect success, with the withdrawal recording reviewer and time (FR-009).
- [X] T018 [P] [US1] In `tests/test_summary_native_review_item_custody.py`, add the import tests (FR-010, R10):
  - `test_import_checks_bundle_items_only`: export a decision on B, touch A's draft, and the import succeeds;
  - `test_import_refuses_stale_bundle_item_with_detail`: export a decision on A, touch A's draft, and the import is refused with `data.operation == "import"`;
  - `test_import_withdrawal_only_bundle_on_stale_item`: it imports;
  - `test_import_custody_digest_mismatch_still_refuses`: hand-edit the bundle's `custody_digest` and re-sign `bundle_sha256`, and it is refused.
- [X] T019 [P] [US1] In `tests/test_summary_native_review_decisions.py`, extend `test_decision_refuses_when_bound_source_custody_has_changed`. Keep its assertions, and also assert that `response["data"]["changed_files"][0]["path"] == "summaries/001/session-summary.md"` and that every submitted item id is listed. This guards SC-006: no existing refusal turns into a pass. Grep `tests/` for every other `REVIEW_STALE_CUSTODY` or `source bytes changed` assertion and confirm each still refuses. List them in `validation.md`.

### Implementation

- [X] T020 [US1] In `pipelines/summary_native/review/store.py::save_decisions`, replace the whole-custody loop (L579–582), still inside the exclusive lock and at the same point. Do this:
  1. collect the submitted ids that name known items;
  2. call `custody.stale_report(kind=manifest.kind, custody, items, ids, custody.disk_probe(root))`;
  3. if anything is stale, raise `ReviewStoreError(custody.refusal_message(r), "REVIEW_STALE_CUSTODY", detail=custody.refusal_detail(..., operation="decide"))`.

  Unknown ids still fall through to `REVIEW_STALE_DECISION`. The request-receipt replay keeps its current position before the check.
- [X] T021 [US1] In `pipelines/summary_native/review/store.py::import_review_bundle`, keep the digest comparison. Under the lock, after `missing` is computed, run the per-item check over the item ids of non-withdrawal events in `missing`, and refuse with `operation="import"` (R10).
- [X] T022 [US1] In `pipelines/summary_native/review/delegated.py::submit_decisions`, pass `detail=getattr(exc, "detail", None)` when re-wrapping, so `carry`, `policy` and `noise decide` keep the detail. Add `test_submit_decisions_keeps_custody_detail` to `tests/test_summary_native_review_delegated.py`.

**Checkpoint**: T012–T019 pass, and `tests/test_summary_native_review_*.py` passes with no assertion weakened.

---

## Phase 4: User Story 2 — A refusal says exactly what changed and what it affects (P1)

**Goal**: the same structured detail (files → items → NPC, plus the remedy) reaches the CLI text, the CLI `--json`, the local web routes and the capability viewer.

**Independent Test**: change two files, submit a batch touching both, and read the refusal on each surface.

### Tests (write first, confirm they fail)

- [X] T023 [P] [US2] In `tests/test_summary_native_review_item_custody.py`, add `test_us2_s1_json_refusal_names_files_items_npcs`. Touch A's draft and `002-b.md`, and decide on A and B items in one batch. Check `data` exactly against contracts/custody-refusal.md: two `changed_files`, each with only its dependents, NPC labels, `by_npc`, and sort orders.
- [X] T024 [P] [US2] In `tests/test_summary_native_review_item_custody.py`, add `test_us2_s2_refusal_names_refresh_command`. `data.remedy.command` must equal `summary_native review refresh <id> --expected-generation <gen>`, and `remedy.note` must be present because a draft changed. Then run that exact command and repeat the decision on B: it saves. On A, the refresh refuses as today (`REVIEW_NPC_SIGNOFF_STALE` for the sign-off), which documents R14.
- [X] T025 [P] [US2] In `tests/test_summary_native_review_item_custody.py`, add `test_us2_text_mode_lists_files_and_remedy`. Without `--json`, stdout has the `REVIEW_STALE_CUSTODY:` line, one line per changed file in the contract's text form, and the `Bring them current:` line.
- [X] T026 [P] [US2] In `tests/test_summary_native_review_routes.py`, add `test_stale_custody_refusal_relays_data`. Use the existing fake runner to return a `REVIEW_STALE_CUSTODY` envelope with `data`. The route body carries `data` verbatim, and the status is unchanged.
- [X] T027 [P] [US2] In `tests/test_summary_native_review_http.py`, add:
  - `test_capability_stale_custody_returns_whitelisted_detail`: expect 409, the custody message, and `detail.changed_files[*].{path,state,items}` only;
  - `test_capability_detail_dropped_when_shape_unexpected`: extra keys and a non-string value both drop `detail`;
  - `test_other_stale_codes_unchanged`.
- [X] T028 [P] [US2] Create `frontend/src/components/ReviewLauncher.test.ts` (Vitest). Mock `fetch` to return a 409 envelope with `data`. After "Save decision", the result `<pre>` contains the changed path and the note shows the message.

### Implementation

- [X] T029 [US2] In `pipelines/summary_native/review/cli.py`, change the refusal handler (L971–973) to `_emit(args, ok=False, code=code, message=str(exc), data=getattr(exc, "detail", None))`. In `_emit`'s text branch, when `code == "REVIEW_STALE_CUSTODY"` and `data` is present, print `custody.refusal_text_lines(data)` instead of the raw JSON.
- [X] T030 [US2] In `server/routers/review_routes.py::_error`, include `"data": payload["data"]` when it is a dict.
- [X] T031 [US2] In `pipelines/summary_native/review/web/app.py::safe_command_error`, for `REVIEW_STALE_CUSTODY`:
  - rebuild `detail` from the contract's whitelist, with string caps and a list cap of `max_batch_decisions`;
  - set the custody message;
  - keep 409.

  Every other code's body is unchanged.
- [X] T032 [US2] In `pipelines/summary_native/review/web/viewer.js`, have the `api()` error carry `body.detail`. In the save handler (L77), when `e.code === "REVIEW_STALE_CUSTODY"`, render `detail.changed_files` as a list (path, state, NPC: item ids) under `#save-state`, using `textContent` only, and unhide `#reload`. Add the list style to `viewer.css` if needed.
- [X] T033 [US2] In `frontend/src/components/ReviewLauncher.vue::request`, on refusal set `result.value = JSON.stringify(body.data, null, 2)` when `body.data` is present, before throwing. Run `npm test` and `npm run build` in `frontend/`.

**Checkpoint**: T023–T028 pass.

---

## Phase 5: User Story 3 — Review status shows stale items by NPC (P1)

**Goal**: `review status` reports `changed_files` and `stale_by_npc`, computed from the current files. The existing counts are unchanged.

**Independent Test**: change one draft and one summary, then run `review status`.

### Tests (write first, confirm they fail)

- [X] T034 [P] [US3] In `tests/test_summary_native_review_item_custody.py`, add:
  - `test_us3_s1_unchanged_sources_nothing_stale`: both lists are `[]`, and `counts` equals the pre-feature value captured in the test;
  - `test_us3_s2_draft_change_lists_only_that_npc`: A only, with its stale count equal to its item count and the draft path;
  - `test_us3_s3_summary_change_lists_naming_npcs_only`: touching `001-a.md` lists A and C, not B. D is listed too, because of the fallback, and the test asserts that explicitly as the conservative case.
- [X] T035 [P] [US3] In `tests/test_summary_native_review_routes.py`, add `test_status_route_relays_stale_by_npc`. `GET /{id}/status` returns the new keys untouched.

### Implementation

- [X] T036 [US3] In `pipelines/summary_native/review/store.py::review_status`, after the existing counts, compute `custody.stale_report(kind, custody, items, None, disk_probe(root))` from `read_snapshot`'s custody, and add `changed_files` and `stale_by_npc` per contracts/review-status.md. The `counts` code path is untouched.

**Checkpoint**: T034–T035 pass. Every existing `review status` assertion passes unchanged. Find them with `grep -rn "REVIEW_STATUS\|review_status(" tests/`. Note that `tests/test_review_status.py` is `sd_review` and is unrelated.

---

## Phase 6: User Story 4 — Publishing one NPC never fails because another NPC changed (P3)

**Goal**: sign-off freshness is per item (FR-011). Held reasons name the files (FR-013). The write is bound to the checked draft bytes (FR-012).

**Independent Test**: sign A and B, change A's draft, and publish both.

### Tests (write first, confirm they fail)

- [ ] T037 [P] [US4] Create `tests/test_summary_native_npc_publish_custody.py` using `tests/_custody_fixture.py`, with GM dossiers composed so their headers name the current draft sha, and A and B both signed with no `_signoff_checker` seam. Add `test_us4_s1_other_npc_publishes_edited_held_naming_draft`. After touching A's draft, B is `published` and A is `held`, with a reason containing A's draft display path and `custody_changed` in A's receipt (`receipt_dir` set).
- [ ] T038 [P] [US4] In `tests/test_summary_native_npc_publish_custody.py`, add `test_us4_s2_summary_change_holds_dependent_npc`. Touch `002-b.md`, and B is held with `NPC_DRAFT_SIGNOFF_STALE` naming `docs/summaries/002-b.md`. A publishes.
- [ ] T039 [P] [US4] In `tests/test_summary_native_npc_publish_custody.py`, add `test_us4_s3_draft_changed_between_check_and_write_is_held`. Wrap the real checker so that, after returning current for A, it appends a line to A's draft (the race). Expect A held with `NPC_DRAFT_CHANGED_AT_WRITE`, A's target not written, and B published. Add `test_published_body_is_bound_to_signed_draft`: B's target body equals the GM body whose header names B's signed draft sha.
- [ ] T040 [P] [US4] In `tests/test_delta_freshness.py`, add `test_graph_cannot_narrow_below_item_dependencies`. With a dependency graph that omits a summary the evidence names, a change to that summary still holds the NPC (FR-011). With the graph naming an extra file, a change to it also holds. Existing tests are unchanged.
- [ ] T041 [P] [US4] In `tests/test_summary_native_npc_publish_custody.py`, add `test_bool_signoff_api_unchanged`. `_current_draft_signoff` still returns `bool`, and the `_signoff_checker=lambda p, d: True` seam still publishes (`tests/test_summary_native_npc_publish.py` passes unchanged).

### Implementation

- [ ] T042 [US4] In `pipelines/summary_native/npc_publish.py`, add `SignoffFreshness` and `signoff_freshness(root, draft_path, draft_sha256, *, dependency_graph=None, graph_item=None, current_digests=None, probe=None)`. It matches each ledger sign-off record to its item **first**. For a match, it computes `custody.dependency_sets` for that item, unions the graph's dependencies (when they are custody paths) per FR-011, keeps `item_stale`, and keeps every existing approve/disposition/verdict/sha condition. It returns `current=True` if any record is current, and otherwise the changed files of the most recent stale record. Re-implement `_current_draft_signoff` as `signoff_freshness(...).current`.
- [ ] T043 [US4] In `pipelines/summary_native/npc_publish.py::plan_publish`, make one `custody.disk_probe(root)` per call and pass it to the default checker. In `_plan_summary_native`:
  - accept either a `bool` or a `SignoffFreshness` from the checker;
  - on stale with changed files, set the `NPC_DRAFT_SIGNOFF_STALE` reason per contracts/publish-held.md;
  - append the draft display path to the "draft changed after composition" refusal;
  - set `item.draft_path`;
  - record `item.custody_changed`.
- [ ] T044 [US4] In `pipelines/summary_native/npc_publish.py::publish.write`, immediately before `_put(it.target, text)` for a summary-native item, re-hash `it.draft_path`. If it differs from `it.draft_sha256`, or is missing, hold the NPC with `NPC_DRAFT_CHANGED_AT_WRITE` and write a `held` receipt with `custody_changed`, then continue to the next item. In `receipt_for`, add `custody_changed` when it is set. Add the `draft_path` and `custody_changed` fields to `PublishItem`.

**Checkpoint**: T037–T041 pass. `tests/test_summary_native_npc_publish.py`, `tests/test_cli_npc_publish.py`, `tests/test_delta_*.py` and `tests/test_summary_native_review_findings_547.py` pass unchanged.

---

## Phase 7: Polish & Cross-Cutting

- [ ] T045 [P] Create `tests/test_summary_native_custody_baseline.py`, a read-only replay (SC-002, SC-005). Skip it unless `STORMGIANTS` points at a checkout containing `docs/reviews/npc-review-6ee694eebf5b`, using the same skip pattern as `tests/test_summary_native_noise_baseline.py`. Load the snapshot with `read_snapshot` under the shared lock. Wrap `custody.disk_probe` with an override provider, and write nothing. Assert:
  - for every draft source f, the newly stale set compared with the no-override baseline equals exactly {items whose dependency set contains f}, and those items all share f's NPC key;
  - for `docs/summaries/010-session-the-seer.md`, the newly stale NPCs equal the NPCs whose evidence names it (8 at authoring time; assert the computed set, and print the count);
  - all 164 evidence files take the `evidence_sources` basis, with no fallback;
  - no write happened: the mtime and sha of the review directory are unchanged.
- [ ] T046 [P] Update `docs/cli/summary_native_review.md` with:
  - per-item custody: the dependency set, the GM ruling on summaries, and the fallback;
  - the refusal's text and JSON forms;
  - `review status` with `changed_files` and `stale_by_npc`;
  - that withdrawals are always allowed;
  - the import rule (R10);
  - the remedy, and the draft re-verify note.
- [ ] T047 [P] Update `docs/cli/npc_dossiers_howto.md`'s publish section with the four held reasons from contracts/publish-held.md, the `custody_changed` receipt key, and "one NPC's edit never holds another".
- [ ] T048 Run the full suite: `PYTHONPATH=<worktree> ~/.venv/bin/python -m pytest --basetemp=$HOME/.cache/pytest-042 tests/ -q`. Then run `STORMGIANTS=~/storm-giant/stormgiants … tests/test_summary_native_custody_baseline.py -s`, and in `frontend/` run `npm test` and `npm run build`. Walk quickstart.md sections 1–4. Record the counts, the replay output, and every pre-existing test changed (with the reason) in `specs/042-per-item-custody/validation.md`.

---

## Dependencies & Execution Order

- **Setup (T001–T002)**: no dependencies.
- **Foundational (T003–T011)**: T005 comes before T006–T010. T006 → T007 → T008 → T009 run in sequence in one file. T003, T004 and T011 can run in parallel. This phase blocks every story.
- **US1 (T012–T022)**: the tests T012–T019 run in parallel, then T020 → T021, and then T022.
- **US2 (T023–T033)**: depends on T020, because the detail must be raised. The tests run in parallel. T029–T033 touch different files and can run in parallel after the tests.
- **US3 (T034–T036)**: depends only on Foundational. It can run in parallel with US1 and US2.
- **US4 (T037–T044)**: depends only on Foundational. T042 → T043 → T044 run in one file.
- **Polish (T045–T048)**: T045 depends on T008 and T009. T048 is last.

## Implementation Strategy

The MVP is Foundational plus US1. That removes the #624 stall, and each later story is independently testable on the T004 fixture. US4 ships the #633 fix and can be developed in parallel with US2 and US3.

## Task count

| Phase | Tasks |
|---|---|
| Setup | 2 (T001–T002) |
| Foundational | 9 (T003–T011) |
| US1 | 11 (T012–T022) |
| US2 | 11 (T023–T033) |
| US3 | 3 (T034–T036) |
| US4 | 8 (T037–T044) |
| Polish | 4 (T045–T048) |
| **Total** | **48** |
