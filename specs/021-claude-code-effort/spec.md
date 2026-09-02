# Feature Specification: Claude Code Subscription Effort Level

**Feature Branch**: `021-claude-code-effort` (worktree: `worktrees/021-claude-code-effort`)

**Created**: 2026-09-01

**Status**: Draft

**Input**: User description: "I want the equivalent feature for Codex Subscription to set the effort level - both CLI and UI https://github.com/kostadis/CampaignGenerator/pull/359"

**Scope ruling**: The literal reading of the request — effort control for the Codex subscription — is already shipped: PR [#359](https://github.com/kostadis/CampaignGenerator/pull/359) (`specs/019-codex-reasoning-effort/`, closing [#357](https://github.com/kostadis/CampaignGenerator/issues/357)) gave the `codex-cli` backend `--codex-reasoning-effort` across every CLI and UI surface. At the specification checkpoint the operator ruled that this feature targets **the other subscription backend, `claude-code`**, which has no effort control at all. This spec is the `claude-code` equivalent of #359.

## Background: what exists today

The `claude-code` backend (`campaignlib/api/backends.py`) spends the operator's Claude subscription instead of metered API credits. It already *sends* an effort level to `claude -p`, but the operator cannot choose it, cannot see it, and in two of three cases does not own it:

| Situation | What is sent today | Who decided |
|---|---|---|
| Thinking suppressed (the default), clamp-eligible model | `--effort high`, hardcoded | CampaignGenerator, silently |
| Thinking suppressed, always-thinking model family | nothing — the CLI reads `effortLevel` from the operator's own `~/.claude/settings.json` | a file outside this repo |
| Thinking opted in (`CG_CLAUDE_CODE_THINKING` / per-call) | nothing — same `settings.json` inheritance | a file outside this repo |

The hardcoded clamp is not arbitrary: with thinking disabled, the two highest effort levels are refused outright, so a subscription whose `settings.json` pins a high level would otherwise fail every call. But the clamp is invisible, it silently overrides a level the operator deliberately chose, and it is exactly the shape Principle XI names as a scar — an engine that makes a choice no human can reach.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Choose an Effort Level on Every Claude Code CLI Run (Priority: P1)

As a campaign operator running CampaignGenerator against the saved Claude subscription, I can choose the effort level on any command or orchestrated workflow that uses the `claude-code` backend, using one option name with one meaning and one precedence rule everywhere.

**Why this priority**: This is the capability itself. Effort is the single largest lever on run time and output depth for this backend, and today it is unreachable — a render pass that deserves a deeper pass cannot get one, and a cheap pass cannot be made cheaper.

**Independent Test**: For every production command that directly invokes or forwards work to the shared `claude-code` backend, select an explicit level with a compatible thinking state and verify every resulting `claude` invocation receives that level, without changing the command's established inputs, outputs, or review checkpoints.

**Acceptance Scenarios**:

1. **Given** any direct model-bearing command with `claude-code` selected, **When** the operator supplies an explicit effort level, **Then** the run uses that level for its Claude work.
2. **Given** an orchestrator or dispatcher with `claude-code` selected, **When** the operator supplies an explicit effort level, **Then** every applicable child operation receives the same level.
3. **Given** two different commands that use the shared Claude Code backend, **When** the same effort option is supplied to both, **Then** it has the same name, the same meaning, and the same precedence in both.
4. **Given** an explicit effort level and a backend other than `claude-code`, **When** the command is validated, **Then** it is refused before any model work starts.

---

### User Story 2 - Choose and Reuse the Effort Level in the UI (Priority: P1)

As a campaign operator launching work from the application UI, I can choose the effort level anywhere I can choose the `claude-code` backend or a Claude model. My choice is stored with the applicable Claude Code backend profile, survives backend switching and page reloads, and reaches the same CLI engine a manual command would.

**Why this priority**: Constitution Principle XI — every CLI capability ships its face in the same feature. A CLI-only effort control would leave every UI-launched run stuck at whatever the engine hardcodes, which is the state this feature exists to end.

**Independent Test**: On each UI surface that offers the Claude Code backend — global settings, session-document work, scene work, and ensemble stage setup — select an explicit level, launch a run, reload and switch backends and back, and verify the selection is retained and the run reports that level.

**Acceptance Scenarios**:

1. **Given** a UI backend selector set to `claude-code`, **When** the operator opens its Claude Code settings, **Then** they can choose "Claude Code default" or any supported explicit level.
2. **Given** the operator selected an effort level in a persistent UI profile, **When** they reload the page or switch to another backend and back, **Then** the Claude Code selection is restored, and no other backend's settings are altered.
3. **Given** a profile that already carries a stored Codex reasoning effort, **When** the operator sets a Claude Code effort level, **Then** both are stored independently and each stays dormant while the other backend is active.
4. **Given** a UI-launched run with an explicit effort level, **When** the run begins, **Then** it follows the same CLI path and precedence as the equivalent manual invocation.
5. **Given** a UI surface that exposes `claude-code` or its model setting, **When** the feature is accepted, **Then** that same surface also exposes the effort control; no Claude Code-capable UI surface is missing it.

---

### User Story 3 - See What Effort a Run Actually Used (Priority: P1)

As a campaign operator, I can see — before model work begins and in the run's own records — which effort level the run used, and whether it came from my explicit choice, the environment, the engine's compatibility clamp, or my `settings.json`.

**Why this priority**: This is P1 rather than P2 because the reporting gap is a live defect, not a nicety. Today a run can silently execute at a lower effort than the operator pinned, and nothing anywhere says so; two runs that produced different-quality output are indistinguishable after the fact. Constitution Principle VIII — the state is discoverable from the artifact, not from the operator's memory.

**Independent Test**: Exercise the full precedence matrix — explicit value, environment-only value, omission with the clamp active, omission with the clamp skipped — and verify the reported effort state and its source in command output and in every existing record that already reports the effective model.

**Acceptance Scenarios**:

1. **Given** an explicit effort level and an environment value, **When** a `claude-code` run starts, **Then** the explicit value wins and is reported as explicitly chosen.
2. **Given** no explicit value but a valid environment value, **When** a `claude-code` run starts, **Then** the environment value is used and reported as environment-derived.
3. **Given** no explicit and no environment value on a run where the engine applies its compatibility clamp, **When** the run starts, **Then** the clamped level is reported together with the reason it was clamped.
4. **Given** no explicit and no environment value on a run where the engine sends no level at all, **When** the run starts, **Then** the report says the level was inherited from the operator's Claude Code settings and does not claim to know its value.
5. **Given** a run that reports an effective Claude model in a summary, sidecar, or log record, **When** the feature is accepted, **Then** that same record reports the effort state and its source.

---

### User Story 4 - Preserve Today's Behaviour on Omission (Priority: P2)

As a campaign operator with existing campaigns, scripts, and saved configuration, I can omit the setting entirely and every `claude-code` run behaves exactly as it does today, with no configuration file rewritten and no migration to run.

**Why this priority**: P2 because it protects existing work rather than delivering new capability, but it is a hard gate on acceptance: the compatibility clamp is what stops a pinned high level from failing every call, so "omission means send nothing" would be a regression that breaks runs rather than a neutral default.

**Independent Test**: Run the existing regression suite for `claude-code` with no effort selection anywhere, and diff the resulting invocations and artifacts against the pre-feature baseline.

**Acceptance Scenarios**:

1. **Given** a campaign configuration with no effort value, **When** it is loaded and run, **Then** it remains valid, behaves as it does today, and is not silently rewritten.
2. **Given** omission on a run where thinking is suppressed and the model is clamp-eligible, **When** the run starts, **Then** the same compatibility clamp applies as before this feature.
3. **Given** omission on an always-thinking model or a thinking-enabled run, **When** the run starts, **Then** no effort level is sent and the operator's own settings continue to govern.
4. **Given** runs on the Anthropic, DGX, OpenRouter, and Codex backends, **When** the feature is accepted, **Then** their behaviour is unchanged.

### Edge Cases

- An absent or whitespace-only environment value is treated as omission, not as an empty override.
- An explicitly supplied but empty command value is rejected as invalid rather than silently treated as omission.
- The accepted vocabulary is `low`, `medium`, `high`, `xhigh`, and `max`. It deliberately does not include Codex's `minimal`, which the Claude Code CLI does not accept.
- The two highest levels are not accepted when thinking is disabled. An explicit request for one of them on a run whose thinking is suppressed is refused before any model work, naming both remedies (FR-009). Thinking is not enabled automatically: it is off by default on this backend deliberately and by measurement — suppressing the trace took a 130,412-char extraction run from 17m43s to 3m57s — so turning it on is a token-and-time decision that belongs to the operator, not to the engine.
- The conflict does not arise on model families whose thinking cannot be disabled — there the highest levels remain legal, and the engine's clamp is correctly skipped.
- Selecting an effort level while a non-`claude-code` backend is active is refused before model work, not ignored.
- Switching backends in the UI must not leak a Claude Code effort into another provider's profile, nor erase the remembered Claude Code value, nor disturb a stored Codex reasoning effort.
- "Claude Code default" means CampaignGenerator sent no override; it makes no claim about which level the CLI then resolved from the operator's settings.
- A fan-out, retry, resume, or multi-stage workflow carries the resolved level to every newly started Claude Code unit without altering existing retry, cache, overwrite, concurrency, or selection semantics.
- A mixed-backend workflow applies the setting only to stages using `claude-code`; other stages keep their established behaviour.
- A Claude Code CLI too old to accept a valid selected level fails clearly rather than silently dropping the selection.
- Failure, interruption, and timeout do not cause the effort state to disappear from diagnostic output or from saved failure metadata where such metadata already exists.

## Requirements *(mandatory)*

### Functional Requirements

**Shared selection and resolution**

- **FR-001**: Every production command that directly uses or forwards the shared `claude-code` backend MUST accept or faithfully forward one shared option, spelled identically everywhere, naming the Claude Code effort level.
- **FR-002**: The option MUST accept exactly `low`, `medium`, `high`, `xhigh`, and `max`, with help text stating that the two highest levels require thinking to be enabled.
- **FR-003**: A single environment variable MUST provide the fallback for `claude-code` runs that carry no explicit command or UI selection.
- **FR-004**: Resolution precedence MUST be explicit command or UI selection, then the environment variable, then omission.
- **FR-005**: When the resolved state is omission, CampaignGenerator MUST behave exactly as it does today — applying the existing compatibility clamp where it applies today, and sending no level where it sends none today.
- **FR-006**: When a level resolves explicitly, CampaignGenerator MUST send that level to the Claude Code child in place of the clamp, subject to FR-009.
- **FR-007**: A value outside the accepted vocabulary, an explicitly empty value, or the option paired with a backend other than `claude-code` MUST fail validation before any Claude Code child or other model work starts.
- **FR-008**: All direct commands, dispatchers, orchestrators, and future entry points that use the shared `claude-code` client MUST inherit this resolution behaviour without declaring a second vocabulary, a second default, or a second precedence rule.
- **FR-009**: An explicit effort level the run's thinking state cannot support MUST be **refused before any model work starts**, with a message that names the selected level, states that it requires thinking, and gives both ways to resolve it — lower the level, or enable thinking. CampaignGenerator MUST NOT enable thinking on the operator's behalf, MUST NOT silently lower the level, and MUST NOT start the child and let the provider reject it. The rule applies identically at the CLI and in the UI.
- **FR-009a**: The refusal MUST NOT fire on a model family whose thinking cannot be disabled, where the highest levels are legal and no conflict exists.
- **FR-010**: Parent workflows MUST pass the resolved level to every applicable Claude Code child while preserving existing explicit work sets, caching, retries, resume, concurrency, timeouts, overwrite rules, output locations, and human-review checkpoints.
- **FR-011**: The effort selection MUST be independent of, and MUST NOT alter, the existing thinking opt-in, except as required by the FR-009 rule.

**UI parity and persistence**

- **FR-012**: Every current UI surface that exposes the `claude-code` backend, a Claude model for it, or a Claude Code-backed launch MUST expose the effort choice in this same feature.
- **FR-013**: The UI control MUST offer "Claude Code default" plus the five explicit values, without free-text entry.
- **FR-014**: The control MUST appear only in a Claude Code-relevant context and MUST explain that higher levels can increase run time and that the two highest require thinking.
- **FR-015**: Persistent UI backend profiles MUST store the Claude Code effort independently of every other provider's settings — including the existing Codex reasoning effort — preserve it across reloads and backend switches, and represent "Claude Code default" as omission rather than as a guessed value.
- **FR-016**: UI-launched work MUST carry an explicit selection through the existing CLI invocation path; the UI MUST NOT reproduce model work or invent a second precedence rule.
- **FR-017**: Existing campaign configuration without an effort value MUST remain valid, behave as omission, and MUST NOT be silently rewritten. The field is additive and MUST NOT require an out-of-band migration.

**Observability**

- **FR-018**: Before model work begins, command output MUST identify the effective model and the effort state, distinguishing an explicit value, an environment-derived value, an engine-applied compatibility clamp, and inheritance from the operator's own Claude Code settings.
- **FR-019**: Every existing run summary, sidecar, or log record that reports the effective Claude Code model MUST also report the resolved effort state and its source.
- **FR-020**: When the engine applies its compatibility clamp, the output MUST say so and say why, rather than presenting the clamped level as the operator's choice.
- **FR-021**: UI progress or result views that already surface command output or run metadata MUST make the same effort information visible without requiring the operator to open a log file.

**Safety and compatibility**

- **FR-022**: Adding effort control MUST NOT weaken the existing saved-login, credential-stripping, tool-isolation, MCP-isolation, output-ceiling, auto-continue-detection, or artifact-integrity guarantees of the `claude-code` backend.
- **FR-023**: Existing behaviour for the Anthropic, DGX, OpenRouter, and Codex backends, and for Claude Code runs that omit the setting, MUST remain unchanged.
- **FR-024**: Operator-facing help and documentation MUST state the accepted values, the precedence, the omission behaviour, the thinking interaction, the UI location, and what each reported effort state means.
- **FR-025**: Acceptance coverage MUST maintain an inventory of all production CLI and UI Claude Code entry points and MUST fail when a new Claude Code-capable surface does not accept, forward, expose, or report the shared setting as applicable.

### Scope Boundaries

- This feature controls effort only for the existing `claude-code` subscription backend. It does not add a generic effort control to the Anthropic, DGX, or OpenRouter backends, and it does not modify the Codex reasoning-effort control shipped by #359.
- This feature does not change the default. Omission remains the default and preserves today's behaviour exactly.
- This feature does not change which model is selected, does not infer an effort level from a model name, and adds no automatic fallback to a different model, level, or backend beyond the existing compatibility clamp it makes visible.
- This feature does not change the thinking opt-in's own default, its environment variable, or which model families are treated as always-thinking.
- This feature does not alter workflow scope, campaign content, prompt assembly, output schemas unrelated to run metadata, or human approval boundaries.

### Key Entities

- **Claude Code Effort Selection**: The requested state for a run — an optional canonical level plus its source (explicit command or UI, environment, or omitted).
- **Resolved Effort State**: What the run actually did — the level sent (if any), and whether it came from an explicit choice, the environment, the engine's compatibility clamp, or the operator's own Claude Code settings. This is the thing reported; it is not always equal to the selection.
- **Claude Code Backend Profile**: The operator's Claude Code-specific UI configuration — the existing model and thinking settings plus the optional remembered effort level — isolated from the Codex profile and from every other provider's.
- **Claude Code Entry-Point Inventory**: The complete set of production commands, forwarding workflows, and UI surfaces that can invoke the shared `claude-code` backend and therefore require parity coverage.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of inventoried production commands and forwarding workflows that can use `claude-code` accept or forward the same effort selection with the same name and precedence.
- **SC-002**: 100% of precedence cases — explicit over environment, environment over omission, and total omission in both its clamped and unclamped forms — produce the specified resolved state across direct, dispatched, and UI-launched runs.
- **SC-003**: 100% of current Claude Code-capable UI surfaces expose the same six choices ("Claude Code default" plus five explicit levels), retain the Claude Code choice across reload and backend switching without disturbing the stored Codex selection, and launch the equivalent CLI behaviour.
- **SC-004**: 100% of invalid-value, empty-value, wrong-backend, and effort/thinking-conflict cases fail before model work starts, create zero successful artifacts, and state how to correct the input; the conflict case names both remedies and never alters the thinking setting.
- **SC-005**: In 100% of omission cases the invocation is byte-identical to the pre-feature baseline, and no configuration file is rewritten.
- **SC-006**: 100% of command outputs and existing model-reporting records identify both the effective model and the resolved effort state with its source; a run whose level was clamped says so.
- **SC-007**: The regression suite for all other backends and for omitted-effort Claude Code runs passes with zero changed user-visible defaults, zero new provider fallbacks, and no weakened isolation guarantee.
- **SC-008**: An operator who has pinned one of the two highest levels in their own Claude Code settings can determine, from a single run's output alone and without external help, which level that run used and why.

## Assumptions

- The accepted vocabulary is exactly the five levels the installed Claude Code CLI's `--effort` option documents. Codex's `minimal` is deliberately absent: it is not part of this CLI's vocabulary, and inventing it would create the dialect Principle XII forbids.
- The option is named on the Codex precedent set by #359 — a provider-prefixed flag, a matching environment variable, and a matching optional field on the shared model-selection record — so that the two subscription backends read as one family rather than two dialects. The exact spelling is a naming decision for the plan; the requirement here is that it is one spelling everywhere.
- The optional effort field is an additive extension of the existing selection record. Existing files without it stay valid and need no migration, so Constitution Principle XIII is not triggered.
- The existing compatibility clamp is retained as the omission behaviour rather than removed. Removing it would make every run fail for an operator whose Claude Code settings pin one of the two highest levels — the concrete state of the operator's current machine.
- Refusing the effort/thinking conflict rather than repairing it was ruled at a human checkpoint on 2026-09-01, on the same no-silent-repair grounds as #359's no-fallback requirement.
- The always-thinking model families are treated exactly as they are today; this feature reports that distinction rather than changing it.
- `#359` and `specs/019-codex-reasoning-effort/` are the reference implementation for shape, contracts, and test layout. This feature mirrors that structure rather than inventing a parallel one.

## Dependencies

- Builds on the `claude-code` backend delivered by the shared backend/model option family, and on the shared model-selection record extended by #359.
- Validation must account for [#286](https://github.com/kostadis/CampaignGenerator/issues/286) — six test files skip silently in a worktree, so a green suite inside `worktrees/021-claude-code-effort` is not by itself evidence. Acceptance requires a run from the primary checkout, or an explicit accounting of which files skipped.
