# Feature Specification: Scene Extraction Token Limit from the UI

**Feature Branch**: `011-extract-max-tokens`

**Created**: 2026-08-17

**Status**: Draft

**Input**: User description: "scene_extract does not take the value of max_tokens that sd_narrate does from the UI (use codememory_mcp to verify). I want to change it so it does."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Set a per-scene output cap before extracting (Priority: P1)

A GM running the Session Doc Editor's Stage 2 (Extract) is working with scenes
that run long, or with a model whose default output cap is either too small
(truncated extractions) or unnecessarily large (slower / costlier runs). Today
the Narrate stage (Stage 4) exposes a "Token limit" field in the Config drawer
that the GM can raise or lower per campaign; the Extract stage exposes no such
control at all — every extraction run is silently capped at the tool's
built-in default, with no way to see or change it from the UI. The GM wants
the same kind of control for Extract that they already have for Narrate.

**Why this priority**: This is the entire feature. Without it there is no
functioning capability to test or ship.

**Independent Test**: Open the Session Doc Editor's Config drawer for a
campaign, find a token-limit field under the Extract section, change it to a
non-default value, save, then run Stage 2 (Extract or Re-Extract). Confirm the
run used the configured value rather than the tool's built-in default (e.g. by
observing a scene whose extraction would have been truncated at the default
but is not truncated at the raised value).

**Acceptance Scenarios**:

1. **Given** a campaign whose Extract token limit has never been set, **When**
   the GM opens the Config drawer, **Then** the Extract section shows a token
   limit field pre-populated with the tool's documented default value.
2. **Given** the GM changes the Extract token limit to a new value and saves
   the campaign's editor configuration, **When** the GM runs Stage 2 (Extract
   or Re-Extract), **Then** the extraction run is capped at the newly
   configured value, not the old one.
3. **Given** the GM has configured an Extract token limit, **When** the GM
   reopens the Config drawer in a later session, **Then** the field still
   shows the previously saved value (the setting persists with the rest of
   the campaign's editor configuration).

---

### Edge Cases

- What happens when the GM enters a value below a sane minimum (e.g. 0 or a
  negative number)? The field must behave like the existing Narrate token
  field, which enforces a minimum via its input control.
- What happens to a campaign that has never configured this value (pre-feature
  campaigns, or a campaign whose editor config file predates this feature)?
  Extraction must still run successfully, using the same default the
  extraction tool has always used, so existing campaigns see no behavior
  change until the GM opts in.
- What happens if the GM sets an extremely large value that exceeds what the
  active model/backend can actually return? Existing error handling for
  oversized/truncated model output responses applies unchanged; this feature
  only changes what value is sent, not how such errors are surfaced.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The Session Doc Editor's Config drawer MUST present a token
  limit field for the Extract stage, following the same presentation pattern
  (labeled numeric field with helper text) already used for the Narrate
  stage's token limit field.
- **FR-002**: The Extract stage's token limit MUST be persisted as part of the
  campaign's editor configuration, the same way the Narrate stage's token
  limit is persisted, so it survives across editor sessions and page reloads.
- **FR-003**: When the GM triggers Stage 2 (Extract or Re-Extract), the
  configured Extract token limit MUST be forwarded to the extraction run and
  MUST determine the per-scene output cap actually used.
- **FR-004**: A campaign that has not set an Extract token limit MUST extract
  using the extraction tool's existing built-in default, unchanged from
  current behavior — this feature must not alter output for campaigns that
  don't opt in.
- **FR-005**: The Extract token limit field MUST default, when never
  configured, to the same numeric value the extraction tool already uses as
  its built-in default, so the UI's shown default matches what actually runs.
- **FR-006**: Saving an Extract token limit that is out of the field's allowed
  range (e.g. non-numeric, zero, or negative) MUST be prevented or corrected
  by the field itself, mirroring how the Narrate token field already
  constrains input.

### Key Entities

- **Editor configuration (per campaign)**: The persisted set of Session Doc
  Editor settings for a campaign, already holding a Narrate token limit among
  other per-stage knobs. This feature adds an equivalent Extract token limit
  to that same persisted set.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A GM can change the Extract stage's output token cap from the
  UI and see that value take effect on the very next extraction run, with no
  need to edit any file by hand or pass a command-line flag manually.
- **SC-002**: Every existing campaign continues to extract scenes exactly as
  it did before this feature ships, unless and until the GM explicitly
  changes the new field.
- **SC-003**: The Extract token limit setting survives a page reload and a
  full editor restart, matching the persistence behavior of every other
  per-stage knob already in the Config drawer.

## Assumptions

- The "value of max_tokens that sd_narrate does from the UI" referenced in the
  feature request is the existing Narrate "Token limit" field in the Session
  Doc Editor's Config drawer (persisted, default 16000, forwarded to the
  narration run) — verified via the codebase graph (`codebase-memory-mcp`)
  against `server/session_editor_config_shared.py`, `server/routers/
  scene_editor.py`, and `frontend/src/components/scene-editor/KnobDrawer.vue`.
  The equivalent gap on the Extract side — no persisted config field, no
  drawer control, and no value forwarded to the extraction run when the GM
  clicks Extract/Re-Extract — is confirmed the same way.
- This feature targets the Session Doc Editor's Stage 2 (Extract / Re-Extract)
  flow specifically; it does not add a token-limit control to any other UI
  surface that might separately invoke the extraction tool.
- The extraction tool's current built-in default output cap remains the
  default a campaign sees until the GM changes it — this feature is additive
  (expose and wire an existing capability) rather than a change to what any
  campaign already produces today.
- "Token limit" means the per-scene maximum output tokens the extraction call
  is allowed to produce, matching the meaning of the existing Narrate token
  limit field.
