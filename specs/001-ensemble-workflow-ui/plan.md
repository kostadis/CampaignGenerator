# Implementation Plan: Ensemble Grounding-Doc Workflow UI

**Branch**: `001-ensemble-workflow-ui` | **Date**: 2026-06-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-ensemble-workflow-ui/spec.md`

## Summary

Add a dedicated, stepped UI surface that mechanizes the ensemble grounding-doc pipeline (extraction → fact bundling → synthesis → review/promote), deriving stage status from files on disk and streaming each mechanical step's output, while preserving the human-judgment checkpoints (scope review, alias correction, diff-before-promote) as handoffs to a Claude conversation or the CLI. Make each LLM-bearing stage backend-selectable, **adding OpenRouter** alongside the existing local-hardware (DGX/Spark) and Anthropic (Claude) options, independently per stage.

Technical approach, in one line per layer:

- **Seam (`campaignlib/api`)**: add an OpenRouter branch to `make_client` so OpenRouter is reached through the *one* LLM seam (Principle V) — a real API key from the environment and OpenRouter model ids, not the dgxlib registry.
- **CLI (engine)**: plumb a uniform `--backend` / `--endpoint` / `--model` selection into the four synthesis scripts (`synthesise_world_state.py`, `campaign_state.py`, `party.py`, `planning.py`) so synthesis can target DGX/Anthropic/OpenRouter — the extraction scripts already accept `--endpoints`/`--model` and only need the seam change.
- **Server (face)**: a new `server/routers/ensemble.py` (mounted `/api/ensemble`) that shells out to those CLI scripts via `subprocess_runner` and exposes disk-derived stage status — never reimplementing pipeline logic (Principle VI).
- **Frontend (face)**: a new `/ensemble` stepped page built on the existing `WizardShell` + `connectSSE` patterns, leaving the existing `/grounding` page untouched.

## Technical Context

**Language/Version**: Python 3.11+ (backend + CLI); TypeScript 5 / Vue 3 (frontend).

**Primary Dependencies**: FastAPI + uvicorn (server); `anthropic` SDK and `openai` SDK (both already present — `openai` powers the DGX path today); `dgxlib` (local model registry); Vue 3 + Pinia + Vue Router; PyYAML. OpenRouter is reached via the existing `openai` SDK pointed at `https://openrouter.ai/api/v1`.

**Storage**: Files on disk are the source of truth (Principle I) — chapter files, `docs/ensemble/per_chapter/*/merged.json`, `docs/ensemble/state_dossiers/*.md`, `merged_dossiers/*.md`, `*_draft.md`, live grounding docs. UI state in `ui_state.yaml` (`ui.ensemble` section); machine-local secrets/config in `.campaigngenerator.local.yaml` (gitignored) or environment.

**Testing**: `pytest` (`tests/`), including the CI guard `tests/test_retrieve_render_isolation.py`. Frontend: existing Vite/Vue toolchain (no test mandate added here).

**Target Platform**: Single-operator local workstation (WSL2 on Windows 11), local-first, intermittent network tolerated.

**Project Type**: Web application (FastAPI backend + Vue 3 frontend) layered over a CLI engine.

**Performance Goals**: Extraction is a long-running job (tens of minutes) — the UI streams progress over SSE and relies on the CLI's per-item resumability rather than expecting fast responses. Synthesis token cost stays bounded (~280K metered for a full Phandalin-scale refresh) by keeping extraction off the metered API.

**Constraints**: One seam per external boundary (Principle V) — OpenRouter must route through `campaignlib`. CLI-first (Principle VI) — every UI step is a CLI invocation. Human checkpoints are blocking (Principle II). No browser-only pipeline state (Principles I/VIII). Drafts only; never auto-overwrite live docs (Principle I).

**Scale/Scope**: One GM; campaigns up to ~45 chapters / ~1900 entities / ~860 known names (Phandalin is the reference scale).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The CampaignGenerator constitution (v1.2.0) has ten principles. This feature is, by the constitution's own words, the **canonical shape** for Principle IX, so alignment is load-bearing, not incidental. (Principle X — *Selection is Explicit* — was added during this feature, arising from its chapter picker; see the post-implement amendment in `tasks.md`.)

| Principle | Gate for this feature | Verdict |
|---|---|---|
| I. Disk is Truth, Model is Draft | Stage status derived from files; synthesis writes `*_draft.md` only; promotion is a manual file act (FR-002, FR-013, FR-017). | ✅ PASS |
| II. Human Checkpoint Non-Negotiable | Scope/alias/promote gates block auto-advance; UI never feeds one LLM stage's unreviewed output into the next across a precision boundary (FR-010, FR-011). | ✅ PASS |
| III. Retrieval/Render Separated | New router only shells out; it issues neither retrieval (`retrieve`/`rpg_search`) nor render (`stream_api`/`call_api`) calls. `test_retrieve_render_isolation.py` stays green. | ✅ PASS (no new mixing) |
| IV. Verbatim is Sacred | Extraction preserves `source_quote`; no step paraphrases transcripts. No new verbatim surface introduced. | ✅ PASS |
| V. One Seam per Boundary | **The pivotal gate.** OpenRouter is a *new external dependency* and MUST be reached only through `campaignlib`'s `make_client`. No `import openai`/OpenRouter calls added in routers or scripts outside the seam. | ✅ PASS *by design* (see Research) |
| VI. CLI is Engine, UI is Face | Backend selection is a CLI flag first; the router builds commands and streams via `subprocess_runner`, reimplementing nothing (FR-016). | ✅ PASS |
| VII. Extract Once, Synthesize Deliberately | The pipeline *is* this shape; the plan adds no pass-collapsing. Extraction stays local/cheap; synthesis stays deliberate. | ✅ PASS |
| VIII. State is Discoverable | The ensemble page reads campaign state from disk; what is done/pending is visible, not tribal (FR-002). | ✅ PASS |
| IX. UI Mechanizes; Claude Converses | The whole feature: UI steps the sequence; judgment between steps happens in Claude/CLI; files are the interchange; the human is never trapped in the UI (FR-012, FR-016, FR-017). | ✅ PASS |
| X. Selection is Explicit; No Silent "All" | Chapter picker stores the literal chosen set; extraction refuses an empty selection; "Select all" materializes every path. The CLI glob is exempt (explicit at the CLI). | ✅ PASS |

**Authority & Human Checkpoint clause**: This plan is a draft reviewed against the constitution; it imposes no autonomous precision decision. The one risk surface — OpenRouter as a second LLM vendor — is contained to the single seam, which is exactly what Principle V demands.

**Result**: No violations. Complexity Tracking left empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-ensemble-workflow-ui/
├── plan.md              # This file (/speckit-plan command output)
├── spec.md              # Feature specification (/speckit-specify)
├── research.md          # Phase 0 output (/speckit-plan)
├── data-model.md        # Phase 1 output (/speckit-plan)
├── quickstart.md        # Phase 1 output (/speckit-plan)
├── contracts/           # Phase 1 output (/speckit-plan)
│   ├── api.md           #   HTTP endpoints for /api/ensemble
│   └── cli.md           #   CLI backend-selection flag contract
└── checklists/
    └── requirements.md  # Spec quality checklist (/speckit-specify)
```

### Source Code (repository root)

```text
# ── Seam: the one LLM boundary (Principle V) ──
campaignlib/
└── api/
    ├── client.py        # MODIFY: make_client() gains an "openrouter" backend branch
    └── backends.py      # MODIFY: OpenRouter client (OpenAI SDK + real api_key, no dgxlib registry)

# ── CLI engine (Principle VI): backend selection plumbed into synthesis scripts ──
synthesise_world_state.py   # MODIFY: add --backend/--endpoint, pass to make_client()
campaign_state.py           # MODIFY: same (synthesize path)
party.py                    # MODIFY: same (synthesize path)
planning.py                 # MODIFY: same (synthesize path)
# ensemble.py / ensemble_batch.py / ensemble_extract.py / facts_to_state.py
#   already accept --endpoints/--model → reach OpenRouter once the seam supports it

# ── Server (face): new router, mirrors grounding.py ──
server/
├── main.py              # MODIFY: include_router(ensemble.router, prefix="/api/ensemble")
├── config_models.py     # MODIFY: add EnsembleSection + backend-profile fields to UIState
├── config.py            # MODIFY (maybe): OpenRouter model id suggestions for the picker
└── routers/
    └── ensemble.py      # NEW: stage runners (SSE) + disk-derived stage-status endpoints

# ── Frontend (face): new stepped page, /grounding untouched ──
frontend/src/
├── router.ts            # MODIFY: add /ensemble route tree
├── views/
│   ├── EnsembleWorkflow.vue       # NEW: WizardShell host (mirrors SessionWorkflow.vue)
│   └── ensemble/                  # NEW: one component per stage
│       ├── EnsembleSetup.vue      #   paths + per-stage backend selection
│       ├── EnsembleExtract.vue    #   Stage 1 run + status
│       ├── EnsembleBundle.vue     #   Stage 2 run + scope-review gate
│       └── EnsembleSynthesize.vue #   Stage 3 run + diff/promote gate
└── stores/
    └── config.ts        # REUSE: ui.ensemble section via updateSection()

# ── Tests ──
tests/
└── test_openrouter_seam.py        # NEW: make_client("openrouter") routing + no out-of-seam imports
```

**Structure Decision**: Web-application layout already in place (`server/` + `frontend/` over root-level CLI scripts). This feature is purely additive at every layer — one new seam branch, four script flag additions, one new router, one new frontend page tree — and touches the existing `/grounding` surface not at all (FR-015).

## Complexity Tracking

> No constitution violations. No entries required.
