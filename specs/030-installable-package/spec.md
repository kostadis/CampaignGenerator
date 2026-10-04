# Feature Specification: Installable CampaignGenerator package

**Feature Branch**: `main` (no branch hook configured)

**Created**: 2026-10-04

**Status**: Draft

**Input**: User description: "issue #494" — [Make CampaignGenerator installable](https://github.com/kostadis/CampaignGenerator/issues/494)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Use an installed copy away from the checkout (Priority: P1)

An operator installs CampaignGenerator into a fresh environment and runs its tools from a different working directory. Shipped prompts, templates, reference data, and other read-only resources are available without a source checkout. Installed commands do not attempt to write into the installed code.

**Why this priority**: Today installation completes but importing the package fails while looking for a prompt in the source tree. This prevents every installed command from starting and blocks the CampaignGenerator step of the external installer.

**Independent Test**: Install a built distribution into a fresh environment, change to an unrelated directory, import the five named package areas, and run `registry --help`, `distill --help`, and `sd_verify_quotes --help`.

**Acceptance Scenarios**:

1. **Given** a fresh, non-editable installation and an unrelated working directory, **When** the operator imports `campaignlib`, `session_doc`, `pipelines`, `entity_registry`, and `provenance`, **Then** all five imports complete without a missing-resource error.
2. **Given** that installation, **When** the operator invokes the three representative commands for help, **Then** each command starts and shows its help text.
3. **Given** a tool that uses a shipped read-only resource, **When** it runs from outside the checkout, **Then** it reads the resource successfully without requiring a source-tree path.
4. **Given** an installed command that creates or changes state, **When** it runs, **Then** its output is placed in the selected campaign workspace or a documented user data location, never in the installed code.

---

### User Story 2 - Preserve campaign prompt customization (Priority: P2)

A GM keeps a custom prompt in the campaign's `config/agents` directory. The installed application uses that prompt in preference to its shipped default. Campaign-specific configuration and explicit file choices remain usable.

**Why this priority**: Installation must not silently replace a GM's established prompt or change the campaign's output.

**Independent Test**: Put a distinct prompt override in a campaign directory, request it from an installed copy, then remove the override and request it again. The two requests must return the custom and shipped versions, respectively.

**Acceptance Scenarios**:

1. **Given** a campaign-local prompt and a shipped prompt with the same name, **When** the operator loads that prompt for the campaign, **Then** the campaign-local version wins.
2. **Given** no campaign-local override, **When** the operator loads a shipped prompt, **Then** the shipped version is available from an unrelated working directory.
3. **Given** a request for a prompt absent from both locations, **When** it is loaded, **Then** the operator gets an error that names the missing prompt and the relevant locations.

---

### User Story 3 - Use external wiring after installation (Priority: P2)

An operator installs CampaignGenerator through the wider system and expects it to use the external service settings rendered by mneme. Those settings live outside the installed application and are discoverable by both the renderer and CampaignGenerator.

**Why this priority**: A packaged application cannot depend on mneme writing a host-specific file into its installed code. An agreed location is necessary for the external installation path to work.

**Independent Test**: Render distinct external wiring through mneme, run an installed CampaignGenerator command from an unrelated directory, and confirm it reads the rendered values.

**Acceptance Scenarios**:

1. **Given** mneme-rendered external wiring, **When** the installed application starts, **Then** it reads that wiring from the agreed external location.
2. **Given** a deliberate wiring location supplied by the operator, **When** the application starts, **Then** that location takes precedence over the default location.
3. **Given** no external wiring, **When** a feature that permits absent wiring starts, **Then** it retains the current empty/default behavior rather than failing during import.
4. **Given** external wiring at the former checkout location, **When** the operator upgrades, **Then** a documented, separately invoked migration moves that state to the chosen location and explains how to update mneme's render target; normal application startup does not silently migrate it.

---

### User Story 4 - Keep the source-checkout workflow usable (Priority: P3)

An operator who runs CampaignGenerator from its checkout continues to use `./start` and existing campaign workspaces after the packaging changes.

**Why this priority**: The installed path is an addition to an established run-in-place workflow, which operators still use for the web UI.

**Independent Test**: Run `./start` from a checkout with an existing campaign and confirm the service starts and serves its usual interface.

**Acceptance Scenarios**:

1. **Given** a working source checkout and an existing campaign, **When** the operator runs `./start`, **Then** the application starts and serves the campaign interface.
2. **Given** an installed copy, **When** the operator follows the installed-mode guidance, **Then** it directs them to installed commands for CLI use and to `./start` from a checkout for the web UI.

### Edge Cases

- A resource exists in the checkout but was omitted from the built distribution: installation verification must fail before release.
- A local prompt shares a name with a shipped prompt: the local prompt wins, including when the application was installed as a package.
- The operator starts a command from an unrelated working directory with no campaign selected: shipped defaults remain readable; commands that require campaign state report that requirement clearly.
- An explicit resource path is missing: the application reports the missing path rather than silently substituting an unrelated shipped resource.
- An installed command needs writable state: it must use the selected campaign or documented user data location, including in a read-only installed environment.
- External wiring is absent or malformed: absent wiring retains current optional behavior; malformed wiring is reported at the point it is needed.
- Legacy wiring remains at a known source checkout: checkout startup refuses it and tells the operator to run the migration and update mneme rather than silently reading both locations. An installed process cannot discover an arbitrary checkout that was not supplied to it; operators upgrading from such a checkout must run the documented migration before installed use.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A non-editable installation MUST make all five package areas named in User Story 1 importable from outside the source checkout.
- **FR-002**: Installed console commands MUST start from outside the source checkout. At minimum, `registry --help`, `distill --help`, and `sd_verify_quotes --help` MUST complete successfully.
- **FR-003**: Every read-only prompt, template, reference file, or other application resource needed at runtime MUST be available in the installed distribution and readable independently of the source checkout.
- **FR-004**: The 17 resource lookups identified in issue #494 MUST each be classified and verified as a shipped read-only resource, campaign or user resource, external wiring, package-local file, or web build artifact. No lookup may depend solely on an accidental checkout-relative path.
- **FR-005**: Campaign-local agent prompts MUST take precedence over shipped defaults; a missing local override MUST use the corresponding shipped prompt.
- **FR-006**: Missing explicitly selected resources MUST produce a clear error identifying the requested resource; they MUST NOT silently fall back to a different resource.
- **FR-007**: Installed CampaignGenerator MUST look for mneme-rendered external `wiring.yaml` at `~/.config/campaigngenerator/wiring.yaml` by default, and mneme's render target MUST agree with that location.
- **FR-008**: An operator-supplied explicit wiring path MUST take precedence over any default wiring location; absent wiring MUST preserve current optional behavior.
- **FR-009**: Runtime writes MUST go to the selected campaign workspace or a documented user data location, not beside installed application files.
- **FR-010**: The source-checkout `./start` workflow MUST continue to start and serve the existing interface.
- **FR-011**: The installed distribution MUST support CLI use without requiring web UI assets. The web UI MUST remain available through `./start` from a source checkout; installed-mode guidance MUST state this boundary.
- **FR-012**: Release verification MUST build a distribution, install it non-editably into a fresh environment, and run the import and representative command checks from an unrelated directory.
- **FR-013**: Installation guidance MUST describe the supported installed and run-in-place modes, the chosen external wiring location, prompt override precedence, and where runtime output is written.
- **FR-014**: The secondary dependency installation instructions MUST agree with the application's declared dependencies, without maintaining an independent unbounded list.
- **FR-015**: Moving existing external wiring from the checkout MUST use a separate, deliberate migration step. Normal application use MUST neither rewrite that state nor silently read the retired location. When startup knows a checkout path containing retired wiring, it MUST refuse that file with the migration command in the error; upgrade guidance MUST require migration before installed use when the installed process has no checkout reference.
- **FR-016**: Migration guidance MUST identify affected workspaces, the exact migration command, the required mneme render-target change, behavior before migration, and a way to verify the result.

### Key Entities

- **Shipped resource**: A read-only prompt, template, reference file, or package-local file required by a runtime command; identified by purpose and included in the installed distribution.
- **Campaign override**: A campaign-owned prompt or configuration file whose explicit local choice takes precedence over a shipped default.
- **External wiring**: Mneme-owned host settings rendered outside the installed application and read at runtime.
- **Runtime output**: A file or state change produced by a command, owned by a campaign workspace or user data location.
- **Installed distribution**: The artifact installed without a source checkout and expected to contain every shipped runtime resource.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a fresh, non-editable installation tested from outside the checkout, all five named package areas import successfully and all three representative commands start successfully, with zero missing-resource errors.
- **SC-002**: All 17 resource lookups identified in issue #494 have an explicit classification and a passing installed-mode verification appropriate to that classification.
- **SC-003**: In 100% of tested same-name prompt pairs, the campaign override is selected; in 100% of tested no-override cases, the shipped prompt is selected.
- **SC-004**: A write-producing installed-mode command creates its output in a temporary workspace and leaves the installed application directory unchanged in release verification.
- **SC-005**: A configured installation reads the rendered external wiring in 100% of the installation smoke scenarios, and `./start` continues to serve the existing interface in the source-checkout smoke scenario.
- **SC-006**: An operator can complete the documented installation and verify a representative command from an unrelated directory in under 10 minutes, excluding environment creation and dependency download time.
- **SC-007**: In an upgrade scenario with wiring at the former location, the operator can run the documented migration and verify that the installed application reads the same settings from the new location, with no silent state change during ordinary startup.

## Assumptions

- Issue #494 is the scope authority. Dependency bounds tracked by #493 are separate; both contribute to the wider installation goal in [mneme#50](https://github.com/kostadis/mneme/issues/50).
- Campaign-local prompt precedence is already specified by issue #494 and its acceptance criteria, so it does not require another decision.
- Existing campaign workspaces and source-checkout use remain supported; a breaking move of campaign state requires the project's separate migration workflow and documentation.
- The existing operator-supplied wiring path remains supported. The chosen default location assumes mneme and CampaignGenerator run as the same user; deployments that do not meet that assumption must use an explicit shared path.
- The operator chose CLI-only installed mode and the source-checkout `./start` path for the web UI on 2026-10-04.
- Python 3.10 is the oldest supported interpreter for this distribution. The former `>=3.9` declaration could not install the existing `mcp` dependency, and the wheel's existing imports raised on 3.9 type annotations; release checks cover 3.10 and 3.14.
- Updating mneme's render target is a coordinated dependency because that repository owns production of the external wiring.
