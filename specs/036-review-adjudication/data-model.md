# Data Model

All new records are strict, versioned documents: unknown fields, duplicate keys/IDs, invalid enums, unsafe paths, unresolved references and invalid state combinations refuse. Canonical JSON uses UTF-8, sorted keys, no insignificant whitespace and no nonfinite numbers; digests exclude the digest field itself. File-byte hashes are separate from canonical record hashes. Times are UTC; reviewer is required nonempty attribution, not authentication.

## Storage and ownership

```text
<campaign>/docs/reviews/<review-id>/
  manifest.json                  # current review generation and item revision references
  items/<item-id>/<revision>.json # immutable item snapshots
  events/<event-id>.json          # immutable common decisions; request ID unique per review
  runs/<run-id>.json              # selected rerun members and results
  exports/<export-id>.json        # immutable decision bundles
  proposals/<proposal-id>.json    # typed source/identity/document action proposal
  receipts/<receipt-id>.json      # outcomes and changed paths
  access/<grant-id>.json          # credential digest, expiry and revocation (mode 0600)
<campaign>/docs/authority.yaml    # version 2 shared rulings, including review_decision
<campaign>/docs/authority/       # existing event/snapshot/journal/tip infrastructure
<campaign>/.review-runtime/      # private service handles/readiness; no public capability logs
```

Review roots are campaign-local and fixed by the CLI. They are not supplied by remote clients. Filenames use validated opaque/sluggable IDs, never arbitrary labels. Source excerpts are captured at review creation; the browser does not fetch live source paths. Journals cover manifest, event and authority-ledger changes together. Indexes may be reconstructed from immutable snapshots/events; existing external sources may not.

## Campaign and ReviewManifest (version 1)

Fields: `version`, `campaign_id` (persisted UUID in review initialization metadata), `review_id`, `kind` (`npc_verification|duplicate_identity|grounding_documents`), `generation`, `created_at`, `created_by`, `audience` (GM-only in this release), `selection` (literal selected source/subject IDs), `items` (item ID/revision/digest), `source_manifest`, `rule_versions`, `history_tip`.

Campaign UUID plus canonical campaign root binds local inputs; relocating a campaign requires deliberate rebind after verifying its snapshots, never matching on basename alone. Review item listings contain no other campaign's references. Counts are derived from a coherent manifest/event snapshot, not mutable counters.

## ReviewItem (version 1)

Fields: `item_id`, `revision`, `campaign_id`, `review_id`, `domain`, `subject_ref`, `occurrence_id`, `locator`, `claim_text` (exact), `failure_context` for non-sentence failures, `evidence[]`, `diagnostics[]`, `categories[]`, `severity`, `assignment_basis`, `rationale`, `proposed_action`, `scope`, `audience`, `rule_versions`, `input_bindings`, `review_digest`.

Evidence entry: source identity/path, anchor, exact excerpt or explicit missing reason, and selected-span hash. Full containing-file hashes live separately in input_bindings/source_manifest as custody hashes; they are not included in review_digest. Citation resolution and semantic support are separate fields; `support=unassessed|candidate_issue|gm_supported|gm_unsupported`. Mechanical success never writes `gm_supported`.

Identity: assign a UUID to a newly encountered occurrence. On regeneration, reuse it only for a unique match of producer, subject, stable source anchor and rule identity, with exact claim/evidence binding; reordered lines alone do not change it. Duplicate indistinguishable occurrences and changed/unmatchable claims create new IDs linked by `supersedes_candidate`; they never inherit approval. Duplicate pair IDs use sorted stable entity IDs plus reviewed scope. Whole-document items use projection and logical document identity, with bytes in their revision digest.

The review digest is a hash of a named semantic payload, not the entire serialized ReviewItem: it includes claim/evidence spans, fact-bearing context, relevant authored edits, registry identities, scope, audience, rule revisions, and complete proposed disposition. Exclude full containing-file custody hashes, audit timestamps, display locations and rebind history; those have their own artifact hashes. It excludes unrelated dossier bytes and display line numbers. Changed containing files trigger dependency re-evaluation; an unchanged excerpt/context may retain approval, but a changed fact-bearing dependency or uncertain mapping stales it. Source mutation additionally requires full current file hashes.

Severity: `blocking|needs_judgment|advisory`. Assignment: `mechanical|advisory_candidate|gm_confirmed`. Preserve all legacy codes, multiple categories, and diagnostic-specific block flags. A taxonomy label never lowers an existing blocking check.

## DecisionEvent and common verdicts (version 1)

Fields: `event_id`, `request_id`, `campaign_id`, `review_id`, `item_id`, `item_revision`, `review_digest`, `expected_decision_revision`, `decision_revision`, `verdict`, `disposition`, `note`, `reviewer`, `recorded_at`, `supersedes_event`, `authority_record_id`, optional `proposal_id` and `proposal_digest`.

| Domain | UI action | Stored verdict/disposition |
|---|---|---|
| NPC finding | Approve displayed no-change resolution | approve / accept_no_change |
| NPC finding | Approve exact correction proposal | approve / source_correction |
| Duplicate | Merge + confirm canonical/scope/preview | approve / merge |
| Duplicate | Distinct + confirm scope/evidence | approve / distinct |
| Any finding | Reject proposed action | reject / reject_action |
| Any finding | Discuss | discuss / defer |
| Whole document | Explicit sign-off | approve / document_signoff |

Rejecting merge does not imply distinct. Batch decisions include individual item revisions and one explicit disposition per item. Batch save is all-or-refuse if any precondition fails. Repeated request ID with identical payload returns the original result; a different payload refuses. Notes cannot mutate the accepted action; changing it creates a new proposal/review revision.

State is computed from separate axes: disposition (`pending|approved|rejected|discussed`), freshness (`current|stale|superseded`), verification (`unchecked|passed_mechanical|failed_mechanical|needs_judgment`) and application (`none|proposed|prepared|writing|committed|attention_required`). Client `pending_save|save_failed` is explicitly transient. “Settled” means current human-approved disposition, not necessarily applied or publishable. Disappearance after a rerun records a resolved diagnostic; it does not invent GM approval or document sign-off.

## Shared authority ledger version 2

Keep existing source `ruling` and `note` records unchanged. Add a strict `review_decision` variant with ID/revision, classification RULED, subject/scope/audience/projections, reviewer/time, review/item/event references and digests, domain disposition, status `accepted|superseded|withdrawn`, and typed proposal/receipt references when present. It is audit-only for generation; no `source` replacement fields and no implicit factual overlay. Every event reference is validated against its campaign and digest.

One authority record per accepted decision revision preserves history and exact supersession. Reject/Discuss events remain common review history without acquiring RULED authority. Applying a source correction transitions the existing source ruling and appends application evidence; applying identity changes updates the dedicated proposal/receipt reference. Retracting a decision never silently undoes a source or identity change. An applied mutation needs a newly reviewed inverse proposal; ambiguous split/undo is refused for manual re-adjudication.

Existing version-1 source proposals/receipts remain immutable archival evidence. Live v1 ledger reads fail with the migration command. Updating all discriminated unions, conflict logic, planning input filters, status/history and tip validation is a required migration gate.

## RerunSelection and RunReport

A persisted selection names item/revision/digest, check IDs, dependency hashes and selection hash. `mode=unresolved` accepts only current rejected/discussed/mechanical-failure items, excluding current approvals. `mode=selected` allows explicitly selected pending/stale items for renewed checks. A changed selection refuses before work. Only selected checks execute, though a checker may read necessary shared evidence. Report records attempted, completed, refused, failed and unprocessed members; interrupted work never becomes a pass. Each member result commits independently with a final run summary; retry uses member completion records, not transport-level job resume.

## ApplicationProposal, Journal and Receipt

Proposal includes domain, exact decision inputs, campaign, reviewed target paths, before/after presence and bytes/digests, affected dependency closure, inspected-but-unchanged paths, collisions, registry/ledger generations, staged deterministic outputs, and generative rebuild work. Approval binds the whole proposal digest and input revisions. A prepared alternative binds each item revision/digest and the expected current decision revision (zero when undecided); a prior event reference is optional historical context. It cannot require the future approving event, because that event itself records the fixed proposal digest. The subsequent application receipt binds the actual approving event IDs. Apply verifies that each current accepted event names that exact proposal and that no intervening change invalidated its inputs. A baseline ledger hash may advance only through verified audit-only approval transitions for that proposal; changed relevant ledger facts or unverified lineage refuse.

Journal v2 has per-target operation `create|replace|delete`, explicit presence, snapshots and state `prepared|writing|committed|attention_required`. A logical rename is destination creation plus source deletion. Recovery checks ALL current target states before any further write, then resumes only approved operations. Snapshots, receipts and authority history are immutable. A committed receipt records exact changed paths, before/after hashes, decision/ledger references and required remaining review work; no self-referential digest cycle.

## AccessGrant and service handle

A grant stores ID, review ID, SHA-256 of a cryptographically random 256-bit token, allowed actions `read_review|save_decision`, issued/expiry times and revoked state. Raw token is shown only to the authorized local operator when issued, never persisted in public artifacts or logs. Restart retains grant validity until expiry/revocation; a lost raw token requires rotation. Default expiry 24 hours is a single config default, selectable by the operator. The service handle contains PID plus process-start identity, review, bind address, advertised origin and readiness nonce; status must not trust a reused PID. Revocation is rechecked on every request. Browser decision commands recheck it under the writer lock before committing.

## Identity scope boundary and current registry

Registry v1 uses names and flat string aliases, not permanent entity UUIDs. The review assigns its own subject ID and records immutable canonical names/registry snapshots plus the proposed target identity. Do not claim the current registry has stable UUID fields. Historical review-decision subject checks use their validated immutable event/proposal snapshots; current staging still validates exact registry identity. Removing a loser must not invalidate history.

Only persistent/global aliases and persistent, same-type identities can enter an applicable merge. A scoped alias request is retained in the review as `blocked` with `REVIEW_SCOPED_ALIAS_UNSUPPORTED`, and no registry/dependent file is changed. Differing/nonpersistent entity scope, differing type, distinct/rejected-alias guards or unresolved name collisions block too. The registry schema stays v1; full scoped-alias application is #483. Explicit user review cannot force the unsafe conversion of scoped aliases to global strings.

A deterministic `review refresh` operation may rebind a review to changed containing files only after verifying exact claim/evidence spans, surrounding identity/citation context and relevant dependencies are unchanged. Record old/new full hashes and unchanged review digest in an immutable rebind event. Preserve the item revision and immutable semantic item snapshot; a new source-manifest generation stores the updated custody binding. A decision refers to the semantic item revision, while every apply proposal separately refers to the current custody generation. Ambiguous mapping stales the item. This preserves unrelated approvals without silently rebinding a source-changing proposal: all such proposals still require fresh full input hashes and renewed exact-patch approval.
