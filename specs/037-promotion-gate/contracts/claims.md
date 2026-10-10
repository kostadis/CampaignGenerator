# Claim Checking and Review Contract

## Stages and authority

1. **Select:** Generate a proposed source manifest from the four exact drafts, their citations/dependencies, relevant configured authority and explicitly chosen later sources/horizon. GM confirms the materialized manifest. Missing sources/ambiguous identity are visible; no empty-means-all behavior.
2. **Extract or import:** An explicit optional model operation proposes interpretations and semantic findings from bounded selected packets. Manual import uses the same strict format. Verify exact excerpts/locators and output schema after each chunk; failures remain failed, not an empty successful result. No model is invoked by promotion or checking.
3. **Review mappings:** Display exact source text and proposed subject, predicate, value, certainty, temporal/audience scope together. GM confirms the interpretation, rejects it or discusses it. Confirmation creates an audit-only shared decision; it does not declare that a source assertion is canon. Unsupported/unconfirmed fields are not mechanical truth.
4. **Check:** Compare accepted explicit structured representations and existing applicable authority using deterministic rules. Emit JSON and Markdown plus semantic candidates where appropriate. Preserve source authority disputes for the GM; do not rank contradictory summaries by time alone.
5. **Review findings:** Use the same private review surface with typed proposed dispositions. Corrections route to #546; publication never edits source or draft prose to make checks pass.
6. **Sign off and promote:** All four whole-document sign-offs bind the current relevant evidence and report/coverage context. The promotion gate verifies these events and recomputes the deterministic report identity/results under current input bindings.

## Source selection

Selection explicitly lists every source path/hash, document occurrence, effective horizon and authority record/revision. Match entity/thread identities through current reviewed registry entries and aliases; ambiguous names require selection, never fuzzy authoritative identity. Citation-linked source spans and their relevant context form candidate packets. The UI can suggest additional latest mentions from explicit identity/authority links; it must show and materialize the set before extraction. Configured notes are included with their CANON/TABLE/PREP/OVERLAY/OPEN classification and audience; a proposed note is never promoted to factual source automatically.

Changes in selected source membership, authority, audience, horizon or rules stale the check. Corpus freshness uses the existing run manifests plus the selected later-source manifest. A required missing source blocks; an out-of-scope or unsupported semantic dimension is a disclosed coverage limitation. Declaring a limitation cannot suppress a specific unresolved finding already discovered in the selected inputs.

Mandatory source closure cannot be deselected: include all four drafts and support/run records, all corpus-manifest dependencies used to build them, explicit citation targets, applicable configured high-authority records/notes for the selected projections/horizon, and any explicit superseding/later-source links from that set. Inventory maintained summary chapter identities so known later linked sources cannot disappear merely because a user omitted them. Ambiguous additional relevance requires a recorded GM scope choice; no implicit source winner or arbitrary omission. Changing the closure invalidates the selection/report.

Model chunk selection controls optional assistance, not source membership or integrity checks. Without an extractor, the GM may supply reviewed mappings manually; unnormalized prose dimensions remain explicitly outside mechanical coverage and must be acknowledged in whole-document sign-off. A failed selected extraction or a specific discovered unresolved candidate always blocks and cannot be renamed a coverage limit. Never report complete semantic verification for the no-model/no-mapping path.

All reports, candidate packets/runs, source excerpts and review artifacts are GM-private and stored owner-only. They are not generated reference members and must never be copied by promotion. Existing private capability authorization protects their presentation. Party-facing diagnostics redact GM-only text and restricted locators; they may state that a restricted authority conflict requires GM review. Tests must check both report access and publication membership against an embedded GM-only marker.

## Deterministic rule families

| Category | Sufficient reviewed structure for mechanical finding | Otherwise |
|---|---|---|
| Direct contradiction | Same subject/predicate with incompatible accepted values and overlapping effective/applicable scope, with reviewed applicability metadata; code may establish incompatibility even when no authority winner is known | Candidate; show both statements and ask for judgment |
| Stale claim superseded | Explicit supersedes relation or applied ruling invalidating the bound assertion within this scope | Candidate; later date is not enough |
| Suspicion stated as fact | GM-approved mapping of source certainty and asserted certainty for the same claim, with applicable authoritative context | Semantic candidate; no keyword verdict |
| GM-only truth in party knowledge | Explicit reviewed source audience and a reviewed claim that asserts party/character knowledge without that grant | Candidate if knowledge or audience is inferred; GM-only report display is not itself a leak |
| Resolved still active | Explicit applicable thread/obligation status and reviewed draft status mapping for that subject/time | Candidate if status/temporal scope requires inference |
| Incompatible ownership/debt/location/status | Reviewed typed values, matching subject/property and comparable scope; authoritative conflict policy known | Candidate when comparability or authority is uncertain |

The five real examples currently enter the right-hand column. After GM confirmation of exact normalized spans, code can check a narrow structured comparison; reports must identify that human-supplied prerequisite. No result claims generalized semantic certification.

`planning` uses #546's applicable planning precedence without applying future PREP/OVERLAY as past factual truth. Equal-authority incompatible reviewed assertions produce a mechanical conflict with no chosen winner and block until adjudicated. Detection does not imply choosing which assertion is true. OPEN remains uncertainty. No new implicit recency, confidence-score threshold or model-consensus winner is introduced.

## Disposition mapping without a new decision store

Use existing `grounding_documents` review kind / `grounding_document` domain. New typed actions live in strict validated `proposed_action.details`, with stable rule IDs and payload hashes. Existing ReviewItem/Event storage shapes stay version 1; authority stays version 2.

| Item/action | Existing verdict/disposition | Gate meaning |
|---|---|---|
| Confirm exact proposed claim interpretation | Approve / accept_no_change | Mapping usable; source truth/precedence still separate |
| Dismiss semantic candidate with displayed evidence | Approve / accept_no_change | Candidate nonblocking while that exact proposed dismissal remains valid |
| Accept explicitly displayed nonblocking uncertainty | Approve / accept_no_change | Uncertainty remains in report/receipt; no new fact asserted |
| Candidate is incorrect and requires correction | Reject / reject_action | Blocking; prepare a source correction through #546 |
| Exact prepared source correction | Approve / source_correction | Authorizes that source proposal only; still blocks promotion until applied, regenerated and re-reviewed |
| Discuss or pending | Discuss / defer, or no event | Blocking for required mappings/findings |
| Whole-document approval, rule v2 | Approve / document_signoff | Counts only for the corresponding exact document and bound context |

Local preparation can offer bounded dismissal/uncertainty alternatives with exact payload digests; the phone chooses only displayed prepared alternatives. Custom normalization or a changed rationale returns to local preparation and creates a new item revision. Notes alone cannot change disposition. Mechanical integrity errors cannot offer a dismissal alternative.

Validate action/disposition compatibility at all save boundaries, including the private capability POST path. Do not accept a generic `document_signoff` event on a mapping/finding item, or `accept_no_change` on a required whole-document sign-off item. Bind authority history to exact shared decisions as #547 does. These constraints also cover imported review bundles.

## Reports, coverage and blocking

A final CheckReport includes the complete selected four-document scope, source manifest, normalized mappings with basis, all six category counts, each finding's paired locations/provenance, per-rule outcomes, incomplete work, current resolutions and coverage limitations. Mechanical findings require both assertions. Missing counterpart evidence becomes an incomplete/candidate diagnostic and cannot be mislabeled as mechanically proven.

- Mechanical integrity or established contradiction, confirmed false draft, unresolved required candidate, stale review, failed declared check, missing required evidence: **block**.
- Current evidence-backed dismissal or GM-approved uncertainty: nonblocking with recorded rationale and events.
- Declared unsupported semantic coverage without a specific unresolved candidate: informational, visible at all four sign-offs.
- Zero candidates or a model's “no issues” output: not proof of correctness; four current human sign-offs remain required.

Adding a new relevant candidate after sign-off blocks promotion until disposition and updated sign-off context are reviewed. Digests follow the acyclic order in data-model.md: analysis binds sources/mappings/findings/coverage; resolution adds finding decisions; sign-off context binds that resolution; preview adds whole-document sign-off events. A report never includes the sign-off events that approve it in its own identity. Outside those deliberate dependency boundaries, digests exclude only presentation/time data, never source scope, model-run completion or applicable rule revisions. Changes to unrelated authority history do not invalidate relevant decisions, but ledger integrity is still checked.

## Reconstructed acceptance evidence

Create `tests/fixtures/summary_native/promotion/phandalin_shapes/` with one bad and one nonbad case per example. Each fixture provenance record labels:

- `reconstruction: true`, originating issue and spike case;
- original source locator and revision/hash from the read-only spike;
- which assertions are surviving source excerpts versus reconstructed draft text;
- explicitly synthetic GM mapping/ruling data used to test deterministic rules;
- expected candidate category, evidence, decision path and final gate outcome.

Do not check in unrelated campaign content, full private notes or capability tokens. Use minimal relevant excerpts and clearly fictional/synthetic replacements where private plot details are not needed. Validate the resulting mechanics on copies, never mutate Phandalin. Positive controls preserve uncertainty, correct party/allegiance, rejected debt and proper ordering. Include a newer incorrect summary as a negative control against “latest wins.”
