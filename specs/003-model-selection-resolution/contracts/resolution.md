# Contract: The Resolution Seam

The feature's central contract. One function is the only place model/backend resolution happens;
every token-spending path calls it and no path re-derives it. This is Principle V ("One Seam per
Boundary") applied to selection.

## The seam

```
resolve_selection(
    request_model:   str | None,
    request_backend: str | None,
    service:         ServiceSelection | None,   # None for inheriting services
    platform:        PlatformRuntime,
) -> ResolvedSelection
```

**Location**: `server/platform_config_service.py`, replacing `resolve_default_model` (which
resolves the model alone and has no concept of a backend or a service tier).

**Callers** — all 22 token-spending endpoints, with no other resolution logic between the call and
the built command:

| Router | Endpoints | Service tier passed |
|---|---|---|
| `ensemble.py` | extract, bundle, recent-events, threads, synthesize | per-stage `EnsembleBackend` |
| `scene_editor.py` | enhance, extract, narrate/{n}, scrub/{n}, scrub-all, plan | active `BackendProfile` |
| `grounding.py` | distill, campaign-state, build-dossiers | `grounding.yaml` `selection` |
| `grounding.py` | party | `party.yaml` `selection` |
| `grounding.py` | planning | `planning.yaml` `selection` |
| `prep.py` | session-prep, npc-table, query | `None` |
| `setup.py` | dnd-sheet, make-tracking | `None` |
| `connections.py` | extract | `None` |

**Deleted by this contract**:
- `server/routers/grounding.py:72` `_backend_flags` — its cross-service read of
  `SessionEditorConfigService` is FR-005's violation.
- `server/routers/ensemble.py:117` `_backend_args`'s model-resolution half, including the inline
  `claude-` guard at `:170` (the guard's *rule* survives in the compatibility predicate; its
  silent-substitution *behaviour* does not).
- `server/routers/scene_editor.py:554` `_model_args`'s two-level chain.

`server/backend_forwarding.py::backend_cli_args` survives as the flag *builder* — it is already
correctly scoped to formatting, not resolution.

## Guarantees

| ID | Guarantee |
|---|---|
| C1 | Exactly one `--model` flag reaches any subprocess. Two flags (today's Grounding + DGX case) is a contract violation. |
| C2 | `--backend` is emitted for every non-`anthropic` resolved backend, on every one of the 22 endpoints. |
| C3 | The resolver never returns a model the operator did not select. When resolution yields an incompatible pair it returns a refusal, never a substitute. |
| C4 | No router reads another service's configuration document. |
| C5 | `model` and `backend` come from the same tier when that tier supplies either (the pairing rule). |

## Compatibility predicate

```
compatible(model, backend) -> bool
```

| Backend | Compatible when | Rejects |
|---|---|---|
| `anthropic` | `model.startswith("claude-")` | `Qwen/…`, `openai/…`, `anthropic/claude-…` (OpenRouter form) |
| `claude-code` | `model.startswith("claude-")` | same |
| `dgx` | `not model.startswith("claude-")` | `claude-sonnet-4-6`, … |
| `openrouter` | `"/" in model` | bare `claude-…` |

**Not** membership of `server/config.py`'s `MODELS`. That list is a hand-maintained snapshot;
testing against it would refuse a legitimate new Claude id the day it ships. The predicate only
rejects ids that *cannot* belong to the target backend. Rationale carried forward verbatim from
`server/routers/ensemble.py:160-166`.

## Refusal

When `compatible` is false the endpoint returns **HTTP 409 Conflict** — the run is not started and
no subprocess is spawned.

```json
{
  "detail": {
    "error": "incompatible_selection",
    "message": "\"Qwen3-Next-80B\" is not an Anthropic model.",
    "model": "Qwen3-Next-80B",
    "model_origin": "service",
    "backend": "anthropic",
    "backend_origin": "platform",
    "service": "grounding",
    "remedy": "clear_override"
  }
}
```

409 rather than 400: the request is well-formed; it is the stored state that conflicts. The
`service` and `remedy` fields are what let the UI offer "Clear override" at the point of refusal
(FR-010) instead of sending the operator hunting for the setting.

## CLI boundary

The refusal is a **server-side** contract. It does not apply to a CLI invocation.

A GM typing `--model Qwen/… --backend anthropic` at a shell is performing an explicit act, the way
a typed glob is explicit under Principle X. `campaignlib/api/backends.py`'s `claude-* →
DGX_DEFAULT_MODEL` substitution therefore remains for direct CLI use. It simply stops being
reachable from a UI-launched run, because the resolver refuses first.

This preserves Principle VI (the CLI is the engine; the server adds no pipeline logic) — the server
is deciding *what to invoke*, which it already does, not *how the pipeline behaves*.
