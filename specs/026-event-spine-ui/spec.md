# Feature Specification: Event Spine UI

**Feature Branch**: `026-event-spine-ui`

**Created**: 2026-09-03

**Status**: Draft

**Input**: User description: "Issue #353: State Projection UI cannot build the event spine and allows guaranteed-failing no-input builds"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Prepare Event Spine Without a Terminal (Priority: P1)

As a campaign operator viewing State Projection for a first-time campaign, I can see that the event spine is missing, explicitly choose the chapter corpus to use, and build the event spine without leaving the page.

**Why this priority**: A missing event spine currently prevents Campaign State projections from being built, while the only recovery path requires command-line knowledge. Making that prerequisite reachable completes the primary UI workflow.

**Independent Test**: Start with a campaign that has one or more merged chapter files but no event spine, select a non-empty corpus in the UI, run the event-spine action, and verify that the missing store is created and the affected projection sections become buildable.

**Acceptance Scenarios**:

1. **Given** a campaign has merged chapter files and no event spine, **When** the operator opens State Projection, **Then** the page identifies the missing event-spine path, explains that it is a prerequisite, and offers an action to create it.
2. **Given** the event spine is missing and the operator has explicitly selected one or more corpus inputs, **When** the operator starts event-spine creation, **Then** the system builds the store from exactly those selected inputs and shows the run's progress and outcome.
3. **Given** event-spine creation succeeds, **When** the run completes, **Then** the page refreshes section readiness and immediately allows sections whose required inputs are now present to be selected for building.
4. **Given** no corpus inputs are selected, **When** the operator attempts event-spine creation, **Then** the system refuses to start and explains that corpus scope must be explicitly selected.

---

### User Story 2 - Avoid Guaranteed-Failing Projection Builds (Priority: P2)

As a campaign operator, I cannot accidentally start a projection build for a section whose required input is known to be missing, and I can see what action will make that section ready.

**Why this priority**: Preventing predictable failures reduces confusion and makes the page's reported state actionable instead of merely diagnostic.

**Independent Test**: Open State Projection with at least one required-input section in a no-input state, use both individual selection and Select All, and verify that no run can include that section until its prerequisite exists.

**Acceptance Scenarios**:

1. **Given** a section has a missing required input, **When** the operator views or tries to select it, **Then** the page shows the missing path and prevents that section from entering an ordinary projection build.
2. **Given** buildable and required-input-missing sections appear together, **When** the operator chooses Select All, **Then** only buildable sections are selected and the omitted sections remain visibly marked with their prerequisites.
3. **Given** a selection becomes invalid because a required input disappears before the run starts, **When** the operator starts the build, **Then** the run is blocked before work begins and the current missing prerequisite is shown.

---

### User Story 3 - Recover Clearly From Setup Failures (Priority: P3)

As a campaign operator, I receive a useful result when event-spine creation cannot proceed, without losing my explicit corpus selection or being misled about section readiness.

**Why this priority**: Files can move, become invalid, or disappear between selection and execution. Clear recovery preserves operator control and avoids accidental scope expansion.

**Independent Test**: Select corpus inputs, make one unavailable or invalid, start the action, and verify that the page reports the specific failure, preserves the intended selection where possible, and does not mark dependent sections ready.

**Acceptance Scenarios**:

1. **Given** a selected corpus input is unavailable or invalid, **When** the operator starts event-spine creation, **Then** the action fails with a specific, actionable message and no dependent section is shown as ready because of that failed run.
2. **Given** event-spine creation fails, **When** the operator corrects the problem, **Then** the operator can retry with an explicit selection without reloading the whole application.
3. **Given** the campaign has no eligible merged chapter files, **When** the operator opens the prerequisite action, **Then** the page states that the ensemble workflow must produce chapter inputs first and does not offer an implicit all-chapters fallback.

### Edge Cases

- An event spine already exists, but the operator wants to refresh only selected chapters; the action must make the chosen replacement scope clear before starting.
- Some selected chapters contain no qualifying events; a successful run must distinguish a valid zero-event result from a failure.
- Duplicate, overlapping, or differently ordered selections must not cause the same input to be processed more than once.
- Inputs disappear or change between discovery and execution; the run must fail clearly rather than broadening to other available inputs.
- The event spine is created successfully but another required input remains missing; only sections whose complete prerequisites are present become buildable.
- No projection sections are currently buildable; Select All must result in an empty selection and the ordinary build action must remain unavailable.
- A run is already in progress; the UI must prevent conflicting duplicate starts while continuing to show progress.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The State Projection page MUST identify every section whose required input is missing and display each missing input path.
- **FR-002**: When the missing input is the event spine, the page MUST explain that the operator must build it from an ensemble chapter corpus before dependent sections can be rendered.
- **FR-003**: Operators MUST be able to initiate event-spine creation from the State Projection workflow without using a terminal.
- **FR-004**: The event-spine action MUST require the operator to explicitly select at least one corpus input before a run can start.
- **FR-005**: An empty or absent corpus selection MUST mean that nothing is selected and MUST never be interpreted as all available inputs.
- **FR-006**: A deliberate Select All action for corpus inputs MUST materialize the full currently displayed eligible set as the explicit selection.
- **FR-007**: Before starting the run, the page MUST make the exact selected corpus scope reviewable by the operator.
- **FR-008**: Event-spine creation MUST process exactly the explicitly selected corpus inputs, with duplicate selections treated as a single input.
- **FR-009**: The page MUST show event-spine run progress, successful completion, and failure output in the same observable manner as other projection runs.
- **FR-010**: After a successful event-spine run, the page MUST refresh all projection section states without requiring a page reload.
- **FR-011**: A successful run that yields zero qualifying events MUST be reported as successful while clearly stating that zero events were found.
- **FR-012**: A section with any missing required input MUST NOT be selectable for an ordinary projection build.
- **FR-013**: Select All for projection sections MUST exclude every section with a missing required input.
- **FR-014**: Immediately before starting an ordinary projection build, the system MUST re-check selected-section prerequisites and refuse the run if any required input is missing.
- **FR-015**: A refused build MUST identify the affected section, the missing input, and the prerequisite action when one is available in the UI.
- **FR-016**: Event-spine failures MUST preserve the operator's explicit selection where the inputs remain identifiable, allowing correction and retry without silent scope changes.
- **FR-017**: When no eligible corpus inputs exist, the page MUST explain that chapter corpus generation is required before the event spine can be built.
- **FR-018**: The existing direct command-line behavior for missing inputs and explicit corpus scope MUST remain unchanged.
- **FR-019**: The UI-triggered event-spine operation MUST use the same durable campaign store and the same engine behavior as the equivalent command-line operation.
- **FR-020**: The system MUST prevent a second conflicting event-spine run from starting while one is already active.

### Key Entities

- **Projection Section**: A renderable portion of a campaign document, including its readiness state, required inputs, missing inputs, and whether it is currently eligible for selection.
- **Corpus Input**: An operator-selectable merged chapter artifact that defines the explicit scope used to update the event spine.
- **Corpus Selection**: The materialized, non-empty set of corpus inputs reviewed and approved by the operator for one event-spine run.
- **Event Spine**: The durable, chapter-ordered event store at `docs/ensemble/events.jsonl` from which dependent projections are rendered.
- **Projection Run**: An observable execution with a selected operation, explicit inputs, progress, outcome, and diagnostic output.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In usability testing, 100% of operators can take a first-time campaign with eligible chapter inputs and no event spine to a build-ready Campaign State section without opening a terminal.
- **SC-002**: In all tested empty-selection cases, zero event-spine runs start and zero cases silently expand scope to all chapters.
- **SC-003**: In all tested required-input-missing cases, zero ordinary projection runs start with a section already known to be unbuildable.
- **SC-004**: After successful event-spine creation, updated readiness is visible within 2 seconds of run completion without a full page reload.
- **SC-005**: At least 90% of first-time operators can identify the missing prerequisite and the action needed to resolve it within 30 seconds of viewing the page.
- **SC-006**: In all tested failure cases, the UI names the unavailable or invalid input and retains every still-valid explicit selection for retry.
- **SC-007**: Existing command-line contract tests for event-spine creation and missing projection inputs continue to pass without changed operator-facing behavior.

## Assumptions

- The target operator already has access to the campaign workspace through the existing application and may modify its generated campaign artifacts.
- Eligible corpus inputs are merged per-chapter artifacts produced by the existing ensemble workflow; creating those upstream artifacts is outside this feature's scope.
- Event-spine creation is deterministic and does not require a model call or a human review gate after execution.
- Updating an existing event spine replaces data only for explicitly selected chapters and preserves chapters outside the chosen scope.
- The current event-spine path remains the configured durable store surfaced by projection status; this feature does not introduce a second store or browser-only state.
- Thread-registry setup and review are outside this feature except that their missing inputs follow the same general no-input selection safeguards.
- The UI mechanizes invocation, input selection, and status display; it does not replace the campaign files or the equivalent command-line workflow as sources of truth.

## Scope Boundaries

### In Scope

- Discovering and explicitly selecting eligible event-spine corpus inputs.
- Creating or selectively refreshing the event spine from the State Projection workflow.
- Showing prerequisite guidance, progress, results, and refreshed readiness.
- Preventing known-invalid ordinary projection builds.

### Out of Scope

- Generating the upstream ensemble chapter corpus.
- Editing individual event-spine rows in the browser.
- Automatically selecting all chapters when no explicit selection exists.
- Changing event extraction, filtering, ordering, or replacement semantics.
- Changing direct command-line failure behavior.
- Completing thread proposal review or other human judgment workflows.

## Dependencies

- The campaign contains at least one eligible merged chapter artifact before an event spine can be created.
- Projection readiness continues to report missing required inputs and their paths.
- The existing event-spine engine remains the authoritative operation used by both command-line and UI workflows.
