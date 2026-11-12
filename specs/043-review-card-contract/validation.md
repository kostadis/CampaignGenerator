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
