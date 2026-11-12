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
