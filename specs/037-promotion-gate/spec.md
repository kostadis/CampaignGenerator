# Feature Specification: Reviewed Bundle Promotion Gate

**Feature Branch**: `codex/548-promotion-gate`

**Created**: 2026-10-10

**Status**: Draft

**Input**: Specify issue #548, including #521 (whole-bundle promotion) and #517 (cross-document checks after an evidence spike), in a new worktree. Use codememory-mcp for discovery, Astra for specification/planning, and the previously approved available GPT-5.6-Sol for orchestration/coding.

## Planning Prerequisite and Evidence Status

The five-example feasibility investigation is recorded in [spike.md](spike.md). The original faulty draft bundle is unavailable. On 2026-10-10 the user explicitly approved completing the plan with reconstructed fixtures based on surviving sources, with the historical replay limitation recorded. This resolves the planning evidence gate without claiming recovery of the original failures. The promotion foundation is delivered first; the claims checker then follows the spike’s finding that all five original prose shapes require candidate interpretation and GM judgment before deterministic comparison.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Preview the Exact Reviewed Bundle (Priority: P1)

As a GM, I can select one campaign range and inspect everything that promotion would change, including supporting references, before authorizing publication.

**Why this priority**: The current manual copying workflow makes it easy to omit supporting files or combine different generations.

**Independent Test**: Preview a complete reviewed bundle against an existing live bundle; compare every displayed source, destination, and change with the selected files and verify that preview changes nothing on disk.

**Acceptance Scenarios**:

1. **Given** a complete reviewed range, **When** I preview promotion, **Then** I see the four grounding documents, timeline, complete generated reference directory, retained reading-contract path records, and all additions, replacements, removals, and content differences.
2. **Given** a missing document, missing required reference, incomplete draft, stale source, or absent/currently invalid document sign-off, **When** I preview or promote, **Then** the result identifies each blocking condition and the action needed to resolve it; promotion is unavailable.
3. **Given** item-level approvals without whole-document sign-off, **When** I request promotion, **Then** those decisions do not substitute for approval of each of the four exact draft revisions.
4. **Given** no explicit campaign range selection, **When** I request preview or promotion, **Then** the operation refuses without selecting a range for me.
5. **Given** changed draft content, supporting evidence, reference content, or live destination content after preview, **When** I attempt to publish the previously previewed change, **Then** the operation refuses and requires a current preview and any affected renewed review.

6. **Given** an older individual-document publication entry point, **When** it attempts to install live grounding output, **Then** it either invokes this same complete-bundle gate or refuses with the whole-bundle workflow instructions; it cannot bypass the gate.

---

### User Story 2 - Publish One Complete Generation Safely (Priority: P1)

As a GM, I can publish the reviewed bundle in one explicit operation and retain the previous usable generation if anything fails.

**Why this priority**: A partially replaced grounding bundle can mislead session preparation even if each individual document looks valid.

**Independent Test**: Publish a reviewed bundle, verify every live member and receipt, then repeat with failures at each publication boundary and verify that no mixed generation is available to supported readers.

**Acceptance Scenarios**:

1. **Given** a complete, current, approved bundle with passing gates, **When** I confirm promotion, **Then** the four documents, timeline, and references become one live generation, with pointer and outline checks passing against the destination layout and a durable receipt identifying the exact publication.
2. **Given** a copy, validation, receipt, or activation failure, **When** promotion stops, **Then** the previous live generation remains intact and usable; on the first promotion, no incomplete live generation is exposed.
3. **Given** an interruption during promotion, **When** I inspect or retry the operation, **Then** its completed, failed, or recovery-required state is explicit, and recovery cannot expose a partially installed generation or report unverified success.
4. **Given** two simultaneous promotions or a concurrent source/destination change, **When** they compete to publish, **Then** only an operation still matching its reviewed inputs and expected live generation can succeed; the other receives an actionable conflict.
5. **Given** a successful promotion, **When** I inspect its receipt, **Then** I can identify the selected range, source and destination revisions, review provenance, replaced generation, every affected path, and all gate outcomes; no commit or push has occurred.
6. **Given** an unchanged completed promotion, **When** I retry the same operation, **Then** I receive its recorded result without additional content mutation or a second logical publication.

7. **Given** existing loose live files without a generation record, **When** the workflow first encounters them, **Then** it preserves them and requires explicit inventory and validation before adopting them as a prior generation; any required migration is deliberate and documented.

---

### User Story 3 - Resolve Cross-Document Findings Before Publication (Priority: P2)

As a GM, I can inspect conflicting or overstated claims across the four documents, distinguish facts that code can check from questions needing my judgment, and prevent known blocking defects from reaching live documents.

**Why this priority**: Structurally valid documents can still assign a task to the wrong party, exaggerate suspicion, or retain superseded obligations. This work follows the promotion foundation and the five-example feasibility spike required by #548.

**Independent Test**: Exercise the five Phandalin failure shapes and positive controls. Verify evidence-backed mechanical findings where structured authority exists and an explicit candidate-for-GM outcome where meaning must be judged; then test promotion with blocking, informational, settled, stale, and incomplete results.

**Acceptance Scenarios**:

1. **Given** compatible structured claims and explicit authoritative status, ownership, chronology, or audience metadata, **When** checking the bundle, **Then** reproducible conflicts identify both assertions, their locations, authority, and the precise rule violated.
2. **Given** prose requiring interpretation, such as calling Sridar a conspirator or the Eastern Heart refugees hostile, **When** a potential conflict is surfaced, **Then** it remains a candidate for GM judgment; matching words or resolving citations do not establish semantic truth.
3. **Given** a confirmed blocking finding, **When** promotion is attempted, **Then** it stops until the source is corrected and the affected drafts are regenerated and reviewed, or a current GM ruling dismisses the candidate with evidence that the draft is not defective. A ruling confirming false prose remains blocking until correction, regeneration, and renewed sign-off. A semantic approval cannot waive a broken pointer, incomplete bundle, or stale review.
4. **Given** informational uncertainty only, **When** all required checks have completed and sign-offs are current, **Then** promotion may proceed and the uncertainty remains visible in the report and receipt.
5. **Given** an unavailable source, failed check, or unchecked required portion of the selected scope, **When** the gate runs, **Then** the result is incomplete and blocks publication rather than claiming a clean report. An explicitly disclosed limit on automated semantic coverage is distinct from a failed required check.
6. **Given** a recorded GM resolution, **When** its relevant claim, evidence, audience, or authority changes, **Then** the old ruling remains in history but cannot settle the changed finding.
7. **Given** a GM-only source, **When** the checker or reviewer presents evidence, **Then** audience restrictions are preserved and the evidence cannot be copied into party-facing material merely to explain a finding.

8. **Given** a candidate requiring GM disposition, **When** it is pending, rejected for correction, or marked Discuss, **Then** publication blocks; an evidence-backed dismissal or a ruling that the displayed uncertainty is acceptable can make it nonblocking without rewriting authority.
9. **Given** a completed check with a declared limitation in semantic coverage and no specific unresolved candidate, **When** that limitation is reported, **Then** it is informational; a missing required source or failed required check cannot be relabeled as a coverage limitation.

---

### User Story 4 - Reach the Same Workflow from the Application (Priority: P2)

As a GM, I can select a range, preview, check, review findings, publish, and inspect outcomes from the application or command line with the same rules and durable state.

**Why this priority**: The repository requires every new command-line capability to be reachable from the application in the same feature.

**Independent Test**: Perform equivalent operations through both entry points and compare selected scope, manifests, eligibility, finding dispositions, receipts, and refusal reasons.

**Acceptance Scenarios**:

1. **Given** the same selected bundle, **When** I preview or check it from either entry point, **Then** I see equivalent changes, gate results, and review status.
2. **Given** a report requiring GM judgment, **When** I open its review, **Then** the existing shared review workflow preserves claim locations, evidence, notes, decisions, and freshness binding.
3. **Given** a successful, blocked, or interrupted publication, **When** I return later or change entry points, **Then** I can discover its actual state and required next action from durable records.

### Edge Cases

- Missing or empty required references; nested references; removed references still needed by an old live document; obsolete generated members mixed with unrelated hand-authored files.
- A complete-looking draft with incomplete-generation markers or a different range's provenance.
- A changed timeline/reference file with unchanged document text; changed authority or source evidence after sign-off.
- Existing live prose edits since the last publication; preview must show their replacement, and later changes must cause a conflict.
- First publication, repeated publication, disk exhaustion, permission failure, interrupted publication, and receipt failure.
- Readers opening several bundle members while publication occurs; supported consumers must see a consistent generation or an explicit retry/unavailable outcome.
- Paths escaping the selected campaign or linking outside its permitted bundle; ambiguous destination ownership must block destructive changes.
- Equivalent aliases, duplicated claims, different temporal scopes, disputed source priority, missing audience labels, or prose with no structured claim representation.
- A source location resolves but does not support the asserted meaning; an old proposal is confused with an accepted obligation.
- A model or reviewer cannot inspect a required source; lack of evidence is visible and does not become a verdict.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Provide explicit preview and promotion for one selected campaign range. Empty selection MUST refuse. `summary_native promote --dry-run` is the requested command contract and MUST show the full manifest and differences without writing campaign files, reports, receipts, or review state or calling a model.
- **FR-002**: The promotion unit MUST contain `world_state`, `campaign_state`, `party`, `planning`, `canon_events_timeline.md`, the complete generated `reference/` directory, and the reading-contract path records required to interpret their links. Each member MUST belong to the same selected generation; every required dependency MUST be accounted for.
- **FR-003**: Drafts MUST remain under the selected range's `state/` area. Promotion MUST be the only summary-native workflow that installs these generated grounding members into live `docs/`. Existing individual `review document prepare/promote` publication capabilities MUST delegate to this complete-bundle gate or refuse with instructions for the new workflow; they MUST NOT remain a live-publication bypass. Other unrelated document pipelines and deliberate human edits are outside this restriction.
- **FR-004**: Require current explicit whole-document sign-off for all four draft revisions using the shared #547 review state and #546 authority history. Item approvals, a range name, file presence, and absence of findings MUST NOT count as sign-off. A sign-off MUST cover the draft text, its cited evidence and required support files, applicable audience/identity/authority context, and the checking rules presented during review. Changes in that bound set MUST require renewed review; changes only to the expected live destination invalidate the publication preview, not source approval. Newly discovered unresolved findings invalidate promotion eligibility until disposition even if document bytes are unchanged. Unrelated changes MUST NOT erase valid review history.
- **FR-005**: Preview MUST enumerate exact source and destination paths, content identities, additions, replacements, removals, and differences, including any live manual edits that would be overwritten. Unrelated live files MUST remain untouched; uncertain ownership of a proposed removal MUST block it. Commit MUST revalidate the previewed inputs and destination generation.
- **FR-006**: Publication MUST expose one complete validated generation to supported readers: repository command-line and application consumers of these grounding documents, including session preparation, grounding/planning reads, and review/promotion inspection. Every such consumer MUST either read a single generation throughout an operation or refuse/retry explicitly when consistency cannot be assured. Uncoordinated external editors reading multiple paths over time are outside that concurrent-read guarantee; a completed or failed operation must still leave a complete stable live bundle for ordinary file access. Failure or interruption MUST leave the previous generation intact and usable, with no successful result for a mixed generation. Recovery state MUST be discoverable; retry of a completed operation MUST produce no additional mutation.
- **FR-007**: Pointer, outline, completeness, freshness, review, and applicable cross-document checks MUST participate in the same promotion gate. Pointer and outline checks MUST also validate the copied bundle in its destination layout before success is reported. Failed, missing, or incomplete required checks MUST block publication.
- **FR-008**: Successful publication MUST have a durable machine-readable receipt identifying the operation, campaign/range, source and destination content identities, previous and new generation, review decisions, all affected paths, gate results, relevant findings and resolutions, and completion time. Failed/interrupted attempts MUST be distinguishable from success. Receipt failure MUST NOT leave an unrecorded successful publication.
- **FR-009**: Promotion MUST NOT commit or push, rewrite source summaries, invent campaign facts, silently apply corrections, or start paid/model work. Correction of a factual defect MUST follow the reviewed #546 source workflow before affected drafts are regenerated and signed off.
- **FR-010**: Before implementing or finalizing detailed scope for #517, complete a recorded feasibility spike on all five Phandalin failure shapes. Per the 2026-10-10 user ruling, explicitly labeled reconstructed fixtures based on surviving original sources satisfy this planning prerequisite when faulty originals are unavailable. For each, identify available on-disk claims and authority, reproduce the failure shape, classify it as mechanically checkable from existing structured evidence or requiring candidate extraction plus GM judgment, and record missing evidence and limits. A hypothetical structured fixture MUST NOT be presented as proof that the original prose can be checked mechanically.
- **FR-011**: Cross-document reports MUST distinguish direct contradiction; stale claim superseded by a later source; suspicion stated as fact; GM-only truth leaked into party knowledge; resolved item still described as active; and incompatible ownership, debt, location, or status. Findings MUST include both assertions for any mechanically established contradiction or supersession, exact locations, authority/provenance, applicable audience and time scope, severity, rationale, and next action. A missing counterpart MUST be reported as missing evidence or a judgment candidate, never as a completed mechanical contradiction or supersession finding.
- **FR-012**: Mechanical verdicts MUST be limited to relationships explicitly established by structured, reviewed authority and claim data. Temporal supersession, identity, attribution, hostility, certainty, and audience MUST NOT be inferred as authoritative from prose or citation presence alone. Disputed authority MUST be referred to the GM.
- **FR-013**: Judgment-dependent findings MUST enter the existing shared review workflow as candidates. Human resolutions MUST record reviewer, disposition, rationale, and exact relevant revisions. Automated candidate extraction, if justified by the spike, MUST be a separately selected operation whose outputs require GM review before affecting authority; promotion itself remains deterministic and model-free.
- **FR-014**: Reports MUST separate mechanically established blockers, GM-confirmed blockers, unresolved semantic candidates, and informational uncertainty. Unresolved semantic candidates MUST remain visible for explicit GM disposition before whole-document sign-off can authorize promotion. A candidate may be dismissed with evidence, confirmed as requiring correction, marked Discuss, or explicitly accepted by the GM as nonblocking uncertainty. Pending/Discuss and confirmed-incorrect cases MUST block. Acceptance of uncertainty MUST NOT assert new facts or waive confirmed false prose. Informational uncertainty means a declared coverage limitation without a specific unresolved candidate, or a current GM decision accepting uncertainty; it alone MUST NOT block. Failed checks and missing required evidence cannot use this category. A current ruling can settle a semantic candidate but cannot waive mechanical integrity or freshness failures.
- **FR-015**: Provide both structured JSON and human-readable cross-document reports covering the selected four-document bundle, latest relevant summaries, and configured high-authority notes. The check manifest MUST identify every selected source revision, the selected range and effective horizon, any later source consulted, and the applicable authority/rule revisions. Relevance MUST follow cited subjects and explicit dependency/authority links, with ambiguity surfaced for GM selection; filename or timestamp recency alone MUST NOT decide supersession. Reports MUST disclose checked scope, unavailable inputs, semantic coverage limits, and completion state. Rechecking identical reviewed inputs and rules MUST produce the same mechanical findings.
- **FR-016**: Every selection, preview, checking, review, promotion, receipt inspection, recovery, and migration capability introduced by this feature MUST be reachable from command line and application with equivalent controls and results. Review MUST reuse #547's shared private review surface and preserve audience restrictions; application state alone MUST NOT authorize publication.
- **FR-017**: Concurrent operations and changes between preview, validation, and publication MUST be detected and prevented from mixing generations or overwriting unseen live changes. Paths outside the authorized campaign and bundle MUST refuse. The concurrency guarantee covers repository readers/writers using the managed boundary; noncooperating external editors must not modify managed files during publication. Observed external changes MUST also refuse, but advisory locks cannot guarantee exclusion of arbitrary external processes.
- **FR-018**: Existing loose live files MUST be explicitly inventoried and validated before being adopted as a prior generation; their presence alone MUST NOT establish coherent generation membership. If delivery changes stored workspace layout or state formats, provide an explicit migration and operator instructions, including affected workspaces, exact invocation, refusal behavior before migration, and verification afterward. Reads and routine promotion MUST NOT silently migrate old state.

### Key Entities

- **Grounding Bundle**: One selected range's four documents, timeline, references, required path records, and dependency identities.
- **Generation**: A complete, identifiable version of a live or candidate grounding bundle.
- **Promotion Preview**: Exact proposed changes and their eligibility, bound to selected sources and the expected live generation.
- **Document Sign-off**: Human approval of an exact draft and relevant evidence, independent from individual finding dispositions.
- **Claim and Authority Evidence**: An assertion, its subject, location, time/audience scope, and supporting or superseding source; unknown attributes remain unknown.
- **Cross-Document Finding**: A mechanical observation or semantic candidate, with category, severity, evidence, scope, and resolution status.
- **GM Resolution**: A durable human disposition bound to the relevant claim and evidence revisions.
- **Promotion Receipt**: The accountable record of a completed publication, its generation membership, review authority, and validation results.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For every acceptance bundle, preview lists 100% of proposed additions, replacements, removals, and supporting members, and leaves all campaign file contents and review state unchanged.
- **SC-002**: Across successful, failed, interrupted, and concurrent publication scenarios, supported readers observe zero mixed generations; failed publication preserves 100% of the previous live bundle and unrelated files.
- **SC-003**: All incomplete, stale, missing-sign-off, changed-after-preview, and mechanically invalid acceptance cases refuse publication with an actionable explanation. Every successful case passes destination pointer and outline checks and has exactly one logical publication receipt.
- **SC-004**: Each of the five Phandalin failure shapes has a recorded evidence classification, a regression fixture, and a positive control. Original-case reproducibility and synthetic rule coverage MUST be reported separately; an original case with missing evidence remains historically unverified; user-approved reconstructed fixtures satisfy feature acceptance only when their constructed assertions and surviving source provenance are explicit. Zero semantic candidates are represented as mechanically proven merely because citations or keywords match.
- **SC-005**: All six finding categories appear in structured and readable acceptance reports with source locations and authority or an explicit missing-evidence statement. Blocking and informational cases produce their specified promotion outcomes.
- **SC-006**: A GM can complete preview, review follow-up, promotion, and receipt inspection through either supported entry point without manual multi-file copying or reconciling separate review state; equivalent selections produce equivalent outcomes.
- **SC-007**: Repeating completed promotion creates zero additional content changes, and every interrupted acceptance case has an inspectable outcome and a documented safe recovery path.

## Assumptions

- Scope is [#548](https://github.com/kostadis/CampaignGenerator/issues/548), with [#521](https://github.com/kostadis/CampaignGenerator/issues/521) delivered first and [#517](https://github.com/kostadis/CampaignGenerator/issues/517) following its required spike. The full feature is not complete until the resulting cross-document gate is integrated; a staged promotion foundation must disclose absent semantic coverage.
- The baseline is merged #546 and #547 at `5e63e852f3f45dd9bfd9c6b4e62a83cbec43cbc0`. Their existing current sign-offs replace #548's provisional suggestion of a simple range declaration; no second review authority is introduced.
- The five Phandalin examples are Earthstone assigned to the wrong party; Eastern Heart refugees called hostile Talosians; Sridar promoted from plausible collector to conspirator; Petra's superseded 500 gp proposal retained as active debt; and Leilon presented as immediate despite the Cassian/manifold-first ruling.
- The spike determines which examples have sufficient existing structured evidence. Missing original inputs remain a reported limitation. On 2026-10-10 the user approved reconstructed fixtures with the limitation recorded; they establish failure-shape coverage, not exact original-corpus replay.
- Summary authority and explicit GM rulings remain authoritative. Promotion is publication of reviewed output, never an opportunity to reinterpret facts or repair sources silently.
- The target is the existing single-GM campaign workflow. New public hosting, multi-user account management, a replacement review application, and unrelated campaign-wide generator redesign are outside scope.
- Existing supported campaign readers must participate in consistent-generation reading if needed. The implementation plan must define the supported filesystem and recovery guarantees explicitly and cannot describe sequential file replacement as atomic publication.
- Any optional model extraction removes no human precision decision: the GM settles its candidates. Its invocation, boundaries, cost/scope controls, and feasibility must be justified after the spike; guarded deterministic modules remain model-free.
