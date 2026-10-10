# Whole-Bundle Publication Contract

Planned interface and persistence rules, not implemented behavior.

## Ownership and layout

```text
<campaign>/docs/
  world_state.md -> grounding/current/world_state.md
  campaign_state.md -> grounding/current/campaign_state.md
  party.md -> grounding/current/party.md
  planning.md -> grounding/current/planning.md
  canon_events_timeline.md -> grounding/current/canon_events_timeline.md
  reference -> grounding/current/reference
  grounding/
    layout.json
    current -> generations/<generation-id>/live
    generations/<generation-id>/
      live/                     # ordinary readable/editable document tree
      published/                # retained exact bytes originally published
      manifest.json             # immutable original membership/hashes
      publication-receipt.json  # immutable commit candidate, not proof of activation alone
    activations/<activation-id>.json # immutable reconciled activation chain
    operations/<operation-id>/
      intent.json
      previous/                 # exact precommit live bytes, including human edits
      previous-manifest.json
      state.json
```

`docs/` stays a real directory: authority/review writers reject a symlinked docs root. Six explicit compatibility aliases preserve familiar file paths without retaining a second live copy. Configured grounding paths are migrated to `../docs/grounding/current/<document>.md`. No arbitrary destination path is accepted by promotion.

Resolve source paths with `schema.draft_dir(range_dir, document)` (currently `<range>/state/drafts`). The four source draft files map to the four live names; `canon_events_timeline.md` beside those drafts maps unchanged; every regular file under `state/drafts/reference/` maps with its exact relative path. Reading-contract comments remain byte-for-byte identical. Copy the minimum run/path records needed to interpret provenance into generation metadata, with a manifest map keyed by (document member path, unchanged embedded locator, anchor) to its retained metadata copy and hash, retaining the original resolution base. Validate copy containment and identities; never resolve colliding locator strings against the new live path as if their draft bases were identical. Bind originals as inputs as well. Summary/dossier source dependencies remain external and explicitly identified; do not mistake those for the self-contained path records. Historical inspection resolves retained records through that map rather than depending on regenerable original run directories. Do not copy annotations or extraction reports unless the explicit reading contract requires them. Missing required artifacts refuse. Reject source symlinks, devices, case-colliding paths, path traversal and conflicting support bytes. If existing canonical `reference/` contains uncertain ownership, migration refuses until the user supplies an explicit member inventory.

`published/` is historical evidence, never read as a fallback when live state is missing. The active `live/` bytes are authoritative for normal reads. Supported human editing uses `docs/grounding/current/<member>` (the final member is a regular file), or the resolved live path; compatibility aliases are advertised for reading. Editors that replace an alias itself detach it: status/preview/readers refuse that conflict and identify both the detached content and canonical path; never silently repair or discard either. Human prose edits are permitted and reported as `edited_since_publication`; they do not rewrite original hashes, receipt, or source sign-off. No campaign writer mutates a retired generation. Retained generations and precommit snapshots are not garbage-collected by this feature.

## Reader and writer boundary

`campaignlib.grounding_bundle.open_grounding_snapshot` is the shared reader. Under an existing shared authority lock, validate layout/pointer ownership, resolve `current` once, and materialize all requested bundle members and required references into a read snapshot. Validate reading-contract completeness; return original generation ID plus actual live-tree digest and drift status. Release the lock after all bytes are captured, before rendering/model calls or long UI work. A consumer never repeatedly follows `current` while assembling one context.

Convert `campaignlib.config.assemble_docs`, prep context assembly, summary-native compare, the grounding context used by session-doc operations, and campaign MCP document/context reads to this boundary. Direct context paths that name a managed member join the same snapshot; unrelated external context retains its current behavior. In-process member writes must take the exclusive lock and retain aliases. Existing non-summary-native generators may continue writing their ordinary nonmanaged outputs; on a migrated managed target they refuse and name a draft output path. This prevents detaching a compatibility alias with per-file atomic replacement without redesigning those generators.

Classify configured/explicit managed paths against one pinned current resolution. Permit only the six owned compatibility links and the validated current link; reject other symlink components or escape paths. Validate relative references within the pinned generation and external dependencies only against the bound source map. Existing generic review `_safe`/`_reject_symlinks` guards remain strict; do not globally relax them. Use immutable bytes from the snapshot, not open paths returned to callers. Missing/corrupt layout, missing required members, malformed pointers or pending migration refuse explicitly. Ordinary human edits are visible as drift, not silently discarded or treated as a failed historical receipt. Required pointer/outline integrity failures still refuse the affected operation.

Uncoordinated external filesystem readers/writers do not participate in the locking protocol. Stable aliases help compatibility but cannot guarantee a multi-file snapshot. Concurrent external edits during commit are unsupported; stat/content rechecks detect observed changes and refuse. The publication guarantee applies to repository consumers through the shared boundary and to stable file access after completion.

## Pure preview

`promote --dry-run` performs no writes, including no mkdir, lock-file creation, report export, cache population or model invocation. Open the existing lock without creation on initialized campaigns; on an unmigrated campaign report migration-needed read-only. Do not enter the existing scan/build dispatch that writes validation reports.

The returned preview contains all source/output/dependency hashes, the expected active pointer and actual live membership/hashes, all four sign-offs, current findings/resolutions, the complete diff including removals, and a canonical `preview_sha256`. Exclude display timestamps and transient diagnostics from digest computation. Preview is reproducible without persisting it. Blocked previews still show available changes and list all eligibility failures, but cannot be committed.

Destination-only edits change the preview digest while preserving source approvals. Source/rule/finding changes invalidate the appropriate report or sign-offs. Hash only relevant authority records and source excerpts for semantic continuity; bind full source-file hashes for custody and revalidate run-record freshness independently. A no-op publication returns its existing logical receipt only after checking exact input and destination identities; drift is never a no-op.

## Commit protocol

The existing authority lock is the single mutation lock. Do not introduce opposing lock acquisition orders or hold it across model calls. Publication uses a dedicated pointer protocol rather than passing live files to `authority_apply`'s sequential target writer.

1. Collect inputs and stage candidate bytes on the same filesystem as `docs/grounding`. Preliminary staging may happen outside the exclusive lock; it is private and never live.
2. Acquire the exclusive campaign lock, refuse unresolved authority or promotion operations, validate the ledger tip, and recompute the supplied preview digest against current source, review, report and destination state. If it differs, discard eligibility; do not silently refresh the user's consent.
3. Persist an operation intent and an exact snapshot of the previous live bytes, including edits, or an explicit absent prior generation. Fsync files/directories. Before first activation this retains whatever validated prior state existed; no full-bundle promotion may adopt loose files implicitly.
4. Stage both `published/` and `live/` from reviewed source bytes without hard links. Preserve full nested membership. Check every output hash, outline and pointer against the actual final destination layout, including references and retained reading-contract records. Run the same deterministic claims gate with current reviewed mappings/resolutions.
5. Write a generation manifest and generation-local receipt candidate binding preview, parent generation/activation, previous snapshot digest, all review events, gate results and new output hashes. Fsync every file and containing directory. Rename the staging generation to its final opaque path; fsync the generations directory. Receipt preparation failure stops here and leaves the prior pointer untouched.
6. Compare the actual live tree again with the exact step-3 snapshot immediately before activation and refuse any observed mismatch. Revalidate relevant sources/live hashes and bind the intent to the sealed generation. Prepare a relative current-pointer symlink next to `current`; atomically replace `current` and fsync `docs/grounding`. This is the publication commit point. Do not mutate several live member paths.
7. Write and fsync an immutable ActivationRecord, then mark the operation committed and return the completed receipt (candidate joined with activation). The record binds parent activation ID/digest, operation, new generation/manifest/candidate hashes, and previous snapshot. `completed_at` is the time durable activation is reconciled, not precommit preparation time. If recovered after a crash, record `recovered_at` and a bounded observed activation interval rather than inventing an exact swap timestamp. This metadata may lag the pointer after a crash; it never defines activation by itself. There are no fallible validation steps that can invalidate content after activation: all were performed on the complete final generation first.

The gate validates **copied bytes in their destination layout**, rather than checking only source drafts. A blocked generation never becomes current. Unsupported cross-filesystem staging or filesystem durability/locking assumptions refuse before mutation.

## Failure, interrupted acknowledgments and recovery

| Observed durable state | Meaning / action |
|---|---|
| No sealed candidate; old pointer intact | Failed or interrupted before commit. Old bundle remains live. Recovery records aborted; retry is a new explicitly bound attempt. |
| Sealed candidate/receipt exists; old pointer intact | Prepared but not published. Recovery may mark aborted; it must not publish automatically. A fresh commit requires the same current preview and checks. |
| Pointer names candidate; valid receipt and bytes exist | Activation occurred. Recovery synchronizes metadata and records committed, without copying or publishing again. |
| Process loses response or directory sync errors after swap | Outcome is `commit_unknown`, never a reported rollback or content-validation failure. Preserve both generations; status/recovery inspects pointer, validates receipt and synchronizes before declaring committed/aborted. |
| Pointer or involved bytes are unexpected | Refuse destructive repair and report intervention required with exact observed/expected identities. Never select the newest directory by date. |
| Operation is already committed and a later valid publication exists | Return original receipt as historical success using the verified activation history; do not reactivate or overwrite the newer bundle. |

Before any later publication, reconcile an unresolved prior operation under the same lock and durably persist its immutable activation record. The next generation binds that parent activation ID and digest. Operation state alone is not historical commit proof; status validates the activation record and its chain. A current-pointer match plus durable intent/receipt candidate permits reconciliation if the record is missing. A committed operation's history links to its parent's activation receipt; an unactivated orphan receipt is never success. The original generation and exact precommit snapshot remain inspectable. Recovery aborts precommit attempts or reconciles postcommit ones; it is not a new discretionary rollback feature.

Only an explicitly initialized pristine campaign with no managed output may have an absent baseline; existing loose output requires deliberate adoption or an actionable incomplete-bundle refusal. On a first promotion with no prior generation, precommit failure leaves no active generation. Migration creates a `legacy_baseline` activation record binding its receipt and adopted generation, or an explicit absent baseline for a pristine campaign, before clearing pending. After a normal pointer swap with unreconciled activation metadata, supported readers return an explicit retry/reconciliation-required result; they do not perform recovery or label the candidate historically committed. On migration, pending status blocks all supported readers while files/config are being transformed. Recovery itself requires explicit invocation; routine reads do not perform migration or repair.

## Required proof

Inject failures at every file write, validation, synchronization, generation rename, pointer swap, and metadata completion boundary. A reader loop using the supported snapshot API must only observe complete old or new bundles. Test two contenders, stale previews, manual edits, lost responses, receipt creation failure, changed references with unchanged prose, first publication, nested/removal membership, alias detachment, and subsequent publication after recovered activation. Physical power-loss behavior remains limited to tested local-filesystem synchronization guarantees, not a claim to survive storage-device corruption.
