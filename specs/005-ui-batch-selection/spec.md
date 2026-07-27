# Feature Specification: Batch as a UI Selection Option

**Feature Branch**: `005-ui-batch-selection`

**Created**: 2026-07-27

**Status**: Draft

**Input**: User description: "the cli's now support the ability to specify batch as a way to run the API, the UI doesn't offer such a feature. For every existing UI control that allows you to specify the backend and model - there should be an option to choose batch"

## Overview

Every command-line tool in the toolkit can now run its Claude API work through batch processing at half the token cost. The web UI cannot: an operator who runs the same work from a page instead of a terminal pays full price, with no control anywhere on screen to choose otherwise.

The UI already has a settled answer for *how* an operator expresses "run this work this way": a model choice and a backend choice, resolved by one rule — the app-wide selection applies unless a service overrides it — and displayed with its origin before the operator commits tokens. Batch is a third choice of exactly that kind. This feature adds it to that existing mechanism rather than inventing a parallel one, so that anywhere the operator can say *which model* and *which backend*, they can also say *batch or not*, and see what a run will actually do before starting it.

One surface already has a bespoke batch checkbox (the Session Doc Editor's two stages, added when only those two tools supported batch). That control is superseded by the unified one.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Choose batch for a run from the page that runs it (Priority: P1)

The operator is on any page that spends tokens — a grounding document, an ensemble stage, session prep, a session-doc stage. Alongside the model and backend already shown there, they turn on batch, start the run, and the work executes at the batch rate. The output artifacts are the same ones a non-batch run produces, in the same places.

**Why this priority**: This is the entire point — the cost saving is unreachable from the UI today. A single page proves the mechanism end to end and delivers real money saved.

**Independent Test**: On a grounding page, turn batch on, run, and confirm the run completes with its normal artifact and appears in billing at the batch rate; turn batch off, run again, confirm unchanged behavior.

**Acceptance Scenarios**:

1. **Given** a service page showing a model and backend selection, **When** the operator turns batch on and starts a run, **Then** the run executes as batch work and produces the same artifact a non-batch run would.
2. **Given** a batch run in progress, **When** the operator watches the page, **Then** they see the run's progress reported over time and an unambiguous final state (finished / failed / aborted) — not a silent or apparently-hung page.
3. **Given** batch is off (the default), **When** the operator runs anything, **Then** behavior is exactly as it is today.

---

### User Story 2 - One batch choice, resolved by the same rule everywhere (Priority: P2)

The operator sets batch once app-wide and every service inherits it; where a service needs to differ, that service's own selection overrides the app-wide choice. Before running, the page shows whether batch is on for *this* run and where that came from — the app-wide setting or this service's own override — exactly as it already does for model and backend.

**Why this priority**: The value of a uniform option is that it is learned once and trusted everywhere. A batch switch that exists on some pages, means something different on others, and can't be seen before running would recreate the per-service divergence the selection rule was introduced to end.

**Independent Test**: Turn batch on app-wide, visit each service page, and confirm each shows batch as inherited; override it off on one service, confirm only that service changes and its page reports the override as the origin.

**Acceptance Scenarios**:

1. **Given** batch is turned on app-wide, **When** the operator opens any token-spending service page, **Then** that page shows batch on, attributed to the app-wide setting.
2. **Given** a service has its own batch override, **When** the app-wide setting is changed, **Then** that service keeps its override and every non-overriding service follows the change.
3. **Given** any service page, **When** the operator looks at the run controls before starting, **Then** batch state and its origin are visible without starting a run.

---

### User Story 3 - Batch is honoured or the run is refused — never silently downgraded (Priority: P2)

Batch is a cost-savings measure: the operator chooses it to spend half as much. So when batch is selected and the work cannot actually be done as batch — the service runs on a non-Claude backend, or its tool has no batch capability — the run is **refused**, with the reason stated and a way to resolve it. It never runs anyway at full price.

**Why this priority**: A run that quietly ignores the batch selection bills double what the operator asked for, and does so invisibly. That is the failure mode worth engineering against — more than the inconvenience of a refusal, which the operator can see and fix in one click. Refusing also keeps the UI's behaviour identical to the command line, which already refuses this combination.

**Independent Test**: Set a service's backend to a non-Claude provider with batch selected; confirm the page refuses the run and states why, and that clearing either half makes the run available again.

**Acceptance Scenarios**:

1. **Given** batch is selected and a service resolves to a backend that cannot do batch, **When** the operator views its run controls, **Then** the selection is shown as incompatible, the run is blocked, and the reason names batch as the cause.
2. **Given** that same incompatible state, **When** the operator attempts the run anyway, **Then** it fails with that reason rather than running at full price.
3. **Given** an incompatible selection, **When** the operator looks at the refusal, **Then** it offers the way out — clear the batch selection, or change the backend.
4. **Given** a stage whose work must run in order (slower under batch for the same saving), **When** the operator selects batch there, **Then** the page states the trade-off before the run starts.

---

### Edge Cases

- The operator changes the backend to a non-Claude provider while batch is selected → the selection becomes incompatible and the run is blocked with the reason, rather than the backend change quietly cancelling the cost saving.
- Batch is selected app-wide and a service cannot do batch → that service refuses until the operator resolves it (clear batch for that service, or change its backend). This is intended: an app-wide cost-savings choice that some services silently ignore would be worse than one that says so.
- A batch run's work is already fully cached → nothing is submitted; the page reports that rather than appearing to stall.
- The operator navigates away or closes the tab mid-batch → the run's outcome must remain discoverable when they return, and the existing abort semantics (a lost connection ends the run) must not silently leave remote work running and billing.
- A run partially fails under batch → the page reports which units failed while keeping the successful ones, and the run's final state is "failed", not "finished".
- A service whose tool accepts batch but cannot honour it → the page must not present batch as effective there.
- Batch is armed on a service whose run is long → the operator must be able to tell a still-polling run from a stuck one.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every UI surface that lets the operator choose a model and backend MUST also let them choose batch.
- **FR-002**: Batch MUST resolve by the same rule already used for model and backend: the app-wide choice applies unless the service overrides it.
- **FR-003**: The resolved batch state, and its origin (app-wide or service override), MUST be visible on the run controls before a run starts.
- **FR-004**: Batch MUST default to off, so that operators who change nothing see no change in behavior.
- **FR-005**: When a selection resolves to batch on a service that cannot do batch — because of its backend or because its tool has no batch capability — the selection MUST be reported as incompatible before the run, with the reason naming batch, and the run MUST be blocked at the UI.
- **FR-006**: A run whose resolved selection is batch MUST either run as batch or fail. It MUST NOT run without batch. Batch is a cost-savings measure: silently running at full price spends the operator's money against their stated intent, and does so invisibly. This also keeps the UI's behaviour identical to the command line, which already refuses this combination.
- **FR-006a**: The refusal MUST offer the way out — clearing the batch selection, or changing the backend — in the same place the refusal appears.
- **FR-007**: A batch run MUST report progress over time and MUST end in an unambiguous state (finished / failed / aborted), consistent with how non-batch runs report today.
- **FR-008**: A batch run's artifacts MUST be identical in kind and location to the same run without batch.
- **FR-009**: A partially failed batch run MUST report which units failed, retain successful units, and end in a failed state.
- **FR-010**: Where batch changes a stage's run characteristics materially (ordered stages that lose parallelism), the UI MUST state the trade-off before the run.
- **FR-011**: The existing bespoke batch checkbox on the Session Doc Editor MUST be replaced by the unified control, with no loss of the behavior it offers today.
- **FR-012**: Abandoning a batch run from the UI (abort, navigation away, lost connection) MUST NOT leave remote batch work running unattended and billing.
- **FR-013**: The Connection Graph service is explicitly **out of scope**: it keeps running live and offers no batch option. It is the only service whose run happens inside a single web request rather than as a streamed background run, so a batch run there could outlive the request and strand the operator. Its selection controls MUST continue to work unchanged for model and backend, and the absence of batch there MUST be deliberate rather than an oversight — see FR-014.
- **FR-014**: Where a service is out of scope for batch (currently only the Connection Graph), its run controls MUST NOT present a batch option at all, rather than presenting a disabled or non-functional one.

### Key Entities

- **Batch selection**: the operator's choice to run work as batch — a third selection alongside model and backend, held at the app-wide tier and optionally overridden per service, and resolved to a single effective value for each run.
- **Resolved run selection**: what a specific run will actually use — model, backend, and now batch — together with where each value came from, surfaced before the run starts.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can run any token-spending work from the UI at the batch rate without leaving the browser, and billing confirms the discounted rate.
- **SC-002**: 100% of in-scope UI surfaces offering a model and backend choice also offer a batch choice. The Connection Graph is the one documented exception (FR-013); its exclusion is tracked as follow-up work, not left implicit.
- **SC-003**: An operator can determine, before starting any run, whether it will use batch and why — from the page alone.
- **SC-004**: No run ever executes at full price after batch was selected — every such case is refused with a stated reason, and zero cases proceed silently.
- **SC-005**: With batch left off, every run behaves exactly as it does today.
- **SC-006**: The outcome of a batch run started from the UI is discoverable from the UI — including after the operator navigates away and returns.

## Assumptions

- "Batch" means the same capability the command-line tools expose today: the same work, executed asynchronously at half the token cost, with progress reported instead of live token-by-token output. Losing live streaming under batch is accepted, as it already is on the one surface that offers batch today.
- Batch belongs in the same selection mechanism as model and backend (app-wide default plus per-service override) rather than as a per-run-only toggle, because the feature description ties it directly to the existing backend/model controls.
- The set of surfaces in scope is the set that offers a model and backend choice today: the app-wide selector, the per-service selection shown on each service's run controls, and the ensemble's per-stage settings — minus the Connection Graph, excluded per FR-013 and deferred to its own feature (tracked as a filed issue) because it must first become a streamed background run like every other service.
- Batch is treated as a **hard constraint expressing a cost intent**, not a preference: selecting it means "run this at the batch rate or not at all". Every requirement about incompatible combinations follows from that.
- Tools that cannot act on batch make the selection incompatible for that service (refused with a reason), consistent with FR-006. Exactly one such tool exists today (the optional polish pass, which accepts the batch flag and runs live anyway) and it is **not reachable from the UI**, so no service is affected at present. The rule is stated now so that wiring that pass into the UI later carries the obligation to make its command-line behaviour refuse too — the UI and the command line must never disagree about the same run.
- No new capability is added to the command-line tools by this feature; it exposes what already exists. Where a tool's batch behavior is degraded or absent, the UI reflects that rather than compensating for it.
- Single operator, one page at a time; no coordination between concurrent operators is required.
- Cost reporting beyond what billing already shows (e.g. an in-app savings estimate) is out of scope.
