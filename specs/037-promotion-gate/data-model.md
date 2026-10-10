# Data Model: Promotion and Cross-Document Checks

All new persisted records use strict version 1 JSON models (unknown keys rejected), canonical SHA-256 identities, opaque IDs, UTC times, and campaign-relative normalized paths. Existing shared ReviewItem/DecisionEvent formats and authority ledger v2 remain unchanged. No sidecar becomes a competing source of campaign facts.

## BundleSelection

Fields: campaign ID; explicit range `{since, until, out_root}`; four `{document_id, path, sha256}` members; timeline entry; complete nested reference membership; retained reading-contract records; source dependency manifest; audience; review ID; rule versions.

Exactly one of each `world_state`, `campaign_state`, `party`, `planning` is required. Paths derive from the actual range schema; mixed ranges and incomplete synthesis outputs refuse. Selection digest includes supporting files and path-record bytes, not only prose. Missing versus empty is explicit. Filesystem enumeration is sorted; duplicate/case-colliding destinations and symlink inputs refuse.

## SourceSelection and ClaimAnnotation

SourceSelection fields: bundle digest; explicit source entries (stable source ID, path, full hash, excerpt/context hashes, occurrence locator, source kind, authority references); effective horizon; intended claim audience; explicitly selected chunks; selection digest. Discovery produces suggestions; GM confirmation materializes selection before spending tokens. Empty chunks cannot imply all.

ClaimAnnotation fields:

- Stable occurrence ID and revision; document/source role; exact original span and context; source ID/path/anchor/byte span/full hash.
- Proposed subject reference, predicate, normalized scalar/relation, certainty, effective interval, audience and authority record references. Unknown values stay null; arbitrary invented registry identities refuse.
- Origin `structured_source`, `human_candidate`, or `model_candidate`; extraction run/prompt/model/input identity when applicable.
- Review item ID/digest and current mapping-confirmation event if interpreted from prose.
- Explicitly reviewed supersession or ordering relation where present; never derived from file date alone.

Interpretation states: `candidate → mapping_confirmed | rejected | discuss`; source/scope/rule change produces a new revision with the old approval stale. Confirmation means “this span says this,” not “the campaign fact is true.” An authority conflict still needs #546 adjudication. Pure structured fields from a valid active authority record retain that record's identity instead of creating another authority fact.

Predicates are a versioned registry for actor assignment, faction affiliation/posture, identity, certainty, obligation status/amount, location/status and temporal order. Mapping proposal fields and explanations are presented together. An unsupported predicate/value is reviewable as prose but ineligible for mechanical comparison; do not silently coerce it.

## CandidateRun

Fields: operation/run ID; selection and packet digests; model/backend/prompt/rule identity; explicit selected chunk IDs; per-chunk outcome; candidate annotation/finding IDs; costs/usage when available; created/completed time; failure details.

Outcomes: pending, completed, failed, invalid_output. Cached outputs are reused only for identical input and extraction settings; --force overwrites a selected extraction output as an explicit new run revision, never grants approval. Any failed/unchecked selected chunk prevents a “completed selected extraction” result. Partial results remain inspectable but cannot be reported as full coverage.

## ClaimFinding and CheckReport

Finding fields: stable finding ID/revision; one or more of six issue categories; both compared annotation/source references or an explicit missing counterpart; rule ID/version; scope/audience; `mechanical | semantic_candidate | gm_confirmed` basis; severity; exact evidence, rationale and next action; required disposition; current decision binding; semantic digest.

Mechanical comparisons require approved/structured meanings, compatible scopes, exact reviewed subject identity and applicable authority. Unknown/incomparable values produce coverage/candidate diagnostics, not a fabricated contradiction. A mechanical contradiction/supersession cannot omit either assertion.

CheckReport fields: report digest; bundle/source-selection identities; sorted annotations/findings; per-rule outcomes; checked source scope/horizon; required extraction completion if selected; coverage limitations; relevant review events/authority revisions; artifact paths; `complete | blocked | incomplete` outcome. JSON and Markdown render the same report. Wall-clock display times are outside the deterministic findings digest. Store under the range's `state/promotion/checks/<report-id>/`. Reports, candidate runs, retained evidence excerpts and review artifacts are GM-private (owner-only storage, existing authorized private review access); they are never promoted as reference/bundle content. A party-facing summary may show only a redacted diagnostic/allowed locator, never GM-only excerpts.

Mapping review and finding review are separate typed actions. Final gate checks their current events; it does not infer approval from report presence. Coverage may be incomplete semantically while all declared checks have completed, but this must be explicitly visible at document sign-off. Failed declared checks or missing required sources are blocking.

### Digest dependency order (no review cycle)

`source_selection_digest → mapping_set_digest → analysis_digest → resolution_digest → signoff_context_digest → preview_digest`.

- `mapping_set_digest` includes only accepted mapping events and exact annotation payloads, not finding decisions.
- `analysis_digest` binds selected inputs/rules/mappings and resulting findings/coverage, excluding finding dispositions and all document sign-offs. Finding review items bind this digest and their own payloads.
- `resolution_digest` binds analysis plus current finding dispositions; it excludes all whole-document sign-off events. `report_id` identifies this evaluated resolution report; its analysis identity remains separately available.
- `signoff_context_digest` binds resolution plus the exact per-document/support/evidence context; all four sign-off items bind that context before their decisions exist.
- `preview_digest` includes those sign-off events and actual destination state. Final gate result may include them without modifying the report or sign-off input digests.

Refresh of a report after resolving findings changes resolution context as needed and requires renewed affected sign-offs. Merely saving the four sign-off events does not produce a new report identity. This order must be exercised by an end-to-end sign-off/preview test.

## ReviewBinding and DocumentSignoffContext

Reuse campaign/review/item IDs, exact item revision/review digest, decision event and revision, reviewer, disposition and accepted authority record ID. For bundle sign-off rule v2, the item binds full document bytes; the relevant required reference/timeline bytes; retained path/run records; applicable cited source excerpts/context and authority/identity/audience/rule bindings; current report/coverage context.

Whole-source custody hashes also bind checking/publication; changing unrelated source bytes requires explicit custody refresh and a current check, but can preserve approval only when the existing semantic continuity rules prove the reviewed context unchanged. If exact dependency locality cannot be proved, conservatively require renewed review. Current generation edits do not stale source sign-off.

Old v1 document approvals remain immutable history. They cannot authorize the expanded bundle gate until new v2 review items are reviewed. No silent mutation of old events. Newly added relevant unresolved findings block publication even if document text is unchanged.

## PromotionPreview

Fields: bundle digest, report identity, review bindings, applicable authority/rules; expected active generation and activation ID (or explicit absent); exact actual live membership/hash/type map including compatibility links/config; proposed after map; additions/replacements/removals; text/binary differences; pointer/outline/freshness/completeness/claim/review results; `eligible`; refusal codes; canonical preview digest.

Digest excludes current time and presentation-only formatting. Destination-only drift produces a new preview. Source/check/review differences require refreshed eligibility. Preview is stdout data, never an implicitly persisted proposal. Callers may explicitly save the output externally, but the dry-run engine writes nothing.

## GenerationManifest

Fields: generation ID, operation ID, campaign/range; original publication member/path/hash map; paths to immutable `published/` and editable `live/`; retained run/path-record mapping keyed by (member path, embedded locator, anchor), with original resolution base, metadata-copy path and hash; source dependency manifest; bundle/report/rule identities; previous activation reference; kind `published | legacy_adoption`; created time and manifest digest.

Original membership is historical truth about publication, not an assertion that editable live bytes remain equal forever. Snapshot reads return an additional actual live-tree digest and drift status. Required members cannot disappear without an explicit integrity error. Publication manifest/receipt and published bytes never change when a GM edits live prose.

## PromotionIntent, ActivationRecord and Receipt

Intent fields: operation/request ID; preview digest; expected pointer/activation/live hashes; proposed generation/manifest/receipt-candidate digests; previous exact snapshot path/digest or absent; creator; prepared time; expected allowed state transitions.

Receipt candidate fields: exact source/destination identities, prior snapshot, changed paths, review provenance, all gate outcomes, findings/resolutions, prepared time. It is sealed before activation and does not claim a completion time.

ActivationRecord fields: operation and new generation IDs; manifest and receipt-candidate digests; parent activation ID/digest or null; previous observed pointer/snapshot digest; actor; `completed_at` when the transition and its synchronization are durably reconciled; optional `recovered_at`; observed activation interval when the exact swap time was lost. Records are immutable under `docs/grounding/activations/<activation-id>.json`. A discriminated `legacy_baseline` variant binds the adopted generation manifest and migration receipt digest, with no publication-candidate digest; migration creates/synchronizes it before clearing pending. A pristine absent baseline has no activation parent. The first real publication may name the validated legacy_baseline as parent. A later promotion cannot begin until its current parent's activation is reconciled and verified. Status joins candidate plus ActivationRecord into the completed machine-readable receipt.

Attempt states: `prepared → staged → activation_pending → committed`; precommit failure → `aborted`; interruption/durability ambiguity → `commit_unknown → committed | aborted | intervention_required`. The current pointer/validated generation determines reconciliation, never an orphan receipt alone. A committed historical receipt returns as history when a newer valid activation exists; replay never changes current.

Unknown post-swap outcomes are not labeled failed rollback. Receipt preparation failure before activation leaves the old pointer intact. Missing post-swap metadata is recoverable from durable intent + pointer + receipt candidate; subsequent mutations refuse until reconciled.

## LayoutMigration

Fields: version; explicit campaign ID; source loose path inventory/config hash; proven generated reference membership; adoption completeness; planned aliases/new paths; exact before/after map; plan digest; phases; backup snapshots; receipt. Initialized pristine campaigns use an explicit `absent` baseline only when no managed outputs exist.

States: preview (unpersisted), prepared, copying, switching, verified, committed, recovery_required. Any partial migration sets a durable pending marker visible to all supported readers. Apply requires the exact preview digest. Unexpected bytes stop recovery without overwriting; no automatic fallback to retired loose paths.
