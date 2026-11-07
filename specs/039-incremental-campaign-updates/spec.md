# Feature Specification: Incremental Campaign Grounding and NPC Updates

**Feature Branch**: not created (no branch yet; spec-only)

**Created**: 2026-11-05

**Status**: Draft; specification only, no implementation or new commands shipped

**Code baseline**: `887a5c17aa3b34ff43d4e83c6ed7f8e40b29aa72`

**Input**: User description: "Describe the gaps in CampaignGenerator's incremental grounding-document and NPC processes, using the completed Out of the Abyss Chapter 75 workflow as evidence." (Rough draft preserved at `draft-input.md` in this directory and used as the primary input.)

**Related work**: [#588](https://github.com/kostadis/CampaignGenerator/issues/588) (grounding delta), [#587](https://github.com/kostadis/CampaignGenerator/issues/587) (changed-NPC delta), [#585](https://github.com/kostadis/CampaignGenerator/issues/585) (unchanged attestation). [#512](https://github.com/kostadis/CampaignGenerator/issues/512) is closed and supplies existing cache/carry behavior; it does not deliver this workflow.

## Problem and Intended Outcome

After reviewing a new session, the GM should be able to update the four grounding documents and the materially affected NPC dossiers from the last reviewed publications plus that session. Established history should survive unchanged. The update should pass the existing authority, verification, review and publication gates without a historical rebuild, campaign-specific scripts, or an exception that allows direct live edits.

CampaignGenerator already has many of the necessary components. What it lacks is a supported end-to-end operation that binds an actual published baseline, selects only new sources, generates minimal changes, preserves inherited evidence, and carries that exact lineage through review and publication. A one-chapter synthesis is not a merge into an existing baseline. Cached full-range extraction is useful but does not establish bounded source reads or preserve reviewed prose.

This specification defines the missing contracts. It does not replace the existing promotion, NPC publication or review systems. Interface names below describe operations, not installed CLI syntax.

## Context and Evidence: The Chapter 75 Workflow

The completed November 2 Chapter 75 update is the evidence base. The reviewed summary has SHA-256 `ca597853064830cbd9596fe70616d8ab4e338b308b46deea9af07860e8a497d5`. The campaign artifacts listed in the References appendix retain the actual decisions and receipts.

| Area | What the completed workflow established | Glue the operator supplied |
|---|---|---|
| Sources | The exact reviewed summary, rather than the older imported export; a selected-only flat publication reused by both updates | Located a separate batch worktree, checked the summary digest, and ran repository publication functions in a one-chapter scratch root |
| NPCs | Ten existing dossiers updated and three new dossiers published; thirteen native verifier passes; 96 unselected publications unchanged | Publication-specific baseline inventory, cached-evidence merge, contextual links, sparse verification context, native review construction and explicit selected publication |
| Grounding | Four documents advanced from the approved Chapters 2–74 live baseline using Chapter 75 only; one stale item-selection statement repaired and rechecked | Numbered baseline lines, model replacement proposals, host reconstruction, preservation checks, consistency and custom review/application records |
| Publication | NPCs used native sign-off and publication; grounding used a separately approved guarded editable-live correction | The grounding run could not produce a native baseline-plus-delta generation. It retained origins/backups and left the native Chapter 72 generation, timeline, references and historical receipts unchanged |
| Review and delivery | Four draft approvals followed by a separate application approval; review servers stopped after saved decisions were validated | The first artifact was explicitly draft-only, so another approval was necessary. Runtime capability URLs had to be removed from shipment metadata without changing signed records |

The grounding baseline was not merely the Chapter 72 immutable publication: it also included approved live updates for Chapters 73–74. NPC baselines likewise differed by subject: most selected dossiers ended at Chapter 74, while Dawnbringer's actual published baseline ended at Chapter 73. A range directory name alone could not establish either baseline.

**Read-bound terminology:** "no historical rescan" means no historical summary parsing, extraction, model input or redrafting. Hashing an exact historical custody dependency can still read its bytes. The product must report those integrity reads separately rather than claiming that no historical file was opened at all.

### Existing Capabilities That Must Be Preserved

- Range-based corpus building, content-addressed extraction reuse across ranges, and carry-forward of eligible NPC dossiers absent from newly checked notes. These are existing behavior, including the delivered portion of #512.
- NPC prompt-key skips, model-stage run records, dispatch and compatible draft resume. An identical prompt-key skip is not an attestation that later chapters leave a published dossier unchanged.
- Deterministic NPC verification and composition; exact-draft GM sign-off; explicit selected publication; overwrite guards and authority writer locking. NPC publication is currently independent per member, not an atomic multi-NPC batch.
- Native authority and shared review records, freshness checks, proposal application, identity review and recovery. A citation resolving is not proof that its prose meaning is true.
- Managed grounding migration, claims selection/checking, four exact document sign-offs, digest-bound promotion previews, whole-generation activation, historical receipts and recovery.
- Structural separation of authored NPC manual material from Secrets: safe draft/manual inputs can reach a model; composed GM Secrets must not be used as convenient drafting input.

The feature extends those systems to understand delta lineage. It must not fabricate a full-corpus receipt, a successful verifier result, a native sign-off, or a complete historical coverage claim to make existing gates accept a sparse update.

## User Scenarios & Testing *(mandatory)*

Priorities: P1 covers core correctness; P2 covers operator workflow. CLI and application parity is mandatory in the same delivered feature regardless of phase priority.

### User Story 1 - Update the Four Documents From One Reviewed Session (Priority: P1)

The GM selects one newly reviewed session chapter and produces four complete candidate grounding documents, plus a native complete-bundle preview, from the adopted Chapters 2–74 baseline. Historical summaries are not parsed.

**Why this priority**: The four documents are what session prep navigates by. Without a delta path, every update is either a full rebuild or a manual local correction outside the native gates.

**Independent Test**: Begin with a valid or adopted Chapters 2–74 baseline and select only Chapter 75. Produce four complete candidates and a native complete-bundle preview without parsing historical summaries.

**Acceptance Scenarios**:

1. **Given** current-state text saying faction answers and Davra's meeting are pending, **When** the delta is checked, **Then** all conflicting current assertions are revised and the earlier negotiation history survives.
2. **Given** the completed forge restart and spent dust, **When** the update is generated, **Then** current inventory and objectives reflect completion without inferring a new rest, attunement or unrecorded delivery.
3. **Given** an inherited old citation or reference, **When** the delta is checked or promoted, **Then** its retained lineage resolves it without a fabricated one-chapter full-corpus manifest.
4. **Given** reviewed live patches and an unreviewed live hunk, **When** baseline adoption is proposed, **Then** the reviewed patches retain their true local lineage and the unreviewed hunk requires explicit disposition before use.
5. **Given** a baseline with gaps, **When** Chapter 75 is applied, **Then** coverage remains that baseline plus the selected chapter, not a claim of complete history through 75.
6. **Given** live prose through 74 but supporting timeline and references through 72, **When** the baseline is adopted, **Then** per-member gaps remain explicit. The delta cannot label those supporting members complete through 74 or 75; any required repair uses separately selected, authorized sources or refuses with the precise missing dependency.
7. **Given** unchanged candidate prose but a changed relevant old source, retained excerpt or reference digest, **When** inherited custody is checked, **Then** affected reuse and sign-offs become stale or require focused repair. Hash reads are disclosed and do not silently become historical parsing, extraction or model input.

---

### User Story 2 - Update Only the Affected NPCs (Priority: P1)

The GM updates only the NPC dossiers that the new chapter materially affects, adds bounded new dossiers for newly established NPCs, and records explicit unchanged attestations for passing mentions. Everything else stays byte-identical.

**Why this priority**: NPC dossiers are the per-person reference. Rebuilding all of them for one chapter is wasteful, and silently skipping one is worse.

**Independent Test**: Use mixed Chapter 73/74 published baselines, one new chapter, a material change, a passing mention and a new NPC.

**Acceptance Scenarios**:

1. **Given** a changed NPC, **When** its update is generated, **Then** its old history and quotes remain byte-identical and it gains supported new history and current state. **And** a new NPC receives a bounded new dossier.
2. **Given** an unpublished newer draft, **When** baselines are selected, **Then** the draft is ignored as a baseline. **And** broken publication-to-draft lineage refuses that subject with an actionable reason.
3. **Given** a scene-only named NPC with no NPC heading, **When** the census runs, **Then** it receives bounded evidence through an approved identity or context path, or an explicit unresolved or excluded outcome. It cannot silently vanish as a registry-only finding. **And** an indirect title, pronoun or collective association requires scoped review and does not imply physical presence or deployment.
4. **Given** an approved unchanged attestation, **When** a later horizon is built, **Then** the old publication remains byte-identical. **And** an explicitly unselected subject is not reported as reviewed through the new chapter.
5. **Given** independent evidence changes for NPC B, **When** freshness is checked, **Then** B is stale and A is not. **And** if their shared source changes, both are stale. Changing the new draft requires a new exact-draft sign-off.
6. **Given** a missing cached scene, an absent entry or moment span, a corrupt cache, or an attempted sparse-as-full substitution, **When** the candidate is generated, **Then** the affected candidate is blocked. Real native verification runs, and a caller-supplied PASS is rejected.
7. **Given** an exact historically approved publication, **When** unrelated group drift occurs, **Then** the publication remains usable baseline provenance. **And** the changed whole candidate still requires its own current approval.

---

### User Story 3 - Review and Apply the Exact Intended Update (Priority: P1)

The GM reviews the concrete candidates and the publication effect, through the CLI or the application, and any change to a bound input before application invalidates the affected approval.

**Why this priority**: Approval is only meaningful if it binds to exactly what will be written.

**Independent Test**: Review the concrete candidates and publication effect through CLI and application, then change one bound input before application.

**Acceptance Scenarios**:

1. **Given** a candidate update, **When** it is presented for review, **Then** diffs for existing prose, full prose for new dossiers, evidence, exact hashes, coverage and inherited findings are shown. All four complete grounding candidates remain inspectable.
2. **Given** a review handoff, **When** the GM decides, **Then** draft approval, unchanged attestation, scoped association approval and publication authorization are recorded with distinct meanings. They may be collected in one concrete review handoff, and a second permission round is not forced merely because the application effect was omitted from the first page.
3. **Given** a Discuss, unmarked, unsaved or stale decision, **When** the affected action is attempted, **Then** the action is blocked. Elapsed time and a model's consistency verdict do not grant approval.
4. **Given** a changed baseline, selected source, output, applicable authority or publication destination, **When** the change is detected, **Then** the relevant check, sign-off or preview is invalidated. Prior historical approvals remain in the record.
5. **Given** an unchanged relevant approval, **When** the update is re-run, **Then** it is reused without another question. **And** changed findings trigger a targeted repair and recheck, not a historical regeneration.

---

### User Story 4 - Resume and Publish With Honest Outcomes (Priority: P1)

The operator can interrupt a run at any boundary (evidence generation, model output, verification, review creation, sign-off, first publication, receipt creation) and resume it without duplicate approvals, duplicate publications, or misreported results.

**Why this priority**: The NPC publication path writes many independent files, and a grounding activation writes a whole generation. Each has a different failure mode, and the outcome must be honest in both.

**Independent Test**: Interrupt at each durable boundary listed above, then resume.

**Acceptance Scenarios**:

1. **Given** a completed compatible stage, **When** the run resumes, **Then** it is reused by digest. **And** failed or incomplete output is never mistaken for a prior successful draft. No duplicate approvals or logical publications occur.
2. **Given** a grounding update, **When** failure occurs before activation, **Then** the prior generation remains usable. **And** an ambiguous activation is inspected and recovered by operation identity, using the existing complete-generation transaction and consistent-reader behavior.
3. **Given** NPC publication, **When** it runs, **Then** it declares independent-member semantics. Every selected member has a durable outcome. **And** a crash between target write, log update and completion receipt can be reconciled safely. A lock or a sequence of replacements is not described as an atomic batch.
4. **Given** held or rejected NPCs, **When** publication completes, **Then** they keep their old publications. Publication is blocked where a required dependency is held. A mixed result is reported as PARTIAL, not COMPLETE. Repeating a completed intent produces a no-op or its recorded receipt.
5. **Given** NPC publication that precedes a grounding update, **When** the grounding plan is checked, **Then** it binds the exact resulting dossiers. A changed or missing required dossier blocks dependent grounding checks. No cross-subsystem atomic transaction is implied.
6. **Given** a run with a batch size, **When** work is materialized, **Then** the batches are derived from the plan before dispatch. Changing batch size does not change the selected subjects or their semantic outcomes. Compatible skipped work makes zero model calls. Resume reuses the existing dispatcher rather than a second scheduling engine.

---

### User Story 5 - Use the Workflow Without Local Glue (Priority: P2)

The operator runs the same selected update through the CLI or the application from a supported worktree, restarts the review server, and inspects durable status without writing campaign-specific scripts.

**Why this priority**: The Chapter 75 run needed manual worktree handoffs, separate scope explanations and cleanup of serving and shipment metadata. That glue is what makes the workflow fragile to repeat.

**Independent Test**: Run the same selected update through both surfaces, restart the review server, and inspect durable status.

**Acceptance Scenarios**:

1. **Given** the same update, **When** it is run through either surface, **Then** both use the same plan, service contracts, gate results and receipts. Source selection, model settings and the stopping point persist across phases.
2. **Given** a deliberate, verified artifact transfer or worktree binding, **When** the update runs there, **Then** canonical campaign identity is preserved. No edit to campaign identity metadata and no disabled moved-campaign guard is required.
3. **Given** the review hosting is restarted, **When** the GM returns, **Then** saved decisions are intact. Capability URLs are runtime metadata; durable receipts remain useful without shipping access tokens.
4. **Given** a finished run, **When** the final report is read, **Then** it identifies changed, new, unchanged, deferred and unresolved members; sources parsed versus custody inputs hashed; model calls; checks; decisions; and actual publication state.

### Edge Cases

- Nonconsecutive selected chapters.
- Multi-session chapter suffixes.
- A deliberately incomplete baseline.
- A selected source revised after review.
- An earlier-chapter correction, supplied as a separately explicit scope.
- A missing baseline cache.
- A later-horizon dossier requested for an earlier view.
- Generic names, and known-but-unregistered entities.
- Duplicate contextual links; rejected or Discuss decisions.
- Model failure leaving an old successful file behind.
- Disk or permission failure; concurrent publication.
- Local live drift discovered during baseline adoption.

## Requirements *(mandatory)*

Gap inventory (background for the requirements below):

| ID | Priority | Gap in the current product | Required behavior |
|---|---|---|---|
| G1 | P1 | No native four-document baseline-plus-selected-chapters generator | Typed delta plan, exact baseline bindings, minimal evidence-backed edits and host-validated reconstruction |
| G2 | P1 | Ordinary range validation reads the whole directory before filtering; a range flag does not enforce a new-source-only read bound | Explicit selected-file ingestion and observable parse/prompt boundaries, without scratch-root scripts |
| G3 | P1 | Promotion and claims expect full-range corpus, notes and synthesis records; sparse new-chapter input cannot account for inherited citations and members | Native delta lineage and inherited custody/citation resolution accepted by the existing complete-bundle gate |
| G4 | P1 | A managed generation plus approved editable-live patches is not a first-class reviewed delta baseline | Deliberate baseline adoption that distinguishes immutable publication, current live bytes, retained origins and unreviewed drift |
| N1 | P1 | No publication-bound changed/new/unchanged NPC planner or cross-range minimal updater | Per-NPC actual publication baseline, reviewed change census, exact historical reuse and selective generation |
| N2 | P1 | Cached evidence plus new sources has no supported, typed sparse verification/review input | Explicit available targets, source lineage, coverage and audience; real native verification over that context |
| N3 | P1 | Shared-review custody can stale one dossier when an unrelated member changes | Complete per-dossier dependency closure; shared dependencies still invalidate every actual consumer |
| N4 | P1 | Literal linking cannot express the scoped contextual associations needed for indirect references | Reviewable source-bound associations without invented aliases, source rewrites or automatic identity decisions |
| N5 | P1 | Passing mentions lack a native unchanged-through-new-chapters attestation | Evidence-bound GM attestation; original dossier bytes and horizon retained; affected freshness checks |
| C1 | P1 | Model-stage resume and individual native operations do not constitute a recoverable end-to-end delta run | Durable stages, exact selection, member receipts, safe resume, explicit partial outcomes and idempotence |
| C2 | P2 | The bridge requires manual worktree handoffs, separate scope explanations and serving/shipment cleanup | Supported, verified artifact transfer; clear approval and application scope; discoverable run status; portable provenance |

### Functional Requirements

**Workflow and sources**

- **FR-001**: The system MUST provide an explicit incremental mode, distinct from full refresh, taking selected reviewed source revisions, requested products and a stopping point. It MUST NEVER silently fall back to a full scan.
- **FR-002**: The system MUST bind a four-document grounding baseline and each NPC's actual publication baseline by identity, retained lineage and digest. It MUST NOT choose a baseline by newest directory or nominal end range.
- **FR-003**: The system MUST support explicit adoption of a valid legacy or edited-live baseline, showing origins, reviewable drift, audience and coverage limitations. Adoption MUST NOT be hidden inside generation.
- **FR-004**: The system MUST accept an explicit selected-file source set, and MUST record parsed new summaries, parsed historical summaries, reused baseline artifacts, integrity-only dependencies and model-input sources as separate categories.
- **FR-005**: The system MUST record full versus sparse evidence as different types, enumerate the actual available targets, lineage, audience and limitations, and MUST NOT let a sparse candidate masquerade as a complete corpus.

**Grounding edits**

- **FR-006**: Edits MUST use stable, host-owned identifiers with exact before and after bindings, a category, a reason and evidence. The system MUST reject malformed, duplicate, overlapping, stale or unsupported edits, and unjustified empty proposals.
- **FR-007**: The system MUST preserve unrelated baseline bytes, quotations, citations, open promises, GM staging and authored material. Heading structure, table widths and citation targets MUST be checked as well as prose.
- **FR-008**: The system MUST find superseded current assertions across each affected document or dossier, and preserve prior statements as history where appropriate rather than appending contradictory overlays.
- **FR-009**: The system MUST keep testimony versus observation, acceptance versus delivery, plans versus outcomes, and GM versus party knowledge distinct, and MUST NOT infer resources, powers or secret causes.
- **FR-010**: The system MUST expose explicit generation and consistency backend, model and effort selections; retain actual run identity; and fail without silent model or provider substitution.
- **FR-015**: The system MUST run bounded semantic consistency checks on all proposed deltas and cross-document effects. After repair, it MUST check the exact changed spans and report outstanding findings. Semantic limits MUST be disclosed without relabeling failed required checks as limitations.
- **FR-016**: The system MUST carry or update all required grounding bundle members with explicit inheritance and support mappings, and MUST integrate delta source lineage into existing claims selection and checks, exact sign-offs and digest-bound native promotion.

**NPCs**

- **FR-011**: The system MUST produce a complete NPC disposition census and reviewed, scoped-context associations. It MUST NEVER use fuzzy identity merging or invented aliases to increase coverage.
- **FR-012**: The system MUST reuse real native NPC verification, composition, sign-off and selected publication over the supported typed delta context. Authored Secrets remain structurally outside drafting input. Audience compatibility MUST be enforced before cached content is exposed, including fallback, reference and diagnostic paths. Unclassified legacy evidence remains GM-only until explicitly classified or granted under existing authority rules.
- **FR-013**: The system MUST provide unchanged attestations bound to exact publication, new-evidence and ruling identities, with an explicit scope. The original publication bytes and its actual provenance horizon MUST be kept.
- **FR-014**: Freshness MUST bind to the complete relevant dependencies of each item. Shared-dependency changes MUST invalidate every actual consumer. Unrelated review-group members MUST NOT stale each other.

**Approval, state and publication**

- **FR-017**: Draft approval and live-application authority MUST be explicit. The system MUST support a concrete combined review handoff when scope is known, reuse prior valid authorization, and require fresh review only for affected changes.
- **FR-018**: The system MUST persist a versioned run state with exact input and output hashes, materialized bounded work batches, stage results and member outcomes. It MUST reuse the existing dispatch and resume behavior, keep selection and results invariant to batch size, skip compatible work without model calls, and report failures, partial progress and stale state accurately.
- **FR-019**: Grounding MUST reuse native whole-generation atomicity and recovery. NPC publication MUST gain durable per-member reconciliation and idempotence around the existing independent writes. The system MUST NOT claim group atomicity for it.
- **FR-020**: Publication MUST require a fresh preview and preconditions. Source-approval dependencies MUST be separated from expected current destination hashes, and a concurrent destination publication MUST cause a publication conflict.
- **FR-021**: The system MUST preserve immutable generations, signed decisions and historical receipts. It MUST NEVER use test overrides, force, manufactured synthesis records, caller-asserted verification or writes over managed aliases to bypass gates.
- **FR-022**: The system MUST deliver equivalent CLI and application operations in this feature, on the same durable state, and MUST provide supported, verified canonical or worktree artifact transfer that does not rewrite campaign identity.
- **FR-023**: Private hosting capabilities MUST be kept separate from durable evidence. Saved review decisions MUST be persisted and validated; stopping or restarting the server MUST NOT imply approval or lose decisions.
- **FR-024**: The system MUST produce a completion receipt with the selected chapters, inherited coverage and gaps, changed/new/carried/held subjects, exact publication hashes, checks, decisions, read and call counts, and recovery state. Git actions require their own user scope.

**Grounding-specific contract (G1–G4)**

- The baseline MUST bind all four documents, their retained origins, the active generation and its manifest and receipts, and the exact editable-live hashes. Its declared historical coverage is inherited, with known gaps and limitations preserved.
- A newer directory or a mutable live file is not evidence of reviewed lineage. Coverage is recorded per member: live prose through Chapter 74 does not advance the coverage of an inherited Chapter 72 timeline or reference tree. Complete bundle membership and complete historical coverage are different claims.
- Stable paragraph or line identifiers are assigned to the bound baseline. A replacement proposal names its target identifier, proposed text, change category, rationale and exact selected-source support. Host code supplies the before-text, rejects unknown, duplicate or overlapping targets, and preserves all untouched bytes. A model MUST NOT have to reproduce a large old table or document from memory.
- Categories MUST distinguish new information, superseded current state, a resolved thread, a historical event and no material change. Recurring present-tense claims that conflict with new evidence are corrected everywhere; historical accounts are retained as history. Existing annotation behavior still only adds warnings without rewriting prose. Delta replacement is a separate, explicit, reviewed operation.
- A native delta generation MUST carry a complete effective bundle: four documents, timeline, full nested reference tree, reading-contract records and dependency lineage. Unchanged members may be inherited with exact digests. Affected timeline and reference members need bounded deterministic updates and review and check bindings. Retaining the Chapter 72 timeline and references is an honest bridge limitation, not the intended native end state.
- Missing inherited supporting targets MUST block the affected update or offer an explicit targeted repair. They MUST NOT trigger a hidden historical rebuild.
- The claims and promotion machinery needs a delta-aware input type. A Chapter 75-only corpus cannot stand in for inherited Chapters 2–74. Inherited citations MUST resolve through retained baseline evidence and custody, not be falsely required to exist in a Chapter 75-only corpus. Inherited span and mapping checks and approvals carry over only where their complete dependencies remain valid.
- Each changed complete grounding document still requires a current exact sign-off bound to the composed candidate, its supporting bundle and its report. An old whole-document approval cannot authorize changed bytes. New or changed assertions, cross-document effects and applicable authority still require their normal checks. Inherited limitations remain visible; neither a model pass nor baseline adoption certifies all old prose.
- Baseline adoption with live edits shows each difference from the immutable generation and its retained origin and approval, if available. The GM MUST explicitly resolve unreviewed differences. Adoption preserves earlier generations and receipts and does not retroactively claim that prior local corrections were native promotions. A campaign MUST be able to enter the native incremental workflow from a valid adopted baseline without first regenerating its entire history.

**NPC-specific contract (N1–N5)**

- Each NPC's baseline is selected from the publication log and the exact published draft, evidence and composition lineage. Different subjects may legitimately have different last-publication horizons. A newer unpublished draft is not a substitute. A hand-edited published target, missing baseline evidence or broken lineage produces a named repair requirement. A genuine historical publication approval remains baseline provenance when shared-review custody later goes stale solely through an unrelated NPC. It is not current authority for republishing the baseline or for approving its new candidate.
- The planner reads the complete selected new chapters and accounts for literal and indirect references. Its census distinguishes materially changed, new, mentioned-but-unchanged, absent from selected sources, explicitly deferred, excluded and unresolved. Unregistered names and deliberate exclusions remain distinguishable. Models may propose changes or contextual associations; identity, affected scope and unsupported facts require the existing authority and human checkpoints.
- A contextual association records the canonical identity, the exact source revision and scene or span, the established relationship support, a rationale, scope, audience and the reviewer's decision. Accepting all faction offers can affect the relevant representatives' obligations without proving that their support teams deployed. A scoped short-name resolution MUST NOT automatically add a global alias. Rejected, Discuss and unresolved associations remain visible and cannot silently enter drafting evidence.
- Approved historical draft and evidence blocks are reused exactly for existing dossiers. Supported new events are appended, and stale current status, location and relationships are replaced. New NPCs are drafted from selected new evidence. Published GM dossier bytes may be hashed for lineage but MUST NOT be copied wholesale into prompts, because composition can contain Secrets. Authored material is preserved through its owning native interfaces.
- Sparse verification enumerates the actual targets and source spans available to each NPC. A horizon such as Chapters 2–75 does not make every chapter, scene, entry or moment available evidence. Entry and moment targets MUST have real bound supporting spans and cannot be synthesized from chapter membership. Missing required support is distinguished from inherited or unexamined scope. The verifier's real findings and semantic limits are retained. An unrelated historical wording issue is not a reason to redraft all old history.
- An unchanged attestation binds the existing publication, the exact added sources, evidence and context links, relevant identity, authority and rules, and the GM's reason. It permits a later horizon to reuse the vetted dossier where appropriate, without editing the dossier or pretending it was republished. Existing absence-based carry remains automatic where its current rules apply. Mentioned-but-unchanged carry requires the explicit attestation requested by #585. Unselected is not the same as examined and unchanged.
- Per-dossier sign-off freshness follows the actual dependency graph. Changing B's independent draft or evidence MUST NOT stale A merely because they shared a review. Changing a shared source, identity ruling, relevant authored material, verification rule or contextual association MUST stale every affected item, even when its draft bytes happen to remain equal. Old decisions are preserved, and authority is never renewed by copying an old approval onto new prose.

### Key Entities *(include if feature involves data)*

- **Delta plan**: Campaign identity; operation identity and version; products; stopping point; exact selected sources and rulings; generation and consistency model settings; base and adoption identity; selection census; dependency edges.
- **Grounding baseline**: Published generation identity and manifest; the four immutable, live and origin digests; approved patch and adoption lineage; existing timeline, reference and support digests; per-member inherited coverage, gaps and audience.
- **NPC baseline**: Canonical subject; actual publication entry with full and body hashes; reviewed draft, cached evidence and authored composition dependencies; last actual horizon; any later unchanged attestations.
- **Evidence context**: Full or sparse kind; exact available targets and source spans; per-artifact digests; inherited versus new distinction; reviewed associations; authority, audience and rule revisions; missing versus unexamined scope.
- **Edit proposal**: Subject and document; stable target identifier; before digest; proposed bytes; category; rationale; support; dependent locations and required follow-up checks.
- **Review binding**: Exact candidate, plan, evidence and rule hashes; item and document decisions; reviewer; explicit decision revision; approval scope; inherited and outstanding findings.
- **Publication intent and receipt**: Expected current destinations; fresh preview, check and sign-off bindings; per-member effects; inherited or replaced generation lineage; actual output digests; idempotency key; partial or recovery state.
- **Run report**: Durable stages and artifacts; parsed-source and integrity-read counts; model call identity and results; decisions; changed/new/unchanged/held census; actual draft, application and publication status.

Normal stages are: plan, prepare baseline and evidence, propose and draft, verify and check, review, publication preview, and application. Each stage can be stopped deliberately. A run may be failed, stale, awaiting review, partial or recovery-required; these states must be discoverable after restart. "Complete" means the requested stopping point is achieved for every required selected member, not that some output files happen to exist.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In the one-new-chapter fixture, exactly that chapter is parsed as new input. Historical parse and extraction calls and historical prose redrafting are zero. Declared custody hashes and selected cached-artifact reads are reported separately.
- **SC-002**: All unrelated baseline fragments and unselected publications remain byte-identical. Heading, table and citation checks catch destructive edits, including accidental deletion of both copies of a repeated heading.
- **SC-003**: Replaying the Chapter 75 fixture produces the supported accepted agreements, the completed forge restoration, the exhausted dust, exact selections, and the unresolved missing-memory requester, without claiming unobserved deployment, attunement or a final Glabbagool reward.
- **SC-004**: The changed-NPC, passing-mention, new-NPC, mixed-horizon and indirect-reference cases each complete through public supported operations, without campaign-specific orchestration or sign-off overrides.
- **SC-005**: Mutating each bound baseline, relevant source, draft, rule, association or destination produces the appropriate stale or conflict refusal. Mutating an unrelated dossier does not invalidate a valid independent approval.
- **SC-006**: Failure injection at every durable boundary shows that grounding activation is safe and that NPC member outcomes are honest and recoverable, including target-before-log and log-before-run-receipt failures. An identical completed replay performs no content writes.
- **SC-007**: Secret canaries never appear in drafting prompts, intermediate model artifacts, player views or diagnostic output. Reusing a GM evidence cache or review in a player or character request is refused before content is exposed; fallback and reference paths cannot bypass that refusal; unclassified legacy evidence remains GM-only. A Secrets-only change can be composed without a new prose model call, and applicable composition and sign-off freshness still apply.
- **SC-008**: CLI and application integration tests produce equivalent plans, eligibility results, saved decisions and receipts. Restart and supported worktree transfer preserve exact campaign identity and current approvals.
- **SC-009**: A complete native grounding delta succeeds with inherited old citations and nested references. Missing required inherited support blocks with a targeted repair requirement, without fabricating coverage or rescanning history.

## Assumptions

- The Chapter 75 workflow's reviewed summary (SHA-256 above) is the reference fixture for the acceptance tests.
- Existing #512 caches, the claims and promotion gates, NPC verification and sign-off, and the authority and locking primitives are reused as they are; this feature extends them and does not replace them.
- Existing NPC publication remains independent per member. A future atomic multi-NPC selection mode would be a separate contract and is not assumed.
- Campaign identity is preserved across worktrees and artifact transfers by the existing canonical identity; this feature does not change how identity is stored.
- Session prep continues to treat the four grounding documents as navigation indexes, with summaries as the authority, as already documented for the summary-native pipeline.
- No new model provider is introduced. Model selection uses the existing backends and explicit selection rules (FR-010).

### Explicit Exclusions

- No graph-store rewrite, fuzzy identity inference, historical source rewriting, automatic retcon, broad full-refresh optimization, replacement authority ledger, or mandatory cross-NPC or grounding global transaction.
- Full refresh remains available as a separate, explicit user choice.
- Implementation must correct outdated operator text that still describes manual grounding copying. It must distinguish three things: "existing cache or full-range rerender," "native delta generation and publication," and "explicit local editable-live correction." A local bridge must not be advertised as the native feature.

## Delivery Order

1. **Foundation (P1)**: Selected-source ingestion; typed full and sparse evidence; baseline and adoption records; per-item dependency bindings; durable run identity and read accounting. Reuses #512 caches and current authority and review primitives.
2. **NPC path (P1)**: Publication-bound census; contextual review; unchanged attestations; minimal historical reuse; typed native verification; selected native publishing; recoverable member receipts. Addresses #587 and #585.
3. **Grounding path (P1)**: Host-owned minimal edits; bounded consistency; inherited claims and citations; complete timeline and reference lineage; integration with native bundle promotion. Addresses #588.
4. **Workflow completion (P2)**: Canonical and worktree transfers; review lifecycle; portable receipts; reduced operator handoffs. Application parity accompanies the corresponding engine capabilities in this same feature; it is not deferred to a later release. A CLI-only completion does not satisfy the feature.

## References (non-normative)

Pointers to the evidence and existing seams. These are background for the planner, not requirements.

### Existing toolkit

- [Corpus validation](../../pipelines/summary_native/validate.py): the `scan` step parses discovered files before applying range scope. [Corpus building](../../pipelines/summary_native/corpus.py) consumes the resulting in-range input set. Selected-file ingestion must precede validation.
- [NPC linker](../../pipelines/summary_native/npc_link.py): exact identity forms, whole observations and explicit digests; not contextual identity inference.
- [NPC drafting](../../pipelines/summary_native/npc_draft.py): existing prompt caching, draft records, dispatch and resume to reuse.
- [NPC verifier](../../pipelines/summary_native/npc_verify.py) and [review verifier adapter](../../pipelines/summary_native/review/verification.py): existing deterministic verification and pure adaptation; a supported delta-context contract is missing.
- [Review CLI](../../pipelines/summary_native/review/cli.py): real verification, source custody and exact-draft approval.
- [NPC publication](../../pipelines/summary_native/npc_publish.py): existing eligibility and overwrite checks; shared-custody freshness and independent member writes are the relevant seams.
- [Bundle selection](../../pipelines/summary_native/promotion/manifest.py), [record gate](../../pipelines/summary_native/promotion/gates.py) and [claims source selection](../../pipelines/summary_native/claims/selection.py): the full-range lineage and custody seams that native delta records must extend without bypassing.
- [Authored loader](../../pipelines/summary_native/npc_authored.py) and [composer](../../pipelines/summary_native/npc_compose.py): preserve the manual and Secrets boundary.
- [Review operations](../../docs/cli/summary_native_review.md), [authority](../../docs/cli/summary_native_authority.md), [grounding migration](../../docs/cli/grounding_bundle_migration.md) and [grounding promotion](../../docs/cli/grounding_bundle_promotion.md): current gates, not missing functionality.
- [Spec 036](../036-review-adjudication/spec.md) and [Spec 037](../037-promotion-gate/spec.md): reuse their existing freshness, recovery and publication contracts.

### Completed campaign evidence

Pinned to campaign shipment commit `a3334ae5f98589557918925046cdea114dcc027e`. These are reference evidence, not templates to execute unchanged.

- [NPC delta README](https://github.com/kostadis/campaigns/blob/a3334ae5f98589557918925046cdea114dcc027e/out-of-the-abyss/notes/npc_delta/ch075/README.md), [builder](https://github.com/kostadis/campaigns/blob/a3334ae5f98589557918925046cdea114dcc027e/out-of-the-abyss/notes/npc_delta/ch075/build_delta.py), and [completion audit](https://github.com/kostadis/campaigns/blob/a3334ae5f98589557918925046cdea114dcc027e/out-of-the-abyss/notes/npc_delta/ch075/completion_audit.json).
- [Grounding delta README](https://github.com/kostadis/campaigns/blob/a3334ae5f98589557918925046cdea114dcc027e/out-of-the-abyss/notes/summary_native_delta/ch075-20261106/README.md), [baseline and source manifest](https://github.com/kostadis/campaigns/blob/a3334ae5f98589557918925046cdea114dcc027e/out-of-the-abyss/notes/summary_native_delta/ch075-20261106/manifest.json), and [application receipt](https://github.com/kostadis/campaigns/blob/a3334ae5f98589557918925046cdea114dcc027e/out-of-the-abyss/notes/summary_native_delta/ch075-20261106/grounding_application_manifest.json).
- [Shipment scope and sanitization record](https://github.com/kostadis/campaigns/blob/a3334ae5f98589557918925046cdea114dcc027e/out-of-the-abyss/notes/shipments/ch075-reviewed-20261105.json): separate commits, exact reviewed source, runtime exclusions and retained original exports.
