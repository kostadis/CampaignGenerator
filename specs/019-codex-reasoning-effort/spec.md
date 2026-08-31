# Feature Specification: Codex Reasoning Effort Everywhere

**Feature Branch**: N/A — specification created on `main`; no branch hook is configured

**Created**: 2026-08-30

**Status**: Draft

**Input**: User description: "CG#357 - this issue should be applied to all uses of the codex cli and make changes to the UI"

**Source issue**: [CampaignGenerator #357](https://github.com/kostadis/CampaignGenerator/issues/357) — “Expose Codex reasoning effort for the codex-cli backend”

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Choose Reasoning Effort on Every CLI Run (Priority: P1)

As a campaign operator using the saved Codex subscription, I can choose a Codex reasoning effort on any CampaignGenerator command or orchestrated workflow that uses the `codex-cli` backend. The same option name, accepted values, precedence, and omission behavior apply everywhere, so I do not need to remember command-specific dialects.

**Why this priority**: The issue’s core value is explicit control over reasoning depth. Partial adoption would make results and token usage unpredictable across workflows.

**Independent Test**: For every production command that directly invokes or forwards work to the shared `codex-cli` backend, select `max` with a compatible model and verify that every resulting Codex invocation receives `max` without changing the command’s established inputs, outputs, or review checkpoints.

**Acceptance Scenarios**:

1. **Given** any direct model-bearing command with `codex-cli` selected, **When** the operator supplies `--codex-reasoning-effort max`, **Then** the run uses `max` for its Codex work.
2. **Given** an orchestrator or dispatcher with `codex-cli` selected, **When** the operator supplies an explicit reasoning effort, **Then** every applicable child operation receives that same selection.
3. **Given** two different commands that use the shared Codex backend, **When** the same reasoning-effort option is supplied to both, **Then** it has the same meaning and precedence in both commands.

---

### User Story 2 - Choose and Reuse Reasoning Effort in the UI (Priority: P1)

As a campaign operator launching work from the application UI, I can choose the reasoning effort anywhere I can choose `codex-cli` or a Codex model. My choice is stored with the applicable Codex backend profile, survives backend switching and page reloads, and reaches the same CLI engine used by a manual command.

**Why this priority**: The UI is a required face of the CLI capability. A CLI-only setting would leave UI-launched runs unable to control quality and cost.

**Independent Test**: On each UI surface that offers the Codex backend—including global settings, session-document work, scene work, and ensemble stage setup—select `max`, launch a run, reload or switch away and back, and verify that the selection is retained and the run reports `max`.

**Acceptance Scenarios**:

1. **Given** a UI backend selector set to `codex-cli`, **When** the operator opens its Codex settings, **Then** they can choose “Codex default” or any supported reasoning-effort value, including `max`.
2. **Given** the operator selected a Codex reasoning effort in a persistent UI profile, **When** they reload the page or switch to another backend and back, **Then** the Codex-specific selection is restored without affecting another backend’s settings.
3. **Given** a UI-launched run with an explicit reasoning effort, **When** the run begins, **Then** it follows the same CLI path and precedence as an equivalent manual invocation.
4. **Given** a UI surface that exposes `codex-cli` or its model setting, **When** the feature is accepted, **Then** that same surface also exposes reasoning effort; there are no Codex-capable UI surfaces with the control missing.

---

### User Story 3 - Preserve Defaults and Explain What Ran (Priority: P2)

As a campaign operator, I can omit the setting to preserve Codex’s current model or subscription default, use an environment fallback for unattended runs, and see the resolved model and reasoning-effort state in command output and relevant run records. Invalid input fails before any Codex work or artifact creation begins.

**Why this priority**: Existing runs must remain unchanged by default, while explicit runs must be auditable and configuration mistakes must not spend tokens.

**Independent Test**: Exercise the full precedence matrix—explicit command value, environment-only value, and complete omission—plus invalid and model-incompatible values; verify the reported selection, child-start count, and resulting artifacts for each case.

**Acceptance Scenarios**:

1. **Given** both an explicit command value and an environment value, **When** a `codex-cli` run starts, **Then** the explicit command value wins and is reported.
2. **Given** no explicit command or UI value but a valid `CG_CODEX_REASONING_EFFORT`, **When** a `codex-cli` run starts, **Then** the environment value is used and reported.
3. **Given** no explicit or environment value, **When** a `codex-cli` run starts, **Then** CampaignGenerator sends no reasoning-effort override and reports “Codex default.”
4. **Given** an invalid value, **When** the command is validated, **Then** it fails with the accepted values listed, starts no Codex child, and creates no successful artifact.
5. **Given** a valid effort that the selected model does not support, **When** Codex rejects the combination, **Then** the operator receives a clear model/effort compatibility error and CampaignGenerator makes no fallback attempt.

### Edge Cases

- An absent or whitespace-only environment variable is treated as omission; it does not create an empty override.
- An explicitly supplied but empty command value is rejected as invalid rather than silently treated as “Codex default.”
- The accepted vocabulary is `minimal`, `low`, `medium`, `high`, `xhigh`, and `max`; individual models may support only a subset.
- `max` is selectable for `gpt-5.6-sol`, while compatibility failures for other models remain visible and do not trigger a provider or effort fallback.
- Supplying the Codex-only option while another backend is active is rejected before model work, rather than being ignored.
- A fan-out, retry, resume, or multi-stage workflow carries the resolved effort to every newly started Codex unit without changing existing retry, cache, overwrite, or selection semantics.
- A mixed-stage workflow applies the setting only to stages using `codex-cli`; other backend stages keep their established behavior.
- Switching backends in the UI does not leak a Codex effort into another provider’s profile or erase the remembered Codex value.
- “Codex default” means CampaignGenerator supplied no effort override; it does not claim to know which model-dependent default Codex chose internally.
- Older Codex installations that cannot accept a valid selected value fail clearly without silently dropping the selection.
- Errors, interruption, and timeout do not cause the effort setting to be lost from diagnostic output or saved failure metadata where such metadata already exists.

## Requirements *(mandatory)*

### Functional Requirements

**Shared selection and resolution**

- **FR-001**: Every production command that directly uses or forwards the shared `codex-cli` backend MUST accept or faithfully forward one shared option named `--codex-reasoning-effort`.
- **FR-002**: The shared option MUST accept exactly `minimal`, `low`, `medium`, `high`, `xhigh`, and `max`, with help text explaining that model support varies and that `gpt-5.6-sol` supports `max`.
- **FR-003**: `CG_CODEX_REASONING_EFFORT` MUST provide the environment fallback for all `codex-cli` runs that do not have an explicit command or UI selection.
- **FR-004**: Resolution precedence MUST be explicit command or UI selection over `CG_CODEX_REASONING_EFFORT` over omission.
- **FR-005**: When the resolved state is omission, CampaignGenerator MUST supply no reasoning-effort override to Codex and MUST preserve the current subscription/model default.
- **FR-006**: When a value resolves, CampaignGenerator MUST explicitly supply that value to the Codex child even though the child continues to ignore user configuration.
- **FR-007**: A value outside the accepted vocabulary, an explicitly empty command value, or a Codex-only option paired with another backend MUST fail validation before a Codex child or other model work starts.
- **FR-008**: A valid but model-incompatible effort MUST produce a clear failure that identifies the selected model and effort, MUST create no successful artifact, and MUST NOT retry with another model, effort, or backend.
- **FR-009**: All direct commands, dispatchers, orchestrators, and future entry points that use the shared `codex-cli` client MUST inherit the same resolution behavior without maintaining a separate vocabulary or default.
- **FR-010**: Parent workflows MUST pass the resolved effort to every applicable Codex child while preserving existing explicit work sets, caching, retries, resume, concurrency, timeouts, overwrite rules, output locations, and human-review checkpoints.

**UI parity and persistence**

- **FR-011**: Every current UI surface that exposes `codex-cli`, a Codex model, or a Codex-backed launch MUST expose the reasoning-effort choice in the same feature.
- **FR-012**: The UI control MUST offer “Codex default” plus the six accepted explicit values and MUST make `max` available without free-text entry.
- **FR-013**: The reasoning-effort control MUST be shown only in a Codex-relevant context and MUST explain that higher effort can increase run time and that model support varies.
- **FR-014**: Persistent UI backend profiles MUST store the Codex effort independently of other providers, preserve it across reloads and backend switches, and represent “Codex default” as omission rather than as a guessed value.
- **FR-015**: UI-launched work MUST carry an explicit selection through the existing CLI invocation path; the UI launch path MUST NOT independently reproduce model work or invent a second precedence rule.
- **FR-016**: Existing campaign configuration without a reasoning-effort value MUST remain valid and behave as omission; loading or running it MUST NOT silently rewrite unrelated configuration.

**Observability, safety, and compatibility**

- **FR-017**: Before model work begins, command output MUST identify the effective model selection and the reasoning-effort state as an explicit value, an environment-derived value, or “Codex default.”
- **FR-018**: Every existing run summary, sidecar, or log record that reports the effective Codex model MUST also report the resolved reasoning-effort state, using “Codex default” when no override was sent.
- **FR-019**: UI progress or result views that surface command output or run metadata MUST make the same effective model and reasoning-effort information visible to the operator.
- **FR-020**: Adding reasoning-effort control MUST NOT weaken the existing saved-login, ignored-user-config, credential stripping, tool isolation, timeout, cleanup, no-fallback, or artifact-integrity guarantees of the `codex-cli` backend.
- **FR-021**: Existing behavior for Anthropic, DGX, OpenRouter, Claude Code, and Codex runs that omit reasoning effort MUST remain unchanged.
- **FR-022**: Operator-facing help and documentation MUST state the accepted values, precedence, omission behavior, model-dependent compatibility, UI location, and meaning of the reported “Codex default” state.
- **FR-023**: Acceptance coverage MUST maintain an inventory of all production CLI and UI Codex entry points and fail when a new Codex-capable surface does not accept, forward, expose, or report the shared setting as applicable.

### Scope Boundaries

- This feature controls reasoning effort only for the existing `codex-cli` subscription backend; it does not add a generic reasoning control to other providers.
- This feature does not choose a new default effort. Omission remains the default and delegates the choice to Codex.
- This feature does not change which model is selected, add automatic model/effort compatibility fallback, or infer an effort from a model name.
- This feature does not alter workflow scope, campaign content, prompt assembly, output schemas unrelated to run metadata, or human approval boundaries.

### Key Entities

- **Codex Reasoning Selection**: The requested state for a run, consisting of an optional canonical value, its source (explicit command/UI, environment, or omitted), and whether an override will be sent.
- **Codex Backend Profile**: The operator’s Codex-specific UI configuration, including the existing model choice and the optional remembered reasoning effort, isolated from profiles for other providers.
- **Codex Run Identity**: The observable record of what a run used, including effective model selection, resolved reasoning-effort state, and whether the effort came from an explicit value, the environment, or omission.
- **Codex Entry-Point Inventory**: The complete set of production commands, forwarding workflows, and UI surfaces that can invoke the shared `codex-cli` backend and therefore require parity coverage.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of inventoried production commands and forwarding workflows that can use `codex-cli` accept or forward the same reasoning-effort selection, including successful `max` coverage for `gpt-5.6-sol`.
- **SC-002**: 100% of precedence cases—explicit over environment, environment over omission, and total omission—produce the specified resolved state across direct, dispatched, and UI-launched runs.
- **SC-003**: 100% of current Codex-capable UI surfaces expose the same seven choices (“Codex default” plus six explicit values), retain the Codex-specific choice as specified, and launch the equivalent CLI behavior.
- **SC-004**: 100% of invalid-value and wrong-backend acceptance cases fail before starting model work, create zero successful artifacts, and list actionable correction guidance.
- **SC-005**: In 100% of omission cases, no reasoning-effort override is sent and existing Codex output destinations, defaults, and workflow behavior remain unchanged.
- **SC-006**: 100% of relevant command outputs and existing model-reporting sidecar/log records identify both the effective model selection and reasoning-effort state; UI-launched runs make that information visible without requiring log-file inspection.
- **SC-007**: The full regression suite for existing backends and omitted-effort Codex runs passes with zero changed user-visible defaults, provider fallbacks, or weakened isolation guarantees.
- **SC-008**: In a task-based usability check covering manual CLI, unattended environment-driven, and UI-launched runs, the operator completes all three effort-selection tasks and correctly identifies the resolved effort from the displayed result without consulting external help.

## Assumptions

- The existing shared Codex backend, shared backend/model option family, and UI backend profiles are the baseline supplied by features 015 and 016; this feature extends their contract rather than adding another Codex execution path.
- The accepted value set is the union needed by current Codex configuration and model capabilities: `minimal`, `low`, `medium`, `high`, `xhigh`, and `max`. Model compatibility is allowed to vary and is never silently repaired.
- `max` support for `gpt-5.6-sol` is a required compatibility case from CG#357 and the model’s [official documentation](https://developers.openai.com/api/docs/models/gpt-5.6-sol).
- Empty or whitespace-only `CG_CODEX_REASONING_EFFORT` is equivalent to an unset environment variable; an explicit CLI value must be one of the six canonical values.
- Persisting an optional Codex effort is an additive configuration extension: existing files without it remain valid, need no migration, and retain omission behavior.
- UI surfaces that only display progress or results do not need a separate selector if their launch configuration is owned elsewhere, but they must display the effective effort when they already display model/run identity.
- Existing commands that accept `codex-cli` only transitively satisfy parity by forwarding the shared option to all applicable child commands; they do not need to perform model work themselves.
