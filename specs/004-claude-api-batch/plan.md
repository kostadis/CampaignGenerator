# Implementation Plan: Claude API Batch Processing Option

**Branch**: `004-claude-api-batch` | **Date**: 2026-07-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/004-claude-api-batch/spec.md`

## Summary

Make Anthropic Message Batches (50% billing discount, asynchronous) a uniform, first-class option of the Claude API backend across every LLM-bearing CLI. The load-bearing discovery from codebase research: **the seam already exists** — `campaignlib/api/batch.py` implements build/submit/poll/collect with JSON sidecars, and `scene_extract` + `enhance_summary` already expose a `--batch` flag. This feature therefore (1) promotes `--batch` into the shared backend vocabulary (`add_backend_args`) so all ~23 registrar CLIs accept it identically, (2) hardens the seam to meet the spec — fail-fast rejection on non-anthropic backends, batch-id reporting at submission, abort → remote cancellation, per-item truncation warnings, per-item failure reporting with non-zero exit, atomic per-unit writes — and (3) routes the multi-call pipelines (`run_extract_pipeline`, `run_scene_extraction`, per-file/glob loops) through grouped batch submissions at their natural unit boundaries. Execution model is **block-and-poll** (spec FR-012); the existing detached `--submit-only`/`--collect` flags in the two pioneer CLIs are grandfathered, not extended.

## Technical Context

**Language/Version**: Python 3.12 (single package, `pyproject.toml` console scripts)

**Primary Dependencies**: `anthropic` SDK (`client.messages.batches.create/retrieve/results/cancel`), `pyyaml`; no new dependencies

**Storage**: Files — output artifacts identical to sequential runs; existing `*.batch.json` sidecars (submission records for the grandfathered detached mode); per-unit extraction caches

**Testing**: `pytest tests/` — per-file fakes (no conftest): `FakeStreamAPI` callable-class monkeypatch pattern, `_fake_client_with_batches` SimpleNamespace pattern in `tests/test_batch_api.py`

**Target Platform**: Linux (WSL2), CLI-first; web UI shells out to the same CLIs but is **out of scope** (spec assumption)

**Project Type**: CLI toolkit with one shared library (`campaignlib`) — Constitution V/VI

**Performance Goals**: 50% API cost reduction on batched runs (SC-001); wall-clock is explicitly *not* a goal — batch trades latency for cost, block-and-poll accepted (FR-012)

**Constraints**: Batch requests are inherently non-streaming; only the real Anthropic client has `messages.batches` (all three façades — dgx/openrouter/claude-code — lack it, `_ClaudeCodeClient` docstring says batching unsupported); `sd_narrate`'s scene loop is order-dependent (`handoff` chains into the next prompt) so it cannot be grouped; Batch API limits (100K requests / 256 MB / 24h window / results 29 days) are far above this repo's workloads

**Scale/Scope**: ~23 CLIs via `add_backend_args` + 1 hand-rolled vocabulary copy (`facts_to_state`); 4 grounding CLIs fan out through `run_extract_pipeline`; largest realistic batch ≈ tens of units (chapters/scenes/chunks)

## Constitution Check

*GATE: evaluated against all ten principles (v1.2.0). Re-checked after Phase 1 — see bottom.*

| Principle | Verdict | Notes |
|---|---|---|
| I. Disk is Truth, Model is a Draft | ✅ | Batch results land in the exact files the sequential path writes (FR-004); sidecars are records over disk, rebuildable/deletable. Drafts stay drafts — batch changes transport, not review status. |
| II. Human Checkpoint | ✅ | No LLM call is added, removed, or re-chained. Batch groups calls that were already independent within one pipeline stage; every existing human gate (dossier proposal, draft-vs-live promote, per-pass review) is untouched. Per the global checklist: the decision removed from the human is "none". |
| III. Retrieval/Render Separated | ✅ with action | Batch submission is a render-side act. **Action**: the new blocking entry point(s) must be added to the render-call list in `tests/test_retrieve_render_isolation.py`, otherwise a function mixing retrieval + batch render would slip past CI. |
| IV. Verbatim is Sacred | ✅ | N/A — no transcript handling changes. |
| V. One Seam per Boundary | ✅ with action | All batch traffic already flows through `campaignlib/api/batch.py` (inside the one `anthropic`-importing package). **Action**: do not let CLIs call `client.messages.batches.*` directly; extend the seam. The `--backend` vocabulary is duplicated in `facts_to_state.py` and `server/backend_forwarding.py` — the CLI copy gains `--batch` in sync; the server copy is untouched (UI out of scope) and gets a comment pointing at this plan. |
| VI. CLI is the Engine | ✅ | Feature is CLI-only. Future UI exposure = pass a flag through `_build_*_cmd()`, no router logic. |
| VII. Extract Once, Synthesize Deliberately | ✅ | Batch preserves the per-unit cache discipline: already-on-disk units are excluded *before* submission (scene_extract already does this; `run_extract_pipeline`'s skip-if-exists check moves ahead of request building). No passes are collapsed. |
| VIII. State is Discoverable | ✅ | Batch id printed at submission (FR-013) and recorded in the sidecar; an in-flight run is diagnosable from disk + provider console. |
| IX. UI Mechanizes; Claude Converses | ✅ | N/A this feature; noted for the follow-up UI exposure. |
| X. Selection is Explicit | ✅ | Batch acts on the set the pipeline already selected explicitly (CLI globs are explicit acts per the constitution's own clause). `--batch` itself is opt-in; default behavior byte-identical (FR-011). |

**No violations to justify — Complexity Tracking section omitted.**

## Project Structure

### Documentation (this feature)

```text
specs/004-claude-api-batch/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   ├── cli-batch-flag.md    # Uniform --batch CLI contract
│   └── batch-seam.md        # campaignlib.api.batch function contracts
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
campaignlib/
├── api/
│   ├── client.py        # add_backend_args gains --batch; client_from_args validates batch⟹anthropic
│   ├── batch.py         # EXISTING seam — extended: run_batch (blocking submit→poll→collect),
│   │                    #   cancel-on-abort, per-item stop_reason, failure summary
│   └── __init__.py      # export new entry points
├── pipelines.py         # run_extract_pipeline gains batch mode (grouped submission per chunk set)
├── scenes.py            # run_scene_extraction: batch path already exists in scene_extract; unchanged
└── io_atomic.py         # NEW (or fold into existing module): _atomic_write_text promoted from
                         #   pipelines/ensemble/extract_facts.py for batch result writes

session_doc/             # sd_plan, sd_consistency, sd_narrate, enhance_summary, scene_extract, …
pipelines/
├── grounding/           # planning, party, distill, campaign_state, npc_table, make_tracking
├── session_prep/        # prep, transform
├── content_ingest/      # dnd_sheet
├── rlm/                 # query
└── ensemble/            # synthesise_*, extract_facts, polish, facts_to_state (hand-rolled vocab)

tests/
├── test_batch_api.py               # existing seam tests — extended
├── test_backend_seam_guardrails.py # choices-list guardrails — updated for --batch
├── test_retrieve_render_isolation.py  # render-call list gains batch entry points
└── test_*.py                       # per-CLI batch acceptance (FakeStreamAPI-style fakes)
```

**Structure Decision**: single existing package; no new top-level modules beyond the (possible) atomic-write helper. All batch logic stays inside `campaignlib/api/batch.py` (Constitution V); CLIs and `campaignlib/pipelines.py` only call the seam.

## Phase 0 → research.md

All technical unknowns resolved; no NEEDS CLARIFICATION markers remain. Decisions (extend-vs-rebuild, flag placement, blocking-helper shape, dependent-loop handling, atomicity, validation point) recorded in [research.md](research.md).

## Phase 1 → data-model.md, contracts/, quickstart.md

- [data-model.md](data-model.md) — Batch submission / batch item / sidecar record entities and lifecycle
- [contracts/cli-batch-flag.md](contracts/cli-batch-flag.md) — the uniform CLI parameter contract (flag, validation, output lines, exit codes)
- [contracts/batch-seam.md](contracts/batch-seam.md) — `campaignlib.api.batch` function signatures and behavior
- [quickstart.md](quickstart.md) — end-to-end validation scenarios mapping to spec SC-001…SC-005

## Constitution Re-check (post-design)

Design artifacts reviewed against the gates above: the two "with action" items (isolation-test render list, seam-only access) are encoded as explicit contract clauses in `contracts/batch-seam.md` and will become tasks. No principle is violated by the Phase 1 design; the `sd_narrate` degraded mode (sequential one-item batches) preserves ordering (Principle II — ordering is precision) rather than parallelizing a dependent chain. **PASS.**

## Execution strategy (repo convention)

Per the standing orchestrate/implement split: implementation phases are delegated to Sonnet subagents in a worktree on branch `004-claude-api-batch` (never commit to main; PR at the end; merge only on explicit go-ahead). Worktree pytest runs use `cd <worktree> && env -u PYTHONPATH ~/.venvs/main/bin/python -m pytest -q` (the PYTHONPATH guard is unsafe — mempalace strips it mid-suite) and require copying gitignored `config/wiring.yaml` from the main checkout. Suggested phase split for `/speckit-tasks`: (1) seam hardening in `campaignlib/api/batch.py` + `client.py` + guardrail tests; (2) pipeline integration (`run_extract_pipeline`, atomic writes) + grounding CLIs; (3) remaining CLIs sweep (single-call + `facts_to_state` + `sd_narrate` degraded mode) + isolation-test update + full-suite gate.
