# HTTP Contract: `/api/summary-native/delta`

Thin routes in `server/routers/summary_native_delta.py`. Each route builds argv from `console_script("summary_native")` plus the `delta` command in `contracts/cli.md`, and runs it with `run_bounded_json` (for JSON reads) or streams it over SSE (for long stages). The router holds no pipeline logic (Principle VI). Defaults come from the owning config model, not from literals in the router (Principle XII).

## Parity map

| CLI command | Route | Method |
|---|---|---|
| `delta plan` | `/plans` | POST |
| `delta sources` | `/plans/{id}/sources` | POST |
| `delta baseline status` | `/plans/{id}/baseline` | GET |
| `delta baseline adopt` | `/plans/{id}/baseline/adopt` | POST |
| `delta census` | `/plans/{id}/census` | POST (stream) |
| `delta associate propose` | `/plans/{id}/associations/propose` | POST (stream) |
| `delta associate decide` | `/associations/{id}/decision` | POST |
| `delta npc draft` | `/plans/{id}/npc/draft` | POST (stream) |
| `delta npc verify` | `/plans/{id}/npc/verify` | POST (stream) |
| `delta npc attest` | `/plans/{id}/npc/{subject}/attest` | POST |
| `delta npc publish` (preview: no `--preview-sha`, `--json`) | `/plans/{id}/npc/publish/preview` | POST |
| `delta npc publish` | `/plans/{id}/npc/publish` | POST (stream) |
| `delta grounding propose` | `/plans/{id}/grounding/propose` | POST (stream) |
| `delta grounding decide` | `/grounding/proposals/{id}/decision` | POST |
| `delta grounding check` | `/plans/{id}/grounding/check` | POST (stream) |
| `delta grounding preview` | `/plans/{id}/grounding/preview` | POST |
| `delta grounding apply` | `/plans/{id}/grounding/apply` | POST (stream) |
| `delta run status` | `/plans/{id}/status` | GET |
| `delta run resume` | `/plans/{id}/resume` | POST (stream) |
| `delta receipt` | `/plans/{id}/receipt` | GET |
| `delta review show` | `/plans/{id}/review` | GET |
| `delta review handoff` | `/plans/{id}/review/handoff` | POST |
| `delta transfer verify` | `/transfer/verify` | POST |
| `delta transfer bind` | `/transfer/bind` | POST |

Every write route returns the same record the CLI writes under `--json`. The response does not add or drop fields. `test_delta_parity.py` checks this.

## Conventions

- **Bodies** are JSON that maps to CLI flags. Sources are a list, never a glob or a "select all" flag. An empty list returns 400 with the CLI's refusal text.
- **Decisions** (`/associations/{id}/decision`, `/grounding/proposals/{id}/decision`) carry `reviewer` in the body; the CLI refuses a decision with none (exit 2, HTTP 400).
- **NPC publication is two calls.** `POST .../npc/publish/preview` with `{members}` runs `npc publish --member … --json` (no `--preview-sha`), writes nothing and returns the record with `preview_sha256`. `POST .../npc/publish` then takes `{members, preview_sha}`; without `preview_sha` it returns 400.
- **SSE** streams for long stages use the existing SSE shape from the summary-native run routes: `event: line` for output, `event: exit` with the exit code. The client may reconnect; the run continues on disk, and `/status` reports where it is.
- **Errors** carry the CLI exit code and reason. Exit 3 (stale) returns 409. Exit 4 (partial) returns 207 with per-member outcomes. Exit 5 (recovery) returns 409 with the recovery command.
- **Capabilities**: no capability URL or access token appears in any response or receipt (FR-023). Review hosting, if used, is a separate runtime setting.

## Page: `DeltaRun.vue` (`/grounding/delta`)

A stepper over the stages in `status`, one control per route above.

- Source picker: lists chapters the operator selects by checkbox. "Select all" writes every resolved chapter into the explicit list. The page never sends an implicit set (Principle X).
- Decisions need a reviewer name entered on the page (a per-viewer remembered convenience only; never sent empty). NPC publication is Preview then Publish: the page shows the previewed digest and members, and publishes exactly those with that digest; editing the member list discards the preview.
- Each stage shows the files it produced (Principle VIII). Judgments (associations, grounding proposals, attestations, publication) are entered on this page or in the CLI, and each is a file. The page holds no state that the CLI cannot see (Principle IX).
- Status banner shows `stale`, `partial` and `recovery_required` from `/status`, read on load, so a restart shows the same state.
