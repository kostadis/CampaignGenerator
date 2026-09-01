# Feature Specification: Persistent Narration Wiki

**Feature Branch**: `358-narration-wiki`

**Created**: 2026-08-31

**Status**: Draft

**Input**: User description: "https://github.com/kostadis/CampaignGenerator/issues/358"

**Source issue**: [CampaignGenerator #358](https://github.com/kostadis/CampaignGenerator/issues/358) — “Narration findings die in the session dir: add a persistent wiki layer between critiques and the rulebook”

**Design source**: [A Persistent Wiki Layer Between Narration Critiques and the Rulebook](https://github.com/kostadis/CampaignGenerator/blob/docs/358-narration-wiki/docs/design/NarrationWiki_proposal.md)

## Clarifications

### Session 2026-08-31

- Q: When must the baseline measurement be persisted relative to Gate 1? → A: Persist it after collection and before Gate 1; Gate 1 remains unavailable without it.
- Q: How must UI-triggered narration-wiki operations reach the command-line engine? → A: Use the project's established CLI subprocess and streamed-progress seam; non-streaming responses are limited to read-only status or artifact retrieval.
- Q: What deterministic records control reconsideration of rejected proposals and disputed seed rules? → A: Reconsideration requires a new canonical source digest tied to an affected rule or an explicit GM override; each seed conflict persists its sources, digests, GM ruling, and rationale.
- Q: How can CampaignGenerator verify that deployed companion skills use campaign-resolved guidance instead of copied rule tables? → A: Require a locally readable, versioned capability manifest declaring contract version 1, `guidance_source: campaign-resolved`, and maintainer/proposer support.
- Q: Which viewport and panel-size matrix defines responsive support for the Narration Wiki UI? → A: Support a 1280×720 viewport and a 320×160 minimum for every resizable panel, with visible horizontal and vertical scrolling whenever content exceeds the available region.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Promote Durable Patterns Through a Human Gate (Priority: P1)

As a GM finishing a session review, I can select exactly one session, gather its narration critiques and supporting artifacts, and review proposed action patterns before any of them enter durable campaign or cross-campaign knowledge. Each proposal explains the problem, its root cause, and a corrective strategy rather than merely adding another banned phrase.

**Why this priority**: The feature exists to prevent useful critique findings from disappearing while preserving the GM's authority over what becomes durable guidance.

**Independent Test**: Run collection on a session containing critiques, approve one proposed structural pattern, reject another, and verify that only the approved pattern appears under the GM-confirmed wiki tier with a unique index entry and unchanged raw session artifacts.

**Acceptance Scenarios**:

1. **Given** an explicitly selected session with narration critiques, **When** the GM starts a wiki iteration, **Then** the system produces a bounded trace manifest for that session and does not inspect unrelated sessions or paths outside its campaign.
2. **Given** a draft pattern that states a problem, root cause, and corrective strategy, **When** the GM confirms the pattern and its tier, **Then** it receives a stable identity and enters the corresponding persistent wiki.
3. **Given** a draft that only lists a surface phrase or lacks a root cause, **When** it is checked or reviewed, **Then** it is refused as a durable pattern and no wiki entry is created.
4. **Given** several draft patterns from one session, **When** the GM reviews them, **Then** each pattern receives its own explicit accept-or-reject ruling; approval of the batch cannot silently approve an individual pattern.
5. **Given** collection has completed, **When** the operator attempts to begin Gate 1, **Then** a deterministic baseline measurement for the explicitly selected corpus and current authoritative guidance must already be persisted or Gate 1 refuses to open.

---

### User Story 2 - Accept or Reject One Atomic Rule Change Safely (Priority: P1)

As a GM, I can consider one narrowly scoped change to the authoritative campaign guidance, compare deterministic evidence before and after that exact change, and accept or reject it without losing the durable lesson that motivated it.

**Why this priority**: The rejection asymmetry—restore the skill-layer file but retain the wiki evidence and ruling—is the mechanism that prevents the system from repeatedly proposing the same failed idea.

**Independent Test**: From one confirmed wiki pattern, propose a one-file edit, record the before-state, reject the edit, and verify that the target file is byte-for-byte restored while the wiki page and a Rejected ledger entry containing the diff and measurements remain.

**Acceptance Scenarios**:

1. **Given** confirmed wiki knowledge and prior rulings, **When** a change is proposed, **Then** it affects exactly one authorized rulebook, character-voice file, example file, or rulebook-owned checker block and is presented as one atomic diff.
2. **Given** an atomic proposal, **When** the GM accepts it after reviewing the diff and before/after evidence, **Then** the target change persists and an Accepted ledger entry is appended.
3. **Given** an atomic proposal, **When** the GM rejects it, **Then** the target is restored exactly, the confirmed wiki knowledge remains, and a Rejected ledger entry is appended.
4. **Given** a prior rejected proposal, **When** a later iteration has neither a new canonical source digest tied to an affected rule nor an explicit GM override with rationale, **Then** the same change is not proposed again; a new path or artifact identity with an already-recorded digest does not qualify.

---

### User Story 3 - Measure and Audit the Loop Deterministically (Priority: P1)

As a GM or maintainer, I can collect evidence, measure known narration budgets, validate wiki indexes, apply a candidate patch for comparison, accept and retain it or reject and restore the prior bytes, and append rulings with deterministic tools whose results do not depend on a model's self-report.

**Why this priority**: Human judgment needs stable evidence and trustworthy history. If measurements or writeback vary between identical runs, the approval gates cannot be audited.

**Independent Test**: Run the same measurement twice over the same selected corpus and rulebook, confirm byte-identical results, attempt a duplicate ledger append and an invalid index, and verify that both invalid writes are refused without partial state changes.

**Acceptance Scenarios**:

1. **Given** unchanged narration files and authoritative guidance, **When** measurement runs twice, **Then** the two results are byte-identical and include observed value, applicable budget, and verdict for every supported category.
2. **Given** a ledger entry whose iteration identity already exists, **When** append is attempted again, **Then** the duplicate is refused and the ledger is unchanged.
3. **Given** an index with a duplicate slug or an entry missing problem, root cause, or fix information, **When** validation runs, **Then** validation fails with the offending entries identified.
4. **Given** a measurement that breaches a budget, **When** the GM reviews a proposal, **Then** the breach is shown as evidence but cannot apply the candidate for comparison, accept and retain it, or reject and restore the prior bytes by itself.

---

### User Story 4 - Reach the Same Workflow From CLI and UI (Priority: P2)

As a campaign operator, I can invoke every deterministic narration-wiki capability from either the command line or the session UI. Both surfaces use the same engine, require an explicit session selection, show the same files and results, and leave the actual pattern and rule-change judgments at visible human checkpoints.

**Why this priority**: The project requires every command-line capability to have a UI face while keeping files as the interchange and keeping judgment in the CLI or conversational review loop.

**Independent Test**: For each narration-wiki command, perform the equivalent operation from the UI on the same selected session and verify identical persisted artifacts, results, refusal behavior, and approval boundaries.

**Acceptance Scenarios**:

1. **Given** no session is selected, **When** the operator invokes collection or a later workflow action from either surface, **Then** the action refuses to run and does not interpret the empty selection as all sessions.
2. **Given** a selected session, **When** the operator invokes collection, measurement, index validation, accept, or reject from the UI, **Then** the UI executes the same command-line behavior through the project's established subprocess and streamed-progress seam and displays the resulting files and status.
3. **Given** a partially completed iteration, **When** the operator switches between UI, CLI, and conversation, **Then** each surface discovers the same state from disk without browser-only progress state.
4. **Given** a draft pattern or rule change, **When** it reaches either approval gate, **Then** the UI presents the decision and evidence but does not infer or silently submit the GM's ruling.
5. **Given** an existing CampaignGenerator page beside a narration-wiki page or panel, **When** the operator compares their colors, typography, spacing, controls, and interaction states, **Then** the narration-wiki surface follows the established visual system rather than introducing a separate theme.
6. **Given** the supported 1280×720 viewport or a resizable narration-wiki panel at its 320×160 minimum, **When** content exceeds the available width or height, **Then** visible horizontal or vertical scrollbars appear as needed and all evidence, controls, and approval actions remain reachable.

---

### User Story 5 - Seed Shared Knowledge Without Rule Forks (Priority: P2)

As a GM working across campaigns, I can reuse portable prose lessons without leaking character-specific rules into the wrong campaign. Existing hand-copied narrator caps and tic summaries are replaced by references to authoritative campaign guidance and the appropriate wiki tier.

**Why this priority**: A persistent store only improves quality if it eliminates the divergent copies that currently deliver OOTA-specific guidance to other campaigns.

**Independent Test**: Seed portable and campaign-specific patterns, run the workflow for Phandalin and OOTA, and verify that portable knowledge is available to both while named characters, caps, and canon remain limited to their owning campaign.

**Acceptance Scenarios**:

1. **Given** a pattern that names a character or campaign fact, **When** its tier is proposed, **Then** campaign-tier placement is the default and the GM must explicitly confirm any different routing.
2. **Given** a campaign-neutral craft pattern, **When** it is confirmed as portable, **Then** it becomes available to later campaign proposal work without being copied into each campaign rulebook.
3. **Given** a narration skill running against Phandalin, **When** it resolves authoritative guidance, **Then** it surfaces Phandalin narrators and rules and does not deliver OOTA narrator caps.
4. **Given** the disagreement over Phandalin's em-dash rule, **When** knowledge is seeded, **Then** the system persists a conflict record containing the stable conflict ID, rule key, competing source references and digests, GM ruling, and rationale rather than promoting either copy automatically.
5. **Given** locally deployed companion maintainer or proposer skills, **When** CampaignGenerator verifies their narration-wiki capability, **Then** a versioned manifest must declare narration-wiki contract version 1, `guidance_source: campaign-resolved`, and both supported roles; a missing or incompatible manifest prevents the dependency from being reported as complete.

### Edge Cases

- A selected session contains no critique files, or only some optional supporting artifacts; collection reports exactly what is absent and does not manufacture an empty finding.
- Critiques use any of the three known layout generations: flat `voice_critique_*` files, a `voice_critiques/` directory, or current and legacy scene-extraction and GM-assist names.
- The selected path is outside the configured campaign, resolves through a symlink outside the campaign, or is the workspace root rather than one session; collection refuses it before traversal.
- The campaign has no authoritative genre/rulebook file, as in the currently tracked toee gap; measurement and proposal work stop with an actionable error rather than silently using another campaign's rules.
- The rulebook has no campaign-specific checker configuration; applicable checks report a skipped or missing-configuration reason rather than a clean result.
- A repeated phrase occurs several times for one narrator but not another; it does not count as cross-narrator convergence.
- A candidate repeated sequence crosses markup, metadata, quoted table speech, or narrator boundaries; only eligible narration prose contributes to the measure.
- A proposed edit touches multiple files, multiple independent rules, an unauthorized file, or the narration prompt/render path; it is refused before application.
- The target file changes after the proposal's before-state was captured; application for comparison, acceptance, or restoration refuses the stale proposal rather than overwriting newer work.
- Comparison application, accepted retention, rejected restoration, or ledger append is interrupted; the operation leaves either the complete prior state or complete new state, never a partial edit or partial row.
- The same stable pattern slug is proposed with different casing or punctuation; normalization detects the collision.
- The global knowledge tier is unavailable; campaign-local collection and measurement remain usable, while cross-campaign maintenance reports the missing dependency explicitly.
- The wiki is absent during narration rendering; rendered output remains unchanged because the renderer never consumes wiki content.
- A GM rejects every proposed rule change; confirmed patterns and rejection history still persist for later reasoning.
- At the supported 1280×720 viewport or within a panel resized to its 320×160 minimum, a long path, wide measurement table, or large diff exceeds its available region; the affected page or panel exposes visible horizontal or vertical scrolling as needed without hiding the current gate.

## Requirements *(mandatory)*

### Functional Requirements

**Explicit scope and immutable evidence**

- **FR-001**: Every wiki iteration MUST operate on exactly one session explicitly selected by the operator; an empty selection MUST mean no work, never all sessions.
- **FR-002**: Collection MUST root all discovery at the selected session within its configured campaign and MUST refuse paths or followed links that escape the campaign boundary.
- **FR-003**: Collection MUST recognize flat and directory-based critique layouts plus the current and two documented legacy naming generations for scene extractions and GM-assist artifacts.
- **FR-004**: Collection MUST produce a deterministic manifest that identifies every included source, its role, and every expected-but-missing source with a reason.
- **FR-005**: Raw critiques, narration, manifests, source records, and generation settings MUST remain immutable inputs to the accumulation loop.
- **FR-006**: The default workflow MUST process sessions prospectively one at a time and MUST NOT backfill the existing historical critique corpus automatically.

**Persistent knowledge and Gate 1**

- **FR-007**: The knowledge base MUST have a portable craft tier shared across campaigns and a campaign tier versioned with the campaign whose rulebook it can influence.
- **FR-008**: Every pattern MUST have a stable normalized slug, exactly one owning tier, supporting evidence references, and explicit Problem, Root Cause, and Corrective Strategy content.
- **FR-009**: A surface phrase MAY appear as evidence, but a page that only enumerates phrases or error messages MUST fail validation and MUST NOT enter durable knowledge.
- **FR-010**: Each wiki index entry MUST identify its pattern page and summarize the problem, root cause, and fix in one or two discriminative sentences.
- **FR-011**: Duplicate pattern slugs, including normalization-equivalent slugs, MUST be refused within and across the indexes visible to a proposal run.
- **FR-012**: Gate 1 MUST remain unavailable until a deterministic baseline measurement for the explicitly selected corpus and current authoritative guidance has been persisted; it MUST then obtain and record a separate GM ruling for each draft pattern and its proposed tier before that pattern is added or updated.
- **FR-013**: A pattern that names a character or campaign canon MUST default to the campaign tier; portable placement MUST require an explicit GM confirmation.
- **FR-014**: Rejected or unreviewed Gate 1 drafts MUST NOT be available to the rule-change proposer as confirmed knowledge.

**Atomic proposal and Gate 2**

- **FR-015**: A rule-change proposal MUST reason from confirmed wiki entries, the impact ledger, and explicitly requested raw traces; it MUST NOT treat unconfirmed drafts as authority.
- **FR-016**: Each proposal MUST contain one atomic edit to exactly one authorized skill-layer file: the campaign rulebook, one character voice file, one example file, or the checker configuration owned by that rulebook.
- **FR-017**: The proposal workflow MUST refuse edits to the narration prompt, narration renderer, or any other render-path source.
- **FR-018**: The same explicitly identified narration corpus MUST be measured after collection and before Gate 1, and that persisted baseline MUST be bound to each resulting atomic proposal and compared with a measurement taken after the candidate edit is applied for comparison; any corpus or authoritative-guidance digest change MUST invalidate the baseline and require remeasurement.
- **FR-019**: Gate 2 MUST show the GM the target, complete unified diff, before measurement, after measurement, and relevant prior rulings before requesting a decision.
- **FR-020**: Measurements and budget verdicts MUST remain evidence only; no numeric result or model output MAY apply a candidate for comparison, accept and retain it, or reject and restore the prior bytes.
- **FR-021**: Gate 2 MUST require an explicit GM Accept or Reject ruling for each atomic proposal.
- **FR-022**: Acceptance MUST persist the one target edit and append an Accepted impact record; rejection MUST restore the target byte-for-byte and append a Rejected impact record.
- **FR-023**: Rejection MUST retain the confirmed wiki pattern, its evidence, and its rejection history so later runs can reason about why the skill-layer change was not adopted.
- **FR-024**: A previously rejected equivalent proposal MUST NOT recur unless the new impact entry records either an explicit GM override with rationale or at least one canonical source digest absent from the prior impact entry together with the affected rule or measured category to which that source applies. A changed path or artifact identity with an already-recorded digest MUST NOT qualify as materially new evidence.

**Deterministic harness and audit trail**

- **FR-025**: The feature MUST provide non-model command-line capabilities to collect traces, measure a corpus, validate indexes, append impact records, apply a candidate patch for comparison, accept and retain that patch, and reject and restore the prior bytes.
- **FR-026**: Repeated execution of any read-only capability against unchanged inputs MUST produce byte-identical output and ordering.
- **FR-027**: Measurement MUST use the same authoritative campaign rules and checking definitions used by the existing narration checker, without maintaining a second copied rule set.
- **FR-028**: Measurement MUST report observed value, applicable budget, and verdict for the established document-level categories: “the shape of” at most once per document, portable portrait at most once, taxonomy phrases at zero, first-person filing language in at most two sections, campaign-configured per-narrator bookkeeping caps, and no more than two narration em-dashes per document.
- **FR-029**: Measurement MUST additionally report cross-narrator convergence when an eligible sequence of three or more consecutive words appears in prose attributed to at least two narrators in the selected session.
- **FR-030**: An inapplicable or unconfigured check MUST carry its own skipped or missing-configuration reason and MUST NOT be reported as clean.
- **FR-031**: Every impact record MUST include a unique iteration/proposal identity, selected session and corpus identity, target, diff, before and after measurements, GM ruling, and any override rationale or qualifying new-evidence source-digest and affected-rule pair.
- **FR-032**: The impact ledger MUST be append-only and MUST refuse a duplicate iteration/proposal identity without modifying the file.
- **FR-033**: Candidate application for comparison, accepted retention, rejected restoration, wiki updates, and ledger appends MUST be atomic and MUST detect a target that changed after proposal creation.
- **FR-034**: Index validation MUST identify missing Problem/Root Cause/Corrective Strategy content, malformed index descriptions, missing pages, duplicate slugs, and tier collisions.

**Discoverability, parity, and isolation**

- **FR-035**: Every narration-wiki command-line capability MUST be reachable from the session UI in this feature; no deterministic verb MAY ship as an orphaned CLI capability.
- **FR-036**: The UI MUST require an explicit session and route every operation that executes command-line work through the project's established server-to-CLI subprocess seam rather than introduce a second execution path. Long-running or mutating operations MUST use the established streamed-progress contract; non-streaming responses MAY read persisted status or artifacts but MUST NOT execute engine logic. The UI MUST display the same manifest, measurements, validation results, diff, and final ruling state as the CLI.
- **FR-037**: Iteration state and outputs MUST be persisted as human-readable files discoverable by UI, CLI, and conversation; the browser MUST NOT be the sole holder of progress or rulings.
- **FR-038**: The UI MUST mechanize invocation and presentation only; it MUST NOT merge the maintainer and proposer roles, infer a Gate 1 or Gate 2 decision, or automatically advance through either checkpoint.
- **FR-039**: The narration renderer MUST never read either wiki tier, and narration produced with the wiki unavailable MUST be byte-identical to narration produced with it present when all skill-layer inputs are unchanged.

**Seeding, single-sourcing, and adoption**

- **FR-040**: Initial seeding MUST separate portable craft lessons from named-character and campaign-canon lessons. Before disputed guidance can be promoted, every conflicting source—including Phandalin's em-dash discrepancy—MUST produce a persistent conflict record containing a stable conflict ID, rule key, competing source references and digests, GM ruling, rationale, and campaign scope.
- **FR-041**: Narration skills and review checklists MUST resolve caps and rules from the selected campaign's authoritative guidance rather than retain hand-copied narrator tables or tic summaries, and deployed companion maintainer and proposer skills MUST advertise that behavior through the versioned capability manifest.
- **FR-042**: A skill running for one campaign MUST NOT surface named narrators, caps, or canon from another campaign.
- **FR-043**: The portable tier's canonical source, capability manifest, and maintainer/proposer skill changes MUST be version-controlled through the companion skill repository. CampaignGenerator MUST verify the locally deployed manifest read-only, requiring narration-wiki contract version `1`, `guidance_source: campaign-resolved`, and maintainer/proposer capabilities, and MUST report the dependency incomplete when the manifest is absent or incompatible without writing into another repository.
- **FR-044**: Operator documentation MUST place the wiki iteration in the post-session routine and explain both gates, tier routing, evidence-only measurements, rejection asymmetry, recovery behavior, and the companion-skill dependency.
- **FR-045**: Existing campaign workspaces MUST remain valid without an in-place migration; wiki state is additive and is created only through an explicit initialization or confirmed first iteration.
- **FR-046**: Every new or modified narration-wiki UI surface MUST reuse CampaignGenerator's established colors, typography, spacing, control treatments, focus states, and status conventions; it MUST NOT introduce a feature-specific visual theme.
- **FR-047**: Every narration-wiki page MUST support a 1280×720 viewport, and every resizable content panel MUST support a minimum size of 320×160. At those dimensions, each page or panel MUST provide visible vertical and, where wide content requires it, horizontal scrolling when content exceeds the available region, keeping all evidence and approval controls reachable without page breakage or clipping.

### Scope Boundaries

- This feature adds the CampaignGenerator-owned deterministic harness, command-line surface, UI parity, on-disk contracts, tests, and operator documentation.
- The model-driven maintainer and proposer live in the companion skill repository and are a declared end-to-end dependency, not files edited from this worktree.
- This feature does not auto-apply critique fixes, auto-accept patterns, auto-accept rule changes, or replace qualitative GM judgment with a score.
- This feature does not change the substance of campaign prose rules. Conflicts discovered during seeding require a separate recorded GM ruling.
- This feature does not change the Pass 5 prompt, add wiki content to narrator context, merge maintainer and proposer roles, or otherwise change the narration render path.
- This feature does not automatically backfill the 110 historical critique reports; it seeds from already distilled authoritative guidance and then processes future sessions explicitly.
- This feature does not silently migrate, rewrite, or probe multiple legacy locations for campaign state.

### Key Entities

- **Wiki Iteration**: One explicitly selected session's accumulation cycle, including its manifest, measurements, Gate 1 rulings, atomic proposals, Gate 2 rulings, and completion state.
- **Trace Manifest**: The deterministic inventory of immutable critique, narration, extraction, GM-assist, source, and generation-setting artifacts included from the selected session.
- **Wiki Pattern**: A durable, stable-slugged lesson containing one action-pattern problem, its root cause, corrective strategy, evidence references, owning tier, and GM confirmation.
- **Wiki Index Entry**: The unique lookup key and one- or two-sentence problem/root-cause/fix description that lets later proposal work distinguish related patterns.
- **Knowledge Tier**: Either portable craft knowledge shared across campaigns or knowledge owned by one campaign and versioned with its rulebook.
- **Measurement Snapshot**: A deterministic observed/budget/verdict record for the selected corpus and authoritative guidance, including explicit skipped reasons.
- **Atomic Proposal**: One proposed diff against one authorized skill-layer file, bound to its before-state and evidence.
- **Gate Ruling**: The GM's explicit decision at Gate 1 for a pattern and tier, or at Gate 2 for an atomic skill-layer change.
- **Conflict Ruling**: A persistent, campaign-scoped record of a stable conflict identity and rule key, competing source references and digests, the GM's selected resolution, and rationale.
- **Impact Ledger Entry**: An append-only record of proposal identity, target, diff, before/after measurements, GM ruling, and either an explicit override rationale or qualifying new-evidence source-digest and affected-rule pairs permitting reconsideration.
- **Companion Capability Manifest**: Locally readable, companion-owned metadata declaring its narration-wiki contract version, `campaign-resolved` guidance source, and maintainer/proposer capabilities so CampaignGenerator can verify the deployed integration without modifying the companion repository.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Collection succeeds for 100% of the three documented artifact-layout generations and refuses 100% of test paths that escape the selected campaign, without modifying any raw input.
- **SC-002**: Two measurements over identical corpus and guidance inputs are byte-identical in 100% of acceptance runs; every supported category reports observed value, budget, and verdict or an explicit skipped reason.
- **SC-003**: 100% of durable pattern pages pass the Problem/Root Cause/Corrective Strategy contract, have unique normalized slugs, carry recorded Gate 1 approval, and appear in exactly one confirmed tier.
- **SC-004**: In rejection-and-restoration acceptance testing, rejecting a proposal restores the target byte-for-byte in 100% of runs while retaining the confirmed wiki page and exactly one Rejected impact entry with its diff and measurements.
- **SC-005**: In acceptance testing, accepting and retaining a proposal changes exactly one authorized file and creates exactly one Accepted impact entry; stale, duplicate, multi-file, and unauthorized proposals create zero partial changes.
- **SC-006**: 100% of narration-wiki CLI capabilities have an equivalent UI action using the same engine, and 100% of empty-selection tests refuse to run without creating artifacts.
- **SC-007**: Removing both wiki tiers changes zero bytes of rendered narration when rulebook and voice inputs are unchanged, and no production render step lists a wiki file among its inputs.
- **SC-008**: Cross-campaign verification finds zero OOTA-only narrator names or caps delivered during a Phandalin run, while 100% of seeded portable patterns remain available to both campaign proposal workflows; 100% of deployed-companion checks refuse a missing, incompatible, or non-campaign-resolved capability manifest.
- **SC-009**: A first end-to-end exercise on the seven-critique Phandalin 20260623 session produces individually reviewable pattern drafts, records at least one intentional Gate 1 or Gate 2 rejection, and preserves that rejection so the next run does not repeat the same proposal.
- **SC-010**: In a persisted operator-usability result, active-operator timing starts when the Narration Wiki page opens with an explicitly selected session and stops when the Gate 2 ruling is persisted. The GM MUST complete collect → measure → pattern review → one atomic accept-or-reject cycle in under 15 minutes of active operator time, with total elapsed time and excluded model-response duration recorded separately, and MUST identify both approval gates and the persisted ruling without consulting implementation code.
- **SC-011**: Duplicate iteration identities, duplicate normalized slugs, malformed indexes, and missing campaign-rulebook inputs are refused in 100% of acceptance cases with actionable errors and no file changes.
- **SC-012**: The historical critique corpus receives zero automatic edits or bulk imports during rollout; all newly durable knowledge can be traced to an explicitly selected session or an explicitly approved seed source.
- **SC-013**: Visual review finds zero narration-wiki-specific color, typography, control, focus, or status styles that diverge from the existing CampaignGenerator design system without an approved accessibility reason.
- **SC-014**: At the sole supported viewport of 1280×720 and after resizing every resizable panel to its 320×160 minimum, 100% of content and approval actions remain reachable through visible horizontal or vertical scrolling as needed, with zero clipped or inaccessible controls.

## Assumptions

- The new spec directory uses the next sequential feature number, `020`, independently of issue number 358 and branch name.
- The existing per-campaign rulebook and its checker configuration remain the authoritative skill layer. OOTA already has this baseline; a campaign without it must resolve that prerequisite rather than borrow another campaign's rules.
- The portable craft tier is canonically versioned in the companion skill repository and deployed to the user's cross-campaign skill area; campaign-tier knowledge remains inside each campaign repository.
- Cross-narrator reuse initially uses the fixed issue-defined threshold of three or more consecutive words appearing in at least two narrators' eligible prose. It becomes configurable only after evidence shows one shared threshold is inadequate.
- Gate 1 is per-pattern and includes tier confirmation; Gate 2 is per atomic proposal. This is the safest default under the project's mandatory human-checkpoint doctrine.
- UI parity is in scope because the project constitution requires every new CLI capability to have a UI face unless the human explicitly exempts it; no exemption was requested.
- The companion maintainer and proposer skills may make model calls, but every output remains a draft until the corresponding GM gate. The CampaignGenerator harness itself makes no model decisions.
- Wiki and ledger artifacts are human-readable disk state. No database, daemon, or browser-only state is needed to preserve or reconstruct an iteration.
- Adding new wiki files and optional workflow state is additive and does not require a breaking-state migration.
