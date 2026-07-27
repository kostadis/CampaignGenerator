# Feature Specification: Claude API Batch Processing Option

**Feature Branch**: `004-claude-api-batch`

**Created**: 2026-07-27

**Status**: Draft

**Input**: User description: "When specifying a backend, an option for claude API should be to use batch. All clis must also be configured to handle batch as a parameter"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Halve the API cost of a bulk pipeline run (Priority: P1)

The GM runs a token-heavy, non-interactive pipeline — a grounding-doc synthesis, a multi-scene narration pass, a per-chunk extraction sweep — and selects the Claude API backend with the batch option. The run produces exactly the same artifacts in the same locations as a normal run, but is billed at the Batch API's discounted rate (50% of standard). Nothing downstream (review gates, promotion, later pipeline stages) can tell the difference in how the text was produced.

**Why this priority**: Token spend is the standing cost of the whole architecture (Constitution, "Architecture is Destiny" — which already names "the Batch API at 50% off" as how the system stays affordable). Bulk pipeline runs are the dominant spend; halving them is the entire point of the feature.

**Independent Test**: Run one synthesis CLI (e.g., planning synthesis) twice against the same inputs — once normally, once with batch — and verify both produce a complete output document of the same kind in the same place, and that the batch run appears in billing at the discounted rate.

**Acceptance Scenarios**:

1. **Given** a campaign workspace with valid inputs for a synthesis run, **When** the GM invokes the CLI with the Claude API backend and the batch option, **Then** the run completes and writes the same output artifact (same path, same format) a normal run would have written.
2. **Given** a batch run in flight, **When** the GM observes the terminal, **Then** the run reports its state over time (submitted, in progress with counts, completed) rather than sitting silent.
3. **Given** a pipeline whose work is many independent LLM calls (per-scene, per-chunk), **When** run with the batch option, **Then** those independent calls are submitted together as batch work rather than serially one at a time, and each result lands where the sequential run would have put it (including any per-unit on-disk caches, so re-runs reuse them identically).

---

### User Story 2 - One parameter, learned once, everywhere (Priority: P2)

The GM already knows the uniform backend-selection vocabulary that every LLM-bearing CLI in the repo shares. Batch is added to that shared vocabulary: the same parameter, spelled the same way, is accepted by every CLI that performs LLM calls — prep, the session-doc passes, the grounding-doc generators, the ensemble tools, and the rest. There is no per-tool variation to memorize.

**Why this priority**: The uniform backend vocabulary is an existing, deliberate property (one seam, one vocabulary). A batch option that only some CLIs understand — or that different CLIs spell differently — would fragment it and make the discount unreachable for whole pipelines.

**Independent Test**: Enumerate the CLIs that accept backend selection; invoke each with the batch parameter and the Claude API backend against trivial inputs; every one either runs in batch mode or (if it reaches no LLM call on that code path) behaves exactly as it does today. None rejects the parameter as unknown.

**Acceptance Scenarios**:

1. **Given** any LLM-bearing CLI in the repo, **When** the GM passes the batch parameter with the Claude API backend, **Then** the CLI accepts it and performs its LLM calls in batch mode.
2. **Given** a CLI invoked with the batch option and a backend other than the Claude API (local endpoint, OpenRouter, subscription/claude-code), **When** the run starts, **Then** it is rejected up front with a clear message that batch is a Claude API option — before any work is dispatched or tokens are spent.

---

### User Story 3 - Failures and aborts are unambiguous and don't waste money (Priority: P3)

A batch run that goes wrong tells the GM exactly what happened. If some items in a batch fail while others succeed, the successful results are kept on disk, the failed items are listed individually, and the run as a whole exits as failed. If the GM aborts a run while a batch is outstanding, the system attempts to cancel the outstanding remote work so abandoned items aren't billed.

**Why this priority**: Batch runs are asynchronous and can be large; a silent partial failure would poison downstream synthesis with missing inputs (the exact "optimistic lie" the constitution forbids), and an abandoned batch left running is money spent on work nobody will read. Valuable, but only matters once stories 1–2 exist.

**Independent Test**: Force a batch containing at least one failing item (e.g., an over-limit request); verify the run exits non-zero, names the failed item(s), and leaves the successful items' outputs in place. Separately, abort a run mid-batch and verify a cancellation attempt is made and reported.

**Acceptance Scenarios**:

1. **Given** a batch where some items succeed and some fail, **When** the run completes, **Then** successful outputs are written, failed items are reported individually by name, and the CLI exits with a failure status.
2. **Given** a batch run in flight, **When** the GM interrupts it, **Then** the outstanding remote batch is cancelled (best effort) and the cancellation outcome is reported.
3. **Given** a batch item whose response was cut off at the output-token ceiling, **When** results are processed, **Then** the same loud truncation warning the sequential path emits is emitted for that item.

---

### Edge Cases

- Batch selected with a non-Claude-API backend → rejected before any dispatch (Story 2, scenario 2).
- The remote batch expires or is cancelled server-side before completing → the run reports which items ended unprocessed and exits as failed; completed items' outputs are kept.
- A single-call CLI (one LLM call per run) invoked with batch → still works; it simply submits its one call as batch work and waits. The discount applies; nothing else changes.
- The process is killed (not gracefully aborted) while a batch is outstanding → only the wait is lost: the remote batch runs to completion unobserved and its results are simply never collected. The batch identity was reported at submission (FR-013), so the GM can cancel it manually; re-running the CLI starts a fresh run.
- An interactive/streaming-UX call path (where the GM watches tokens stream) run in batch mode → incremental streaming is inherently unavailable; the CLI must degrade to progress reporting, not pretend to stream.
- Batch results arrive for a pipeline with per-unit caches → results must be written through the same cache discipline as sequential runs (atomic per-unit writes), so an interrupted result-collection pass never leaves a corrupt cache entry.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The backend-selection surface MUST offer batch processing as an option of the Claude API backend, selectable wherever a backend is selectable.
- **FR-002**: Every CLI that performs LLM calls and participates in the shared backend-selection vocabulary MUST accept the batch parameter, spelled and behaving identically across CLIs.
- **FR-003**: Combining the batch option with any backend other than the Claude API MUST fail fast with a clear error, before any tokens are spent.
- **FR-004**: A batch run MUST produce the same artifacts (paths, formats, per-unit caches) as the equivalent sequential run, such that no downstream consumer can tell how the text was produced.
- **FR-005**: All batch communication with the Claude API MUST pass through the repo's single existing API integration seam (Constitution Principle V) — no second integration point.
- **FR-006**: Pipelines composed of many independent LLM calls MUST submit those calls as grouped batch work at their natural boundaries (per-scene, per-chunk), not serially as one-item batches.
- **FR-007**: While a batch is outstanding, the CLI MUST report observable progress (submitted / processing counts / ended) at reasonable intervals.
- **FR-008**: Per-item failures MUST be reported individually; a run with any failed item MUST exit with a failure status while preserving successful items' outputs.
- **FR-009**: Aborting a run with an outstanding batch MUST attempt cancellation of the remote batch and report the outcome.
- **FR-010**: Per-item output-token-ceiling truncation MUST trigger the same loud warning the sequential path emits.
- **FR-011**: When the batch option is not selected, behavior of every CLI MUST be unchanged.
- **FR-012**: While a batch is outstanding, the CLI MUST block and poll until the batch ends, preserving today's single-invocation run-to-completion semantics (one invocation = one finished run, including under the web UI's streaming runner). Submit-and-detach machinery (durable submission records, a separate collect step) is out of scope.
- **FR-013**: The CLI MUST report the batch's identity at submission time, so a batch orphaned by a hard kill of the waiting process can be located and cancelled through the provider's own tools.

### Key Entities

- **Batch submission**: one grouped set of LLM requests handed to the Claude API for asynchronous processing — has an identity, a lifecycle (submitted → processing → ended), per-item results, and a billing rate distinct from standard calls.
- **Batch item**: one LLM request within a submission, corresponding to exactly one unit of pipeline work (one scene, one chunk, one synthesis call); individually succeeds, fails, or expires, and maps back to the on-disk artifact/cache slot the sequential path would have filled.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A representative bulk run (multi-unit extraction or synthesis) executed with the batch option costs half the standard-rate cost of the identical run without it, as visible in API billing.
- **SC-002**: 100% of the repo's LLM-bearing CLIs accept the batch parameter; for each, a batch run yields an artifact set identical in kind and location to its sequential run.
- **SC-003**: A GM can determine the outcome of any batch run (success / which items failed / cancelled) from the CLI output and exit status alone, without consulting the provider's console.
- **SC-004**: Runs without the batch option are byte-for-byte unaffected — existing tests pass unchanged.
- **SC-005**: An aborted batch run leaves no remote work silently running: cancellation is attempted and its result is stated in the run output.

## Assumptions

- "Claude API" means the direct API backend; the subscription (claude-code), local-endpoint, and OpenRouter backends have no batch equivalent here and are explicitly out of scope (they reject the option, FR-003).
- Batch grouping happens at each pipeline's existing natural unit boundary (scene, chunk, dossier); no cross-pipeline or cross-run aggregation is in scope.
- The web UI is out of scope for this feature: it shells out to these CLIs, so batch becomes *reachable* through existing pass-through mechanisms, but no UI surface work (pickers, config fields) is included. A follow-up feature can expose it deliberately.
- The existing name "ensemble batch" (local multi-endpoint dispatch in the ensemble pipeline) refers to a different concept; the new parameter's naming must not collide with or be mistakable for it.
- Batch processing is expected to complete well inside the provider's completion window for the workload sizes this repo produces; the design should tolerate, not optimize for, the multi-hour tail. Losing the waiting terminal (sleep, disconnect) loses only the wait — the remote batch still completes and standard-rate money is not spent; the accepted cost is re-running the submission.
- Single-user tool: no concurrent-submission coordination between multiple operators is needed.
