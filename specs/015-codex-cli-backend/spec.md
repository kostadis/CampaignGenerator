# Feature Specification: Codex CLI Subscription Backend

**Feature Branch**: `fix/348`

**Created**: 2026-08-27

**Status**: Draft

**Input**: User description: "implement feature CG#348"

GitHub issue: [kostadis/CampaignGenerator#348](https://github.com/kostadis/CampaignGenerator/issues/348) — "Add a Codex CLI subscription backend for consistency audits"

**Scope ruling (issue author, adopted by the user)**: this feature exposes the
new `codex-cli` choice through the consistency-auditor command line and the
Codex consistency skills. Frontend/backend-selector exposure is a separate
follow-up. The planning phase must record this explicit CLI-only ruling in its
constitution check.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run the canonical audit with a Codex subscription (Priority: P1)

A GM who is signed in to the Codex command-line application wants to run the
CampaignGenerator consistency auditor without an Anthropic or OpenAI API key.
They select `codex-cli` as the audit backend. The auditor assembles exactly the
same document, canonical registry, configured grounding documents, explicit
context files, and consistency instructions it uses for every other backend,
then saves the returned Markdown report through the existing report workflow.

**Why this priority**: This is the feature's core value. It lets a GM use an
existing ChatGPT/Codex subscription while retaining CampaignGenerator's
canonical prompt assembly and report format.

**Independent Test**: With the Codex command-line application authenticated
and both metered API-key variables absent, run the auditor with `--backend
codex-cli` and an output path. Confirm that the normal Markdown report is
printed, saved, and counted by the existing report-format rules.

**Acceptance Scenarios**:

1. **Given** an authenticated Codex subscription and valid campaign inputs,
   **When** the GM runs a consistency audit with `--backend codex-cli`, **Then**
   the auditor produces a non-empty Markdown consistency report without
   requiring an Anthropic or OpenAI API key.
2. **Given** a document, canonical registry, configured grounding documents,
   and repeated explicit context inputs, **When** the audit runs through
   `codex-cli`, **Then** all of those inputs reach the model unchanged and in
   the same assembled order used by the existing auditor.
3. **Given** a successful audit and an output path, **When** the result is
   returned, **Then** the complete report is printed, saved at that path, and
   counted using the auditor's existing issue-count convention.
4. **Given** the auditor's consistency instructions and campaign material,
   **When** the request is submitted, **Then** the instructions retain their
   higher-priority role and the document plus campaign context remain user
   material rather than being merged into one undifferentiated prompt.

---

### User Story 2 - Keep subscription audits isolated and unmetered (Priority: P1)

A GM needs confidence that selecting the subscription backend cannot silently
turn into a metered API run or let unrelated repository context and executable
extensions alter the audit. The run uses the saved Codex login, places only the
supplied campaign material in the user prompt, cannot modify files, cannot
browse the web, cannot delegate to other agents, does not start user-configured
plugins or external-tool servers, and does not discover repository instructions.

**Why this priority**: Subscription billing and prompt isolation are part of
the backend's identity, not optional hardening. A run that silently consumes an
API key or inherits unrelated instructions would report a different operation
from the one the GM selected.

**Independent Test**: Start a mocked subscription audit from a repository that
has local agent instructions, user-configured plugins and external tools, and
metered API keys in its parent environment. Confirm that the child is launched
outside the repository, does not load that user configuration, exposes no
executable tool capability, and has read-only access in its isolated working
location.

**Acceptance Scenarios**:

1. **Given** `OPENAI_API_KEY` and `CODEX_API_KEY` are present in the parent
   environment, **When** a `codex-cli` audit starts, **Then** neither credential
   is present in the subscription process and no alternative backend is used.
2. **Given** user-configured plugins, external-tool servers, or repository
   instructions exist, **When** the audit runs, **Then** the plugins and servers
   are not started, the repository instructions are not discovered, and no
   executable extension can receive campaign material.
3. **Given** a subscription audit, **When** it executes, **Then** it cannot
   modify the campaign or repository, browse the web, or create subagent work.
4. **Given** the Codex executable is missing, authentication is unavailable,
   or the subscription command exits unsuccessfully, **When** the audit is
   attempted, **Then** the auditor fails clearly and does not fall back to any
   other backend.

---

### User Story 3 - Get predictable model, timeout, and error behavior (Priority: P2)

A GM can rely on the subscription backend to choose a compatible model and to
stop cleanly when execution fails. An inherited Claude model default is not
sent to Codex. The GM may intentionally select a Codex-compatible model, and
may set a Codex-specific default. Long-running audits have a configurable time
limit. Timeouts, unsuccessful exits, and empty results are distinct failures
with actionable messages.

**Why this priority**: The primary path can work without these controls, but
predictable resolution and bounded failures are necessary for dependable daily
use and prevent accidental cross-provider configuration drift.

**Independent Test**: Exercise the backend with an inherited Claude default,
an explicit compatible model, a Codex-specific model default, an expired time
limit, an unsuccessful process, and empty output; verify the selected model or
the exact refusal in each case and confirm no fallback occurs.

**Acceptance Scenarios**:

1. **Given** the consistency command's inherited `claude-*` model default,
   **When** the GM selects `codex-cli` without another model choice, **Then**
   the subscription's default model is used and the Claude model name is not
   forwarded.
2. **Given** a compatible model explicitly selected for this audit, **When**
   the audit starts, **Then** that model takes precedence over a Codex-specific
   environment default and the subscription default.
3. **Given** no compatible explicit model and a `CG_CODEX_MODEL` value, **When**
   the audit starts, **Then** that Codex-specific model is selected.
4. **Given** the execution exceeds `CG_CODEX_TIMEOUT`, **When** the configured
   limit expires, **Then** the child execution is stopped and the GM sees a
   timeout message naming the configured duration.
5. **Given** an unsuccessful exit or a successful exit with empty output,
   **When** the auditor receives the result, **Then** it reports the applicable
   failure clearly, writes no successful report, and does not try another
   backend.
6. **Given** `--batch` and `--backend codex-cli` are selected together, **When**
   the command is validated, **Then** it refuses before starting a subscription
   run and explains that provider message batching is supported only by the
   Anthropic backend.

---

### User Story 4 - Use the Codex consistency workflows end to end (Priority: P2)

A Codex user invokes the `consistency-check` or `staged-consistency` skill. The
skill routes its CampaignGenerator audit through `codex-cli`, so the canonical
auditor performs prompt assembly and report generation instead of the skill
reproducing that reasoning independently. Existing review and fix-approval
steps continue unchanged after the report is generated.

**Why this priority**: The skills are the intended day-to-day entry point and
the reason the backend is needed. The backend remains independently valuable
and testable through User Stories 1–3, so skill adoption follows them.

**Independent Test**: Run each skill against a representative session
document with a mocked subscription response. Confirm each invokes the
CampaignGenerator auditor with `codex-cli`, consumes the saved report, and
continues its established review workflow.

**Acceptance Scenarios**:

1. **Given** a user invokes `consistency-check`, **When** the underlying audit
   is launched, **Then** it selects `codex-cli` and uses the report produced by
   CampaignGenerator's canonical auditor.
2. **Given** a user invokes `staged-consistency`, **When** any CampaignGenerator
   consistency stage is launched, **Then** it selects `codex-cli` and preserves
   the stage's existing inputs, outputs, and approval boundary.
3. **Given** a staged audit report has been generated, **When** the user opens
   the existing HTML batch-review workflow, **Then** that workflow behaves as
   before; it is not confused with provider message batching.

---

### Edge Cases

- **No saved Codex login.** The run refuses with an authentication-oriented
  error and does not look for an API key or another provider.
- **Codex executable absent.** The run identifies the missing prerequisite
  rather than presenting a generic audit failure.
- **Metered keys present in the parent shell.** Both known Codex/OpenAI API-key
  variables are removed only for the child subscription run; the parent
  environment is unchanged.
- **Claude model inherited from the auditor default.** Any `claude-*` value is
  treated as incompatible and omitted, allowing the subscription default.
- **Explicit incompatible model.** A provider-incompatible model is not
  forwarded silently; the operator receives a clear model-selection refusal.
- **Codex-specific model override is empty.** It is treated as unset, leaving
  the subscription default in control.
- **Timeout is unset.** A documented ten-minute default bounds the run.
- **Timeout is invalid or non-positive.** The command refuses before starting
  the audit and states the required positive-duration format.
- **Process exits non-zero after writing partial output.** Partial output is
  diagnostic only and is not accepted or saved as a successful report.
- **Process exits successfully with whitespace-only output.** The run is an
  empty-result failure and does not create a successful report.
- **Large multiline instructions and campaign context.** Line breaks and
  content boundaries survive transport unchanged.
- **Unsupported interaction shape.** Multi-turn conversations, tools, image
  input, and provider message batches are rejected rather than approximated.
- **Streaming caller.** The existing streaming audit path receives one
  complete text result through its expected interface; true incremental token
  delivery is not required for this backend.
- **Cleanup after success, error, or timeout.** The isolated working location
  does not retain campaign material after the child run ends.

## Requirements *(mandatory)*

### Functional Requirements

**Backend selection and audit parity**

- **FR-001**: The system MUST offer `codex-cli` anywhere the shared command-line
  backend vocabulary is available, while limiting this feature's supported
  user workflow to the consistency auditor and the two named Codex skills.
- **FR-002**: Selecting `codex-cli` MUST use the operator's saved Codex
  subscription authentication and MUST NOT require an Anthropic, OpenAI, or
  Codex API key.
- **FR-003**: The backend MUST support the single-turn text-in/text-out request
  shapes used by both the existing non-streaming and streaming audit paths.
- **FR-004**: The backend MUST preserve the auditor's system/user distinction:
  consistency instructions retain developer-level precedence, while the
  assembled document and campaign context remain user input.
- **FR-005**: The backend MUST preserve the assembled user content byte for
  byte, including the checked document, canonical registry, configured
  grounding documents, repeated explicit context files, separators, and order.
- **FR-006**: A successful result MUST return through the auditor's existing
  report path so normal printing, issue counting, and optional output-file
  persistence remain unchanged.

**Subscription safety and isolation**

- **FR-007**: The subscription run MUST remove `OPENAI_API_KEY` and
  `CODEX_API_KEY` from its child environment without changing the parent
  environment.
- **FR-008**: The subscription run MUST execute ephemerally with read-only file
  access from an isolated temporary working location.
- **FR-009**: The subscription run MUST ignore user configuration, execute from
  outside the repository with project-instruction loading disabled, prevent
  user-configured plugins and external-tool servers from starting, and expose no
  executable extension capable of receiving campaign material.
- **FR-010**: The subscription run MUST have web search and subagent delegation
  disabled.
- **FR-011**: The isolated working location MUST be cleaned after success,
  refusal, unsuccessful exit, or timeout.
- **FR-012**: The backend MUST NOT fall back to another backend for any failure,
  including missing executable, missing login, incompatible model, timeout,
  unsuccessful exit, or empty output.

**Model and execution behavior**

- **FR-013**: An inherited `claude-*` model default MUST NOT be forwarded to
  Codex; absent another compatible choice, the subscription default model MUST
  be used.
- **FR-014**: An explicitly supplied Codex-compatible model MUST take
  precedence over `CG_CODEX_MODEL`, which MUST take precedence over the
  subscription default.
- **FR-015**: An explicitly supplied provider-incompatible model MUST produce a
  clear refusal rather than being forwarded, ignored, or replaced silently.
- **FR-016**: `CG_CODEX_TIMEOUT` MUST configure a positive execution time limit;
  when unset, the limit MUST default to 600 seconds.
- **FR-017**: Invalid or non-positive timeout configuration MUST be rejected
  before child execution begins.
- **FR-018**: A timed-out run MUST stop its child execution and report that the
  configured duration was exceeded.
- **FR-019**: A non-zero child exit MUST be reported with enough child error
  detail to diagnose the failure, while any partial standard output MUST NOT be
  accepted as a report.
- **FR-020**: Empty or whitespace-only output from an otherwise successful child
  MUST be reported as an empty-result failure.

**Compatibility and boundaries**

- **FR-021**: `--batch` MUST remain Anthropic-only and MUST be rejected for
  `codex-cli` before any subscription process starts.
- **FR-022**: The backend MUST reject unsupported tools, image input,
  multi-turn conversations, and other request shapes outside single-turn text
  generation with a clear explanation.
- **FR-023**: Existing `anthropic`, `dgx`, `openrouter`, and `claude-code`
  behavior, defaults, model handling, and error behavior MUST remain unchanged.
- **FR-024**: The existing `claude-code` subscription backend MUST remain a
  distinct selectable backend and MUST NOT be renamed, redirected, or otherwise
  modified by this feature.
- **FR-025**: Frontend and server-side backend-selector exposure for
  `codex-cli` MUST NOT be added by this feature; that surface is explicitly
  deferred by issue #348.

**Skill adoption**

- **FR-026**: The Codex `consistency-check` skill MUST select `--backend
  codex-cli` when it invokes the CampaignGenerator consistency auditor.
- **FR-027**: Every CampaignGenerator auditor invocation in the Codex
  `staged-consistency` skill MUST select `--backend codex-cli`.
- **FR-028**: Updating the skills' backend selection MUST NOT change their
  document discovery, context selection, report location, human review,
  approval, or fix-application behavior.
- **FR-029**: The staged-consistency HTML batch-review page MUST continue to
  operate on a generated audit report and MUST remain independent of the
  provider-specific `--batch` option.

### Key Entities

- **Consistency audit request**: The immutable material submitted for one
  audit: the checked document, canonical registry, configured grounding
  documents, explicit context documents, ordered user content, consistency
  instructions, model intent, output limit, and execution time limit.
- **Subscription execution**: One isolated, ephemeral attempt using the saved
  Codex login. It has a selected model or subscription default, a sanitized
  environment, an outcome status, and diagnostic output, but no fallback
  provider.
- **Consistency report**: The non-empty Markdown result returned by a
  successful execution. It remains compatible with the auditor's current
  issue counting, terminal presentation, file persistence, and downstream
  review workflows.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In 100% of authenticated acceptance runs, a GM can produce and
  save a normal consistency report through `--backend codex-cli` with all
  metered API-key variables absent.
- **SC-002**: For a fixed audit fixture, 100% of document and context bytes and
  their ordering match between the existing auditor assembly and the material
  delivered through the subscription backend.
- **SC-003**: Across success, refusal, error, and timeout tests, zero child runs
  receive either stripped API credential, start a user-configured plugin or
  external-tool server, discover repository instructions, expose an executable
  tool, gain write access, use web search, or delegate to subagents.
- **SC-004**: 100% of missing-executable, missing-login, incompatible-model,
  invalid-timeout, timeout, non-zero-exit, and empty-output cases end with a
  distinct actionable error and zero fallback attempts.
- **SC-005**: 100% of existing backend regression tests continue to pass with
  no changed outputs for `anthropic`, `dgx`, `openrouter`, or `claude-code`.
- **SC-006**: Both named Codex skills route every CampaignGenerator consistency
  audit through `codex-cli`, and their existing post-report review workflows
  complete unchanged in end-to-end acceptance tests.
- **SC-007**: 100% of `codex-cli` plus provider-batch requests are rejected
  before a child subscription process starts, while 100% of staged HTML
  batch-review checks continue to operate after report generation.
- **SC-008**: With no compatible explicit or Codex-specific model, zero
  subscription invocations receive the auditor's inherited Claude model; with
  a compatible explicit model, 100% receive that exact choice.
- **SC-009**: In an operator walkthrough, the GM can identify whether a failed
  audit was caused by setup, authentication, model selection, timeout, child
  failure, or empty output from the terminal message alone, without inspecting
  source code or temporary files.

## Assumptions

- **Codex is installed and logged in.** A successful live run depends on an
  installed Codex command-line application with a saved ChatGPT/Codex login.
  Installing it and performing `codex login` are prerequisites, not work this
  feature automates.
- **The saved login does not depend on metered key variables.** Removing
  `OPENAI_API_KEY` and `CODEX_API_KEY` from the child environment still leaves
  subscription authentication available through the Codex login store.
- **The installed Codex version supports isolated non-interactive execution.**
  Planning must verify the available command surface before implementation;
  the required outcome is ephemeral, read-only, repository-instruction-isolated
  execution with web search and subagents unavailable.
- **The saved-login boundary is not a blank Codex installation.** Current Codex
  can ignore user configuration, isolate itself from a repository, and disable
  executable tools and extensions while retaining normal authentication. It
  does not publicly guarantee that all administrator-provided or bundled
  instruction metadata is absent. This feature promises the enforceable issue
  #348 boundary in FR-009, not an unobservable zero-metadata environment.
- **One complete response is sufficient.** The consistency auditor consumes a
  final report. The backend must satisfy the existing streaming-shaped caller
  contract, but does not need true token-by-token delivery from Codex.
- **Text-only, one-turn scope is intentional.** Tool calls, images, multi-turn
  history, and provider message batches remain unsupported because the
  consistency auditor does not use them.
- **Ten minutes is the default execution budget.** Operators can override it
  with `CG_CODEX_TIMEOUT`; the default favors completion of large campaign
  audits while still bounding a stuck child process.
- **The issue explicitly defers UI parity.** Although the constitution normally
  requires every shared backend capability to have a frontend face, issue #348
  explicitly limits this change to the consistency-auditor CLI and Codex
  skills. The plan must preserve that written exemption and must not broaden the
  feature silently.
- **Other CLIs may display the shared backend choice but are not certified by
  this feature.** The shared vocabulary remains uniform, while supported usage,
  request shapes, and end-to-end acceptance are limited to the consistency
  auditor until separate work adopts the backend elsewhere.
- **No persistent campaign state changes shape.** This feature adds an
  execution choice and updates skill invocation behavior; it does not migrate
  configuration or rewrite campaign data.
