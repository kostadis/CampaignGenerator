# Feature Specification: Prefer Smoothed Scene Extractions for Narration

**Feature Branch**: `018-prefer-smoothed-extractions`

**Created**: 2026-08-28

**Status**: Draft

**Input**: User description: "After I create `scene_extractions_smoothed`, the UI still uses `scene_extractions_new` as input to the Narrate command. The UI should show where the smoothed voice files are and use them if they are present."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Narrate from the smoothed voice layer (Priority: P1)

A GM reviews the raw scene extractions, creates a voice-smoothed version in
`scene_extractions_smoothed`, and returns to the Session Doc UI to narrate a
scene. The Narrate action uses that scene's smoothed extraction instead of the
corresponding file in `scene_extractions_new`, without requiring the GM to
reconfigure the editor or copy the smoothed text over the raw file.

**Why this priority**: The smoothed layer exists specifically to provide the
voice-ready wording that narration should render. Continuing to use the raw
layer discards the GM's reviewed work and produces narration from the wrong
source.

**Independent Test**: Put distinguishable content for one scene in both the
raw and smoothed extraction directories, invoke Narrate for that scene from
the UI, and confirm the resulting narration is grounded in the smoothed
content.

**Acceptance Scenarios**:

1. **Given** a scene has both a raw extraction and a smoothed extraction,
   **When** the GM invokes Narrate for that scene, **Then** Narrate consumes the
   smoothed extraction.
2. **Given** the editor was opened before the smoothed extraction was created,
   **When** the GM creates it and then invokes Narrate, **Then** the newly
   present smoothed extraction is used without a page reload or configuration
   change.
3. **Given** a smoothed extraction is selected for narration, **When** the
   narration run starts, **Then** the exact smoothed source shown to the GM is
   the source consumed by the run.

---

### User Story 2 - See the source Narrate will use (Priority: P1)

Before spending tokens on Narrate, the GM can see the location of the
voice-smoothed extraction directory and, for the current scene, whether the
smoothed file exists and is the active narration input. When Narrate will fall
back to the raw layer, the UI says so and shows that source instead.

**Why this priority**: Automatic preference is only safe if it is visible.
The GM must be able to review the same file the Narrate action will consume,
rather than trust hidden selection state.

**Independent Test**: Open the same scene first with no smoothed file and then
with one present. Confirm the UI identifies the raw file as active in the
first state, the smoothed file as active in the second, and displays the
resolved smoothed location in both states.

**Acceptance Scenarios**:

1. **Given** the current session has a `scene_extractions_smoothed` directory,
   **When** the GM views the Session Doc UI, **Then** the UI displays its
   resolved location and whether it contains an eligible file for the current
   scene.
2. **Given** an eligible smoothed file exists for the current scene, **When**
   the GM views that scene, **Then** the UI identifies the smoothed file as the
   active Narrate input.
3. **Given** no eligible smoothed file exists for the current scene, **When**
   the GM views that scene, **Then** the UI identifies the raw extraction as
   the fallback Narrate input and does not imply that smoothing was applied.
4. **Given** the active source changes on disk, **When** the scene state is
   refreshed or Narrate is invoked, **Then** the displayed source updates to
   match the source that will actually be used.

---

### User Story 3 - Continue safely with partial or absent smoothing (Priority: P2)

A GM may smooth scenes incrementally. Scenes already smoothed use their
voice-ready files; scenes not yet smoothed continue to use their raw
extractions. An incomplete smoothed directory therefore does not block the
whole session or cause one scene's input to be substituted for another.

**Why this priority**: This preserves the existing raw-only workflow and lets
the GM adopt smoothing one scene at a time, while keeping selection explicit
and predictable.

**Independent Test**: Create raw extractions for three scenes and smoothed
extractions for only scenes one and three. Narrate all three from the UI and
confirm scenes one and three use their smoothed files while scene two uses its
raw file.

**Acceptance Scenarios**:

1. **Given** the smoothed directory exists but the current scene has no
   smoothed file, **When** the GM invokes Narrate, **Then** that scene's raw
   extraction is used.
2. **Given** no smoothed directory exists, **When** the GM uses the existing
   narration workflow, **Then** all scenes continue to use the configured raw
   extraction layer with no added setup.
3. **Given** neither a smoothed nor raw extraction exists for the current
   scene, **When** the GM attempts Narrate, **Then** the run is refused with a
   message that names both locations checked.

---

### Edge Cases

- **The smoothed directory exists but is empty.** It is shown as present, but
  no scene is labelled smoothed and each scene falls back independently to its
  raw extraction.
- **The smoothed directory contains only notes or sibling artifacts.** Files
  that are not eligible scene extractions do not make the smoothed layer
  active.
- **Only some scenes have been smoothed.** Selection is made per scene; the
  existence of one smoothed file never redirects an unsmoothed scene to a
  missing input.
- **Both an edited scaffold and its ordinary sibling exist in the smoothed
  layer.** The same established precedence used when loading scene
  extractions determines which one is active, so the UI and Narrate do not
  disagree.
- **A matching smoothed file exists but cannot be read.** The UI reports that
  the preferred source is unusable and Narrate refuses to run; it does not
  silently discard the GM's smoothed work by falling back to raw content.
- **The smoothed file is added, removed, or renamed while the UI is open.**
  The next refresh or Narrate action re-evaluates disk state and does not rely
  on stale browser-only state.
- **Raw and smoothed files use different descriptive slugs.** The established
  scene identity and ordering rules, rather than an exact full filename match,
  determine whether the smoothed file belongs to the selected scene.
- **The configured raw extraction directory uses a custom location.** It
  remains the fallback source; automatic smoothed-layer preference does not
  overwrite or relocate it.
- **A smoothed source emits an existing content warning.** Selection still
  occurs, the warning remains visible, and no new silent content correction is
  introduced by this feature.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: For every Narrate action initiated from the UI, the system MUST
  determine the current scene's input from the files that exist at the time
  the action begins.
- **FR-002**: If an eligible smoothed extraction exists for the selected
  scene, the system MUST use that extraction as the Narrate input in
  preference to the raw extraction.
- **FR-003**: If no eligible smoothed extraction exists for the selected
  scene, the system MUST use the configured raw extraction for that scene.
- **FR-004**: Smoothed-input preference and raw fallback MUST be evaluated per
  scene, so a partial smoothed layer remains usable without requiring every
  scene to be smoothed.
- **FR-005**: The Session Doc UI MUST display the resolved location of the
  current session's smoothed extraction directory, including an explicit
  not-present state.
- **FR-006**: For the selected scene, the UI MUST display the exact active
  Narrate source, identify it as smoothed or raw, and indicate whether it is
  available.
- **FR-007**: The source displayed for a scene MUST be the same source the
  subsequent Narrate action consumes. Source selection MUST NOT exist only as
  hidden or browser-local state.
- **FR-008**: The active source indication MUST be refreshed after a scene
  change, an explicit state refresh, and completion of any operation that may
  change scene extraction files.
- **FR-009**: The system MUST re-check the active source immediately before
  Narrate begins, so a file change made outside the UI is respected without a
  page reload or configuration edit.
- **FR-010**: If the preferred smoothed file is present but unreadable, the
  system MUST refuse Narrate and identify that file as the problem rather than
  silently falling back to raw content.
- **FR-011**: If neither source has an eligible file for the selected scene,
  the system MUST refuse Narrate and show the GM the smoothed and raw
  locations that were checked.
- **FR-012**: Files that the existing scene-extraction workflow would ignore
  MUST NOT count as evidence that a smoothed extraction is available.
- **FR-013**: The feature MUST preserve the established rule for choosing
  between multiple eligible files for the same scene, including edited-file
  precedence.
- **FR-014**: Discovering or using a smoothed extraction MUST NOT copy,
  rewrite, rename, delete, or otherwise mutate either the raw or smoothed
  source.
- **FR-015**: When no smoothed scene extractions exist, the existing raw-only
  UI narration workflow MUST continue without additional configuration or
  user action.
- **FR-016**: This feature MUST affect the input selected for Narrate only; it
  MUST NOT silently change the inputs used by extraction, quote verification,
  planning, consistency checks, or other pipeline stages.

### Key Entities

- **Raw scene extraction**: The existing per-scene source, commonly stored in
  `scene_extractions_new`, produced by the extraction stage and retained as
  the fallback when no smoothed counterpart exists.
- **Smoothed scene extraction**: A voice-edited per-scene derivative stored in
  `scene_extractions_smoothed`. It is the preferred Narrate source for its
  scene but does not replace or modify the raw extraction.
- **Active Narrate source**: The one resolved scene-extraction file that the UI
  shows and the next Narrate action will consume, together with its layer type
  and availability state.
- **Scene identity**: The stable association that lets the system match raw
  and smoothed files to the same scene even when their descriptive filename
  portions differ.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a test set containing raw-only, smoothed-only, both-layer,
  and partially smoothed sessions, 100% of Narrate actions use the source
  required by the smoothed-first, per-scene fallback rule.
- **SC-002**: For 100% of scenes shown in the UI, the active source displayed
  immediately before Narrate is the source consumed by that run.
- **SC-003**: A GM can create a smoothed file outside the UI and use it in the
  next Narrate action with zero configuration changes, zero file copies, and
  zero page reloads.
- **SC-004**: In a session with no smoothed files, 100% of previously valid
  Narrate actions continue to succeed from their raw inputs without any new
  setup step.
- **SC-005**: A GM can identify both the resolved smoothed directory and the
  selected scene's active Narrate source from the Session Doc UI before
  starting a token-spending run.
- **SC-006**: When no eligible source exists or the preferred source is
  unreadable, 100% of refused runs name the relevant checked path or failing
  file, with zero silent fallbacks from an unusable smoothed file.

## Assumptions

- The request establishes a deliberate **smoothed-over-raw** precedence for
  Narrate. It does not add a manual layer selector: the smoothed file is used
  when present for that scene, and the configured raw layer is the fallback.
- `scene_extractions_smoothed` is a derived layer beside the other artifacts
  for the current session. The feature discovers it from the current session
  rather than requiring a second stored configuration path.
- “Present” means an eligible scene-extraction file exists for the selected
  scene. Merely creating the directory, or placing unrelated files in it,
  does not redirect Narrate.
- The existing rules for scene-file eligibility, scene matching, and edited
  scaffold precedence remain authoritative and are shared by UI display and
  Narrate selection.
- The UI exposes the file handoff and invocation; review and editing remain
  file-based human checkpoints. This feature does not add automatic smoothing,
  content rewriting, or a new model call.
- The Narrate operation remains the existing engine. The UI selects and shows
  its file input but does not implement a separate narration path.
- No on-disk schema or workspace layout changes. Existing raw and smoothed
  directory conventions are consumed as-is, so no migration is required.
- Updating Plan & Check or any non-Narrate operation to prefer smoothed files
  is outside this feature's scope.
