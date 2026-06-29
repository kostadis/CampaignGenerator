# Quickstart / Validation: Ensemble Run Observability

Runnable scenarios that prove the feature works end-to-end. Each maps to a user
story and its success criteria. Implementation details live in `tasks.md`; this is
the validation guide.

## Prerequisites

- A campaign workspace with chapter files (e.g. `docs/chapters/chapter_*.md`).
- The web UI running: from the campaign workspace, `./startup` (builds the frontend
  and starts the FastAPI server), then open the `/ensemble` page.
- For a metered backend test (optional): `OPENROUTER_API_KEY` set in the **server**
  environment (never passed through the UI).
- Contracts: see [`contracts/run-stream.md`](./contracts/run-stream.md). Data model:
  see [`data-model.md`](./data-model.md).

## Scenario A — See and reuse the exact command (US1 / FR-001–003, SC-001/002)

1. On the `/ensemble` page, select one or more chapters and click **Run extraction**.
2. **Expect**: a dedicated, copyable **command box** appears showing the full
   invocation (env prefix + `python …/ensemble_batch.py --chapters … --model …`).
3. Copy it, open a terminal in the campaign workspace, paste, and run.
4. **Expect**: it runs the same operation with no hand-editing (SC-001).
5. Inspect the command box and the live output for any API key.
   **Expect**: none present (SC-002). With an OpenRouter backend, the command shows
   `CG_BACKEND=openrouter OPENROUTER_MODEL=…` but **no** `OPENROUTER_API_KEY`.

## Scenario B — Watch progress live (US2 / FR-004/005, SC-003)

1. Run the extraction over several chapters.
2. **Expect**: output lines appear **while the run is still going** (chapter-by-chapter
   `[extract+merge] <stem>` / `[skip] <stem>` lines), not only at the end (SC-003).
3. **Expect**: the page clearly shows a "running" state (button shows `Running…`).

## Scenario C — Know it finished + durable record (US3 / FR-006/007/011, SC-004/006)

1. Let an extraction run to completion.
2. **Expect**: an unambiguous **success** state (e.g. "Done", exit 0) plus the final
   output (SC-004).
3. Force a failure (e.g. point a stage at a missing input) and run.
   **Expect**: an unambiguous **failure** state distinct from success, with the error
   output shown.
4. Run a stage with **no chapters selected**.
   **Expect**: a readable refusal ("No chapters selected …"), not a blank/generic
   error (FR-011).
5. Look under `<campaign>/logs/` for the newest `*_ensemble_batch.md` (or relevant
   script) file. **Expect**: it contains the command, full output, returncode, and
   duration — recoverable after closing the browser (SC-006).

## Scenario D — Abort a run (US4 / FR-008/009/010/013, SC-005)

1. Start an extraction over **many** chapters (long enough to interrupt).
2. After a chapter or two completes, click **Abort**.
3. **Expect**: the run stops within a few seconds; the page shows an **aborted** state
   distinct from success and failure; output captured so far stays visible (SC-005,
   FR-009).
4. Verify no orphaned workers: `pgrep -af ensemble_extract` (or `ps`) shows **nothing**
   still running for this campaign (FR-013 / process-group kill).
5. Re-run the same extraction.
   **Expect**: already-completed chapters are **skipped** (`[skip] <stem>`), only the
   interrupted/remaining chapters run (FR-010).
6. Inspect the per-chapter dir of the chapter that was mid-flight when you aborted.
   **Expect**: either a complete `merged.json` or none — never a truncated one
   (FR-014). The newest `logs/` entry records `result: aborted` (R5).

## Scenario E — Disconnect = implicit abort (FR-013)

1. Start a long extraction.
2. **Close the browser tab** (or navigate away) mid-run.
3. From a terminal: `pgrep -af ensemble_batch` and `pgrep -af ensemble_extract`.
   **Expect**: within a few seconds, **nothing** for this campaign keeps running — the
   server treated the disconnect as an abort and group-killed the tree. No metered
   run continues unobserved.

## Regression checks (must stay green)

- `python -m pytest tests/` — including existing `tests/test_ensemble_*.py` and
  `tests/test_retrieve_render_isolation.py` (the router/runner add no retrieval/render
  mixing).
- The `/grounding` (Anthropic) page still runs and streams unchanged.
- New: `tests/test_subprocess_abort.py` — group-kill, grace→force timing, atomic
  cache write (no truncated file on kill), lock release on abort, no secret in the
  persisted record.
