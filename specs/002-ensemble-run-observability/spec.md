# Feature Specification: Ensemble Run Observability

**Feature Branch**: `002-ensemble-run-observability`

**Created**: 2026-06-28

**Status**: Draft

**Input**: User description: "when running an extraction, through the ensemble, as a user I need to observe what happened. I want to see the actual command that was run, if I have the actual command, I can run it later, if I need to. I want to see if the command is progressing - the output of the command as it runs. I want to know that the command finished and see the output of the command as it finished. And I want to be able to abort the command"

## Overview

When the operator runs a stage of the ensemble grounding-doc workflow from the UI, the page kicks off a long-running command and shows its output. Today that experience is thin: the operator cannot reliably tell *which* command ran (so they cannot reproduce it later at the CLI), cannot stop a run once it has started, and has only an informal sense of when a run has truly finished versus stalled.

This feature makes an ensemble run **observable and controllable** as a first-class thing. For any ensemble stage the operator launches from the UI, they can: see the exact command that was run in a form they can copy and re-run themselves; watch the command's output appear live as it progresses; see a clear, unambiguous signal when the command finishes (success or failure) together with its final output; and abort a running command before it completes.

This serves the project's standing commitment that the UI only *mechanizes* the sequence and never traps the human inside it: a copyable, reproducible command is precisely the escape hatch that lets the operator drop to the CLI and lose nothing, and a persisted run record keeps the truth of "what happened" on disk rather than only in a browser tab.

## Clarifications

### Session 2026-06-28

- Q: When the operator aborts a running command, how should it be terminated? → A: Graceful stop signal first; force-kill if the process has not exited within a short grace period (~3–5s).
- Q: If the operator closes the tab / navigates away / loses connection mid-run, what happens to the command? → A: Treat disconnect as an implicit abort — stop the run using the same graceful-then-force termination. No unobserved metered runs.
- Q: How is in-flight unit integrity guaranteed when a force-kill interrupts a write? → A: Atomic per-unit publish (write-temp-then-rename) — a force-kill leaves no partial file the resume check trusts; the unit is recomputed on re-run.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See the exact command that ran, and reuse it (Priority: P1)

When the operator launches an ensemble stage from the UI, the page shows the exact command that was executed — the full invocation, including which inputs and which backend/model it used — in a form the operator can read and copy. If the operator later needs to re-run that step themselves (to debug, to tweak a flag, or to run it outside the UI), they can take that command, paste it into a terminal in the campaign workspace, and reproduce the same run.

**Why this priority**: This is the load-bearing escape hatch. The whole point of the UI is to mechanize the sequence without stealing the human's ability to step down to the CLI. If the operator cannot recover the actual command, the UI has become a walled garden. It is also the cheapest, most foundational slice — it delivers value the moment a single stage can be launched.

**Independent Test**: Launch any ensemble stage from the UI. Confirm the displayed command names the same inputs and backend the operator chose, can be copied, and — when pasted into a terminal in the campaign workspace — runs the same operation and produces equivalent output. Confirm no secret values (e.g. API keys) appear in the displayed command.

**Acceptance Scenarios**:

1. **Given** the operator launches a stage with a specific set of inputs and a chosen backend, **When** the run starts, **Then** the page displays the full command line reflecting exactly those inputs and that backend.
2. **Given** a displayed command, **When** the operator copies it and runs it in a terminal opened in the campaign workspace, **Then** it executes the same operation without manual editing to make it runnable.
3. **Given** a run that used a backend requiring a secret credential, **When** the command is displayed, **Then** the secret value is not shown, while the command remains reproducible by an operator who has that credential in their own environment.

---

### User Story 2 - Watch the command progress as it runs (Priority: P1)

While a stage is running, the operator sees the command's output appear incrementally, as it is produced, rather than waiting for the whole run to finish. This lets the operator tell that the run is alive and making progress (e.g. moving from chapter to chapter), and notice early if something is going wrong.

**Why this priority**: Ensemble stages are long-running. Without live progress the operator cannot distinguish "working" from "hung," which makes every run anxiety-inducing and pushes people back to the CLI. Live output is core to the "observe what happened" need.

**Independent Test**: Launch a stage that produces output over time. Confirm output lines appear in the page while the command is still running (not only at the end), within a couple of seconds of being produced, and that the page indicates a run is in progress.

**Acceptance Scenarios**:

1. **Given** a running stage that emits output over time, **When** the command produces a line, **Then** that line appears in the page shortly afterward, while the command is still running.
2. **Given** a running stage, **When** the operator looks at the page, **Then** the page clearly indicates that a run is currently in progress.
3. **Given** a stage that processes multiple inputs in sequence, **When** it advances from one input to the next, **Then** the operator can see that progression in the streamed output.

---

### User Story 3 - Know the command finished, and see its final output (Priority: P1)

When the command completes, the page gives the operator an unambiguous signal that it has finished and whether it succeeded or failed, alongside the command's full output as it ended. The operator does not have to guess whether more output is still coming. The complete record of the run — the command, its full output, and its result — survives after the run, so the operator can review or reproduce it later even after closing the browser.

**Why this priority**: "Did this finish, and did it work?" is the question every run ends on. A run whose completion is ambiguous, or whose output vanishes when the tab closes, fails the basic observability need. Persisting the record on disk keeps "what happened" as truth on disk rather than ephemeral browser state.

**Independent Test**: Run a stage to completion (both a successful run and a failing one). Confirm the page shows a clear finished state distinguishing success from failure, shows the final output, and that the full run record (command + output + result) can still be found after the browser is closed.

**Acceptance Scenarios**:

1. **Given** a stage that completes successfully, **When** the command exits, **Then** the page shows an unambiguous "finished successfully" state along with the final output.
2. **Given** a stage that fails, **When** the command exits with a failure, **Then** the page shows an unambiguous failure state distinct from success, along with the output that led to the failure.
3. **Given** a completed run, **When** the operator returns later (including after closing and reopening the browser), **Then** the command, its full output, and its result are still recoverable.
4. **Given** a run that cannot even start because a precondition is not met, **When** the operator launches it, **Then** the page shows a readable reason for the failure rather than a generic or silent error.

---

### User Story 4 - Abort a running command (Priority: P2)

While a stage is running, the operator can abort it. Aborting stops the underlying command promptly and the page reflects that the run was aborted (distinct from finished-success and finished-failure). Work that the run had already completed and written to disk is preserved, so a later re-run can resume rather than start over.

**Why this priority**: Long, metered, or mistaken runs need a stop button — the operator who realizes they picked the wrong inputs or the wrong backend should not have to wait it out or kill a server. It is P2 because the observe-and-reproduce slices (US1–US3) already deliver standalone value without it, but it closes the loop on real control.

**Independent Test**: Launch a long-running stage, then abort it. Confirm the underlying command stops within a few seconds, the page shows an "aborted" state, and any work the run had already finished and written to disk is still present (a subsequent re-run skips that completed work).

**Acceptance Scenarios**:

1. **Given** a running stage, **When** the operator aborts it, **Then** the underlying command stops promptly and the page shows an aborted state distinct from success and failure.
2. **Given** a stage that had already completed and persisted part of its work when it was aborted, **When** the operator re-runs the stage, **Then** the already-completed work is reused rather than recomputed.
3. **Given** an aborted run, **When** the operator looks at the page, **Then** the output captured up to the abort point remains visible and the run record reflects that it was aborted.

---

### Edge Cases

- **Browser closed mid-run**: If the operator closes the tab, navigates away, or loses connection while a command is running, the run is treated as an implicit abort (stopped via the same graceful-then-force termination), so no metered run keeps burning cost unobserved. The run record (command, output captured, aborted result) must still be recoverable afterward; the operator must not be left unable to tell whether the command kept running or stopped.
- **Very long output**: A run that emits a large volume of output must remain readable (scrollable) in the page and must not lose earlier output from the persisted record.
- **Failure to start**: A run blocked by an unmet precondition (e.g. nothing selected to act on) must surface a readable reason, not a blank or generic error.
- **Abort during the final input of a batch**: Aborting just as an item is being written must not corrupt the partially-written output. Each unit's output is published to its trusted cache location atomically (written to a temp location, then atomically moved), so a force-kill can leave at most a discardable temp artifact — never a partial file at the path the resume check treats as complete. The interrupted unit is recomputed on the next run.
- **Secret-bearing commands**: When a backend needs a credential, the displayed/reproducible command must omit the secret value while remaining runnable by an operator whose environment supplies it.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: For every ensemble stage launched from the UI, the system MUST display the exact command that was executed, including the inputs acted on and the backend/model used.
- **FR-002**: The displayed command MUST be copyable and, when run in a terminal opened in the campaign workspace, MUST reproduce the same operation without requiring the operator to hand-edit it to make it runnable.
- **FR-003**: The system MUST NOT display secret credential values (e.g. API keys) as part of the command, while keeping the command reproducible for an operator whose own environment supplies those credentials.
- **FR-004**: While a command is running, the system MUST stream its output to the operator incrementally as it is produced, not only after completion.
- **FR-005**: While a command is running, the system MUST clearly indicate that a run is in progress.
- **FR-006**: When a command finishes, the system MUST present an unambiguous finished state that distinguishes success from failure, together with the command's final output.
- **FR-007**: The system MUST persist a durable record of each run — the command, its full output, and its result — that remains recoverable after the run ends and after the browser is closed.
- **FR-008**: The operator MUST be able to abort a running command. Abort MUST first request a graceful stop and, if the command has not exited within a short grace period (~3–5 seconds), MUST force-kill it so the stop is bounded.
- **FR-009**: After an abort, the system MUST show an aborted state distinct from both success and failure, and MUST retain the output captured up to the abort point.
- **FR-010**: An abort MUST preserve work the run had already completed and written to disk, such that a subsequent re-run reuses that completed work rather than recomputing it.
- **FR-011**: When a run cannot start because a precondition is unmet, the system MUST surface a readable reason rather than a silent or generic failure.
- **FR-012**: The run record and displayed command MUST reflect the operator's explicit input selection for the stage, never an implicitly expanded set (consistent with explicit-selection rules for token-spending passes).
- **FR-013**: When the operator's connection to a running command is lost (tab closed, navigation away, or network drop), the system MUST treat it as an implicit abort and stop the underlying command using the same graceful-then-force termination as an explicit abort, so no metered run continues unobserved.
- **FR-014**: Each unit of resumable work MUST be published to its trusted cache location atomically (e.g. written to a temporary location then atomically moved), so that an abort or force-kill cannot leave a partial output that a subsequent re-run would treat as completed work. An interrupted unit MUST be recomputed on re-run.

### Key Entities *(include if feature involves data)*

- **Run record**: A durable account of one ensemble-stage execution. Attributes: the exact command line (with secrets omitted), the chosen backend/model, the inputs acted on, the captured output, the final result (succeeded / failed / aborted), and timing. Lives on disk so it outlives the browser session and can be reviewed or reproduced from the CLI.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For 100% of UI-launched ensemble runs, an operator can copy the displayed command and reproduce the run from a terminal in the campaign workspace with no manual edits to make it runnable.
- **SC-002**: No run ever displays a secret credential value in its command, in the live output, or in its persisted record.
- **SC-003**: Output produced by a running command becomes visible to the operator within a few seconds of being produced, while the command is still running.
- **SC-004**: At the end of every run the operator can correctly tell, without ambiguity, whether it succeeded, failed, or was aborted.
- **SC-005**: After aborting, the underlying command stops within a few seconds, and a subsequent re-run resumes from the already-completed work rather than starting over.
- **SC-006**: The full record of any run (command, output, result) remains recoverable after the browser is closed.

## Assumptions

- **Scope across stages**: The four observability needs (see the command, watch progress, see completion, abort) are generic to any ensemble stage that runs a command. Extraction is the driving example named in the request; this spec treats the capability as applying uniformly to every command-running ensemble stage, not extraction alone.
- **One run at a time per stage**: A given ensemble stage runs one command at a time from the UI; launching is disabled while that stage's run is in progress. Coordinating multiple simultaneous runs across stages is out of scope for this feature.
- **Reproducible command form**: "Reproducible" means runnable from a terminal opened in the campaign workspace by an operator whose environment already provides the necessary credentials; the command may include the non-secret environment context needed to reproduce it (e.g. which backend/endpoint/model), but secret values are omitted.
- **Abort semantics**: Abort issues a graceful stop signal first and force-kills only if the command has not exited within a short grace period (~3–5s), so the stop is bounded but a cleanly-exiting command keeps its chance to finish writing the current unit atomically. It does not attempt a graceful drain of all remaining in-flight work. Because ensemble extraction is resumable (completed inputs are cached on disk), preserving already-finished work and discarding the in-flight item is the intended behavior.
- **Persistence location**: The durable run record uses the campaign workspace's existing per-run log convention (a file under the workspace `logs/` directory) so it is equally visible to the UI, the CLI, and a Claude conversation.
- **No change to the underlying engine's behavior**: This feature is about observing and controlling runs, not changing what each ensemble stage computes; the stages themselves and their outputs are unchanged.
