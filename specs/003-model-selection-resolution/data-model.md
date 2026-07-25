# Phase 1 Data Model: Model Selection Resolution

This feature adds **no new file and no database**. It adds one field to the platform document, one
field to three service documents, and a request-scoped value object that is computed and never
persisted. Existing overrides in `ensemble.yaml` and `session_doc.yaml` are re-expressed, not
replaced.

## Entity: `ModelSelection` (value object, persisted as a nested field)

The shared shape of "a chosen model and the backend that serves it". Both fields optional; both
absent means "no selection here — defer to the tier above".

| Field | Type | Default | Notes |
|---|---|---|---|
| `backend` | `anthropic` \| `dgx` \| `openrouter` \| `claude-code` \| null | null | null = defer |
| `model` | string \| null | null | null = defer. Must satisfy R5's predicate for the resolved backend |

**Invariants**:
- A `ModelSelection` is never partially inherited: see the pairing rule below.
- An empty `ModelSelection` (both null) MUST be indistinguishable from an absent one.
- Storing an incompatible pair is permitted; *running* one is refused (FR-009). This is deliberate
  — the operator may switch the platform backend and return to fix the override later, and a write
  that rejected the pair would make the refusal message impossible to reach.

## Entity: Platform selection (extends an existing entity)

Adds one field to `PlatformRuntime` (`server/platform_config_shared.py:109`), persisted under the
existing `runtime:` key of `platform.yaml`.

| Field | Type | Default | Status |
|---|---|---|---|
| `default_model` | string | `campaignlib.constants.DEFAULT_MODEL` | **existing, unchanged** |
| `default_backend` | `anthropic` \| `dgx` \| `openrouter` \| `claude-code` | `anthropic` | **NEW** |
| `session_dir` | string \| null | null | existing, unrelated |

`PlatformRuntime` is `extra="forbid"`; adding the field is a schema change requiring the migration
in the Migration section below. Default `anthropic` reproduces today's effective behaviour for a
campaign that has never touched the toggle (`backend_cli_args` returns `[]` for anthropic —
`server/backend_forwarding.py:32`).

**Invariants**:
- Exactly one platform selection exists per campaign.
- `default_model` MUST be non-empty; `resolve` falls back to the `DEFAULT_MODEL` literal if it is.
- A write to any service document MUST NOT be able to modify it — the regression already guarded by
  `test_ui_section_write_cannot_touch_platform_yaml`.

## Entity: Service override (new field on three existing documents)

| Service | Document | Path | Shape |
|---|---|---|---|
| Grounding | `grounding.yaml` | `selection` | `ModelSelection` |
| Party | `party.yaml` | `selection` | `ModelSelection` |
| Planning | `planning.yaml` | `selection` | `ModelSelection` |
| Ensemble | `ensemble.yaml` | `backends.<stage>` | `EnsembleBackend` — **existing**, already a superset |
| Session Doc Editor | `session_doc.yaml` | `backends.<name>` | `BackendProfile` — **existing**, already a superset |

The two existing shapes are supersets of `ModelSelection`, differing in endpoint plurality:

| | `ModelSelection` | `EnsembleBackend` | `BackendProfile` |
|---|---|---|---|
| `backend` | ✓ | ✓ | ✓ |
| `model` | ✓ | ✓ | ✓ |
| `endpoints` (list) | — | ✓ (DGX fan-out) | — |
| `endpoint` (single) | — | — | ✓ |

That difference is load-bearing and preserved (spec Assumptions): the ensemble extract stage fans
out across both Sparks; the Session Doc Editor targets one host. The shared contract is the common
core, not a forced merge.

**Invariants**:
- The five inheriting services — Setup, Session Prep, NPC Table, Query, Connection Graph — MUST
  have no override field anywhere (FR-004).
- A service override MUST be readable only by its owning service (FR-005). Specifically,
  `server/routers/grounding.py` MUST NOT construct a `SessionEditorConfigService`.

## Entity: `ResolvedSelection` (computed, never persisted)

Produced once per run at launch. The single output of the single resolver.

| Field | Type | Notes |
|---|---|---|
| `model` | string | Always non-empty |
| `backend` | backend literal | Always present |
| `model_origin` | `request` \| `service` \| `platform` \| `literal` | Which tier supplied `model` |
| `backend_origin` | `request` \| `service` \| `platform` | Which tier supplied `backend` |
| `endpoint(s)` | string / list / null | Carried from the service override when present |
| `compatible` | bool | R5 predicate applied to (`model`, `backend`) |
| `refusal` | string \| null | Human-readable reason when `compatible` is false |

**Lifecycle**: computed at request time, used to build the subprocess command, discarded. It is
**not** a source of truth — the persisted record of what a run used is the run log (R7), not this.

**Invariants**:
- `compatible == false` ⟹ the run MUST NOT start and `refusal` MUST be non-empty (FR-009).
- `compatible == true` ⟹ exactly one `--model` flag reaches the subprocess. The two-`--model`
  command of R2 is the defect this invariant exists to kill.
- The resolver MUST NOT substitute a different model when `compatible` is false (FR-011).

## Resolution rule (the one rule)

Applied identically for every token-spending run:

```
model    := request.model    ?? service.model    ?? platform.default_model  ?? DEFAULT_MODEL
backend  := request.backend  ?? service.backend  ?? platform.default_backend
```

**The pairing rule.** `model` and `backend` are resolved from the *same tier* whenever that tier
supplies either. A service that sets only `model` inherits the platform `backend`, and the pair is
then checked by R5 — this is precisely the stale-override case, and it refuses rather than
silently mixing tiers into a working-looking command. Independent per-field inheritance is what
produces R2's two-owner command and is prohibited.

## State transitions

`ModelSelection` has three states from the operator's view:

```
        set an override
absent ─────────────────> present, compatible ──> run proceeds
   ^                            │
   │                            │ platform backend changes
   │ clear override             v
   └──────────────────── present, incompatible ──> run REFUSED (FR-009)
                                │                  operator clears or corrects (FR-010)
                                └──────────────────────────┘
```

There is no fourth state. "Present but ignored" — today's ensemble behaviour — is the state this
feature removes.

## Migration

Single-user deployment: **migrate and delete**, no dual-location probes, no back-compat shim
(standing project rule).

1. Read `session_doc.yaml`'s `backends.active` — today's de-facto global backend.
2. Write it to `platform.yaml` `runtime.default_backend`.
3. Leave `session_doc.yaml`'s `backends` block intact: it remains the Session Doc Editor's own
   override, which is legitimate under the new rule. Only its role as the *app-wide* value moves.
4. `server/migrate_platform_config.py` is the precedent for shape and placement.

**Verification**: after migration, `grounding.py` must import nothing from
`session_editor_config_service`, and the sidebar toggle must round-trip through
`PUT /api/config/runtime`.
