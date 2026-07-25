# Feature Specification: Model Selection Resolution

**Feature Branch**: `003-model-selection-resolution`

**Created**: 2026-07-25

**Status**: Draft

**Input**: User description: "when selecting a model, there is a default platform model, and then each service can have a per service selection. The resolution is - "if nothing picked, use platform, each service can override" Right now that rule is not enforced. For information on services check docs/config/service-cut.md and use codememory-mcp to see how the code flows."

## Overview

CampaignGenerator presents the operator with an app-wide model choice and an app-wide backend choice, and every service that spends tokens is expected to honour a single rule: **if nothing is picked for this service, use the platform's choice; a service may override it.**

That rule is stated in the configuration docs and implemented three separate times, differently, by three of the six services that run models — and not at all by the other three. The result is that the operator's picks do not reliably reach the work. A run can execute on a different model than the one displayed, on a different backend than the one selected, or on a metered API after the operator explicitly chose local hardware.

This feature makes the resolution rule **one enforced rule** rather than a convention each service re-derives: every model-spending run resolves its choice the same way, every service that may override has a declared place to do so, and the operator can see which model and backend a run will actually use before committing tokens to it.

This is gap #3 of `docs/config/service-cut.md` — "Duplicated backend/model selection … not closed; relocated, not unified" — the selection half that the platform-isolation work explicitly deferred after unifying the *registry* half ("which models exist, and which is the default").

### Current behaviour (the defect, in operator terms)

The app's sidebar shows a MODEL picker and a BACKEND toggle side by side, presenting both as global. They are not owned by the same thing, and neither reaches every service:

| Service (operator-visible surface) | Honours the platform model? | Can override per service? | Honours the sidebar backend? |
|---|---|---|---|
| Ensemble (extract, bundle, threads, recent events, synthesize) | Yes | Yes — per stage | Yes — per stage |
| Session Doc Editor (narrate, scrub) | Yes | Yes — per backend | Yes |
| Grounding (distill, campaign state, party, planning, build dossiers) | Yes | **No** — nowhere to set one | **Borrows the Session Doc Editor's choice** |
| Session Prep (session prep, NPC table, query) | Yes | **No** | **No — always runs on the metered API** |
| Setup (D&D sheet, make tracking) | Yes | **No** | **No — always runs on the metered API** |
| Connection Graph (extract) | Yes | **No** | **No — always runs on the metered API** |

Three consequences the operator actually meets:

1. **The backend toggle silently does nothing on half the app.** Selecting DGX or OpenRouter and then running an NPC Table, a Query, a D&D sheet import, or a Connection Graph extract bills the metered Anthropic API anyway. Nothing in the UI says the choice was dropped.
2. **A Grounding run's model and backend come from two different owners and can contradict each other.** The model arrives from the platform tier; the backend arrives from the Session Doc Editor's own configuration. Choosing a local backend can therefore send a Claude model name to a local endpoint, or send a stale local model name to a run the operator expected to be Anthropic — the outcome depends on what the Session Doc Editor happens to be remembering.
3. **Changing one service's settings changes another service's runs.** Because Grounding has no backend selection of its own, editing the Session Doc Editor's backend silently re-targets every Grounding run.

Where the rule *is* honoured, it is honoured by three unrelated pieces of code that each spell it differently — one resolves three levels, one resolves four with a guard against foreign model names, one resolves two. A fix applied to one does not reach the others.

## Clarifications

### Session 2026-07-25

- **Q: Which services get a per-service override?** → **Exactly the services that already own a configuration document**: Ensemble and Session Doc Editor keep the overrides they have; Grounding, Party and Planning gain one. Setup, Session Prep, NPC Table, Query and Connection Graph remain override-free, preserving the "stateless by decision" ruling (D1) that deliberately stripped their configuration. They still inherit the platform model and backend correctly — they simply have nothing of their own to set. This is the deciding constraint on scope: the feature must not hand config back to services that were purposely relieved of it, and it therefore creates **no new configuration files**.

  *Corrected during planning*: this question was first answered against a list that named Setup as a config owner and omitted Party and Planning. Setup owns no configuration document; Party and Planning each own one (`party.yaml`, `planning.yaml`) and had been folded into Grounding because their runs launch from the Grounding page. The set above is the corrected one, re-confirmed against the same rationale — no config for stateless services.

- **Q: Where does the app-wide backend choice live, and may services override it?** → **The platform tier, with per-service override.** The backend selection moves up beside the model so both sidebar controls are genuinely global, and the five config-owning services may override the pair. This makes the model rule and the backend rule the same rule, and it turns the ensemble's per-stage split (DGX for extract, Anthropic for synthesize — a load-bearing workflow) into an ordinary instance of the rule rather than a special case that only one service can express.

- **Q: What happens when a stored override cannot run on the active backend?** → **The run refuses to start and says why.** The operator clears or corrects the override explicitly; the system never substitutes a selection the operator did not make. This **reverses** the current ensemble behaviour, which silently discards a foreign model name and swaps in the platform's. That substitution is deliberate and documented today, so the reversal is a conscious change of behaviour, not a bug fix — see Assumptions.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The platform choice reaches every run (Priority: P1)

As the GM, when I pick a model and a backend once, I want every token-spending action in the app to use them, so that my choice means what it says and I am never billed for a run I intended to execute locally.

**Why this priority**: This is the correctness core, and the one with a direct money consequence. Today four of the six services ignore the backend choice entirely and quietly spend metered tokens. Nothing else in this feature matters if the platform choice does not reach the work.

**Independent Test**: Select each backend in turn; run one action from every service; confirm each run executes on the selected backend and the selected model. Fully testable without any per-service override existing.

**Acceptance Scenarios**:

1. **Given** I have selected a local backend and no service has an override, **When** I run any model-spending action in any service, **Then** the run executes on that local backend using the platform model, and no metered API call is made.
2. **Given** I have selected the metered API backend and a model, **When** I run any model-spending action, **Then** the run executes on exactly that model.
3. **Given** I change the platform model, **When** I run any action in a service with no override, **Then** the run uses the new model without my visiting that service's settings.
4. **Given** a service's own settings are changed, **When** I run an action in a *different* service, **Then** that run is unaffected.

---

### User Story 2 - A service can deliberately override (Priority: P2)

As the GM, I want to give one of the five config-owning services a different model and backend from the platform default — a cheap local model for bulk extraction, an expensive one for final synthesis — and have that override apply to that service only, so that I can match cost to task without changing my global default back and forth.

**Why this priority**: This is the half of the rule that makes the platform default useful rather than restrictive, and it is the workflow the ensemble already depends on (DGX for extract, Anthropic for synthesize, in the same run). It ranks below P1 because an override that reaches the run is worthless if the *underlying* resolution is unreliable.

**Independent Test**: Set an override on one config-owning service, leave the others unset, run an action in each of the ten; confirm only the overriding service diverges and every other service still follows the platform.

**Acceptance Scenarios**:

1. **Given** a config-owning service has an override set, **When** I run an action in that service, **Then** the run uses the override's model and backend, not the platform's.
2. **Given** a config-owning service has an override set, **When** I run an action in any other service, **Then** that run uses the platform selection.
3. **Given** a config-owning service has an override set, **When** I clear it, **Then** that service's runs return to the platform selection with no further action from me.
4. **Given** a config-owning service has an override set, **When** I change the platform selection, **Then** the overriding service's runs are unchanged and every non-overriding service's runs follow the new platform selection.
5. **Given** the ensemble has different per-stage selections, **When** I run a workflow spanning those stages, **Then** each stage uses its own selection within the one run.
6. **Given** I am viewing a service that owns no configuration, **When** I look for a per-service override, **Then** none is offered, and the platform selection is shown as the one in effect.

---

### User Story 3 - I can see what a run will use before I spend on it (Priority: P3)

As the GM, before starting a run I want to see the model and backend it will actually use and where that choice came from — platform default or this service's override — so that I can catch a wrong or stale selection before spending tokens rather than after.

**Why this priority**: Real value, but it is a visibility layer over P1 and P2. Once resolution is correct and overrides work, this is what makes the behaviour trustworthy instead of merely correct. It also closes the specific failure where a stale override survives a backend switch and silently retargets a run.

**Independent Test**: With various combinations of platform choice and service override, inspect each service's run surface before launching; confirm the displayed model, backend and origin match what the run actually uses.

**Acceptance Scenarios**:

1. **Given** any service with no override, **When** I view its run surface, **Then** it shows the model and backend that will be used and identifies them as the platform default.
2. **Given** a service with an override, **When** I view its run surface, **Then** it shows the overriding model and identifies it as this service's own setting.
3. **Given** a service holds an override that is incompatible with the currently selected backend, **When** I view its run surface, **Then** the incompatibility is visible before I start the run rather than discovered from its output.

---

### Edge Cases

- **A stale override survives a backend switch.** An operator sets a local model name for a service, then switches the platform backend to the metered API. The remembered name is meaningless to the new backend. The run must refuse to start, name the incompatibility, and offer to clear or correct the override — never substitute the platform choice on the operator's behalf.
- **Nothing is picked anywhere.** No platform model is set and no service overrides. The system must still run, on a documented built-in default, rather than failing or emitting no selection at all.
- **A service supports a backend the platform choice cannot serve.** A model name valid for one backend is not valid for another; resolution must never pair a model with a backend that cannot run it.
- **Two services run concurrently with different overrides.** Each run must carry its own resolved choice; neither may observe the other's.
- **The platform choice changes while a run is in flight.** The in-flight run must keep the choice it resolved at launch, not adopt the new one mid-run.
- **An override names a model that no longer exists.** The operator must be able to tell that this is what happened, rather than seeing an opaque failure from the provider.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST resolve the model for every token-spending run using one single ordered rule: an explicit per-run choice, then that service's override, then the platform default, then a documented built-in fallback.
- **FR-002**: The system MUST apply that rule identically across every service that spends tokens, with no service implementing its own variant.
- **FR-003**: The five config-owning services — Ensemble, Session Doc Editor, Grounding, Party, Planning — MUST each have a declared place in their existing configuration document to record an override, and MUST fall back to the platform choice when that place is empty.
- **FR-004**: The five services that own no configuration — Setup, Session Prep, NPC Table, Query, Connection Graph — MUST inherit the platform selection and MUST NOT gain a configuration surface of their own. This feature MUST create no new configuration file.
- **FR-005**: A service's override MUST affect only that service's runs. No service may read another service's selection.
- **FR-006**: The platform tier MUST own the app-wide backend choice alongside the app-wide model choice, so that both are set in one place and neither is stored inside a service.
- **FR-007**: A service override MUST cover model and backend as a pair, so that a service can select a model together with a backend able to serve it.
- **FR-008**: The operator's platform backend choice MUST reach every one of the six token-spending services, including the four that currently ignore it.
- **FR-009**: The system MUST refuse to start a run whose resolved model cannot be served by its resolved backend, and MUST name the incompatibility rather than substituting a different selection.
- **FR-010**: When a run is refused under FR-009, the system MUST let the operator clear or correct the offending override directly from the point of refusal.
- **FR-011**: The system MUST NOT silently replace any operator-set selection with a different one under any circumstance.
- **FR-012**: The system MUST make the resolved model, the resolved backend, and the origin of each (platform default or service override) visible on the run surface before the run starts.
- **FR-013**: Clearing a service's override MUST return that service to the platform choice with no further operator action.
- **FR-014**: The system MUST record, with each run, the model and backend it actually used, so that a completed run's selection can be verified after the fact.
- **FR-015**: The system MUST keep the resolution rule documented in one place, and that documentation MUST match the enforced behaviour.

### Key Entities

- **Platform selection**: the operator's single app-wide choice of model *and* backend. Applies to every service that has not overridden it. There is exactly one.
- **Service override**: an optional per-service selection of a model and backend pair that supersedes the platform selection for that service's runs alone. Absent by default. Available to the five config-owning services only.
- **Resolved selection**: the model and backend a specific run will actually use, together with the origin that produced each. Computed per run at launch, never stored as a separate source of truth.
- **Override-capable service**: a token-spending service that owns a configuration document and may therefore hold an override — Ensemble, Session Doc Editor, Grounding, Party, Planning.
- **Inheriting service**: a token-spending service that owns no configuration by prior decision and always uses the platform selection — Setup, Session Prep, NPC Table, Query, Connection Graph.
- **Incompatibility**: the condition where a resolved model cannot be served by its resolved backend. Blocks the run and is reported, never resolved by substitution.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of token-spending actions in the app execute on the backend the operator selected. Today 4 of 6 services ignore it.
- **SC-002**: 100% of token-spending actions execute on the resolved model, verifiable from the run's own record after it completes.
- **SC-003**: The number of independent implementations of the resolution rule drops from three (plus three services with none) to one.
- **SC-004**: Changing any one service's settings provably changes no other service's runs.
- **SC-005**: An operator can determine which model and backend a run will use, and where each came from, without leaving the run surface and without starting the run.
- **SC-006**: An operator who selects a local backend incurs zero metered API charges across every service, where today four services would charge them.
- **SC-007**: Setting a per-service model requires visiting only that service, and clearing it requires only clearing it — no global setting is disturbed in either direction.
- **SC-008**: Zero runs execute on a model or backend the operator did not select. Every incompatibility is reported before the run starts, and no selection is ever silently substituted.
- **SC-009**: The number of services that own a backend selection they do not use drops to zero — no service reads another service's choice.

## Assumptions

- The platform's existing single app-wide model choice is the correct place for the default; this feature does not introduce a second global tier.
- The list of available models remains a platform-level concern; this feature governs *selection*, not the registry of what exists. Moving the registry's source is separately deferred work (issue #177).
- "Service" means the six token-spending services enumerated above, matching the service boundaries in `docs/config/service-cut.md`. Services with no token-spending runs are out of scope.
- Model and backend are treated as a paired selection, because a model name valid on one backend is generally invalid on another. A rule that resolved the model alone would not remove the observed defect.
- The five services left without an override remain without one because they own no configuration by prior decision (D1), not because they matter less. Should one later need its own selection, granting it is a reversal of that decision and belongs to a separate change.
- Overrides live in the configuration documents that already exist; no service gains a new file. Grounding, Party and Planning each add a field to a document they already own.
- Ensemble and Session Doc Editor keep their existing override *reach* — Ensemble's per-stage selection and the Session Doc Editor's per-backend selection both survive, and unifying the rule must not narrow either.
- **Ensemble's stale-model behaviour changes deliberately.** It currently discards a model name that cannot belong to the active backend and silently substitutes the platform's; under FR-009/FR-011 it must refuse the run instead. Existing tests assert the old silent substitution and will need to be rewritten to assert refusal — an intended reversal of documented behaviour, and the one place where this feature is not backward-compatible.
- Refusing a run on incompatibility trades friction for certainty: an operator who switches backends with an override set will be interrupted. This is accepted because the alternative spends tokens on a selection the operator did not make.
- Per-run explicit choices continue to win over both service and platform selections, preserving the existing ability to override a single run.
- Existing campaigns' stored configuration remains valid; operators are not expected to re-enter selections they have already made.
- This feature changes selection only. Producer/consumer contracts between services and dependency ordering — the other two open gaps in `docs/config/service-cut.md` — remain out of scope.
