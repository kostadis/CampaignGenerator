# Contract: HTTP Surface

Changes to the server's HTTP API. Three shapes: the platform tier gains a backend field, each
override-capable service gains a selection sub-resource, and every run endpoint gains a preview and
a refusal.

## 1. Platform selection

### `GET /api/config` (existing, extended)

`runtime` gains `default_backend`:

```json
{ "runtime": { "default_model": "claude-sonnet-4-6",
               "default_backend": "anthropic",
               "session_dir": "…" } }
```

### `PUT /api/config/runtime` (existing, extended)

Accepts `default_backend` alongside `default_model`. This becomes the **only** write path for the
app-wide backend — the sidebar toggle re-points here from `PUT /api/editor/config`.

```json
{ "default_backend": "dgx" }
```

Validation: must be one of the four backend literals. An unknown value is rejected by `PlatformRuntime`'s `Literal` and surfaces as the **400** this handler already returns for any invalid runtime value — not a 422, which would make this one field inconsistent with every other key the same endpoint accepts.

### `GET /api/models` (existing, extended)

Today returns `{models, default}` — an Anthropic-only list (`server/config.py:51`). It gains the
backend dimension so the UI can tell which ids are selectable for the active backend:

```json
{ "models": ["claude-opus-5", "…"],
  "default": "claude-sonnet-4-6",
  "backends": ["anthropic", "dgx", "openrouter", "claude-code"],
  "default_backend": "anthropic" }
```

The `models` list stays Anthropic-specific: DGX and OpenRouter ids are free-form and not
enumerable from this repo. The UI must accept a typed id for those backends rather than constrain
to the list.

## 2. Service override

One sub-resource per override-capable service, on that service's existing router.

| Service | Endpoint |
|---|---|
| Grounding | `GET`/`PUT` `/api/grounding/selection` |
| Party | `GET`/`PUT` `/api/party/selection` |
| Planning | `GET`/`PUT` `/api/planning/selection` |
| Ensemble | existing per-stage backend config (unchanged path) |
| Session Doc Editor | existing `PUT /api/editor/config` `backends` block (unchanged path) |

```json
PUT /api/grounding/selection
{ "model": "Qwen3-Next-80B", "backend": "dgx" }
```

Clearing (FR-013) is `{ "model": null, "backend": null }`, or `DELETE` on the same path. Both MUST
return the service to platform inheritance.

**No such endpoint exists for Setup, Session Prep, NPC Table, Query or Connection Graph** — FR-004.
Their absence is the contract.

## 3. Run preview (FR-012)

### `GET /api/<service>/selection/resolved`

Returns the `ResolvedSelection` a run *would* use, without starting one. This is what US3's
pre-run display reads and what makes the refusal visible before tokens are spent.

```json
{ "model": "claude-sonnet-4-6",
  "backend": "anthropic",
  "model_origin": "platform",
  "backend_origin": "platform",
  "compatible": true,
  "refusal": null }
```

Available for every token-spending service including the inheriting ones — an inheriting service
returns `model_origin: "platform"` always, which is exactly what the operator needs to see.

## 4. Refusal on run endpoints

All 22 token-spending endpoints gain one failure mode: **409 Conflict** when the resolved pair is
incompatible. No subprocess is spawned and no SSE stream opens.

Body shape is defined in [resolution.md](./resolution.md#refusal).

This is a new response for endpoints that today stream a 200 and fail (or silently succeed on a
substituted model) partway through. The distinction matters: a 409 is actionable before spend; a
mid-stream failure is not.

## 5. Removed

| Removed | Why |
|---|---|
| The sidebar's write of `backends.active` via `PUT /api/editor/config` | The app-wide backend moves to `PUT /api/config/runtime` (FR-006). The editor's *own* `backends` block stays — only its role as the global value goes. |

No endpoint is deleted outright. `PUT /api/editor/config` keeps serving the Session Doc Editor's
own override; it stops being the app's global backend switch.
