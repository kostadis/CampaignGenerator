# Validation: Source-Custody Rebase (T036)

Date: 2026-11-09. Branch `040-source-custody-rebase`. `CG_BACKEND` unset (an exported `CG_BACKEND=claude-code`
makes 6 unrelated batch-flag tests fail, so the suite was run without it).

## Backend (Python)

The suite has 426 test files. `pytest-xdist` is not installed and one process exceeds the tool timeout, so the
files were split into three contiguous shards run one after another (command per shard:
`python -m pytest $(cat shard_N) -q -p no:cacheprovider`).

| Shard | Result |
|---|---|
| 0 (`tests/test_a*` .. first third) | 2990 passed, 366 skipped, 15 failed (all pre-existing, below) before the fix; after it, 14 (the 15th was `rebase_propose`, fixed) |
| 1 | 3060 passed, 8 skipped, 0 failed |
| 2 | 3523 passed, 1 skipped, 6 failed (pre-existing, below) |

After the fix, `tests/test_backend_seam_guardrails.py`, `tests/test_delta_no_llm_in_records.py`,
`tests/test_retrieve_render_isolation.py` and every `tests/test_rebase_*.py` were re-run together:
only the nine known seam failures remain.

### Failure attributable to this branch (fixed)

`tests/test_backend_seam_guardrails.py::test_no_out_of_seam_make_client[pipelines/summary_native/delta/rebase_propose.py]`:
`rebase_propose.py` called `make_client` directly. It now builds its client with
`campaignlib.api.client.client_from_args`, and `tests/test_rebase_us1.py` patches that name. 14/14 pass.

### Pre-existing failures (also fail at base fbb15dc)

- `tests/test_codex_cli_family.py`: 5 (`test_direct_inventory_contains_27_model_bearing_commands`,
  `test_direct_command_has_model_option_with_omission_default[pipelines/npc_agent/agent.py]`,
  `test_direct_command_adopts_shared_model_resolver[pipelines/summary_native/delta/cli.py]`,
  `test_direct_hand_written_backend_choice_has_canonical_codex_once`,
  `test_hand_written_surfaces_consume_shared_reasoning_registrar[pipelines/summary_native/delta/cli.py]`).
- `tests/test_backend_seam_guardrails.py`: 9 (`test_production_backend_surface_inventory_is_exact`;
  `test_no_out_of_seam_make_client[...delta/associations.py | census.py | grounding_check.py | grounding_edits.py]`;
  `test_model_flag_implies_backend_args[...delta/cli.py]`; `test_all_31_codex_surfaces_share_reasoning_effort_registration`;
  `test_all_31_claude_code_surfaces_share_effort_registration`; `test_all_31_claude_code_surfaces_share_thinking_registration`).
- `tests/test_setup_routes.py`: 6 (`test_party_config_is_forwarded`, `test_no_output_location_is_sent_when_the_operator_set_none`,
  `test_blank_output_fields_are_not_forwarded`, `test_an_explicit_output_is_still_forwarded`,
  `test_output_dir_is_forwarded_for_multiple_pdfs`, `test_omitting_party_config_leaves_the_flag_off`):
  503 "config service not initialized"; verified failing at base (6 failed, 1 passed). Not in the brief's known list.

Totals across shards: 9573 passed, 375 skipped, 20 failed, all 20 pre-existing at base.

## Frontend

`cd frontend && npm test`: 9 files, 61 tests passed. `npm run build` (vue-tsc + vite): succeeded.

## T035

`custody_store`, `rebase_inspect`, `rebase_impact`, `rebase`, `rebind` and `cli_rebase` are in the AST no-LLM map in
`tests/test_delta_no_llm_in_records.py`; `rebase_propose` is allowed only for `propose`.
`tests/test_retrieve_render_isolation.py` passes.
