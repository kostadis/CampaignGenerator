# Verification Queue and Rerun Contract

## Lossless taxonomy adapter

Each finding retains `legacy_code`, exact sentence/span, source path and locator, original rationale, category candidates, severity, basis and proposed action. A check failure without a sentence uses explicit failure context. Multiple categories are allowed; no finding is lost because a legacy diagnostic fits imperfectly.

| Existing/new observation | Category | Basis and consequence |
|---|---|---|
| invalid citation, uncited bullet, invalid manual pointer | missing_source_or_pointer | Mechanical blocking defect; includes original code |
| outside-evidence, citation-mismatch | missing_source_or_pointer plus support candidate when warranted | Mechanical evidence membership/pointer failure; not semantic adjudication |
| quote not-found | unsupported_or_contradicted candidate | Exact-match failure is mechanical blocking for claimed-verbatim; meaning remains unassessed |
| manual-dropped | unsupported_or_contradicted candidate | Mechanical missing authored requirement; never silently discard the original manual-dropped code |
| typography-normalised | typography_presentation | Mechanical advisory unless the declared exactness contract makes it blocking |
| placeholder-speaker | typography_presentation plus attribution judgment | Advisory; missing attribution cannot be guessed or silently fixed |
| status word, number or ordinal absent from cited evidence | citation_non_entailment candidate | Advisory only; GM judges meaning and attribution |
| explicit reviewed metadata supersedes cited fact | later_source_supersedes | Mechanical observation of encoded supersession; implied temporal semantics need GM |
| explicit audience grants exclude requested target | knowledge_leak | Mechanical blocking; inferred character/player knowledge needs GM |
| timeout, unavailable service, malformed/incomplete verifier response | verifier_transport_protocol | Operational failure; no item is passed as a side effect |
| GM assertion of contradiction/non-entailment/supersession/knowledge leak | corresponding category | GM-confirmed, attributable, evidence-bound |

Stable machine category identifiers correspond to all seven names in FR-009. Rule-policy version is bound to the review digest. The adapter must not relabel uncertainty as a confirmed semantic violation. Preserve existing PASS/FAIL compatibility as mechanical results and expose a separate semantic-review status.

## Finding entry and corrections

`review finding add REVIEW --finding FILE --expected-generation N` provides the GM/agent-chat interchange for semantic findings that deterministic code cannot discover; the UI exposes the same typed form. It records an attributable candidate, not approval. Fields include exact claim occurrence, evidence, category, rationale and proposed action. Bulk import uses the same validation and explicit selection. No mandatory model pass is added.

A source correction must carry an explicit #546 ruling/staged source proposal before it can be approved as a correction. A generated dossier error with a correct summary must not “fix” that summary: record the rejected claim and evidence, retain the review decision, and regenerate the affected draft through existing authored/draft workflows. If an authored dossier correction is needed, its exact change is separately previewed under the identity/draft adapter, with source truth unchanged. Never insert invented summary content to satisfy a failed generated claim.

## Selection semantics

Initial review creation verifies only the literal selected dossier set and includes every finding in that scope. It must not inherit `_npc_verify`'s current no-name-means-all behavior for this new workflow. The existing command may retain legacy behavior outside the new review path, but every UI launch materializes selection.

Unresolved preview filters explicitly selected current items to rejected/discussed/mechanically failed status, and refuses ineligible approved entries rather than broadening or silently dropping selection. Pending/stale items use `mode=selected`. The returned selection digest binds item revisions, check IDs and dependencies. Execute selected checking functions only; shared source loading is permitted, running unrelated checks and hiding their output is not. A stale semantic decision requires human reassessment, not automatic approval from a mechanical rerun.

Refactor whole-dossier verification into reusable scoped checks while preserving the existing public `verify` aggregator and diagnostic compatibility. A checker may need a whole dossier to establish context, but must report precisely which selected checks ran. A structural change that prevents locating an item marks it stale; an ambiguous match never inherits a decision. Report progress per member and retain partial failure/unprocessed state.

## Publication gates

A current approved no-change semantic disposition may settle a GM judgment question. Broken pointers, invalid source identities, explicit audience violations, missing required authored edits and violated exactness claims remain blocking until repaired and rechecked. Human review does not change a failed mechanical report to a pass. New draft output requires document sign-off for its exact bytes; resolving findings is insufficient. Related whole-document approval is invalidated by any document byte change, even when unaffected per-item approvals can survive.

## Review continuity versus mutation binding

`review refresh` is a deterministic, audited custody rebind. Semantic item revisions hash only the named exact claim/span/context/dependency/disposition payload; source-manifest generations separately hash complete containing files. Refresh can preserve a semantic item revision/decision while recording new full-file custody hashes only after proving the bound semantic payload unchanged. Ambiguity stales instead. Apply proposals bind current full hashes and custody generation; refresh never transfers source-mutation approval to a new proposal. Tests must change an unrelated paragraph in the same evidence file as well as an unrelated dossier.
