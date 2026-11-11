# HTTP Contract: `/api/summary-native/delta/rebase`

Thin routes in `server/routers/summary_native_delta.py`. They use `build_delta_argv` and the existing `_json` / `_sse` helpers, hold no pipeline logic (Principle VI), and introduce no default literals (Principle XII).

| CLI command | Route | Method |
|---|---|---|
| `delta rebase inspect` | `/rebase/inspect` (query `plan`) | GET |
| `delta rebase prepare` | `/rebase` (body: `sources[]` required, non-empty; `old_bytes{chapter: path}`; `for_plan`) | POST |
| `delta rebase show` | `/rebase/{plan_id}` | GET |
| `delta rebase propose` | `/rebase/{plan_id}/propose` (body: backend, model) | POST (stream) |
| `delta rebase repair` | `/rebase/{plan_id}/repairs` (body: `line`+`text`, or `hold_entry` `CH/ENTRY` for a bulk hold; `reason`, `reviewer`) | POST |
| `delta rebase decide` | `/rebase/{plan_id}/decisions` (body: reviewer, source_decisions{}, member_decisions{}, reason) | POST |
| `delta rebind` (top-level leaf) | `/plans/{plan_id}/rebind` (body: baseline) | POST |

An empty `sources` returns 400 before any subprocess runs (Principle X). A missing `reviewer` returns 400. Exit codes map to HTTP status through the existing `_status_for`.

## UI: `frontend/src/views/grounding/SourceRebase.vue` (route `grounding-rebase`)

The page has four steps. Each step reads the CLI's `--json` output; the page keeps no state beyond what is in the files.

1. **Inspect.** A table of stale sources with expected/actual digests and providers. Checkboxes build the explicit selection: nothing is preselected, and an empty selection disables Prepare.
2. **Review.** Per source: the diff, affected lines (with repair and hold status) and unknown-impact members. A repair editor posts to `/repairs`. Repair decisions use the existing `/grounding/proposals/{id}/decision` route.
3. **Decide.** Per-source and per-member radio controls with no preselection. The reviewer field is required.
4. **Publish.** Links to the existing grounding preview/apply and claims/signoff steps for the rebase plan id, followed by "Rebind pending plan" when a `for_plan` was given.

A Vitest component test covers the following: empty selection disables Prepare; there is no preselected decision; the reviewer field is required.
