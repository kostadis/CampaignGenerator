# Implementation Plan: Batched Scene Extraction

**Branch**: `perf/scene-extract-token-utilization` | **Date**: 2026-08-22 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/013-batched-scene-extraction/spec.md`

## Summary

Stage 2 sends the full session transcript once per scene. On the metered API that
is nearly free (cached prefix); on the subscription (`claude -p`) it is pure
waste — every scene is a fresh process with a fresh session, so an 8-scene
re-extract ships ~125K tokens of repetition.

This feature adds a **batched mode**: one exchange carries the transcript plus
every scene still needing extraction, and the response carries every scene's
moments, split back apart deterministically by sentinel markers. A session whose
projected output fits the ceiling uses one call; above it, the fewest groups that
fit. The ceiling defaults to 32,000 tokens and is the GM's lever — raising it
collapses a long session back to a single call.

The technical shape follows from three findings in [research.md](./research.md):
the split must be structural (D5) because it also has to express "the response
stopped here"; the projection can be loose (D4) because over- and under-estimating
cost the same one extra transmission, so the *median* multiplier beats a
conservative one; and skip-if-exists must filter **before** the request is built
(D6), or a nearly-finished session costs the same as a fresh one.

## Technical Context

**Language/Version**: Python 3.11+ (engine, CLI, FastAPI server); TypeScript / Vue 3 (editor UI)

**Primary Dependencies**: `anthropic` (only via `campaignlib/api`), `pydantic` (config models), FastAPI, Vue 3 + Pinia

**Storage**: Files on disk. Per-scene extractions at `<session>/scene_extractions*/NN_<slug>.md`; config at `<config>/session_doc.yaml`

**Testing**: `pytest` (`tests/test_scene_extract.py`, `tests/test_session_editor_config_service.py`, `tests/test_sd_agent.py`, `tests/test_verify_quotes.py`)

**Target Platform**: Linux (WSL2); subscription path shells out to the `claude` CLI

**Project Type**: CLI engine + FastAPI server + Vue frontend (the repo's standing shape)

**Performance Goals**: One transcript transmission per group instead of one per scene — ≥ 50% wall-clock reduction on a full 8-scene subscription re-extract (SC-002)

**Constraints**: Zero regression in verbatim fidelity (SC-003/SC-004, measured with the existing zero-token quote verifier); the metered path byte-for-byte unchanged (SC-008); no model call anywhere in the response split (FR-004)

**Scale/Scope**: 5–8 scenes per session (up to ~14 observed on longer sessions); transcripts 106–150 KB; single-user, one session at a time

## Constitution Check

*GATE: evaluated before Phase 0 and re-evaluated after Phase 1.*

| Principle | Assessment | Verdict |
|---|---|---|
| **I. Disk is Truth, the Model is a Draft** | On-disk extraction files stay the record of what is done, and are what skip-if-exists consults (FR-008d). A partial response leaves disk in a valid, resumable state (FR-010/011). | ✅ Pass |
| **II. The Human Checkpoint is Non-Negotiable** | Scene structure still comes from the human-reviewed Stage 1 summary; the Stage 1→2 gate is untouched (FR-019). Grouping is arithmetic over a declared constant, not a model decision. | ✅ Pass |
| **III. Retrieval and Render are Separated** | Unchanged — this feature touches only how a render pass is transmitted, not what it retrieves. | ✅ Pass |
| **IV. Verbatim is Sacred** | **The principal risk.** One response rationing a budget across N scenes is exactly the condition under which a model compresses quotes. Mitigated by carrying every verbatim rule into the batched prompt (D9/FR-016), by never rewriting the transcript (FR-015), and gated by the deterministic quote verifier on the **exact** rate, not the `near` rate (D10/SC-003/SC-004). | ⚠️ Pass **with a required gate** — see Complexity Tracking |
| **V. One Seam per Boundary** | All calls stay behind `campaignlib/api`'s `stream_api`. No new `import anthropic`. The batched engine is a sibling in `campaignlib/scenes.py`, not a new integration point. | ✅ Pass |
| **VI. CLI is the Engine, UI is a Face** | Batching is implemented in the engine and exposed as CLI flags; the router adds flags to `_build_reextract_cmd` and reimplements nothing. | ✅ Pass |
| **VII. Extract Once, Synthesize Deliberately** | Reinforced: skip-if-exists means an extracted scene is never re-extracted without Force (FR-008a/b). | ✅ Pass |
| **VIII. State is Discoverable** | The run reports scenes requested / returned / missing / groups / transmissions (FR-018), so what happened is visible rather than inferred. | ✅ Pass |
| **IX. The UI Mechanizes; Claude Converses** | The UI gains a checkbox and a number field. No conversation, no judgement. | ✅ Pass |
| **X. Selection is Explicit; There is No Silent "All"** | The scene set is chosen by Force / skip-if-exists exactly as today (FR-008). The batched toggle is pre-selected on the subscription but **visible and overridable** (FR-007a) — a default the GM sees, not an inferred behaviour. | ✅ Pass |

**Gate result**: pass. One conditional (Principle IV) is tracked below with the
verification that discharges it.

## Project Structure

### Documentation (this feature)

```text
specs/013-batched-scene-extraction/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 — codebase survey + measurements (D1–D12)
├── data-model.md        # Phase 1 — entities, states, validation rules
├── quickstart.md        # Phase 1 — runnable validation scenarios
├── contracts/
│   ├── cli-surface.md   # scene_extract flags + run-report format
│   ├── wire-protocol.md # sentinel markers, split + reconciliation rules
│   └── editor-api.md    # /api/editor/extract + config field contract
├── checklists/
│   └── requirements.md  # Spec quality checklist (complete)
└── tasks.md             # Phase 2 — NOT created by /speckit-plan
```

### Source Code (repository root)

```text
campaignlib/
├── scenes.py                     # ENGINE — add batched extraction alongside
│                                 #   run_scene_extraction (D1):
│                                 #   • project_scene_output()   — D4
│                                 #   • group_scenes()           — FR-006a–c
│                                 #   • render_batched_user_prompt()
│                                 #   • split_batched_response() — D5
│                                 #   • run_batched_scene_extraction()
│                                 #   REUSED unchanged: plan_scene_extraction,
│                                 #   build_scene_extraction_system_prompt,
│                                 #   format_scene_output, snapshot_scene_for_rerun
└── __init__.py                   # export the new surface

config/agents/
├── scene_extract.md              # UNCHANGED (per-scene, FR-009)
├── scene_extract_user.md         # UNCHANGED
├── scene_extract_batched.md      # NEW — batched system prompt (D9)
└── scene_extract_batched_user.md # NEW — batched user prompt + sentinel protocol

session_doc/
└── scene_extract.py              # CLI — add --batch-scenes / --batch-max-tokens;
                                  #   route to the batched engine; run report

server/
├── session_editor_config_shared.py  # ExtractKnobs: + batch_scenes, + batch_tokens (D7)
└── routers/scene_editor.py          # _build_reextract_cmd: forward the two flags;
                                     #   resolved config exposes the pre-selection (D8)

frontend/src/
├── views/session/SessionDocEditor.vue        # batched toggle (pattern: forceReextract)
└── components/scene-editor/KnobDrawer.vue    # batch-token field + fix stale force text (D12)

tests/
├── test_scene_extract.py                  # engine: grouping, split, partial, force
├── test_batched_split.py                  # NEW — wire-protocol edge cases
├── test_session_editor_config_service.py  # config defaults (existing pin stays green)
└── test_scene_extract_isolation.py        # NEW — metered path unchanged
```

**Structure Decision**: the repo's standing engine / CLI / server / frontend
split, unchanged. The batched engine is a sibling function in the module that
already owns scene extraction (`campaignlib/scenes.py`) so both modes share the
file-layout and force helpers and cannot drift (D1). No new module, no new
integration boundary, no new external dependency.

## Phase 0 — Research

**Status**: complete → [research.md](./research.md)

D1 the per-scene loop and why the subscription pays for it · D2 measured cost ·
D3 what the model actually generates (~23K, not ~29K — refines the spec's
framing) · D4 the projection method and why the *median* multiplier beats a
conservative one · D5 the sentinel wire protocol · D6 force / skip-if-exists ·
D7 two token defaults, not one · D8 activation via `cfg.backends.active` ·
D9 prompt strategy · D10 fidelity measurement and the `near`-is-not-safe caveat ·
D11 what must not change · D12 an incidental stale-help-text defect.

No `NEEDS CLARIFICATION` remains. The three scope questions were ruled on by the
GM before planning and are recorded in the spec's "Resolved decisions" table.

## Phase 1 — Design & Contracts

**Status**: complete → [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

Design in one paragraph: `plan_scene_extraction` produces the scene plan and its
`exists` flags; the batched engine filters that plan by Force **first** (D6),
projects each surviving scene's output from its gm-assist body length (D4),
packs them into the fewest groups fitting the ceiling (FR-006b), and issues one
`stream_api` call per group with the shared system prompt. Each response is split
on `<<<CG-SCENE NN BEGIN: name>>>` / `<<<CG-SCENE NN END>>>` pairs (D5); a scene
is complete iff both markers are present, so an unmatched BEGIN is exactly the
"stopped here" signal. Complete scenes go through the same `format_scene_output`
+ `snapshot_scene_for_rerun` path as the per-scene mode; incomplete and missing
scenes are named in the run report and left for a re-run, which — because
skip-if-exists is unchanged — requests only them.

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|---|---|---|
| **Conditional pass on Principle IV** — batched mode ships only once the quote verifier confirms the exact-match rate holds (SC-003) and no scene loses a disproportionate share of moments (SC-004), measured on a real session extracted both ways | This feature changes the exact conditions under which a model produces verbatim spans: one budget rationed across N scenes instead of a full budget per scene. Constitution IV calls a fabricated or "improved" quote the most expensive failure the system can produce, and a token saving bought with degraded quotes is not a saving | Shipping on the token measurement alone would verify the thing that is easy to measure and assume the thing that matters. The verifier is deterministic and costs no tokens, so there is no reason to skip it |
| **A second engine function** rather than a flag on `run_scene_extraction` | The two modes share file layout and force semantics but nothing else: one is a resumable per-scene loop, the other is response-splitting with structural completeness. Their failure modes are disjoint | A `batched: bool` parameter would put two unrelated control flows in one function and make the per-scene path — which must stay byte-identical on the metered API (SC-008) — a branch inside code being actively changed |
| **A second token knob** (`batch_tokens`) rather than reusing `tokens` | FR-017b requires the per-scene default to stay at 8,192 while the batched default is 32,000; an existing test pins the former to the CLI default | One field with a mode-dependent default cannot be expressed in argparse without `default=None`, which erases the CLI's own visible default and breaks the pin |
