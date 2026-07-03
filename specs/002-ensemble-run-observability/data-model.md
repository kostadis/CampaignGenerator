# Phase 1 Data Model: Ensemble Run Observability

This feature adds no database and no persistent schema beyond a file. The "data" is (a) the **Run record** persisted to disk and (b) the **SSE stream protocol** the run emits. Both are described here.

## Entity: Run record (persisted)

One file per run, written under `<campaign>/logs/<YYYY-MM-DD_HHMMSS>_<script>.md` by `subprocess_runner._save_run_log`. It is the durable, CLI/Claude-visible truth of "what happened" (Principle VIII).

| Field | Type | Source | Notes |
|---|---|---|---|
| `command` | string (multiline) | the launched `cmd` + non-secret env prefix | Secret-free (R4). The reproducible invocation. |
| `result` | enum: `succeeded` \| `failed` \| `aborted` | derived from returncode | `0` → succeeded; positive non-zero → failed; negative (signal) → aborted (R5). |
| `returncode` | int \| null | `proc.returncode` | Raw exit code (incl. negative signal codes). |
| `duration` | float (seconds) | `time.monotonic()` delta | Wall time from launch to exit/abort. |
| `cwd` | string (path) | `Path.cwd()` | The campaign workspace the run targeted. |
| `output` | string (multiline) | full captured stdout/stderr | Not truncated (FR-007, R6). |
| `timestamp` | datetime | filename + body header | When the run started. |

**Lifecycle**: created exactly once, when the run reaches a terminal state (natural exit, explicit abort, or disconnect-abort). There is no update-in-place; a re-run writes a new timestamped file.

**Validation / invariants**:
- MUST NOT contain any API key or secret value, in `command` or `output` (SC-002). Guaranteed because secrets are inherited env, never on the command line or echoed.
- MUST be written on *every* terminal path, including abort (enforced via the `finally` in `stream_subprocess`).
- `result` MUST distinguish all three outcomes (SC-004).

## Entity: Cache unit (existing, hardened)

Not new, but its write contract is tightened by FR-014. A *cache unit* is any artifact whose mere existence the resume/skip logic trusts to mean "this work is done":

| Cache unit | Trusted-by | Write site (to make atomic) |
|---|---|---|
| `docs/ensemble/per_chapter/<stem>/merged.json` | `ensemble_batch.py` `merged.exists()` skip check | the extract/merge worker that produces `workdir/merged.json` |
| `docs/ensemble/state_dossiers/<type>_<slug>.md` | `facts_to_state.py` `dossier_path(...).exists()` | `facts_to_state.py:write_dossier` |

**Invariant (new, FR-014)**: a cache unit MUST be published to its trusted path **atomically** (temp file in the same directory, then `os.replace`). At no instant may a partially-written file exist at the trusted path. An interrupted unit leaves at most a discardable temp file and is recomputed on re-run.

## Entity: Run stream (transient, SSE)

The live protocol between a `/api/ensemble/run/*` endpoint and the browser. See `contracts/run-stream.md` for the wire format. Logical states observed by the frontend `useEnsembleRun`:

```
idle ──run()──▶ running ──┬── done(rc=0) ────────▶ done
                          ├── done(rc>0) ────────▶ error
                          ├── done(aborted|rc<0) ▶ aborted
                          └── abort()/disconnect ▶ aborted   (client closes stream;
                                                              server group-kills in finally)
```

| Field (frontend state) | Type | Notes |
|---|---|---|
| `command` | string | populated from the `command` SSE event (R4); copyable. |
| `output` | string | accumulated `data` chunks. |
| `status` | `idle`\|`running`\|`done`\|`error`\|`aborted` | adds `aborted` to today's set. |
| `returnCode` | int \| null | from the `done` event when present. |

**Transitions of note**:
- `abort()` is only valid from `running`; it closes the `EventSource` and sets `status=aborted` without waiting for a `done` event (the server may already be gone).
- A precondition failure (empty selection, etc.) arrives as a `data` line + a non-zero `done` with an `error` field (existing `sse_error_stream`), landing in `error` with a readable reason (FR-011) — never silent.
