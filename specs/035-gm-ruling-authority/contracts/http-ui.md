# HTTP and UI Parity Contract

The Summary Native router invokes CLI commands through the existing subprocess runner. It validates request syntax and campaign paths only; it does not reimplement authority policy.

## Read routes

| Method and path | Query/response |
|---|---|
| `GET /api/summary-native/authority/status` | Returns ledger revision/digest, pending transaction, stale projections, and initialization state. |
| `GET /api/summary-native/authority/records` | Optional `status`; returns summaries safe for the authenticated local GM view. |
| `GET /api/summary-native/authority/records/{id}` | Returns record, proposal/receipt links, conflicts, and current revision. |
| `GET /api/summary-native/authority/records/{id}/history` | Returns immutable AuthorityEvents and source receipts. |
| `GET /api/summary-native/authority/conflicts` | Optional `status`; returns structured/human findings and dispositions. |
| `GET /api/summary-native/authority/conflicts/{id}/history` | Returns the exact conflict and immutable events referencing that conflict ID. |

Successful reads return the CLI JSON `data` envelope. Missing record is 404; validation/stale/recovery/conflict classes map to 422/409/423/409 with the unchanged stable `code`.

## Preview and validation routes

| Method and path | Request body | Response |
|---|---|---|
| `POST /api/summary-native/authority/validate` | `{}` | Validation envelope and artifacts. |
| `POST /api/summary-native/authority/notes/preview` | `{audience}` | GM members include concrete paths, reasons, external flags, member digest, and `records[{id, classification, audience, effective, status, anchor, section_sha256}]`, plus `selection_sha256`; non-GM failures are generic before paths can surface. |
| `POST /api/summary-native/authority/records/stage` | `{record_file}` | CLI envelope `data: {id, record, sha256}`; use `id` and `sha256` for guarded apply. |
| `POST /api/summary-native/authority/records/{id}/propose` | `{}` | Proposal ID/digest and exact before/after artifact paths. |

These invoke read-only/proposal CLI commands and return JSON after subprocess completion. File arguments must resolve through the campaign's allowed local paths.

## Mutation routes

| Method and path | Required body |
|---|---|
| `POST /api/summary-native/authority/init` | `{campaign_dir}` |
| `POST /api/summary-native/authority/records/stages/{id}/apply` | `{stage_sha256, expected_ledger_sha256}` |
| `POST /api/summary-native/authority/records/{id}/retire` | `{reason, expected_revision, expected_ledger_sha256}` |
| `POST /api/summary-native/authority/records/{id}/apply` | `{proposal_sha256}` |
| `POST /api/summary-native/authority/records/{id}/withdraw` | `{reason}` |
| `POST /api/summary-native/authority/conflicts/{id}/resolve` | `{resolution_record_file, expected_ledger_sha256}` |
| `POST /api/summary-native/authority/conflicts/{id}/dismiss` | `{reason, expected_ledger_sha256}` |
| `POST /api/summary-native/authority/conflicts/identify` | `{id, record_ids, basis, reason, expected_ledger_sha256}` |
| `POST /api/summary-native/authority/transactions/{id}/recover` | `{}` |

Mutations stream the invoked CLI's stdout/stderr as the existing Summary Native SSE operation format. The terminal event contains the full CLI JSON envelope with artifact paths, final record/transaction ID, and ledger digest. The router cannot synthesize a missing digest or convert a CLI refusal into success.

Conflict list data includes each compared record's source path and anchor, normalized value, effective scope, and projections. Invalid conflict IDs, record IDs, basis, paths, and stale digests retain the CLI validation/stale envelopes and their HTTP mapping.

Planning synthesis request adds exact fields `authority_selection` and `audience`, mapped to `--authority-selection` and `--audience`. Planning selector CRUD remains owned by the existing `/api/planning/*` service and persists the strict selector model.

## Summary Native page

`frontend/src/views/grounding/SummaryNative.vue` exposes:

- initialize authority ledger;
- stage/apply/retire record revisions;
- authority status and pending-transaction banner;
- planning note-selector editor and concrete audience preview;
- source proposal exact diff and explicit digest-bound apply;
- withdrawal and reversal proposal review;
- conflict resolution record staging;
- history, events, proposals, receipts, and stale projections;
- idempotent recovery and unexpected-byte inspection.

The page stores no unique authority state. Refresh reconstructs it from files through the routes. It does not add issue #547's discussion/adjudication queue.

## Parity acceptance

End-to-end tests assert each delivered CLI operation/meaningful option has a UI invocation, including init, record mutation, conflict resolution, apply, withdrawal, and recovery. CLI and UI must display the same selection/proposal/stage digest and final record/event/receipt IDs.
