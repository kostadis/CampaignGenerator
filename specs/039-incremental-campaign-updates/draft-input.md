# Feature Specification: Incremental Campaign Grounding and NPC Updates

**Created**: 2026-11-05  
**Status**: Draft; specification only, no implementation or new commands shipped  
**Code baseline**: `887a5c17aa3b34ff43d4e83c6ed7f8e40b29aa72`  
**Input**: Describe the gaps in CampaignGenerator's incremental grounding-document and NPC processes, using the completed Out of the Abyss Chapter 75 workflow as evidence.  
**Related work**: [#588](https://github.com/kostadis/CampaignGenerator/issues/588) (grounding delta), [#587](https://github.com/kostadis/CampaignGenerator/issues/587) (changed-NPC delta), [#585](https://github.com/kostadis/CampaignGenerator/issues/585) (unchanged attestation). [#512](https://github.com/kostadis/CampaignGenerator/issues/512) is closed and supplies existing cache/carry behavior; it does not deliver this workflow.

## Problem and intended outcome

After reviewing a new session, the GM should be able to update the four grounding documents and materially affected NPC dossiers from the last reviewed publications plus that session. Established history should survive unchanged. The update should pass the existing authority, verification, review and publication gates without a historical rebuild, campaign-specific scripts, or an exception allowing direct live edits.

CampaignGenerator has many of the necessary components. What it lacks is a supported end-to-end operation that binds an actual published baseline, selects only new sources, generates minimal changes, preserves inherited evidence, and carries that exact lineage through review and publication. A one-chapter `synth` is a one-chapter synthesis, not a merge into an existing baseline. Cached full-range extraction is useful but does not establish bounded source reads or preserve reviewed prose.

This specification defines the missing contracts. It does not replace the existing promotion, NPC publication or review systems. Interface names below describe operations, not installed CLI syntax.

## Evidence: the Chapter 75 workflow

The reviewed November 2 summary has SHA-256 `ca597853064830cbd9596fe70616d8ab4e338b308b46deea9af07860e8a497d5`. The campaign artifacts linked in [Evidence and integration points](#evidence-and-integration-points) retain the actual decisions and receipts.

| Area | What the completed workflow established | Glue the operator supplied |
|---|---|---|
| Sources | The exact reviewed summary, rather than the older imported export; a selected-only flat publication reused by both updates | Located a separate batch worktree, checked the summary digest, and ran repository publication functions in a one-chapter scratch root |
| NPCs | Ten existing dossiers updated and three new dossiers published; thirteen native verifier passes; 96 unselected publications unchanged | Publication-specific baseline inventory, cached-evidence merge, contextual links, sparse verification context, native review construction and explicit selected publication |
| Grounding | Four documents advanced from the approved Chapters 2–74 live baseline using Chapter 75 only; one stale item-selection statement repaired and rechecked | Numbered baseline lines, model replacement proposals, host reconstruction, preservation checks, consistency and custom review/application records |
| Publication | NPCs used native sign-off and publication; grounding used a separately approved guarded editable-live correction | The grounding run could not produce a native baseline-plus-delta generation. It retained origins/backups and left the native Chapter 72 generation, timeline, references and historical receipts unchanged |
| Review and delivery | Four draft approvals followed by a separate application approval; review servers stopped after saved decisions were validated | The first artifact was explicitly draft-only, so another approval was necessary. Runtime capability URLs required removal from shipment metadata without changing signed records |

The grounding baseline was not merely the Chapter 72 immutable publication: it also included approved live updates for Chapters 73–74. NPC baselines likewise differed by subject: most selected dossiers ended at Chapter 74, while Dawnbringer's actual published baseline ended at Chapter 73. A range directory name alone could not establish either baseline.

**Read-bound terminology:** “no historical rescan” means no historical summary parsing, extraction, model input or redrafting. Hashing an exact historical custody dependency can still read its bytes. The product must report those integrity reads separately rather than claiming that no historical file was opened at all.

## Existing capabilities that must be preserved

- Range-based corpus building, content-addressed extraction reuse across ranges, and carry-forward of eligible NPC dossiers absent from newly checked notes. These are existing behavior, including the delivered portion of #512.
- NPC prompt-key skips, model-stage run records, dispatch and compatible draft resume. An identical prompt-key skip is not an attestation that later chapters leave a published dossier unchanged.
- Deterministic NPC verification and composition; exact-draft GM sign-off; explicit selected publication; overwrite guards and authority writer locking. NPC publication is currently independent per member, not an atomic multi-NPC batch.
- Native authority and shared review records, freshness checks, proposal application, identity review and recovery. A citation resolving is not proof that its prose meaning is true.
- Managed grounding migration, claims selection/checking, four exact document sign-offs, digest-bound promotion previews, whole-generation activation, historical receipts and recovery.
- Structural separation of authored NPC manual material from Secrets: the safe draft/manual inputs can reach a model; composed GM Secrets must not be used as convenient drafting input.

The feature extends those systems to understand delta lineage. It must not fabricate a full-corpus receipt, a successful verifier result, a native sign-off, or a complete historical coverage claim to make existing gates accept a sparse update.

## Gap inventory

P1 covers core correctness. P2 covers operator workflow. CLI/application parity is mandatory in the same delivered feature regardless of phase priority.

| ID | Priority | Gap in the current product | Required behavior |
|---|---|---|---|
| G1 | P1 | No native four-document baseline-plus-selected-chapters generator | Typed delta plan, exact baseline bindings, minimal evidence-backed edits and host-validated reconstruction |
| G2 | P1 | Ordinary range validation parses the directory before filtering; a range flag does not enforce a new-source-only read bound | Explicit selected-file ingestion and observable parse/prompt boundaries, without scratch-root scripts |
| G3 | P1 | Promotion and claims expect full-range corpus/notes/synthesis records; sparse new-chapter input cannot account for inherited citations and members | Native delta lineage and inherited custody/citation resolution accepted by the existing complete-bundle gate |
| G4 | P1 | A managed generation plus approved editable-live patches is not a first-class reviewed delta baseline | Deliberate baseline adoption that distinguishes immutable publication, current live bytes, retained origins and unreviewed drift |
| N1 | P1 | No publication-bound changed/new/unchanged NPC planner or cross-range minimal updater | Per-NPC actual publication baseline, reviewed change census, exact historical reuse and selective generation |
| N2 | P1 | Cached evidence plus new sources has no supported, typed sparse verification/review input | Explicit available targets, source lineage, coverage and audience; real native verification over that context |
| N3 | P1 | Shared-review custody can stale one dossier when an unrelated member changes | Complete per-dossier dependency closure; shared dependencies still invalidate every actual consumer |
| N4 | P1 | Literal linking cannot express scoped contextual associations needed for indirect references | Reviewable source-bound associations without invented aliases, source rewrites or automatic identity decisions |
| N5 | P1 | Passing mentions lack a native unchanged-through-new-chapters attestation | Evidence-bound GM attestation, original dossier bytes/horizon retained, affected freshness checks |
| C1 | P1 | Model-stage resume and individual native operations do not constitute a recoverable end-to-end delta run | Durable stages, exact selection, member receipts, safe resume, explicit partial outcomes and idempotence |
| C2 | P2 | The bridge requires manual worktree handoffs, separate scope explanations and serving/shipment cleanup | Supported verified artifact transfer, clear approval/application scope, discoverable run status and portable provenance |

### G1–G4: grounding-specific contract

The baseline must bind all four documents, their retained origins, the active generation and its manifest/receipts, and the exact editable-live hashes. Its declared historical coverage is inherited, with known gaps and limitations preserved. A newer directory or a mutable live file is not evidence of reviewed lineage. Coverage must be recorded per member: live prose through Chapter 74 does not advance the coverage of an inherited Chapter 72 timeline or reference tree. Complete bundle membership and complete historical coverage are different claims.

Assign stable paragraph or line identifiers to the bound baseline. A replacement proposal names its target identifier, proposed text, change category, rationale and exact selected-source support. Host code supplies the before-text, rejects unknown/duplicate/overlapping targets, and preserves all untouched bytes. Local changes must not require a model to reproduce a large old table or document from memory.

Categories must distinguish new information, superseded current state, a resolved thread, a historical event and no material change. Correct recurring present-tense claims everywhere they conflict with new evidence, while retaining historical accounts as history. Existing annotation behavior intentionally adds warnings without rewriting prose; delta replacement is a separate explicit reviewed operation, not a change to `annotate`'s invariant.

A native delta generation must carry a complete effective bundle: four documents, timeline, full nested reference tree, reading-contract records and dependency lineage. Unchanged members can be inherited with exact digests; affected timeline/reference members need bounded deterministic updates and review/check bindings. Retaining the Chapter 72 timeline and references was an honest bridge limitation, not the intended native end state. Missing inherited supporting targets must block the affected update or offer an explicit targeted repair; they must not trigger a hidden historical rebuild.

The existing claims and promotion machinery needs a delta-aware input type. Today, bundle selection expects native corpus/notes/synthesis records, the record gate requires a synthesis step, and claims source discovery resolves citations against that selected corpus. A Chapter 75-only corpus therefore cannot stand in for inherited Chapters 2–74. Existing generation parent activation records publication ancestry; it does not establish incremental input composition or evidence coverage. Inherited citations must resolve through retained baseline evidence/custody, not be falsely required to exist in a Chapter 75-only corpus. Inherited span/mapping checks and approvals may carry only where their complete dependencies remain valid. Each changed complete grounding document still requires a current exact v2 sign-off bound to the composed candidate, supporting bundle and report; an old whole-document approval cannot authorize changed bytes. New or changed assertions, cross-document effects and applicable authority still require their normal checks. Inherited limitations must remain visible; neither a model pass nor adoption certifies all old prose.

When adopting a baseline with live edits, show each difference from the immutable generation and its retained origin/approval if available. The GM must explicitly resolve unreviewed differences. Adoption must preserve earlier generations and receipts and must not retroactively claim that prior local corrections were native promotions. A campaign should be able to enter the native incremental workflow from a valid adopted baseline without first regenerating its entire history.

### N1–N5: NPC-specific contract

Select each NPC's baseline from the publication log and exact published draft/evidence/composition lineage. Different subjects can legitimately have different last-publication horizons. A newer unpublished draft is not a substitute. A hand-edited published target, missing baseline evidence or broken lineage produces a named repair requirement. A genuine historical publication approval remains baseline provenance when shared-review custody later became stale solely through an unrelated NPC; it is not current authority for republishing the baseline or for approving its new candidate.

The planner must read the complete selected new chapters and account for literal and indirect references. Its census distinguishes materially changed, new, mentioned-but-unchanged, absent from selected sources, explicitly deferred, excluded and unresolved. Unregistered names and deliberate exclusions must remain distinguishable. Models may propose changes or contextual associations; identity, affected scope and unsupported facts require the existing authority/human checkpoints.

A contextual association records the canonical identity, exact source revision and scene/span, established relationship support, rationale, scope, audience and reviewer decision. Accepting all faction offers can affect the relevant representatives' obligations without proving that their support teams deployed. A scoped short-name resolution must not automatically add a global alias. Rejected, Discuss and unresolved associations remain visible and cannot silently enter drafting evidence.

Reuse approved historical draft and evidence blocks exactly for existing dossiers, append supported new events, and replace stale current status/location/relationships. Draft new NPCs from selected new evidence. Published GM dossier bytes may be hashed for lineage but must not be copied wholesale into prompts because composition can contain Secrets. Preserve authored material through its owning native interfaces.

Sparse verification must enumerate the actual targets and source spans available to each NPC. A horizon such as Chapters 2–75 does not make every chapter, scene, entry or moment in that interval available evidence. Entry/moment targets must have real bound supporting spans; they cannot be synthesized from chapter membership. Distinguish missing required support from inherited/unexamined scope, and retain the verifier's real findings and semantic limits. An unrelated historical wording issue is not a reason to redraft all old history.

An unchanged attestation binds the existing publication, exact added sources/evidence/context links, relevant identity/authority/rules and the GM's reason. It permits a later horizon to reuse the vetted dossier where appropriate without editing the dossier or pretending it was republished. Existing absence-based carry remains automatic where its current rules apply; mentioned-but-unchanged carry requires the explicit attestation requested by #585. Unselected is not the same as examined-and-unchanged.

Per-dossier sign-off freshness must follow the actual dependency graph. Changing B's independent draft/evidence must not stale A merely because they shared a review. Changing a shared source, identity ruling, relevant authored material, verification rule or contextual association must stale every affected item even when its draft bytes happen to remain equal. Preserve immutable old decisions; never renew authority by copying an old approval onto new prose.

## User scenarios and acceptance tests

### Story 1 — Update the four documents from one reviewed session (P1)

**Independent test:** Begin with a valid/adopted Chapters 2–74 baseline and select only Chapter 75. Produce four complete candidates and a native complete-bundle preview without parsing historical summaries.

1. Given current-state text saying faction answers and Davra's meeting are pending, when the delta is checked, then all conflicting current assertions are revised; the earlier negotiation history survives.
2. Given the completed forge restart and spent dust, when the update is generated, then current inventory and objectives reflect completion without inferring a new rest, attunement or unrecorded delivery.
3. Given an inherited old citation or reference, when the delta is checked/promoted, then its retained lineage resolves it without a fabricated one-chapter full-corpus manifest.
4. Given reviewed live patches and an unreviewed live hunk, when baseline adoption is proposed, then the former retains its true local lineage and the latter requires explicit disposition before use.
5. Given a baseline with gaps, when Chapter 75 is applied, then coverage remains that baseline plus the selected chapter, not a claim of complete history through 75.
6. Given live prose through 74 but supporting timeline/references through 72, when the baseline is adopted, then per-member gaps remain explicit. The delta cannot label those supporting members complete through 74/75; any required repair uses separately selected authorized sources or refuses with the precise missing dependency.
7. Given unchanged candidate prose but a changed relevant old source, retained excerpt or reference digest, when inherited custody is checked, then affected reuse/sign-offs become stale or require focused repair. Hash reads are disclosed; they do not silently become historical parsing, extraction or model input.

### Story 2 — Update only affected NPCs (P1)

**Independent test:** Use mixed Chapter 73/74 published bases, one new chapter, a material change, a passing mention and a new NPC.

1. The changed NPC keeps its old history/quotes byte-identical and gains supported new history/current state. The new NPC receives a bounded new dossier.
2. An unpublished newer draft is ignored as a baseline; broken publication-to-draft lineage refuses that subject with an actionable reason.
3. A scene-only named NPC without an NPC heading receives bounded evidence through an approved identity/context path, or an explicit unresolved/excluded census outcome; it cannot silently vanish as a registry-only finding. An indirect title/pronoun/collective association requires scoped review and does not imply physical presence or deployment.
4. An approved unchanged attestation leaves the old publication byte-identical. An explicitly unselected subject is not reported as reviewed through the new chapter.
5. Changing B's independent evidence stales B, not A; changing their shared source stales both. Changing the new draft requires a new exact-draft sign-off.
6. A missing cached scene, absent entry/moment span, corrupt cache or attempted sparse-as-full substitution blocks the affected candidate. Native real verification runs; caller-supplied PASS is rejected.
7. An exact historically approved publication remains usable baseline provenance after unrelated group drift; the changed whole candidate still requires its own current approval.

### Story 3 — Review and apply the exact intended update (P1)

**Independent test:** Review the concrete candidates and publication effect through CLI and application, then change one bound input before application.

1. Diffs for existing prose, full prose for new dossiers, evidence, exact hashes, coverage and inherited findings are shown. All four complete grounding candidates remain inspectable.
2. Draft approval, unchanged attestation, scoped association approval and publication authorization have explicit distinct meanings. They may be collected in one concrete review handoff; the feature must not force a second permission round solely because the application effect was omitted from the first page.
3. Discuss, unmarked, unsaved or stale decisions block the affected action. Elapsed time and a model's consistency verdict do not grant approval.
4. A changed baseline, selected source, output, applicable authority or publication destination invalidates the relevant check, sign-off or preview as appropriate. Prior historical approvals remain in the record.
5. An unchanged relevant approval is reused without another question. Changed findings trigger a targeted repair/recheck, not a historical regeneration.

### Story 4 — Resume and publish with honest outcomes (P1)

**Independent test:** Interrupt at evidence generation, model output, verification, review creation, sign-off, first publication and receipt creation, then resume.

1. Completed compatible stages are reused by digest; failed/incomplete output cannot be mistaken for a prior successful draft. No duplicate approvals or logical publication occur.
2. Grounding uses the existing complete-generation transaction and supported consistent-reader behavior. Failure before activation leaves the prior generation usable; an ambiguous activation is inspected/recovered by operation identity.
3. NPC publication declares its independent-member semantics. Every selected member has a durable outcome, and a crash between target write, log update and completion receipt can be reconciled safely. A lock or a sequence of replacements is not described as an atomic batch.
4. Held/rejected NPCs keep their old publications; publication is blocked where a required dependency is held. A mixed result is PARTIAL, not COMPLETE. Repeating the same completed intent produces a no-op or its recorded receipt.
5. If NPC publication precedes a grounding update, the grounding plan binds the exact resulting dossiers. A changed or missing required dossier blocks dependent grounding checks. No cross-subsystem atomic transaction is implied.
6. Work batches are materialized from the plan before dispatch. Changing batch size does not change the selected subjects or their semantic outcomes; compatible skipped work makes zero model calls. Resume reuses the existing dispatcher rather than inventing a second scheduling engine.

### Story 5 — Use the workflow without local glue (P2)

**Independent test:** Run the same selected update through CLI and the application from a supported worktree, restart its review server, and inspect durable status.

1. Both surfaces use the same plan, service contracts, gate results and receipts. Source selection, model settings and the stopping point persist across phases.
2. A deliberate verified artifact-transfer/worktree binding preserves canonical campaign identity; no edit to `campaign.json` or disabled moved-campaign guard is required.
3. Review hosting restarts without losing saved decisions. Capability URLs are runtime metadata; durable receipts remain useful without shipping access tokens.
4. The final report identifies changed/new/unchanged/deferred/unresolved members, sources parsed versus custody inputs hashed, model calls, checks, decisions and actual publication state.

## Functional requirements

| ID | Requirement |
|---|---|
| FR-001 | Provide an explicit incremental mode distinct from full refresh, with selected reviewed source revisions, requested products and stopping point. Never silently fall back to a full scan. |
| FR-002 | Bind a four-document grounding baseline and actual per-NPC publication baselines by identity, retained lineage and digest. Do not choose by newest directory or nominal end range. |
| FR-003 | Support explicit adoption of valid legacy or edited-live baselines, with origins, reviewable drift, audience and coverage limitations; do not hide migration/adoption inside generation. |
| FR-004 | Accept an explicit selected-file source set. Record parsed new summaries, parsed historical summaries, reused baseline artifacts, integrity-only dependencies and model-input sources separately. |
| FR-005 | Record full versus sparse evidence as different types; enumerate actual available targets, lineage, audience and limitations. A sparse candidate cannot masquerade as a complete corpus. |
| FR-006 | Use stable host-owned edit identifiers, exact before/after bindings, categories, reasons and evidence. Reject malformed, duplicate, overlapping, stale or unsupported edits and unjustified empty proposals. |
| FR-007 | Preserve unrelated baseline bytes, quotations, citations, open promises, GM staging and authored material. Check headings, table widths and citation targets as well as prose. |
| FR-008 | Find superseded current assertions across each affected document/dossier; preserve prior statements as history where appropriate rather than appending contradictory overlays. |
| FR-009 | Keep testimony versus observation, acceptance versus delivery, plans versus outcomes, and GM versus party knowledge distinct. Do not infer resources, powers or secret causes. |
| FR-010 | Expose explicit generation and consistency backend/model/effort selections, retain actual run identity, and fail without silent model/provider substitution. |
| FR-011 | Provide the complete NPC disposition census and reviewed scoped-context associations. Never use fuzzy identity merging or invented aliases to increase coverage. |
| FR-012 | Reuse real native NPC verification, composition, sign-off and selected publication over the supported typed delta context; authored Secrets remain structurally outside drafting input. Enforce exact audience compatibility before exposing cached content, including fallback, reference and diagnostic paths. Unclassified legacy evidence remains GM-only until explicitly classified/granted under existing authority rules. |
| FR-013 | Provide unchanged attestations with exact publication/new-evidence/ruling bindings and scope. Keep original publication bytes and its actual provenance horizon. |
| FR-014 | Bind freshness to complete relevant per-item dependencies, with shared-dependency invalidation; unrelated review-group members must not stale each other. |
| FR-015 | Run bounded semantic consistency on all proposed deltas and cross-document effects; after repair check exact changed spans/outstanding findings. Disclose semantic limits without relabeling failed required checks as limitations. |
| FR-016 | Carry or update all required grounding bundle members with explicit inheritance and support mappings. Integrate delta source lineage into existing claims selection/checks, exact sign-offs and digest-bound native promotion. |
| FR-017 | Keep draft approval and live-application authority explicit. Support a concrete combined review handoff when scope is known, reuse prior valid authorization, and require fresh review only for affected changes. |
| FR-018 | Persist a versioned run state with exact input/output hashes, materialized bounded work batches, stage results and member outcomes; reuse existing dispatch/resume, keep selection/results invariant to batch size, skip compatible work without model calls, and report failures, partial progress and stale state accurately. |
| FR-019 | Reuse native whole-generation atomicity/recovery for grounding. Add durable per-member reconciliation/idempotence around existing independent NPC publication; do not falsely claim group atomicity. |
| FR-020 | Require a fresh publication preview/preconditions. Separate source-approval dependencies from expected current destination hashes; a concurrent destination publication must cause a publication conflict. |
| FR-021 | Preserve immutable generations, signed decisions and historical receipts. Never use test overrides, force, manufactured synth records, caller-asserted verification, or writes over managed aliases to bypass gates. |
| FR-022 | Deliver equivalent CLI and application operations in the same feature with the same durable state; provide supported verified canonical/worktree artifact transfer without rewriting campaign identity. |
| FR-023 | Keep private hosting capabilities separate from durable evidence. Persist and validate saved review decisions; stopping/restarting serving must not imply approval or lose it. |
| FR-024 | Produce a completion receipt with selected chapters, inherited coverage/gaps, changed/new/carried/held subjects, exact publication hashes, checks, decisions, read/call counts and recovery state. Git actions require their own user scope. |

## Core records and lifecycle

| Record | Required information |
|---|---|
| Delta plan | Campaign identity; operation identity/version; products; stopping point; exact selected sources and rulings; generation/consistency model settings; base/adoption identity; selection census; dependency edges |
| Grounding baseline | Published generation identity and manifest; four immutable/live/origin digests; approved patch/adoption lineage; existing timeline/reference/support digests; per-member inherited coverage, gaps and audience |
| NPC baseline | Canonical subject; actual publication entry and full/body hashes; reviewed draft, cached evidence and authored composition dependencies; last actual horizon; any later unchanged attestations |
| Evidence context | Full/sparse kind; exact available targets and source spans; per-artifact digests; inherited/new distinction; reviewed associations; authority/audience/rule revisions; missing versus unexamined scope |
| Edit proposal | Subject/document; stable target ID; before digest; proposed bytes; category; rationale; support; dependent locations and required follow-up checks |
| Review binding | Exact candidate/plan/evidence/rule hashes; item and document decisions; reviewer; explicit decision revision; approval scope; inherited and outstanding findings |
| Publication intent/receipt | Expected current destinations; fresh preview/check/sign-off bindings; per-member effects; inherited/replaced generation lineage; actual output digests; idempotency key; partial/recovery state |
| Run report | Durable stages and artifacts; parsed-source and integrity-read counts; model call identity/results; decisions; changed/new/unchanged/held census; actual draft/application/publication status |

Normal stages are plan, prepare baseline/evidence, propose/draft, verify/check, review, publication preview and application. Each stage can be stopped deliberately. A run may become failed, stale, awaiting review, partial or recovery-required; these states must be discoverable after restart. “Complete” means the requested stopping point is achieved for every required selected member, not that some output files happen to exist.

## Success criteria and regression suite

- **SC-001:** In the one-new-chapter fixture, exactly that chapter is parsed as new input; historical parse/extraction calls and historical prose redrafting are zero. Declared custody hashes and selected cached-artifact reads are separately reported.
- **SC-002:** All unrelated baseline fragments and unselected publications remain byte-identical. Heading/table/citation checks catch destructive edits, including accidental deletion of both copies of a repeated heading.
- **SC-003:** Replaying the Chapter 75 fixture produces supported accepted agreements, completed forge restoration, exhausted dust, exact selections and the unresolved missing-memory requester, without claiming unobserved deployment, attunement or a final Glabbagool reward.
- **SC-004:** The changed-NPC, passing-mention, new-NPC, mixed-horizon and indirect-reference cases complete through public supported operations, without campaign-specific Python orchestration or sign-off overrides.
- **SC-005:** Mutating each bound baseline, relevant source, draft, rule, association and destination exercises the appropriate stale/conflict refusal; mutating an unrelated dossier does not invalidate a valid independent approval.
- **SC-006:** Failure injection at every durable boundary proves safe grounding activation and honest recoverable NPC member outcomes, including target-before-log and log-before-run-receipt failures. Identical completed replay performs no content writes.
- **SC-007:** Secret canaries never appear in drafting prompts, intermediate model artifacts, player views or diagnostic leaks. Reusing a GM evidence cache/review in a player/character request refuses before exposing content; fallback/reference paths cannot bypass that refusal, and unclassified legacy evidence remains GM-only. A Secrets-only change can compose without a new prose model call; applicable composition/sign-off freshness still applies.
- **SC-008:** CLI and application integration tests produce equivalent plans, eligibility, saved decisions and receipts. Restart and supported worktree transfer preserve exact campaign identity and current approvals.
- **SC-009:** A complete native grounding delta succeeds with inherited old citations and nested references. Missing required inherited support blocks with a targeted repair requirement, without fabricating coverage or rescanning history.

Additional edge cases include nonconsecutive selected chapters; multi-session chapter suffixes; a deliberately incomplete baseline; revised selected source after review; earlier-chapter correction supplied as a separately explicit scope; a missing baseline cache; a later-horizon dossier requested for an earlier view; generic names; known-but-unregistered entities; duplicate contextual links; rejected or Discuss decisions; model failure leaving an old successful file behind; disk/permission failure; concurrent publication; and local live drift during baseline adoption.

## Delivery order and exclusions

1. **Foundation (P1):** Selected-source ingestion, typed full/sparse evidence and baseline/adoption records, per-item dependency bindings, durable run identity/read accounting. Reuse #512 caches and current authority/review primitives.
2. **NPC path (P1):** Publication-bound census, contextual review, unchanged attestations, minimal historical reuse, typed native verification, selected native publishing and recoverable member receipts. Addresses #587 and #585.
3. **Grounding path (P1):** Host-owned minimal edits, bounded consistency, inherited claims/citations, complete timeline/reference lineage and integration with native bundle promotion. Addresses #588.
4. **Workflow completion (P2):** Canonical/worktree transfers, review lifecycle, portable receipts and reduced operator handoffs. Application parity accompanies the corresponding engine capabilities in this same feature; it is not deferred to a later release. CLI-only completion does not satisfy the feature.

No graph-store rewrite, fuzzy identity inference, historical source rewriting, automatic retcon, broad full-refresh optimization, replacement authority ledger or mandatory cross-NPC/grounding global transaction is included. Full refresh remains available as a separate explicit user choice. A future atomic NPC selection mode would be an additional contract, not a property silently attributed to today's publisher.

Implementation must also correct outdated operator text that still describes manual grounding copying. It must distinguish “existing cache/full-range rerender,” “native delta generation/publication,” and “explicit local editable-live correction.” A local bridge must not be advertised as the native feature.

## Evidence and integration points

### Existing toolkit

- [Corpus validation](../../pipelines/summary_native/validate.py), `scan`: parses discovered files before applying range scope. [Corpus building](../../pipelines/summary_native/corpus.py), `build_corpus`: consumes the resulting in-range input set. Selected-file ingestion must precede validation.
- [NPC linker](../../pipelines/summary_native/npc_link.py), `link_with_findings` and `write_link_outputs`: exact identity forms, whole observations and explicit digests, not contextual identity inference.
- [NPC drafting](../../pipelines/summary_native/npc_draft.py), `draft_key`, `run_draft` and `_resume_draft_record`: existing prompt caching, draft records, dispatch and resume to reuse.
- [NPC verifier](../../pipelines/summary_native/npc_verify.py), `CorpusIndex`, `load_context`; [review verifier adapter](../../pipelines/summary_native/review/verification.py): existing deterministic verification and pure adaptation, with a missing supported delta-context contract.
- [Review CLI](../../pipelines/summary_native/review/cli.py), `_create_verified_dossier_review`, `_npc_signoff_items`, `_sign_npc_draft`: real verification, source custody and exact-draft approval.
- [NPC publication](../../pipelines/summary_native/npc_publish.py), `_current_draft_signoff`, `plan_publish`, `publish`: existing eligibility/overwrite checks; shared custody freshness and independent member writes are the relevant seams.
- [Bundle selection](../../pipelines/summary_native/promotion/manifest.py), `_record_and_dependencies`, `build_bundle_selection`; [record gate](../../pipelines/summary_native/promotion/gates.py), `synth_record_complete`; [claims source selection](../../pipelines/summary_native/claims/selection.py), `_discovered_rows`, `mandatory_source_closure`: the concrete full-range lineage/custody seams that native delta records must extend without bypassing.
- [Authored loader](../../pipelines/summary_native/npc_authored.py) and [composer](../../pipelines/summary_native/npc_compose.py): preserve the manual/Secrets boundary.
- [Review operations](../../docs/cli/summary_native_review.md), [authority](../../docs/cli/summary_native_authority.md), [grounding migration](../../docs/cli/grounding_bundle_migration.md) and [grounding promotion](../../docs/cli/grounding_bundle_promotion.md): supported current gates, not missing functionality.
- [Spec 036](../036-review-adjudication/spec.md) and [Spec 037](../037-promotion-gate/spec.md): reuse their existing freshness, recovery and publication contracts.

### Completed campaign evidence

The following artifacts are pinned to campaign shipment commit `a3334ae5f98589557918925046cdea114dcc027e`; they are reference evidence, not templates to execute unchanged:

- [NPC delta README](https://github.com/kostadis/campaigns/blob/a3334ae5f98589557918925046cdea114dcc027e/out-of-the-abyss/notes/npc_delta/ch075/README.md), [builder](https://github.com/kostadis/campaigns/blob/a3334ae5f98589557918925046cdea114dcc027e/out-of-the-abyss/notes/npc_delta/ch075/build_delta.py), and [completion audit](https://github.com/kostadis/campaigns/blob/a3334ae5f98589557918925046cdea114dcc027e/out-of-the-abyss/notes/npc_delta/ch075/completion_audit.json).
- [Grounding delta README](https://github.com/kostadis/campaigns/blob/a3334ae5f98589557918925046cdea114dcc027e/out-of-the-abyss/notes/summary_native_delta/ch075-20261106/README.md), [baseline/source manifest](https://github.com/kostadis/campaigns/blob/a3334ae5f98589557918925046cdea114dcc027e/out-of-the-abyss/notes/summary_native_delta/ch075-20261106/manifest.json), and [application receipt](https://github.com/kostadis/campaigns/blob/a3334ae5f98589557918925046cdea114dcc027e/out-of-the-abyss/notes/summary_native_delta/ch075-20261106/grounding_application_manifest.json).
- [Shipment scope and sanitization record](https://github.com/kostadis/campaigns/blob/a3334ae5f98589557918925046cdea114dcc027e/out-of-the-abyss/notes/shipments/ch075-reviewed-20261105.json): separate commits, exact reviewed source, runtime exclusions and retained original exports.
