# Data Model: GM Rulings and Authority Tiers

## Storage topology

```text
<campaign>/
├── config/planning.yaml
├── docs/authority.yaml
├── docs/authority/
│   ├── proposals/<proposal-id>/proposal.json
│   ├── proposals/<proposal-id>/before.bin
│   ├── proposals/<proposal-id>/after.bin
│   ├── receipts/<transaction-id>.json
│   ├── events/<event-id>.json
│   └── transactions/<transaction-id>.json
└── <range>/state/runs/<run-id>/record.json
```

`docs/authority.yaml` is the only editable authority ledger. Files beneath `docs/authority/` are immutable proposal, snapshot, journal, and receipt artifacts referenced by the ledger. Selected note prose remains in its authored note file.

## AuthorityLedger

| Field | Type | Rules |
|---|---|---|
| `version` | integer | Exact supported schema version; unknown or retired versions refuse with migration guidance. |
| `campaign` | string | Stable campaign identity; must match the active workspace. |
| `revision` | positive integer | Increments on every committed ledger mutation. |
| `records` | list of AuthorityRecord | Stable IDs unique across ruling and note records. |
| `conflicts` | list of ConflictFinding | Stable conflict IDs; never inferred from list order. |

Unknown top-level and nested fields are refused. Duplicate YAML keys are refused before typed validation. Every ledger mutation, including note-only metadata changes, writes an immutable AuthorityEvent containing canonical before/after ledger bytes and digests through the authority lock and transaction journal.

## AuthorityRecord

Shared fields:

| Field | Type | Rules |
|---|---|---|
| `id` | stable slug | Unique, immutable identity. |
| `kind` | `ruling` or `note` | Selects the typed record shape. |
| `revision` | positive integer | Increments when mutable metadata changes; every revision is preserved by an immutable AuthorityEvent. |
| `classification` | enum | `RULED`, `CANON`, `TABLE`, `PREP`, `OVERLAY`, or `OPEN`; `ruling` requires `RULED`. |
| `subject` | SubjectRef | Exact registry entity or thread identity; free text is allowed only for a deliberately unregistered planning topic and cannot participate in automatic identity conflicts. |
| `claim_key` | optional string | Human-authored property/decision key used for deterministic conflicts. |
| `normalized_value` | optional scalar | Required with `claim_key` for automatic value conflicts. |
| `effective` | EffectiveInterval | Inclusive chapter bounds or explicitly future/open horizon. |
| `audience` | AudienceGrant | Explicit grants; empty is invalid. |
| `projections` | non-empty set | Allowed values: `world_state`, `campaign_state`, `party`, `planning`. |
| `recorded_at` | timestamp | Human decision/record time; never used as implicit precedence. |
| `recorded_by` | string | Required human reviewer identity. |
| `status` | typed enum | State machine depends on record kind. |
| `supersedes` | optional record ID | Same subject/claim and compatible scope; cycles refused. |

### RulingRecord

| Field | Type | Rules |
|---|---|---|
| `source` | SourceRef | Mandatory maintained authoritative summary target. V1 refuses VTT, generated drafts, arbitrary YAML, and external-note mutation. Registry or thread identity changes must use their existing authority workflow. |
| `rejected_claim` | non-empty string | Exact claim under review; cannot act as fuzzy identity or unbounded matcher. |
| `replacement_fact` | non-empty string | Proposed maintained source truth. |
| `proposal_id` | optional proposal ID | Required from `proposed` onward. |
| `applied_receipt` | optional receipt ID | Required in `applied`, `withdrawal_requested`, `reversal_proposed`, `withdrawn`, or `superseded`. |
| `withdrawal_reason` | optional string | Required when withdrawal is requested. |

`RULED` has no read-time override behavior. Until its proposal is applied to the source, it is an instruction and audit record only.

### NoteRecord

| Field | Type | Rules |
|---|---|---|
| `source` | NoteSourceRef | Authored selector plus resolved file and optional stable section anchor. The reserved `__document__` anchor classifies a complete read-only support file only. |
| `content_digest` | SHA-256 | Digest of the independently classified selected section, or the whole file for `__document__`. |
| `planning_date` | optional date/chapter | Required for `PREP` and `OVERLAY` stale-future checks. |
| `selection_label` | string | Human-facing explanation shown in previews and manifests. |

One record may cover a whole homogeneous file or one stable anchored section. Mixed audience/classification content must use separate sections and records. `__document__` keeps valid YAML and JSON byte-for-byte for deterministic adapter input; it is invalid for `RulingRecord` and cannot authorize source replacement.

## SubjectRef

| Field | Type | Rules |
|---|---|---|
| `kind` | `entity`, `thread`, or `topic` | Entity/thread IDs resolve exactly through their existing registries. |
| `id` | string | Stable identity. Similarity matching is prohibited. |

## EffectiveInterval

| Field | Type | Rules |
|---|---|---|
| `from_chapter` | optional integer | Inclusive lower bound. |
| `through_chapter` | optional integer | Inclusive upper bound and not less than lower bound. |
| `horizon` | optional `future` or `open` | Used when chapter bounds do not describe prospective material. |

Disjoint intervals describe evolution. Overlapping intervals with incompatible structured values may conflict.

## AudienceGrant

| Field | Type | Rules |
|---|---|---|
| `grants` | non-empty set | Values are `gm`, `players`, `characters`, or `character:<stable-id>`. |

`players` never implies `characters`. `characters` means all declared characters. Named character IDs resolve exactly. GM can inspect every record, but a record still carries its declared grants for downstream views. Missing or unresolved grants refuse.

## SourceRef

| Field | Type | Rules |
|---|---|---|
| `path` | authored path | Mandatory for a ruling; points to a maintained authoritative summary in V1. |
| `resolved_path` | normalized path | Must remain within the campaign's configured summaries root for mutation. |
| `anchor` | stable claim anchor | Identifies the independently reviewable passage. |
| `before_sha256` | SHA-256 | Whole-file digest displayed and approved with the proposal. |
| `before_span_sha256` | SHA-256 | Digest of exact replacement bytes. |

Reading an explicitly selected external planning note is permitted and disclosed. Writing to it is not authorized by selection and is refused by the V1 source adapter.

## PlanningNoteSelector

Added to `PlanningConfig.notes`:

| Field | Type | Rules |
|---|---|---|
| `id` | stable slug | Unique in planning configuration. |
| `path` | exact path or scoped glob | Authored value preserved; paths resolve from campaign root unless explicitly absolute. |
| `record_ids` | optional non-empty set | Limits the file to named authority records/sections. |
The preview emits resolved canonical paths, external flags, matching record IDs, selection reasons, and a membership digest. Symlink aliases deduplicate to one resolved file. Every configured selector is required: a missing, unreadable, or zero-match selector refuses. A planning configuration with no `notes` field is a legacy summary-only configuration; once `notes` is present, it must be non-empty.

## SelectionSnapshot

| Field | Type | Rules |
|---|---|---|
| `selectors_digest` | SHA-256 | Digest of authored typed selectors. |
| `members` | ordered list | Deterministically sorted concrete selected sections. |
| `membership_digest` | SHA-256 | Digest over resolved member identity, section digest, reason, and external flag. |
| `created_at` | timestamp | Informational only; not precedence. |

A run must compare current resolution to the reviewed snapshot. Changed membership requires a new preview.

## SourceChangeProposal

| Field | Type | Rules |
|---|---|---|
| `id` | stable slug | Immutable. |
| `ruling_id` | AuthorityRecord ID | Must name a current ruling revision. |
| `campaign` | string | Must match workspace. |
| `ledger_revision` / `ledger_sha256` | integer / SHA-256 | Bind approval to the post-`propose` ledger state, whose ruling references `proposal_id` but not `proposal_sha256`; this avoids self-invalidation. |
| `target` | SourceRef | Exact allowed source and anchor. |
| `before_sha256` / `after_sha256` | SHA-256 | Whole-file digests. |
| `before_bytes_sha256` / `after_bytes_sha256` | SHA-256 | Bind immutable snapshot files. |
| `operation` | `replace` | V1 supports exact maintained-summary replacement only. |
| `proposal_sha256` | SHA-256 | Canonical proposal digest displayed at approval. |

The exact `before` span must match once. The proposal refuses immutable/verbatim spans and any result that fails source validation. `proposal_sha256` is computed from the canonical proposal with that field omitted. Approval never mutates the proposal; a separate ApprovalEvent binds proposal ID/digest, reviewer, timestamp, and current ledger/source digests.

## ApprovalEvent

Immutable record written by the explicit apply action. It contains proposal ID and digest, reviewer identity and time, current source/ledger digests, and requested operation. It becomes one transaction input and is not part of the proposal digest.

## AuthorityEvent

Every ledger mutation emits an immutable event with event ID, reason, actor, timestamp, before/after ledger revisions and digests, canonical before/after ledger snapshot paths, and optional transaction/proposal/receipt references. Note edits, conflict dispositions, and retirements therefore have complete history even when no source file changes.

## AuthorityTransaction

| Field | Type | Rules |
|---|---|---|
| `id` | stable transaction ID | Unique and immutable. |
| `proposal_id` / `proposal_sha256` | references | Exact approved proposal. |
| `state` | transaction enum | `prepared`, `writing`, `source_written`, `ledger_written`, `committed`, or `attention_required`. |
| `targets` | ordered list of TransactionTarget | Source, ledger, and receipt files with before/after digests and snapshot paths. |
| `started_at` / `updated_at` | timestamps | Audit only. |
| `error` | optional text | Required for attention state. |

The journal is persisted and synced before target replacement. Any nonterminal transaction blocks dependent readers.

### Recovery classification

- Every target at `after`: verify and finish the receipt/commit idempotently.
- Every target at `before`: resume the exact already-approved proposal.
- Mixture of `before` and `after`: resume forward only from stored approved bytes after validating every target.
- Any unexpected digest: enter `attention_required`; do not overwrite.

## ApplyReceipt

Contains transaction, proposal, ruling, campaign, before/after source and ledger digests, reviewer, commit time, affected projections, and resulting ledger revision. The applied ledger references only the predetermined receipt ID; the receipt may therefore include the final ledger digest without the ledger embedding that receipt digest. It is immutable and is included in run input provenance.

## ConflictFinding

| Field | Type | Rules |
|---|---|---|
| `id` | stable slug | Unique. |
| `record_ids` | two or more IDs | Comparable records or human-identified candidates. |
| `basis` | enum | `structured_value`, `source_anchor`, `human_identified`, or `prose_candidate`. |
| `overlap` | EffectiveInterval | Required for deterministic value conflicts. |
| `projections` | non-empty set | Affected views. |
| `status` | `open`, `resolved`, or `dismissed` | Only a human action resolves/dismisses. |
| `resolution_record` | optional ruling ID | Required when resolution changes authority. |

Only `structured_value` and `source_anchor` are automatic verdicts. `prose_candidate` remains explicitly unresolved.

## AuthorityInputManifest

Stored within each run record and used by freshness:

- authority schema and policy versions;
- ledger digest and relevant record IDs/revisions/metadata digests;
- selected note authored/resolved paths, section/file digests, reasons, and external flags;
- selector and materialized membership digests;
- relevant applied proposal and receipt digests;
- authoritative source digests;
- target audience and effective horizon;
- filtered payload digest passed to extraction/rendering;
- pending transaction status (must be none).

## State transitions

### Ruling

```text
draft → proposed → applied → withdrawal_requested → reversal_proposed → withdrawn
                     └──────────────→ superseded
```

- `draft → proposed`: exact source proposal and immutable snapshots created.
- `proposed → applied`: one explicit digest-bound human action completes a recoverable transaction.
- `applied → withdrawal_requested`: records intent only; source remains authoritative and unchanged.
- `withdrawal_requested → reversal_proposed`: safe inverse or authored replacement is reviewed against current source.
- `reversal_proposed → withdrawn`: reversal transaction commits.
- `applied → superseded`: a later reviewed source change explicitly supersedes it; history is retained.

Deleting a ruling never changes source and is refused once the ruling has a proposal or receipt.

### Note

```text
active → superseded
active → retired
```

Status changes increment record revision and stale dependent artifacts. Retired content remains in history and is not selected for new runs.
