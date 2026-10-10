# Feature Specification: Shared Review and Identity Adjudication

**Feature Branch**: `codex/547-review-adjudication`

**Created**: 2026-10-09

**Status**: Draft — validated and ready for planning

**Input**: User description: "Create a new worktree and run speckit-specify using issue #547: one review-and-adjudication workflow, with NPC verification and duplicates as its users. Astra plans; GPT-5.6-Sol orchestrates and codes."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Review NPC Findings on a Phone (Priority: P1)

As a GM, I can open an NPC verification review on my phone, inspect each exact claim and its evidence, record a decision and note, and continue on desktop without recreating my work.

**Why this priority**: The shared workflow and its first real queue must ship together so review solves an actual verification problem.

**Independent Test**: Open a review containing 25 representative NPC findings on a phone, save each decision type, interrupt the connection, restart the service, and continue from the same decisions through the desktop and command-line workflow.

**Acceptance Scenarios**:

1. **Given** an NPC review, **When** the GM opens its supported phone-accessible link, **Then** the claim, cited excerpts, source locations, rationale, proposed action, category, and severity are readable without horizontal page scrolling at 320-pixel width.
2. **Given** a selected item, **When** the GM chooses Approve, Reject, or Discuss and adds a note, **Then** the saved record identifies the review, item, verdict, note, reviewer, time, and reviewed revision; all other access methods show the same decision.
3. **Given** saved decisions and an interrupted connection, **When** the GM reloads or the service restarts, **Then** saved work persists, unsaved work is visibly pending or failed, and no unsaved decision is counted as saved.
4. **Given** a mixed queue, **When** the GM filters, hides approved items, or selects a batch, **Then** counts distinguish total, filtered, selected, settled, and unresolved items; an empty selection changes nothing and refuses a batch action.
5. **Given** a Discuss decision, **When** the GM continues in chat or at the command line, **Then** evidence and discussion notes remain available and the item remains unresolved until an explicit replacement decision is recorded.

---

### User Story 2 - Resolve Verification Failures Without Repeating Settled Work (Priority: P1)

As a GM, I can understand why verification raised a finding, distinguish checkable defects from questions of meaning, and rerun only explicitly selected unresolved work.

**Why this priority**: A failure count alone does not explain what needs fixing, and unrelated regeneration must not erase prior review.

**Independent Test**: Review a queue containing each of the seven required categories, approve selected dispositions, regenerate an unrelated dossier, and rerun selected unresolved items. Then change evidence for one approved item and verify that only its approval becomes stale.

**Acceptance Scenarios**:

1. **Given** a real citation whose text says “second” and a generated sentence claiming “third,” **When** verification and review run, **Then** citation validity is reported separately from support for the claim; the discrepancy is exposed for GM judgment and a successful mechanical check never certifies meaning.
2. **Given** a typography-only difference, **When** it is reviewed, **Then** it is distinguished from unsupported content; any artifact claiming verbatim still requires exactness before publication.
3. **Given** approved items whose claim, evidence, audience, scope, and proposed action have not changed, **When** unrelated dossiers regenerate, **Then** their approvals remain valid.
4. **Given** rejected, discussed, or mechanically failed items, **When** the GM previews and confirms an unresolved rerun selection, **Then** only those selected items are processed; valid approved items are skipped.
5. **Given** changed claim text, relevant evidence, audience, scope, or proposed action, **When** an older decision is encountered, **Then** it remains in history but cannot authorize current application or publication without renewed review.
6. **Given** an approved correction, **When** the GM applies its exact reviewed proposal, **Then** the correction uses the #546 ruling workflow and its source freshness checks; approval alone neither edits sources nor promotes a draft.

---

### User Story 3 - Adjudicate Duplicate Identities Safely (Priority: P2)

As a GM, I can decide whether two candidates represent the same identity, choose the canonical identity and alias scope, inspect every affected artifact, and apply only the reviewed change.

**Why this priority**: Duplicate review must resolve repeated identities and rebuilds, beyond hiding a report row.

**Independent Test**: Review a representative set of 38 candidate pairs containing merge, distinct, discuss, scoped aliases, and filename collisions. Apply an approved collision-free merge and verify identity, references, history, and affected rebuilds; verify that unsafe cases stop without overwriting content.

**Acceptance Scenarios**:

1. **Given** a candidate pair, **When** the GM chooses merge, **Then** the workflow requires a canonical identity, preserves former spellings with explicitly reviewed scope, and shows the proposed changes before application.
2. **Given** a reviewed merge, **When** it is applied, **Then** the registry identity, dependent dossiers, links, citations, filenames, and manifests agree, and the report identifies every changed path and the originating decision.
3. **Given** an ambiguous filename collision, conflicting identity decision, or changed reviewed input, **When** application is attempted, **Then** it stops for review without overwriting unrelated content or declaring completion.
4. **Given** a distinct decision, **When** the same pair is proposed again with unchanged relevant evidence, **Then** the pair is suppressed; new relevant evidence reopens review without erasing the earlier ruling.
5. **Given** a context-limited alias, **When** it is encountered outside its approved scope or without enough context to establish scope, **Then** it does not silently resolve to the merged identity.
6. **Given** two valid names for the same NPC in factually accurate summaries, **When** the GM approves and applies their registry merge, **Then** dependent dossiers combine their evidence under the canonical identity while the summary wording remains unchanged.
7. **Given** a summary incorrectly describes the candidates as different people, **When** their identity merge is reviewed, **Then** the factual contradiction is surfaced for a separate reviewed source correction under #546 and is not silently rewritten or considered corrected by the merge.
8. **Given** an interrupted application, **When** the GM inspects and resumes it, **Then** completed and outstanding changes are explicit; repeating the same completed decision causes no additional mutation.

---

### User Story 4 - Reuse Review for Grounding Documents (Priority: P3)

As a GM, I can review long grounding drafts through the same workflow, preserve document sign-off, and export decisions for the existing apply or promote step.

**Why this priority**: The third supported content type verifies that the shared review works for documents as well as queues without another bespoke page.

**Independent Test**: Review the four grounding documents together, inspect embedded evidence and long content on a narrow screen, record different dispositions, export decisions, and verify that only exact approved revisions are eligible for their existing promotion checks.

**Acceptance Scenarios**:

1. **Given** long grounding drafts, **When** the GM opens their review, **Then** headings, paragraphs, lists, evidence, and proposed replacements remain legible and decisions use the same record format as NPC and duplicate reviews.
2. **Given** all item findings have been handled but document sign-off is absent, **When** promotion is attempted, **Then** the draft remains unapproved.
3. **Given** an exported decision and a matching reviewed document, **When** apply or promote consumes it, **Then** reviewer and provenance are preserved and existing gates still run; changing the document invalidates its sign-off.

### Edge Cases

- The same claim appears twice in one dossier or the same words refer to different entities; decisions must not leak between occurrences or subjects.
- Two devices submit conflicting decisions against the same revision; the later stale submission requires reconciliation instead of silently replacing saved work.
- A decision save succeeds but its response is lost; retrying must not duplicate history or application.
- Sources are missing, unreadable, moved, or no longer match reviewed evidence; review shows the missing evidence and refuses stale application.
- A verifier times out, returns malformed output, or checks only part of a selected set; unchecked items remain unresolved, never implicitly passed.
- A claim has multiple categories, or an unsupported semantic claim is also a knowledge leak; the report preserves all relevant findings.
- An item is approved as requiring no change versus approved for a proposed correction; the approved disposition is explicit.
- A batch contains stale items; the workflow identifies them and never extends approval to changed revisions.
- Merge chains, cycles, already-merged identities, case-only names, multiple aliases for one identity, and overlapping alias scopes need deterministic refusal or an explicit reviewed resolution.
- A missing registry identity requires a reviewed canonical choice, never an inferred identity creation.
- GM-only evidence embedded in a review or diagnostic must remain restricted to the intended reviewer audience.
- A revoked or unauthorized review link cannot read campaign evidence or write decisions; arbitrary requested paths cannot escape the authorized review inputs and decision destination.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Provide one reusable review workflow and decision format for NPC verification findings, duplicate candidates, and grounding documents. Deliver the shared workflow with NPC verification as its first integrated user, then duplicate adjudication.
- **FR-002**: Each decision MUST include format version, campaign and review identity, stable item identity, reviewed revision, verdict, explicit disposition or proposed action, note, reviewer, and timestamp. The decision MUST bind to the exact claim, relevant evidence, input revisions, and applicable checking-rule revision; source paths and excerpts MUST remain available from the reviewed item, with missing evidence explicitly recorded.
- **FR-003**: Support Approve, Reject, Discuss, notes, filters, hide-approved, per-item review, explicit batch selection, progress, export, and resume. Duplicate dispositions MUST be merge, distinct, or discuss; their mapping to common review verdicts MUST be visible and unambiguous.
- **FR-004**: Store review state durably in the campaign workspace so phone, desktop, command line, and agent chat share one authoritative state. Preserve decision history and distinguish saved, pending, failed, and stale states. Conflicting saves against an outdated decision revision MUST require reconciliation, never silently overwrite another decision. Retrying after a lost response MUST record one logical decision rather than duplicate history.
- **FR-005**: Expose every new review, export, rerun, preview, apply, recovery, and migration capability through both command-line and user-interface workflows with equivalent selections and results.
- **FR-006**: Phone access MUST use a supported reachable link, preserve the same review gates, provide touch controls, and fit 320-pixel-wide screens without horizontal page scrolling. A desktop-only localhost link is insufficient.
- **FR-007**: The single review surface MUST be a dedicated LAN/Tailscale capability-URL review server, as selected by the user. The GM MUST explicitly choose the serving address and review before sharing a link. Possession of the authorized link grants access only to that review and its configured decision destination; invalid or revoked links MUST fail. The service MUST NOT expose arbitrary campaign files, directory listings, or unrelated application controls. A security review of this new network surface and its read/write boundaries MUST be completed before release. The existing application MUST provide invocation and status access to this same review surface rather than a separate adjudication page.
- **FR-008**: NPC review items MUST preserve the exact generated sentence or identify a non-sentence failure explicitly, supporting excerpts when available, source locations, verifier rationale, proposed next action, severity, and taxonomy. Missing evidence MUST be represented as missing.
- **FR-009**: Use stable categories: unsupported or contradicted claim; citation resolves but does not entail; later source supersedes; player/character/GM knowledge leak; missing source or broken pointer; typography/presentation only; verifier transport or protocol failure. Group run reports by category and severity, preserving a lossless mapping of existing diagnostic codes and advisories, their detail, and whether an assignment is mechanical, advisory, or GM-confirmed.
- **FR-010**: Mechanical checks MAY establish pointer validity, exact quote differences, audience violations and supersession explicitly encoded in reviewed metadata, and transport/protocol failures. Meaning, inferred knowledge, contradiction, and inferred supersession require GM judgment; a model may suggest findings but cannot settle them. A valid citation MUST NOT be reported as semantic proof. Numeric/ordinal mismatches and inconsistencies with cited evidence MUST be surfaced as advisory candidates, including the #506 false-entailment example.
- **FR-011**: Severity MUST distinguish blocking source/identity/access defects, semantic questions needing judgment, and presentation advisories. Presentation classification MUST NOT waive an artifact's declared exactness requirements. Failed or incomplete verification MUST NOT be represented as a pass.
- **FR-012**: Initial review MUST include all findings in the explicitly selected scope. An unresolved rerun MUST preview an explicit item set and process only selected rejected, discussed, or mechanically failed items; newly pending or stale items require explicit selection for renewed verification. Empty selection MUST refuse, and select-all MUST materialize its members.
- **FR-013**: Approvals MUST survive unrelated regeneration and MUST become stale when the reviewed claim, relevant evidence, identity context, scope, audience, proposed action, or applicable checking-rule revision changes. Distinct decisions MUST suppress only the same pair within their reviewed scope and evidence revision; changed relevant evidence MUST mark the earlier decision stale and reopen its review.
- **FR-014**: Approved decisions MUST be recorded through the shared ruling model established by #546 and linked to the correction or identity proposal and application receipt. Source corrections MUST use #546's reviewed source-change workflow; identity application MUST explicitly extend the ruling integration to registry changes rather than pretending they are summary-text replacements. Review approval alone MUST NOT apply a source change, bypass verification, or provide document sign-off.
- **FR-015**: Duplicate merges MUST require an explicitly chosen canonical registry identity and preserve former spellings as aliases with GM-approved scope. An approved registry merge MUST suffice to resolve identity without requiring summary edits when the summaries contain valid names and accurate facts. Summary corrections MUST be proposed separately through #546 only when their facts are wrong; an identity merge MUST NOT silently correct or conceal a factual contradiction in a summary. Existing narrow duplicate-exclusion rulings MUST NOT silently become merge authority.
- **FR-016**: Scope-limited aliases MUST resolve only within explicitly declared campaign context. Unknown or overlapping ambiguous context MUST require a ruling. No consumer affected by a merge may flatten a scoped alias into an unconditional global alias; scope MUST NOT be inferred from occurrence frequency or location alone.
- **FR-017**: Before merge application, present every affected dossier, summary occurrence, reference, citation, filename, manifest, identity, and planned rebuild, distinguishing references inspected from files proposed for change. Apply MUST be bound to the reviewed input revisions and exact proposed actions. Ambiguous collisions MUST block application.
- **FR-018**: Apply MUST produce a report reproducible from the accepted decision file and its exact bound input revisions, refusing if those inputs are unavailable or changed. The report MUST list every changed path and decision provenance, retain recoverable history, support safe resumption after interruption, and avoid additional changes when the same completed decision is replayed. Regenerate only affected corpus artifacts; unrelated artifacts and approvals MUST remain unchanged.
- **FR-019**: Grounding document review MUST support long formatted drafts with evidence and proposed replacements. Per-item resolution and explicit document sign-off MUST be separate; exported decisions MUST preserve revision binding and required downstream gates.
- **FR-020**: Preserve summary authority, original evidence, and immutable verbatim sources. Semantic corrections MUST use reviewed source changes under #546; identity decisions MUST NOT invent or rewrite events, attribution, or speech.
- **FR-021**: Malformed, unsupported-version, cross-campaign, stale, or conflicting decision input MUST refuse with an actionable explanation. Breaking stored-state changes MUST require a deliberate migration with operator instructions; merely reading a review MUST NOT silently migrate it.

### Key Entities

- **Review**: A campaign-bound collection of items, input revisions, intended reviewer audience, progress, and durable history.
- **Review Item**: A stable subject and occurrence, exact content, relevant evidence, category, severity, proposed disposition, scope, audience, and revision.
- **Decision**: A versioned, attributable human verdict bound to one reviewed item revision, with notes and an explicit domain disposition.
- **Verification Finding**: A check result with taxonomy, severity, rationale, evidence, next action, and an explicit distinction between mechanical observation and semantic judgment.
- **Identity Adjudication**: A merge, distinct, or discuss ruling over identified candidates, including canonical identity and alias scope where relevant.
- **Application Proposal and Receipt**: The reviewed changes and their input revisions, followed by recorded outcomes, changed paths, recovery state, and links to #546 ruling history.
- **Document Sign-off**: Explicit approval of a whole draft revision, distinct from handling its individual findings.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A GM can complete a review containing 25 NPC findings, using all three verdicts and notes, across phone and desktop with zero lost acknowledged decisions after refresh, reconnect, and service restart.
- **SC-002**: At 320- and 375-pixel widths, all review actions and evidence are usable without horizontal page scrolling; a real-phone acceptance walkthrough can open the supported link and confirm saved decisions from desktop and command line.
- **SC-003**: All seven taxonomy categories have representative acceptance examples. The false-entailment and typography-only examples are distinguished correctly, and zero mechanical passes certify unsupported semantic meaning.
- **SC-004**: In a mixed settled/unresolved review, an explicitly selected unresolved rerun processes exactly its selected eligible items; unrelated regeneration preserves 100% of still-valid approvals and changed relevant evidence invalidates 100% of affected approvals.
- **SC-005**: A 38-pair duplicate review demonstrates merge, distinct, discuss, scoped aliases, and collisions. Every approved safe merge has complete change provenance; every ambiguous collision refuses without overwriting content; unchanged distinct pairs remain suppressed.
- **SC-006**: NPC queues, duplicate pairs, and all four grounding drafts complete review and export through the same decision format; no separate copy-paste reconciliation is needed.
- **SC-007**: Replaying a completed application produces no additional change, and interruption/resumption preserves an accountable outcome for every proposed path. Unauthorized access and stale decisions cause zero source mutations.

## Assumptions

- Scope is parent [#547](https://github.com/kostadis/CampaignGenerator/issues/547) and children [#520](https://github.com/kostadis/CampaignGenerator/issues/520), [#523](https://github.com/kostadis/CampaignGenerator/issues/523), and [#522](https://github.com/kostadis/CampaignGenerator/issues/522). [#546](https://github.com/kostadis/CampaignGenerator/issues/546) is a merged prerequisite.
- [#394](https://github.com/kostadis/CampaignGenerator/issues/394) supplies phone continuity and save-feedback acceptance. [#369](https://github.com/kostadis/CampaignGenerator/issues/369) supplies durable findings and shared-viewer precedent; migrating all narration and scrub workflows is outside this feature.
- [#483](https://github.com/kostadis/CampaignGenerator/issues/483) remains open. This feature must handle or safely refuse scoped aliases touched by duplicate application; a campaign-wide registry-cleanup redesign is outside scope. Planning must identify every affected consumer before enabling scoped merges.
- [#506](https://github.com/kostadis/CampaignGenerator/issues/506) informs advisory verification and its regression example. GM judgment settles meaning; automatic semantic certification, model voting, and a new mandatory model pass are outside scope.
- The GM is the reviewer. Reviewer attribution records who made a decision; it is not a substitute for controlling access to private campaign content.
- Approve means accepting the displayed disposition, which may be no change or a specific proposed correction. Reject and Discuss remain unresolved for this workflow; notes alone do not authorize mutation.
- Document review covers the existing four summary-native grounding outputs. Redesigning their generators, transport-level job resume (#519), and the thread-ratification graph editor (#535) are outside scope.
- On 2026-10-09 the user selected a dedicated LAN/Tailscale capability-URL review server. This selects the hosting option in #547 and preserves #520's private sharing behavior. Application launch/status integration satisfies interface reachability; adjudication has one shared page.
- On 2026-10-09 the user selected option A: registry merges resolve identity; summaries require separately reviewed edits only when their facts are incorrect. This resolves #547's open merge-policy question and supersedes the blanket requirement to edit summaries for every duplicate. Summaries remain authoritative for events and claims, and the narrow duplicate-exclusion store does not gain merge authority.
