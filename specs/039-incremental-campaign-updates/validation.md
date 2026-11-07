# Validation: 039 quickstart on the synthetic fixture (T091)

Run date: 2026-11-07. Branch `039-incremental-campaign-updates`, uncommitted working tree.
All runs use the synthetic fixtures (`tests/fixtures/delta/`, `tests/support/delta_grounding_fixture.py`). No private campaign data.

| Quickstart step | Result | Evidence |
|---|---|---|
| 1. Full suite green, full-mode golden unchanged | PASS | `python -m pytest tests/`: 9361 passed, 328 skipped, 6 failed. The 6 failures (`test_backend_seam_guardrails.py` x4, `test_codex_cli_family.py` x2) fail identically on the pre-change baseline. `tests/fixtures/delta/golden/verify_full.md` sha256 `728022ec…6d77` was captured from the unmodified `npc_verify.py` (sha256 `6abdd18c…1bed`) and is unchanged; the golden test also passes against HEAD's `npc_verify.py` in a detached worktree. |
| 2. One new chapter is the only parsed input (SC-001) | PASS | `test_delta_grounding_e2e.py::test_quickstart_step_2_*`, `test_delta_sources.py` (`parsed_new == 1`, `parsed_historical == 0`, model calls 0) |
| 3. Empty selection refuses (X) | PASS | `test_delta_plan.py`, `test_delta_cli_us1.py`, `test_delta_parity.py` (CLI exit 2, HTTP 400, no plan file) |
| 4. Baseline binding and drift (FR-002/003) | PASS | `test_delta_grounding_e2e.py::test_quickstart_step_4_*`, `test_delta_baseline.py` (adoption writes a new record; history digests unchanged) |
| 5. Grounding edit reconstruction (SC-002) | PASS | `test_delta_grounding_edits.py`, `test_delta_grounding_e2e.py::test_quickstart_step_5_*` |
| 6. NPC changed/new/mention/mixed horizon (SC-004) | PASS | `test_delta_census.py::test_fixture_dispositions`, `test_delta_npc_e2e.py`, `test_delta_attest.py` |
| 7. Freshness scope (SC-005) | PASS | `test_delta_freshness.py`, `test_delta_fix_round.py::test_3_*`, `::test_t1_*`, `test_delta_review_binding.py` |
| 8. Failure injection and resume (SC-006) | PASS | `test_delta_run_resume.py` (nine boundaries), `test_delta_partial_outcome.py`, `test_delta_grounding_recovery.py`, `test_delta_batch_invariance.py` |
| 9. Real Chapter 75 replay (SC-003) | NOT RUN | Manual acceptance (T093); requires private campaign data in a worktree. |
| 10. Secrets canaries (SC-007) | PASS | `test_delta_secrets.py` (canary `CANARY-SECRET-7f3a` absent from prompts, drafts, verify reports, run records, receipts; player audience refused before reads) |
| 11. Parity and restart (SC-008, FR-023) | PASS | `test_delta_parity.py`, `test_delta_restart.py`; frontend `npm test` 53 passed, `npm run build` OK |
| 12. Inherited grounding delta (SC-009) | PASS | `test_delta_grounding_e2e.py::test_quickstart_steps_2_4_5_12_*`, `::test_quickstart_step_12_*`, `::test_real_promotion_path_publishes_the_delta`, `::test_second_delta_resolves_chapter_one_through_the_chain_*` |

Delta suite: `python -m pytest tests/test_delta_*.py tests/test_no_anthropic_in_delta.py tests/test_verifier_golden_full.py tests/test_retrieve_render_isolation.py` gives 807 passed, 23 skipped.

Remaining problems after the single review pass are filed as GitHub issues #597, #598, #599, #600, #601.
