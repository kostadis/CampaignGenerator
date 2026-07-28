# Implementation Plan: Batch as a UI Selection Option

**Branch**: `005-ui-batch-selection` | **Date**: 2026-07-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/005-ui-batch-selection/spec.md`

## Summary

Add batch as a third value in the selection mechanism feature 003 already built, so it is chosen, resolved, displayed, and forwarded exactly like model and backend. The decisive structural fact from codebase research: **every token-spending service already funnels through two functions** — `resolve_selection()` (tier resolution: request → service → platform) and `selection_cli_args()` (flag building) — and each exposes a read-only `GET /api/{service}/selection/resolved` that the shared `SelectionPanel.vue` renders. Adding `batch` to `ResolvedSelection` plus those two functions therefore reaches all eight subprocess services at once, and adding it to `SelectionPanel` reaches every page's display and override at once. No per-router batch logic is written (Constitution VI: the UI forwards a flag; the CLI is the engine — all batch behavior shipped in spec 004).

**Batch is a hard cost constraint, not a preference**: a selection of batch means "run at the batch rate or not at all". A run that cannot honour it is *refused*, never quietly executed at full price — that would bill double what the operator asked for, invisibly, and would make the UI behave differently from the command line (which already refuses). This lands on machinery 003 already built: an unsatisfiable batch selection populates the existing `refusal`, so run routes raise `incompatible_selection`, preview routes return it, and `SelectionPanel.vue` renders the reason, disables the parent's Run button through its `compatible` emit, and offers remedy actions. No new incompatibility mechanism is needed.

Four requirements are therefore satisfied by already-merged work: progress reporting (spec 004's `run_batch` prints poll progress to stderr, which the existing SSE runner streams), abort-cancels-remote-batch (spec 002's abort sends SIGTERM; `run_batch`'s handler cancels the remote batch), fail-fast on an impossible combination (`client_from_args` rejects batch + non-anthropic), and the refusal display path just described.

The Connection Graph is out of scope (FR-013) — the only in-process caller; tracked as issue #192.

## Technical Context

**Language/Version**: Python 3.12 (FastAPI server), TypeScript + Vue 3 (frontend)

**Primary Dependencies**: existing only — no new packages. Consumes `campaignlib.api.batch` (spec 004) indirectly, via the `--batch` CLI flag.

**Storage**: YAML on disk — `config/platform.yaml` (platform tier, `runtime.*`), per-service selection stores (service tier), `config/ensemble.yaml` (ensemble's own per-stage tier)

**Testing**: `pytest tests/` (server + config shape), `npm run build` in `frontend/` for the TS/Vue gate

**Target Platform**: Local FastAPI server + browser, single operator

**Project Type**: Web application (Vue frontend + FastAPI backend) over a CLI engine

**Performance Goals**: None new. Batch trades latency for 50% cost; the UI must make that trade visible, not fast.

**Constraints**: The UI may not implement batch behavior — only select and forward it (Constitution VI). Batch is Claude-API-only, so the resolved (backend, batch) pair has an invalid combination that must be **refused**, never run at full price (FR-006). Live token streaming is unavailable under batch; progress replaces it. `sd_narrate`/`prep` run as sequential one-item batches — slower for the same discount — which the UI must state before the run (FR-010). The optional polish pass cannot batch at all, but is not UI-exposed today, so no service currently sits in the incompatible state.

**Scale/Scope**: 8 in-scope services (grounding ×5 run routes, prep ×3, setup ×2, scene-editor, ensemble ×2 stages, planning, party, plus each service's preview endpoint); 1 excluded (connections); ~10 frontend views consuming 2 shared panels

## Constitution Check

*GATE: evaluated against all ten principles (v1.2.0). Re-checked after Phase 1 — see bottom.*

| Principle | Verdict | Notes |
|---|---|---|
| I. Disk is Truth | ✅ **strengthened** | Batch selection persists to the same YAML tiers as model/backend; `ResolvedSelection` stays per-request and unpersisted; the run log's `command` line carries `--batch`. The refuse-don't-downgrade rule is this principle's *Optimistic Lies* clause applied to money: a run that reports success while having silently spent double is precisely the confident-looking artifact that isn't what it claims. |
| II. Human Checkpoint | ✅ | No LLM call is added, removed, or re-chained; no scope/ordering/attribution decision moves. Batch is a transport choice over identical work producing identical artifacts (FR-008). Per the global checklist, the decision removed from the human is "none". |
| III. Retrieval/Render Separated | ✅ | N/A — no retrieval or render code changes. |
| IV. Verbatim is Sacred | ✅ | N/A. |
| V. One Seam per Boundary | ✅ **load-bearing** | Batch resolution goes in `resolve_selection` and flag emission in `selection_cli_args` — the two functions 003 created precisely so this rule stops being re-derived per service. **No router may read a batch setting directly or append `--batch` itself.** The NOTE spec 004 left in `backend_forwarding.py` already marks where the flag joins. |
| VI. CLI is the Engine | ✅ **load-bearing** | The server only forwards `--batch`. Every behavior (grouping, polling, cancel-on-signal, truncation warnings, partial-failure exit codes) already lives in the CLIs. Polling or interpreting batch state in a router would be a violation. |
| VII. Extract Once | ✅ | Untouched — batch preserves the per-unit cache discipline in the CLI layer. |
| VIII. State is Discoverable | ✅ | The resolved-selection preview endpoints extend to show batch + origin (FR-003); the run log's command line records it; an in-flight batch's id is already printed to the streamed output by `run_batch`. |
| IX. UI Mechanizes; Claude Converses | ✅ | Batch is mechanical — a transport toggle, not judgment. Equivalent at the CLI (`--batch`), so no judgment is trapped in the UI. |
| X. Selection is Explicit | ✅ | Batch defaults off (FR-004). An inherited platform-tier batch is not an implicit "all": it is an explicit operator act at the app-wide tier, displayed with its origin on every page before any run (FR-003). Batch does not widen *which inputs* a run touches — the blast radius is unchanged. |

**No violations to justify — Complexity Tracking section omitted.**

## Project Structure

### Documentation (this feature)

```text
specs/005-ui-batch-selection/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   ├── selection-api.md     # ResolvedSelection shape, preview + override endpoints
│   └── ui-batch-control.md  # What every batch control must show, disable, omit
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
server/
├── platform_config_service.py   # ResolvedSelection (+batch, +batch_origin),
│                                #   resolve_selection tier logic + batch refusal
│                                #   (reuses `refusal`), selection_cli_args --batch
├── platform_config_shared.py    # platform tier: runtime.default_batch
├── backend_forwarding.py        # unchanged — batch joins via selection_cli_args
├── ensemble_config_shared.py    # ensemble per-stage tier: extract/synthesize batch
└── routers/
    ├── grounding.py, prep.py, setup.py, scene_editor.py,
    │   planning_routes.py, party_routes.py   # NO batch logic — they already call
    │                                         #   resolve_selection/selection_cli_args
    ├── ensemble.py                           # per-stage batch → its run routes
    └── connections.py                        # OUT OF SCOPE (FR-013): preview omits
                                              #   batch; no control offered

frontend/src/
├── components/shared/SelectionPanel.vue   # batch display + origin + override toggle
├── components/scene-editor/KnobDrawer.vue # retire bespoke batch checkbox (FR-011)
├── components/layout/AppSidebar.vue       # app-wide batch (platform tier)
├── views/session/SessionDocEditor.vue     # drop useBatch ref + ?batch=1 URL building
├── views/ensemble/EnsembleSetup.vue       # per-stage batch
└── stores/config.ts                       # platform batch state

tests/
├── test_service_selection_override.py   # ⚠ 3 pre-existing failures on main — see below
├── test_platform_config_*.py            # resolution + batch-refusal cases
├── test_ensemble_gates.py               # --batch forwarded on ensemble run routes
└── test_scene_editor_*.py               # migration off the bespoke toggle
```

**Structure Decision**: no new modules. The change concentrates in `platform_config_service.py` (resolution + flags) and `SelectionPanel.vue` (display + override), with the ensemble's parallel per-stage store handled alongside. Routers are deliberately *not* touched except ensemble's (its stage tier is its own) and connections' (exclusion).

## Phase 0 → research.md

Eight decisions recorded in [research.md](research.md): where batch resolution lives, why batch incompatibility reuses the existing `refusal` mechanism, why the outcome is origin-independent, why progress/abort need no work, how the ensemble's parallel tier is handled, the migration of the bespoke Session Doc Editor toggle, how per-service capability is represented, and what is out of scope. No NEEDS CLARIFICATION markers remain.

## Phase 1 → data-model.md, contracts/, quickstart.md

- [data-model.md](data-model.md) — batch selection at each tier, the extended `ResolvedSelection`, the resolution/compatibility state machine
- [contracts/selection-api.md](contracts/selection-api.md) — resolved-selection payload additions, override endpoint additions, and the invariant that flags come only from `selection_cli_args`
- [contracts/ui-batch-control.md](contracts/ui-batch-control.md) — what every batch control must display, disable, and omit
- [quickstart.md](quickstart.md) — validation scenarios mapped to SC-001…SC-006

## Constitution Re-check (post-design)

The Phase 1 design keeps both load-bearing gates intact: batch is resolved in exactly one function and emitted by exactly one flag builder (V), and the server never inspects or polls batch state — it forwards a flag and streams the CLI's own output (VI). The refuse-don't-downgrade rule (FR-006) additionally *reinforces* VI: because the CLI already refuses batch on an incompatible backend, any UI that ran anyway would be a Split-Brain between the two. Refusal lives in `resolve_selection`, not in router branching, so it cannot drift per service. **PASS.**

## Execution strategy (repo convention)

Orchestrate/implement split per the standing pattern: worktree on branch `005-ui-batch-selection`, phases delegated to Sonnet subagents, reviewed and committed by the main thread; never commit to main; PR at the end and merge only on explicit go-ahead. Worktree pytest runs use `cd <worktree> && env -u PYTHONPATH ~/.venvs/main/bin/python -m pytest -q` and require copying the gitignored `config/wiring.yaml`. Suggested phases for `/speckit-tasks`: (1) resolution seam + platform tier + flag emission, with tests; (2) per-service override storage + preview endpoints + ensemble stage tier; (3) frontend (SelectionPanel, sidebar, ensemble setup, KnobDrawer retirement) with the `npm run build` gate.

**Known pre-existing condition to handle first**: `tests/test_service_selection_override.py` has 3 failing parametrizations on `main` (a FastAPI route-registration issue, unrelated to this work but sitting squarely in this feature's blast radius). The first task should establish whether they must be fixed before or alongside this feature, rather than discovering them mid-implementation and mistaking them for a regression.
