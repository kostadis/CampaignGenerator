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
