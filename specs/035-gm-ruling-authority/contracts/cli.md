# CLI Contract

All commands run through the existing `summary_native` entry point. Shared options retain their current meaning. Machine-readable operations support `--json` and return stable numeric exits.

## Ledger and record operations

```text
summary_native authority init --campaign-dir DIR
summary_native authority list [--status STATUS] [--json] [--config PATH]
summary_native authority show ID [--json] [--config PATH]
summary_native authority validate [--json] [--config PATH]
summary_native authority history ID [--json] [--config PATH]
summary_native authority status [--json] [--config PATH]

summary_native authority record stage RECORD_FILE [--json] [--config PATH]
summary_native authority record apply STAGE_ID --stage-sha256 SHA --expected-ledger-sha256 SHA [--json] [--config PATH]
summary_native authority record retire ID --reason TEXT --expected-revision N --expected-ledger-sha256 SHA [--json] [--config PATH]
```

`record stage` accepts one strict typed ruling/note record document and writes an immutable proposed ledger revision without changing `docs/authority.yaml`. `record apply` is the explicit acceptance checkpoint and writes the ledger plus AuthorityEvent under the writer lock/journal. `record retire` never deletes history. Direct manual YAML edits are detected as unrecorded ledger digest changes and `validate` refuses them until staged and accepted.

## Selection and conflict operations

```text
summary_native authority notes preview --audience TARGET [--json] [--config PATH]
summary_native authority conflicts [--status STATUS] [--json] [--config PATH]
summary_native authority conflict resolve ID --resolution-record RECORD_FILE --expected-ledger-sha256 SHA [--json] [--config PATH]
summary_native authority conflict identify ID --record RECORD_ID [--record RECORD_ID ...] --basis human_identified|prose_candidate --reason TEXT --expected-ledger-sha256 SHA [--json] [--config PATH]
summary_native authority conflict dismiss ID --reason TEXT --expected-ledger-sha256 SHA [--json] [--config PATH]
summary_native authority conflict history ID [--json] [--config PATH]
```

Preview materializes the exact selection and returns `selection_sha256`. Empty/missing/unreadable/zero-match configured selections exit 2. `conflict resolve` records a human resolution and optional superseding ruling through the same staged ledger mutation path; it does not add a generic review queue.

`conflicts` returns each finding with its compared records' source pointer, anchor, normalized value, effective scope, and affected projections. `identify` records a human finding; `dismiss` preserves an explicit GM disposition; both bind the reviewed ledger digest and reason. `history` returns only events whose parsed `conflict_id` matches exactly.

## Source correction operations

```text
summary_native authority propose ID [--json] [--config PATH]
summary_native authority apply ID --proposal-sha256 SHA [--json] [--config PATH]
summary_native authority withdraw ID --reason TEXT [--json] [--config PATH]
summary_native authority recover TRANSACTION_ID [--json] [--config PATH]
```

- `propose` writes immutable before/after artifacts; it does not alter source.
- `apply` is the human checkpoint and records a separate approval event binding the exact displayed proposal digest.
- `withdraw` creates a withdrawal request/reversal proposal and never reverts source automatically.
- `recover` is idempotent and refuses unexpected bytes.
- `--force` never bypasses digest, approval, audience, target, lock, or recovery gates.

## Planning synthesis integration

```text
summary_native synth planning ... --authority-selection SHA --audience TARGET
```

`--authority-selection` names the reviewed materialized preview. `--audience` uses exactly `gm`, `players`, `characters`, or `character:<stable-id>`. When configured planning notes are present, both are required. A changed/missing preview, pending transaction, stale authority manifest, or unresolved blocking structured conflict refuses before a model call. Sibling commands that consume the same audience-aware inputs use the same option names and semantics.

## Exit and JSON contract

| Exit | JSON `code` class | Meaning |
|---:|---|---|
| 0 | `OK` | Completed; validation has no blocking finding. |
| 2 | `AUTH_VALIDATION` | Invalid ledger, record, selection, audience, target, or source. |
| 3 | `AUTH_STALE` | Proposal, stage, selection preview, source, manifest, or draft is stale. |
| 4 | `AUTH_RECOVERY` | Pending/unexpected transaction state requires recovery or inspection. |
| 5 | `AUTH_CONFLICT` | Blocking structured conflict or incompatible proposal. |

JSON is `{ "ok": bool, "code": string, "message": string, "artifacts": [path], "data": object }`. Specific codes such as `AUTH_STALE_PROPOSAL` and `AUTH_UNEXPECTED_RECOVERY_BYTES` refine the class while preserving the numeric exit. Human output includes the exact next command and never prints content forbidden to the requested audience.
