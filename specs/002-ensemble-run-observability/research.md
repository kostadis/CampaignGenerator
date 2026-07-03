# Phase 0 Research: Ensemble Run Observability

All Technical Context unknowns are resolved below. Each item: Decision / Rationale / Alternatives considered.

## R1 — How does an abort (or disconnect) actually terminate the run, including child workers?

**Decision**: Launch every run subprocess in its **own session/process group** (`asyncio.create_subprocess_exec(..., start_new_session=True)`). On abort, signal the **whole group**: `os.killpg(pgid, SIGTERM)`, wait up to a grace window (~3–5 s) for exit, then `os.killpg(pgid, SIGKILL)` if still alive. Detect both explicit abort and client disconnect at the *same* place: the streaming async generator in `stream_subprocess`. When the client connection drops, Starlette/uvicorn cancels the response task, raising `asyncio.CancelledError`/`GeneratorExit` inside the generator; a `try/finally` around the read loop runs the group-kill, the log write, and the lock release on every exit path.

**Rationale**: `ensemble_batch.py` fans out child workers (`ThreadPoolExecutor` → `subprocess.run(ensemble_extract…)`). Killing only the top process orphans those workers, which keep running and keep spending tokens — exactly the FR-013 harm. Process-group kill is the only reliable way to stop the whole tree. Doing termination in the generator's `finally` unifies explicit abort and disconnect into one mechanism (matches the clarification: disconnect = implicit abort = same graceful-then-force path).

**Alternatives considered**:
- *Kill only the parent PID* — rejected: orphans the extract workers (token + correctness leak).
- *Poll `await request.is_disconnected()` in a side task* — workable but redundant once the generator already receives cancellation; adds a second code path. Kept the single `finally` path.
- *`proc.terminate()` then `proc.kill()` on the parent only* — rejected for the same orphan reason as group-kill is required.

## R2 — Transport for explicit abort, given `EventSource` is GET-only

**Decision**: **Explicit abort = the client closes the stream connection** (`EventSource.close()` in `useEnsembleRun.abort()`), which the server observes as a disconnect and handles via the R1 `finally` termination. The UI sets its own status to `aborted` locally (it initiated the close, so it knows). No separate abort endpoint and no server-side run-id registry are required.

**Rationale**: Minimal surface, one termination mechanism, and it's identical to the disconnect path the spec already mandates (FR-013) — so explicit abort and "closed the tab" are guaranteed to behave the same. Keeps the existing `EventSource` transport and the `_RUNNING` per-stage lock unchanged (the lock is released in the same `finally`).

**Alternatives considered**:
- *Separate `POST /run/abort` + in-process `{run_id: proc}` registry* — more moving parts (id generation, id propagation to the client via an early SSE event, registry lifecycle, races between abort and natural completion). Rejected as unnecessary for a single-operator local server when closing the connection already terminates the run. (Revisit only if multi-client or programmatic abort is ever needed.)
- *Switch to `fetch` + `ReadableStream` + `AbortController`* — gives an explicit client-side abort handle, but means replacing the shared `connectSSE`/`EventSource` helper. Deferred: the close-connection approach achieves the same result without the rewrite.

## R3 — Are per-unit cache writes atomic today? (FR-014)

**Decision**: No — make them atomic with a **temp-file-then-`os.replace`** idiom at every *cache-trust* write site, via one shared helper (`campaignlib.atomic_write_text` / `atomic_write_json`). Concrete sites:
- The per-chapter `merged.json` written by the extract/merge worker (the file `ensemble_batch.py` trusts by `merged.exists()` at line ~162 to skip a chapter).
- `facts_to_state.py:write_dossier` (line ~361), trusted by `dossier_path(...).exists()` at the resume check (line ~493).

`os.replace` is atomic on the same filesystem (POSIX rename), so a force-kill can leave at most a discardable temp file, never a half-written file at the trusted path. Write temp in the **same directory** as the destination to guarantee same-filesystem rename.

**Rationale**: The resume/skip logic trusts *existence* of the destination file, not its integrity. A non-atomic `write_text` interrupted by SIGKILL yields a truncated-but-present file that the next run treats as complete → silent corruption downstream (a Principle I/IV precision failure). Atomic publish makes the integrity guarantee structural rather than timing-dependent (the clarified Q3 = Option A).

**Alternatives considered**:
- *Validate each cached file on resume (parse-check)* — rejected as the primary fix: it's per-format, easy to under-implement, and still races. Atomic publish is simpler and format-agnostic. (A cheap `json.loads` sanity check may be added opportunistically but is not the guarantee.)
- *Write a `.done` sentinel beside each output* — extra files, extra bookkeeping; `os.replace` achieves the same with the real artifact.

## R4 — Reproducible command form & secret-safety (FR-002, FR-003, SC-002)

**Decision**: Reuse the existing command echo, but emit it as a **distinct SSE `command` event** (not just an inline `$ …` data chunk) so the UI can render a dedicated copy-to-clipboard box. The command string keeps the existing form: any non-secret env prefix (`CG_BACKEND=…`, `DGX_ENDPOINT=…`, `OPENROUTER_MODEL=…`, `DGX_MODEL=…`) followed by the full `python … script.py --flags`. **Secrets are already absent**: `_llm_env` never injects API keys — `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` are inherited from the server's environment, so they never appear on the command line. The persisted log (`_save_run_log`) records the same secret-free command.

**Rationale**: "Reproducible" per the spec means runnable by an operator whose own environment supplies the credentials (spec Assumption). The env prefix shown is exactly what an operator pastes in front of the command in their workspace shell; the API key comes from their environment, just as it does for the server. A distinct event (vs. parsing the first `$ ` line out of the output) keeps the copyable command robust and unambiguous.

**Alternatives considered**:
- *Keep the inline `$ …` line only* — works but forces the UI to string-parse output to find the command; brittle and not cleanly copyable. Rejected.
- *Echo the resolved absolute interpreter path vs. `python`* — keep `python_exe()` (already used) so the copied command matches what actually ran; acceptable since the operator runs in the same workspace/venv.

## R5 — Distinguishing aborted from failed in the result (FR-006, FR-009)

**Decision**: A run terminated by group-kill exits with a **negative returncode** (e.g. `-15` SIGTERM, `-9` SIGKILL). The runner classifies this exit as `aborted` (not `failed`), records `result: aborted` in the persisted log, and — when the connection is still open at abort time (rare) — emits a `done` event carrying an `aborted` flag. On the common path (operator clicked Abort → connection closed), the **frontend** owns the `aborted` status because it initiated the close; the persisted log still records `aborted` from the negative returncode. Failure = the process exited on its own with a non-zero positive code; success = exit 0.

**Rationale**: Three outcomes must be distinguishable (SC-004). Signal-based negative returncodes cleanly separate "we stopped it" from "it failed." Persisting `aborted` keeps the on-disk record honest even though the UI may have already shown `aborted` from the close.

**Alternatives considered**:
- *Treat any non-zero as failure* — rejected: collapses aborted into failed, violating SC-004.

## R6 — Long-output readability & persistence (Edge Case, FR-007)

**Decision**: Keep streaming into the existing `StreamOutput.vue` `<pre>` (already `overflow-y:auto`, scrollable, `white-space:pre-wrap`). The full output is captured server-side and written to `<campaign>/logs/<ts>_<script>.md` by `_save_run_log` regardless of how the run ended (now also on the abort `finally` path). No truncation of the persisted record.

**Rationale**: The component already satisfies the "remain readable / scrollable" requirement; the only change is ensuring the log write happens on the abort path too (folded into R1's `finally`).

**Alternatives considered**: virtualized log viewer / ring buffer — unnecessary at single-operator scale; deferred.

## Cross-cutting note — what does NOT change

No stage's computation changes (spec Assumption). No new LLM call, no retrieval/render mixing, no new external dependency, no DB. The `/grounding` (Anthropic) path and non-ensemble run routes are untouched because the changes live in the *shared* runner and the ensemble-specific frontend/engine files.
