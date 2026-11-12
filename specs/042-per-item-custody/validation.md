# Validation: 042 per-item custody

## T001 — baseline (unmodified branch, `PYTHONPATH=<worktree>`; `pipelines.__file__` resolves inside the worktree)

| File | Passed |
|---|---|
| tests/test_summary_native_review_decisions.py | 9 |
| tests/test_summary_native_review_delegated.py | 10 |
| tests/test_summary_native_review_routes.py | 31 |
| tests/test_summary_native_review_http.py | 6 |
| tests/test_summary_native_npc_publish.py | 31 |
| tests/test_delta_freshness.py | 6 |
| **Total (one run of all six)** | **93 passed** |

## T002 — stormgiants measurements (read-only; `npc-review-6ee694eebf5b`, custody generation 5)

- Sources by role: 164 draft / 164 evidence / 84 summary (412 in all).
- Items: 781; per NPC (per draft path) mean 4.76 (4.8), max 19 (`npc_bob_saget`).
- Evidence naming `docs/summaries/010-session-the-seer.md` (R5 `Source:` lines): 8 NPCs.
- Drift of the live checkout against generation 5: 10 files — 5 drafts, 1 summary, 4 evidence files
  (`055-session-the-return-to-silverymoon.md`; drafts helia, hyuth_kolstaag, lord_taern_hornblade,
  methrammar_aerasumé, rebecca_deakin; evidence blagothkus, bob_saget, delsephine, methrammar_aerasumé).

## Code review (one pass, `/code-review high`): 10 findings, all fixed in cc837d4

The 16 regression tests are in `tests/test_summary_native_custody_review_fixes.py`.

1. Refresh no longer preserves an item whose non-bound draft, evidence or summary dependency changed. A stale sign-off can no longer be laundered through `review refresh` into a publish.
2. `DiskProbe`, `plan_publish` and `publish` resolve the campaign root, so a relative directory no longer reports every file missing.
3. Findings coded `invalid`, `outside-evidence` or `not-found`, or whose verifier text cites the corpus, depend on all summaries. Sign-offs keep the evidence-named set: their verdict is a recorded pass checked against the draft sha.
4. Delegated multi-batch submissions are custody-checked as a whole before the first save.
5. and 6. Publish freshness uses `custody.stale_report` once per NPC, so a no-dependency sign-off is stale. A supplied seam's answer is final.
7. `review status` reads items and custody under one lock, and a symlinked path is reported as `unreadable`.
8. A binding that cannot be resolved widens the dependency set instead of being dropped.
9. The web refusal detail reports truncation.
10. `npc_evidence` is removed, and `with_overrides` is documented as a replay helper.

The replay after the fixes is unchanged: 781 items over 164 NPCs, all on `evidence_sources`. Changing the seer summary stales 58 items across 8 NPCs, with 0 false and 0 missed refusals. No real item carries a corpus-dependent code.

## T048: full suite

`PYTHONPATH=$WT ~/.venv/bin/python -m pytest tests/ -q --basetemp=$HOME/.cache/... --ignore=tests/test_backend_seam_guardrails.py --ignore=tests/test_codex_cli_family.py`
gives **9270 passed, 1 failed, 50 skipped**.

- The one failure is `test_summary_native_key_npcs.py::TestMissing::test_fallback_lines_are_built_by_code_from_checked_notes_alone`. It also fails on main, order-dependent, and is recorded on #644.
- The run before the fixes also hit the `test_summary_native_annotate.py` flake, which happens on main too (a run directory named to the second); recorded on #644.
- The stormgiants replay passed: 5 tests, read-only.
- Frontend: `npm test` passed 62 and `npm run build` succeeded (US2 phase).

Follow-up filed: #647, `counts.stale` and `stale_by_npc` can disagree until a refresh.
