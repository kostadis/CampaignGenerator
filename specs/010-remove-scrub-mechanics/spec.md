# Feature Specification: Remove scrub_mechanics.py (superseded by the /scrub skill)

**Feature Branch**: `010-remove-scrub-mechanics`

**Created**: 2026-08-17

**Status**: Draft

**Input**: User description: "Remove `session_doc/scrub_mechanics.py` — the autonomous
single-pass LLM mechanical-residue scrubber for session_doc narration — and every
route, config knob, and UI action surface that exists only to drive it. This CLI
is dead: `ScrubKnobs.enabled` already defaults to `False`. It has been superseded
by the `/scrub` Claude Code skill (`mytools` repo), which does the same job with a
human-in-the-loop propose→confirm→apply flow instead of an unreviewed autonomous
LLM pass — the skill's own SKILL.md states it replaces `scrub_mechanics.py` 'per
CampaignGenerator issue #151 (the spell-stripping incident).' Two things that look
related must NOT be touched: (1) the `.scrubbed.md` file contract in
`session_doc/assemble.py` (`collect_scene_files`), which is producer-agnostic and
stays alive — a `.scrubbed.md` file can still legitimately exist, now produced by
the `/scrub` skill instead of the CLI; (2) `split_frontmatter_raw()`, a real shared
utility that happens to be defined inside `scrub_mechanics.py` today and is used
by `tests/test_frontmatter_parsers.py` — it must be relocated to
`campaignlib/textproc.py`, not deleted."

## User Scenarios & Testing *(mandatory)*

<!--
  This is a decommissioning feature, not a net-new one: the "user" is the GM
  operating the Session Doc Editor and the developer maintaining the repo. Each
  story below is a slice of dead-code removal that is independently completable
  and independently verifiable (the app boots, the tests pass, the UI renders)
  without depending on the other slices being done first.
-->

### User Story 1 - A GM opening the Session Doc Editor no longer sees a dead "Scrub" action (Priority: P1)

A GM running a live session-doc pass through the web UI sees the per-scene
**Scrub** button and the header **Scrub All** button removed from the editor.
Nothing in the UI invites them to run the retired autonomous pass. The GM can
still see, per scene, whether a `.scrubbed.md` sibling exists (the existing
"Stage 4½" status dot and the Review screen's "④½ Scrub" badge), because that
status reflects a file that can still legitimately exist — produced by running
the `/scrub` Claude Code skill outside the web UI — and hiding that status would
make a real on-disk artifact invisible to the GM.

**Why this priority**: This is the user-visible half of the change and the one
most likely to confuse a GM if left half-done (a button that 404s, or worse,
silently no-ops). It is also low-risk: removing a button and its handler cannot
break any other pipeline stage.

**Independent Test**: Load the Session Doc Editor for a session with an existing
`.scrubbed.md` file. Confirm the "Scrub" and "Scrub All" buttons are gone from
the UI, confirm the scene list's status dot and the Review screen's lifecycle
badge still report `has_scrubbed: true` for that scene, and confirm no other
button's layout or behavior changed.

**Acceptance Scenarios**:

1. **Given** the Session Doc Editor is open on a scene with a narration file,
   **When** the GM looks at the per-scene toolbar, **Then** there is no "Scrub"
   button (only Save / Edit in Typora / Reload / Diff / Narrate remain in that
   toolbar).
2. **Given** the Session Doc Editor header, **When** the GM looks at the Stage
   4½ button group, **Then** there is no "Scrub All" button.
3. **Given** a scene whose narration directory already contains a
   `<scene>.scrubbed.md` file (produced by a prior run of the CLI or by the
   `/scrub` skill), **When** the GM views the scene list or the Review screen,
   **Then** the existing scrub-status indicator (dot / "④½ Scrub" badge) still
   shows that scene as scrubbed.

---

### User Story 2 - The backend no longer exposes the retired scrub action routes or config knob (Priority: P1)

The two action routes that shell out to `scrub_mechanics` (`GET /scrub/{n}` and
`GET /scrub-all`) are removed from the Session Doc Editor router, along with the
`ScrubKnobs` config model and the `scrub` field on the editor's config schema.
The passive status read (`_scrubbed_for_scene`, `has_scrubbed`) is kept, because
it reports on a file that remains a legitimate artifact, not on the retired
action.

**Why this priority**: Equal priority to Story 1 — a UI with no Scrub button but
a live `/scrub/{n}` route behind it is an inert door, not a removed feature, and
leaves `console_script("scrub_mechanics")` wired to a script the plan also
deletes (Story 3), which would 500 on the rare direct hit.

**Independent Test**: `grep` the router for `/scrub` action routes and find none;
issue a request to the (now-nonexistent) route and get a 404; confirm
`GET /api/editor/config` no longer has a top-level `scrub` key; confirm an
existing campaign's `session_doc.yaml` that still has a persisted `scrub:` block
from before this change still loads without error (the retired-field is
dropped, not rejected).

**Acceptance Scenarios**:

1. **Given** the running server, **When** a client requests
   `GET /api/editor/scrub/1` or `GET /api/editor/scrub-all`, **Then** the
   response is a 404 (route no longer registered).
2. **Given** `GET /api/editor/config`, **When** the response is inspected,
   **Then** it has no `scrub` key, and every other top-level key
   (`paths`, `narrate`, `backends`, `session_name`, `profiles`,
   `active_profile`, `model`, `work_dir`, `campaign_dir`, `config_dir`, `vtt`,
   `session_dir`, `genre`) is unchanged.
3. **Given** a `session_doc.yaml` on disk that still has a top-level
   `scrub: {enabled: false, tokens: 16000}` block (written before this change),
   **When** the Session Doc Editor loads that campaign's config, **Then** it
   loads successfully (the retired field is stripped on load, with the same
   drop-and-announce pattern already used for other retired
   `session_doc.yaml` fields), not rejected by the schema's `extra="forbid"`.
4. **Given** the scene list / pipeline-status endpoints, **When** they are
   called for a session with a `.scrubbed.md` file on disk, **Then**
   `has_scrubbed: true` is still reported for that scene (unchanged behavior).

---

### User Story 3 - The CLI and its console-script entry point are gone; the shared frontmatter helper survives (Priority: P2)

`session_doc/scrub_mechanics.py` is deleted, along with its
`scrub_mechanics` console-script entry in `pyproject.toml` and its dedicated
test file (`tests/test_scrub_mechanics.py`, which tests the CLI's `--batch`
plumbing directly). Before deletion, `split_frontmatter_raw()` — the
byte-preserving sibling of `campaignlib.textproc.split_frontmatter()` that
`tests/test_frontmatter_parsers.py` imports directly from
`session_doc.scrub_mechanics` — is relocated into `campaignlib/textproc.py`
next to `split_frontmatter()`, and every importer is updated to the new
location.

**Why this priority**: Lower priority than the two user-facing removals because
nothing outside the deleted file's own tests and the router (already fixed in
Story 2) references `scrub_mechanics` by import — this is pure cleanup with no
UI-visible effect, but it must land before Story 4 (docs) can honestly say the
CLI no longer exists.

**Independent Test**: `python -m pytest tests/` passes with no collection
errors; `python -c "from campaignlib.textproc import split_frontmatter_raw"`
succeeds; `session_doc/scrub_mechanics.py` no longer exists; the `pyproject.toml`
console-scripts table no longer lists `scrub_mechanics`.

**Acceptance Scenarios**:

1. **Given** the repository after this change, **When** searching for
   `session_doc/scrub_mechanics.py`, **Then** the file does not exist.
2. **Given** `pyproject.toml`, **When** its `[project.scripts]` table is
   inspected, **Then** it has no `scrub_mechanics` entry.
3. **Given** `campaignlib/textproc.py`, **When** its public functions are
   inspected, **Then** `split_frontmatter_raw` is defined there with the same
   signature and behavior it had in `scrub_mechanics.py` (raw block including
   delimiters, empty-frontmatter-safe, does not parse).
4. **Given** `tests/test_frontmatter_parsers.py`, **When** it is run, **Then**
   it imports `split_frontmatter_raw` from `campaignlib.textproc` and all three
   of its assertions (raw-with-delimiters, parsed-dict, and the deliberate
   divergence between the two) still pass unchanged in substance.
5. **Given** `tests/test_scrub_mechanics.py`, **When** the repository is
   searched, **Then** the file does not exist (its useful behavioral coverage
   of `split_frontmatter_raw` already lives in `test_frontmatter_parsers.py`;
   its `--batch`/`scrub_batch`/`scrub_one` coverage tested code that no longer
   exists).

---

### User Story 4 - Live reference docs describe the current system, not a retired CLI (Priority: P3)

`docs/web/session_doc_editor.md` and `docs/cli/cli_tools.md` — both living
how-to references for the current system, unlike the historical/archival specs
and design-decision postmortems under `specs/` and `docs/design/` — no longer
document a "Scrub" button, a "Scrub All" header action, or a `scrub_mechanics`
CLI entry. They instead note that mechanical scrubbing now happens via the
`/scrub` Claude Code skill, run outside the web UI, and that the `.scrubbed.md`
output contract (what `assemble.py` prefers) is unchanged. The root `CLAUDE.md`'s
mention of `scrub_mechanics` in its "LLM renders, humans decide" section is
reworded so it no longer cites a live command, while keeping the historical
point about issue #151 intact.

**Why this priority**: Lowest priority — a stale doc does not break anything at
runtime, but shipping the removal without it means the next reader is told to
click a button that no longer exists.

**Independent Test**: `grep -i scrub` over the two named docs plus root
`CLAUDE.md` and confirm no remaining reference reads as "this is a live,
clickable action" or "this CLI exists to run standalone" — historical/narrative
mentions (e.g. "the #151 incident that motivated the `/scrub` skill") are fine
and expected to remain.

**Acceptance Scenarios**:

1. **Given** `docs/web/session_doc_editor.md`, **When** read end to end,
   **Then** it contains no instructions to click a "Scrub" or "Scrub All"
   button, and instead points at the `/scrub` skill as the current mechanism.
2. **Given** `docs/cli/cli_tools.md`, **When** read end to end, **Then** it has
   no `scrub_mechanics` CLI entry.
3. **Given** root `CLAUDE.md`, **When** its "LLM renders, humans decide"
   section is read, **Then** it still recounts the #151 lesson but does not
   present `scrub_mechanics` as a command a reader could run today.
4. **Given** `specs/004-claude-api-batch/*`, `docs/design/MarkdownAsInput.md`,
   `docs/design/SourceTreeRestructure.md`, `docs/design/QuoteTriage_research.md`,
   `docs/design/ExtractionContract_implementation.md`, and
   `specs/007-two-phase-extraction/data-model.md`, **When** the repository diff
   for this feature is inspected, **Then** none of these historical/archival
   files were modified.

---

### Edge Cases

- A `session_doc.yaml` written by a version of the code that still had
  `ScrubKnobs` (i.e. every real campaign that has ever opened the Session Doc
  Editor's config drawer, since the config service dumps the full model
  including defaults) has a persisted top-level `scrub:` block on disk. Because
  `SessionEditorConfig` is `extra="forbid"`, simply deleting the `scrub` field
  would make every such campaign's config fail to load and take the editor down
  on boot. This is handled the same way three earlier retirements in this same
  file were handled (`RETIRED_PATH_FIELDS`, `RETIRED_NARRATE_FIELDS`): the field
  is stripped before validation, with a stderr notice, not silently and not by
  rejecting the load.
- The one-shot migration CLI `server/migrate_session_doc.py` reads a legacy
  flat `ui.session_doc` shape (from a pre-Phase-5 `ui_state.yaml`) via
  `TYPED_SESSION_DOC_TO_GROUPED`, which currently maps `scrub_enabled` /
  `scrub_tokens` into the (now-removed) `scrub` group. This repo's own
  established convention for a retired migration target (see the existing
  `roleplay_dir` / `narration_genre` / `characters` / `gm_player` entries in
  that same table, each removed with an explanatory comment when their target
  field was retired) is followed: the two `scrub_*` entries are removed from
  the map, so the migration reports them as unrecognised/left-behind rather
  than mapping into a field that no longer exists.
- A GM who already has a scene with a `.scrubbed.md` sibling on disk, produced
  before this change, must not lose visibility into that fact — `has_scrubbed`
  keeps working across this change (see User Story 1/2).
- `session_doc/assemble.py`'s `collect_scene_files` docstring currently
  attributes `.scrubbed.md` production to "`scrub_mechanics`" by name. Since
  that CLI no longer exists, the one-line attribution is corrected to name the
  `/scrub` skill instead — the surrounding preference logic itself is
  untouched, per the explicit constraint that this contract is producer-agnostic
  and out of scope for behavioral change.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST NOT expose any UI control (button, menu item, or
  otherwise) that triggers the mechanical-residue scrub CLI, in either the
  per-scene editor or the Session Doc Editor header.
- **FR-002**: The system MUST continue to display, per scene, whether a
  `.scrubbed.md` sibling file exists on disk (the scene-list status dot and the
  Review screen's lifecycle badge), regardless of what produced that file.
- **FR-003**: The backend MUST NOT expose HTTP routes that invoke the
  `scrub_mechanics` CLI (`GET /api/editor/scrub/{n}`, `GET /api/editor/scrub-all`).
- **FR-004**: The Session Doc Editor's configuration schema MUST NOT have a
  `scrub` knob group (no `ScrubKnobs` model, no `scrub` field on
  `SessionEditorConfig`/`ResolvedEditorConfig`).
- **FR-005**: Loading an existing, on-disk `session_doc.yaml` that still
  contains a top-level `scrub:` block (written before this change) MUST
  succeed, with the retired field dropped (not rejected), consistent with how
  this file already handles other retired top-level fields.
- **FR-006**: `session_doc/scrub_mechanics.py` MUST be deleted, along with its
  `pyproject.toml` console-script entry and its dedicated test file
  (`tests/test_scrub_mechanics.py`).
- **FR-007**: `split_frontmatter_raw()` MUST be preserved as a callable,
  importable function with unchanged behavior, relocated to
  `campaignlib/textproc.py`. Every importer of the old location MUST be updated
  to import from the new one.
- **FR-008**: `session_doc/assemble.py`'s preference for `.scrubbed.md` over
  `.md` when assembling the final document (`collect_scene_files`, the
  `--no-prefer-scrubbed` flag) MUST be unchanged in behavior — this feature
  touches no logic in that file, only an outdated attribution in a docstring.
- **FR-009**: `docs/web/session_doc_editor.md` and `docs/cli/cli_tools.md` MUST
  be updated to remove references to the retired CLI/button and to state that
  mechanical scrubbing now happens via the `/scrub` Claude Code skill outside
  the web UI, with the `.scrubbed.md` output contract unchanged.
- **FR-010**: Root `CLAUDE.md`'s reference to `scrub_mechanics` MUST be reworded
  so it does not cite a live, runnable command, while preserving the historical
  point about issue #151.
- **FR-011**: The historical/archival documents explicitly out of scope
  (`specs/004-claude-api-batch/*`, `docs/design/MarkdownAsInput.md`,
  `docs/design/SourceTreeRestructure.md`, `docs/design/QuoteTriage_research.md`,
  `docs/design/ExtractionContract_implementation.md`,
  `specs/007-two-phase-extraction/data-model.md`) MUST NOT be modified by this
  feature.
- **FR-012**: The full test suite (`python -m pytest tests/`) MUST pass after
  this change, including every test file that references "scrub" incidentally
  (`test_batch_flag_uniformity.py`, `test_editor_profiles_routes.py`,
  `test_editor_verify_routes.py`, `test_migrate_session_doc.py`,
  `test_editor_pipeline.py`, `test_editor_service_integration.py`) — each
  updated only where it actually breaks (dropped fixtures/assertions for the
  removed `scrub` field/routes), not deleted wholesale.

### Key Entities

- **`ScrubKnobs` / `scrub` config group**: the per-campaign knob (`enabled`,
  `tokens`) that gated the retired autonomous pass. Removed entirely; not
  replaced by anything, because the `/scrub` skill has no equivalent
  config-driven "enabled" toggle (it runs as an interactive skill invocation).
- **`.scrubbed.md` sibling file**: the on-disk artifact of a scrub pass —
  UNCHANGED entity. Its existence is still meaningful and still displayed;
  only the thing that used to *produce* it via a UI button is retired.
- **`split_frontmatter_raw()`**: a shared text-processing utility, relocating
  from `session_doc/scrub_mechanics.py` to `campaignlib/textproc.py` — a move,
  not a removal.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero references to `scrub_mechanics` remain in runnable code
  paths (routes, config models, console scripts, CLI files) after this change;
  `grep -ri scrub_mechanics` over `server/`, `session_doc/`, `pyproject.toml`,
  and `frontend/src/` returns only the corrected docstring/comment mentions
  identified in the Edge Cases section, not a live wiring path.
- **SC-002**: `python -m pytest tests/` passes with the same or greater number
  of passing tests as the pre-change baseline (accounting for the deletion of
  `tests/test_scrub_mechanics.py`'s tests, whose useful coverage already lives
  elsewhere).
- **SC-003**: A campaign's existing `session_doc.yaml` from before this change
  (with a persisted `scrub:` block) loads without error after this change.
- **SC-004**: The Session Doc Editor UI, loaded against a campaign with a
  `.scrubbed.md` file already on disk, shows that scene as scrubbed in both the
  scene list and the Review screen, with no Scrub/Scrub All button present
  anywhere in the UI.

## Assumptions

- The `/scrub` Claude Code skill (in the `mytools` repo, installed at
  `~/.claude/skills/scrub/`) is out of scope to modify — it already exists and
  already documents itself as the replacement. This feature only removes the
  superseded code on the CampaignGenerator side.
- No campaign currently depends on `scrub.enabled: true` in production — this
  is asserted true by the codebase itself (`ScrubKnobs.enabled` already
  defaults to `False`, per the task's premise), so removing the knob is not
  believed to silently change any running campaign's behavior.
- "Live reference docs" vs. "historical/archival records" is judged by
  authorial framing (present-tense how-to text describing current system
  behavior, vs. a dated status record of a completed past decision with commit
  hashes) — not by directory location alone. Two additional docs surfaced
  during implementation research that fit the "live reference" category despite
  not being named in the original task brief
  (`docs/config/schema.md`, `docs/config/values.md`, `docs/config/master.md`,
  `docs/config/service-cut.md` — all present-tense schema/value maps that would
  otherwise go stale) are treated as in-scope for the same reason
  `docs/web/session_doc_editor.md` and `docs/cli/cli_tools.md` are;
  `docs/config/session-editor-isolation.md` (explicitly marked "Status: Done"
  with dated commit hashes, a completed-migration postmortem) is treated as
  archival and left alone, matching the treatment of the explicitly-named
  historical docs.
- The `TYPED_SESSION_DOC_TO_GROUPED` migration-field-map cleanup
  (`scrub_enabled`/`scrub_tokens` entries) and the `SessionEditorConfig`
  retired-top-level-field validator were not named in the original task brief
  but are required for FR-005 (an existing campaign's config must still load)
  and for internal consistency with this file's own established pattern for
  retiring a field — both are treated as in-scope, necessary consequences of
  FR-004/FR-005 rather than scope creep.
