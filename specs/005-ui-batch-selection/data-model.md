# Data Model: Batch as a UI Selection Option

**Feature**: 005-ui-batch-selection | **Date**: 2026-07-27

No database. State is YAML on disk plus one per-request computed object (Constitution I). Batch mirrors the existing model/backend tiers exactly.

## Batch selection, by tier

| Tier | Where it lives | Field | Default | Set from |
|---|---|---|---|---|
| Platform (app-wide) | `config/platform.yaml` → `runtime` | `default_batch: bool` | `false` (FR-004) | App sidebar |
| Service (per-service override) | that service's selection store, alongside its `model`/`backend` | `batch: bool \| null` | `null` = defer to platform | `SelectionPanel` on the service's page |
| Ensemble stage (parallel service tier) | `config/ensemble.yaml` → `extract` / `synthesize` | `batch: bool \| null` | `null` = defer | `EnsembleSetup.vue` (three-state: inherit / on / off) |
| Request (per-run) | not persisted | — | absent | not exposed in this feature |

`null` at the service tier is load-bearing: it is the difference between "this service defers" and "this service explicitly chose off". Only the former follows an app-wide change.

## ResolvedSelection (extended)

Computed per request by `resolve_selection()`, never persisted — the durable record of what a run used stays the run log's `command` line, which now carries `--batch`.

| Field | Type | Status | Notes |
|---|---|---|---|
| `model`, `backend` | str | existing | unchanged |
| `model_origin`, `backend_origin` | str | existing | `request \| service \| platform \| literal` |
| `endpoint`, `endpoints` | str \| tuple | existing | unchanged |
| `refusal`, `compatible` | str \| None, bool | existing, **now also carries batch** | an unsatisfiable batch selection populates `refusal` exactly as an incompatible model/backend pair does (D2) |
| `batch` | bool | **new** | the resolved selection; what `--batch` is emitted from |
| `batch_origin` | str | **new** | `request \| service \| platform` — displayed so the operator knows which switch to flip; does **not** change behaviour (D3) |

**Invariant**: `batch is True and compatible` ⟹ `backend == "anthropic"` **and** the service's capability is not `incompatible`. Any other batch-true combination sets `refusal`, so `compatible` is False and the run is refused — never silently run without batch (FR-006).

**No downgrade field exists.** An earlier draft carried `batch_unavailable_reason` for a run-anyway-without-batch path; that path is gone.

## Batch capability map (static, per service)

Derived from the CLIs' actual behavior as merged in spec 004; drives what the UI may offer (D7).

| State | Meaning | Services | UI consequence |
|---|---|---|---|
| `full` | Independent calls grouped into one submission | grounding (distill, campaign state, party, planning), ensemble extract/synthesize, scene extract, enhance summary, npc table, make tracking, query, dnd sheet, sd_plan, sd_consistency | Offer the control normally |
| `degraded` | Ordered chain → sequential one-item batches; same discount, slower | session prep, sd_narrate | Offer, with the trade-off stated before the run (FR-010) |
| `incompatible` | Tool cannot act on batch | *(none reachable from the UI today — polish is unwired; see D7)* | Selecting batch refuses the run with a stated reason (FR-005/FR-006) |
| `excluded` | Out of scope for this feature | connections | Do not offer a control; preview omits batch entirely (FR-013/FR-014) |

## Resolution + compatibility

```
request.batch?  ─┐
service.batch?  ─┼─► first non-null wins ──► batch, batch_origin
platform.batch  ─┘

batch == False
        └─► compatible (batch plays no part in refusal)

batch == True
        ├─ backend == "anthropic" and capability != incompatible
        │       └─► compatible — run proceeds as batch
        └─ otherwise
                └─► refusal = "batch is a cost-savings option that this run
                               cannot honour: <specific reason>"
                    ⇒ compatible == False
                    ⇒ run routes raise incompatible_selection
                    ⇒ preview routes return it for display + remedy
```

Identical in both directions regardless of `batch_origin` (D3): an inherited app-wide batch refuses exactly as a per-service one does. Origin is shown so the operator knows *where* to resolve it, not *whether* it applies.

## Flag emission

`selection_cli_args(resolved)` is the only producer of run flags. It appends `--batch` when `resolved.batch` is true, after the existing `--backend`/`--endpoint(s)`/`--model` flags. A resolved selection that reaches flag building has already passed the compatibility check, so `--batch` is never emitted alongside a non-anthropic `--backend`. The CLI's own fail-fast (`client_from_args`) remains the backstop beneath it — and the fact that both layers refuse the same combination is the point: the UI and the command line cannot disagree about the same run.
