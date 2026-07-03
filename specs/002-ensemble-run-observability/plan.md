# Implementation Plan: Ensemble Run Observability

**Branch**: `002-ensemble-run-observability` | **Date**: 2026-06-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-ensemble-run-observability/spec.md`

## Summary

Make an ensemble-stage run a first-class, observable, controllable thing in the `/ensemble` UI. The operator must (1) see the **exact, copyable, reproducible command** that ran (secrets omitted), (2) **watch its output stream live**, (3) get an **unambiguous finished/failed/aborted result** plus a durable on-disk record, and (4) **abort** a run — where abort is graceful-then-force, kills the whole worker process group, and a lost connection counts as an implicit abort.

Technical approach: the streaming/observability plumbing already exists in `server/subprocess_runner.py` and the `/api/ensemble/run/*` routes (command is echoed, stdout streamed, a per-run log written). The gaps are (a) **abort/disconnect termination** — `stream_subprocess` never watches for client disconnect and never terminates the child, and child *worker* processes (e.g. `ensemble_batch.py`'s `ThreadPoolExecutor` → `ensemble_extract.py`) are not in a killable group; (b) **a distinct copyable command surface** rather than an inline `$ …` line; (c) an explicit **aborted** state distinct from failure in the UI and the persisted record; and (d) **atomic per-unit cache writes** so a force-kill can never leave a truncated file the resume check trusts. All engine-side correctness work (process-group kill, atomic writes) lands in the CLI/seam layer; the router stays logic-free.

## Technical Context

**Language/Version**: Python 3.11+ (FastAPI backend, CLI engine); TypeScript / Vue 3 (frontend)

**Primary Dependencies**: FastAPI + Starlette `StreamingResponse` (SSE), `asyncio` subprocess, `os` process-group signals; Vue 3 + Pinia + Vue Router; browser `EventSource`. No new third-party dependency.

**Storage**: Files on disk only — per-run logs under `<campaign>/logs/`, cache artifacts under `docs/ensemble/` (`per_chapter/*/merged.json`, `state_dossiers/*.md`). No database.

**Testing**: `pytest` (`tests/`, alongside existing `test_ensemble_*.py`); new `tests/test_subprocess_abort.py` for termination/atomicity. Frontend: manual via `quickstart.md` (no FE test harness in repo).

**Target Platform**: Linux / WSL2, single local operator, no auth. Server is `uvicorn` behind the `startup` script.

**Project Type**: Web (FastAPI backend + Vue frontend) over a CLI engine — the established CG shape (Constitution Principle VI).

**Performance Goals**: Abort bounded to the graceful grace window + force-kill (~3–5 s, SC-005). Live output visible within a few seconds of being produced (SC-003). No new long-lived process or daemon.

**Constraints**: Must not change what each stage *computes* (spec Assumption). Must not break the existing `/grounding` (Anthropic) path or non-ensemble run routes — their request/response shapes are unchanged; they additionally gain disconnect-driven cleanup for free via the shared seam (I2 / Shared-seam blast radius). No secrets in the command, live output, or persisted record (SC-002). One run at a time per stage (existing `_RUNNING` lock).

**Scale/Scope**: One operator, one campaign at a time; a handful of stages; one in-flight run per stage. ~4 ensemble run endpoints already exist; this feature touches the shared runner + the frontend run composable, so it covers all of them uniformly (spec "Scope across stages").

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Verdict | Notes |
|---|---|---|
| I. Disk is Truth, Model is Draft | **PASS / reinforces** | The durable run record and atomic cache writes make disk the trustworthy truth; the index (resume check) can never be corrupted by a partial write. |
| II. Human Checkpoint | **PASS (N/A)** | No new LLM call; no precision decision is automated. Abort *adds* operator control. |
| III. Retrieval/Render Separated | **PASS** | No `retrieve`/`stream_api`/`call_api` added to any router or runner function. `tests/test_retrieve_render_isolation.py` stays green. |
| IV. Verbatim is Sacred | **PASS (N/A)** | No transcript/quote handling touched. |
| V. One Seam per Boundary | **PASS** | Process control lives in the one subprocess seam (`subprocess_runner.py`); LLM backend selection still flows through the existing `_llm_env` → `campaignlib` path. No new `import anthropic`. |
| VI. CLI is Engine, UI is a Face | **PASS / reinforces** | Engine correctness (process-group kill, atomic per-unit writes) lands in the CLI scripts + the shared runner, **not** reimplemented in the router or browser. The copyable command is literally the CLI invocation. |
| VII. Extract Once, Synthesize Deliberately | **PASS (N/A)** | Pass structure unchanged. |
| VIII. State is Discoverable | **PASS / reinforces** | A run's command, output, and outcome (incl. aborted) become a discoverable file under `logs/`, not browser-only state. This is the principle's exact intent. |
| IX. UI Mechanizes; Claude Converses | **PASS / reinforces** | The reproducible, copyable command is the escape hatch that lets the operator drop to the CLI and lose nothing — directly the anti-"walled garden" guarantee. |
| X. Selection is Explicit | **PASS** | The displayed command/record reflects the explicitly selected inputs (FR-012); the existing empty-selection refusal in `run_extract` is preserved. |

**Gate result: PASS.** No violations; several principles are actively reinforced. No entries in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/002-ensemble-run-observability/
├── plan.md              # This file
├── research.md          # Phase 0 — termination model, transport, atomicity, secret-safety
├── data-model.md        # Phase 1 — Run record + SSE event protocol entities
├── quickstart.md        # Phase 1 — runnable validation scenarios (US1–US4)
├── contracts/
│   └── run-stream.md     # SSE stream + abort contract for /api/ensemble/run/*
└── tasks.md             # Phase 2 (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
server/
├── subprocess_runner.py        # CHANGED: disconnect-aware termination; process-group
│                               #          launch; graceful→force kill; command event;
│                               #          aborted outcome in log + done event
└── routers/
    └── ensemble.py             # CHANGED: thread the run id / command event through
                                #          _run_locked; release lock on abort path

ensemble_batch.py               # CHANGED (FR-014): atomic per-chapter merged.json write
                                #          in the extract/merge worker path
facts_to_state.py               # CHANGED (FR-014): atomic write_dossier (temp + os.replace)
campaignlib.py                  # MAYBE: a shared atomic_write_text/atomic_write_json helper
                                #          (single home for the temp-then-rename idiom)

frontend/src/
├── api/sse.ts                  # CHANGED: surface a `command` event; expose abort (close)
├── views/ensemble/
│   ├── useEnsembleRun.ts        # CHANGED: track command + 'aborted' status; abort()
│   ├── EnsembleExtract.vue      # CHANGED: copyable command box + Abort button
│   ├── EnsembleBundle.vue       # CHANGED: same shared run controls
│   └── EnsembleSynthesize.vue   # CHANGED: same shared run controls
└── components/shared/
    ├── StreamOutput.vue         # reused as-is (scrollable long output, Edge Case)
    └── RunCommandBar.vue        # NEW (optional): command + status + abort, shared by stages

tests/
└── test_subprocess_abort.py    # NEW: group-kill, grace→force timing, atomic-write,
                                #      lock-release-on-abort, no-secret-in-record
```

**Structure Decision**: Web-over-CLI (the existing CG layout). Correctness changes are concentrated in the **one subprocess seam** (`subprocess_runner.py`) and the **CLI engine** (`ensemble_batch.py`, `facts_to_state.py`, optional `campaignlib.py` helper); the router and frontend only carry the new command/abort/aborted signals through. No new top-level modules or services.

## Complexity Tracking

> No constitution violations — section intentionally empty.
