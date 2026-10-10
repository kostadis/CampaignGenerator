# Identity Adjudication and Application

## Proposal construction

For phone review, the local queue producer prepares immutable bounded alternatives for each explicitly selected eligible pair, one per existing candidate survivor. Each contains its exact global alias set and full impact preview/digest. The phone selects and approves a prepared alternative; it cannot invent a source path or cause a proposal to be constructed remotely. A custom survivor/scope/action request is recorded as Discuss with a note; a trusted local operator prepares it, then the GM explicitly reviews the new proposal. Scoped alternatives remain blocked. No intent is counted as an approved merge before an exact applicable preview is accepted. Prepared alternatives bind the item revision/digest and expected current decision revision, which may be zero; they do not bind a future approving event. The accepted event records the fixed proposal digest, and the later receipt records that event. The proposal ledger baseline permits only verified audit-only approval transitions for this proposal before apply; other relevant ledger changes refuse.

Resolve the selected pair against exact current registry names/explicit aliases and snapshot the registry. Require the GM to choose the canonical survivor and confirm the full retained alias set. Preserve former canonical spelling and aliases; no first-token inference or model suggests an applied identity. Preserve provenance, source and authored notes without discarding conflicts. Same-type, persistent entities and explicit global alias scope are the only applicable case in this feature.

Requested local scope remains an auditable blocked choice (`REVIEW_SCOPED_ALIAS_UNSUPPORTED`); it cannot reach apply until #483 defines and implements the scope contract. Nonpersistent entities, mismatched types/scopes, anti-merge guards, ambiguous normalization or cross-campaign entities also block. Do not invoke existing direct `cmd_merge`; extract/reuse pure validation and candidate-registry construction, then validate serialized candidate bytes before staging.

For distinct decisions, persist the scoped/evidence-bound ruling in the shared review/authority model. Duplicate candidate suppression consults current accepted distinct decisions for the exact pair, scope and evidence digest in addition to legacy registry/canon guards. Do not project review-owned decisions into registry v1 `distinct`: it has only global name pairs and cannot carry scope, evidence revision or ownership. Changed evidence stales/reopens the review decision without deleting legacy guards. `canon.yaml` remains the narrow existing exclusion/link store; no merge keys and no silent import. If an existing narrow guard suppresses a candidate, explicit candidate review can show it and require a separate reviewed guard-resolution proposal before merge.

## Dependency closure and preview

Inventory all configured summary-native ranges, corpus/NPC manifests, published NPC dossiers, authored NPC files and review items referring to either identity. Use manifest edges and exact parsed references, not arbitrary search/replace. Record the complete inspected path set and before hashes. A missing/malformed manifest or unclassifiable dependent reference blocks complete application with a repair command. Do not pretend a partial inventory is exhaustive.

Preview includes:

- Registry before/after identity, aliases, provenance and guards.
- All matching summary occurrences as unchanged source evidence unless a separate factual correction was requested.
- Source and destination paths for corpus dossiers, linked evidence, draft/published dossiers and authored files; redirects/reference updates and collision classification.
- Manifest/link/citation changes, affected review items and freshness changes, exact deterministic rebuild selection, and separately listed generative drafts requiring regeneration/review.

A unique old file can move to an unused target only when its identity/content contract remains valid. Two authored dossiers require explicit reconciliation; never concatenate silently. Existing target content, normalized/casefold path collisions, symlink aliases, overlapping merge chains and cycles block. Identical bytes alone do not prove equal identity. Validate canonical relative paths and unique resolved targets.

## Commit and rebuild

1. Build deterministic affected outputs in staging from frozen selected inputs and the proposed registry; preserve unaffected artifact bytes. Compute the exact dependency closure and input/target hashes.
2. Record immutable proposal, including all writes/deletes and stale/rebuild markers. No source mutation and no model calls.
3. Display proposal and record explicit GM acceptance of its digest. A changed selected decision, source, registry, relevant ledger generation or dependency inventory refuses.
4. Under the shared campaign writer lock, require no pending transaction, validate all inputs and target states, and persist journal snapshots. Include registry, affected deterministic artifacts/manifests, decision application references, authority event/tip and receipt in one recoverable write set.
5. Commit through journal v2. Rename is a destination create plus old-path delete, never an unjournaled move. Readers across registry and summary-native consumers must hold the shared lock for coherent snapshots and refuse pending transactions.
6. A committed identity receipt is distinct from regenerated prose being ready. Schedule only explicitly selected affected generative artifacts through existing extract/synth/NPC commands; reuse unchanged extraction caches, recheck input generation before publishing, and require new review/sign-off for changed drafts. Unaffected reviews/artifacts retain validity after audited dependency rebind.

A full registry digest change still invalidates old coarse caches. Extend manifests for this path with subject-level registry dependencies and an explicit schema migration; do not falsely claim selective freshness while the existing global hash silently stales every unrelated artifact. If independence cannot be proven, include the larger affected set in preview and require renewed selection rather than silently broadening work.

## Recovery and replay

Journal v2 records before/after presence and hashes. Validate all snapshots and every current target before writing any recovery step. Missing is not empty; absent-after deletion is a valid after state. All-before or mixed approved before/after states resume forward; unexpected bytes stop with no further mutation. Repeated committed apply/recover returns the same receipt. No automatic rollback over later edits. Source factual correction and identity application are separate proposals; neither receipt falsely claims the other has completed.

All existing registry writes must use the same authority lock and pending-transaction guard to avoid racing reviewed application. Refactor shared loader/saver locking for legacy commands without nesting nonreentrant locks. Read-only consumers must snapshot under that same boundary. The expert direct registry command remains separately authorized behavior; it cannot bypass an in-progress journal or inherit a reviewed proposal's approval.
