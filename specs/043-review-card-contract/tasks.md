---
description: "Task list for 043 review card contract (#643 slice 1, #655)"
---

# Tasks: Review Card Contract

**Input**: Design documents from `specs/043-review-card-contract/`

**Prerequisites**: plan.md, spec.md, research.md (R1–R15), data-model.md, contracts/cards-cli.md, contracts/card-files.md, contracts/cards-routes-and-launcher.md, contracts/kit.md, quickstart.md

**Tests**: REQUIRED. Every acceptance scenario has a named regression test (`test_us<N>_s<M>_…`). Write each story's tests first, and confirm they fail before implementing.

**Environment rule (every Python test command)**: `PYTHONPATH=<worktree> ~/.venv/bin/python -m pytest --basetemp=$HOME/.cache/pytest-043 …`. Run `mkdir -p $HOME/.cache` first (R15). A green run without the pinned `PYTHONPATH` proves nothing about this branch. Do not use xdist.

**Hard invariants (check them in every task)**:
- **Only an explicit GM card verdict records anything.** Unmarked stays unmarked. The packet carries no verdict, guess or recommendation (FR-004).
- **Decide expands from the stored packet, never from the decisions file.** The file's `members` and `draftSha256` are echoes, compared and never trusted (R10).
- **A whole-file refusal leaves the review tree byte-identical.** Assert it with `tests/conftest_npc.py::sha_tree` (SC-002).
- **No on-disk shape change** to any existing file. No `DecisionEvent` field is added; provenance goes in `request_id` (R6).
- **No model call.** The review package is AST-guarded.
- **Nothing writes to `~/storm-giant/stormgiants`.**
- **The GM's mytools edits are on main** (`5c5e5d5`). The mytools work starts from a fresh worktree off main.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US6 from spec.md

---

## Phase 1: Setup

- [X] T001 Verify that `PYTHONPATH=<worktree> ~/.venv/bin/python -c "import pipelines; print(pipelines.__file__)"` prints the worktree path. Then run `tests/test_summary_native_review_decisions.py tests/test_summary_native_review_delegated.py tests/test_summary_native_review_noise_cli.py tests/test_summary_native_review_routes.py tests/test_summary_native_review_item_custody.py tests/test_summary_native_no_llm.py -q` on the unmodified branch. Record the pass counts in a new `specs/043-review-card-contract/validation.md`.
- [X] T002 [P] Add `jsonschema>=4` to the `test` optional-dependency list in `pyproject.toml`. Add `pipelines/summary_native/review/schemas/*.json` to `[tool.hatch.build.targets.wheel.force-include]`, following the existing `review/web/viewer.*` entries. Create an empty `pipelines/summary_native/review/schemas/` directory with a `.gitkeep`.

---

## Phase 2: Foundational (blocks every story)

**Purpose**: the #655 action table, the `cards.py` models, the one shared expansion, and structured partial-save reporting. See R3, R4, R9 and R11.

- [X] T003 Write `tests/test_summary_native_review_action_table.py`. It must fail now. It covers:
  - **Allowed pairs.** For **every** action in research R4's table, each allowed pair is accepted by `store._validate_action_decision`, and each other `(verdict, disposition)` pair over `{approve, reject, discuss} × {accept_no_change, source_correction, merge, distinct, reject_action, defer, document_signoff}` is refused with `REVIEW_ACTION_MISMATCH`.
  - **Unknown actions.** An unknown action `"made_up_action"` is refused (FR-017).
  - **`review_claim_against_evidence` and `review_presentation`** with `approve/reject_action` and `reject/accept_no_change` are refused through `review decide` on the `_custody_fixture` review, with the store unchanged (SC-004, US2 scenario 7).
  - **Existing rows are unchanged.** That covers the sign-off branch, `confirm_claim_mapping`, the basis rule and the digest rule.
  - **Every produced action has a row.** Grep-assert that every `"action":` string literal produced in `pipelines/summary_native/review/verification.py`, `review/cli.py`, `review/documents.py`, `claims/review.py` and `claims/cli.py` has a row, or takes the sign-off branch. That way a newly produced action without a row fails this test.
- [X] T004 In `pipelines/summary_native/review/store.py::_validate_action_decision`, add the R4 rows for `review_claim_against_evidence`, `review_presentation`, `review_classified_noise`, `rerun_selected_check`, `repair_or_recheck_pointer`, `review_supersession`, `review_audience_and_knowledge`, `acknowledge_claim_coverage` and `adjudicate_identity`. Replace `if allowed is None: return` with a raise of `ReviewStoreError("REVIEW_ACTION_MISMATCH: no decisions are declared for action <action>", "REVIEW_ACTION_MISMATCH")`. Make T003 pass.
- [ ] T005 **GATE.** Run the **full** suite, `tests/ -q`. Any failure caused by T004 means stop and report it to the GM, with the test, the action and the pair. **Do not widen the table** (R4). Record the result in `validation.md`.
- [ ] T006 [P] In `pipelines/summary_native/review/cards.py` (new file), add the strict pydantic models from data-model.md: `CardPacket`, `Card`, `EvidenceRow`, `Member`, `CardDecisions`, `CardVerdict`, `DecisionPlan`, `PlannedCard` and `PlannedMember`.
  - Use camelCase aliases with `populate_by_name`, `extra="forbid"` and `frozen=True`.
  - Set `SCHEMA_VERSION = 1` and `ACCEPTED_SCHEMA_VERSIONS = frozenset({1})`.
  - Add `packet_id_for(body: dict) -> str`, which returns `"packet-" + sha256(canonical_bytes(body without packetId))[:20]`, using `models.canonical_bytes`.
  - Add `DISPOSITION_FOR`, the map from `(action, verdict)` to a disposition (R4). Approve on `signoff_npc_draft` gives `document_signoff`. Approve on any other R4 finding action gives `accept_no_change`. Reject gives `reject_action` and Discuss gives `defer` for all.
  - Add `card_note(card_id, gm_note) -> str`, returning `"GM card verdict [<id>]"` plus `": <note>"` when the note is non-empty (R5).
  - Add `schemas_dir()` and `write_schemas()`, which write `model_json_schema(by_alias=True)` for `CardPacket` and `CardDecisions` to `review/schemas/card-packet.v1.schema.json` and `card-decisions.v1.schema.json` with sorted keys and indent 2.
  - Run `write_schemas()` once and commit the two files.
- [ ] T007 [P] In `pipelines/summary_native/review/delegated.py`, make `submit_decisions` structured on partial failure (R9).
  - When batch k>0 fails, re-raise `ReviewStoreError` with the inner code and `detail={"recorded": [item ids committed so far], "not_recorded": [the rest], "cause": inner detail or None}`. Keep the existing prose suffix in the message.
  - Add an optional `batches: list[list[dict]] | None` parameter. When given, it is used as-is in place of fixed-size slicing (card-aligned packing, T018), and each batch must be at most `max_batch_decisions`, else `REVIEW_INVALID_BATCH`.
  - Extend `tests/test_summary_native_review_delegated.py` with `test_partial_save_reports_recorded_and_not_recorded`. Force a failure on batch 2 by monkeypatching `store.save_decisions` to raise on its second call, and assert the detail lists.
- [ ] T008 Write a shared-expansion test in `tests/test_summary_native_review_cards.py` (new file; the US1 tests come later). It must fail now. Call `cards.expand(snapshot, member_ids=…, verdict=…, disposition_for=…, gm_note=…)` on a hand-built review, reusing the `test_summary_native_review_delegated.py` helpers `campaign`, `_create`, `_decide` and `_item`. Assert:
  - members with no fresh decision are classified `new`;
  - members with a fresh, identical `(verdict, disposition, note)` are `identical`;
  - members with a fresh but different decision are `differs`, with the previous decision attached;
  - `expected_decision_revision` equals `delegated._active_revision`;
  - a disallowed pair raises `REVIEW_ACTION_MISMATCH`.
- [ ] T009 Implement `cards.expand` and its result type `Expansion(members: list[ExpandedMember])` in `pipelines/summary_native/review/cards.py`. Each `ExpandedMember` has `item_id`, `category`, `decision` (dict) and `previous`. It uses `delegated._current_decision`, `_active_revision`, `_latest`, `delegated._decision` and `store._validate_action_decision`. Import them; do not copy them. Make T008 pass.
- [ ] T010 Switch `delegated.plan_noise_class` to call `cards.expand`, treating both `identical` and `differs` as "already decided" (R3). Its return value, note text (`GM class verdict on batch card [noise-<class>] (<n> occurrences): <note>`), codes and `planned`/`already_decided` lists must stay **byte-for-byte unchanged**. Run `tests/test_summary_native_review_noise_cli.py` and `tests/test_summary_native_review_delegated.py` unchanged; they must pass (FR-008, FR-023).

**Checkpoint**: #655 is closed, the models and schemas exist, there is one expansion rule, and noise is unchanged.

---

## Phase 3: User Story 1 — verdicts applied without hand translation (P1) 🎯 MVP

**Goal**: `review cards export` and `review cards decide` (plan, then write) work end to end on an NPC review.

**Independent Test**: export from `_custody_fixture`, write a page-shaped decisions file, plan, write, and compare the recorded events with the expected set.

### Tests for US1 (write first; they must fail)

- [ ] T011 [US1] In `tests/test_summary_native_review_cards.py`, write the US1 tests. Use `tests/_custody_fixture.build` for finding and sign-off items. For noise members, use a hand-built review with `review_classified_noise` items from `tests/test_summary_native_review_noise_cli.py`'s `noise_review` fixture (import it, or move it to a shared helper in `tests/conftest_npc.py` if needed). Write:
  - `test_us1_s1_export_stores_packet_with_members_excluding_decided`: decide one finding first. Export. The packet file exists under `docs/reviews/<r>/packets/<packetId>.json`. Every card has `members`, the decided finding is absent, and the sign-off cards carry `draftSha256`. Assert `packetId == cards.packet_id_for(body)`. A second export returns the same id with `reused: true`.
  - `test_us1_s2_plan_lists_four_records_one_unmarked_writes_nothing`: approve a 3-member noise class card, reject one finding, leave a third card unmarked. The plan has `counts.record == 4`, `counts.unmarked == 1`, and the store tree is unchanged.
  - `test_us1_s3_write_records_exactly_the_plan`: run `--write --plan-sha256 <from plan>`. Exactly 4 new decision events exist. Each disposition equals `DISPOSITION_FOR[(action, verdict)]`, each note equals `card_note(...)`, and each `request_id` starts with `cards-<packetId>-`. The unmarked members have no events.
  - `test_us1_s4_discuss_records_defer_with_note`.
  - `test_us1_s5_partial_save_is_reported`: set `max_batch_decisions=2` through `config/review.yaml`, and fail the second batch by monkeypatching. The envelope `data` has `recorded`/`not_recorded` matching the event files on disk. Re-running decide `--write` (after a new plan) finishes the job, with the already recorded members as `noop`.
  - `test_us1_write_requires_plan_sha` gives `REVIEW_CARDS_PLAN_REQUIRED`. `test_us1_plan_changed_refuses`: a CLI `review decide` between plan and write gives `REVIEW_CARDS_PLAN_CHANGED`.
  - `test_us1_signoff_approve_records_document_signoff`: the event matches what `review npc sign` would record, except for note and request id.
  - `test_us1_cards_aligned_batches`: with cap 3 and cards of sizes 2 and 2, there are two transactions and no card is split. A card of size 5 is split.

### Implementation for US1

- [ ] T012 [US1] In `cards.py`, implement `build_packet(root, review_id, *, item_ids=None, actions=None) -> tuple[dict, list[dict]]`, returning the packet body and `skipped_signoffs` (R2).
  - It uses `store.read_review_state`.
  - It refuses any kind other than `npc_verification` with `REVIEW_CARDS_KIND`.
  - It selects items with no fresh approve or reject.
  - Noise class cards use `delegated._noise_members`, filtered to undecided members.
  - Sign-off cards run `delegated.npc_signoff_blocker`; blocked ones are skipped and listed.
  - Ordering, card text, evidence rows and `npc` labels follow research R2 and data-model.md. Port the text rules from mytools `claude/skills/_shared/review-artifact/npc_review_items.py:121-208` (read only), writing **plain text only**.
  - Duplicate membership raises `REVIEW_CARDS_DUPLICATE_MEMBER`.
  - Nothing to offer raises `REVIEW_CARDS_NOTHING_TO_EXPORT`.
- [ ] T013 [US1] In `cards.py`, implement `export_packet(root, review_id, *, item_ids, actions, out: Path | None) -> dict`.
  - Under `authority_lock(root, exclusive=True)` with `require_no_pending_transaction`, it builds the packet, validates it through `CardPacket`, and computes the id.
  - If the path exists with identical bytes, it reuses it. With different bytes it raises `REVIEW_CARDS_PACKET_CONFLICT`. Otherwise it writes via `_prepare_transaction_locked` and `recover_transaction(_already_locked=True)` with `TransactionTarget.create`, copying `store.export_review`.
  - It runs `_reject_symlinks` on the path.
  - With `out`, it writes byte-identical bytes via `campaignlib.util.atomic_write_bytes`.
  - It returns the `REVIEW_CARDS_EXPORTED` data from contracts/cards-cli.md.
- [ ] T014 [US1] In `cards.py`, implement `load_packet(root, review_id, packet_id) -> CardPacket`. It refuses:
  - a missing file with `REVIEW_CARDS_PACKET_UNKNOWN`;
  - a re-hash that is not equal to the id with `REVIEW_CARDS_PACKET_ALTERED`;
  - a `reviewId` that does not equal `review_id` with `REVIEW_CARDS_REVIEW_MISMATCH`.
- [ ] T015 [US1] In `cards.py`, implement `parse_decisions(raw: bytes, *, max_note_chars) -> CardDecisions`.
  - It checks `schemaVersion` first: anything not in `ACCEPTED_SCHEMA_VERSIONS` raises `REVIEW_CARDS_SCHEMA`, with the accepted list in the message.
  - Then it validates the model. Any validation error raises `REVIEW_CARDS_INVALID`, naming the field.
  - A note over `max_note_chars` raises `REVIEW_CARDS_NOTE_TOO_LONG`.
- [ ] T016 [US1] In `cards.py`, implement `plan_decide(root, review_id, decisions: CardDecisions) -> dict`, which returns a DecisionPlan.
  - It loads the packet (T014) and checks `generation == manifest.generation`, else `REVIEW_CARDS_PACKET_STALE` with the export command as the remedy.
  - Contract checks (US2 adds their tests; implement them here): unknown cards, the member echo set compared with the packet, and the sign-off `draftSha256` echo compared with the packet.
  - For each marked card in packet order it does three things:
    1. It refuses the card with `REVIEW_CARDS_MEMBER_STALE` if any member's live `item_revision`/`review_digest` differs from the packet's.
    2. For an Approve on a sign-off it refuses the card with the blocker code if `npc_signoff_blocker` fails.
    3. Otherwise it calls `expand`, with `noop` for `identical`, `supersede` for `differs` and `record` for `new`.
  - It runs `custody.stale_report` over all record and supersede members. A card with any stale member is refused with `REVIEW_STALE_CUSTODY` and `custody.refusal_detail` as data (spec 042).
  - It computes `planSha256` over the canonical `cards` list.
- [ ] T017 [US1] In `cards.py`, implement `apply_decide(root, review_id, decisions, *, reviewer, plan_sha256) -> dict`.
  - It rebuilds the plan. A hash that differs from `plan_sha256` raises `REVIEW_CARDS_PLAN_CHANGED`, with the new plan as detail.
  - It packs the record and supersede decisions into card-aligned batches (T018) and calls `delegated.submit_decisions(..., prefix=f"cards-{packet_id}", batches=…)`.
  - It returns the plan plus `saved`.
  - With nothing to record, it returns `saved: []` without calling the store.
- [ ] T018 [US1] In `cards.py`, implement `pack_batches(cards_decisions: list[list[dict]], cap) -> list[list[dict]]`. It packs greedily, never splitting a card unless that card alone is larger than `cap`.
- [ ] T019 [US1] In `pipelines/summary_native/review/cli.py`, add the nested subparser `cards = commands.add_parser("cards")` with `cards_command` set to `export` or `decide`, following the `npc sign` pattern at cli.py:145-147. Apply `_scope_args` to each leaf.
  - `export REVIEW [--item ID]... [--action NAME]... [--out FILE]`.
  - `decide REVIEW --decisions FILE|- --reviewer NAME [--write] [--plan-sha256 HEX]`.
  - A blank reviewer raises `REVIEW_INVALID_BATCH`. `--write` without `--plan-sha256` raises `REVIEW_CARDS_PLAN_REQUIRED`.
  - Read `max_note_chars` and the batch cap from `load_campaign_review_config(root)`.
  - Add dispatch in `run()`. Emit codes and data per contracts/cards-cli.md.
  - Text rendering: one line per card, the supersede lines, the refused cards, and the `plan <sha>` line with the exact `--write --plan-sha256` command.
- [ ] T020 [US1] Make T011 pass. Run the US1 tests and the Phase 2 tests, and record the counts in `validation.md`.

**Checkpoint**: the MVP. A page-shaped decisions file is applied with no hand-built batch (SC-001).

---

## Phase 4: User Story 2 — nothing a page sends can record what CampaignGenerator cannot prove (P1)

**Goal**: every whole-file and per-card refusal in research R7, each proven to leave the store untouched.

**Independent Test**: each bad input against a fixture packet gives the refusal code, and `sha_tree` is unchanged.

- [ ] T021 [US2] In `tests/test_summary_native_review_cards.py`, write these tests. Each whole-file test asserts the code, the exit code and that `sha_tree(review dir)` is unchanged:
  - `test_us2_s1_unknown_packet_refused`;
  - `test_us2_s2_review_id_mismatch_refused`;
  - `test_us2_s3_unknown_card_named`, where `data.cards` lists every unknown id;
  - `test_us2_s4_stale_generation_refused_with_export_remedy`, run after a real `review refresh`, with exit 3 and the message naming `review cards export`;
  - `test_us2_s5_signoff_draft_changed_refuses_that_card_only`: edit the draft. The sign-off card is listed as refused with `REVIEW_NPC_SIGNOFF_STALE`, naming the draft, and the other cards still record;
  - `test_us2_s5_signoff_echo_missing_or_different_refused` gives `REVIEW_CARDS_FINGERPRINT_MISMATCH`, whole file;
  - `test_us2_s6_packet_has_no_verdict_and_unmarked_records_nothing`: assert recursively that no key in the packet is named `verdict`, `guess`, `decision` or `recommendation`. A file with an empty `cards` writes nothing;
  - `test_us2_s7_disallowed_pair_refused_on_every_path`. The store is the gate, so it covers `review decide`, `review npc sign` and `cards decide`. For `cards decide`, monkeypatch `DISPOSITION_FOR` to a wrong pair and assert `REVIEW_ACTION_MISMATCH`;
  - `test_us2_member_echo_mismatch_refused`;
  - `test_us2_altered_packet_refused`: edit one byte of the stored packet;
  - `test_us2_member_item_moved_refused_per_card`: stage a new item revision via `store.append_review_items`, or hand-write the item revision, and assert `REVIEW_CARDS_MEMBER_STALE`;
  - `test_us2_custody_stale_refused_per_card`: touch an evidence file of one NPC. That NPC's finding card is refused with the spec 042 detail, and another NPC's card records;
  - `test_us2_schema_version_refused` (`schemaVersion: 2`, message names `[1]`);
  - `test_us2_extra_key_refused`;
  - `test_us2_unsaved_page_refused` (`savedAt` empty).
- [ ] T022 [US2] Fix any gaps T021 exposes in `cards.plan_decide` and `parse_decisions`. No new behaviour beyond research R7.

**Checkpoint**: SC-002 holds for every bad input.

---

## Phase 5: User Story 3 — re-saving keeps every mark and shows every change (P2)

**Goal**: diff and supersede semantics (R5).

**Independent Test**: apply twice, which gives no changes. Change one verdict and re-apply, which gives exactly that card's members as supersedes.

- [ ] T023 [US3] In `tests/test_summary_native_review_cards.py`, write these tests:
  - `test_us3_s1_reapply_is_noop`: write, re-plan, `counts.noop == previous record count`; `--write` gives `saved == []`. The event count is unchanged (SC-003).
  - `test_us3_s2_changed_verdict_supersedes_and_keeps_history`: approve, then change the file to reject and re-apply. Exactly that card's members are listed as `supersede`, with `previous.verdict == "approve"`. The new events carry `supersedes_event`, and both events remain on disk.
  - `test_us3_s3_cli_decision_after_export_is_diffed`: a `review decide` with the same verdict and disposition but a different note gives `supersede`. With an identical verdict, disposition and `card_note` text it gives `noop`.
  - `test_us3_discuss_then_approve_supersedes`.
  - `test_us3_later_packet_same_verdict_is_noop`: export a second packet after some decisions, and apply the same verdicts. They are `noop`, with no spurious supersede, because the note carries no packet id (R5).
- [ ] T024 [US3] Fix any gaps T023 exposes in `cards.expand` and `plan_decide` (the note comparison and the supersede revision).

---

## Phase 6: User Story 4 — the contract is tested (P2, CampaignGenerator side)

**Goal**: schemas, golden fixtures, version refusal and plain-text carriage (R11). The kit-side half of US4 is T037–T040.

**Independent Test**: a deliberate model change that is not reflected in the schema fails a test.

- [ ] T025 [P] [US4] Create the golden fixtures in `tests/fixtures/review_cards/`:
  - `packet.v1.json`, a packet exported from a **deterministic** `_custody_fixture` build. Replace machine-specific absolute paths with relative ones if any appear; if the packet holds any, fix `build_packet` to carry campaign-relative paths only.
  - `decisions.v1.json` (approve, reject, discuss, and a sign-off with an echo).
  - `decisions.bad-version.json` and `decisions.extra-key.json`.
- [ ] T026 [US4] Write `tests/test_summary_native_review_cards_contract.py`:
  - `test_us4_s1_goldens_validate_and_round_trip`: `jsonschema.validate` each golden against the checked-in schema, and assert that model parse then dump (by alias, canonical) equals the golden's canonical bytes.
  - `test_us4_s1_every_exported_packet_validates`: export from `_custody_fixture` and from the noise review, then validate.
  - `test_schemas_are_current`: regenerate via `cards.model_json_schema` into tmp and compare with the checked-in files. This is SC-005's tripwire, and its failure message is `run cards.write_schemas()`.
  - `test_us4_s2_unknown_major_version_refused_naming_accepted`.
  - `test_us4_s3_markup_carried_as_text`: put `<script>alert(1)</script>` and `<b>x</b>` into a fixture NPC's draft and claim text. The exported packet contains those exact characters, unescaped and unaltered, in `body`, and the schema's `body` description says plain text.
  - `test_golden_packet_matches_fresh_export`: a fresh deterministic export equals `packet.v1.json`, so the golden cannot rot.
- [ ] T027 [US4] Add `assert "cards.py" in names  # spec 043` to `test_review_package_makes_no_model_call` in `tests/test_summary_native_no_llm.py`.

---

## Phase 7: User Story 6 — export and apply from the web app (P3)

**Goal**: two routes and a "Card packet" fieldset, including the GM-ruled filter inputs (contracts/cards-routes-and-launcher.md).

**Independent Test**: a Vitest component test drives export, plan and confirm, plus a refusal. Route tests assert the exact argv.

- [ ] T028 [P] [US6] Extend `tests/test_summary_native_review_routes.py`. Using the existing `route_app` recorder fixture, assert:
  - `POST /{id}/cards/export` with `{"items":["a"],"actions":["review_presentation"]}` gives argv `review cards export ID --item a --action review_presentation --campaign-dir ROOT --json`;
  - `POST /{id}/cards/decide` with write false or true gives the argv in the contract;
  - `decisions_path` outside the campaign, or missing, is refused before any CLI run;
  - the status mapping for each new code in the contract table, using the `_refusing` helper;
  - `extra="forbid"` on both bodies.
- [ ] T029 [US6] In `server/routers/review_routes.py`, add `CardsExportRequest` and `CardsDecideRequest` (`StrictRequest`) and the two routes, built through `_command` and `_run`. Add `REVIEW_CARDS_PACKET_UNKNOWN: 404` and `REVIEW_CARDS_PLAN_CHANGED: 409` to `_EXACT_STATUS`. Make T028 pass.
- [ ] T030 [P] [US6] Extend `frontend/src/components/ReviewLauncher.test.ts` with the `reply()` and `fetch` stub pattern:
  - `exports a card packet with filters`: enter item ids and actions, click "Export card packet", and assert the request body `{items, actions}` and that the packet id and counts are shown.
  - `plans then confirms with the plan hash`: "Confirm and record" is disabled before Plan. After Plan the grouped plan is shown, and Confirm sends `write:true, plan_sha256:<shown>`.
  - `editing the path resets confirm`.
  - `shows a refusal like the CLI`: a 409 `REVIEW_CARDS_PACKET_STALE` envelope shows its message in the note and its `data` in the result `<pre>` (US6 scenarios 1–3).
- [ ] T031 [US6] In `frontend/src/components/ReviewLauncher.vue`, add the "Card packet" fieldset per the contract:
  - item ids and action names inputs, split on commas or whitespace, with empty meaning no filter;
  - the Export button;
  - the decisions path and reviewer inputs;
  - Plan, and "Confirm and record", which is enabled only when a plan is shown and is reset when the path or reviewer changes.
  - The plan is rendered as grouped lists (Record, Supersede old → new, No change, Unmarked, Refused).
  - Use the existing `request()` helper.
  - Make T030 pass.
  - Run `npm test` and `npm run build` from `frontend/`.

---

## Phase 8: User Story 5 — one page kit for both agents (P3, mytools) and US4 kit half

**Goal**: the kit merge, the NPC shims and the retirement of the Codex fork (contracts/kit.md, R12). This is a separate mytools PR.

**Independent Test**: each Codex skill that used the fork builds and reads its page through the shared kit. `check-skill-sync.sh` and `test-codex-links.sh` pass. No kit file reads the store.

- [ ] T032 Create a mytools worktree, `git -C ~/src/mytools worktree add <scratch>/wt043-mytools -b 043-review-card-contract origin/main`, after confirming `origin/main` includes `5c5e5d5`. Never edit `~/src/mytools` itself. Never use `git stash`.
- [ ] T033 [US5] Move `dotfiles/claude/skills/_shared/review-artifact/` to the canonical `dotfiles/shared/skills/_shared/review-artifact/` with `git mv`. Create symlinks `dotfiles/claude/skills/_shared/review-artifact` and `dotfiles/codex/skills/_shared/review-artifact` pointing to it, using the relative-path style of existing `shared/skills` links.
  - Update `dotfiles/skill-layout.json`: drop `_shared/review-artifact` from `claude_only`, and drop `_shared/review-page` from `codex_only`.
  - Run `bash dotfiles/check-skill-sync.sh` and `bash dotfiles/tests/test-codex-links.sh`.
  - If the layout checker cannot express a shared `_shared/` directory, make the **smallest** change to `check-skill-layout.py` that does, with a test. If that is not small, fall back to a real directory in `claude/skills/_shared/` plus a Codex-side link (R12), and record which in the PR body.
- [ ] T034 [US5] Merge the Codex save surface into `shared/.../review-artifact/build_review.py` as `--save artifact|local`, defaulting to `artifact`.
  - `local` reproduces `codex/skills/_shared/review-page/build_review.py`'s save controls exactly: Copy output, a Save output download using `outputName`, Save to VM via `PUT ./decisions` when `<meta name="codex-review-save" content="enabled">` is present, and an export that includes `unmarked`.
  - `artifact` output must be **byte-identical** to before. Add a test comparing it with a page built by the pre-change script from a fixed items file.
- [ ] T035 [US5] Merge Codex's `read_decisions.py --in decisions.json` mode and its `normalize()` into the shared `read_decisions.py`, keeping `--html`. Move `codex/.../review-page/serve_review.py` to the shared kit, importing `normalize` from the shared `read_decisions`. Its behaviour, including the bind default, is unchanged. Move `tests/test_review_server.py` over, and it must pass unchanged apart from import paths.
- [ ] T036 [US5] Repoint every Codex consumer from `_shared/review-page` to `_shared/review-artifact`, adding `--save local` to their `build_review.py` calls. That is each `codex/skills/*/SKILL.md` listed in research R12, plus:
  - `codex/skills/dialogue-edit/references/review-and-apply.md`;
  - `codex/skills/dialogue-edit/tests/test_review_edits.py:206`;
  - `codex/skills/vtt-spell-pass/render_review.py:18`;
  - `codex/skills/_shared/batch-chapters/batch.py:46` (`RP`) and `BATCH.md`;
  - the `paired` entries in `skill-layout.json`.

  Then `git rm -r dotfiles/codex/skills/_shared/review-page`. Check that `grep -rn "review-page" dotfiles/` returns nothing, apart from `CLAUDE_CODEX_CONVERGENCE.md`, which is updated in T041.
- [ ] T037 [US4] [US5] Rewrite `npc_review_items.py` as the shim in contracts/kit.md.
  - It runs `summary_native review cards export REVIEW --campaign-dir DIR [--item]… [--action]… --out TMP --json` through `subprocess`, resolving `summary_native` with `shutil.which` and failing clearly if it is absent.
  - It maps each card to a kit item: `id`, `t` = title, `y` = approveMeans, `n` = rejectMeans, `ev` = body plus evidence. Every string goes through `html.escape`. `members` and `draftSha256` pass through, `group` is set for noise class cards, and `reviewId = packetId`.
  - It keeps the existing CLI flags, mapping `--ids` and `--ids-file` to `--item`. It drops `--allow-stale` and `--undecided` (now always), with a clear error if they are passed.
  - It deletes `load_review`, `current_decisions` and all store-file reads.
- [ ] T038 [US4] [US5] In the shared `read_decisions.py`, add `--npc --html SAVED --review REVIEW --out FILE`. It writes a CampaignGenerator decisions file (contracts/card-files.md):
  - `packetId` comes from the page `reviewId`, and `savedAt` from the state.
  - The per-card `members` and `draftSha256` come **from the saved page's `ITEMS`**.
  - Notes are copied, and unmarked cards are omitted.
  - `pick` and extra verdicts are refused (NPC pages have none).

  Delete the class-card expansion (`:164-218`) and the `classes` output. Update `test_read_decisions.py` accordingly.
- [ ] T039 [US4] [US5] Add kit tests in `shared/.../review-artifact/tests/test_npc_shim.py`. Run them against a real CampaignGenerator fixture review, built by importing `tests._custody_fixture` from `PYTHONPATH=<wt043>`, and skip with a reason if CampaignGenerator is not importable. Cover:
  - the shim's cards equal the packet's;
  - `<script>` in campaign text arrives escaped in the built page;
  - `members` and `draftSha256` reach the page `ITEMS`;
  - a page saved with two verdicts gives, through `read_decisions --npc` and then `summary_native review cards decide`, a plan with the expected records;
  - **static**: no `.py` in the kit contains `manifest.json`, `"items"` path joins, `events/` or `docs/reviews` (SC-006).
- [ ] T040 [US5] Merge the two `CONTRACT.md` files into one shared `CONTRACT.md`. It has a "Save transports" section (artifact and local) and an NPC section that points to CampaignGenerator `specs/043-review-card-contract/contracts/card-files.md` and the two commands. It deletes the hand-translation instructions (`review decide` / `review npc sign` keyed by card id).
- [ ] T041 [US5] Update `dotfiles/CLAUDE_CODEX_CONVERGENCE.md:39-40` to say both agents use `_shared/review-artifact`, with Codex using `--save local`. Update `claude/skills/summary-native-npc-delta/SKILL.md`, its Codex twin and `references/review-and-apply.md`: the NPC review loop is `npc_review_items.py`, then page, then `read_decisions.py --npc`, then `review cards decide` (plan), then GM confirmation, then `--write --plan-sha256`. Update `claude/skills/_shared/batch-chapters/BATCH.md:600-604`'s test command path.
- [ ] T042 [US5] Run every kit test (`~/.venv/bin/python -m pytest dotfiles/shared/skills/_shared/review-artifact/tests`), both dialogue-edit test suites, the batch-chapters tests, `check-skill-sync.sh` and `test-codex-links.sh`. Record the results in CampaignGenerator `validation.md`. Commit on the mytools branch. Do not open the PR yet (T048).

---

## Phase 9: Polish & cross-cutting

- [ ] T043 [P] Update `docs/cli/summary_native_review.md`:
  - a new "Card packets" section covering `cards export` and `cards decide`, plan then `--write --plan-sha256`, every refusal code decoded, and re-saving (noop and supersede);
  - the #655 action table;
  - the page contract pointer.

  Fix the two lines that say the review-artifact kit reads the store (:256, :346). Add a row to the CLAUDE.md docs table only if a new doc file is created (none planned).
- [ ] T044 [P] Run `SC-007` scale: in `tests/test_summary_native_review_cards.py`, add `test_scale_800_items_export_and_decide_under_60s`, using `_custody_fixture.build(extra_npcs=…)` sized to about 800 items. The timing assertion is loose (< 60 s each), and wall times are recorded in `validation.md`.
- [ ] T045 Run the full Python suite and the frontend `npm test`, `npm run build` and `npm run test:e2e` (with `PLAYWRIGHT_CHROME_EXECUTABLE_PATH=/usr/bin/google-chrome`). Walk quickstart.md sections 1–7. Record everything in `validation.md`.
- [ ] T046 One code-review pass over the CampaignGenerator diff and the mytools diff (`/code-review`). Fix the confirmed findings, then re-run the affected suites.
- [ ] T047 File follow-up issues (GitHub MCP, `kostadis/CampaignGenerator`):
  - the third latest-decision copy in `cli._fresh_decision` and `store.review_status`, which does not check item revision or digest (research R3);
  - `#643` slice 2 linkage, a comment on #643 with what slice 1 shipped;
  - a comment on #655 when the PR lands.
- [ ] T048 Push both branches and open both PRs: CampaignGenerator `043-review-card-contract` to `main` (closes #655 and references #643), and mytools `043-review-card-contract` to `main`. Each PR names the other. **Do not merge** without the GM's explicit go-ahead.

---

## Dependencies & Execution Order

- **Setup (T001–T002)** comes first.
- **Foundational (T003–T010)** blocks everything. **T005 is a hard gate**: a failure stops the run and is reported to the GM.
- **US1 (T011–T020)** depends on Foundational and is the MVP.
- **US2 (T021–T022) and US3 (T023–T024)** depend on US1's `plan_decide`. They are independent of each other but edit the same test file, so run them sequentially.
- **US4 CampaignGenerator side (T025–T027)** depends on US1 (it needs export). It can run alongside US2 and US3, because it uses different files.
- **US6 (T028–T031)** depends on US1's CLI (T019). The route tests and the Vitest tests are [P] with each other.
- **US5 and the US4 kit side (T032–T042)** depend on US1 and US2. The shim needs `cards export`, and the reader's output must pass `cards decide`. They can run alongside US6.
- **Polish (T043–T048)** comes after everything.

## Parallel Opportunities

- T002 ∥ T001.
- T006 ∥ T007, and both ∥ T003/T004 (different files).
- T025 ∥ T021–T024 (fixtures versus test file).
- T028 ∥ T030 (Python route tests versus Vitest).
- The mytools track (T032–T042) ∥ US6 (T028–T031).
- T043 ∥ T044.

## Implementation Strategy

1. **MVP = Phases 1–3.** #655 is closed, and a GM's page decisions are applied with no hand translation. Stop and validate.
2. **Add US2 then US3.** The safety and re-save semantics. They are P1 and P2, but US2 is what makes throwaway pages safe, so it ships with the MVP in the same PR.
3. **US4 contract tests**, then **US6 face**, then **US5 mytools**.
4. **Orchestration.** Opus orchestrates; Sonnet subagents implement per phase. Opus reviews each phase's diff and test output before the next phase starts. One code-review pass at the end (T046). Every deferred gap becomes an issue (T047).
