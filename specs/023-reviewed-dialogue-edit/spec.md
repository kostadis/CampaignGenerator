# Feature Specification: Dialogue Edit Skill

**Feature Branch**: `kostadis/narration-v1`

**Created**: 2026-09-06

**Status**: Skill implemented; GM editorial acceptance trials pending

**Input**: "issue CG487 and Campaigns#232", refined by the GM: "a skill is better tuned like the ones we have for $no-mech, $staged-consistency than a feature in CG."

**Delivery**: A Codex skill named `dialogue-edit`, maintained alongside the supplied Codex skills. The CG checkout holds this design document; the deliverable belongs to the skills collection.

**Generation rollout**: The GM subsequently requested the accepted narration-v1 prompt for all campaigns. The shared CG narration templates now implement that separate upstream change. The skill itself remains an editing pass after UI narration; see [SkillPipelineOrder.md](../../docs/design/SkillPipelineOrder.md).

**Source resolution**: This draft uses [CampaignGenerator #387](https://github.com/kostadis/CampaignGenerator/issues/387), identified by the earlier user context and [Campaigns PR #232](https://github.com/kostadis/campaigns/pull/232). #487 could not be found during the initial specification. The issue supplies editorial evidence and safeguards; the GM's later instruction determines delivery as a skill.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Read the right scene with its established voice (Priority: P1)

As a GM, I can ask for dialogue editing of existing narration. The skill inventories my selected scenes, resolves their reviewed extractions and declared voices, reads campaign rulings, and reads each complete scene before proposing edits.

**Why this priority**: The difficult work is recognizing what a line does in its scene. Keyword scans and quote similarity cannot decide whether hesitation, repetition, or an odd phrase is part of the performance.

**Independent Test**: Invoke the skill on a frozen scene with its reviewed extraction and references. Confirm the selected files and existing rulings are identified, every part of the scene is read, and missing evidence is reported without changing source material.

**Acceptance Scenarios**:

1. **Given** selected narration and known source mappings, **When** the skill starts, **Then** it reports the exact scene, narrator, extraction layer, declared voices, and applicable campaign rules before proposing changes.
2. **Given** missing narration, a missing declared voice, or an ambiguous source mapping, **When** inventory runs, **Then** the affected scene is marked blocked or not run; the skill does not generate missing artifacts or guess an identity.
3. **Given** clear mappings and standing rulings already recorded, **When** the skill resolves inputs, **Then** it uses those records without asking the GM to reconfirm settled choices. Conflicting or materially changed evidence is raised explicitly.
4. **Given** few or no pattern matches, **When** a scene is reviewed, **Then** the skill still reads the full scene and its source. A scan result is not a finding of editorial quality.
5. **Given** several possible sessions or an empty selection, **When** no current instruction resolves the scope, **Then** the skill asks for the missing selection rather than choosing all scenes.

---

### User Story 2 - Rule on exact dialogue changes, one scene at a time (Priority: P1)

As a GM, I receive a short, evidence-backed set of proposed changes for one scene. I can see the original words, replacement words, surrounding exchange, and the reason for the change. I decide whether the edit preserves the player's voice.

**Why this priority**: A line can retain its words and meaning while losing its cadence. The GM checkpoint is the editorial control that catches that failure.

**Independent Test**: Use the Zenvon, Vukradin, and Valphine archive cases to produce proposals and review them against full scenes and sources. Check the protected conditions below, including cases that should stay unchanged.

**Acceptance Scenarios**:

1. **Given** Vukradin's tide calculation, **When** the skill proposes removing accidental duplication, **Then** the proposal retains the wrong first answer, self-correction, final emphasis, and sincere surrounding commentary.
2. **Given** Zenvon's “more effort. For the same output.” and “At the ravine?”, **When** the skill proposes edits, **Then** the separate landing and confirmatory intent remain.
3. **Given** ambiguous “over. Yeah” radio-play wording, **When** the skill cannot establish that it is empty filler, **Then** it leaves it intact or presents that uncertainty as its own ruling, outside any larger cleanup approval.
4. **Given** two speakers agreeing with “Yes” or expressive repeated speech, **When** duplication is considered, **Then** their separate contributions and conversational intent determine the proposal.
5. **Given** a scene with no justified edits, **When** reading completes, **Then** the skill records no changes needed and continues within the selected scope without manufacturing an approval question.
6. **Given** an existing scene review with unresolved proposals, **When** the skill reaches its checkpoint, **Then** it waits for the GM's ruling before applying or advancing that scene's edit workflow.

---

### User Story 3 - Apply exactly what was approved (Priority: P1)

As a GM, I can approve exact changes in chat or through the existing standalone review page. The skill applies those changes to a separate narration revision, preserves the original, and keeps a durable record of my decisions.

**Why this priority**: Approval of one passage must not authorize a new rewrite or a neighboring fix the GM never saw.

**Independent Test**: Start with a saved proposal set, record mixed decisions, and apply the approved subset. Repeat with a stale file, altered replacement text, overlapping proposals, and mismatched decision identities.

**Acceptance Scenarios**:

1. **Given** approved, rejected, discussed, and unmarked proposals, **When** application runs, **Then** only approved exact replacements appear in the derived revision; every other passage keeps its original wording.
2. **Given** changed source content, proposal text, or ambiguous locations, **When** application is attempted, **Then** it refuses the affected scene without partial replacement and asks for updated review.
3. **Given** a review page exists or has been opened, **When** no explicit decisions have returned, **Then** the skill applies nothing. In page mode only pasted or saved decision output authorizes the page's edits.
4. **Given** returned decisions, **When** they are read, **Then** their run identity, item identities, verdicts, and linkage to the exact proposals are checked. Discussed items return to chat; unmarked items stay unresolved.
5. **Given** application exposes an orphaned reply or a damaged neighboring exchange, **When** the skill reads the result, **Then** it brings that defect as a new proposal rather than silently extending the earlier ruling.
6. **Given** a candidate or an approved derived revision, **When** the skill finishes, **Then** it identifies the output and its status without assembling, publishing, or replacing the selected original narration.

---

### User Story 4 - Resume and retain campaign-specific lessons (Priority: P2)

As a GM, I can resume an interrupted review from saved evidence and decisions. I get a final account of what changed, what remains unresolved, and whether neighboring scenes still join correctly.

**Why this priority**: The useful tuning comes from actual campaign rulings and known failure cases, and it must survive beyond one conversation.

**Independent Test**: Resume from saved proposals and mixed decisions, verify their freshness, inspect adjacent scene boundaries, and reconcile the final report with the selected scene list.

**Acceptance Scenarios**:

1. **Given** an interrupted run with saved rulings, **When** it resumes, **Then** valid decisions are reused without asking again and stale ones are identified before application.
2. **Given** an edited scene with a repeated or quoted boundary echo, **When** the skill checks its joins with neighboring scenes, **Then** it reports any defect and changes no neighboring scene without a separate ruling.
3. **Given** a new ruling with possible future relevance, **When** the run is recorded, **Then** the session manifest records it with its scope; promotion into shared campaign policy requires approval of the destination and wording unless already authorized.
4. **Given** a source omission such as the inherited pike/bike interaction loss, **When** dialogue review encounters it, **Then** it records an upstream or coverage-review carry-forward rather than inventing the missing exchange.
5. **Given** blocked, unchanged, partially approved, or unreviewed scenes, **When** the final report is produced, **Then** each status remains distinct and no unrun scene is reported as passed.

### Edge Cases

- The GM is also a player or an NPC is voiced under a GM label: read attribution and stage directions; labels alone do not decide whether speech is expendable.
- Duplicate words appear within a single quotation rather than across quotations: read the whole utterance and its correction structure.
- A proposed completion is plausible but unsupported: leave the text and raise the uncertainty; character references are not evidence of a new event or line.
- A necessary attribution adjustment overlaps another proposal: make the dependency visible and request a coherent ruling before application.
- Inputs or approved wording change after review: require renewed review for the affected scene instead of applying by approximate match.
- A destination already contains a prior result: retain it and select a new run/revision identity.
- A page export contains foreign or missing identities: refuse invalid decisions; missing decisions are unresolved.
- Narration is absent: report that dialogue editing was not run; do not invoke narration to fill the gap.
- An input is accessible through a link to a protected source file: write guards apply to the resolved destination as well as the supplied path.
- A clean scene needs no work: record that result without an edit quota.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Deliver the workflow as a Codex skill invoked for existing narration, with `$dialogue-edit <session-or-scene-path>` as its proposed name and invocation. The skill owns reading, proposals, review checkpoints, and recording outcomes. A new CG command, application stage, configuration service, or Session Doc Editor feature is outside scope.
- **FR-002**: Inventory the explicitly selected scene set and its exact reviewed sources, declared narrator/supporting voice references, and applicable register rules before editing. Resolve clear mappings from existing evidence; ask only when identity or scope is unresolved. Never infer all scenes from an empty selection or create missing pipeline artifacts.
- **FR-003**: Read the complete selected scene, relevant complete extraction, declared voice references, and applicable standing rulings before proposing edits. Deterministic scans may highlight candidates but MUST NOT classify speech or establish that a scene is clean.
- **FR-004**: Apply the editorial permissions of archived approach B and its common brief, strengthened by the cadence findings: allow the smallest source-supported dialogue change while preserving characteristic words, humor, uncertainty, pauses, emphatic landings, and self-corrections.
- **FR-005**: Preserve descriptive and inner prose except for necessary adjacent attribution or punctuation changes, which MUST be separately visible. Preserve speaker identity, scene order, remote communication, knowledge boundaries, meaningful repetition, and proposed-versus-completed action.
- **FR-006**: Preserve comprehensible ESL diction, campaign vocabulary, and separate speakers' contributions. Ambiguous filler, acknowledgments, or repetition MUST be left unchanged or explicitly presented for a ruling, never bundled into a larger cleanup decision.
- **FR-007**: The active Codex conversation performs the reading and proposes exact edits. A separate generation backend or a full-scene model rewrite MUST NOT be required. Deterministic inventory, comparison, and application helpers make no model calls; the editorial reading itself is model work and MUST NOT be described as deterministic or free of model use.
- **FR-008**: Save each proposal with a stable identity, exact original and replacement text, target location, relevant conversational context, supporting source/reference anchors, and the reason or unresolved question. Any complete candidate shown for context MUST be the original plus these recorded proposals, with no hidden additional edits.
- **FR-009**: Present one scene's proposals at a time, with independent rulings for distinct editorial choices. Ask whether to use chat or the existing shared standalone review page at the start of a run unless the GM has already chosen for that run. A batch page covers one scene; it does not authorize a blanket session cleanup.
- **FR-010**: Reuse the shared review-page contract for page mode. Validate returned run/item identities, verdicts, and exact proposal linkage. Apply only explicit approvals; rejected proposals leave text unchanged, discussed proposals return to chat, and unmarked proposals stay unresolved. Page existence, browser state, and modification times are never approval.
- **FR-011**: Apply only exact approved replacements, without model rewriting, after checking original/source/reference content identities, proposal identity, and exact locations. Refuse stale, conflicting, ambiguous, or unsupported application before changing the affected scene. Approval of an unsupported guess does not establish evidence.
- **FR-012**: Preserve VTT files, every extraction layer, voice and policy references, and original narration. Write candidates and approved revisions only to explicitly selected derived narration destinations outside inputs and active assembly selection. Preserve completed outputs. Any helper that writes text MUST enforce these boundaries on resolved paths.
- **FR-013**: Read the applied scene and its joins with adjacent scenes to check for orphaned replies, lost setups, repeated boundary sentences, and narration rendered as quoted dialogue. Newly discovered repairs require their own proposal; previous approval does not extend to neighboring text.
- **FR-014**: Save a session-local sources-and-rulings manifest containing the selected scenes, exact input/proposal/output identities, skill version, decisions, applied changes, untouched originals, run statuses, seam findings, and scoped carry-forward items. Record chat decisions on disk and revalidate saved evidence when resuming.
- **FR-015**: Read existing campaign rulings before re-proposing settled choices and reuse still-valid decisions. Record new rulings with their actual scope. Amend shared campaign policy only when the exact destination and wording are authorized; never generalize one scene's ruling into a universal rule.
- **FR-016**: End with per-scene read/review/apply status, changes applied, rejected/discussed/unresolved proposals, blocked or not-run scenes, output paths, seam results, and carry-forward. No-edit, unreviewed, failed, and approved outcomes MUST remain distinguishable.
- **FR-017**: Treat upstream transcription, identity, canon, missing-content, and broad prose problems as carry-forward to the appropriate existing workflow. This skill performs no automatic re-narration, extraction repair, approach A/B/C stacking, assembly, or publication. An additional remote generation or re-narration run requires user authorization covering its scope and backend; reuse that authorization when already given.
- **FR-018**: Keep runtime provenance honest: record the active skill and observable execution context; explicitly mark model details unavailable when not exposed. Separate runner experiments, if requested, retain their complete submitted messages and actual reported execution identity, and preserve failures rather than silently switching providers. Do not fabricate a full prompt snapshot for the active Codex conversation.
- **FR-019**: Validate the skill against all three archived cases and preserve complete proposals, review outcomes, and failed attempts. Evaluate whether its review process catches the known cadence and uncertainty errors, including refusing unapproved edits. Automated helper checks establish file/decision integrity only, not editorial quality.
- **FR-020**: Keep the skill entrypoint focused on routing, editorial judgment, and the review/apply boundaries. Put substantial experiment lessons in supporting references and add deterministic helpers only for repeated, fragile operations such as exact application and freshness checks. Reuse the shared review machinery; no new review platform or CG migration is required.

### Key Entities *(include if feature involves data)*

- **Scene evidence**: The selected original narration, exact reviewed extraction, declared voices, and applicable campaign rulings.
- **Edit proposal**: An exact replacement with its location, context, source support, reason, and stable identity.
- **Scene review**: The presented proposal set and explicit decisions returned in chat or through the shared page.
- **Derived revision**: The original scene plus only approved replacements, retained separately from its source.
- **Sources-and-rulings manifest**: Durable selected scope, evidence identities, decisions, application outcomes, seam checks, and unresolved work.
- **Campaign ruling**: A scoped human decision that may guide future reviews; a session decision does not automatically amend campaign-wide policy.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every selected scene is either read in full with its required evidence or explicitly marked blocked/not run. Every missing-input or ambiguous-mapping case is surfaced before edits; zero source files change during inventory or proposal work.
- **SC-002**: The three archived cases exercise every protected condition below. Review identifies the known lost-cadence and changed-question proposals as unacceptable, preserves useful source-supported Vukradin cleanup, and records no accepted violation of source meaning or player voice.
- **SC-003**: Every proposed wording change is visible to the GM with exact before/after text and evidence or an explicit unresolved question. Zero unapproved, unsupported, or hidden changes appear in an applied revision.
- **SC-004**: Mixed-decision application preserves original/rejected/discussed/unmarked text and produces exactly the approved subset. All stale, altered-proposal, invalid-decision, overlapping-conflict, and protected-destination cases refuse the affected application without a partial scene write.
- **SC-005**: Chat and page review lead to equivalent approved text for the same proposal set. Resuming a saved review loses zero decisions, accepts no stale approval, and requires no browser-only state.
- **SC-006**: Every completed run reports statuses for the entire selected scene set, records seam findings and unresolved items, and preserves the original narration. No automatic narration, assembly, publication, or additional backend call occurs.
- **SC-007**: All three regression reviews retain complete proposals and GM outcomes; helper validation and historical experiment results are reported separately from editorial judgments. The skill can complete the normal workflow without a new CG application capability.

### Protected Regression Conditions

| Case | Required preservation or review outcome |
| --- | --- |
| Zenvon — Obelisk scene 1, Arrival at Wyvern Tor | Preserve the mage-hand sentence landing, ravine confirmation, comprehensible ESL diction, unknown enemy count/distances, and planned-versus-completed movement. |
| Vukradin — Phandalin scene 1, Patrons of the Common Chord | Clarify Valphine's unfinished question only from the extraction's explicit meaning; preserve the tide calculation's wrong answer, correction, and emphasis; retain studio/charity perspective, Old Hesp reflection, and expressive “We're gonna get it back” repetition. |
| Valphine — Phandalin scene 2, The Ninth Crate Disappears | Retain or flag ambiguous radio-play wording; preserve separate speakers' agreement, analytical inner voice, final magical-disinterest exchange, Sending Stone knowledge boundary, unknown spell, and memory-versus-willingness distinction. |
| All cases | No invented lines, jokes, facts, guessed speakers, removed meaningful exchanges, unsupported completions, vocabulary normalization, obligatory shortening, or edit quota. |
| Known coverage limitation | Carry the inherited pike/bike misunderstanding to separate source-coverage review; do not claim dialogue editing repaired the interaction. |

## Assumptions

- This revision changes the specification only. Building and installing the skill is the subsequent implementation task.
- The proposed source home is `~/src/mytools/dotfiles/codex/skills/dialogue-edit/`, following the supplied sibling skills; discoverability follows the existing `~/.codex/skills/` arrangement. The Claude skill collection is outside this deliverable.
- The skill runs after narration, using reviewed source extractions as evidence. `voice-smooth` edits the upstream derived extraction layer; `no-mech` removes table mechanics before narration; `staged-consistency` checks pipeline boundaries. None is implicitly run or modified by dialogue editing.
- Approach B supplies editorial guidance, not a requirement to reproduce the old runner. A/C remain archived alternatives. The accepted v1 narration drafts remain the comparison baseline; production prompt adoption is separate from the skill and was subsequently authorized in the generation rollout above.
- Historical Phandalin trials used selected perspective sections and local generic-instruction adjustments; Obelisk used full declared voices and register policy. A skill review must record the references actually read and not claim equivalence to those original submissions. The old gpt-6-astra/medium setting identifies historical evidence and is not a required backend for the skill.
- #369 is related review work, not a prerequisite for this skill: the existing shared review page supplies batch adjudication. #368 informs register protections; #386 identifies the separate coverage-review concern.
- **Constitution IV justification**: #387 and the requested skill concern limited paraphrase in labeled derived narration. Edited prose is not a verbatim transcript or replacement source quotation. Original records remain exact, evidence is required, and the GM rules on each change. This does not relax extraction or quotation-verification rules.
- **Delivery ruling for Constitution VI/XI**: On 2026-09-06 the GM selected a skill “than a feature in CG,” citing no-mech and staged-consistency. Consequently this design requires no CG CLI/UI feature or parity work. The shared standalone page remains an optional skill review surface. Any later CG application addition is a separate scope decision.
- The source issue-number assumption remains documented; this change does not alter GitHub issues or imply that #387 has been implemented.

## Intended Skill Workflow

1. **Inventory** the selected narration and exact source/reference files; read campaign rulings and resolve only genuine gaps.
2. **Read and propose** against one full scene. Save exact edits, surrounding exchange, evidence, and uncertainty; do not change narration yet.
3. **GM review** in chat or one shared page for that scene. Wait for the actual rulings. A changed proposal returns for review.
4. **Apply** the approved exact replacements to a derived narration revision after freshness and destination checks; preserve the original.
5. **Read the result and scene joins**. Bring newly discovered defects as new proposals.
6. **Record and continue** through the selected scenes, retaining decisions, explicit unresolved work, and campaign-specific lessons.

The skill does the interpretive reading and proposing. Deterministic helpers handle bookkeeping and exact approved transformations. Neither a scan nor a successful helper run supplies the GM's editorial judgment.

## Evidence and Dependencies

- [CampaignGenerator #387](https://github.com/kostadis/CampaignGenerator/issues/387) and [Campaigns PR #232](https://github.com/kostadis/campaigns/pull/232): original recommendation and experiment handoff, read during the initial specification. The GM's later skill-delivery instruction supersedes the issue's proposed application packaging.
- [Pinned archive README](https://github.com/kostadis/campaigns/blob/0355cdd28179650cf11ecb4435e4841fbe61d54c/experiments/sd-narrate/README.md) and [dialogue review](https://github.com/kostadis/campaigns/blob/0355cdd28179650cf11ecb4435e4841fbe61d54c/experiments/sd-narrate/dialogue-edit-tests/review.md): nine independent A/B/C calls and concrete editorial lessons; limited qualitative evidence, not a reliability guarantee.
- [Consolidation verification](https://github.com/kostadis/campaigns/blob/0355cdd28179650cf11ecb4435e4841fbe61d54c/experiments/sd-narrate/VERIFICATION.md): 17 historical helper tests and nine prompt/baseline reconstructions. No new tests or model trials are implied by citing them. Ten historical runner-version checks remain explicitly unavailable.
- [no-mech skill](/home/kostadis/src/mytools/dotfiles/codex/skills/no-mech/SKILL.md): full reading, per-scene GM rulings, deterministic application, orphan/seam checks, and scoped campaign lessons.
- [staged-consistency skill](/home/kostadis/src/mytools/dotfiles/codex/skills/staged-consistency/SKILL.md): explicit stage gates, truthful not-run states, durable manifests, and review-page decisions.
- [Shared review-page contract](/home/kostadis/src/mytools/dotfiles/codex/skills/_shared/review-page/CONTRACT.md): page input/output, decision identity, and no inferred approval.
- [Constitution](../../.specify/memory/constitution.md): thirteen principles assessed in the accompanying quality checklist.
