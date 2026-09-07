# Contract: The app-wide MODEL control

**Surface**: `frontend/src/components/layout/AppSidebar.vue`, sidebar footer.
**Scope**: the app-wide (platform-tier) model selection. Per-page override panels
(`SelectionPanel.vue`) and ensemble per-stage fields are already free text and are
out of scope.

---

## 1. Structure

Exactly **one** control on **all five** backends:

```
<input class="model-select" list="cg-model-ids" :value="displayedModel" @change="setModel(…)">
<datalist id="cg-model-ids"> … </datalist>
```

| Requirement | Contract |
|---|---|
| C1 | The element type MUST NOT depend on the active backend. One `<input>`, always. |
| C2 | The `modelIsFreeText` computed and the `v-if`/`v-else` fork it drives MUST be gone, not merely widened. A widened condition is a fork waiting to narrow again. |
| C3 | `<datalist>` options are populated from `config.models` when the backend is `anthropic` or `claude-code`, and are empty otherwise. |
| C4 | An empty `<datalist>` MUST leave the input fully usable — no placeholder option, no disabled state. |
| C5 | The per-backend `placeholder` text is retained, and the Claude backends gain one naming a curated id as an example. |

**Why C1/C2 rather than "make the input available on Claude too":** FR-011 is a
structural claim. As long as the component can render two different widgets, the
two can drift, and the last four years of this control's history is drift. One
element makes the requirement unfalsifiable-by-accident.

---

## 2. Accepted values

| Input | Stored `default_model` | Stored `default_models[backend]` |
|---|---|---|
| `claude-opus-5` (curated, picked) | `claude-opus-5` | `claude-opus-5` |
| `claude-opus-6` (not curated, typed) | `claude-opus-6` | `claude-opus-6` |
| `"  claude-opus-5  "` (pasted) | `claude-opus-5` | `claude-opus-5` |
| `""` (cleared) | `""` | `""` |
| `Qwen/Qwen3-80B` on `anthropic` | `Qwen/Qwen3-80B` | `Qwen/Qwen3-80B` |

| Requirement | Contract |
|---|---|
| C6 | The two stored fields MUST always receive the **same** string. (Today they do not — research R5.) |
| C7 | The only transformation applied is trimming surrounding whitespace. No case folding, no prefixing, no substitution, no rejection. |
| C8 | An id absent from `config.models` MUST be accepted without warning, marker, or styling that suggests it is irregular. |
| C9 | An id incompatible with the active backend (last row) is **stored**, not blocked at entry. The refusal is `resolve_selection`'s job and is surfaced by the resolved-selection preview before a run — see §4. |

**C9 is deliberate.** Blocking at the keystroke would put a second, weaker copy of
the compatibility rule in the browser, and it would fight the GM mid-type
(`claude-` is not yet a valid id). One rule, one place, reported at the point of
consequence.

---

## 3. Persistence

| Requirement | Contract |
|---|---|
| C10 | A change issues exactly one `PUT /api/config/runtime` carrying `default_model` and the full `default_models` map. |
| C11 | After reload, the control shows the stored value for the active backend, whether curated or typed. |
| C12 | Switching backend A → B → A restores A's remembered value unchanged, including a typed one. |
| C13 | Switching to a backend with no remembered model yields `""` (defer), not another backend's model and not a curated default. |

C13 is existing behaviour (`setBackend`) and is pinned here because the new input
makes `""` visible on the Claude backends for the first time.

---

## 4. Reporting

| Requirement | Contract |
|---|---|
| C14 | `SelectionPanel.vue` reports a typed model with the same `model_origin` labelling as a curated one. No new origin value is introduced. |
| C15 | An incompatible pair produces the existing refusal string, before any token-spending run starts. |
| C16 | Nothing anywhere records or displays *how* a model id was entered. |

C16 is the property that makes C14 and FR-005 hold by construction: there is no
provenance bit, so no downstream consumer can branch on one.

---

## 5. Out of contract

- The contents of `config.models` (see `config-models-api.md`).
- Whether a typed id names a real model — unknowable locally; the provider's error
  at call time is the answer, reported verbatim.
- Accumulating typed ids into the suggestion list — declined for v1 (spec
  Assumptions).
