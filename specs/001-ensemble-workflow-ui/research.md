# Phase 0 Research: Ensemble Grounding-Doc Workflow UI

All decisions below resolve the design unknowns implied by the spec and the Technical Context. The dominant constraint throughout is **Principle V (One Seam per Boundary)**: OpenRouter is a new external dependency and may be reached from exactly one place.

---

## R1 — How OpenRouter plugs into the existing LLM seam

**Decision**: Add an `"openrouter"` backend branch to `make_client()` in `campaignlib/api/client.py`, backed by an OpenRouter-aware client in `campaignlib/api/backends.py`. OpenRouter is OpenAI-wire-compatible, so the client reuses the `openai` SDK pointed at `https://openrouter.ai/api/v1`, but with two differences from the existing `_OpenAICompatClient`:
1. A **real API key** from `OPENROUTER_API_KEY` (the DGX client uses `api_key="not-needed"`).
2. **Model resolution does not go through the dgxlib registry** — OpenRouter model ids (e.g. `anthropic/claude-sonnet-4`, `meta-llama/llama-3.1-70b-instruct`) are passed through verbatim, and per-call request extras (timeouts, thinking) use sensible defaults instead of `dgxlib.resolve_model_config`.

**Rationale**:
- `campaignlib/api/backends.py:_OpenAICompatClient` (lines 150–185) hard-imports `dgxlib` and calls `resolve_model_config(self.model_override)`. dgxlib only knows Spark-served models, so OpenRouter ids would fail registry lookup. A separate branch keeps the DGX path unchanged while still living **inside the one seam** Principle V mandates.
- `make_client(endpoint, model_override, backend)` already has a `backend` parameter and a `$CG_BACKEND` env hook (`client.py:30–35`), and already precedes the endpoint/Anthropic branches. Adding `if backend == "openrouter":` is the minimal, idiomatic extension.
- Routing through `make_client` means `stream_api`/`call_api` (which already branch on client type for `thinking`/cache extras) and their retry logic are inherited for free.

**Alternatives considered**:
- *Reuse `_OpenAICompatClient` by passing `endpoint=https://openrouter.ai/api/v1`*: rejected — it would still call `dgxlib.resolve_model_config` on OpenRouter ids and use `api_key="not-needed"`. Bending it to OpenRouter would entangle the DGX path with vendor-specific behavior.
- *Add a new top-level module / `import openai` in the synthesis scripts*: rejected outright — a direct Constitution Principle V violation (a second place that crosses the LLM boundary).
- *Use the `anthropic` SDK against OpenRouter's Anthropic-compat shim*: rejected — OpenRouter's first-class surface is the OpenAI wire format already used here; the `openai` SDK is already a dependency.

---

## R2 — Where the OpenRouter credential and model list live

**Decision**: The API key comes from the `OPENROUTER_API_KEY` environment variable, mirroring how `ANTHROPIC_API_KEY` is handled today (CLAUDE.md: "`ANTHROPIC_API_KEY` must be set in the environment"). The server passes it through to subprocesses via `subprocess_runner`'s existing `env_extra` mechanism — it is never written to a tracked file. A small, editable list of suggested OpenRouter model ids is surfaced for the picker (alongside the existing `server/config.py:MODELS` Claude list and the DGX model id), but the operator may type any id.

**Rationale**: Secrets stay out of `config.yaml`/`ui_state.yaml` (both tracked). `.campaigngenerator.local.yaml` (gitignored) is an acceptable fallback for a machine-local key, but environment-variable parity with Anthropic is the least surprising. The model id is free-text because OpenRouter's catalog changes faster than any hard-coded list.

**Alternatives considered**:
- *Store the key in `ui_state.yaml`*: rejected — it is tracked; secrets must not be committed.
- *Fetch OpenRouter's live model catalog for the picker*: rejected for v1 — adds a network dependency at UI load (bad in Bear Valley) for marginal benefit; a static suggestion list plus free-text covers it.

---

## R3 — Backend selection surface across CLI stages

**Decision**: Introduce a uniform selection convention across the LLM-bearing scripts:
- **Synthesis scripts** (`synthesise_world_state.py`, `campaign_state.py`, `party.py`, `planning.py`) gain `--backend {anthropic,dgx,openrouter}` plus the already-conventional `--endpoint`/`--model`, and pass them into `make_client(...)`. They currently call `make_client()` with no args (Anthropic-only); default stays `anthropic` so existing invocations are byte-for-byte unchanged (FR-015).
- **Extraction/aggregation scripts** (`ensemble.py`, `ensemble_batch.py`, `ensemble_extract.py`, `facts_to_state.py`) already accept `--endpoints`/`--dgx-endpoint`/`--model`; selecting OpenRouter for them is achieved by pointing the endpoint at OpenRouter and relying on the R1 seam branch (driven by `--backend openrouter` or `CG_BACKEND=openrouter`, which `make_client` already reads).

**Rationale**: Honors Principle VI — the backend choice is a CLI capability first; the UI merely sets the flag. A single `--backend` vocabulary across scripts keeps the router's command-building uniform and the contract testable.

**Alternatives considered**:
- *Only support OpenRouter via env vars, no flags*: rejected — env-only selection is invisible state and harder to test per stage; the spec requires per-stage, run-time selection (FR-006, FR-018).
- *A single global backend setting for the whole run*: rejected — the clarified scope is **per-stage** choice (extract on one backend, synthesize on another).

---

## R4 — Stage-status discovery from disk

**Decision**: The router exposes read-only status endpoints that infer each stage's completion from artifact presence, reusing the pattern already in `grounding.py` (`/extracts`, `/extracts/{filename}`). Specifically: extraction complete ⇔ `docs/ensemble/per_chapter/*/merged.json` exist for the chapter glob; bundling complete ⇔ `docs/ensemble/state_dossiers/*.md` (and `merged_dossiers/*.md`) exist; synthesis complete ⇔ the relevant `*_draft.md` exist. No status is stored server-side or in the browser (Principles I/VIII, FR-002, FR-017).

**Rationale**: `facts_to_state.py` and `ensemble_batch.py` are already resumable by checking for these exact files, so "does the file exist?" is the same predicate the CLI uses — the UI and CLI cannot disagree. Reusing `grounding.py`'s file-listing endpoints minimizes new surface.

**Alternatives considered**:
- *A status manifest file the router writes*: rejected — introduces a second source of truth that can drift from the actual artifacts; the artifacts already are the state.

---

## R5 — Long-running extraction over SSE

**Decision**: Run each stage as a streamed subprocess via the existing `stream_subprocess()` (SSE `data:`/`event: done`), exactly as `grounding.py`/`session_workflow.py` do. Resumability comes from the CLI's existing per-chapter / per-entity skip-if-exists behavior; an interrupted run is restarted by re-invoking the same stage, which skips completed items. The doc's `tmux` guidance remains the recommended path for *very* long unattended runs; the UI targets attended runs and surfaces progress live.

**Rationale**: No new long-job infrastructure is needed — the CLI is already resumable and the SSE plumbing already exists. This keeps the UI a thin face (Principle VI).

**Alternatives considered**:
- *A background job queue / persistent worker*: rejected for v1 — over-engineered for a single local operator; adds a daemon (a recurring tax the constitution warns against) for a workflow that is already resumable on disk.

---

## R6 — Synthesis-capability warning

**Decision**: The UI warns (does not block) when a backend/model chosen for the **synthesis** stage is below the assumed capability bar (a model at least as capable as Sonnet). The signal is heuristic: a curated "synthesis-capable" allow-list (the Claude `MODELS` and a small set of frontier OpenRouter ids) versus everything else (local 3B/80B open models, which the workflow doc records as unable to synthesize). Extraction has no such warning — weak open models are expected and fine there.

**Rationale**: Encodes the user's explicit statement that the workflow "assumes a model at least as powerful as Sonnet," and the doc's calibration finding that `Qwen3-Next-80B` "cannot handle synthesis." A warning, not a block, respects operator agency (it is their experiment to run).

**Alternatives considered**:
- *Hard block on sub-Sonnet synthesis*: rejected — contradicts the local-hardware exploration goal; the operator may deliberately want to calibrate a weak model on synthesis.

---

## R7 — Keeping the existing Anthropic workflow untouched

**Decision**: The new ensemble page is a separate route tree (`/ensemble`) and a separate router (`/api/ensemble`); `GroundingDocs.vue` and `grounding.py` are not modified. The synthesis scripts default `--backend anthropic`, so the old `/grounding` invocations produce identical commands and identical results (FR-015, SC-006).

**Rationale**: The user requires the old path preserved "until I decide to retire it." Physical separation at both router and view layers is the simplest guarantee against regression.

**Alternatives considered**:
- *Add an ensemble mode/tab inside `GroundingDocs.vue`*: rejected per the clarification (a new separate page was chosen), and because co-locating raises the risk of touching the old path.

---

## Summary of decisions

| # | Decision | Primary principle upheld |
|---|----------|--------------------------|
| R1 | OpenRouter branch inside `make_client`/`backends.py` | V (one seam) |
| R2 | `OPENROUTER_API_KEY` env var; free-text model id | I (no secrets on tracked disk) |
| R3 | Uniform `--backend`/`--endpoint`/`--model` on synthesis scripts; default `anthropic` | VI (CLI first) |
| R4 | Disk-derived stage status, reuse `grounding.py` pattern | I/VIII (disk is truth, discoverable) |
| R5 | SSE subprocess streaming + CLI resumability; no new daemon | VI; "no recurring tax" |
| R6 | Warn (not block) on sub-Sonnet synthesis backend | II/IX (human decides) |
| R7 | Separate `/ensemble` route + router; old path defaults unchanged | (regression guard) |
