# Contract: `GET /api/config/models`

**Status: unchanged by this feature.** Documented so the change of *meaning* is
recorded somewhere a future reader will look, and so a future contributor does not
"helpfully" turn the list back into a gate.

---

## Response

```json
{
  "models": ["claude-opus-5", "claude-fable-5", "…"],
  "default": "claude-sonnet-4-6",
  "backends": ["anthropic", "dgx", "openrouter", "claude-code", "codex-cli"],
  "codex_reasoning_efforts": ["…"],
  "claude_code_efforts": ["…"],
  "default_backend": "anthropic"
}
```

| Field | Before | After |
|---|---|---|
| `models` | The set of values the sidebar would accept | **Suggestions.** A starting point, with no veto over what may be selected |
| every other field | — | Untouched |

| Requirement | Contract |
|---|---|
| A1 | The response shape, field names and types are unchanged. No client needs a coordinated update. |
| A2 | `models` remains sourced from `server/config.py::MODELS`, hardcoded, in registry order. |
| A3 | An empty or stale `models` array MUST NOT prevent any model from being selected or run. Staleness costs the GM some typing and nothing else. |
| A4 | No endpoint may reject a model id on the grounds that it is absent from `models` (FR-007). |

---

## The rule this pins

`MODELS` is a **hand-maintained snapshot of ids worth suggesting**, never an
allow-list. The codebase already argues this at length, in
`campaignlib/selection.py::compatible()`:

> Existing backend checks use a `claude-` prefix rather than membership of
> `server.config.MODELS` on purpose. MODELS is a hand-maintained snapshot;
> testing against it would silently reject a legitimate Claude id that simply
> hadn't been added yet — quietly refusing a model the caller is entitled to run.

Two consumers had not adopted that reasoning; this feature converts both. A1–A4
exist so a third does not appear.

**Tempting future change to refuse**: validating `PUT /api/config/runtime`'s
`default_model` against `models`. It would look like input hygiene and would
reinstate exactly the defect this feature removes — one release behind, forever.
