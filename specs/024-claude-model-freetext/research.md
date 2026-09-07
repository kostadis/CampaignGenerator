# Phase 0 Research: Hand-Entered Claude Model Ids

Eight decisions. R2, R3 and R5 record findings that change what the feature must
do relative to the spec's assumptions; the rest confirm or bound the approach.

---

## R1 — What the combo control is built from

**Decision**: One `<input class="model-select" list="cg-model-ids">` rendered on
**every** backend, paired with a `<datalist id="cg-model-ids">` populated from
`config.models` when a Claude backend is active and empty otherwise. The existing
`v-if="modelIsFreeText"` / `v-else` fork is deleted along with the
`modelIsFreeText` computed.

**Rationale**:

- **No new dependency.** `frontend/package.json` has exactly three runtime deps
  (`vue`, `vue-router`, `pinia`). `<datalist>` is native HTML; a combobox library
  would be the largest thing this feature drags in, for one control.
- **It makes FR-011 structurally true, not just true today.** With one element on
  all five backends there is no fork left to diverge. A `<select>` plus an
  "Other…" escape hatch would keep the fork and add a sentinel value that can be
  persisted by accident.
- **It preserves SC-004.** In Chromium the list opens on click, so picking a
  curated id is click-open → click-item: the same two interactions and the same
  zero keystrokes a `<select>` costs today.
- **It keeps the existing styling and handler.** The free-text branch already uses
  `<input class="model-select" @change="setModel(…)">`; the Claude branch adopts
  that shape rather than inventing one.

**Alternatives considered**:

| Option | Rejected because |
|---|---|
| `<select>` + an "Other…" sentinel option that reveals an input | Two controls and a magic value. `Other…` is a string that can reach `default_model` through any path that does not special-case it, and the backend fork survives. |
| A hand-rolled combobox component | Owning focus management, keyboard navigation and ARIA for a single-operator local app, to reproduce what the browser already does. |
| Drop the shortlist; make it a bare text field | Direct SC-004 regression, and the GM asked to be *able* to type — not to be required to. Explicitly declined in the spec's Assumptions. |

**Caveats to carry into implementation**: `<datalist>` entries are *suggestions* —
nothing is ever "selected", so `displayedModel` remains the single source of the
control's value and no selected-option state is introduced. Browsers filter the
list against typed text, which is a feature here (typing `opus` narrows to the
Opus ids) but means the full list is only visible on an empty field.

---

## R2 — Where the capability warning actually misfires

**Finding (changes the scope picture)**: the warning at
`server/routers/ensemble.py:1148` is guarded by `backend != "anthropic"`:

```python
if backend != "anthropic" and model and model not in SYNTHESIS_CAPABLE:
```

So it **never fires on the metered Anthropic backend** — the case the spec's edge
case implied. It fires on `claude-code`, `dgx`, `openrouter` and `codex-cli`.
That makes the defect narrower but *worse* than assumed: `claude-code` is the
subscription Claude backend, where a brand-new Claude id is the expected input,
and where `SYNTHESIS_CAPABLE` holds only ids from the Anthropic snapshot. A GM who
types tomorrow's Opus there is told their strongest available model may be too
weak.

**Decision**: replace the set-membership test with a predicate,
`synthesis_capable(model) -> bool`, exported from the same module:

- an id carrying the sub-Sonnet tier marker is **not** capable (FR-013 — this is
  the one genuine judgement, preserved);
- an Anthropic-shaped id (`claude-…`, and the OpenRouter spelling
  `anthropic/claude-…` per R4) is capable;
- anything else falls back to membership of `_THIRD_PARTY_SYNTHESIS_CAPABLE`,
  which is unchanged.

**Rationale**: this is `compatible()`'s reasoning applied to a second question.
The tier exclusion is a human capability judgement and survives; "I have never
heard of this id" is not evidence of anything and stops being treated as such.

**Alternatives considered**: suppress the warning whenever the model was
hand-entered — rejected, the server cannot know how a string was typed, and it
would silence the warning for genuinely weak hand-entered ids too, breaking
FR-013. Extend `MODELS` on each release — rejected, that is the treadmill the
feature exists to end.

---

## R3 — `SYNTHESIS_CAPABLE` is deleted, and one existing test flips

**Decision**: remove the `SYNTHESIS_CAPABLE` set entirely; keep `_SUB_SONNET_TIER`
and `_THIRD_PARTY_SYNTHESIS_CAPABLE` as the predicate's inputs.

**Rationale**: a derived set that no longer decides anything is a second
declaration of a rule with an owner — Principle XII's "a default duplicated into a
second place is a Split-Brain that has not diverged *yet*." Only
`ensemble.py` and `tests/test_synthesis_capable_registry.py` import it.

**Consequence that must not be mistaken for a regression**:
`test_retired_date_suffixed_id_is_gone` asserts `"claude-sonnet-4-20250514" not in
SYNTHESIS_CAPABLE`. Under the predicate that id *is* capable — it is a Sonnet, and
the bar is "at least as capable as Sonnet". The test changes. Two reasons this is
correct and not a weakening:

1. The assertion pinned **snapshot freshness** — that a derived set had dropped a
   retired entry. Once nothing is snapshotted, the property it guarded no longer
   exists to be violated.
2. "May be too weak" was always the wrong message for a retired model. Retirement
   is reported by the provider's error at call time, not by a capability warning.
   Answering "this model no longer exists" with "this model may be weak" sends the
   GM to change a knob that is not the problem.

The module's other tests (registry models are capable, the Haiku tier is not,
frontier third-party ids survive, the platform default never warns about itself)
all hold under the predicate and are re-pointed at it rather than rewritten.

---

## R4 — The OpenRouter spelling, and why the two rules stay separate

**Decision (a)**: the predicate recognises `anthropic/claude-…` as Anthropic-shaped.

**Rationale**: `_THIRD_PARTY_SYNTHESIS_CAPABLE` lists `anthropic/claude-sonnet-4`
and `anthropic/claude-opus-4` by hand, so it goes stale on the OpenRouter side on
exactly the same schedule. The vendor prefix makes the id unambiguously Anthropic
and the same tier logic applies. The set keeps the genuinely non-derivable
`openai/…` and `google/…` entries, which no rule in this repo can infer.

**Decision (b)**: `synthesis_capable()` stays in `server/routers/ensemble.py`; it
is **not** merged with `campaignlib/selection.py::compatible()` into a shared
helper.

**Rationale**: they answer different questions — *can this backend serve this
model* versus *is this model strong enough for this stage* — and they disagree by
design (`claude-haiku-4-5` is perfectly compatible with the Anthropic backend and
deliberately not synthesis-capable). Merging them would produce one function with
two meanings, which is the failure Principle XII actually forbids. What is shared
is the *inference style*, and that is enforced by the tests, not by a call.

---

## R5 — A whitespace split-brain in `setModel`

**Finding**: `AppSidebar.vue::setModel` trims into the per-backend memory but
persists the raw value as the active model:

```ts
modelMemory.value[currentBackend.value] = value.trim()
config.model = value
await config.updateRuntime({ default_model: value, default_models: { …modelMemory.value } })
```

A pasted `" claude-opus-5 "` therefore writes `claude-opus-5` into
`default_models` and `" claude-opus-5 "` into `default_model` — two different
strings for one choice, from one function, in one write. Today only the three open
backends can reach it; after this feature every backend can.

**Decision**: trim once at the top of `setModel` and use the trimmed value for all
three assignments.

**Rationale**: FR-005 permits exactly one normalisation, and the fix makes the
function honour it consistently rather than half the time.

---

## R6 — Empty entry: already correct, newly reachable

**Finding**: nothing needs to change for FR-006.

- `PlatformRuntime.default_model` is a plain `str`, so `""` persists literally.
- `setBackend` already writes `""` when switching to a backend with no remembered
  model, so `""` is an established stored value, not a new state.
- `_cmd_opt` skips falsy values, so no `--model` flag is emitted and the CLI's own
  default applies.
- `compatible(None|"", backend)` returns `True` — "an absent model is vacuously
  compatible: it means *nothing chosen*, which resolution handles by falling back,
  not by refusing."

**Decision**: no schema or resolution change. Add a test pinning the behaviour on
the Claude backends, which could not previously reach an empty model at all.

---

## R7 — How the UI half gets tested

**Finding**: there is no Vue component-test harness (issue #345, stated in
`tests/test_claude_code_effort_ui.py`'s docstring). But Playwright **is** wired up
(`frontend/playwright.config.ts`) against the Vite dev server with route mocking
and `reuseExistingServer`, so an e2e spec needs no backend and no campaign.

**Decision**: three layers, matching what the repo already does plus one it can
now afford.

| Layer | Proves | Where |
|---|---|---|
| pytest source guardrails | The control exists, the fork is gone, no backend-conditional entry mechanism has crept back | `tests/test_model_selector_ui.py` |
| Playwright e2e, route-mocked | The real behaviour: typing an unlisted id, the `PUT /api/config/runtime` payload it produces, reload persistence, per-backend memory across a switch | `frontend/e2e/model-selector.spec.ts` |
| pytest, server-side | The predicate, the warning text, the compatibility refusal | `tests/test_synthesis_capable_registry.py` |

**Rationale**: the guardrail-only pattern was a limitation, not a preference — its
own docstring says "these prove a control is present in the file, not that it
renders, persists, or round-trips." Persistence is the heart of FR-003/FR-004, so
this feature should not settle for a text search. The e2e asserts on the
intercepted request body, which is the actual contract.

---

## R8 — Audit: is anything else gated on `MODELS`?

**Finding**: three consumers, and only two are gates.

| Consumer | Uses `MODELS` to | Gate? |
|---|---|---|
| `server/routers/config_routes.py:159` | Publish the list to the frontend | No — it is the suggestion source, and stays |
| `server/routers/ensemble.py:110` | Derive `SYNTHESIS_CAPABLE` | **Yes** — fixed here (R2) |
| `campaignlib/selection.py:154` | Nothing — the docstring explains at length why it deliberately does *not* | No |

Plus `AppSidebar.vue`, which consumes the published list as `<option>`s — the
other gate, fixed here.

**Decision**: this closes the audit. The GM's ruling (selector + capability
warning) covers every place `MODELS` is treated as authoritative; the broader
"audit every model-facing surface" option would have found nothing further. If a
third gate appears later it is a defect to file, per the spec's Assumptions.

**Note for the future**: `server/config.py`'s own docstring records that moving
`MODELS`' *source* into `wiring.yaml` — so the suggestion list itself can be
extended without a release — is a deferred Phase 5b needing a change in the
separate `mneme` repo. This feature makes that strictly optional: after it,
`MODELS` being stale costs the GM some typing, not the ability to run a model.
