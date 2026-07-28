# Quickstart: Validating Batch in the UI

**Feature**: 005-ui-batch-selection. Scenarios proving the spec's success criteria. Details in [contracts/](contracts/) and [data-model.md](data-model.md).

## Prerequisites

- Server running from a campaign workspace (`./startup`); the package editable-installed into the server's venv so console scripts resolve.
- `ANTHROPIC_API_KEY` set. Scenarios 1 and 6 spend real tokens.
- A campaign with enough material for a multi-unit run (the OOTA checkout works).

## 1. Batch is reachable and actually discounted (SC-001)

1. Sidebar → turn batch **on** app-wide.
2. Open a grounding page (e.g. Distill World State) and confirm the run controls show batch on, attributed to the app-wide setting.
3. Run it.

**Expect**: the streamed output opens with `Batch submitted: msgbatch_… (N requests)`, shows periodic progress lines, and ends in a normal success state with the usual draft artifact in its usual place. Billing shows the batch rate.

## 2. Every in-scope surface offers the control (SC-002)

Walk each page that shows a model/backend selection — grounding ×4, session prep, npc table, query, dnd sheet, make tracking, planning, party, session doc editor, ensemble setup — and confirm a batch control is present with its origin.

**Expect**: present on every one of them. The single documented absence is the Connection Graph (out of scope, FR-013) — and its absence should be total, not a disabled control. (The optional polish pass also cannot batch, but it is not exposed in the UI at all, so there is nothing to check.)

## 3. Inheritance and override (SC-003 / FR-002)

1. With batch on app-wide, confirm several service pages show it as inherited.
2. On one service, override batch **off**. Confirm only that service changes and its page attributes the value to the service override.
3. Turn the app-wide setting **off**, then on again.

**Expect**: the overriding service keeps its own value through both changes; every deferring service follows.

## 4. An unsatisfiable batch selection refuses — it never runs at full price (SC-004 / FR-005, FR-006, FR-006a)

1. Set one service's backend to DGX or OpenRouter while batch is selected.

**Expect**: the page shows the selection as incompatible, names batch as the cause, and the Run button is disabled — the same refusal treatment an incompatible model/backend pair already gets.

2. Attempt the run anyway (e.g. by issuing the request directly).

**Expect**: it fails with `incompatible_selection` and that reason. Critically: **no run executes at full price.** Check billing shows no charge for an unintended standard-rate run.

3. Use the remedy offered in the refusal (clear the batch selection, or change the backend back).

**Expect**: the run becomes available immediately.

4. Repeat with batch inherited from the app-wide setting rather than a service override.

**Expect**: identical refusal — the outcome does not depend on which tier chose batch; only the displayed origin differs, telling you which switch to flip.

## 5. Degradation is stated up front (FR-010)

Open Session Prep or the narrate stage and arm batch.

**Expect**: before running, the page states that steps run one at a time — slower than a grouped batch, same discount.

## 6. Abort cancels the remote batch (SC-006 / FR-012)

Start a multi-unit batch run from a grounding page, then hit Abort mid-run.

**Expect**: the run ends in the aborted state, and the streamed output shows the cancellation being requested. Confirm via the batch id printed at submission that the remote batch is canceling/canceled — no orphaned work still billing. Repeat by closing the tab instead of clicking Abort (a lost connection is an implicit abort per spec 002).

## 7. Partial failure reads as failure (FR-009)

Best exercised in tests rather than live. Confirm a run whose batch had a failed unit ends **failed**, names the failed unit, and leaves succeeded units' artifacts on disk.

## 8. The migrated Session Doc Editor path still works (FR-011)

Run the Stage 1 (enhance) and Stage 2 (extract) actions with batch on, now driven by the unified control rather than the retired checkbox.

**Expect**: identical behavior to the old checkbox — batch submission, poll progress, files written. Confirm no `?batch=1` remains in the requests the page issues.

## 9. Nothing changed with batch off (SC-005)

```bash
env -u PYTHONPATH ~/.venvs/main/bin/python -m pytest -q
cd frontend && npm run build
```

**Expect**: suite green except the known pre-existing failures (note the 3 in `test_service_selection_override.py` that already fail on `main` — establish their status before starting, per the plan); frontend builds clean. With batch off, every run behaves exactly as before.
