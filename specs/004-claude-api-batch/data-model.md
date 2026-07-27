# Data Model: Claude API Batch Processing Option

**Feature**: 004-claude-api-batch | **Date**: 2026-07-27

No databases; all state is in-process or plain files (Constitution I). Three entities.

## BatchSubmission

One grouped set of Message requests handed to the Batches API by a single blocking `run_batch` call.

| Field | Type | Source | Notes |
|---|---|---|---|
| `batch_id` | str | API (`batches.create().id`) | Printed to stderr at submission (FR-013); the handle for poll/cancel and for manual cleanup after a hard kill |
| `requests` | list[dict] | `build_batch_request(...)` per unit | Each carries `custom_id` + `params` (model, max_tokens, system w/ optional cache breakpoint, messages) |
| `processing_status` | str | API (`batches.retrieve`) | `in_progress` → `canceling` → `ended`; blocking loop exits only on `ended` |
| `request_counts` | dict | API | `processing / succeeded / errored / canceled / expired` — progress line source (FR-007) |

**Lifecycle**: built → submitted (id reported) → polled (progress ticks) → ended → collected. Abort during polling ⇒ `cancel` attempted, outcome reported, non-zero exit (FR-009). Hard kill ⇒ remote batch continues unobserved; `batch_id` on the terminal/log is the recovery trail.

## BatchItem / BatchItemResult

One request within a submission = exactly one unit of pipeline work (one chunk, one scene, one file, or the whole prompt for single-call CLIs).

| Field | Type | Notes |
|---|---|---|
| `custom_id` | str | Deterministic unit key chosen by the caller (e.g. chunk stem, scene id). The **only** join key — results arrive in arbitrary order |
| `status` | str | `succeeded` / `errored` / `canceled` / `expired` |
| `text` | str \| None | Extracted response text on success — written to the same path the sequential run would write, atomically |
| `stop_reason` | str \| None | NEW field carried through `collect_batch`; `max_tokens` ⇒ loud truncation banner naming the custom_id (FR-010) |
| `error` | str \| None | Provider error payload summary for errored items (FR-008 per-item listing) |
| `usage` | dict \| None | Token usage, available for logging |

**Invariant (FR-004)**: `custom_id → output path` mapping is owned by the caller and identical to the sequential loop's iteration order mapping; a downstream consumer cannot distinguish transports.

**Failure semantics (FR-008)**: successful items' files are written; failed items are listed by `custom_id` + status + error; process exits non-zero if any item is not `succeeded`. Skip-if-exists runs **before** request building, so a re-run submits only the missing units.

## Sidecar record (`*.batch.json`) — existing, grandfathered

Written/read by `write_batch_sidecar` / `read_batch_sidecar` for the pre-existing detached mode (`scene_extract` / `enhance_summary` `--submit-only` / `--collect`). Fields: `batch_id`, submission timestamp (`utc_now_iso`), unit→custom_id mapping. **Unchanged by this feature**; plain `--batch` (block-and-poll) does not require a sidecar, though writing one remains harmless and keeps in-flight state discoverable on disk (Constitution VIII).

## State transitions (blocking mode)

```
build requests (missing units only)
        │ submit_batch
        ▼
SUBMITTED ── stderr: "Batch submitted: <id> (<n> requests)"
        │ poll (interval, progress ticks)
        ├── SIGINT/SIGTERM ──► cancel attempted ──► report ──► exit ≠ 0
        ▼
ENDED
        │ collect_batch (keyed by custom_id)
        ▼
per-item: succeeded ─► atomic write to sequential path (+ truncation banner if stop_reason=max_tokens)
          errored/canceled/expired ─► listed individually
        │
        ▼
exit 0 iff every item succeeded
```
