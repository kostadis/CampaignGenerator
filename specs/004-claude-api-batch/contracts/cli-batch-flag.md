# Contract: Uniform `--batch` CLI Parameter

**Feature**: 004-claude-api-batch | Applies to every CLI that registers backend selection via `campaignlib.api.client.add_backend_args`, plus `facts_to_state` (hand-rolled vocabulary copy).

## Flag

```
--batch    Process Claude API calls through the Message Batches API
           (50% token cost, asynchronous). The command blocks and polls
           until the batch completes. Anthropic backend only.
           Not related to `ensemble_batch` (local multi-chapter dispatch).
```

- `store_true`, default `False`. Omitted ⇒ behavior byte-identical to today (FR-011).
- Registered by `add_backend_args()` so spelling, help text, and default are identical across all CLIs (FR-002).
- Grandfathered extras: `scene_extract` and `enhance_summary` keep their pre-existing `--submit-only` / `--collect` (require `--batch`); **no other CLI grows detached-mode flags** (FR-012).

## Validation (fail fast — FR-003)

`client_from_args` rejects `--batch` with any resolved backend other than `anthropic` — including a backend selected via the `CG_BACKEND` env var — **before** constructing a client or dispatching any work:

```
error: --batch requires the Claude API backend (--backend anthropic);
backend '<x>' has no batch support
```

Exit code ≠ 0, no tokens spent.

## Required output lines (stderr)

| Event | Line shape |
|---|---|
| Submission (FR-013) | `Batch submitted: <batch_id> (<n> requests)` |
| Progress tick (FR-007) | `[batch <id>] processing: <p> succeeded: <s> errored: <e> (elapsed <t>s)` |
| Truncation (FR-010) | The existing `!!!` banner from `stream_api`'s max_tokens warning, prefixed with the item's `custom_id` |
| Abort (FR-009) | `Abort received — requesting batch cancellation… status: <canceling|failed: reason>` |
| Per-item failure (FR-008) | One line per non-succeeded item: `FAILED <custom_id>: <status> <error summary>` |

## Exit codes

| Condition | Exit |
|---|---|
| All items succeeded | 0 |
| Any item errored / canceled / expired | ≠ 0 (successful items' outputs are still written) |
| `--batch` with non-anthropic backend | ≠ 0 (before any work) |
| Aborted (SIGINT/SIGTERM) during wait | ≠ 0 after cancellation attempt |

## Grouping semantics per CLI (FR-006)

| CLI group | Unit = one batch item | Notes |
|---|---|---|
| `planning` / `party` / `distill` / `campaign_state` (extract fan-out) | chunk (via `run_extract_pipeline`) | Missing-chunk set computed before submission |
| `scene_extract` | scene | Existing behavior, now with blocking `--batch` default path |
| `scrub_mechanics` | narration file (glob) | |
| `query` | map-phase chunk | Reduce call is a one-item batch |
| Single-call CLIs (`sd_plan`, `sd_consistency`, `check_consistency`, `vtt_voice_compare`, `transform`, `npc_table`, `make_tracking`, `enhance_summary`, `dnd_sheet`, `scabard_sync`, `synthesise_world_state`, `synthesise_polish`, synthesis stages of grounding CLIs) | the single call | One-item batch, discount still applies |
| `prep`, `sd_narrate` | each call, sequentially | Order-dependent chains (5-call prep sequence; `sd_narrate` handoff/prev-voice threading) must not be grouped — sequential one-item batches; help text says so |
| `facts_to_state` | its per-unit calls, anthropic backend only | Hand-rolled parser kept in sync with registrar wording |

## Out of contract

- `server/backend_forwarding.py` and all `_build_*_cmd()` router builders: unchanged (UI out of scope; comment added referencing spec 004).
- dgx/openrouter/claude-code backends: never accept `--batch`.
