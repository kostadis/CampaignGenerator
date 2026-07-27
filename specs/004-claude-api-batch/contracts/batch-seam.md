# Contract: `campaignlib.api.batch` Seam

**Feature**: 004-claude-api-batch. All Message Batches traffic flows through this module (Constitution V). CLIs and `campaignlib/pipelines.py` call these functions; **no caller touches `client.messages.batches.*` directly**.

## Existing functions (unchanged signatures)

| Function | Contract |
|---|---|
| `build_batch_request(*, custom_id, system, user, model, max_tokens=8192, cache_system=False) -> dict` | Mirrors `stream_api`'s request shape (system blocks incl. optional `cache_control: ephemeral` breakpoint, single user message). The **only** place batch request payloads are built. |
| `submit_batch(client, requests) -> str` | `client.messages.batches.create(requests=...)`; returns batch id. |
| `poll_batch(client, batch_id, *, interval=10, on_tick=None, max_wait=None)` | Retrieve-loop until `processing_status == "ended"`; transient errors retried via `_is_retryable`. |
| `collect_batch(client, batch_id) -> dict[str, dict]` | Iterates `batches.results`; keyed by `custom_id`. **Extended**: each entry gains `stop_reason` (from the succeeded item's message). |
| `write_batch_sidecar` / `read_batch_sidecar` | Unchanged; detached-mode support for the two grandfathered CLIs. |

## New: `run_batch`

```python
def run_batch(client, requests, *, label="", poll_interval=10,
              on_tick=None) -> dict[str, dict]
```

Blocking submit → poll → collect composition (FR-012). Behavior contract:

1. **Submission line** to stderr immediately after `submit_batch`: `Batch submitted: <id> (<n> requests)` (FR-013).
2. **Signal handling**: for the duration of the poll loop, SIGINT and SIGTERM trigger a best-effort `client.messages.batches.cancel(batch_id)`, a stderr report of the outcome, and a non-zero exit (FR-009). Handlers are restored on return. SIGTERM support is required because the web UI abort path (spec 002) delivers graceful SIGTERM before force-kill.
3. **Progress** via `on_tick` default: `request_counts`-based stderr line each interval (FR-007).
4. **Truncation banner**: after collection, every item with `stop_reason == "max_tokens"` emits the same `!!!` banner as `stream_api`'s ceiling warning, naming the `custom_id` (FR-010). Does not raise.
5. **Returns all items** (succeeded and failed); never raises on per-item failure — the caller owns unit↔file mapping, writes successes, lists failures, and sets the exit code (FR-008).
6. Raises only on transport-level failure of submit/poll/collect after the seam's standard retries.

## New: pipeline batch mode

```python
run_extract_pipeline(..., batch: bool = False)
```

When `batch=True` (and only reachable with a real Anthropic client — validated upstream by `client_from_args`, FR-003):

- Missing-unit set computed with the existing skip-if-exists check **before** request building (Constitution VII; re-runs submit only what's absent).
- One `build_batch_request` per missing unit; one `run_batch` call per pipeline invocation (FR-006).
- Each successful result written to the identical per-unit path via the atomic write helper (tmp + `os.replace`) (FR-004 + torn-write edge case).
- Synthesize stage unchanged (single call; may independently run as a one-item batch at the CLI's discretion).

## Atomic write helper

`_atomic_write_text` is promoted from `pipelines/ensemble/extract_facts.py` into `campaignlib` (single definition; ensemble module re-imports it). Contract: content is fully written to a same-directory temp file and `os.replace`d — a reader (or a killed process) never observes a partial file.

## CI guardrails (part of this contract)

- `tests/test_retrieve_render_isolation.py`: `run_batch` (and the pipeline batch wrapper if separately named) are added to the render-call list — a function body containing both a retrieval call and a batch entry point must fail CI (Constitution III).
- `tests/test_backend_seam_guardrails.py`: asserts `--batch` present in registrar output, `facts_to_state` parser in sync, and `client_from_args` rejection for each non-anthropic backend and for `CG_BACKEND`-driven selection.
- No module outside `campaignlib/api/` may reference `messages.batches` (grep-level guardrail test).
