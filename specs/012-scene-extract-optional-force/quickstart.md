# Quickstart: Validate Optional Force for Scene Re-Extraction

Manual validation in the running Session Doc Editor — this repo has no
frontend test harness, so per `CLAUDE.md`'s UI-change rule, this is the
"start the dev server and use the feature in a browser" step, covering the
three user stories in `spec.md`.

## Prerequisites

- `startup` running (builds frontend, starts the FastAPI server) against a
  campaign workspace with a session that has already run Stage 1 (Enhance
  Summary), so `session-summary.md` and at least a partial
  `scene_extractions_new/` exist.
- `ANTHROPIC_API_KEY` set (Stage 2 calls the API).

## Scenario 1 — default run only fills missing scenes (P1, FR-001/003/004/005)

1. Open the Session Doc Editor for a session where `N-2` of `N` scenes
   already have extraction files (delete 2 scene files from
   `scene_extractions_new/` to simulate this, or use a session mid-Stage-2).
2. Leave the Force control unchecked (its default state).
3. Click **Re-Extract Quotes**.
4. **Expected**: the streamed output shows `Skipping (already exists): ...`
   for the `N-2` scenes and `Scene-extracting: ...` only for the 2 missing
   ones. `ls scene_extractions_new/` shows exactly 2 new files; the other
   `N-2` files' mtimes and any `.reviewed` markers are unchanged.

## Scenario 2 — nothing to do (P1 edge case)

1. From the state left by Scenario 1 (all `N` scenes now present), click
   **Re-Extract Quotes** again with Force still unchecked.
2. **Expected**: every scene reports `Skipping (already exists): ...`; the
   status line communicates nothing needed to run; no file changes.

## Scenario 3 — explicit Force redoes everything (P2, FR-002/003/006/007)

1. With all `N` scenes present and at least one marked reviewed, check the
   Force control next to **Re-Extract Quotes**. Confirm its label/tooltip
   states this will overwrite every scene and clear reviewed markers
   (P3, FR-007) before clicking.
2. Click **Re-Extract Quotes**.
3. **Expected**: every scene reports `Re-extracting: ...`; each changed
   scene gets a `.prev` snapshot; every `.reviewed` marker is cleared.
4. Reload the page (or navigate away and back). **Expected**: the Force
   control is unchecked again — it did not persist (FR-006).

## Scenario 4 — backend contract still holds directly (sanity check)

`curl -N "http://localhost:<port>/api/editor/extract"` (no `force` param,
against a session with all scenes present) should behave identically to
Scenario 2 — confirms the default lives in the already-correct backend
default (`force: int = 0`), not something the frontend has to inject twice.

## Pass criteria

All four scenarios match their "Expected" outcomes, and Success Criteria
SC-001–SC-005 in `spec.md` hold: exact scoping to missing scenes by default,
no lost reviewed status on default runs, one-action full redo still
available, real reduction in LLM calls for a mostly-complete session, and
zero full overwrites without the explicit Force action.
