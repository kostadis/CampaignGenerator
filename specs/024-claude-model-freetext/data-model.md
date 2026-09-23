# Phase 1 Data Model: Hand-Entered Claude Model Ids

**Nothing in this document is new.** Every entity below already exists with the
type shown. The feature changes *which values may reach them* and *what authority
one of them carries* — not the shape of any of them. That is why Principle XIII
stays unarmed and no migrator ships.

---

## Entity: Model selection (persisted)

Stored in `<campaign>/platform.yaml` under `runtime:`, owned by
`PlatformRuntime` (`server/platform_config_shared.py`).

| Field | Type | Before | After |
|---|---|---|---|
| `default_model` | `str` (default `DEFAULT_MODEL`) | Any string; in practice a curated id on Claude backends because the UI could not produce another | Any string, from any backend. **Type unchanged.** |
| `default_models` | `dict[Backend, OptStr]` | Per-backend memory; hand-typed values already arrive from `dgx` / `openrouter` / `codex-cli` | Same, now reachable for `anthropic` / `claude-code` too. **Type unchanged.** |
| `default_backend` | `Backend` (enum of 5) | — | Untouched |

### Validation rules

| Rule | Source | Status |
|---|---|---|
| A value is stored trimmed of surrounding whitespace | FR-005, spec edge case | **Fixed here** — `setModel` currently trims into `default_models` but not into `default_model` (research R5) |
| `""` means "no model chosen; defer to the backend's default" | FR-006 | Already true — `_cmd_opt` skips falsy, `compatible()` treats empty as vacuously compatible (R6). Newly *reachable* on Claude backends |
| Absence from the curated list is never grounds for rejection | FR-007 | Already true server-side; the UI was the only enforcer |
| The model/backend pair must satisfy `compatible()` | FR-008 | Unchanged — id-shape rule, applies identically to typed and picked ids |
| `default_models` keys are the five canonical backends | existing | Unchanged |

### State transitions

```
                    ┌───────────────────────────────────┐
                    │  no model chosen  ( "" )          │
                    │  → backend picks its own default  │
                    └───────────────────────────────────┘
                        ▲                           │
        clear the field │                           │ type or pick an id
       (newly reachable │                           ▼
        on Claude       │        ┌──────────────────────────────────┐
        backends)       └────────│  a model id is active            │
                                 │  (curated and typed are the same │
                                 │   state — nothing records which) │
                                 └──────────────────────────────────┘
                                       │                    ▲
                       switch backend  │                    │  switch back
                       (current value  ▼                    │  (remembered
                        saved to       ┌────────────────────┴─  value restored)
                        default_models)│  another backend's remembered model │
                                       └─────────────────────────────────────┘
```

**The load-bearing property**: there is no "hand-entered" flag anywhere. A typed id
and a picked id produce byte-identical state, so nothing downstream can treat one
differently — which is what makes FR-005 and FR-009 hold by construction rather
than by discipline.

---

## Entity: Curated model shortlist

`server/config.py::MODELS` — a hardcoded Python list, published verbatim by
`GET /api/config/models` as `body["models"]` and consumed by the frontend store as
`config.models`.

| Aspect | Before | After |
|---|---|---|
| Contents | 8 Anthropic ids | Unchanged |
| Location | Hardcoded in `server/config.py` | Unchanged (relocating it is the deferred Phase 5b — research R8) |
| **Authority over the selector** | **Gate** — the only reachable values | **Suggestion** — offered as `<datalist>` entries, no veto |
| **Authority over synthesis capability** | **Gate** — via the derived `SYNTHESIS_CAPABLE` | **None** — replaced by a predicate (research R2) |
| Consumers | `config_routes.py`, `ensemble.py`, `AppSidebar.vue` | Same three; two of them stop gating |

**This is the only entity whose meaning changes**, and the change is entirely one
of authority. Its type, contents, location and wire format are all untouched, so
no client needs to know it happened.

---

## Entity: Synthesis capability judgement

Currently the set `SYNTHESIS_CAPABLE` in `server/routers/ensemble.py`; becomes the
predicate `synthesis_capable(model: str | None) -> bool` in the same module.

| Input class | Example | Capable? | Rule |
|---|---|---|---|
| Empty / absent | `""`, `None` | yes | Nothing chosen — the resolved default applies, and the platform default never warns about itself |
| Sub-Sonnet tier | `claude-haiku-4-5`, a future Haiku id | **no** | `_SUB_SONNET_TIER` substring — the one human judgement, preserved (FR-013) |
| Anthropic API id | `claude-opus-5`, `claude-opus-6` (unreleased today) | yes | `claude-` prefix |
| Anthropic via OpenRouter | `anthropic/claude-opus-5` | yes | `anthropic/claude-` prefix (research R4) |
| Frontier third-party | `openai/gpt-5`, `google/gemini-2.5-pro` | yes | `_THIRD_PARTY_SYNTHESIS_CAPABLE` membership — not derivable, stays hand-maintained |
| Anything else | `Qwen/Qwen3-Next-80B` | no | Falls through — a local model genuinely may underperform at synthesis |

**Precedence matters**: the tier check runs *before* the prefix check, so
`claude-haiku-5` is excluded rather than admitted by the `claude-` prefix. Getting
this order wrong silently deletes FR-013, and no test that only checks known ids
would notice — hence `contracts/synthesis-capability.md`'s explicit row for it.

**Not merged with** `campaignlib/selection.py::compatible()`: different question,
deliberately different answers (research R4b).

---

## Entity: Resolved selection (read-only projection)

`ResolvedSelection` in `server/platform_config_service.py`, surfaced by
`GET /api/*/selection/resolved` and rendered by `SelectionPanel.vue`.

**Unchanged in every respect.** Listed here only to pin FR-009: because a
hand-entered id produces identical stored state, `model`, `model_origin` and
`refusal` are computed for it exactly as for a curated one. An incompatible typed
id yields the existing refusal string — `"<model>" is not a valid model for the
<backend> backend.` — before any token is spent (FR-008).
