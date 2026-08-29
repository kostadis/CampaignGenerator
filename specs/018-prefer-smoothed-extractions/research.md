# Phase 0 Research: Prefer Smoothed Scene Extractions for Narration

**Feature**: `018-prefer-smoothed-extractions` | **Date**: 2026-08-28

All Technical Context unknowns are resolved here. No `NEEDS CLARIFICATION`
remains.

## Ground truth established before design

| Fact | Evidence |
|---|---|
| The UI Narrate command always passes the configured extraction directory | `server/routers/scene_editor.py:_build_narrate_cmd()` builds `sd_narrate ... --scene-extractions <_scene_extractions_dir(cfg)>`. |
| The configured editor default can be `scene_extractions_new` | `SessionDocEditor.vue:loadConfigFields()` reads `paths.scene_extractions_dir`; the reported defect is the resolved `scene_extractions_new` value surviving after smoothing. |
| The derived voice-smoothed convention is a fixed `scene_extractions_smoothed` directory | The feature specification and existing smoothed-layer tests use that exact name. Deriving `<raw-name>_smoothed` would incorrectly produce `scene_extractions_new_smoothed`. |
| Eligible files and scaffold precedence already have one documented authority | `session_doc/io.py:scene_extraction_files()` skips sibling artifacts, requires an `NN_` prefix, and lets `.scaffold.md` shadow plain `.md`. |
| The router duplicates per-scene lookup rules | `_scene_extraction_file_new()` independently performs exact slug, scaffold, and `NN_` index fallback inside the configured raw directory. |
| `sd_narrate` consumes a directory, not an exact file | `session_doc/sd_narrate.py:main()` loads the full directory, matches plan scene name first, then falls back to compact-list position. |
| A partial directory makes positional fallback unsafe | A directory containing only scene 3 has list position 1. `--scene 3` works only when name matching succeeds; positional fallback cannot locate it and may select another scene for other partial layouts. |
| The UI edits the raw extraction and auto-saves it before every Narrate | `SessionDocEditor.vue:narrate()` calls `saveExtraction(extractionContent.value)` unconditionally before opening the SSE run. |
| The Narrate button is coupled to raw-editor availability | `ExtractionEditor.vue` disables Narrate when `hasExtraction` is false, so a smoothed-only selected scene cannot run. |
| The frontend has no component/unit test runner | `frontend/package.json` defines only `dev`, `build`, and `preview`; `build` runs `vue-tsc -b` and Vite. |
| The requested worktree root is nested and currently unignored | `git worktree list` uses sibling and `.claude` locations today; `.gitignore` contains no `worktrees/` entry. |

## Decisions

### D1 — Share per-directory scene-file resolution in `session_doc/io.py`

**Decision**: Add a reusable resolver beside `scene_extraction_files()` that
returns the eligible file for one scene in one directory. It applies the
existing rules in this order: eligible-file filter and scaffold shadowing,
exact scene-name/slug association where available, then the matching `NN_`
scene prefix. The router's raw helper delegates to it instead of maintaining a
second glob implementation.

**Rationale**: `scene_extraction_files()` already claims to be the single
authority for what the loader reads. Both raw editor lookup and smoothed
Narrate lookup need precisely that rule, including ignored artifacts and
scaffold precedence.

**Alternatives considered**:

- Keep a second router-only helper. Rejected because eligibility and
  precedence would drift between the UI and CLI loader.
- Use plain filename construction only. Rejected because plan titles already
  drift from Stage-2 slugs; existing tests require `NN_` fallback.

### D2 — Discover smoothed input from the current session, not raw-name suffixing

**Decision**: Resolve the preferred directory as
`<current session_dir>/scene_extractions_smoothed`. Resolve the raw fallback
from the existing configured `paths.scene_extractions_dir`, including any
custom override.

**Rationale**: The convention produced by smoothing has one stable name. The
reported raw layer is `scene_extractions_new`; appending `_smoothed` to that
name points at a directory that does not exist. The current session directory
is already the authoritative base for session artifacts.

**Alternatives considered**:

- `raw_dir.parent / f"{raw_dir.name}_smoothed"`. Rejected for the reported
  `scene_extractions_new` case.
- Add a persisted `smoothed_dir` setting. Rejected because the spec chooses
  convention-based automatic discovery and no state migration is needed.

### D3 — Add an exact-file override to `sd_narrate`

**Decision**: Add `--scene-extraction-file FILE` to `sd_narrate`. It is valid
only with exactly one `--scene N`, must name a readable eligible extraction
for that scene, and overrides directory matching for that one scene. The
existing required `--scene-extractions DIR` remains the ordinary context and
fallback input.

For a selected smoothed scene, the UI router passes the configured raw
directory plus the exact smoothed file. If the raw directory itself is absent,
it passes the smoothed file's parent as the required directory. A raw-selected
scene receives the existing command unchanged.

**Rationale**: This makes the exact path shown in the UI the exact path the
CLI reads. It supports partial and smoothed-only layers without changing the
meaning of the existing directory option or relying on compact-list position.

**Alternatives considered**:

- Pass the entire smoothed directory. Rejected because partial directories and
  title drift make positional fallback unsafe.
- Change the global list-index matching semantics only. Rejected because that
  broadens a targeted UI-input feature and still does not transmit the exact
  path the UI displayed.
- Build a temporary overlay directory. Rejected because it creates transient
  handoff state, adds cleanup failure modes, and weakens disk-as-truth.
- Pass file content through the router. Rejected because rendering belongs to
  the CLI and content-in-HTTP would create a second input channel.

### D4 — Return one server-owned `NarrateSourceState`

**Decision**: Add a request-scoped source resolver in the scene-editor router.
It checks the selected scene in the smoothed directory first and raw directory
second, tests readability, and returns a non-persisted state projection. The
same resolver is called by `GET /api/editor/extraction/{n}` and immediately
before `_build_narrate_cmd()` finalizes the CLI arguments.

The projection names the smoothed and raw directories, directory presence,
candidate files, active layer/file, readiness, fallback, and a user-facing
reason. The browser never constructs this state.

**Rationale**: UI display and execution must agree from the same authority.
Re-resolving at the command boundary respects file changes made while the page
is open.

**Alternatives considered**:

- Infer the sibling path in Vue. Rejected as browser-only pipeline truth and a
  duplicate convention.
- Persist active layer in Pinia or YAML. Rejected because disk presence is the
  source and can change outside the browser.
- Add source metadata to every scene-list row. Deferred: the selected-scene
  detail endpoint already runs on each scene change and satisfies the feature
  without scanning two directories for every list refresh.

### D5 — Keep raw editing distinct from active Narrate input

**Decision**: The extraction textarea, Save, Reload, reviewed marker, diff,
and “Edit in Typora” continue to operate on the configured raw extraction.
`narrate_source` is shown as a separate, read-only handoff immediately above
or beside Narrate. A smoothed-only scene may therefore have
`hasExtraction == false` and `narrate_source.available == true`.

**Rationale**: Automatically switching the editable file creates a dangerous
race: a GM may load raw text, a smoothed file may appear, and a later Save
could overwrite the smoothed file with the stale raw buffer. The request is to
show and use the preferred layer, not to redefine which layer the extraction
editor owns.

**Alternatives considered**:

- Load and save whichever source is active. Rejected because a source change
  while the editor is open can redirect a stale buffer into the wrong file.
- Make the smoothed file editable with a new editor mode. Out of scope; that
  is a separate product decision and requires an explicit path/version
  concurrency contract.

### D6 — Remove unconditional pre-Narrate raw writes

**Decision**: Track whether the raw editor buffer is dirty. Before Narrate,
refresh the server source projection. If raw is active and the raw buffer is
dirty, save it and refresh once more. If smoothed is active, do not save or
touch raw as part of Narrate. In all cases, the server re-resolves again when
building the command.

**Rationale**: Current unconditional Save rewrites raw even when it is not the
input and prevents a smoothed-only scene from running. Conditional save
preserves the familiar raw-edit-then-Narrate flow while making smoothed use
read-only and explicit.

**Alternatives considered**:

- Remove every automatic save. Rejected because it regresses the established
  raw editing flow; a dirty raw buffer should still reach a raw Narrate.
- Save raw even when smoothed is active. Rejected because it is an unrelated
  source mutation and falsely suggests the edit affected the upcoming run.

### D7 — Treat unreadable preferred input as blocking

**Decision**: Once an eligible smoothed file is present, a decode/read failure
produces status `unreadable`; the UI disables Narrate and the server refuses
the run with that file's path. It does not fall back to raw. A missing
smoothed candidate is different and falls back normally.

**Rationale**: Presence is the GM's deliberate signal that the smoothed layer
should win. Silent raw fallback would discard that decision and produce paid
output from an unintended source.

**Alternatives considered**:

- Warn and fall back. Rejected because the run could finish before the GM sees
  the warning.
- Let the CLI fail later. Rejected because the UI must show availability before
  starting the token-spending operation.

### D8 — Keep non-Narrate pipeline stages on their existing source

**Decision**: Extraction, quote verification, Plan & Check, consistency,
review markers, and raw editor endpoints continue to use the configured raw
directory. Only the Narrate source projection and command receive smoothed
preference.

**Rationale**: This is FR-016 and avoids turning a focused handoff fix into a
pipeline-wide source-policy change. It also preserves verification's existing
verbatim semantics for raw extraction files.

**Alternatives considered**:

- Change `paths.scene_extractions_dir` to smoothed when discovered. Rejected
  because every consumer would silently switch and the persisted configuration
  would stop expressing the Stage-2 output.

### D9 — GPT-5.6 orchestration, GPT-5.5 implementation, nested worktree

**Decision**: GPT-5.6 owns task decomposition, sequencing, contract and
constitution decisions, diff review, and all integration gates. GPT-5.5 owns
the bounded implementation tasks generated later by `$speckit-tasks`.

Implementation happens only in
`/home/kroussos/src/CampaignGenerator/worktrees/018-prefer-smoothed-extractions`
on branch `018-prefer-smoothed-extractions`. Before creating it, the
orchestrator locally ignores `worktrees/` through `.git/info/exclude`, because
the user-required root is nested inside the primary checkout and is not
currently ignored.

**Rationale**: User-stated execution constraint. The model split is enforced
as review gates, not merely documented as a preference.

**Alternatives considered**:

- Use the existing sibling `CampaignGenerator-worktrees/` convention.
  Rejected because the user explicitly named a different root.
- Create the worktree before design/tasks exist. Rejected: the orchestration
  artifacts define the GPT-5.5 handoffs and must be reviewed first.

## Resolved unknowns

| Unknown | Resolution |
|---|---|
| How is “present” determined? | An eligible file for the selected scene exists under the fixed smoothed directory, using the shared loader/scaffold/index rules. Directory presence alone is insufficient. |
| How can a partial smoothed directory safely reach a directory-based CLI? | A new exact-file override is paired with the selected `--scene`; the existing directory remains context/fallback. |
| How is a smoothed-only scene enabled when raw is absent? | UI enablement comes from `narrate_source.available`, independently of raw `hasExtraction`; the smoothed directory serves as the CLI base if no raw directory exists. |
| Which file does the editor save? | Raw only. Smoothed is a read-only Narrate handoff in this feature. |
| How are external file changes noticed? | Detail refresh and a pre-Narrate refresh update the UI; command construction re-resolves disk once more. |
| Is a migration required? | No. Nothing is stored, moved, renamed, or rewritten. |
| How is the frontend tested? | Backend contract tests plus `npm run build` and `quickstart.md`; adding a frontend test runner is out of scope. |
| Does the CLI/UI split remain constitutional? | Yes. The CLI receives and consumes the exact file; the router selects from disk; the UI displays and invokes the same capability. |
