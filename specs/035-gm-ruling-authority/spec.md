# Feature Specification: GM Rulings and Authority Tiers

**Feature Branch**: `codex/546-gm-rulings`

**Created**: 2026-10-09

**Status**: Draft

**Input**: User description: "Specify issue #546 as one feature covering replayable GM corrections and first-class campaign notes, including authority tiers, precedence, knowledge audiences, and one ruling record."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Preserve a Reviewed Correction (Priority: P1)

As a GM, I can record a reviewed correction once, review its exact source change, and apply it to the maintained authoritative source so every regenerated campaign-state document uses the same corrected truth while retaining the original evidence and decision history.

**Why this priority**: Regeneration currently restores claims the GM already corrected, making generated state unreliable and forcing repeated manual edits.

**Independent Test**: Record one correction to an identified claim, review and apply its source correction, regenerate every affected state document, and verify that each uses the corrected source truth, cites the decision, and preserves the original evidence and decision history.

**Acceptance Scenarios**:

1. **Given** a generated claim that the GM has corrected, **When** the GM reviews and applies the proposed correction to its authoritative source and regenerates the affected documents, **Then** the correction appears consistently in world, campaign, and planning views with its decision provenance.
2. **Given** an applied correction, **When** all derived artifacts are forcibly rebuilt, **Then** the corrected source remains authoritative without a hand edit to any generated document.
3. **Given** an applied correction is later withdrawn, **When** the GM requests reversal, **Then** the system proposes a reviewed source change against the source's current digest and does not silently revert later legitimate edits or erase the correction history.

---

### User Story 2 - Use Campaign Notes in Planning (Priority: P2)

As a GM, I can select campaign notes and future prep as planning inputs so active ordering, unresolved bookkeeping, intended scenes, and knowledge boundaries inform the plan without being presented as events that already happened.

**Why this priority**: Important current planning state often lives outside summaries, and omitting it produces incomplete or misleading plans.

**Independent Test**: Select a set of notes spanning established facts, rulings, prep, overlays, and open questions; generate a plan; and verify that each item appears with its authority, status, audience, and provenance intact.

**Acceptance Scenarios**:

1. **Given** configured note files and scoped selections, **When** the GM starts a planning run, **Then** every matching readable note is included and every selected input is listed with its classification and digest.
2. **Given** a ruled note changes the active order of plots, **When** planning is regenerated, **Then** the new order is used without representing the ruling as player-visible campaign history.
3. **Given** prep or open material, **When** planning is generated, **Then** it remains clearly prospective or unresolved in every resulting view.
4. **Given** a selected future-planning note predates the latest included session, **When** planning begins, **Then** the GM is warned that the planned events may already have occurred.

---

### User Story 3 - Keep Knowledge Audiences Separate (Priority: P3)

As a GM, I can declare who may know each note or ruling so GM-only truth, player knowledge, and individual character knowledge remain distinct throughout generation and review.

**Why this priority**: Authority answers whether a claim governs the campaign; audience answers who may see it. Conflating them can reveal secrets or assign knowledge to the wrong character.

**Independent Test**: Use one fact with different GM, player, and named-character audiences, produce each available view, and verify that every audience receives only permitted material.

**Acceptance Scenarios**:

1. **Given** a GM-only ruling, **When** a player-facing or character-facing artifact is produced, **Then** the ruling content is excluded before any prose is rendered.
2. **Given** information known to the players but not to a character, **When** that character's perspective is produced, **Then** the information is absent.
3. **Given** information known to one named character, **When** views for other characters are produced, **Then** they do not receive it unless explicitly included in the audience.
4. **Given** a record without a valid audience, **When** it is selected, **Then** generation refuses rather than guessing who may see it.

---

### User Story 4 - Review Conflicts and History (Priority: P4)

As a GM, I can see when later authoritative evidence conflicts with an applied correction's decision record, inspect both the source history and current effective truth, and resolve the conflict explicitly.

**Why this priority**: Silent precedence would hide contradictions and make it impossible to explain why a generated claim changed.

**Independent Test**: Add later authoritative evidence that contradicts an applied correction and verify that the conflict identifies the decision record, evidence, affected projections, and required review without changing either record silently.

**Acceptance Scenarios**:

1. **Given** later authoritative evidence that contradicts an applied correction's decision record, **When** affected material is checked or regenerated, **Then** a review finding identifies the decision, the later evidence, and every affected projection.
2. **Given** incompatible proposed corrections over the same source claim and effective period, **When** the records are validated, **Then** their application is blocked until a GM resolves the ambiguity.
3. **Given** a resolved conflict, **When** the GM inspects its history, **Then** the original evidence, superseded decisions, current effective truth, reviewer, and dates remain traceable.

### Edge Cases

- A selected note matches more than one configured selection; it is included once and retains one stable identity and digest.
- A configured file, directory, or scoped selection is missing or unreadable; affected generation refuses and identifies the exact selection to repair.
- A configured selection resolves to no notes; planning refuses rather than silently running without the expected inputs or expanding the selection.
- A selected note is outside the campaign directory; it remains eligible only when it was explicitly selected and can be read, and its external location is made visible in the selection preview and run record.
- A note has an unknown tier, missing audience, invalid effective chapter, duplicate stable identifier, or an identity that cannot be resolved exactly.
- Two proposed corrections overlap only part of a chapter range or affect different projections of the same subject.
- A ruling rejects a claim pattern that no longer appears after regeneration; the ruling remains attached through stable subject and scope rather than stale wording alone.
- A correction attempts to rewrite verbatim speech or another immutable source record.
- A future-prep note has no date, has a date equal to the latest session, or contains a mixture of completed and still-future events.
- A note is safe for one named character but contains adjacent GM-only material; audience filtering applies at the smallest independently classified record.
- An older generated artifact reflects a withdrawn or superseded ruling; freshness reports it as stale.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide one campaign-local ruling model that records a stable identifier, stable subject or thread identity, rejected claim or claim pattern, replacement fact or decision, scope, effective chapter or period, authority type, audience, decision status, decision date, reviewer, affected projections, and a mandatory source pointer for every source-changing ruling. A planning note that proposes no source change may omit the source pointer.
- **FR-002**: The system MUST distinguish preserved original evidence from effective truth. Applying, superseding, withdrawing, or removing a correction MUST NOT rewrite verbatim speech or erase prior evidence or decision history; a maintained authoritative summary may change only through the reviewed source correction or annotation workflow.
- **FR-003**: The system MUST require explicit human approval before a proposed correction may change an authoritative source; approval of generated text alone MUST NOT apply the source change.
- **FR-004**: An applied source correction MUST survive forced rebuilding, extraction, and regeneration of every affected state document and MUST produce consistent effective truth across those documents.
- **FR-005**: The system MUST apply authority classifications consistently: `RULED` for a reviewed instruction to correct or annotate an authoritative source, `CANON` for established campaign truth, `TABLE` for facts or corrections explicitly established during play, `PREP` for intended future material, `OVERLAY` for current planning direction that does not assert history, and `OPEN` for unresolved possibilities or questions. A `RULED` record alone MUST NOT override an uncorrected summary.
- **FR-006**: A `RULED` record MUST identify the exact subjects, claims, chapter scope, projections, and authoritative source change it proposes. Applying it MUST require a human-reviewed patch or annotation and MUST verify that the source still matches the digest reviewed by the human; a mismatch MUST refuse and require a refreshed proposal. Summaries remain authoritative after the reviewed change is applied.
- **FR-007**: `CANON` and `TABLE` MUST both be treated as established evidence within their declared scope. Neither label inherently outranks the other: an explicit, reviewed supersession of the same scoped claim wins; otherwise incompatible established evidence requires a GM ruling, regardless of file order or recency.
- **FR-008**: Within future planning, a scoped `OVERLAY` MUST direct the current plan ahead of conflicting `PREP`; incompatible overlapping overlays MUST require review. Neither classification has authority to assert completed history. `OPEN` MUST remain visibly unresolved and MUST NOT settle an effective fact.
- **FR-009**: Authority classification and knowledge audience MUST be independent. A record's audience MUST support GM-only, all-player, all-character, and named-character access without treating player knowledge as character knowledge.
- **FR-010**: The system MUST exclude content outside the target audience before that content enters any rendering input, generated artifact, preview, export, or diagnostic intended for that audience.
- **FR-011**: A missing, malformed, or ambiguous authority or audience declaration MUST cause affected generation to refuse with an actionable explanation rather than infer authority or access.
- **FR-012**: The GM MUST be able to select planning note files and scoped groups explicitly, preview the resolved selection, and see why each file was selected before generation.
- **FR-013**: A missing or unreadable configured input, or a configured selection that resolves to no notes, MUST cause affected generation to refuse with an actionable explanation. Explicitly selected readable notes outside the campaign directory MUST be identified as external in previews and run records rather than rejected solely for location.
- **FR-014**: Every selected note and ruling MUST appear in the run record with its stable identity, classification, audience, location, content digest, and effective scope.
- **FR-015**: Editing, adding, removing, reclassifying, superseding, or withdrawing any selected note or ruling MUST make dependent drafts stale.
- **FR-016**: The system MUST warn when selected future-planning material predates the latest included session and may describe events that have already occurred.
- **FR-017**: A structured contradiction, or a contradiction explicitly identified by a human reviewer, between later authoritative evidence and an applied correction's decision record MUST create a review finding that identifies both sources and affected projections. Unstructured prose may be presented as a candidate for GM judgment but MUST NOT receive an automatic verdict.
- **FR-018**: Incompatible proposed corrections for the same source claim and scope MUST block application until the ambiguity is resolved; file order and proposal date MUST NOT choose a winner.
- **FR-019**: Every authoritative claim changed by a reviewed correction MUST expose provenance to the original evidence, the decision record, and the applied source change in audit and run history.
- **FR-020**: Withdrawing an applied correction MUST create a reviewable reversal proposal against the current source digest. The system MUST NOT blindly restore old text, overwrite later legitimate edits, or remove the historical correction record.
- **FR-021**: The feature MUST use one new campaign-local authority ledger for general rulings and classified planning notes. Existing stores retain their narrow meanings and are referenced rather than reinterpreted: the duplicate/link decision store remains limited to not-a-duplicate and link decisions, the known-stale provenance store remains search-result context, and the transcript correction store remains verbatim transcript repair.
- **FR-022**: Campaigns with data that must move to the new record shape MUST have an explicit, one-time migration that previews changes, refuses ambiguous mappings, does not overwrite valid existing records without an explicit choice, and reports anything left unmigrated. Its migration guide MUST identify affected workspaces, the exact invocation, behavior while records remain unmigrated, and verification steps. The system MUST NOT lazily upgrade data during normal reads or retain fallback readers for a retired shape. Existing narrow stores require no migration merely because the new ledger exists.
- **FR-023**: The ruling and note workflow MUST provide equivalent capabilities through command-line and graphical campaign workflows in the same release, including selection preview, validation, approval, conflict review, status, and provenance inspection.
- **FR-024**: Every state-changing operation MUST identify the exact campaign, records, scope, and resulting status before it is applied, and generated content MUST never count as approval.
- **FR-025**: The system MUST retain enough decision history to explain which ruling was active for a given generated run and why a later run differs.
- **FR-026**: Basic structured conflicts, stale inputs, invalid scopes, and audience violations MUST be detected without assigning unstructured narrative contradictions a machine verdict; deeper cross-document claims review remains outside this feature.

### Key Entities

- **Ruling Record**: A stable, human-reviewed instruction to correct or annotate an exact authoritative source claim for a declared subject, scope, audience, and set of projections; it records the decision but does not independently outrank the source.
- **Campaign Note**: A selected authored input with stable identity, provenance classification, audience, date or effective range, content digest, and source location.
- **Authority Classification**: The meaning and precedence behavior of `RULED`, `CANON`, `TABLE`, `PREP`, `OVERLAY`, and `OPEN`, independent of audience.
- **Knowledge Audience**: The people or character perspectives allowed to receive a record: GM, players, all characters, or named characters.
- **Effective Claim**: The claim a projection may use after authoritative source corrections and classifications are evaluated; it links back to every source and decision that produced it.
- **Conflict Finding**: A reviewable relationship between incompatible records, carrying both identities, overlap scope, affected projections, status, and resolution history.
- **Run Input Record**: The complete set of selected notes and rulings, their digests and classifications, used to reproduce and freshness-check one generation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a fixture covering world, campaign, and planning views, 100% of affected claims use one reviewed and applied source correction after repeated forced regeneration, with no edits to generated output.
- **SC-002**: For every completed planning run, 100% of selected notes and rulings are represented in its input record with identity, classification, audience, scope, and digest.
- **SC-003**: Changing any selected note or ruling causes 100% of dependent drafts in the fixture set to report stale before they can be treated as current.
- **SC-004**: Across the audience-isolation test set, zero GM-only or non-character knowledge items appear in unauthorized rendering inputs or outputs.
- **SC-005**: In structured and human-identified conflict fixtures, 100% of later-evidence conflicts and overlapping incompatible rulings are surfaced with both sources and affected projections; none are resolved silently, and unstructured prose receives no automatic verdict.
- **SC-006**: A GM can select notes, preview classifications and audiences, review and apply one correction, and inspect its impact in no more than five workflow actions in either supported interface.
- **SC-007**: In 100% of withdrawal fixtures, requesting withdrawal produces a reviewable reversal against the current source, preserves later legitimate edits, and retains the complete correction history; no source is reverted automatically.
- **SC-008**: Migration fixtures preserve 100% of valid legacy decisions, report 100% of ambiguous records for review, and leave original stores recoverable.
- **SC-009**: In the acceptance examples for all six classifications, the GM can identify whether each item is established, ruled, prospective, planning-only, or unresolved directly from its displayed classification and audience.

## Assumptions

- Only an authenticated or locally authorized GM may approve, supersede, or withdraw rulings; generated content and model suggestions are never approvals.
- Summaries remain the authority for reported campaign history. A ruling becomes effective only through an explicitly reviewed and digest-guarded correction or annotation to the maintained authoritative source.
- Stable subject and thread identities already governed by campaign registries are reused; similarity matching does not establish identity.
- Authority and audience are declared per independently usable record. A mixed note must be split or classified in sections before it can safely serve different audiences.
- `TABLE` describes facts or corrections explicitly established during play; `CANON` describes established campaign truth from maintained authoritative material.
- `OVERLAY` directs the current plan without asserting that an event occurred; `PREP` describes intended future material that may be invalidated by later play.
- The feature reports structured overlap and provenance conflicts. Broad semantic contradiction detection and promotion gating are specified separately by the later cross-document claims feature.
- Existing duplicate/link rulings, search corrections, and transcript corrections remain valid in their distinct current roles and may be referenced by the new ledger without being reinterpreted.

## Scope Boundaries

- This feature covers the shared authority, audience, ruling, selected-note, freshness, and provenance model required by issues #518 and #516.
- This feature does not build the general adjudication queue, duplicate-merge workflow, promotion command, cross-document semantic claims checker, or resumable multi-endpoint scheduler grouped in issues #547–#549.
- This feature does not permit direct hand-editing of generated state documents as a persistent correction mechanism.
