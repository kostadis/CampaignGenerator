# Contract: Selection API (batch additions)

**Feature**: 005-ui-batch-selection. Extends the endpoints and functions feature 003 established. Existing model/backend behavior is unchanged throughout.

## `GET /api/{service}/selection/resolved`

Read-only preview of what a run on this service would use. Every in-scope service already exposes this; the payload (`ResolvedSelection.as_dict()`) gains three fields:

```json
{
  "model": "claude-opus-4-8",
  "backend": "anthropic",
  "model_origin": "platform",
  "backend_origin": "platform",

  "batch": true,
  "batch_origin": "platform",

  "refusal": null,
  "compatible": true
}
```

- `batch_origin` ∈ `request | service | platform` — which tier supplied the value. It never encodes an outcome.
- An unsatisfiable batch selection populates the **existing** `refusal` (and flips `compatible` to false) rather than adding a batch-specific field; the message must name batch as the cause so the operator can tell it from a model/backend refusal.
- **The Connection Graph's preview (`/api/connections/selection/resolved`) MUST NOT include these fields** (FR-013/FR-014) — its absence is what tells the UI to render no control.
- Remains read-only and storage-free: providing the preview is not a config surface (003's FR-004).

## `PUT /api/{service}/selection`

The per-service override write path used by `SelectionPanel`. Body gains one optional field:

```json
{ "model": "…", "backend": "…", "batch": true }
```

- `batch: null` (or omitted) = **defer to the platform tier**. This is distinct from `batch: false` = explicitly off for this service, which does not follow app-wide changes.
- A `PUT` setting `batch: true` on a service that cannot honour it is **stored**, not rejected: the resulting selection is simply incompatible and every subsequent resolve refuses it with the reason and remedy. Storing it keeps the operator's stated intent visible and fixable rather than silently discarded (contrast the model/backend fields, whose own validation is unchanged).
- The existing `DELETE` clear-override semantics apply to batch along with the rest.

## Platform tier

The app-wide selection write path (already the only writer for app-wide backend) gains `default_batch: bool`, default `false`. Reachable from the sidebar alongside the model and backend controls.

## `resolve_selection(...)` — resolution invariants

1. Batch precedence is request → service → platform, matching backend.
2. The model/backend **pairing rule does not extend to batch** — a service overriding only `batch` does not thereby inherit that tier's model (D2).
3. If `batch` resolves true but the run cannot honour it — the resolved backend is not `anthropic`, or the service's capability is `incompatible` — `refusal` is populated and `compatible` becomes false. Run routes (`raise_on_incompatible=True`, the default) therefore raise `incompatible_selection`; preview routes (`raise_on_incompatible=False`) return it for display. **Batch is never silently dropped** (FR-006).
4. This is origin-independent: an inherited app-wide batch refuses exactly as a per-service one does (D3).
5. Post-condition: a selection that is `compatible` with `batch is True` always has `backend == "anthropic"` and a non-`incompatible` capability.

## `selection_cli_args(resolved)` — the only flag producer

Appends `--batch` when `resolved.batch` is true, after the existing flags.

**Invariant (Constitution V/VI), enforced by test**: no router may append `--batch` itself or read a batch setting directly — grep-level guardrail, mirroring the one spec 004 added for `messages.batches`. Every service's `--batch` must originate here, so a run log's command line is a faithful record of the resolved selection.

## Out of contract

- No server-side batch polling, cancellation, or batch-state storage: the CLI owns all of it and streams its own progress (D4).
- No change to `backend_forwarding.backend_cli_args` — batch joins at the `selection_cli_args` layer, as the NOTE spec 004 left there anticipates.
- `scene_editor.py`'s `batch=1` query parameters are **removed**, not extended (FR-011/D6).
