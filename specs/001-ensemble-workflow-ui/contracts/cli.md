# CLI Contract: backend selection across LLM-bearing scripts

The CLI is the engine (Principle VI); the UI only sets these flags. This contract defines the **uniform backend-selection vocabulary** added so every LLM stage can target DGX, Anthropic, or OpenRouter — and the **seam change** that makes OpenRouter reachable from the one boundary (Principle V).

---

## Seam: `campaignlib/api`

### `make_client(endpoint=None, model_override=None, backend=None)` — MODIFY
Add an OpenRouter branch, preserving existing precedence (`backend`/`$CG_BACKEND` first, then `endpoint`/`$DGX_ENDPOINT`, then Anthropic default):

```
backend = backend or os.environ.get("CG_BACKEND")
if backend == "claude-code":  return _ClaudeCodeClient(...)          # existing
if backend == "openrouter":   return _OpenRouterClient(model_override=model_override)  # NEW
endpoint = endpoint or os.environ.get("DGX_ENDPOINT")
if endpoint:                  return _OpenAICompatClient(endpoint, model_override)     # existing
return anthropic.Anthropic()                                          # existing default
```

### `_OpenRouterClient` (in `campaignlib/api/backends.py`) — NEW
- Reuses the `openai` SDK: `OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"], timeout=…)`.
- Base URL overridable via `OPENROUTER_BASE_URL`.
- Model id passed through verbatim (no dgxlib registry lookup — that is the difference from `_OpenAICompatClient`).
- Exposes the same Anthropic-shaped `.messages.create(...)` façade the other clients expose, so `stream_api`/`call_api` work unchanged.
- Missing `OPENROUTER_API_KEY` → a clear, immediate error (no silent fallback), consistent with the seam's "the choice is explicit" docstring.

**Contract test** (`tests/test_openrouter_seam.py`): `make_client(backend="openrouter")` returns the OpenRouter client; no module outside `campaignlib/api` imports `openai`/`anthropic` for OpenRouter; missing key raises.

---

## Synthesis scripts — ADD flags

`synthesise_world_state.py`, `campaign_state.py`, `party.py`, `planning.py` each gain:

| Flag | Values | Effect |
|---|---|---|
| `--backend` | `anthropic` (default) \| `dgx` \| `openrouter` | Passed to `make_client(backend=…)`. Omitted ⇒ `anthropic` ⇒ **identical to today** (FR-015, SC-006). |
| `--endpoint` | URL | Passed to `make_client(endpoint=…)` (for `dgx`; OpenRouter uses its default base). |
| `--model` | id | Already present; for `openrouter`, an OpenRouter model id. |

These scripts currently call `make_client()` with no args; the change threads the parsed args into that single call. No other behavior changes.

**Backward-compatibility invariant**: with none of the new flags supplied, the constructed command and the resulting output are unchanged from the current Anthropic path. This is the regression guard behind SC-006.

---

## Extraction / aggregation scripts — NO new flags needed

`ensemble.py`, `ensemble_batch.py`, `ensemble_extract.py`, `facts_to_state.py` already accept `--endpoints`/`--dgx-endpoint`/`--model`. To target OpenRouter:
- set `CG_BACKEND=openrouter` (env, injected by the server) **or** rely on the seam recognizing the OpenRouter selection, and
- pass the OpenRouter `--model` id.

`facts_to_state.py` already calls `make_client(endpoint=…, model_override=…)`; once the seam honors `openrouter`, no script edit is required there. (If a per-stage `--backend` flag is desired on these for symmetry, it is additive and optional.)

---

## Provenance (FR-008)

Each LLM-bearing script records the backend+model it used into its output artifact (frontmatter or trailing comment), so a mixed-backend run is auditable. This is the same place each script already stamps `n_facts`/model metadata.

---

## Invariants enforced by this contract

- One seam: OpenRouter is constructed only inside `campaignlib/api` (Principle V).
- CLI-first: every backend choice is expressible and runnable from the terminal without the UI (Principle VI, FR-016).
- Safe default: absent flags ⇒ today's Anthropic behavior (FR-015).
- Explicit failure: a missing key or unreachable endpoint errors loudly, never silently degrades (FR-009).
