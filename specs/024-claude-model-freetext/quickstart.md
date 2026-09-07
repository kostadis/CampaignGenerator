# Quickstart: validating hand-entered Claude model ids

Proves the feature end to end. §1–§3 are automated and belong in CI; §4 is the
manual pass that covers what no harness in this repo can (issue #345).

**Prerequisites**

- The venv the server runs under, with the package editable-installed:
  `uv pip install -e . --python "$VIRTUAL_ENV/bin/python"`
- `cd frontend && npm install` for the Playwright run
- A campaign workspace for §4. No `ANTHROPIC_API_KEY` is needed for §1–§3; §4.6
  needs whichever backend you exercise to be usable.

Throughout, **`claude-opus-6` stands for "a model id the app has never heard
of."** It does not exist. That is the point — if it did, the test would prove
nothing. Substitute a genuinely new id when one ships.

---

## 1. Server predicate

```bash
python -m pytest tests/test_synthesis_capable_registry.py -v
```

**Expected**: all pass, including the four new cases from
`contracts/synthesis-capability.md`:

- `claude-opus-6` → capable (the regression this feature prevents)
- `claude-haiku-6` → **not** capable (S1 — tier check beats prefix check)
- `anthropic/claude-opus-6` → capable (rule 4)
- a `claude-code` synthesize run with an unlisted Claude model emits no
  `is not on the synthesis-capable list`; one with an unlisted Haiku id still does

**Expected to have changed**: `test_retired_date_suffixed_id_is_gone` is replaced.
If it is still present and passing, the predicate was not actually adopted — the
set is still there. See `contracts/synthesis-capability.md` § Test migration.

## 2. UI guardrails

```bash
python -m pytest tests/test_model_selector_ui.py -v
```

**Expected**: the sidebar renders one `<input list=…>`, a `<datalist>` fed from
`config.models`, and **no** `modelIsFreeText` computed and no backend-conditional
element fork (contract C1/C2).

## 3. Behavioural round-trip

```bash
cd frontend && npx playwright test e2e/model-selector.spec.ts
```

Route-mocked; no backend and no campaign required. **Expected**:

| Assertion | Contract |
|---|---|
| Typing `claude-opus-6` on the `anthropic` backend issues one `PUT /api/config/runtime` whose body carries `default_model: "claude-opus-6"` | C10 |
| `default_models.anthropic` in that same body is the identical string | C6 |
| Pasting `"  claude-opus-6  "` sends the trimmed value in **both** fields | C6/C7 — this is the R5 defect; it fails before the fix |
| After reload the field still reads `claude-opus-6` | C11 |
| anthropic → dgx → anthropic restores `claude-opus-6` | C12 |
| The curated ids are present as `<datalist>` options on both Claude backends and absent on the other three | C3 |

## 4. Manual — the parts no harness covers

Start the app (`./startup`) and open the sidebar.

1. **The list still works.** On the API backend, click MODEL. The curated ids drop
   down; click one. Applied, no typing. *(SC-004 — if this got worse, the feature
   failed even if everything else passes.)*
2. **Type an unknown id.** Enter `claude-opus-6`, press Tab. It sticks. Nothing
   warns, marks, or restyles it. *(FR-001, C8)*
3. **It survives a reload.** Refresh. Still `claude-opus-6`. *(FR-003)*
4. **Per-backend memory.** Switch to Sub, type `claude-opus-6`; switch to DGX, type
   `Qwen/Qwen3-Next-80B`; switch back to Sub. Your Claude id is back. *(FR-004)*
5. **Every backend looks the same.** Click through all five. Same widget each time
   — only the placeholder and the suggestions change. *(FR-011, C1)*
6. **A run uses exactly what you typed.** Set a *real* new model id and start any
   single-model pass. The echoed command carries that id verbatim. *(FR-005)*
7. **Clearing means defer.** Empty the field on the API backend. Open a page with
   a resolved-selection panel: the model reads as the script default, not `""`.
   *(FR-006)*
8. **Incompatible pairs still refuse.** With the API backend active, type
   `Qwen/Qwen3-80B`. The resolved-selection panel shows
   `"Qwen/Qwen3-80B" is not a valid model for the anthropic backend.` — before you
   start anything. *(FR-008, C9, C15)*
9. **The capability warning is fixed and still alive.** On the Ensemble page with
   the **Sub (`claude-code`)** backend — *not* the API backend, where the warning
   never fires — set synthesis to `claude-opus-6` and start a run: no "may be too
   weak" warning. Set it to `claude-haiku-6` and start again: the warning appears.
   *(FR-012, FR-013, SC-007)*
10. **A wrong id fails honestly.** Type `claude-opus-6-typo` and run. The provider's
    own error appears; the app does not claim to have validated it. *(spec edge
    case)*

---

## What "done" looks like

Every FR has a home above:

| FR | Proven by |
|---|---|
| FR-001, FR-002 | §4.1, §4.2 |
| FR-003, FR-004 | §3, §4.3, §4.4 |
| FR-005 | §3 (trim), §4.6 |
| FR-006 | §4.7 |
| FR-007, FR-008 | §4.8 |
| FR-009 | §4.7, §4.8 (the panel reports it like any other) |
| FR-010 | The whole run: no file edited, no restart taken |
| FR-011 | §2, §3, §4.5 |
| FR-012, FR-013 | §1, §4.9 |

**And the meta-check for SC-002**: you reached a new model without editing a
tracked file. If validating this required touching `server/config.py`, the feature
is not done.
