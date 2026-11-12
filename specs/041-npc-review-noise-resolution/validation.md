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

## T035 — baseline oracle inspection (read-only, `~/storm-giant/stormgiants`)

Review `docs/reviews/npc-review-6ee694eebf5b`:
- `items/<item_id>/<rev>.json`: take the highest revision. Each item carries `locator.source_path` (the draft), `display_line`, `claim_text` (**the exact draft line**), `diagnostics[0].legacy_code`, and `input_bindings[]` (draft and evidence path + `custody_sha256`).
- Codes in the review: `number-inconsistency` 323, `ordinal-inconsistency` 88, `status-claim-unsupported` 41, `typography-normalised` 158, `placeholder-speaker` 7, `npc-draft-signoff-required` 164.
- **GM noise oracle**: `requests/gm-number-noise-*-{0,100,200,300}.json` → `result.events[].item_id`, **335** number/ordinal items ruled noise. So 411 − 335 = **76** number/ordinal items are GM-confirmed true positives. `requests/gm-status-synonym-*.json` → **16** status items ruled synonym noise, out of 41.
- `sources/<gen>.json` stores **hashes only** (path, sha256, size), not bytes.

Byte availability: of the 309 bound draft/evidence files, **290 match** their custody sha256 today. **19 differ** (16 drafts, 3 evidence: `npc_bob_saget`, `npc_delsephine`, `npc_methrammar_aerasumé`). No commit in the stormgiants history has their custody bytes; they were edited between review creation and commit. They are unrecoverable.

Replay method for T036:
1. **Item replay (exact)**: for each of the 411 number/ordinal items, classify `claim_text` (the exact line) against the bound evidence file. The evidence is exact unless it is one of the 3 changed files, which are reported separately and excluded from pass/fail. Line-level SC-004: every one of the 76 true-positive items still yields ≥ 1 GM-facing finding. Report how many of the 335 noise items still yield one.
2. **Full current-draft replay (approximate)**: run the number and status checks over every current draft in `docs/npcs/summary_native/ch001-086/draft/` against its current evidence, and count GM-facing number/ordinal findings (SC-001 ≤ 100). This catches findings on lines the old checker never flagged, such as newly examined spelled numbers. The 16 changed drafts are noted as approximate.
3. Status (SC-002): for each of the 16 synonym-noise items, classify the item's line with the status classifier against its evidence. It must yield 0 status findings.

## Phase 3–4 (T012–T018) — US1 and US2, the number check

- Sonnet implementer; reviewed by the orchestrator.
- Orchestrator fix on review: a sentence whose citations all fail to resolve (0 or more than 1 occurrence) now examines **nothing**. The implementer had still recorded label and idiom noise for such sentences. The old checker skipped them, and the line already carries its own citation finding, so recording noise there would put noise items in front of the GM for lines that never produced a finding.
- Existing tests changed, both because the enum gained `CLASSIFIED_NOISE`: `test_lossless_adapter_retains_every_legacy_code_and_all_seven_categories` and `test_adapter_preserves_every_diagnostic_and_maps_all_seven_categories` now each add one cited label line, so the fixture produces a noise item and **full category coverage is restored**, with no exclusion.
- Probe check: "40" in neither cited scene gives one finding naming both scenes; "200" in one of two gives `other-citation`; "Chapter 12" gives `label`; "first time" gives `idiom`; an uncited line gives nothing; bare "one" is skipped. Accounting: 4 = 1 finding + 3 noise.
- Affected suites (noise, adapter, review_verification, scoped_verification, no_llm, foundation, delegated, http, npc_verify, rerun): all pass.
- **Failures already on main, not caused by this branch:**
  - `tests/test_backend_seam_guardrails.py`: 9 failed on main `e6c13a9` and the same 9 on this branch.
  - `tests/test_codex_cli_family.py::test_direct_inventory_contains_27_model_bearing_commands` also fails on main.
  - Both concern `delta/` code this feature does not touch.
