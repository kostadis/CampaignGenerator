# Feature Specification: Reviewed Source-Custody Rebase for Corrected Historical Summaries

**Feature Branch**: `040-source-custody-rebase`

**Created**: 2026-11-09

**Status**: Draft

**Code baseline**: `3c3fbb9` (main)

**Input**: GitHub issue [#606](https://github.com/kostadis/CampaignGenerator/issues/606), "summary_native: reviewed source-custody rebase for corrected historical summaries". Follow-up to spec 039 (`specs/039-incremental-campaign-updates/`). Related: #588 (incremental grounding), #597 (citation target validation, a separate defect), PR #602.

## Problem and Intended Outcome

An active managed grounding generation pins the exact SHA-256 of every historical session summary it depends on. When the GM later corrects one of those summaries, which is the right thing to do because summaries are the authority, every subsequent incremental (delta) run refuses at claims selection with a generic `CLAIMS_SOURCE_STALE`. The refusal is correct: the baseline's claims were made against bytes that no longer exist. But there is no supported way out. The only options today are a full campaign rebuild, or hand-editing hash manifests, which is exactly the integrity bypass the gates exist to prevent.

This feature adds a **source-custody rebase**: a bounded, reviewed operation that reconciles corrected historical summaries with an existing managed grounding baseline. It:

- recovers and retains the exact old bytes;
- shows the GM what each correction changes and which baseline claims it touches;
- separates "this source's identity changed" from "this claim's meaning changed";
- publishes a new, lineage-bound baseline generation, without altering any old one;
- lets a pending delta resume from that new baseline, without losing partial results that are still valid.

The rebase extends spec 039's publication and review gates; it does not replace them, and it does not weaken any integrity check.

## Context and Evidence: The ToEE Chapter 43 Blocker

Observed at toolkit commit `d844f0dd`. Campaign ToEE, active baseline `generation-toee-ch042-promote-20261031`, pending chapter 43 (native plan `plan-0a0f7aa90623202d`).

- Eight NPC dossiers passed native verification, received exact GM approvals and were published.
- The four grounding candidates passed native consistency after approved citation repairs, and `delta grounding preview` staged `ch043-043` with complete lineage.
- `claims select --since 43 --until 43` then refused with `CLAIMS_SOURCE_STALE`, naming no source.

A manual integrity audit found four baseline-pinned summaries whose current bytes differ:

| Chapter | Correction | Nature |
|---|---|---|
| 16 | Fixer's recurring payment terms corrected | Semantic: changes a fact |
| 17 | Contradictory payment-history annotation removed | Semantic: removes a contradiction |
| 38 | "unaware" narrowed to "not yet told" | Semantic: party-knowledge assertion |
| 42 | Prisoner accounting: two of four remain missing | Semantic: a count the pending candidate may still carry wrongly |

All four old versions were recoverable from Git by exact hash. Substituting the new hashes would have certified baseline claims against summaries that now contradict them.

### What the existing code already provides (and does not)

- **Provides:** generation manifests with member and external-dependency hashes; immutable generation directories; whole-bundle activation with journaling and recovery; an append-only adoption record for drift in the four *documents* (not summaries); per-claim source attribution (source path, source hash, byte span and original span text); review bindings that go stale on any change of plan, candidate, evidence or rules; and per-NPC publication receipts.
- **Does not provide:** any retained copy of historical summary bytes (hashes only); a report of *all* stale sources (selection stops at the first, without naming it); any record mapping timeline or reference members to the summaries they draw on; any operation that produces a new baseline generation whose only change is custody of corrected sources plus reviewed claim repairs.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Inspect and Approve a Bounded Repair for Changed Historical Sources (Priority: P1)

The GM runs an inspection against the active baseline (and, optionally, a pending delta). Without changing anything and without calling any model, it lists every pinned source whose current bytes differ, with:

- the source path;
- the expected and actual digests;
- whether the old bytes are recoverable, and from where.

The GM then selects the corrected chapters to reconcile. For those chapters the system recovers and snapshots the old bytes and shows a readable diff of each correction. It also lists every baseline and pending claim, citation and other consumer that depends on the changed bytes, and marks impact that cannot be determined.

For each changed source, the GM then makes one of three decisions:

- **Adopt as claim-unaffected**: supported by evidence that no affected claim's meaning changes.
- **Adopt with repairs**: each affected claim is repaired, or explicitly held.
- **Reject**: no rebase for this source.

A model may propose repairs; only the GM approves. The review shows the concrete effect of applying it.

**Why this priority**: This is the precision decision. A hash swap alone would turn a corrected fact ("two prisoners remain missing") into a silently wrong one in the published baseline.

**Independent Test**: Use a synthetic campaign with an active baseline and four corrected summaries matching the ToEE shapes (payment terms, contradiction removal, knowledge narrowing, prisoner count). Inspection lists all four with digests and recovery sources, writes nothing and makes no model call. Selecting them produces a review that shows the diffs, the affected claims, and the claims whose impact is unknown.

**Acceptance Scenarios**:

1. **Given** four pinned summaries whose bytes changed, **When** the GM inspects, **Then** all four are reported in one result, each with path, chapter, expected digest, actual digest and old-byte availability. The run makes no write and no model call.
2. **Given** a selected chapter whose old bytes are in Git under the exact expected hash, **When** the GM prepares the review, **Then** the old bytes are verified against the pinned digest and snapshotted, and the corrected current summary is left byte-identical.
3. **Given** a selected chapter whose old bytes cannot be found or do not hash to the pinned digest, **When** the GM prepares the review, **Then** the system refuses for that chapter, naming it, the expected digest and the providers it tried.
4. **Given** the prisoner-count correction, **When** the GM tries to adopt it as claim-unaffected while a baseline claim cites the changed span, **Then** the system refuses: semantic changes cannot be adopted through hash replacement alone.
5. **Given** a whitespace-only correction where no cited span's text changed, **When** the GM adopts it as claim-unaffected, **Then** it is accepted with recorded evidence, without any synthesis or model call.
6. **Given** a timeline or reference member whose dependence on a changed source cannot be determined, **When** the review is built, **Then** the member is shown as unknown impact and blocks application until the GM rules on it, recording an explicit reason.

---

### User Story 2 - Apply the Reviewed Repair and Finish the Pending Delta (Priority: P1)

The operator applies the approved rebase through a digest-bound preview. This publishes a new baseline generation that records:

- its parent generation;
- the old and new source hashes and the retained old bytes;
- the GM's decisions;
- which members were repaired and which were unchanged;
- honest coverage.

The pending delta is then rebound to the new baseline through a supported plan revision. Only the checks and signoffs that depend on the changed baseline are invalidated. NPC publications that already succeeded and do not depend on the changed sources are kept: they are not redrafted or republished. The operator then reruns the existing claims, consistency, exact-document signoff and promotion gates, and publication completes.

**Why this priority**: The production blocker is a run stuck after eight successful NPC publications. Repairing the baseline without a safe resume path would force duplicate work or hand-editing.

**Independent Test**: Use the synthetic chapter-43-style fixture, blocked at claims selection by four mismatches with eight NPC receipts already present. After review and application, `claims select` succeeds, and grounding publication completes through the unmodified promotion gates. The eight NPC publications are byte-identical and none is re-published. The prior generation directory, its manifest, activations and receipts are byte-identical to before.

**Acceptance Scenarios**:

1. **Given** an approved rebase review, **When** the operator previews application, **Then** the preview names the new generation's parent, every changed custody entry, every repaired claim and every carried member, and is bound to all their digests.
2. **Given** that preview, **When** the operator applies it, **Then** a new generation becomes active through the existing whole-bundle writer, and every old generation, manifest, activation, review and receipt is unchanged byte-for-byte.
3. **Given** the new active baseline, **When** the pending delta is rebound, **Then** a new plan revision references it. Grounding candidate checks and grounding signoffs are invalidated; NPC receipts whose bindings don't involve the changed sources stay valid.
4. **Given** a pending grounding candidate that still carries the old prisoner accounting inherited from the baseline, **When** consistency reruns after rebinding, **Then** the stale assertion is surfaced as a finding, not carried through as verified.
5. **Given** the rebound delta, **When** the existing claims selection, consistency check, exact signoffs and promotion run, **Then** they enforce their normal gates (nothing is mocked or bypassed) and publication completes.
6. **Given** a published NPC dossier that cites a corrected chapter, **When** the rebase is reviewed, **Then** that dossier is listed as an affected consumer for follow-up, and is neither republished nor marked stale by the grounding rebase.

---

### User Story 3 - Recover an Interrupted Repair and Repeat It Safely (Priority: P2)

If application is interrupted, the operator inspects the operation and recovers it to a single consistent outcome: either fully activated or fully not. Repeating an identical application returns the original receipt without writing. If any source, baseline, candidate, repair draft, approval or preview changed after approval, application refuses before activation.

**Why this priority**: Rebase writes the active baseline; a half-applied rebase would be worse than the original refusal. It is P2 only because it reuses the existing journaled writer.

**Independent Test**: Interrupt application at each journaled phase and recover each time; activation is whole-bundle every time. An identical retry returns the original receipt with no writes. Each stale input listed in FR-016 causes a targeted refusal, tested one at a time.

**Acceptance Scenarios**:

1. **Given** an application interrupted after staging but before activation, **When** the operator recovers, **Then** the outcome is either the prior active generation or the fully activated new one, never a mix.
2. **Given** a completed rebase, **When** the identical application is repeated, **Then** it is a no-op that returns the original receipt.
3. **Given** a corrected summary edited again after approval, **When** application runs, **Then** it refuses, naming the changed source.
4. **Given** another generation activated after the preview, **When** application runs, **Then** it refuses with a publication conflict.

---

### Edge Cases

- **Corrected again since inspection.** A chapter's current summary changed after inspection: the review is stale and must be rebuilt.
- **Two corrections of one chapter.** A chapter was corrected twice since the baseline: only the pinned (old) version and the current version matter. Intermediate versions are not adopted.
- **Conflicting old bytes.** Two retrieval providers return different bytes for the same expected digest: impossible under a correct hash. If the bytes hash differently, the provider is wrong and the system refuses for that chapter.
- **Deleted or renamed source.** A pinned source was deleted or renamed: this is reported as missing, never silently treated as adopted. A rename is not inferred from similarity.
- **Selected but unchanged.** The selected chapter's current bytes match the pinned digest: the system reports "nothing to rebase" for that chapter.
- **Unselected stale sources.** Stale sources exist but the GM selects only some: the unselected ones stay stale and keep blocking any gate that depends on them, and the receipt says so.
- **Inherited custody.** The baseline itself inherits custody through a chain of delta generations: the changed pin is found wherever in the chain it was recorded, and the new generation's parent link points to the active generation, not to an ancestor.
- **Correction removes a cited entry.** The correction removes a scene or entry that a baseline citation targets: the claim is affected and the citation no longer resolves. It must be repaired or held. (Citation target validation in general is #597.)
- **Rebase with no pending delta.** The repair stands alone, and its output is the new active baseline.
- **Pending delta without the stale source.** A pending delta's own new chapter is not among the stale sources: its new-chapter evidence is not reparsed.

## Requirements *(mandatory)*

### Functional Requirements

**Inspection and evidence**

- **FR-001**: The system MUST provide an inspection operation that binds the active generation, an optional pending delta plan, and an optional explicit chapter selection. It MUST report every pinned historical source whose current bytes differ or are missing, each with path, chapter, expected digest, actual digest (or "missing") and old-byte availability by provider. It MUST make no writes and no model calls.
- **FR-002**: Claims selection and other custody checks that refuse for stale sources MUST name the stale source(s), the expected and actual digests, and the inspection operation that addresses them, instead of a generic first-source message.
- **FR-003**: The system MUST recover old bytes only from (a) a retained custody snapshot, (b) a Git object located by exact content hash, or (c) an explicitly supplied file. Every candidate MUST be verified against the pinned digest before use. Missing, unverifiable or mismatched bytes MUST produce a per-chapter refusal naming the providers tried.
- **FR-004**: The system MUST snapshot the verified old bytes and the current bytes of each selected source into retained, content-addressed custody. It MUST never write to authored summaries or their replicas.

**Impact review**

- **FR-005**: For each selected source, the review MUST show a readable diff, and every baseline and pending-candidate claim and citation whose recorded source span intersects a changed region. Claims are matched by recorded source hash and byte span, and a citation whose target entry no longer exists counts as affected.
- **FR-006**: Consumers without a recorded per-source dependency (timeline and reference members, and any other whole-file member) MUST be shown as *unknown impact*. Application MUST be blocked until the GM rules on each one: repaired, held, or attested unaffected with a recorded reason. An attestation MUST be recorded as such, never as verified.
- **FR-007**: Historical parsing and model input MUST be limited to the selected chapters and the affected claims' cached evidence. The system MUST NOT perform an implicit all-history scan, extraction, model call or full refresh.
- **FR-008**: Published NPC dossiers and other products that cite a selected chapter MUST be listed as affected consumers for follow-up. The rebase MUST NOT republish them or mark their receipts stale.

**Decisions**

- **FR-009**: Each selected source MUST receive exactly one explicit GM decision:
  - *adopt-unaffected*: allowed only when no affected claim's cited span text changed and no unknown-impact member remains unruled;
  - *adopt-with-repairs*: each affected claim is repaired or explicitly held;
  - *reject*.

  Adopting a source whose affected claims changed in meaning, by hash replacement alone, MUST be refused.
- **FR-010**: A model MAY propose impact assessments or repair text. Proposals are drafts: identity, canon, uncertainty and coverage decisions MUST come from the GM, and no proposal may feed another model call without GM review.
- **FR-011**: Source-adoption decisions, claim repairs, holds, unknown-impact rulings and the concrete application preview MUST be bound together in one review record, digest-bound to the selected sources (old and new), the baseline, the repair drafts and the preview. A change to any of them MUST invalidate it.

**New baseline**

- **FR-012**: Application MUST publish a new grounding generation through the existing whole-bundle promotion writer. The generation MUST record:
  - its parent generation identity and manifest digest;
  - the rebase kind;
  - old and new hashes per changed source, and the retained snapshot locations;
  - the decision record;
  - repaired, held and unchanged members;
  - coverage limits.
- **FR-013**: Unaffected members MUST travel into the new generation by verified custody, byte-identical. Held claims MUST be visibly marked in the documents that carry them. Coverage MUST NOT be claimed as fuller than what was verified.
- **FR-014**: Every existing generation, manifest, activation record, review, authority event and receipt MUST remain byte-identical.

**Resuming the pending delta**

- **FR-015**: The system MUST provide a supported operation that rebinds a pending delta plan to the new baseline as a new plan revision. It MUST:
  - invalidate exactly the checks and signoffs whose bindings include the old baseline or a changed source;
  - preserve independent completed NPC receipts;
  - require the existing claims, consistency, exact-document signoff and promotion gates to rerun.

  No gate may be skipped or mocked.

**Safety**

- **FR-016**: Application MUST require a fresh digest-bound preview and run under the authority lock with journaling. It MUST refuse before activation if any of these changed after approval: a selected source (current bytes), the active baseline, the pending candidate, a repair draft, the approval, or the preview.
- **FR-017**: Interrupted application MUST be recoverable to whole-bundle prior-or-new state. An identical repeated application MUST be a no-op returning the original receipt.
- **FR-018**: The completion receipt MUST report these categories separately:
  - selected sources and decisions;
  - newly parsed historical sources;
  - cached-evidence reuse;
  - model inputs (sources and call counts);
  - integrity-only reads;
  - unselected stale sources remaining;
  - affected-consumer follow-ups.
- **FR-019**: The CLI MUST be the engine. This feature MUST also deliver equivalent application operations in the same release (spec 039 parity): inspection, review preparation, decision recording, preview, apply, recover and plan rebind. The web application MUST invoke the same CLI on the same durable state and MUST NOT reimplement any logic. A review page MUST show source diffs, affected and unknown-impact consumers, the decision controls and the application preview. Saved decisions MUST persist and be validated; stopping the server MUST NOT imply approval.
- **FR-020**: CLI documentation and a migration/recovery runbook MUST explain inspection, recovery providers, the decision types, application, plan rebinding, every refusal code and the operation's limits.

### Key Entities

- **Stale Custody Entry**: a pinned (chapter, path, expected digest) whose current bytes differ, plus its actual digest and old-byte availability.
- **Custody Snapshot**: retained, content-addressed old and current bytes of a selected source, each with its digest and provider provenance.
- **Impact Set**: per selected source, the affected claims and citations (from recorded source spans), the unknown-impact members, and the affected external consumers.
- **Rebase Review**: the GM's decisions per source, repairs, holds and unknown-impact rulings, and the application preview, all digest-bound.
- **Rebase Generation**: a new immutable grounding generation with parent linkage, rebase provenance, member dispositions and coverage.
- **Plan Revision (rebound)**: the pending delta plan bound to the rebase generation, with a record of which artifacts were invalidated and which preserved.
- **Rebase Receipt**: the outcome record from FR-018.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The synthetic chapter-43-style fixture, blocked by four historical-source mismatches, completes grounding publication after a reviewed rebase. No full refresh runs, no manifest is hand-edited, and no gate is bypassed.
- **SC-002**: In 100% of the semantic correction cases in the fixture (payment terms, contradiction removal, knowledge narrowing, prisoner count), adoption by hash replacement alone is refused, and every superseded claim ends repaired or explicitly held.
- **SC-003**: A formatting-only correction completes with zero model calls and zero synthesis.
- **SC-004**: All previously published generations, manifests, activations, reviews, authority events and receipts, plus all eight NPC publications and every unselected dossier, are byte-identical after the rebase. NPC publication count during the resumed run is zero.
- **SC-005**: Each stale-input boundary (source, target, baseline, repair draft, approval, preview) has a test showing a targeted refusal before activation.
- **SC-006**: Interrupting application at every journaled phase recovers to exactly one whole-bundle state. Identical retries perform zero writes.
- **SC-007**: Historical parsing and model input are confined to the selected chapters. The receipt's counts for unselected historical parses and unselected model inputs are zero.
- **SC-008**: Inspection reports all stale sources in one run, not just the first.

## Assumptions

- **Old-byte providers.** The supported providers for old bytes are retained custody snapshots (created by this feature going forward), Git objects found by exact hash in the campaign repository, and explicit files. All are hash-verified. No other provider (backups, network) is in scope.
- **Per-claim attribution.** Per-claim source attribution (source hash and byte span) already recorded by claims annotation is the authoritative dependency index for claims. Members without per-source records are unknown-impact by design, not inferred by similarity.
- **New baseline as a generation.** The new baseline revision is a new generation, not a mutation of the existing adoption record. The adoption record covers document-prose drift; custody rebase is a different decision and gets its own record kind.
- **NPC follow-up is out of scope.** Correcting NPC dossiers that cite a corrected chapter is outside this feature: they are reported, not changed. A follow-up uses the existing NPC delta workflow.
- **Plan identity.** The pending plan keeps its plan id, since the id does not include the baseline. Rebinding produces a new plan revision whose digest changes, which is what invalidates grounding reviews.
- **Tests use synthetic fixtures.** Tests use a synthetic fixture only, with no private campaign dependency and no model endpoint. Model-proposal paths are tested with deterministic stand-ins at the model seam only, never at the claims or promotion boundary.

### Explicit Exclusions

- Disabling integrity checks, editing immutable manifests, or substituting hashes without review.
- Restoring obsolete summaries over reviewed corrections.
- Automatically classifying a canon change as cosmetic.
- Inventing approval, or using a full refresh as an implicit fallback.
- General citation-target validation (#597).

## References (non-normative)

- `pipelines/summary_native/delta/baseline.py`: `_custody_rows`, `custody_resolver_for_generation`, `adopt` (document-drift adoption).
- `pipelines/summary_native/claims/selection.py`: `delta_inherited_custody`, `_discovered_rows` (`CLAIMS_SOURCE_STALE`).
- `pipelines/summary_native/claims/models.py`: `ClaimAnnotation` source attribution.
- `pipelines/summary_native/delta/{grounding_candidates,grounding_publish,grounding_recovery,review_binding,plan,run}.py`.
- `pipelines/summary_native/promotion/{publish,models,manifest}.py`: generations, activations, journaling.
- Reproduction evidence (local only): `/home/kostadis/toee/toee/notes/native_delta/ch043/`.
