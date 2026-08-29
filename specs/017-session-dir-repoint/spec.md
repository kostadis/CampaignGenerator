# Feature Specification: Session Directory Re-Points Editor Paths

**Feature Branch**: `017-session-dir-repoint`

**Created**: 2026-08-28

**Status**: Draft

**Input**: User description: "Today, when I set the configuration in Session Config to a particular directory, the paths in the Session Doc Editor are not updated to reflect the directory I set. For example, if I set it to `summaries/20260825` but it was previously `20260811`, the paths in the config still reflect `20260811`. What I want is to set the path in Session Config and have the Session Doc Editor reflect that."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Switch sessions and start work immediately (Priority: P1)

A GM finishes one session's document and moves to the next. On the Session
Config screen they change the session directory from `summaries/20260811` to
`summaries/20260825` and save. They open the Session Doc Editor to begin
Stage 1.

Today the editor still shows every path rooted at `20260811` — the scene
extractions directory, the narration directory, the GM-assist recap, the
session summary. The GM either works against last session's files without
noticing, or discovers the mismatch mid-run and has to retype each path by
hand. This story is the whole point of the feature: one authoritative place
to say which session is current, and every downstream path follows it.

**Why this priority**: This is the defect the GM reported, and it sits on the
critical path of every single session. The session directory is *already*
declared to be the single place a session is named — on a screen whose stated
promise is "Everything else is derived automatically" — and it silently is
not. Nothing else in this feature matters if the switch does not take.

**Independent Test**: With a campaign whose current session directory is
`summaries/20260811`, change it on Session Config to `summaries/20260825`,
save, and open the Session Doc Editor without reloading the browser. Confirm
every session-scoped path shown in the editor is rooted at `20260825`.

**Acceptance Scenarios**:

1. **Given** a campaign whose session directory is `summaries/20260811` and
   whose editor paths all resolve under it, **When** the GM sets the session
   directory to `summaries/20260825` and saves, **Then** every session-scoped
   path the Session Doc Editor displays resolves under `summaries/20260825`.
2. **Given** the session directory has just been changed, **When** the GM
   navigates to the Session Doc Editor, **Then** the new paths are shown
   without the GM reloading the page or restarting the server.
3. **Given** the session directory has just been changed, **When** the GM runs
   any pipeline stage from the editor, **Then** the stage reads and writes
   under the new session directory only.
4. **Given** a campaign-scoped path (voice files, examples, party, genre
   rulebook), **When** the session directory changes, **Then** that path is
   unchanged — the switch re-points session-scoped paths only.

---

### User Story 2 - A session switch never pins the old session into stored config (Priority: P1)

The same GM makes the switch and then adjusts a knob in the editor's config
drawer — a token budget, a prose toggle — which auto-saves the whole path
block along with it.

Today that save writes back whatever paths the editor was holding. Because
those were resolved against the *previous* session directory, and because a
path that does not sit under the current session directory is treated as a
deliberate override and stored verbatim, the old session's location becomes
permanently pinned in the campaign's stored configuration. From that point on
the field stops tracking the session directory at all, and no later switch
will move it. The GM's config is silently, durably wrong.

**Why this priority**: Equal to Story 1, because it is what turns a
refreshable display bug into permanent data damage. A GM who works around
Story 1 by retyping paths still hits this. It must be impossible for a session
switch to leave a trace of the old session in stored config.

**Independent Test**: Change the session directory, then change any knob in
the editor drawer so the config auto-saves. Inspect the campaign's stored
session-editor configuration and confirm no session-scoped path names the
previous session directory.

**Acceptance Scenarios**:

1. **Given** the session directory was just changed from `20260811` to
   `20260825`, **When** any editor write occurs, **Then** no session-scoped
   path in stored configuration contains `20260811`.
2. **Given** the GM saves the Session Config screen (which writes both the
   session directory and several path fields), **When** the save completes,
   **Then** the stored path fields are interpreted against the *new* session
   directory, regardless of the order in which the two writes were applied.
3. **Given** a GM switches sessions three times in a row without reloading,
   **When** the third switch completes, **Then** stored configuration names
   only the third session — not an accumulation of the earlier two.

---

### User Story 3 - An already-damaged campaign heals itself (Priority: P2)

A GM has been running a campaign for months. Somewhere along the way a session
switch pinned an old session directory into stored configuration, so one or
more path fields have stopped tracking the session directory entirely. The GM
does not know which fields, or which campaigns, are affected.

When such a field is read, the system recognises it for what it is — a path
pointing into a *different session directory of the same campaign*, which is
never a meaningful thing to intend — re-points it onto the current session
directory, and says so. A path that points somewhere genuinely outside the
campaign's session-directory tree is a real override and is left alone.

**Why this priority**: Below P1 because P1 stops the bleeding for every future
switch; this recovers the campaigns already bleeding. It is still in scope
rather than deferred, because the GM cannot be expected to audit stored
configuration by hand across five campaigns to find damage they were never
told about.

**Independent Test**: Take a campaign whose stored configuration pins a
session-scoped path to a sibling session directory, set the current session
directory to a different one, and open the editor. Confirm the path is shown
under the current session directory, that the GM is told the re-point
happened, and that a path pinned outside the session-directory tree in the
same campaign is untouched.

**Acceptance Scenarios**:

1. **Given** a stored session-scoped path that names a sibling session
   directory of the current campaign, **When** the configuration is read,
   **Then** the path resolves under the *current* session directory.
2. **Given** the same, **When** the re-point happens, **Then** the GM is told
   which field was re-pointed and what it used to name — the correction is
   announced, never silent.
3. **Given** a stored session-scoped path pointing somewhere outside the
   campaign's session-directory tree, **When** the configuration is read,
   **Then** it is left exactly as stored and no notice is emitted.
4. **Given** a re-pointed field, **When** the configuration is next written
   for any reason, **Then** the healed value is what gets stored, so the field
   tracks the session directory from then on.

---

### User Story 4 - The GM can see which re-pointed paths do not exist yet (Priority: P2)

Re-pointing carries names, not files. `scene_extractions/` and `narration/`
are conventional and will exist or be created. But the GM-assist recap and the
session summary are named per session — a field holding
`session_2026_08_24_....md` is meaningless once the session directory is
`20260825`, even though it has been re-pointed correctly.

The editor shows, per path field, whether the resolved target actually exists,
so the GM sees at a glance which two or three fields need attention after a
switch instead of finding out when a stage fails.

**Why this priority**: Re-pointing without this is technically correct and
practically frustrating — the GM lands in the editor with fields that look
right and are not. It is P2 rather than P1 because the GM *can* discover it by
running a stage; the flag turns a run-time failure into a glanceable one.

**Independent Test**: Switch to a session directory that contains no GM-assist
recap and no session summary. Confirm the editor re-points both fields onto
the new directory and marks both as not-yet-present, while
`scene_extractions/` and any file that does exist are not marked.

**Acceptance Scenarios**:

1. **Given** a re-pointed path whose target does not exist on disk, **When**
   the GM views that field, **Then** the field is visibly marked as not-found.
2. **Given** a re-pointed path whose target does exist, **When** the GM views
   that field, **Then** no marking appears.
3. **Given** a field marked not-found, **When** the GM edits it to name a file
   that does exist, **Then** the marking clears without a page reload.
4. **Given** a field whose target does not exist, **When** the session
   directory changes, **Then** the field's stored name is preserved and
   re-pointed — it is never blanked on the GM's behalf.

---

### Edge Cases

- **The new session directory is empty.** A brand-new session folder with no
  recap, no summary, no VTT. Every session-scoped field re-points and the
  file-backed ones are marked not-found. No field is blanked, no field keeps
  pointing at the previous session, and the editor does not refuse to open.
- **The GM is already in the Session Doc Editor when the switch happens.** A
  switch made in another tab, or by returning to Session Config and coming
  back, must not leave the editor holding pre-switch values that a later
  auto-save writes back.
- **A path pinned outside the campaign entirely** (a shared narration
  directory on another volume, say). This is a genuine override with no
  session-relative meaning; it survives every switch untouched, and is not
  reported as damage.
- **A path pinned to a sibling session directory that the GM actually meant** —
  e.g. deliberately pointing this session's narration at last session's
  folder. This is indistinguishable from the damage in Story 3 and is
  therefore treated as damage; the announcement in Story 3 scenario 2 is what
  gives the GM the chance to notice and re-set it.
- **No session directory is set at all.** Nothing is re-pointed, nothing is
  healed, and nothing is rewritten — the existing behaviour of leaving
  session-scoped values untouched when there is no base to interpret them
  against is preserved.
- **The session directory is supplied for one run only, at launch, rather than
  saved.** The run reads its paths against that directory, and nothing about
  that temporary choice is written into stored configuration — including any
  healing that would otherwise have applied.
- **Cosmetic differences in the directory name**: a trailing slash, a `~`, or
  a relative form. `summaries/20260825` and `summaries/20260825/` are the same
  session and must not be treated as a switch.
- **Re-entering the same session directory.** A no-op: no re-point notice, no
  rewrite, no change to any field.
- **The campaign directory changes as well as the session directory.**
  Campaign-scoped fields re-point against the new campaign root by the rule
  that already governs them; the two are independent and neither switch
  disturbs the other's fields.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: When the current session directory changes, every session-scoped
  path presented by the Session Doc Editor MUST resolve under the new session
  directory, with no page reload, no server restart, and no action by the GM
  beyond making the change.
- **FR-002**: A change to the session directory MUST NOT cause any
  session-scoped path to be stored in a form that names the previous session
  directory, regardless of the order in which the session directory and the
  path fields are written.
- **FR-003**: The system MUST NOT write back a session-scoped path that was
  resolved against a session directory other than the current one.
- **FR-004**: A stored session-scoped path that names a *different session
  directory within the current campaign* MUST be treated as stale on read and
  re-pointed onto the current session directory, preserving the file or
  directory name it carried.
- **FR-005**: A stored session-scoped path that names a location outside the
  current campaign's session-directory tree MUST be preserved verbatim as a
  deliberate override, and MUST NOT be re-pointed or reported as stale.
- **FR-006**: Every re-point performed under FR-004 MUST be announced to the
  GM, naming the field, the value that was stored, and the value now in use. A
  correction to stored configuration is never silent.
- **FR-007**: A re-point MUST NOT itself write to disk. The corrected value
  becomes the stored value on the next write that occurs for an independent
  reason.
- **FR-008**: Re-pointing MUST preserve the name a field carries. A field whose
  re-pointed target does not exist MUST NOT be blanked, substituted, or
  auto-discovered on the GM's behalf.
- **FR-009**: For each path field it presents, the editor MUST show whether the
  resolved target currently exists, and MUST update that indication when the
  field or the session directory changes.
- **FR-010**: All session-scoped path fields MUST follow one and the same
  re-point rule. No field may have a second, independent derivation of where it
  lives.
- **FR-011**: The rules in FR-001 and FR-004 MUST apply identically when the
  session directory is supplied at launch for a single run rather than saved —
  except that such a run MUST NOT persist any value, healed or otherwise.
- **FR-012**: Re-pointing MUST be idempotent. Reading an already-correct
  configuration MUST produce no change and no announcement.
- **FR-013**: Campaign-scoped paths MUST be unaffected by a session-directory
  change, and session-scoped paths MUST be unaffected by a campaign-directory
  change.

### Key Entities

- **Session directory**: The single declaration of which session is current.
  One per campaign, changed on Session Config or supplied for one run at
  launch. Everything session-scoped is interpreted against it.
- **Session-scoped path**: A path whose meaning is "inside the current
  session" — the GM-assist recap, the session summary, the scene-extractions
  directory, the narration directory, the output directory. Stored as a name
  relative to the session directory; presented to the GM as a full location.
- **Campaign-scoped path**: A path whose meaning is "inside this campaign" and
  is the same across every session — voice files, examples, party, genre
  rulebook. Governed by the campaign directory, not the session directory.
- **Deliberate override**: A session-scoped field whose stored value points
  outside the campaign's session-directory tree, meaning the GM has pinned it
  somewhere no session-relative name can express. Survives every switch.
- **Stale pin**: A session-scoped field whose stored value points into a
  *different* session directory of the same campaign. Not expressible as an
  intent the system can honour; treated as damage, re-pointed, and announced.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A GM can move a campaign from one session to the next by editing
  exactly one field, and every path in the Session Doc Editor is correct
  immediately afterward — zero fields retyped, zero reloads.
- **SC-002**: After any sequence of session switches, no stored path field in
  any campaign names a session other than the current one, unless it names a
  location outside the campaign's session-directory tree.
- **SC-003**: 100% of automatic re-points are reported to the GM with the
  before and after values; none happens silently.
- **SC-004**: Every existing campaign in the workspace whose configuration
  carries a stale pin is corrected the first time its configuration is read,
  with no GM intervention and no data loss for genuine overrides.
- **SC-005**: Immediately after a switch to a fresh session directory, the GM
  can see which path fields have no file behind them yet without running a
  pipeline stage.
- **SC-006**: Zero pipeline runs read from one session directory and write to
  another as a result of a session switch.

## Assumptions

- The session directory remains the single place a session is declared; this
  feature does not add a second selector, a session picker, or a session
  history. It makes the existing declaration authoritative.
- Session-scoped paths continue to be *stored* as names relative to the session
  directory and *presented* as full locations. Re-pointing is a consequence of
  that contract being honoured on both the read and the write side, not a new
  storage format. No stored schema changes shape, so no out-of-band migration
  is required.
- **Constitution tension, recorded deliberately (Principle XIII, "no lazy
  in-place upgrade")**: Story 3 heals damaged values at read time, which is
  adjacent to the prohibition on rewriting state because it happened to be
  read. It is claimed as compatible on three grounds, and FR-006/FR-007 exist
  to keep it so: (a) nothing changes shape — this is value normalisation
  inside an unchanged schema, not a schema migration; (b) the read itself never
  writes, so no workspace is mutated by being looked at; (c) every correction
  is announced with its before-and-after, so it cannot reach a GM as an
  unexplained change. This ruling must be re-tested by name in the plan's
  Constitution Check; if it does not hold, the fallback is the one-shot
  migrator shape the constitution prescribes.
- Re-pointing carries names only. Discovering what a new session's files are
  actually called stays with the existing Session Config discovery step and
  with the GM — this feature deliberately does not guess a filename, because
  choosing which file is "the recap" is a scope decision (Principle II).
- A session-scoped path pointing into a sibling session directory is assumed
  never to be intentional. FR-006's announcement is the safeguard for the GM
  who meant it.
- Behaviour while a pipeline stage is mid-run is out of scope. Gating or
  refusing a session switch during an active run is a separate concern; this
  feature does not change what happens today if a GM switches mid-run.
- Existing campaigns in the workspace are the acceptance corpus. At least one
  campaign is expected to carry a stale pin; a campaign whose stored paths are
  already relative must come through the change byte-identical.

### Delivery constraints (GM-stated, carry into `/speckit-plan`)

- Implementation happens in a **separate git worktree**, not on a shared
  checkout of `main`.
- The plan must be written for a **split-model execution**: Opus orchestrates
  (decomposition, sequencing, review gates, constitution check) and Sonnet
  implements the individual tasks. Task granularity and hand-off boundaries in
  `tasks.md` should be sized for that split — each task self-contained enough
  for an implementer with no orchestration context.
