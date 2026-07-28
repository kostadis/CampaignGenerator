# Research: Batch as a UI Selection Option

**Feature**: 005-ui-batch-selection | **Date**: 2026-07-27

Codebase facts below come from a direct survey of the selection machinery (`server/platform_config_service.py`, every `resolve_selection` caller, `SelectionPanel.vue` and its consumers). Batch behavior facts come from spec 004, merged in PR #190.

## D1 — Batch resolves in `resolve_selection`, and only there

**Decision**: Add `batch: bool` to `ResolvedSelection` and resolve it inside `resolve_selection()` using the same request → service → platform precedence already applied to backend. Emit the `--batch` flag from `selection_cli_args()`. No router reads a batch setting or appends the flag itself.

**Rationale**: Constitution V, and the concrete history behind it — feature 003 exists *because* three services each re-derived model/backend resolution differently and a fix to one never reached the others. Every in-scope service already calls both functions (`grounding.py` ×5, `prep.py` ×3, `setup.py` ×2, `scene_editor.py`, `ensemble.py`, plus each service's preview endpoint), so one change reaches all of them and none can drift.

**Alternatives considered**: a `batch` query parameter per run route (what the Session Doc Editor does today) — rejected: that is exactly the per-service divergence 003 eliminated, and it would need repeating on ~11 routes with no shared display.

## D2 — Batch incompatibility reuses the existing refusal mechanism

**Decision**: Add `batch: bool` and `batch_origin: str` to `ResolvedSelection`. When the resolved selection is batch but the service cannot do batch, populate the **existing** `refusal` field — the same one model/backend incompatibility already uses — so `resolve_selection()` raises for run routes and returns a refusal for preview routes. No new downgrade field.

**Rationale**: Batch is a cost-savings measure. Selecting it means "run this at the batch rate or not at all", so an unsatisfiable batch selection is an *incompatible selection* in exactly the sense 003 already models — not a preference to be quietly dropped. Reusing `refusal` therefore gets the whole behaviour for free and already-built: `resolve_selection(raise_on_incompatible=True)` raises `incompatible_selection` with the message (the default the run routes use); preview endpoints pass `raise_on_incompatible=False` and return it; `SelectionPanel.vue` renders the refusal, **disables the parent's Run button via its `compatible` emit**, and offers remedy actions. FR-005, FR-006 and FR-006a are satisfied by wiring, not new UI machinery.

It also keeps the UI and the command line identical: `client_from_args` already raises on batch + a non-anthropic backend, so any UI behaviour other than refusing would be a Split-Brain (Constitution VI — fixing the script must fix the UI).

The model/backend **pairing rule** still does not extend to batch: batch is orthogonal to which model runs, and pairing it would mean a service overriding only `batch` also inherits that tier's model — a surprise with no benefit.

**Alternatives considered**: downgrade-and-notify (run without batch, report it) — **rejected by the operator**, and rightly: it bills double what was asked for, and the notice is only as good as the operator's attention. A separate `batch_unavailable_reason` field alongside `refusal` — rejected as redundant once the semantics are "refuse".

## D3 — One behaviour regardless of which tier chose batch

**Decision**: An unsatisfiable batch selection refuses, whether batch came from the service override or was inherited app-wide. Origin is displayed (so the operator knows which switch to flip) but does not change the outcome.

**Rationale**: FR-006 admits no exception. An earlier draft split the behaviour by origin — prevent at the service tier, downgrade when inherited — to keep an app-wide batch setting from blocking services that can't batch. That reasoning valued convenience over the cost intent, and produced exactly the invisible full-price run the operator is trying to avoid. The remedy path (FR-006a) is what makes a blanket app-wide setting workable: the refusal names the conflict and offers the one-click way out.

**Consequence, accepted**: turning batch on app-wide makes every batch-incapable service refuse until the operator clears batch there or changes its backend. That is intended — it surfaces the cost decision per service instead of hiding it.

## D4 — Progress, abort, and fail-fast require no new work

**Decision**: Take all three as-is from merged work; add no server-side polling, cancellation, or batch-state interpretation.

**Rationale**:
- **Progress (FR-007)**: `run_batch` prints `Batch submitted: <id> (<n> requests)` and per-tick `[batch <id>] processing: …` lines to stderr. The subprocess runner already streams stderr to the page over SSE, so progress appears with no UI change beyond not *expecting* token-by-token text.
- **Abort (FR-012)**: spec 002 made abort a graceful-then-force process-group kill; spec 004's `run_batch` installs a SIGTERM handler that calls `batches.cancel` and exits non-zero. A lost connection is already an implicit abort, so navigating away cancels the remote batch. This is why SIGTERM (not just SIGINT) was required in 004.
- **Fail-fast**: `client_from_args` already raises `SystemExit` on batch + non-anthropic, including via `CG_BACKEND`. That is the backstop beneath D2/D3, not the primary mechanism.

**Alternatives considered**: a server-side batch registry to show in-flight batches across page loads — rejected as scope creep; the run log plus the batch id in the streamed output already make an interrupted run diagnosable (Constitution VIII), and building a registry would put batch state in the server (Constitution VI violation).

## D5 — The ensemble's per-stage tier is extended in parallel, not merged

**Decision**: The ensemble keeps its own per-stage selection (`config/ensemble.yaml` → `extract.*` / `synthesize.*`, edited on `EnsembleSetup.vue`) and gains a `batch` field per stage, resolved through the same `resolve_selection` call the ensemble router already makes with its stage config as the `service` argument.

**Rationale**: `resolve_selection`'s `service` parameter is duck-typed ("any object with `backend`/`model` attributes") specifically so the ensemble's stage config and the other services' profiles both pass through unchanged. Adding a `batch` attribute to the stage schema makes it flow the same way. Unifying the ensemble's stage tier into the generic service tier is a separate refactor with no bearing on this feature.

## D6 — The bespoke Session Doc Editor toggle is migrated and deleted

**Decision**: Remove `useBatch` and the `?batch=1` URL construction from `SessionDocEditor.vue`, remove the checkbox from `KnobDrawer.vue`, and drop the `batch` query parameter from `scene_editor.py`'s extract/enhance routes in favour of the resolved selection. The two stages keep exactly the capability they have today, now expressed through the unified control.

**Rationale**: FR-011, plus the standing single-user/no-back-compat rule — migrate and delete rather than leaving two controls that can disagree about the same run. The existing checkbox's copy ("50% off list price; replaces streaming with poll-progress") is good operator-facing language and should be reused for the unified control rather than reinvented.

**Note for implementation**: those two routes are the only ones whose batch capability predates this feature, so they are the natural first end-to-end check that the unified path produces the same behavior the bespoke one did.

## D7 — Capability is a static per-service map with only two live states

**Decision**: Carry an explicit per-service batch-capability map with two states that matter today — **full** (independent calls grouped into one submission) and **degraded** (ordered chains that run as sequential one-item batches: session prep, sd_narrate) — plus **incompatible**, which no UI-reachable service currently occupies. `full` and `degraded` both run; `degraded` additionally states its trade-off before the run (FR-010). `incompatible` refuses (D2).

**Rationale**: This information exists only in the CLIs' behaviour and cannot be derived at runtime without the server reasoning about batch (Constitution VI). A static map is honest, reviewable and cheap.

**Verified during research**: the only tool that accepts the batch flag without acting on it is the optional polish pass, and it is **not exposed in the UI at all** — the sole frontend mention is a KnobDrawer placeholder ("Polish toggle lands when the optional polish pass is wired in"). So the `incompatible` state has no member today. It is specified anyway so that wiring polish into the UI later inherits the rule, and carries the obligation to make polish's own command-line behaviour refuse rather than warn-and-continue.

**Risk noted**: the map can drift from CLI reality. Mitigation is a test pinning it against the CLIs' declared behaviour, helped by `docs/cli/cli_tools.md` § Shared flag already enumerating the same categories in one place.

## D8 — Out of scope, confirmed

- **Connection Graph** (FR-013): only in-process API caller (`connections.py:459-463`); its preview endpoint must continue to report model/backend and must *not* grow a batch field, so the UI has nothing to render (FR-014). Tracked as issue #192.
- **No new capability in the CLIs**: this feature exposes `--batch` as merged; it does not extend batch to tools that lack it.
- **No in-app cost estimation**: billing already shows the rate; SC-001 is verified there.
