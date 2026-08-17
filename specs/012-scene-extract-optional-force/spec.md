# Feature Specification: Optional Force for Scene Re-Extraction

**Feature Branch**: `012-scene-extract-optional-force`

**Created**: 2026-08-16

**Status**: Draft

**Input**: User description: "CG #323"

GitHub issue: [kostadis/CampaignGenerator#323](https://github.com/kostadis/CampaignGenerator/issues/323) — "Re-Extract Quotes always forces a full re-extraction — no resumable or per-scene option"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Fill in missing scenes without redoing finished ones (Priority: P1)

A GM is working Stage 2 of the Session Doc Editor. Most scenes already have
reviewed quote extractions; one or two scenes are missing (new scenes added
to `session-summary.md`, or an earlier run was interrupted). The GM clicks
"Re-Extract Quotes" expecting only the missing scenes to be generated.

**Why this priority**: This is the actual defect. Today's behavior burns an
LLM call on every scene — including ones the GM already reviewed and
approved — every time this button is clicked. It's the single most common
Stage 2 action (any campaign, any session) and currently the most wasteful
one. Fixing the default is the whole point of the feature.

**Independent Test**: In a session with N scenes where N-2 already have
extraction files, click "Re-Extract Quotes" without enabling Force. Confirm
exactly 2 scenes are generated, the other N-2 files and their reviewed
markers are untouched, and the run reports each scene's outcome (skipped vs.
generated).

**Acceptance Scenarios**:

1. **Given** a session with some scenes already extracted and reviewed and
   some scenes missing an extraction file, **When** the GM clicks
   "Re-Extract Quotes" with Force off (the default), **Then** only the
   scenes missing a file are generated, and every existing scene file and
   its reviewed marker are left exactly as they were.
2. **Given** a session where every scene already has an extraction file,
   **When** the GM clicks "Re-Extract Quotes" with Force off, **Then** no
   scene is regenerated and the GM is told the run found nothing to do.
3. **Given** a session where `session-summary.md` was edited to add a new
   scene, **When** the GM clicks "Re-Extract Quotes" with Force off,
   **Then** the new scene is generated and all pre-existing scenes are
   skipped.

---

### User Story 2 - Deliberately redo every scene (Priority: P2)

A GM has substantially rewritten `session-summary.md` (e.g., corrected scene
boundaries or dialogue throughout) and wants every scene's extraction
regenerated from scratch, accepting that this overwrites existing files and
clears their reviewed status. Today this is the only behavior available;
after the P1 fix it must remain available, just as an explicit choice.

**Why this priority**: The GM's existing "redo everything" workflow must not
be lost — the issue explicitly calls this out as a real, intentional
capability, not an oversight to delete. It's second priority because it's
the less frequent path (a full rewrite of the summary is rarer than filling
a gap), and P1 has to land first for this to be a meaningful *choice* rather
than the only option.

**Independent Test**: In a session where every scene already has an
extraction file, explicitly enable the Force control and click "Re-Extract
Quotes". Confirm every scene is regenerated, prior content for each changed
scene is preserved as a snapshot, and every reviewed marker is cleared.

**Acceptance Scenarios**:

1. **Given** a session with existing, reviewed scene extractions, **When**
   the GM explicitly enables Force and clicks "Re-Extract Quotes", **Then**
   every scene is regenerated, each changed scene's prior content is
   snapshotted rather than silently discarded, and all reviewed markers are
   cleared.
2. **Given** Force is off, **When** the GM looks at the Stage 2 controls,
   **Then** there is a visible, explicit way to turn Force on before running
   — it is never inferred from clicking the main action alone.

---

### User Story 3 - Understand what a run will do before it runs (Priority: P3)

A GM wants to know, before clicking "Re-Extract Quotes", whether the run
will touch only missing scenes or overwrite everything — so a full overwrite
is never a surprise.

**Why this priority**: Lower priority because it's a clarity/safety
refinement on top of P1+P2 rather than new capability — the GM can already
tell by checking the Force control's own state. It matters because clearing
reviewed markers is destructive and campaign work already lost time once to
an unreviewed autonomous overwrite (see `docs/cli/transcript_corrections_howto.md`
scar and the Constitution's Principle X).

**Independent Test**: With Force toggled on, confirm the action control (or
its label/tooltip) communicates that the next run will overwrite every scene
and clear reviewed markers, before the GM commits to running it.

**Acceptance Scenarios**:

1. **Given** Force is currently on, **When** the GM inspects the Re-Extract
   control before clicking it, **Then** the interface states that running
   now will regenerate every scene and clear reviewed markers.
2. **Given** Force is currently off, **When** the GM inspects the Re-Extract
   control, **Then** the interface states that running now only fills in
   missing scenes and leaves existing ones untouched.

---

### Edge Cases

- A scene's extraction file exists but is empty or malformed — treated as
  "exists" (skipped in the default mode) exactly as it is today; not a new
  case introduced by this feature.
- The GM enables Force, the run starts, and they navigate away or the stream
  drops mid-run — behavior matches today's existing run/abort/stream-error
  handling; unaffected by this feature.
- The GM toggles Force on, then off again, without running — no action is
  taken until "Re-Extract Quotes" is clicked; toggling alone changes nothing
  on disk.
- The Force control's state does not carry over as a silent default the next
  time the GM opens or returns to the editor — every run starts from the
  safe (skip-existing) default, so a full overwrite is always a fresh,
  deliberate choice (Constitution Principle X).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The Re-Extract Quotes action MUST default to skip-existing
  (resumable) behavior: scenes that already have an extraction file on disk
  are left untouched unless Force is explicitly enabled.
- **FR-002**: The interface MUST provide an explicit Force control next to
  the Re-Extract Quotes action, visibly distinct from the action button
  itself, defaulting to off.
- **FR-003**: When Force is enabled and the GM triggers Re-Extract, every
  scene MUST be regenerated — matching today's existing full-redo behavior
  (prior content snapshotted per changed scene, reviewed markers cleared).
- **FR-004**: When Force is disabled (the default) and the GM triggers
  Re-Extract, only scenes without an existing extraction file MUST be
  regenerated; scenes that already have a file MUST be left unchanged,
  including their reviewed status.
- **FR-005**: The run's output MUST report, per scene, whether it was
  skipped (already existed) or generated, so the GM can see the scope of
  what actually happened.
- **FR-006**: Enabling Force MUST be a fresh, visible choice on every visit
  to the editor — the control MUST NOT silently default to "on" from a
  prior session or a prior run.
- **FR-007**: Before a Force-enabled run executes, the interface MUST make
  clear that it will overwrite every existing scene extraction and clear
  reviewed markers.
- **FR-008**: The skip-existing and force-all behaviors MUST be driven by
  the same underlying extraction engine and its existing on-disk
  skip/snapshot/clear-marker rules — the web UI exposes a choice between two
  behaviors the engine already supports, it does not introduce a second
  implementation of either.

### Key Entities

- **Scene extraction file**: The per-scene output of Stage 2 (one file per
  scene). Has an existence state (present/missing on disk) that determines
  whether the default run touches it, and a reviewed marker that Force
  clears when the file is regenerated.
- **Force selection**: The GM's explicit, per-run choice of whether
  Re-Extract Quotes should skip existing scenes or regenerate all of them.
  Not persisted as a hidden default between runs.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a session where only some scenes are missing an extraction,
  a default (Force-off) Re-Extract run regenerates exactly the missing
  scenes — not the full scene count.
- **SC-002**: A GM can fill in missing scenes without losing the reviewed
  status of scenes they already approved, in every default (Force-off) run.
- **SC-003**: A GM retains a one-action way to regenerate every scene in a
  session when they want to, with no loss of today's full-redo capability.
- **SC-004**: For a session with mostly-complete scenes (e.g., 2 missing out
  of 10), a default Re-Extract run's LLM spend drops by at least 70%
  compared to today's always-full-redo behavior for the same session.
- **SC-005**: Every full-scene overwrite happens only after the GM has taken
  a visible, distinct action (enabling Force) beyond clicking the main
  Re-Extract button — zero full overwrites occur from the default click.

## Assumptions

- The fix is scoped to a session-wide Force on/off choice, not a per-scene
  picker — matching the "Fix direction (agreed)" in issue #323. Per-scene
  selection (choosing exactly which of N scenes to regenerate) is a
  separate, larger feature and out of scope here.
- The skip-if-exists engine behavior and the `--force` full-redo behavior
  already exist in the underlying extraction engine and its CLI; this
  feature is about exposing the existing default (skip) instead of always
  overriding it, plus giving the GM an explicit way to opt back into the
  existing force behavior.
- No additional confirmation dialog (beyond the Force control's own visible
  on/off state and label) is required before a Force-enabled run; this
  matches the confirmation pattern already used by the editor's other
  actions.
- Enabling Force applies to the whole run it triggers; it is not a
  persistent session or user preference remembered across page loads.
