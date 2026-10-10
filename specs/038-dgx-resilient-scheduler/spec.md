# Feature Specification: Resilient DGX Work Scheduler

**Feature Branch**: `codex/549-dgx-scheduler`

**Created**: 2026-10-10

**Status**: Draft

**Input**: User description: "Issue #549: first make DGX parallelism default from each model's declared served concurrency, then provide one deterministic, resumable queue across endpoints for summary-native extraction, audit, NPC drafting, and verification, with endpoint health, cross-endpoint recovery, stable results, telemetry, aligned failure categories, and Summary Native UI parity."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Use the Served Model's Capacity (Priority: P1)

As a GM running summary-native work on DGX, I want each endpoint to use the selected model's declared concurrency by default so runs use the capacity that is actually available without requiring remembered command-line tuning.

**Why this priority**: The scheduler's per-endpoint bound must come from the authoritative model configuration before resilient distribution can use that bound correctly.

**Independent Test**: Configure a DGX model with a concurrency of 8, run extraction without an explicit parallel value, and verify that each endpoint runs no more than 8 calls at once and that the run identifies both the value and its source.

**Acceptance Scenarios**:

1. **Given** a DGX model whose configuration declares concurrency 8, **When** a user starts extraction or audit without an explicit parallel value, **Then** the run uses 8 calls in flight per endpoint and records that the model configuration supplied the value.
2. **Given** a DGX model with no declared concurrency, **When** a user omits the parallel value, **Then** the existing safe default of 6 per endpoint is used and identified as the fallback.
3. **Given** any resolved default, **When** the user explicitly selects a positive parallel value, **Then** that value wins and is identified as user supplied.
4. **Given** the Summary Native page, **When** the user chooses a DGX backend and model, **Then** the page shows the resolved per-endpoint value and its source before the run starts.

---

### User Story 2 - Finish Work Through an Endpoint Failure (Priority: P1)

As a GM running a large summary-native job on multiple DGX endpoints, I want unfinished items to move to a healthy endpoint when one endpoint fails so the useful work continues without manual redistribution.

**Why this priority**: Endpoint failure during a long run is the central operational problem described by the parent issue.

**Independent Test**: Run a deterministic fixture against two endpoints, make one fail after completing some items, and verify that the other completes the remaining eligible items without resending completed work.

**Acceptance Scenarios**:

1. **Given** two healthy endpoints and an explicitly selected set of items, **When** one endpoint fails after its transport retries are exhausted, **Then** that endpoint is quarantined and its unfinished item is returned to the shared queue for another healthy endpoint.
2. **Given** one quarantined endpoint and one healthy endpoint, **When** queued work remains, **Then** the healthy endpoint continues within its own concurrency bound.
3. **Given** a quarantined endpoint whose health check later succeeds, **When** unfinished work remains, **Then** it may rejoin the run without restarting completed work.
4. **Given** an item has exhausted one endpoint's transport handling, **When** another configured healthy endpoint has not attempted it, **Then** the scheduler may try that endpoint; after every configured endpoint has exhausted the item, the item is reported as retry exhausted.
5. **Given** a model response is rejected or verification rejects content, **When** the scheduler records the outcome, **Then** it does not misclassify that result as an endpoint transport failure or use endpoint retry to conceal it.

---

### User Story 3 - Resume from Durable Work (Priority: P1)

As a GM returning to an interrupted run, I want resume to discover valid completed and incomplete work from the existing caches and run records so already completed model calls are not spent again.

**Why this priority**: Durable recovery removes the manual inspection and restart cost that made the Phandalin run expensive.

**Independent Test**: Interrupt a fixture after a known subset completes, restart with resume, and verify that only unfinished or invalidated items are sent while the final result matches an uninterrupted run.

**Acceptance Scenarios**:

1. **Given** a prior compatible run with completed cached items, **When** the user resumes it, **Then** completed items are reused and only unfinished items are eligible for dispatch.
2. **Given** a prior item recorded as incomplete, **When** the user resumes, **Then** the item is shown as unfinished and may be sent; its incomplete cache is never presented as successful output.
3. **Given** cached work whose input, selected model, or result-affecting options differ from the resumed run, **When** resume evaluates it, **Then** the stale work is not reused and the reason is visible.
4. **Given** a completed run, **When** resume is requested again, **Then** no model call is made and the same ordered outputs and completion report are reproduced.
5. **Given** no compatible prior run, **When** resume is requested, **Then** the system refuses with a clear explanation rather than silently beginning a fresh token-spending run.

---

### User Story 4 - Receive Stable Results and Actionable Reporting (Priority: P2)

As a GM reviewing a run, I want outputs and reports to be stable regardless of completion timing and to distinguish content, verification, transport, and exhaustion outcomes so I can tell what needs human judgment and what needs infrastructure recovery.

**Why this priority**: Parallel completion order must not affect campaign artifacts, and mixed failure counts are not actionable.

**Independent Test**: Execute the same fixture serially and with multiple endpoints under deliberately varied completion timing, then compare ordered outputs, hashes, failure groups, and endpoint totals.

**Acceptance Scenarios**:

1. **Given** the same explicit items and result-affecting inputs, **When** serial and parallel runs complete successfully, **Then** their user-visible item ordering and output hashes are identical.
2. **Given** mixed outcomes, **When** the final report is produced, **Then** it separately counts and lists model-response rejection, verifier finding or rejection, transport failure, and exhausted cross-endpoint retry.
3. **Given** verifier findings, **When** they are reported, **Then** they use the shared failure taxonomy: unsupported or contradicted claim; citation mismatch or non-entailment; superseded claim; knowledge leak; missing source or broken pointer; presentation only; verifier transport or protocol failure.
4. **Given** work ran on multiple endpoints, **When** status or the final report is viewed, **Then** each endpoint has separate item, latency, retry, token-usage, failure, quarantine, and recovery information, with unavailable token usage stated rather than invented.

---

### User Story 5 - Operate and Recover from the Local Application (Priority: P2)

As a GM using the local application, I want to start or resume the same resilient jobs and inspect endpoint health from the existing Summary Native and NPC Dossiers workflows so the browser exposes the complete CLI capability while leaving durable state on disk.

**Why this priority**: The project's parity rule requires the new engine controls and observable state to have a UI face in the same feature.

**Independent Test**: Start a selected multi-endpoint extraction in Summary Native, observe one endpoint become quarantined, reload and resume from disk, then verify NPC draft and deterministic verification expose their corresponding durable state on the NPC Dossiers workflow.

**Acceptance Scenarios**:

1. **Given** an explicit nonempty item or range selection, **When** the user starts extraction or audit from Summary Native, or NPC drafting or verification from NPC Dossiers, **Then** the existing page for that workflow invokes the same scheduling/journaling behavior as its command-line operation.
2. **Given** a resumable run, **When** the page is reloaded, **Then** it reconstructs completed, unfinished, failed, and endpoint-health state from disk and offers resume.
3. **Given** no explicit selection, **When** the user attempts a run or resume, **Then** the operation refuses rather than treating an empty selection as all items.
4. **Given** a quarantined or recovered endpoint, **When** status changes, **Then** the page shows the endpoint state, reason, last check, and current work counts without requiring the user to infer it from streaming text.

### Edge Cases

- All configured endpoints fail preflight: no item is sent, the run remains resumable, and the report identifies each endpoint's failure.
- The last healthy endpoint fails while work remains: completed artifacts stay valid; unfinished items are recorded without fabricating successful output.
- An endpoint recovers after all work has already been assigned: it does not duplicate completed or in-flight items.
- A late result arrives from an endpoint after the item was safely reassigned: at most one result becomes canonical, and the deterministic item identity prevents duplicate output.
- Two endpoints share the same display name or normalize to the same identity: the run refuses ambiguous endpoint identity before dispatch.
- The configured model concurrency is zero, negative, malformed, or absent: invalid values are refused at the model boundary; absence uses the documented fallback.
- An explicit parallel value is greater than the model declaration: the explicit choice is honored and clearly identified, while every endpoint remains bounded by that choice.
- Cached content exists without a compatible completion record, or a record exists without its artifact: the item is incomplete and is never skipped as completed.
- A resume request changes the endpoint list only: compatible completed item results remain reusable, while endpoint telemetry records the new run's actual topology.
- Token usage is unavailable from an endpoint response: telemetry marks it unavailable and preserves the other measurements.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: For DGX extraction and audit, the system MUST resolve an omitted per-endpoint parallel limit from the selected model's authoritative configuration; an explicit value MUST win, and an absent declaration MUST fall back to 6.
- **FR-002**: The selected model's configuration MUST support a positive maximum-concurrency declaration, including 8 for `qwen3.8-flash-next`, at the single DGX model-configuration boundary used by clients and server operations.
- **FR-003**: Every run MUST record and display the effective per-endpoint limit, whether it came from the user, model configuration, or fallback, and the selected model to which a model-derived value belongs.
- **FR-004**: Each extraction, audit, and NPC-drafting invocation MUST use one deterministic item queue across its explicitly configured endpoints. Deterministic NPC verification MUST use the same stable item/journal contract with a bounded local executor and no model call; any future endpoint-backed verifier MUST plug into the endpoint scheduler rather than create a second queue design.
- **FR-005**: The scheduler MUST enforce the effective in-flight limit independently for each endpoint and MUST NOT allow work assigned to one endpoint to consume another endpoint's limit.
- **FR-006**: Before first dispatch, every configured endpoint MUST be health checked; a failed endpoint MUST be quarantined with a visible reason and MUST receive no work while quarantined.
- **FR-007**: After an endpoint's existing transport retry behavior is exhausted for an item, the scheduler MUST quarantine that endpoint and return the unfinished item to the shared queue; the scheduler MUST NOT duplicate the lower transport retry loop.
- **FR-008**: An unfinished transport-failed item MUST be attempted on another healthy configured endpoint that has not attempted it, when one exists, and MUST become retry exhausted after all configured endpoints have exhausted it.
- **FR-009**: Endpoint health MUST be rechecked during a run, and a quarantined endpoint MUST be eligible to rejoin only after a successful check; quarantine and recovery transitions MUST be durable and observable.
- **FR-010**: Each work item MUST have a stable identity and deterministic queue position derived from its explicit operation input, independent of endpoint assignment or completion timing.
- **FR-011**: The system MUST commit at most one canonical result for each item and MUST order aggregate outputs by deterministic queue position, making serial and parallel results byte-stable for deterministic fixtures.
- **FR-012**: Resume MUST derive completion from the operation's existing cache artifacts and run records, MUST reuse only compatible successful items, and MUST NOT introduce a second competing checkpoint truth store.
- **FR-013**: Resume MUST send only unfinished or invalidated items, MUST make zero model calls for a compatible completed run, and MUST refuse when no compatible resumable run can be identified.
- **FR-014**: Compatibility MUST bind item inputs, selected model, and every result-affecting option; endpoint assignment, timing, and endpoint-list changes MUST NOT alone invalidate a completed item result.
- **FR-015**: Cached incomplete, corrupt, missing, or stale items MUST remain visibly unfinished and MUST never be reported as successful solely because a cache path exists.
- **FR-016**: Run status and final reports MUST distinguish model-response rejection, verifier finding or rejection, endpoint transport failure, and exhausted cross-endpoint retry without using endpoint failover for content or verifier outcomes.
- **FR-017**: Verification reporting MUST use the shared taxonomy from issue #523 for unsupported or contradicted claims, non-entailing citations, superseded claims, knowledge leaks, missing sources, presentation-only findings, and verifier transport or protocol failures.
- **FR-018**: Per-endpoint telemetry MUST report items attempted/completed, latency, transport retries, cross-endpoint retries, token usage when supplied, failures, quarantine intervals, health checks, and recoveries; aggregate totals MUST reconcile with item outcomes.
- **FR-019**: The CLI MUST offer the same spelling and meaning for shared parallel and resume controls across extraction, audit, NPC drafting, and verification, and the same endpoint control across the three endpoint-backed operations. Verification MUST identify its parallel executor as local unless an endpoint-backed verifier is explicitly selected in a future feature.
- **FR-020**: The local application MUST expose explicit selection, effective parallel value and source, start/resume controls, progress, and categorized outcomes on each operation's existing workflow page by invoking the CLI engine. Summary Native MUST expose extraction/audit endpoint health and resume; NPC Dossiers MUST expose draft endpoint health/resume and deterministic verification resume/status.
- **FR-021**: Browser reload or disconnect MUST NOT erase or create run state; the page MUST reconstruct status from durable files and MUST NOT hold exclusive pipeline truth in browser memory.
- **FR-022**: An empty item or range selection MUST refuse for both new and resumed batch operations; selecting all MUST materialize the explicit set.
- **FR-023**: Existing completed cache artifacts and existing single-endpoint invocations MUST remain usable without a state migration; the feature MUST document any changed defaults and operator recovery behavior.
- **FR-024**: Health, dispatch, resume, and reporting behavior MUST be testable with controlled endpoints and clocks, without requiring live DGX hardware or token-spending model calls.

### Key Entities

- **Work Item**: One stable, explicitly selected unit of extraction, audit, NPC drafting, or verification, with deterministic identity, position, compatibility basis, attempts, and final outcome.
- **Endpoint**: A uniquely identified configured DGX target with an effective concurrency limit, current health state, health history, active work, and telemetry.
- **Attempt**: One scheduler-level assignment of an item to an endpoint after that endpoint's internal transport handling, recording timing and an outcome without replacing the canonical item result.
- **Run Record**: Durable description of the explicit selection, operation, model, result-affecting options, topology, progress, compatibility basis, categorized outcomes, and report references.
- **Cached Result**: Existing operation-owned durable artifact that can prove a compatible item completed successfully or remained incomplete.
- **Endpoint Telemetry**: Per-endpoint measurements and state transitions that reconcile with item attempts and aggregate run totals.
- **Failure Classification**: Stable operational category plus, for verification findings, the shared semantic taxonomy and evidence needed for human action.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With `qwen3.8-flash-next` configured for 8, 100% of omitted-parallel DGX extraction and audit runs use 8 in-flight calls per endpoint; missing declarations use 6; explicit values win in every tested case.
- **SC-002**: In a two-endpoint acceptance fixture where one endpoint fails mid-run, 100% of eligible unfinished items complete on the surviving endpoint, no completed item is resent, and no endpoint exceeds its bound.
- **SC-003**: When the failed fixture endpoint recovers while work remains, it rejoins within one configured health-check interval and receives work without restarting the run.
- **SC-004**: Resuming an interrupted fixture sends exactly the unfinished compatible items; resuming a completed fixture sends zero model calls.
- **SC-005**: For deterministic fixtures, serial, parallel, failed-over, and resumed executions produce identical ordered output bytes and hashes.
- **SC-006**: Every terminal item appears exactly once in one operational outcome group, every verification finding uses one shared taxonomy category, and aggregate totals equal the sum of per-endpoint attempts and canonical outcomes.
- **SC-007**: In UI acceptance testing, a user can identify the effective concurrency source, inspect which endpoints are healthy or quarantined, and resume an interrupted run in no more than three actions after opening the Summary Native page.
- **SC-008**: A browser reload during every tested run state preserves 100% of durable progress and reconstructs the same completed, unfinished, failed, and endpoint-health view.
- **SC-009**: Controlled tests cover all four operations, all four operational failure groups, endpoint quarantine/recovery, stale and incomplete caches, late duplicate results, and unavailable token telemetry without a live model service.

## Assumptions

- The scheduler coordinates item-level failover only after the existing model-call boundary has completed its own transport retries.
- One exhausted transport chain is sufficient evidence to quarantine an endpoint temporarily; a successful active health check is required before rejoining.
- Each item may make at most one scheduler-level attempt per configured endpoint during one run. Exhaustion therefore has a finite and explainable meaning.
- Health-check cadence uses one documented implementation default that is visible in run status and injectable in tests; exact timing does not affect output identity. This feature does not add a new user-facing cadence option.
- Existing cache artifacts and run records remain the source for resume. A scheduler may extend their metadata, but it does not create an independent completion ledger that can disagree with them.
- Model output and verifier findings remain drafts or review inputs under the existing human checkpoints. Scheduling changes transport and recovery, not authority or promotion rules.
- The issue requires a coordinated change in the external DGX model configuration repository for the new model concurrency field; CampaignGenerator consumes that field and retains its fallback until every model declares one.
- This feature changes no campaign workspace schema that requires an out-of-band migration. Documentation and release notes are still required because the omitted-parallel default changes for configured models.

## Scope Boundaries

- Included: shared resilient scheduling for summary-native extraction, audit, NPC drafting, and NPC verification; DGX per-model concurrency; durable resume; stable output; reports and telemetry; Summary Native UI parity; documentation and cross-repository DGX configuration guidance.
- Excluded: automatic correction or promotion of model/verifier output; semantic adjudication of verifier findings; changing lower-level transport retry policy; non-DGX distributed scheduling; implicit discovery of unconfigured endpoints; a new database or daemon; migration of existing campaign workspaces.
