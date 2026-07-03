# Feature Specification: Ensemble Grounding-Doc Workflow UI

**Feature Branch**: `001-ensemble-workflow-ui`

**Created**: 2026-06-27

**Status**: Draft

**Input**: User description: "I want you to transform the docs/cli/ensemble_workflow.md into a feature that uses the UI to simplify the workflow management. Between steps of the UI, the user will interact with claude. The current feature is designed to only work against dgx and claude, I would like to have the ability to use openrouter as well. the feature should not replace the current workflow that uses anthropic. That feature assumes a model that is at least as powerful as sonnet and can be kept around until I decide to retire it."

## Overview

The ensemble grounding-doc workflow (`docs/cli/ensemble_workflow.md`) turns a campaign's chapter files into the four grounding documents (`world_state.md`, `campaign_state.md`, `party.md`, `planning.md`). It does this in stages: extract atomic facts cheaply on local hardware, bundle them into per-entity dossiers, let a human review scope, then spend metered tokens only on the final synthesis. Today the whole thing is a sequence of long, flag-heavy command-line invocations that the operator must remember and run in the right order, interleaved with manual review steps.

This feature gives the operator a **UI surface that mechanizes the sequence** — it shows where the campaign is in the pipeline, runs each mechanical step on request, and surfaces the files each step produces — while preserving the judgment steps (scope review, alias correction, diff-before-promote) as handoffs to a Claude conversation or the CLI. It also makes each LLM-bearing stage **backend-selectable**, adding OpenRouter alongside the existing local-hardware (DGX/Spark) and Anthropic (Claude) options.

The existing per-tool grounding-doc workflow on the current Grounding Docs page is **not** changed by this feature. It remains available, unmodified, until the operator chooses to retire it.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Walk the ensemble pipeline from a single UI surface (Priority: P1)

The operator opens a dedicated ensemble-workflow page for the current campaign. The page shows the pipeline as an ordered set of stages (extract → bundle → synthesize → review/promote), reflects which stages have already produced output (discovered from files on disk), and lets the operator run the mechanical step for the current stage and watch its output stream. After a step finishes, the operator can see the files it produced and move to the next stage.

**Why this priority**: This is the core value — replacing "remember the right command with the right flags, in the right order" with a guided, stateful surface. It delivers value even before OpenRouter exists, using only the backends the workflow supports today.

**Independent Test**: With a campaign that already has chapter files, an operator who has never seen the CLI can run the extraction step, see per-chapter outputs appear, run the bundling step, and reach the synthesis stage — entirely from the page, without typing a command. The page correctly shows, on reload, which stages are already complete.

**Acceptance Scenarios**:

1. **Given** a campaign workspace with chapter files and no prior ensemble run, **When** the operator opens the ensemble page, **Then** the page shows the extraction stage as the next actionable step and later stages as not-yet-started.
2. **Given** a completed extraction (per-chapter outputs exist on disk), **When** the operator reloads the page, **Then** the extraction stage is shown as complete and the bundling stage is shown as the next actionable step.
3. **Given** the operator runs a stage, **When** the underlying step emits progress, **Then** the page streams that progress live and, on completion, lists the artifacts the step wrote.
4. **Given** a stage whose outputs already exist, **When** the operator re-runs it, **Then** already-completed work is skipped (the run is resumable) and the page makes clear nothing was needlessly recomputed.

---

### User Story 2 - Choose the backend per stage, including OpenRouter (Priority: P2)

For each LLM-bearing stage — extraction/aggregation and synthesis — the operator chooses which backend runs it: local hardware (DGX/Spark), Anthropic (Claude), or OpenRouter. The choices are independent: the operator can extract on one backend and synthesize on another. OpenRouter is a new option added without removing the existing two.

**Why this priority**: It removes the workflow's hard dependency on having both a reachable local box and a Claude path. From a remote location with no local hardware, the operator can still run extraction (on OpenRouter); for synthesis, the operator can pick whichever frontier model they prefer. It builds on the stepped UI from US1.

**Independent Test**: With the local box unreachable, an operator can select OpenRouter for extraction, run it successfully, then select Claude for synthesis and complete a grounding-doc refresh — all from the page.

**Acceptance Scenarios**:

1. **Given** the ensemble page, **When** the operator views a stage that uses an LLM, **Then** they can choose among local hardware, Anthropic, and OpenRouter as the backend for that stage.
2. **Given** OpenRouter is selected for a stage, **When** the operator runs that stage, **Then** the step executes against OpenRouter and the page reports which backend and model produced the output.
3. **Given** the operator extracts on OpenRouter and synthesizes on Anthropic, **When** the full pipeline completes, **Then** each stage's artifacts record the backend that produced them.
4. **Given** a backend is unreachable or misconfigured, **When** the operator runs a stage against it, **Then** the page surfaces a clear failure (not a silent hang) and the operator can retry with a different backend without losing prior-stage output.

---

### User Story 3 - Drop to Claude or the CLI for the judgment between steps (Priority: P2)

Between mechanical steps, the pipeline has human-judgment checkpoints: reviewing the entity scope list before aggregation, correcting name aliases, and diffing a draft against the live doc before promoting it. The UI represents these as explicit gates that point the operator to do the work in a Claude conversation or at the CLI. Because every step reads and writes files, the operator can leave the UI, make the change (e.g. edit an alias map, correct a draft, promote a reviewed draft), and return to a UI that reflects the new file state — losing nothing.

**Why this priority**: This is the constitutional spine of the feature (the UI mechanizes; Claude converses). Without it the UI would either skip the precision decisions or try to absorb them — both of which break the workflow's correctness guarantees. It is P2 because US1 is usable for the mechanical steps before the gates are formalized, but the feature is not trustworthy without it.

**Independent Test**: At the scope-review gate, the operator opens the entity list, makes a scope/alias correction outside the UI, and the UI — without re-running any LLM step — reflects the corrected scope before the operator proceeds to aggregation. At the promote gate, a draft is never written to a live grounding doc by the UI itself.

**Acceptance Scenarios**:

1. **Given** extraction is complete, **When** the operator reaches the scope-review gate, **Then** the UI presents the entity/scope list for review and does not proceed to aggregation until the operator confirms.
2. **Given** the operator edits an alias map or scope input outside the UI, **When** they return, **Then** the UI reflects the updated files without having re-run any LLM step.
3. **Given** a synthesized draft exists, **When** the operator reaches the promote gate, **Then** the UI offers to compare the draft against the live document but never overwrites a live grounding document automatically.
4. **Given** any stage, **When** the operator inspects what that stage did, **Then** every input and output is a file on disk that is equally visible from the CLI and a Claude conversation.

---

### User Story 4 - Keep the existing Anthropic workflow available (Priority: P3)

The operator who prefers the current per-tool grounding-doc path (each tool re-extracting from the chapter bible, synthesized by a Claude model at least as capable as Sonnet) continues to use it exactly as before. The new ensemble page is additive.

**Why this priority**: It is a guardrail rather than new capability, but it must hold: the user explicitly wants the old path preserved until they decide to retire it.

**Independent Test**: After this feature ships, an operator runs the existing Grounding Docs page exactly as before and gets the same behavior; nothing about that path changed.

**Acceptance Scenarios**:

1. **Given** the existing Grounding Docs page, **When** the operator uses it after this feature ships, **Then** its behavior is unchanged.
2. **Given** the new ensemble page, **When** the operator navigates the app, **Then** the two workflows are clearly distinct surfaces and neither is a prerequisite for the other.

---

### Edge Cases

- **Local hardware unreachable** (intermittent network at a remote location): selecting the local backend for a stage must fail fast with a clear message, not hang silently; the operator can switch that stage to OpenRouter or Anthropic and proceed.
- **Backend produces empty output** (e.g. a reasoning model that emits only its thinking trace and no result): the stage must be reported as failed/empty, not silently recorded as complete.
- **Underpowered synthesis model**: synthesis requires a model capable of prioritizing and organizing across many dossiers. When a backend/model that cannot do this is chosen for synthesis, the operator should be warned (the workflow assumes a model at least as capable as Sonnet for synthesis).
- **Re-running a completed stage**: completed per-item work is skipped (resumable); the operator is not forced to recompute an expensive stage to make a small downstream change.
- **Operator skips a judgment gate**: the pipeline does not auto-advance past a human checkpoint; scope, alias, and promote decisions remain blocking.
- **Concurrent/duplicate runs of the same stage**: launching a stage that is already running must not corrupt shared working files.
- **A draft is promoted, then re-synthesized**: promotion is a manual, file-level act; a fresh draft never silently clobbers the live doc.
- **Mid-run backend interruption**: a long extraction interrupted partway can be resumed from its cached per-item progress rather than restarted from zero.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a dedicated UI surface, separate from the existing Grounding Docs page, that presents the ensemble grounding-doc workflow as an ordered sequence of stages (extraction, fact bundling/aggregation, synthesis of each grounding doc, review/promotion).
- **FR-002**: The system MUST derive and display each stage's completion status from the artifacts present on disk for the current campaign, so the displayed state survives a page reload and reflects work done outside the UI.
- **FR-003**: The system MUST let the operator run the mechanical step for a stage from the UI and MUST stream that step's progress and output to the page in real time.
- **FR-004**: The system MUST list the artifacts (files) a stage produced after it completes, and those artifacts MUST be the same files the CLI and a Claude conversation can read.
- **FR-005**: Re-running a stage MUST reuse already-completed work where the underlying step supports resumption, and MUST NOT silently recompute completed items.
- **FR-006**: For each LLM-bearing stage (extraction/aggregation and synthesis), the system MUST let the operator choose the backend independently from: local hardware (DGX/Spark), Anthropic (Claude), and OpenRouter.
- **FR-007**: The system MUST support OpenRouter as a backend for both the extraction/aggregation stage and the synthesis stage.
- **FR-008**: The system MUST record, with each stage's output, which backend and model produced it.
- **FR-009**: The system MUST surface backend failures (unreachable endpoint, auth/config error, empty result) as explicit, actionable errors and MUST allow retrying a failed stage with a different backend without discarding prior-stage output.
- **FR-010**: The system MUST represent the workflow's human-judgment checkpoints — scope/entity review before aggregation, name-alias correction, and diff-before-promote — as explicit gates that block automatic advancement of the pipeline.
- **FR-011**: The system MUST NOT perform a precision decision (scope, ordering, attribution) on the operator's behalf, and MUST NOT feed one LLM stage's unreviewed output into the next across a checkpoint without operator confirmation.
- **FR-012**: The system MUST allow the operator to perform any checkpoint's judgment work in a Claude conversation or at the CLI and then continue in the UI, with the UI reflecting the resulting file changes without re-running an LLM step.
- **FR-013**: The system MUST write synthesis results to draft artifacts only, and MUST NOT automatically overwrite a live grounding document; promotion of a draft to a live document is an explicit, operator-initiated act.
- **FR-014**: The system MUST warn the operator when a backend/model selected for the synthesis stage is below the capability the workflow assumes (a model at least as capable as Sonnet), since underpowered synthesis silently degrades the result.
- **FR-015**: The system MUST leave the existing per-tool Anthropic grounding-doc workflow (the current Grounding Docs page) functionally unchanged and independently usable.
- **FR-016**: Every step in the new workflow MUST be expressible and runnable equivalently from the CLI; the UI MUST NOT be the only way to perform any step.
- **FR-017**: The system MUST NOT hold pipeline state that exists only in the browser; if a step produced something, it produced a file that is the source of truth for that state.
- **FR-018**: OpenRouter backend configuration (credentials/endpoint/model selection) MUST be supplied through the system's existing configuration mechanism, not hard-coded, and MUST be selectable per stage at run time.

### Key Entities *(include if data involved)*

- **Pipeline state**: the current campaign's position in the ensemble workflow, derived entirely from which stage artifacts exist on disk; not stored in the browser.
- **Stage**: one step in the ordered workflow (extraction, bundling/aggregation, per-doc synthesis, review/promotion), with a completion status, the artifacts it produces, and — for LLM-bearing stages — a selected backend.
- **Backend profile**: a selectable execution target for an LLM-bearing stage — local hardware (DGX/Spark), Anthropic (Claude), or OpenRouter — including the model used and any reachability/config it needs.
- **Checkpoint / gate**: a human-judgment point between stages (scope review, alias correction, diff-before-promote) that blocks automatic advancement and is satisfied via Claude/CLI.
- **Artifact**: a file on disk produced or consumed by a stage (per-chapter facts, merged facts, per-entity dossiers, draft grounding docs, live grounding docs); the unit of interchange between UI, CLI, and Claude.
- **Grounding document (draft / live)**: the four target docs (`world_state`, `campaign_state`, `party`, `planning`); the workflow writes drafts and the operator promotes them to live docs.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can run a full grounding-doc refresh through the ensemble page — from chapter files to four reviewed drafts — without typing a single command-line invocation.
- **SC-002**: An operator who has not memorized the workflow can identify the correct next step and run it without consulting `docs/cli/ensemble_workflow.md`, in their first session with the page.
- **SC-003**: With local hardware unreachable, an operator can still complete a full grounding-doc refresh by selecting OpenRouter (and/or Anthropic) for the LLM-bearing stages.
- **SC-004**: The metered-token cost of a full refresh through the UI is no higher than the same refresh run from the CLI today (i.e. extraction stays off the metered API when a local or OpenRouter open-model backend is chosen; only synthesis spends frontier tokens).
- **SC-005**: No live grounding document is ever modified by the workflow without an explicit operator promotion action — measured as zero automatic overwrites of live docs across all runs.
- **SC-006**: The existing per-tool Anthropic workflow produces identical results before and after this feature ships (no regression).
- **SC-007**: After any stage runs, 100% of its inputs and outputs are files visible from the CLI; no pipeline state is recoverable only from the browser.
- **SC-008**: For every LLM-bearing stage, the operator can independently select among at least three backends (local, Anthropic, OpenRouter), and the produced artifact records which one was used.

## Assumptions

- **Per-stage backend choice across both LLM stages** (from clarification): OpenRouter is selectable independently for extraction/aggregation and for synthesis; the operator may mix backends across stages (e.g. extract on OpenRouter, synthesize on Anthropic).
- **New separate UI surface** (from clarification): the ensemble workflow lives on its own page/section; the existing Grounding Docs page is left in place and unchanged.
- **Single operator, local-first**: the UI serves one GM on their own workstation; multi-user concurrency and access control are out of scope.
- **Campaign workspace already exists**: the operator runs the page from within a campaign workspace that has chapter files (or the documented inputs); creating the workspace and preparing chapters is out of scope for this feature.
- **Spelling/known-names/alias preparation remains a documented prerequisite**: this feature mechanizes the pipeline stages and their gates; it does not replace the upstream proper-noun consistency pass, which the operator performs as today.
- **Synthesis assumes a capable model**: the synthesis stage assumes a model at least as capable as Sonnet; weaker open models may be fine for extraction/aggregation but are expected to underperform on synthesis, and the UI warns rather than blocks.
- **Long-running stages**: extraction can take tens of minutes; the UI is expected to handle a long-running step (progress, resumability) rather than assume sub-second responses.
- **Existing configuration mechanism is reused**: backend endpoints, models, and credentials (including OpenRouter) are provided through the project's existing configuration files/UI rather than a new bespoke store.
- **Files are the contract**: all interchange between the UI, the CLI, and Claude conversations happens through files on disk; the UI never becomes the sole holder of workflow state.

## Out of Scope

- Replacing, modifying, or retiring the existing per-tool Anthropic grounding-doc workflow.
- Running the synthesis stages on local/open models as the *primary* path (the "all-Spark synthesis" and "per-section fan-out" ideas in the workflow doc remain future exploration, not part of this feature).
- Automating the human-judgment checkpoints (scope, alias, promotion) — these are deliberately preserved as human decisions.
- Multi-user, remote-hosted, or access-controlled deployment of the UI.
- Creating campaign workspaces, preparing chapter files, or running the upstream spelling/known-names preparation passes.
