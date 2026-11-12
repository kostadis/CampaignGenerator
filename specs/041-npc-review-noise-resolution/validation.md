# Validation log: 041 NPC review noise resolution

## Environment

- CG worktree: `/tmp/claude-1000/-home-kostadis-src-CampaignGenerator/a3bc2de0-8755-4531-8838-80b08f58bcdb/scratchpad/wt621`, branch `041-npc-review-noise-resolution`
- MT worktree: `/tmp/claude-1000/-home-kostadis-src-CampaignGenerator/a3bc2de0-8755-4531-8838-80b08f58bcdb/scratchpad/mt041`, branch `041-noise-class-cards`, from mytools `origin/main` at `61157ae`
- Python: `~/.venv/bin/python` (the server venv). `~/.venvs/main` has no pytest.
- Every CG test command runs with `PYTHONPATH=<CG worktree>`.

## T001 — import path and baseline (2026-11-12)

- `import pipelines` resolves to `wt621/pipelines/__init__.py` ✅
- Baseline: `test_summary_native_review_verification_adapter.py`, `test_summary_native_npc_verify.py`, `test_summary_native_review_delegated.py`, `test_summary_native_review_http.py` and `test_summary_native_no_llm.py` → **86 passed**

## T002 — MT worktree and kit baseline

- `git worktree add -b 041-noise-class-cards … origin/main` (`61157ae`) ✅
- `dotfiles/claude/skills/_shared/review-artifact/tests` → **22 passed**

## Phase 2 (T003–T011) — foundation

- Sonnet implementer; reviewed by the orchestrator.
- Orchestrator changes on review:
  - `status_synonyms.yaml` made strict. Dropped `lost`, `gone`, `live` and `lives`. `killed`/`slain` are no longer supported by `died`/`dead`, because they assert an agent (attribution).
  - Added "a second later", "for a second" and "just a second" to `ordinal_idioms.yaml`.
  - Research R3a: draft-side bare "one" is not examined.
- One existing test was adjusted: `test_adapter_preserves_every_diagnostic_and_maps_all_seven_categories` now excludes `CLASSIFIED_NOISE`, because noise items arrive in US1. US1 must restore full coverage.
- Result: 125 passed across noise, no_llm, review_verification_adapter, review_foundation, npc_verify, review_delegated and review_http.

## Phase 7 (T030–T034) — kit class cards (MT)

- MT commit `e353246` on `041-noise-class-cards`.
- Orchestrator change on review: each member's note carries the provenance prefix `GM class verdict on batch card [<card id>] (<k> occurrences)[: note]`, so CG's decision history shows a class verdict, not an apparently individual ruling. CONTRACT.md and the tests were updated to match.
- `build_review.py` is unchanged. Non-noise cards are regression-tested as identical.
- Kit tests: 32 passed (baseline 22).
