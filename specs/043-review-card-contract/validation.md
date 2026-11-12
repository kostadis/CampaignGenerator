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
