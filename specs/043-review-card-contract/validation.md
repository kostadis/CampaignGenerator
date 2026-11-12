# Validation log: 043 review card contract

## T001 baseline (unmodified branch, base 27cad6b)

`PYTHONPATH=<worktree> ~/.venv/bin/python -c "import pipelines; print(pipelines.__file__)"` prints the worktree path.

| File | Result |
|---|---|
| tests/test_summary_native_review_decisions.py | 9 passed |
| tests/test_summary_native_review_delegated.py | 11 passed |
| tests/test_summary_native_review_noise_cli.py | 14 passed |
| tests/test_summary_native_review_routes.py | 33 passed |
| tests/test_summary_native_review_item_custody.py | 26 passed |
| tests/test_summary_native_no_llm.py | 34 passed |
| **Total** | **127 passed** |

## T005 gate (full suite after T004) — FAILED, STOPPED, not marked done

`tests/ -q`: 17 failed, 9866 passed, 388 skipped, 31 errors in 18m10s. After fixing an unrelated-to-R4
packaging mistake of mine (a directory `force-include` of `review/schemas` duplicated `.gitkeep` and
broke every `uv build` wheel test; removed), 32 tests remain (16 failed, 16 errors). All 32 pass on
baseline 27cad6b, so all are caused by T004's fail-closed rule (`no decisions are declared for action X`).

Actions involved (neither is produced by any pipeline code; grep of pipelines/ and server/ finds neither):

- `accept_no_change_or_correct` — the default `proposed_action` of the test item helpers in
  test_summary_native_review_{decisions,delegated,refresh,http}.py (pairs recorded: approve/accept_no_change,
  plus approve/merge-style pairs in findings_547). Test artifact.
- `correct_reviewed_layer` — test_summary_native_review_corrections.py:182 (pair approve/source_correction). Test artifact.

Per R4 the table was not widened and no test was edited. Awaiting a GM ruling.

### T005 resolution (GM ruling 2026-11-12: repoint test fixtures)

Fixtures repointed to actions the pipelines produce: `accept_no_change_or_correct` ->
`review_claim_against_evidence` (tests/test_summary_native_review_{decisions,delegated,refresh,http}.py and
frontend/e2e/summary-native-review.spec.ts:105); `correct_reviewed_layer` -> `prepare_claim_source_correction`
(tests/test_summary_native_review_corrections.py:182). store.py and the R4 table untouched. No other occurrences.

- The five Python test files: 48 passed.
- Full suite `tests/ -q`: **9914 passed, 388 skipped, 0 failed** (17m52s).
- e2e spec: not run (frontend/node_modules absent in the worktree).

T005 is complete.

## Phase 2 (T006-T010)

Run with the pinned PYTHONPATH: action_table, delegated (13), noise_cli (14), decisions, cards (6), no_llm (34),
installable_wheel, review_installation, promotion_wheel: **115 passed** together. `uv build --wheel` ships both
schema files via `packages` (no force-include needed).

Notes: (1) T008/T009 were written implementation-first in one pass, so the test was not observed failing first.
(2) cards.py imports `delegated` lazily inside `expand`; delegated imports `cards` lazily inside `plan_noise_class`
(avoids a cycle). (3) `expand`'s `snapshot` is the `read_review_state` tuple. (4) plan_noise_class passes an empty
placeholder note to `expand` (identical/differs are both "already decided") and builds its own note, so output is unchanged.

## Phase 3 (T011-T020)

T011: the US1 tests were written first and run against the Phase 2 code. `-k us1` gave **13 failed, 6 deselected**
(no `cards export`/`decide` subcommand, no `build_packet`/`load_packet`/`parse_decisions`/`pack_batches`).

T012-T019 implemented; T020: after implementation `tests/test_summary_native_review_cards.py` = **19 passed** (13 US1 +
6 Phase 2). Phase 2 + US1 suites together, pinned PYTHONPATH:
action_table + delegated + noise_cli + decisions + cards + no_llm + routes + item_custody = **169 passed**.

Deviations and conservative choices (see the Phase 3 report):
1. `REVIEW_CARDS_PLAN_CHANGED` exits 5 as contracts/cards-cli.md says, which needed a one-line exception in
   `cli._exit_for` (the code contains none of STALE/BLOCK/CONFLICT).
2. `REVIEW_CARDS_ACTION_UNKNOWN` (new): an undecided item whose action has no `DISPOSITION_FOR` row refuses the
   export instead of being silently left out or carded with no way to decide it.
3. `parse_decisions` measures `max_note_chars` against the STORED note (`card_note` prefix included), so a file
   that passes parsing cannot later fail the store's limit.
4. A non-signoff card that echoes a `draftSha256` is refused with `REVIEW_CARDS_FINGERPRINT_MISMATCH` (the file
   rule is "required iff signoff").
5. Refused cards carry `members: []` in the plan; `counts.refused` counts the packet card's members.

## Phase 4 (T021-T022)

T021: 15 US2 tests added (`-k us2`). Written after the Phase 3 implementation, so 14 passed on first run; 1 failed:
`test_us2_s5_signoff_draft_changed_refuses_that_card_only` (the refusal message was the blocker's bare
"draft bytes changed" and did not name the draft, which US2 s5 requires).

T022 fixes (cards.py only): (1) the stale-sign-off refusal message now appends the draft path and carries
`draftPath` in its data; (2) orchestrator-requested: a refused card (sign-off stale, member moved, custody
stale) lists its packet members as `{itemId, category: "refused", disposition: null, previous: null,
decision: null}` instead of `[]`; `PlannedMember.category` gained `refused` (data-model.md updated);
`counts.refused` is still the member count; (3) the `REVIEW_CARDS_SCHEMA` message now reads `accepted: [1]`.
`REVIEW_CARDS_ACTION_UNKNOWN` untouched.

Run (pinned PYTHONPATH): cards + action_table + delegated + noise_cli + decisions + no_llm + item_custody =
**151 passed** (cards file alone: 34 passed).

Notes: `test_us2_member_item_moved_refused_per_card` presents the moved item by monkeypatching
`store.read_review_state`, because `append_review_items` bumps the generation, which refuses the whole packet
(`REVIEW_CARDS_PACKET_STALE`) before any per-member check can run; a member can therefore only move per-card in
the same generation through a hand-written store edit.

## Phase 5 (T023-T024) and GM rulings of 2026-11-12

T023: the five US3 tests were written against the Phase 3 code. All five passed once three bugs in the tests
themselves were fixed (the first run's failures: `saved` is per batch, and event files sort by id, not by
decision revision); no code gap was exposed, so T024 changed no `expand`/`plan_decide` logic.

GM rulings: (1) `REVIEW_CARDS_ACTION_UNKNOWN` kept (contracts/cards-cli.md, research R7;
`test_export_refuses_unknown_action`). (2) A re-offered Discuss shows `Previously discussed by <reviewer>: <note>`
in `previousDiscussion` for finding and sign-off cards (in `body` per occurrence for noise class cards) so a sign-off `body` stays byte-identical to the draft (data-model Card, research R2; `test_reoffered_discuss_card_shows_previous_note`, `test_signoff_body_is_exact_draft_even_when_previously_discussed`).

Run (pinned PYTHONPATH, basetemp pytest-043b): cards + action_table + delegated + noise_cli + decisions + no_llm +
item_custody = **158 passed** (cards file alone: 41 passed).

## Phase 6 (T025-T027), verbatim fix and launcher check

Determinism: `tests/_custody_fixture.build(..., deterministic=True)` patches `uuid.uuid4` to a counter for the
duration of the build (the campaign id and review id are the only random inputs to item digests and the packet
id), so two builds in different temp dirs give a byte-identical packet. No absolute path appears in the packet;
`build_packet` needed no change. Goldens in `tests/fixtures/review_cards/` (`packet.v1.json`, `decisions.v1.json`,
`decisions.bad-version.json`, `decisions.extra-key.json`); the schema `body` and `previousDiscussion` descriptions say plain text.

Launcher: `ReviewLauncher.vue` read the plan correctly except that an unmarked card has `members: []` (the
Unmarked list now shows the card id only); Vitest fixtures are now a trimmed real `review cards decide --json`
envelope (state `applied`, refused members category `refused`, `saved` a list of `{request_id, events}`).

Counts (pinned PYTHONPATH, basetemp pytest-043): cards 42, cards_contract 6, action_table 21, delegated 13,
noise_cli 14, decisions 9, no_llm 34, item_custody 26, routes 47 = **212 passed**. Frontend: `npm test` 67 passed, `npm run build` clean.

## Polish T043-T044

T043: `docs/cli/summary_native_review.md` gains "Card packets" (export, plan then `--write --plan-sha256`, every
refusal code, noop/supersede, `previousDiscussion`, skipped sign-offs, `REVIEW_CARDS_ACTION_UNKNOWN`, the #655 action
table, the page-contract pointer); the two lines that said the kit reads the store now say it goes through
`review cards export|decide`. `docs/web/web_ui.md` has no review launcher section, so nothing was added there.
Command examples in the doc are real output from the custody fixture (`deterministic=True`).

T044 (SC-007): `test_scale_800_items_export_and_decide_under_60s`, custody fixture with `extra_npcs=796`: 802 items,
802 cards (sign-offs, one member each), mixed approve/reject/discuss, notes on every 7th. No scale marker exists in
tests/ (only `parametrize`), so the test is unmarked; it takes about 43 s including the fixture build.

| Step | Wall time |
|---|---|
| export | 1.2 s |
| decide (dry run, plan) | 2.6 s |
| decide `--write` (9 batches of up to 100) | 26.7 s |

Well inside the 60 s bound, but `--write` is over 20 s, so it was profiled (cProfile, 50 s under the profiler).
Hot spot: the cost is per batch, not per decision. Each of the 9 transactions re-reads the whole review snapshot
(about 2400 YAML documents parsed and pydantic-validated, roughly 11 s of the profile) and rewrites the authority
ledger (`authority.py` `yaml.safe_dump`, about 0.9 s per transaction, 8 s in all). Not optimised; a larger batch size
or caching the snapshot between batches would be the lever, if ever needed.
