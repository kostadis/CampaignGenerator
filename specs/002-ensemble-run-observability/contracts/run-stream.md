# Contract: Ensemble Run Stream + Abort

Applies to all streaming run endpoints under `GET /api/ensemble/run/*`
(`extract`, `bundle`, `synthesize`, `threads`, `recent-events`, `bundle-list`).
Transport: Server-Sent Events (`text/event-stream`) over an `EventSource`.

## Request

Unchanged from today: `GET /api/ensemble/run/<stage>?<params>`. Params carry the
explicit input selection and backend/model (Principle X / FR-012). No request body.

## Response: SSE event stream

Events are emitted in this order. **Bold** = new or changed by this feature.

| # | Event | `data` payload | Meaning |
|---|---|---|---|
| 1 | **`command`** | JSON string: the secret-free, copyable invocation (env prefix + `python … --flags`) | Emitted once, first. The reproducible command (US1, FR-001/002/003). |
| 2 | `data` (default) | JSON string: an output chunk | Live stdout/stderr as produced (US2, FR-004). May repeat many times. A precondition failure emits a single readable `data` line here (FR-011). |
| 3 | `done` | JSON `{ "returncode": N, "error"?: "...", **"aborted"?: true** }` | Terminal. `returncode==0` → success; `>0` → failure; **`aborted:true` or `returncode<0` → aborted** (FR-006/009, SC-004). |

Notes:
- The legacy inline `$ <cmd>` first **`data`** chunk MAY be retained for backward
  compatibility, but the authoritative copyable command is the **`command`** event.
- `done.error` carries the human-readable reason for a precondition refusal
  (e.g. "No chapters selected …"), surfaced to the operator verbatim (FR-011).

## Abort (FR-008) and disconnect (FR-013)

There is **no separate abort endpoint**. Abort is performed by the client
**closing the stream connection**:

1. Frontend `abort()` calls `EventSource.close()` and sets local `status = aborted`.
2. The server observes the dropped connection as a cancellation of the streaming
   generator.
3. In the generator's `finally`, the server terminates the run's **process group**:
   `SIGTERM` → wait grace window (~3–5 s) → `SIGKILL` if still alive (FR-008).
4. The same `finally` releases the per-stage `_RUNNING` lock and writes the durable
   run record with `result: aborted` (FR-007, FR-009).

A lost tab / navigation / network drop is identical to step 2 onward — it is an
**implicit abort** (FR-013). The operator never has an unobserved run still burning
tokens.

### Termination guarantees

- **Process-group kill**: child workers (e.g. `ensemble_batch.py`'s per-chapter
  `ensemble_extract` subprocesses) are launched in the run's session/process group
  and die with it. No orphaned token-spending workers.
- **Bounded stop**: force-kill after the grace window guarantees exit within a few
  seconds (SC-005).
- **Cache integrity**: any in-flight cache unit is published atomically
  (temp + `os.replace`), so an abort/force-kill never leaves a partial file the
  resume check trusts (FR-014). Completed units survive; the interrupted unit is
  recomputed on re-run (FR-010).

## Backward compatibility

- Non-ensemble run routes and the `/grounding` path are untouched. The
  termination/`command`-event changes live in the **shared** `subprocess_runner`,
  so other SSE routes inherit disconnect-driven cleanup for free, but their
  request/response shapes do not otherwise change.
- A client that ignores the `command` event still receives identical `data`/`done`
  events.
