# Implementation Plan: Claude Code Subscription Effort Level

**Branch**: `021-claude-code-effort` (worktree `worktrees/021-claude-code-effort`) | **Date**: 2026-09-01 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/021-claude-code-effort/spec.md`

## Summary

Give the `claude-code` subscription backend the effort control that #359 gave `codex-cli`: one option spelled the same on every CLI, a face on every UI surface that offers the backend, and a run identity that says which level actually ran and who chose it.

The technical approach is deliberately unoriginal — #359 already built this shape, and the strongest thing this feature can do is instantiate it rather than invent a second one. Three things are genuinely new, and they all come from the same fact: `claude-code` already sends an effort level today, hardcoded.

1. **Omission is not "send nothing."** `_claude_code_generate` passes `--effort high` whenever it suppresses thinking on a clamp-eligible model, because the provider refuses the top two levels with thinking off and the operator's own `~/.claude/settings.json` pins `xhigh`. That clamp stays. This feature makes it *visible* and *overridable*, not absent.
2. **The resolved state has four sources, not three.** Codex has explicit / environment / omitted. Claude Code has explicit / environment / **clamp** / **inherited** — the last two being the two different things "omission" means today, which the operator currently cannot tell apart.
3. **The conflict refusal has a location problem.** `thinking` arrives as a per-call argument, so the full conflict state is not knowable at argparse time. The refusal therefore fires in two places, with "before model work" defined as *before the `claude` child process is spawned*.

One structural lever makes CLI parity nearly free: `add_backend_args` already calls `add_codex_reasoning_arg` internally, so all 30 model-bearing CLIs inherit the Codex flag without naming it. Registering the new option in the same place gives Principle XII compliance by construction rather than by discipline.

## Technical Context

**Language/Version**: Python 3.12 (backend, CLIs), TypeScript 5 / Vue 3 + Pinia (frontend)

**Primary Dependencies**: `pydantic` v2 (config models), `argparse` (CLI seam), FastAPI (routes), `subprocess` (the `claude -p` child). No new dependency.

**Storage**: YAML on disk. `<config>/platform.yaml` (runtime tier), `<config>/session_doc.yaml` (`backends.profiles['claude-code']`), `<config>/ensemble.yaml`, `<config>/planning.yaml`, `<config>/party.yaml`. All additive optional fields — no migration (see Constitution Check XIII).

**Testing**: `pytest` (`tests/`). Frontend has no component-test harness (issue #345), so UI-parity assertions are static source checks over `frontend/src/**`, matching `tests/test_codex_reasoning_ui.py`.

**Target Platform**: Linux (WSL2), local FastAPI + Vite dev server, `claude` CLI on PATH (observed 2.1.220).

**Project Type**: Web application over a CLI engine — `campaignlib` (seam) → CLIs → FastAPI routers (subprocess) → Vue frontend.

**Performance Goals**: No new latency. Effort resolution is pure argument/config work with zero I/O beyond one environment read. The measured cost that matters is the operator's: effort and thinking together move a 130,412-char extraction between 3m57s and 17m43s, which is why the control exists and why FR-014 requires the UI to say so.

**Constraints**:
- The provider refuses `xhigh` and `max` when thinking is disabled. Thinking is disabled by default on this backend, deliberately and by measurement.
- **`thinking` is not reachable from any CLI flag or UI control today** — only `CG_CLAUDE_CODE_THINKING` or a Python-level per-call argument that no caller passes. See research R7; this bounds what FR-009's refusal message can offer.
- `~/.claude/settings.json`'s `effortLevel` is read from disk by the child and cannot be unset via the environment.
- Always-thinking model families (`fable`, `mythos` markers) have no conflict and must not be clamped.

**Scale/Scope**: 30 model-bearing CLIs inherit the flag through one registration point; 4 dispatchers forward it explicitly; ~9 frontend files and ~6 server files, mirroring #359's footprint.

## Constitution Check

*GATE: passed before Phase 0. Re-checked after Phase 1 — see "Post-Design Re-check".*

| # | Principle | Verdict | Basis |
|---|---|---|---|
| I | Disk is Truth, the Model is a Draft | **Pass** | Adds optional YAML fields; disk stays authoritative. No generated artifact is promoted to canon. |
| II | The Human Checkpoint is Non-Negotiable | **Pass** | Adds no LLM call. It *hands a decision back* to the human that the engine currently makes silently. The one genuine fork — what to do with an impossible effort/thinking pair — was ruled by the operator at the spec checkpoint (refuse; never auto-enable thinking), not guessed. |
| III | Retrieval and Render are Separated | **Pass** | Touches no retrieval path. `tests/test_retrieve_render_isolation.py` unaffected. |
| IV | Verbatim is Sacred | **Pass** | No prompt, quote, or transcript content is touched. |
| V | One Seam per Boundary | **Pass** | The `claude` CLI is reached only through `campaignlib/api/backends.py`. The effort value is threaded through that one seam; no router or pipeline builds a `claude` command line. |
| VI | CLI is the Engine, UI is a Face | **Pass** | Resolution lives in `campaignlib`; routers add the flag to `_build_*_cmd()` and resolve defaults at the route edge from the config service. No router reimplements precedence. |
| VII | Extract Once, Synthesize Deliberately | **N/A** | No extraction or synthesis pass changes. |
| VIII | State is Discoverable | **Pass — and this is the point** | The feature's User Story 3 exists because the effort a run used is currently invisible and can silently differ from what the operator pinned. FR-018/019/020 put it in output and in every record that already names the model. |
| IX | The UI Mechanizes; Claude Converses | **Pass** | The UI gains a selector, not judgment. Every choice it offers is equally typeable at the CLI. |
| X | Selection is Explicit; No Silent "All" | **N/A** | No batch set is chosen here. |
| XI | Parity is Bidirectional | **Pass** | FR-012 requires the UI face in this same feature; FR-025 requires a guardrail test that fails when a new Claude Code-capable surface lacks it. No CLI-only ruling is claimed. |
| XII | One Spelling per Option | **Pass, with a recorded choice** | One name, one meaning, one default, registered once inside `add_backend_args` so all 30 CLIs get it together — the family-wide introduction the principle demands. The option is provider-prefixed rather than sharing Codex's `--codex-reasoning-effort`; research **R1** records why a merged flag would *violate* this principle rather than satisfy it. |
| XIII | Breaking State Changes Migrate Out of Band | **Pass — not triggered** | Every new field is optional and additive. Absent means omission, which reproduces today's behaviour byte-for-byte (FR-005, SC-005). No shape changes, so no migrator and no `migration.md`. |

**Gate result: PASS. No violations to justify; Complexity Tracking is omitted.**

One boundary is recorded rather than resolved: the FR-009 ruling makes `xhigh`/`max` reachable only by an operator who sets `CG_CLAUDE_CODE_THINKING`, because thinking has no flag and no toggle. That is a real consequence of the ruling, not a defect in it, and widening scope to add a thinking control was not asked for. Research **R7** states it plainly and recommends a follow-up issue instead of absorbing it here.

## Project Structure

### Documentation (this feature)

```text
specs/021-claude-code-effort/
├── plan.md                    # This file
├── research.md                # Phase 0 — R1..R9
├── data-model.md              # Phase 1 — entities, fields, state table
├── quickstart.md              # Phase 1 — runnable validation
├── contracts/
│   ├── cli-family.md          # option name, vocabulary, precedence, refusals
│   ├── ui-selection.md        # surfaces, tiers, persistence, isolation
│   └── run-identity.md        # the four sources and how each is reported
├── checklists/
│   └── requirements.md        # spec quality — 16/16
└── tasks.md                   # Phase 2 — /speckit-tasks, NOT created here
```

### Source Code (repository root)

```text
campaignlib/
├── selection.py                     # + ClaudeCodeEffort literal, CLAUDE_CODE_EFFORTS,
│                                    #   ModelSelection.claude_code_effort, is_empty()
├── api/
│   ├── client.py                    # + add_claude_code_effort_arg (called from
│   │                                #   add_backend_args), resolve_cli_claude_effort,
│   │                                #   client_from_args threading
│   └── backends.py                  # the one seam: effort/source into _ClaudeCodeClient
│                                    #   → _ClaudeCodeMessages → _claude_code_generate;
│                                    #   conflict guard + run-identity banner
└── __init__.py                      # re-export

pipelines/ensemble/
├── ensemble.py, ensemble_batch.py,  # dispatchers: forward the resolved value to
├── ensemble_extract.py,             #   every child invocation
├── facts_to_state.py, polish.py
session_doc/sd_agent.py              # same

server/
├── platform_config_shared.py        # + runtime.default_claude_code_effort
├── platform_config_service.py       # resolve_selection: request>service>platform>env,
│                                    #   validation, wrong-backend refusal, ResolvedSelection
├── session_editor_config_shared.py  # BackendProfile['claude-code'] + is_empty()
├── ensemble_config_shared.py        # EnsembleBackend.is_empty()
└── routers/
    ├── config_routes.py             # /models exposes claude_code_efforts
    ├── ensemble.py, scene_editor.py # _build_*_cmd(): pass the flag, never a literal
    └── connections.py               # report effort in graph results

frontend/src/
├── api/client.ts                    # types + payload field
├── stores/config.ts                 # claudeCodeEfforts, claudeCodeEffort
├── components/layout/AppSidebar.vue         # global selector
├── components/shared/SelectionPanel.vue     # per-service selector + resolved display
├── components/shared/StreamOutput.vue       # identity line
├── components/scene-editor/KnobDrawer.vue   # scene tier
├── views/ensemble/EnsembleSetup.vue + useEnsembleRun.ts
├── views/session/SessionDocEditor.vue + ReviewAssemble.vue
└── views/prep/ConnectionGraph.vue

tests/
├── test_claude_code_effort.py       # resolution, precedence, refusals, clamp
├── test_claude_code_effort_config.py# tiers, isolation from the Codex field
├── test_claude_code_effort_ui.py    # static parity sweep over frontend/src
└── (extended) test_backend_seam_guardrails.py, test_platform_config_service.py,
    test_ensemble_dispatch.py, test_sd_agent.py, test_subprocess_abort.py
```

**Structure Decision**: No new structure. The feature is a second instantiation of the seam #359 established, and every file above already exists. The single most important placement decision is that the option registers inside `add_backend_args` (`campaignlib/api/client.py:350`), which is how it reaches all 30 CLIs as one act rather than 30 — the family-wide introduction Principle XII requires.

## Phase 0 — Research

See [research.md](./research.md). Nine decisions: **R1** provider-prefixed option (not a merged `--effort`), **R2** where the conflict refusal fires, **R3** the clamp is the omission behaviour, **R4** run identity, **R5** seam threading, **R6** config tiers, **R7** thinking is unreachable — the recorded consequence of the FR-009 ruling, **R8** the parity inventory and its guardrail, **R9** validating in a worktree given #286.

No NEEDS CLARIFICATION markers remain — the spec's only one (FR-009) was ruled by the operator before drafting.

## Phase 1 — Design & Contracts

See [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md).

## Post-Design Re-check

Re-evaluated after the Phase 1 artifacts. **Still PASS**, with two things design surfaced:

- **Principle VIII got stronger, not weaker.** `contracts/run-identity.md` splits today's single silent "omission" into `clamp` and `inherited`, and requires the clamp to name itself. A run that quietly downgraded the operator's pinned `xhigh` to `high` now says so.
- **Principle XII survived the naming pressure.** The temptation during design was to rename #359's `--codex-reasoning-effort` into a shared `--reasoning-effort`. Rejected in R1: the two vocabularies genuinely differ (`minimal` is Codex-only), so a shared flag would accept a value on one backend and reject it on another — one spelling with two meanings, which is the drift the principle forbids, dressed as compliance with it.

No violation requires justification, so **Complexity Tracking is omitted** by the template's own instruction.
