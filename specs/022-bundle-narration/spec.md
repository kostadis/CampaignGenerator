# Feature Specification: Bundled Narration Generation

**Feature Branch**: `narration-bundle`

**Created**: 2026-09-05

**Status**: Draft

**Input**: User description: "The current sd-narrate flow creates 1 narration at a time. That burns a lot of tokens. With frontier models, I want the option to generate all narration in one shot from both the CLI and UI, while retaining the ability to generate one at a time."

## Overview

The narration stage currently generates each planned scene in a separate model exchange. Each exchange repeats shared campaign, party, style, and session context, so a full-session run spends input tokens on the same material many times. Modern frontier models can accept the complete planned narration set and return all of its scene sections in one exchange.

This feature adds an opt-in bundled mode to the narration CLI and Session Doc Editor. A bundled run sends the explicitly chosen narration set together, preserves the plan's scene and narrator order, and writes the same individual narration files used by review and assembly today. The existing single-scene action and sequential full-session behavior remain available.

Bundled narration is distinct from the existing provider batch-pricing option. Bundling reduces the number of narration exchanges and repeated input; the provider option changes how eligible exchanges are submitted and billed.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generate a full narration set in one exchange from the CLI (Priority: P1)

The operator has reviewed the narration plan and source scene extractions. They explicitly choose bundled narration for all planned scenes and receive one narration file per scene from a single model exchange, avoiding repeated transmission of shared context.

**Why this priority**: This delivers the requested token saving at the CLI engine where narration behavior is owned.

**Independent Test**: Run the same multi-scene session once in bundled mode and once in the existing sequential mode. Confirm that bundled mode uses one exchange and produces the complete expected set of per-scene files in plan order.

**Acceptance Scenarios**:

1. **Given** a reviewed plan with multiple scenes and all required narration inputs, **When** the operator explicitly requests bundled narration for the full plan, **Then** all chosen scenes are requested in one model exchange.
2. **Given** a successful bundled response, **When** the run completes, **Then** each scene is written to its normal individual narration file with the correct scene identity, narrator identity, and session metadata.
3. **Given** an operator selects a subset of plan scenes using the existing scene selection, **When** bundled mode is also selected, **Then** only that explicit subset is included in the one exchange and written.
4. **Given** no scene subset is supplied, **When** the operator explicitly invokes the all-scenes bundled action, **Then** the displayed or reported request set contains every plan scene before any tokens are spent.

---

### User Story 2 - Generate all narration in one exchange from the editor (Priority: P1)

The operator uses the Session Doc Editor and can choose a visible “all scenes in one exchange” narration action. Before starting, the editor shows which scenes will be regenerated. During and after the run, the operator can see progress, the files produced, and any scenes that still need narration.

**Why this priority**: CLI and UI parity is part of the requested capability, and the editor is the normal guided surface for this workflow.

**Independent Test**: Open a ready multi-scene session in the editor, start the bundled all-scenes action, and confirm the streamed command reports one exchange and the scene list updates to show each produced narration file.

**Acceptance Scenarios**:

1. **Given** a narration-ready session, **When** the operator views narration controls, **Then** both the existing current-scene action and a bundled all-scenes action are available.
2. **Given** the operator chooses bundled all-scenes narration, **When** they review the action before starting it, **Then** the editor shows the exact scene count and scene identities that the run will include, including which already have narration output.
3. **Given** the operator starts the bundled action, **When** the run succeeds, **Then** the editor reports completion and refreshes every affected scene from the files written on disk.
4. **Given** the editor starts a bundled run, **When** the executed command is shown, **Then** the same bundled capability is reproducible directly from the CLI.

---

### User Story 3 - Preserve narration quality, ordering, and review boundaries (Priority: P2)

The operator receives the token benefit without losing the per-scene voice, focus, continuity, or review workflow. Each scene uses its assigned narrator's guidance and source material, neighboring scenes remain in plan order, and the operator still reviews individual files before assembly.

**Why this priority**: A cheaper run is useful only if its narrations remain attributable, coherent, and reviewable.

**Independent Test**: Compare a bundled and sequential run of the same reviewed inputs. Verify every output against its plan entry and source extraction, inspect transitions between adjacent scenes, and confirm assembly still waits for the normal human review.

**Acceptance Scenarios**:

1. **Given** a plan whose adjacent scenes have different narrators, **When** bundled narration is generated, **Then** each returned scene follows its own narrator guidance and no narrator-specific material is assigned to another scene.
2. **Given** a plan with ordered scenes, **When** the bundled result is split into files, **Then** scene order and continuity match the reviewed plan.
3. **Given** a bundled run has written every scene, **When** the run finishes, **Then** it does not assemble, approve, or promote the narration automatically.
4. **Given** bundled files on disk, **When** the operator switches between the UI, CLI, and assembly workflow, **Then** all surfaces see the same individual narration artifacts.

---

### User Story 4 - Keep single-scene and sequential recovery available (Priority: P2)

The operator can continue to narrate one scene at a time, run the established sequential flow, or repair an individual scene after a bundled run. A short or malformed bundled response never forces regeneration of scenes that were returned completely.

**Why this priority**: The user explicitly requires the one-at-a-time capability to remain, and individual reruns are the practical recovery path for a large generation.

**Independent Test**: Generate a bundle with one missing or unusable scene, retain all complete scene files, then rerun only the affected scene with the existing current-scene action.

**Acceptance Scenarios**:

1. **Given** bundled mode is not selected, **When** the operator uses the CLI or editor, **Then** existing single-scene and sequential narration behavior remains available with its current defaults.
2. **Given** a completed bundled run, **When** the operator reruns one scene, **Then** only that scene is regenerated and the other bundled outputs remain untouched.
3. **Given** a bundled response that ends after several complete scenes, **When** the result is processed, **Then** complete and unambiguously identified scenes are retained, incomplete scenes are not written, and every missing scene is reported.
4. **Given** a response whose scene boundaries or identities cannot be reconciled safely, **When** the result is processed, **Then** content is not assigned by guesswork and the run reports the affected scenes for recovery.

### Edge Cases

- A bundle containing one scene uses one exchange and produces the same artifact expected from the current single-scene path.
- An empty scene selection is refused before a model call; it never expands silently to all scenes.
- Duplicate or punctuation-heavy scene names cannot cause one scene's narration to be written under another scene's file.
- Missing source extractions, narrator declarations, voice files, examples, or other required inputs are reported during preflight before the bundled exchange begins.
- If one selected scene cannot be matched to the reviewed plan and source material, the bundle is refused before spending tokens rather than silently omitting the scene.
- If the selected set is too large for the chosen model's available input or output capacity, the operator is told before the call when this is knowable and can use sequential or single-scene mode.
- If a response stops early, only fully delimited and correctly identified scenes are eligible to be written; a rerun can target the missing scenes.
- If a response contains an unknown, duplicate, or out-of-order scene section that cannot be reconciled exactly, it is not written to a guessed destination.
- A bundled run that includes scenes with existing narration makes that replacement scope visible before starting and applies the same replacement semantics as an explicit rerun of those scenes.
- Provider batch pricing being on or off does not silently change whether narration is bundled; both choices remain visible and retain their distinct meanings.
- Closing or leaving the editor during a run does not make completed output undiscoverable because the resulting files and run outcome remain on disk.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The narration stage MUST offer an opt-in mode that requests multiple explicitly selected plan scenes in one model exchange.
- **FR-002**: The narration CLI MUST expose bundled mode and MUST report the exact ordered scene set before starting the model exchange.
- **FR-003**: The Session Doc Editor MUST expose bundled all-scenes narration alongside the existing current-scene narration action.
- **FR-004**: Starting bundled all-scenes narration in the editor MUST be an explicit action that shows the included scene count and identities; an empty or absent selection MUST NOT be interpreted as all scenes.
- **FR-005**: Bundled mode MUST honor an explicit existing scene subset when one is supplied and MUST include no unselected scene.
- **FR-006**: A successful bundled run MUST produce the same kind, location, naming, scene metadata, and reviewable per-scene artifacts as the existing narration flow.
- **FR-007**: Every bundled scene MUST be grounded in the same reviewed plan entry, matching scene extraction, party information, narrator-specific voice guidance, style examples, genre guidance, campaign context, and operator-selected narration settings that govern that scene in sequential mode.
- **FR-008**: Bundled narration MUST preserve the reviewed plan's scene order and MUST provide enough preceding-scene context to maintain the continuity currently carried between sequential scenes.
- **FR-009**: Returned narration MUST be separated and reconciled to the requested scene identities deterministically before files are written; content MUST NOT be assigned using fuzzy or semantic guesses.
- **FR-010**: A scene section that is incomplete, duplicated, unknown, or not safely attributable to exactly one requested scene MUST NOT be written to a narration file.
- **FR-011**: When a bundled response is incomplete, the run MUST retain every complete, safely reconciled scene, name every scene still missing, and finish with an outcome distinguishable from full success.
- **FR-012**: Preflight validation MUST cover the full selected set before the exchange, and a missing required input for any selected scene MUST prevent the bundled call.
- **FR-013**: The run MUST report the number of scenes requested, the number returned complete, the number missing or rejected, and the number of model exchanges used.
- **FR-014**: The editor MUST stream or otherwise display ongoing bundled-run status and MUST refresh all affected scene states from disk when the run ends.
- **FR-015**: Bundled narration MUST remain a draft-only stage; it MUST NOT automatically approve, assemble, promote, or feed its output across the existing human review checkpoint.
- **FR-016**: The current-scene narration action MUST remain available in the CLI and editor after bundled mode is added.
- **FR-017**: The existing sequential multi-scene behavior MUST remain available and MUST remain the default when bundled mode is not explicitly selected.
- **FR-018**: An operator MUST be able to rerun any individual scene after a bundled run without regenerating or modifying other scene narration files.
- **FR-019**: Bundled mode and provider batch-pricing mode MUST be presented as separate choices, and the run MUST report the effective state of each rather than treating either one as the other.
- **FR-020**: Before spending tokens, a bundled run MUST reject a selected set that is known not to fit the active model's supported capacity and MUST direct the operator to sequential or smaller-scope narration.
- **FR-021**: When explicitly replacing existing narration files in a bundle, the run MUST make the replacement set visible beforehand and MUST apply the same preservation and audit behavior used by existing explicit narration reruns.

### Key Entities

- **Narration scene**: One reviewed plan section and its matching source extraction, assigned narrator, narration guidance, position, and destination file.
- **Bundle selection**: The explicit ordered set of narration scenes the operator has chosen to generate together, including whether each scene already has output.
- **Bundled narration result**: The response for a bundle selection, separated into scene sections and classified as complete, incomplete, or unreconciled before any file is written.
- **Narration run outcome**: The durable account of the selected mode, requested scenes, completed files, missing or rejected scenes, exchange count, and final status.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A successful bundled run for two or more selected scenes that fit the active model's capacity uses exactly one model exchange for narration generation.
- **SC-002**: For a full-session bundled run, shared session, party, style, genre, and campaign context is transmitted once rather than once per scene, reducing repeated shared-context transmissions from N to 1 for N selected scenes.
- **SC-003**: 100% of successfully reconciled bundled scenes produce the same expected per-scene artifact shape and destination as sequential narration.
- **SC-004**: 100% of bundled scene outputs are written under the scene identity and narrator assignment from the reviewed plan; no output is assigned by similarity or guesswork.
- **SC-005**: Both the CLI and Session Doc Editor can complete a full bundled narration run without requiring the operator to manually combine or split model output.
- **SC-006**: With bundled mode left off, all existing single-scene and sequential narration acceptance tests continue to pass and their user-visible defaults remain unchanged.
- **SC-007**: In a simulated partial response containing K complete scenes from an N-scene request, exactly K valid scene files are retained and all N−K missing scenes are named for recovery.
- **SC-008**: An operator can identify the chosen narration mode, exact scene scope, exchange count, and final result from the run output in every bundled run.
- **SC-009**: A bundled run never crosses the narration review boundary automatically; 100% of its outputs remain individually reviewable drafts before assembly.

## Assumptions

- Bundled narration is opt-in. Existing single-scene narration and sequential full-session narration remain the defaults unless the operator explicitly selects the new mode.
- “One shot” means one model exchange containing all explicitly selected narration scenes and returning their narrations together. It does not mean one combined output file and does not mean the existing provider batch-pricing mechanism.
- The explicit CLI all-scenes bundled action is itself the operator's deliberate “select all” choice. In the UI, the action shows and materializes the exact plan scene set before it starts.
- The initial UI scope is the full reviewed plan as one bundle plus the existing current-scene action. Existing CLI scene filters can define a smaller explicit bundled set; arbitrary multi-select editing in the UI is not required for the requested full-session action.
- Frontier models with sufficient context and response capacity are the intended target. Sessions that do not fit retain the established sequential and single-scene paths instead of silently changing the requested bundle into multiple exchanges.
- Per-scene files remain the source of truth for review and assembly. The combined model response is a transport result, not a new canonical narration artifact.
- The same backend, model, pricing mode, prose mode, reflections, and narration guidance selected for the run apply to every scene in the bundle, while narrator-specific inputs continue to vary by plan scene.
- Quality comparison between modes uses the same reviewed inputs and checks scene identity, narrator attribution, grounding, continuity, and completeness; bundled mode is not permitted to weaken verbatim or human-review rules.
- No workspace layout or stored configuration migration is required to add this opt-in run mode.
