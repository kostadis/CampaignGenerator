# Feature Specification: CampaignGenerator Top-Level Command

**Feature Branch**: `025-add-cg-command`
**Created**: 2026-08-31
**Status**: Draft
**Input**: User description: "The command line has a set of commands, but no top-level command that lists them. I want a top-level command called `cg` that lists all subcommands and allows me to invoke them."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Discover available commands (Priority: P1)

An operator runs `cg` without a subcommand and sees the commands available through CampaignGenerator, with enough concise information to identify the capability they need without remembering its name.

**Why this priority**: Discoverability is the central user problem. A launcher that dispatches commands but does not reveal them still requires memorization.

**Independent Test**: Install the tool, run `cg` with no arguments, and verify that successful output identifies every supported subcommand and briefly describes each one.

**Acceptance Scenarios**:

1. **Given** CampaignGenerator is installed, **When** the operator runs `cg` with no arguments, **Then** it prints the available subcommands and exits successfully.
2. **Given** the command list is displayed, **When** the operator scans it, **Then** each entry includes its invocation name and a concise distinguishing description.
3. **Given** a command is supported by `cg`, **When** the operator views the listing, **Then** that command appears exactly once under a meaningful category or ordering.

---

### User Story 2 - Invoke a command through cg (Priority: P1)

After finding a command, an operator invokes it as `cg <subcommand>` and supplies the same arguments they would supply to the existing standalone command. The invoked capability behaves the same way and returns the same result.

**Why this priority**: The list becomes a useful top-level interface only when discovered commands can be run through it. Preserving behavior avoids creating a second CLI dialect.

**Independent Test**: Invoke representative commands with and without arguments both directly and through `cg`, then verify equivalent output, effects, and exit status.

**Acceptance Scenarios**:

1. **Given** a listed subcommand requires no additional arguments, **When** the operator runs `cg <subcommand>`, **Then** the corresponding existing capability runs.
2. **Given** a listed subcommand accepts options and positional arguments, **When** they follow the subcommand, **Then** they retain the standalone command's spelling, defaults, and meaning.
3. **Given** the invoked capability succeeds or fails, **When** it finishes, **Then** `cg` reports the same observable output and completion status.

---

### User Story 3 - Get guidance and correct mistakes (Priority: P2)

An operator can request top-level help, request help for a subcommand, and receive useful guidance after entering an unknown subcommand rather than encountering an opaque failure.

**Why this priority**: A discoverable command family must remain navigable and make typing mistakes inexpensive to correct.

**Independent Test**: Run top-level help, subcommand help, and an unknown command; verify that each response is understandable, invokes no unrelated work, and returns an appropriate status.

**Acceptance Scenarios**:

1. **Given** CampaignGenerator is installed, **When** the operator runs `cg --help`, **Then** usage and available subcommands appear without invoking a subcommand.
2. **Given** a listed subcommand, **When** the operator requests its help through `cg`, **Then** they see the same user-facing arguments and guidance available directly.
3. **Given** an unknown subcommand, **When** the operator runs it through `cg`, **Then** no capability runs, the response identifies the unknown name, points to valid choices, and exits unsuccessfully.

### Edge Cases

- Similar command names require a full exact match; the system never silently chooses another capability.
- Options before a subcommand are accepted only when documented as top-level options; ambiguous input shows usage without invoking work.
- `cg <subcommand> --help` reaches the selected command's help without duplicating its option definitions.
- Standard output, standard error, interactive input, and interruptions remain usable through `cg`.
- A non-zero subcommand status is preserved rather than changed to success.
- Adding or removing a supported command updates listing and dispatch together, preventing stale advertised commands.
- Internal or service-only entry points are omitted through an explicit support classification, not an accidental filter.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The installed tool MUST provide a top-level command named `cg`.
- **FR-002**: Running `cg` without a subcommand MUST display supported subcommands and exit successfully without invoking one.
- **FR-003**: Running `cg --help` MUST display top-level usage and supported subcommands without invoking one.
- **FR-004**: Each listed subcommand MUST include its invocation name and a concise user-facing description.
- **FR-005**: The listing MUST organize or order commands consistently for predictable scanning.
- **FR-006**: Every command classified as a supported operator-facing CampaignGenerator command MUST be listed and invokable through `cg`.
- **FR-007**: Commands not intended as supported operator-facing capabilities MUST be excluded based on an explicit classification.
- **FR-008**: `cg <subcommand>` MUST invoke the capability associated with that exact listed name.
- **FR-009**: Arguments after the subcommand MUST retain the standalone command's names, meanings, defaults, validation, and ordering rules.
- **FR-010**: Existing standalone command invocations MUST continue to work; adopting `cg` MUST NOT require immediate migration.
- **FR-011**: The invoked command's output streams, interactive behavior, and completion status MUST remain observable through `cg`.
- **FR-012**: Interrupting a command invoked through `cg` MUST interrupt that capability without starting or leaving an unrelated command.
- **FR-013**: An unknown subcommand MUST invoke nothing, identify the unrecognized name, direct the operator to valid choices, and return an unsuccessful status.
- **FR-014**: Operators MUST be able to request a listed subcommand's existing help through `cg`.
- **FR-015**: Listing and dispatch MUST share one authoritative supported-command catalog so displayed names cannot drift from invocation targets.
- **FR-016**: Adding, renaming, or removing a supported subcommand MUST require a description and update listing and dispatch together.
- **FR-017**: The top-level command MUST NOT duplicate business or pipeline behavior owned by existing commands.
- **FR-018**: The listing MUST work without campaign data, credentials, network access, or token-spending operations.
- **FR-019**: Scope is limited to CLI discovery and dispatch; no UI command palette is required because this organizes existing CLI entry points rather than adding a new pipeline capability.

### Key Entities

- **Supported command**: An operator-facing capability exposed under a stable subcommand name, description, and invocation target.
- **Command catalog**: The authoritative collection used by both top-level listing and dispatch.
- **Invocation**: Execution through `cg`, including the selected name, remaining arguments, input/output channels, and completion status.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A newly installed user can identify the appropriate command for five representative tasks using only `cg` output with at least 90% accuracy.
- **SC-002**: The listing displays within one second locally and performs zero campaign mutations or token-spending operations.
- **SC-003**: 100% of supported operator-facing commands appear exactly once and can be invoked by the displayed name.
- **SC-004**: Across representative successful, invalid-input, and interrupted runs, `cg` preserves standalone observable behavior and status in 100% of cases.
- **SC-005**: 100% of existing standalone command compatibility tests continue to pass.
- **SC-006**: At least 90% of users can discover and invoke a requested command on their first attempt without source code or external documentation.

## Assumptions

- Existing standalone names remain supported for compatibility and scripts.
- Initial `cg` names reuse existing public spellings, avoiding a second vocabulary.
- The project explicitly classifies operator-facing entry points; service launchers and internal utilities need not all become subcommands.
- Individual commands continue to own parsing, validation, help, side effects, and business behavior.
- A no-argument invocation succeeds because its requested default action is discovery.
- FR-019 is the deliberate exception to general CLI/UI parity: this launcher organizes existing CLI capabilities and adds no underlying pipeline capability.
