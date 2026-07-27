# Contract: The Batch Control (every surface)

**Feature**: 005-ui-batch-selection. Applies to every UI surface that offers a model and backend choice.

## Where the control appears

| Surface | Tier it writes | Notes |
|---|---|---|
| App sidebar (`AppSidebar.vue`) | Platform | Sits with the existing app-wide model + backend pickers |
| `SelectionPanel.vue` (inside `RunPanel` / `ExtractSynthesizePanel`, on all service pages) | Service override | The single component that gives ~10 pages the control at once |
| `EnsembleSetup.vue` | Ensemble stage (extract / synthesize) | The ensemble's parallel tier |
| `KnobDrawer.vue` (scene editor) | Service override | Bespoke checkbox **removed**; the unified control replaces it (FR-011) |

## What it must display

1. **Effective state** — whether this run will use batch.
2. **Origin** — inherited from app-wide, or this service's own override — using the same origin vocabulary already shown for model and backend (FR-003).
3. **The trade-off, in operator terms** — reuse the shipped wording rather than reinventing it: *"Use Anthropic Message Batches (50% off list price; replaces streaming with poll-progress)."*
4. **Refusal, when the selection cannot be honoured** — reuse the existing refusal block: state the reason (naming batch), block the run via the panel's `compatible` emit, and offer the remedy actions (clear the batch selection, or change the backend) in the same place (FR-005/FR-006/FR-006a).
5. **Degradation notice** — on `degraded` services (session prep, sd_narrate), state that steps run one at a time so the run is slower for the same saving, before the run starts (FR-010).

## What it must forbid

- **Never run without batch when batch was selected.** There is no downgrade path, no "batch not applied" run. Selecting batch means the batch rate or nothing (FR-006) — this is the single most important rule on this surface.
- **Do not render a control at all** where batch is out of scope — the Connection Graph (capability `excluded`, FR-014). Absence is the honest signal for "not offered here"; a disabled control would imply it is coming.
- **Do not let a backend change quietly cancel the cost saving.** Switching a service to a non-Claude backend while batch is selected must surface the resulting refusal immediately, not drop batch to keep the run available.
- **Do not hide the control to avoid a refusal.** If batch is selectable anywhere it must stay visible with its state; the refusal (with remedy) is how the conflict is communicated.
- **Do not implement batch behavior in the frontend.** No polling loop, no batch-id tracking, no cancel call. The page renders resolved selection and streams the run's own output (Constitution VI).

## Run-time behavior on the page

- Progress arrives on the existing SSE stream as the CLI's own stderr lines (`Batch submitted: <id> …`, per-tick counts). The page must not treat the absence of token-by-token text as a stall.
- The run ends in the same unambiguous states as any other run — succeeded / failed / aborted (FR-007) — with a partially-failed batch ending as **failed** while its successful units remain on disk (FR-009).
- Abort behaves as it does for any run: the existing graceful-then-force kill reaches the CLI, which cancels the remote batch. The page needs no special abort path (FR-012).

## Default

Batch is **off** at every tier out of the box (FR-004). An operator who changes nothing sees no behavioral change anywhere (SC-005).
