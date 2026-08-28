# Feature Specification: Codex CLI Parity Across CLIs

**Feature Branch**: `codex-cli-toolchain`

**Created**: 2026-08-27

**Status**: Draft

**Input**: User description: "we just implemented a feature that was checked in here https://github.com/kostadis/CampaignGenerator/pull/350 and as a speckit feature (#15), I want to implement this across all CLIs"

**Reference behavior**: [CampaignGenerator PR #350](https://github.com/kostadis/CampaignGenerator/pull/350) and its `015-codex-cli-backend` specification define the shipped `codex-cli` subscription backend. That feature certifies the consistency auditor only; this feature extends the same subscription-backed behavior to the complete production CLI family.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run Any CampaignGenerator CLI with a Codex Subscription (Priority: P1)

A GM who is signed in to Codex wants to choose `codex-cli` on any CampaignGenerator command that performs or dispatches language-model work. The command completes its established job using the saved subscription login, without requiring a metered API key and without silently switching providers.

**Why this priority**: This is the feature's core value. The existing backend is visible in the shared vocabulary but is certified only for one auditor, leaving every other command as an unreliable dialect of the same option.

**Independent Test**: With Codex authenticated and metered API-key variables absent, invoke one command from each scoped CLI family with `--backend codex-cli`, including a direct command and a dispatcher. Confirm that each produces its normal output and that every dispatched model operation remains on the selected backend.

**Acceptance Scenarios**:

1. **Given** any direct model-bearing CLI in the scope inventory and valid inputs, **When** the GM selects `--backend codex-cli`, **Then** the command produces the same kind of output it produces through its existing supported backends using the saved Codex login.
2. **Given** an orchestration or dispatcher CLI, **When** the GM selects `codex-cli`, **Then** the selection, compatible model intent, and relevant execution controls reach every child operation without reverting to another backend.
3. **Given** no Anthropic, OpenAI, or Codex API key in the environment, **When** an authenticated subscription run is performed, **Then** it can complete successfully without asking for a metered credential.
4. **Given** a missing executable, unavailable login, incompatible model, timeout, failed child, or empty result, **When** any scoped command runs, **Then** it fails clearly and makes zero fallback attempts.

---

### User Story 2 - Preserve Each Workflow's Established Contract (Priority: P1)

A GM expects changing only the backend to leave the selected files, prompt material, stage order, caching, resume behavior, output locations, and human-review checkpoints unchanged. Multi-stage generation and fan-out workflows still perform the same explicit units of work; completed artifacts remain discoverable on disk.

**Why this priority**: Backend parity is unsafe if it changes scope or bypasses a checkpoint. Campaign artifacts and their review boundaries are more important than provider convenience.

**Independent Test**: For representative fixtures from the session-document, grounding, preparation, search, content-ingest, Scabard, and ensemble families, compare a baseline run's assembled request boundaries and filesystem outcomes with a `codex-cli` run. Confirm identical selected inputs, ordering, stage boundaries, skip/resume decisions, and output destinations.

**Acceptance Scenarios**:

1. **Given** a command's document, configuration, explicit context, and selected units, **When** it runs through `codex-cli`, **Then** the same material reaches the model in the same order and with the same instruction-versus-user-content priority as on the command's normal live path.
2. **Given** a multi-stage workflow with a human checkpoint, **When** a stage completes through `codex-cli`, **Then** its artifact is written to the normal location and no later precision stage runs unless the existing workflow would have run it.
3. **Given** cached, skipped, or already-completed units, **When** a subscription run resumes, **Then** the existing reuse and refusal rules remain unchanged and no additional model work is manufactured.
4. **Given** a fan-out workflow with explicit inputs, endpoints, concurrency, retries, or unit time limits, **When** `codex-cli` is selected, **Then** the workflow preserves its explicit work set and completion semantics while applying the selected backend to every model-bearing unit.
5. **Given** a successful command, **When** its result is returned, **Then** existing terminal presentation, issue or item counting, file naming, logs, and downstream file-based workflows remain compatible.

---

### User Story 3 - Support the Existing Interaction Shapes Safely (Priority: P1)

Most CampaignGenerator commands make one or more text-generation requests. The ensemble polish command additionally uses an application-controlled critique and edit loop. A GM needs both shapes to work through the subscription backend without granting the Codex child general file, shell, web, plugin, or delegation access.

**Why this priority**: Claiming support for all CLIs while rejecting the polish workflow's established interaction shape would leave the most important scope promise false. Allowing unrestricted executable tools would violate the isolation promise inherited from feature 015.

**Independent Test**: Exercise single-turn, sequential, batched-scene, streaming-shaped, multi-turn text, and polish critique/edit fixtures. Confirm normal outputs, preserved message roles and text blocks, and—where the application brokers a polish action—acceptance of only the command's existing named, validated operations against its explicitly selected documents.

**Acceptance Scenarios**:

1. **Given** a single-turn text request, **When** it runs through `codex-cli`, **Then** system instructions and user material remain distinct and the complete non-empty response is returned through the caller's existing response path.
2. **Given** a command that makes several sequential or independent requests, **When** it uses `codex-cli`, **Then** every request receives the context and prior application result that the workflow normally supplies, without exposing unrelated repository context.
3. **Given** the polish critique/edit loop, **When** the model requests an existing polish operation, **Then** the application validates and performs only that declared operation within the explicit document scope and returns its result to the next model turn.
4. **Given** a malformed, undeclared, ambiguous, or out-of-scope polish operation, **When** it is requested, **Then** the application refuses it without expanding filesystem access or treating it as a successful edit.
5. **Given** any subscription child execution, **When** it starts, **Then** the child itself has no general-purpose executable tools, write access, web access, external extensions, or subagent capability.
6. **Given** content shapes unused by the current production CLI inventory, such as images or arbitrary external tools, **When** they are submitted directly to the shared backend, **Then** they remain clearly unsupported rather than being approximated silently.

---

### User Story 4 - Choose Codex Consistently in the CLI and UI (Priority: P2)

A GM sees one spelling, meaning, default behavior, and model-resolution rule for `codex-cli` everywhere. Every scoped capability is reachable from a UI invocation, and every UI launch forwards the same explicit selection the equivalent command line would use.

**Why this priority**: A backend that works only when typed manually is still an orphaned capability for UI-driven workflows, and inconsistent model inheritance can turn a harmless provider switch into a confusing refusal.

**Independent Test**: Inspect every shared CLI registrar, hand-written dispatcher, server-side command builder, backend selector, and direct or transitive capability face. Select `codex-cli` from each applicable UI surface and confirm the launched command contains the same backend and model intent as an equivalent manual invocation.

**Acceptance Scenarios**:

1. **Given** any scoped command's help output, **When** the GM inspects backend choices, **Then** `codex-cli` appears once with a consistent subscription-oriented description.
2. **Given** a scoped CLI capability, **When** the GM reaches it through its direct or owning workflow UI face and selects the Codex backend, **Then** the selection is persisted at the existing owning configuration boundary and forwarded to the CLI without a hard-coded provider override.
3. **Given** no explicit compatible Codex model, **When** a subscription run starts, **Then** an inherited Claude model is not forwarded and Codex uses its Codex-specific or subscription default.
4. **Given** a compatible model explicitly selected for the active Codex backend, **When** a run starts, **Then** that model is used consistently by direct and UI-launched invocations.
5. **Given** the GM switches among backends, **When** they return to `codex-cli`, **Then** any existing backend-specific model memory remains separate from other providers' model choices.

---

### User Story 5 - Keep Provider-Specific Controls Honest (Priority: P2)

A GM can tell which controls apply to the subscription backend. Provider message batching remains Anthropic-only, while application-level grouping, local dispatch, resume, and review workflows retain their separate meanings.

**Why this priority**: CampaignGenerator has several unrelated uses of the word “batch.” Mixing them could cause unexpected cost, scope, or concurrency behavior.

**Independent Test**: Combine `codex-cli` with provider message batching, batched scene extraction, local ensemble dispatch, and HTML report review in separate tests. Confirm only provider message batching is refused and all application-level workflows preserve their existing contracts.

**Acceptance Scenarios**:

1. **Given** `--batch` and `--backend codex-cli`, **When** any scoped command is validated, **Then** it refuses before model work begins and explains that provider message batching is Anthropic-only.
2. **Given** `--batch-scenes` or another application-level grouping mode that is already backend-independent, **When** it runs through `codex-cli`, **Then** grouping and output ceilings retain their existing meaning.
3. **Given** `ensemble_batch`, local fan-out, or staged HTML review, **When** `codex-cli` is used in the model-bearing portion, **Then** those workflows remain distinct from provider message batching.
4. **Given** an execution timeout, **When** a child exceeds the configured positive duration, **Then** it is stopped, temporary campaign material is removed, and the error names the exceeded limit.

### Edge Cases

- **Shared vocabulary but no model work.** A dispatcher accepts and forwards `codex-cli`; it does not start an unnecessary child merely to validate the choice.
- **Inherited Claude model.** A provider-incompatible ambient default is omitted, while an explicitly chosen incompatible model produces a clear refusal.
- **Empty Codex-specific model.** It is treated as unset and leaves the subscription default in control.
- **Mixed child outcomes in a fan-out.** Existing successful artifacts remain governed by the workflow's resume rules, failed units are reported, and no failed or partial response is promoted as complete.
- **Partial output followed by failure.** Partial child output is diagnostic only and is never accepted as a successful campaign artifact.
- **Whitespace-only output.** The unit fails without creating or overwriting its intended successful output.
- **Large prompts and multiline content.** Text, boundaries, separators, and ordering survive transport unchanged.
- **Repeated isolated calls.** Every child gets its own cleanup guarantee; a later call cannot discover an earlier call's campaign material.
- **Polish action repeats or conflicts.** Existing loop limits, validation, and error-return behavior prevent an unbounded or out-of-scope edit sequence.
- **Explicit empty selection.** Commands that require selected units continue to refuse an empty work set; selecting `codex-cli` never changes empty into “all.”
- **Older or incompatible Codex installation.** The command fails closed with setup guidance rather than weakening isolation or trying another provider.
- **Parent shell contains metered keys.** Subscription children do not receive them; the parent environment remains unchanged.

## Requirements *(mandatory)*

### Scope Inventory

This feature covers the 30 production commands that currently register or forward CampaignGenerator's shared model backend selection. Deterministic commands that neither perform nor dispatch model work are outside scope.

- **Session document (8)**: `check_consistency`, `enhance_summary`, `scene_extract`, `sd_agent`, `sd_consistency`, `sd_plan`, `sd_narrate`, `vtt_voice_compare`.
- **Preparation, ingest, search, and integration (5)**: `prep`, `transform`, `dnd_sheet`, `query`, `scabard_sync`.
- **Grounding (8)**: `planning`, `party`, `make_tracking`, `distill`, `campaign_state`, `npc_table`, `grounding_sections`, `thread_registry`.
- **Ensemble (9)**: `synthesise_world_state`, `synthesise_polish`, `extract_facts`, `facts_to_state`, `narrate_chapter`, `polish`, `ensemble`, `ensemble_batch`, `ensemble_extract`.

The inventory is a baseline, not a permanent allowlist: any production command added later that joins the shared backend family must satisfy the same parity checks.

### Functional Requirements

**Coverage and uniform selection**

- **FR-001**: All 30 scoped commands MUST accept or forward the `codex-cli` backend using the shared spelling and meaning.
- **FR-002**: Every direct model-bearing command MUST complete its established user-visible job through `codex-cli`; merely displaying the choice without supporting the command's request shape is not sufficient.
- **FR-003**: Every orchestration and dispatcher command MUST forward the selected backend, compatible model intent, and applicable execution controls to every model-bearing child.
- **FR-004**: The project MUST automatically detect any production CLI that registers or forwards the shared backend vocabulary without `codex-cli` parity.
- **FR-005**: Existing `anthropic`, `dgx`, `openrouter`, and `claude-code` choices, defaults, request behavior, and errors MUST remain unchanged.
- **FR-006**: A `codex-cli` failure MUST NOT fall back to another provider or credential path.

**Workflow and artifact parity**

- **FR-007**: Changing only the backend to `codex-cli` MUST preserve each command's explicit inputs, selected work set, configuration, context order, prompt boundaries, stage order, and output destination.
- **FR-008**: System/developer instructions MUST retain higher priority than campaign material, and campaign material MUST remain user content rather than being merged into an undifferentiated instruction block.
- **FR-009**: Existing file-based caching, skip, resume, overwrite, force, retry, concurrency, and per-unit timeout semantics MUST remain unchanged unless a provider-specific control is explicitly refused by this specification.
- **FR-010**: Existing human-review checkpoints MUST remain in place, and no subscription result MAY automatically cross a precision boundary that the current workflow leaves for review.
- **FR-011**: A successful subscription result MUST use the caller's normal terminal, logging, counting, persistence, and downstream artifact path.
- **FR-012**: A failed, partial, missing, empty, or whitespace-only subscription result MUST NOT be saved or promoted as a successful artifact.
- **FR-013**: An explicit empty selection MUST remain an empty selection and MUST NOT be expanded to all available inputs.

**Supported production interaction shapes**

- **FR-014**: The backend MUST support all text-only request shapes used by the scoped production commands, including single requests, sequential requests, independent fan-out requests, streaming-shaped callers that consume a complete final response, text content blocks, and application-maintained multi-turn text.
- **FR-015**: Request text, line breaks, separators, content-block text, message role, and order MUST be preserved across transport.
- **FR-016**: The ensemble `polish` workflow MUST complete its existing critique/edit loop through `codex-cli`, including declared tool requests, tool results, loop completion, and tool-error feedback.
- **FR-017**: Any application-brokered polish operation MUST be limited to the workflow's existing named operations, validated arguments, explicit input/output document scope, and established iteration limits.
- **FR-018**: Malformed, unknown, ambiguous, or out-of-scope operations MUST be refused without expanding permissions or being counted as successful edits.
- **FR-019**: The Codex child MUST NOT receive shell, general filesystem, web, plugin, external-tool-server, image-generation, or subagent capabilities as a consequence of supporting the polish loop.
- **FR-020**: Images, arbitrary external tools, and request shapes unused by the current production CLI inventory MUST remain explicitly unsupported until separately specified and accepted.

**Subscription safety and execution**

- **FR-021**: All subscription runs MUST use the operator's saved Codex login and MUST NOT require or receive `OPENAI_API_KEY` or `CODEX_API_KEY`.
- **FR-022**: Every Codex child MUST run ephemerally with read-only access from an isolated temporary working location outside the campaign repository.
- **FR-023**: Every Codex child MUST ignore repository instructions and user configuration, prevent user-configured plugins and external-tool servers from starting, and disable web search, executable extensions, and delegation.
- **FR-024**: Temporary campaign material MUST be removed after success, refusal, error, interruption, or timeout.
- **FR-025**: Missing executable, missing login, incompatible model, invalid timeout, timeout, unsuccessful exit, and empty result MUST produce distinct actionable failures.
- **FR-026**: Subscription execution failures MUST remain non-transient to shared retry behavior unless the owning workflow already retries an explicit work unit; no retry MAY change providers.

**Model and provider-specific controls**

- **FR-027**: Across all scoped commands, an explicitly selected compatible Codex model MUST take precedence over a Codex-specific default, which MUST take precedence over the subscription default.
- **FR-028**: An inherited provider-incompatible model default MUST NOT be forwarded to Codex; an explicitly selected incompatible model MUST be refused clearly rather than ignored or replaced silently.
- **FR-029**: Existing UI configuration that remembers models per backend MUST keep the Codex model separate from other providers' model choices.
- **FR-030**: A positive Codex execution limit MUST apply uniformly to each subscription child, with the feature-015 default retained when no override is supplied.
- **FR-031**: Invalid, non-finite, or non-positive timeout configuration MUST be rejected before child execution begins.
- **FR-032**: `--batch` provider message batching MUST be rejected with `codex-cli` before any subscription work begins.
- **FR-033**: Application-level grouping, batched scenes, local ensemble dispatch, resume behavior, and HTML review MUST remain available where they are backend-independent and MUST NOT be confused with provider message batching.

**CLI, UI, and documentation parity**

- **FR-034**: Every scoped command's backend help MUST list `codex-cli` once and describe it consistently as using the saved subscription login.
- **FR-035**: Every scoped CLI capability MUST have a direct or documented transitive UI invocation; every applicable backend selector MUST offer `codex-cli` and MUST forward that selection through the same command path used by an equivalent manual invocation.
- **FR-036**: Existing server-side command builders MUST preserve the resolved Codex backend and model intent without reimplementing model work or hard-coding another backend.
- **FR-037**: UI-launched subscription work MUST write the same disk artifacts and expose the same progress, completion, and error states as the equivalent CLI command; no result MAY exist only in browser state.
- **FR-038**: Operator documentation MUST identify the complete supported CLI family, login prerequisite, model precedence, timeout behavior, isolation boundary, `--batch` incompatibility, application-level batch distinctions, and common errors.
- **FR-039**: The previously certified consistency auditor and its two Codex consistency skills MUST continue to operate unchanged through the canonical auditor.

### Key Entities

- **CLI capability inventory**: The discoverable set of production commands that directly perform or forward language-model work, grouped by workflow family and checked for backend parity.
- **Subscription request**: One immutable model operation containing ordered instructions, user material, message history where required, model intent, output expectations, and a positive execution limit.
- **Subscription execution**: One isolated, ephemeral use of the saved Codex login with a sanitized environment, no provider fallback, an outcome category, and bounded diagnostics.
- **Brokered polish operation**: A model-requested action from the polish workflow's existing named set, with validated arguments, explicit document scope, a result returned to the conversation, and no general executable capability in the child.
- **Workflow artifact**: A draft, report, extraction, narration, plan, state document, log, or other existing file result whose location, review status, and downstream meaning are owned by its CLI workflow.
- **Backend selection**: The explicit provider choice and compatible model intent shared across a CLI, any dispatcher children, an existing UI face, and the owning configuration boundary.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All 30 inventoried production commands pass acceptance coverage proving they accept or forward `codex-cli`; every direct model-bearing command also demonstrates a successful normal output through the subscription path.
- **SC-002**: In 100% of authenticated CLI-family acceptance runs, commands complete with `OPENAI_API_KEY` and `CODEX_API_KEY` absent and with zero fallback-provider attempts.
- **SC-003**: For fixed fixtures from every workflow family, 100% of selected input text, role boundaries, separators, and ordering match the command's established request assembly, and output files appear at the same destinations.
- **SC-004**: Across success, error, interruption, and timeout tests for direct, sequential, fan-out, and polish-loop execution, zero Codex children receive stripped API keys, repository instructions, user plugins, external-tool servers, general write access, web access, or subagent capability.
- **SC-005**: The polish acceptance suite completes all existing declared operation types, refuses 100% of malformed or out-of-scope operations, and performs zero writes outside the explicitly selected polish targets.
- **SC-006**: 100% of missing-executable, missing-login, incompatible-model, invalid-timeout, timeout, failed-process, and empty-result fixtures produce the applicable actionable error, create zero misleading successful artifacts, and make zero provider fallback attempts.
- **SC-007**: 100% of scoped CLI capabilities have a tested direct or transitive UI invocation, every applicable backend selector exposes and forwards `codex-cli`, and equivalent CLI/UI fixture runs resolve the same backend and model intent.
- **SC-008**: 100% of `codex-cli` plus provider-message-batch requests are refused before subscription work, while all covered backend-independent grouping, local dispatch, resume, and review fixtures continue to work.
- **SC-009**: The full existing regression suite for `anthropic`, `dgx`, `openrouter`, and `claude-code` passes without changed user-visible outputs or defaults.
- **SC-010**: In an operator walkthrough spanning at least one command from each of the four inventory families, the GM can select the subscription backend, predict the model/default behavior, find the resulting artifact, and diagnose a setup or execution failure without reading source code.

## Assumptions

- PR #350 and feature 015 are the baseline dependency. They supply the isolated `codex-cli` backend, saved-login behavior, model and timeout controls, error categories, and consistency-auditor adoption; this feature broadens certification rather than redefining that boundary.
- The 30-command inventory reflects production commands in the project at specification time. Automated discovery is expected to keep future additions from recreating partial parity.
- Current production model inputs are text-only. The only scoped production command that requires application-maintained assistant history and declared tool-result turns is `polish`; image input and arbitrary third-party tools are not required for cross-CLI parity.
- Supporting polish means preserving its existing application-controlled document operations, not enabling Codex's own shell, filesystem, web, plugin, or delegation tools.
- Commands with several calls may start several isolated Codex executions. Their existing stage, fan-out, retry, and resume rules remain the source of truth; this feature does not silently collapse or broaden work units.
- Existing UI workflows are extended wherever they already launch a scoped command. Commands without a direct or genuinely equivalent owning workflow face receive the smallest invocation surface that lets the human choose inputs, run the capability, and see its disk-backed outcome; no new browser-only workflow state is introduced.
- The installed Codex version must support feature 015's strict non-interactive isolation contract. An older or incompatible version fails closed rather than running with weaker protections.
- A complete final text response satisfies existing streaming-shaped callers; true token-by-token delivery is not required unless a workflow already exposes a user-visible requirement that depends on it.
- Existing output-token arguments remain accepted as workflow sizing intent even where the Codex command line has no identical provider control; the required outcome is a complete non-empty result that satisfies the owning workflow's existing validation.
- Adding a backend choice to existing selectors does not change the shape or location of persistent campaign state, so no one-shot state migration or migration document is required.
