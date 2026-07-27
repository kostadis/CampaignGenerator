# Research: Claude API Batch Processing Option

**Feature**: 004-claude-api-batch | **Date**: 2026-07-27

Codebase facts below come from a full seam survey (campaignlib/api, all `add_backend_args` callers, pipeline loops, test fakes). API facts come from the Anthropic SDK reference (Message Batches, no beta header required).

## D1 — Extend the existing seam, don't rebuild

**Decision**: Extend `campaignlib/api/batch.py`. It already implements the full lifecycle — `build_batch_request` (mirrors `stream_api`'s system/messages shape including the `cache_control: ephemeral` breakpoint), `submit_batch`, `poll_batch` (reuses `_is_retryable`), `collect_batch` (returns `{status, text, error, usage}` per custom_id), sidecar read/write — and is exported from `campaignlib/api/__init__.py`. Two CLIs (`scene_extract`, `enhance_summary`) already consume it.

**Rationale**: Constitution V (one seam) and the module's own design note (50% discount; human review makes losing streaming acceptable; only on explicit `--batch`) — it was built as exactly this feature's foundation.

**Alternatives considered**: a fresh `batch2.py` or folding batch into `stream_api` via a flag — rejected: duplicate seam / conflates a streaming façade contract with a non-streaming transport.

## D2 — `--batch` joins the shared backend vocabulary

**Decision**: `add_backend_args()` (campaignlib/api/client.py:68) gains `--batch` (store_true, default False, help text naming the 50% discount and block-and-poll behavior). `facts_to_state.py`'s hand-rolled parser copy (its :523 comment explains the per-thread endpoint fan-out) gains the same flag in the same wording. `server/backend_forwarding.py` (third vocabulary copy) is **not** changed — UI out of scope — but gets a one-line comment referencing this spec so the copies don't silently drift.

**Rationale**: FR-001/FR-002 (one parameter, learned once, everywhere); the registrar is the single point that makes ~23 CLIs uniform. The spelling `--batch` is already shipped in two CLIs — changing it would break the two existing surfaces for zero gain. No collision with `ensemble_batch` (a console-script *name*, not a flag; its local-dispatch meaning is disambiguated in help text per the spec assumption).

**Alternatives considered**: `--backend anthropic-batch` as a fifth backend choice — rejected: batch is a *mode of* the anthropic backend, not a client type; a fifth choice would leak into `make_client`, the façades, and all three vocabulary copies, and read as a different integration (Constitution V).

## D3 — Fail-fast validation lives in `client_from_args`

**Decision**: `client_from_args(args)` raises `SystemExit` with a clear message ("--batch is a Claude API (anthropic backend) option; --backend <x> does not support it") when `getattr(args, "batch", False)` and the resolved backend (including `CG_BACKEND` env resolution) is not anthropic. Validation happens before any client construction or token spend.

**Rationale**: FR-003; `client_from_args` is the one place every registrar CLI already funnels through, and it is where backend/env resolution already happens — a check anywhere else would miss the `CG_BACKEND=openrouter` + `--batch` combination. Survey confirms none of the three façades implement `messages.batches` (`_ClaudeCodeClient` docstring explicitly: "batching … unsupported"), so late failure would otherwise be an `AttributeError` mid-run.

## D4 — Blocking helper: `run_batch` in the seam

**Decision**: New `run_batch(client, requests, *, label="", poll_interval=10, on_tick=None) -> dict[str, BatchItemResult]` in `campaignlib/api/batch.py`, composing the existing primitives:

1. `submit_batch` → immediately print `Batch submitted: <batch_id> (<n> requests)` to stderr (FR-013 — the trail for a hard-killed wait).
2. Install SIGINT/SIGTERM handling around `poll_batch`: on either signal, attempt `client.messages.batches.cancel(batch_id)`, report the outcome (`cancellation requested — status: canceling` / best-effort failure message), then exit non-zero (FR-009). SIGTERM matters because the web UI's abort (spec 002) is a graceful-then-force process-group kill — the graceful phase must trigger the cancel.
3. Poll until `processing_status == "ended"`, emitting progress counts from `request_counts` at each tick (FR-007).
4. `collect_batch`, extended to carry `stop_reason` per succeeded item; for each item with `stop_reason == "max_tokens"`, print the same loud `!!!` truncation banner `stream_api` uses (FR-010), naming the custom_id.
5. Return per-item results; the helper does **not** exit on partial failure — callers write successful outputs, list failed items by custom_id, and exit non-zero (FR-008), because only the caller knows the unit↔file mapping.

**Rationale**: FR-012 (block-and-poll) with all cross-cutting requirements in one seam function instead of re-implemented per CLI. Results are keyed by `custom_id` (the API returns them in arbitrary order).

**Alternatives considered**: extending detached submit/collect to all CLIs — explicitly out of scope per spec (FR-012); the existing `--submit-only`/`--collect` flags in `scene_extract`/`enhance_summary` are grandfathered unchanged.

## D5 — Pipeline integration at natural unit boundaries

**Decision** (FR-006):

- `run_extract_pipeline` (campaignlib/pipelines.py:29) gains `batch: bool = False`. Batch path: compute the missing-chunk set first (same skip-if-exists check, moved ahead of submission — Constitution VII cache discipline), build one request per missing chunk via `build_batch_request` (preserving `cache_system` behavior for shared prefixes), one `run_batch` call, write each result to its chunk file **atomically**. This single change batches `planning`, `party`, `distill`, and `campaign_state` extraction fan-outs.
- `scene_extract`: already grouped per scene — unchanged except adopting `run_batch`-based blocking mode for plain `--batch` (its `format_scene_output` is already documented as shared between live and batch paths, so files stay byte-identical).
- `scrub_mechanics` (per-file glob) and `query` (map phase): grouped per file/chunk via the same pattern.
- Single-call CLIs (`sd_plan`, `sd_consistency`, `check_consistency`, `vtt_voice_compare`, `transform`, `npc_table`, `make_tracking`, `enhance_summary`, `scabard_sync`, `dnd_sheet`, synthesis entry points incl. `synthesise_world_state`, `planning`/`party` synthesis calls): one-item batch, still discounted (spec edge case).
- `prep` (5 sequential dependent calls) and `sd_narrate` (per-scene loop where `handoff` from scene N feeds scene N+1's prompt, plus order-dependent `prev_voice_sample`): **cannot group without changing outputs** — ordering is a precision decision (Constitution II). Degraded mode: each call submitted as a sequential one-item batch. Slower, discount preserved, byte-comparable outputs. Documented in help text.

**Rationale**: FR-004 (identical artifacts) outranks throughput; grouping only ever spans calls that were already independent.

## D6 — Atomic per-unit writes

**Decision**: Promote `_atomic_write_text` (tmp file + `os.replace`, currently private in `pipelines/ensemble/extract_facts.py:231`) into `campaignlib` and use it for every batch-result file write (pipeline chunks, scene files). Sequential-path writes are left as-is (out of scope; behavior must stay byte-identical per FR-011).

**Rationale**: spec edge case — an interrupted result-collection pass must never leave a torn cache entry that a re-run would then trust (Constitution I: disk is truth). The helper already exists with a docstring describing exactly this failure.

## D7 — Guardrails and CI

**Decision**:
- Add the batch entry points (`run_batch`, and any pipeline-level batch wrapper) to the render-call list in `tests/test_retrieve_render_isolation.py` (Constitution III — otherwise batch render + retrieval could co-exist in one function unflagged).
- Extend `tests/test_backend_seam_guardrails.py` for the flag (present in registrar; facts_to_state copy in sync; rejection on non-anthropic backends including via `CG_BACKEND`).
- Test fakes: reuse `_fake_client_with_batches` (tests/test_batch_api.py:159) for seam tests; per-CLI tests follow the `FakeStreamAPI` two-binding monkeypatch pattern, patching the batch entry point instead.

## D8 — Out of scope, confirmed

- **Web UI**: no `_build_*_cmd()` or `backend_forwarding` changes; batch becomes reachable later as a pass-through param (Constitution VI).
- **Detached mode**: no new submit/collect verbs anywhere (FR-012 resolution).
- **Other providers**: Message Batches is first-party-API only (not Bedrock/Vertex/Foundry) — irrelevant here since only the anthropic backend qualifies anyway.
- **API mechanics accepted as-is**: no beta header; 100K/256 MB limits far above workload; results retained 29 days; prompt caching works inside batches (the existing `build_batch_request` already places the breakpoint); `fallbacks` and `max_tokens: 0` pre-warm are rejected on the Batches API (neither is used in this repo's batch path).
