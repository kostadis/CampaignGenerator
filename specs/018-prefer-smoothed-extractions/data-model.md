# Phase 1 Data Model: Smoothed-First Narrate Source

**Feature**: `018-prefer-smoothed-extractions` | **Date**: 2026-08-28

This feature adds no stored entity. The campaign workspace, session-editor
configuration, raw extraction files, and smoothed extraction files retain
their current shapes. The model below is request-scoped state derived from
disk and discarded after each response or command build.

## Existing stored entities (unchanged)

### Raw scene extraction

An eligible `NN_*.md` file under configured
`paths.scene_extractions_dir`. It is produced by Stage 2 and remains the file
owned by the Session Doc extraction editor, reviewed marker, diff, Save, and
non-Narrate pipeline stages.

### Smoothed scene extraction

An eligible `NN_*.md` file under
`<session_dir>/scene_extractions_smoothed`. It is a voice-edited derivative
created outside this feature and is read-only to the Narrate handoff.

### Eligibility and precedence

Both layers use the same rules, owned by `session_doc/io.py`:

1. Markdown only.
2. Ignore `plan.md`, `consistency_report.md`, and files beginning with `_`.
3. Require a two-digit `NN_` scene prefix.
4. Collapse a plain/scaffold pair to one candidate, preferring
   `NN_<slug>.scaffold.md`.
5. Associate by exact scene identity when available, then by the `NN_` prefix.

No router or frontend component may restate these rules.

## Derived entities

### `SceneSourceCandidate`

One layer's resolution result for one selected scene.

| Field | Type | Rule |
|---|---|---|
| `layer` | `"smoothed" | "raw"` | Fixed by the directory being inspected. |
| `directory` | absolute path or null | Smoothed: current session plus `scene_extractions_smoothed`; raw: resolved configured extraction path, or null when not configured. |
| `directory_exists` | boolean | True only when the directory currently exists. |
| `path` | absolute path or null | The eligible file associated with this scene, after scaffold precedence; null if absent. |
| `filename` | string or null | Basename of `path`; never an independent identifier. |
| `exists` | boolean | `path` names a file at resolution time. |
| `readable` | boolean or null | Null if no candidate; otherwise a UTF-8 read probe succeeds or fails. |
| `reason` | string or null | Human-readable explanation when absent or unreadable. |

**Invariant**: `exists == true` implies `path != null`.

**Invariant**: `readable == true` implies `exists == true`.

### `NarrateSourceState`

The single server-owned projection sent to the selected-scene UI and used to
build the next Narrate command.

| Field | Type | Meaning |
|---|---|---|
| `scene_index` | positive integer | The explicitly selected 1-based plan scene. |
| `scene_name` | string | Plan scene name used as the identity match when available. |
| `smoothed` | `SceneSourceCandidate` | Preferred-layer result. Always present as a projection, even when its directory is absent. |
| `raw` | `SceneSourceCandidate` | Configured fallback result. |
| `active_layer` | `"smoothed" | "raw" | null` | Chosen layer when ready; null for missing or unreadable state. |
| `active_file` | absolute path or null | Exact file `sd_narrate` must consume. |
| `status` | `"ready" | "missing" | "unreadable"` | Mutually exclusive state. |
| `available` | boolean | True exactly when `status == "ready"`. |
| `fallback_to_raw` | boolean | True only when smoothed is absent and raw is ready. |
| `message` | string | UI/error explanation. Missing-state messages name both checked directories; unreadable messages name the failing preferred file. |

**Selection invariant**:

```text
if smoothed.exists and smoothed.readable:
    active = smoothed, status = ready
elif smoothed.exists and not smoothed.readable:
    active = none, status = unreadable       # no raw fallback
elif raw.exists and raw.readable:
    active = raw, status = ready, fallback_to_raw = true
elif raw.exists and not raw.readable:
    active = none, status = unreadable
else:
    active = none, status = missing
```

**Disk-truth invariant**: this state is never persisted. It is recomputed for
each selected-scene detail response and again for the command builder.

**Execution invariant**: when `status == "ready"`, the command builder's exact
file (for a smoothed source) or directory-resolved raw file is
`active_file`. No other candidate may be substituted by list position.

### `RawEditorState` (frontend, non-persisted)

The existing extraction-editor state gains one local fact; it does not gain a
source-selection policy.

| Field | Type | Meaning |
|---|---|---|
| `content` | string | Configured raw extraction text shown in the textarea. |
| `exists` | boolean | Raw editor file exists; controls Save/Edit/Reload/Diff. |
| `dirty` | boolean | Textarea changed since the most recent raw load/save. |
| `narrate_source` | `NarrateSourceState` | Read-only server projection; controls Narrate and the visible source banner. |

**Separation invariant**: `exists` controls raw editing, while
`narrate_source.available` controls Narrate. Neither is derived from the
other.

**Write invariant**: Narrate may auto-save a dirty raw buffer only when the
freshly resolved active layer is raw. A smoothed-active or blocked Narrate
performs no raw or smoothed source write.

### `ExactSceneInput` (CLI invocation state)

An optional input override inside `sd_narrate`.

| Field | Source | Validation |
|---|---|---|
| `file` | `--scene-extraction-file FILE` | Exists, is readable UTF-8, and is an eligible scene extraction. |
| `scene` | the sole value of `--scene N` | Exactly one positive scene number must be supplied. |
| `parsed extraction` | shared I/O loader | Associates with the requested scene by name or `NN_` prefix; otherwise the CLI refuses before a model call. |

The directory supplied by `--scene-extractions` retains its current purpose
for ordinary/multi-scene input and session-wide source context. When the exact
override is valid, it is used for the selected scene before directory name or
position matching.

## Relationships

```text
current session_dir
        │
        └── scene_extractions_smoothed/ ──► smoothed candidate

configured paths.scene_extractions_dir ──► raw candidate

smoothed candidate ──preferred──┐
raw candidate ───────fallback───┴──► NarrateSourceState
                                         │
                         ┌───────────────┴───────────────┐
                         ▼                               ▼
              GET /extraction/{n} UI          _build_narrate_cmd()
              read-only source banner         exact CLI arguments
```

## State transitions

| Before | Disk event | Next resolution | Narrate effect |
|---|---|---|---|
| Raw ready | Matching smoothed file is created | Smoothed ready | Next refresh/run switches to exact smoothed file. |
| Smoothed ready | Smoothed file is removed | Raw ready if raw exists; otherwise missing | Falls back per scene or refuses. |
| Raw fallback | A different scene is smoothed | Unchanged for current scene | No cross-scene redirect. |
| Smoothed ready | File becomes unreadable | Unreadable | Narrate disabled/refused; raw not used. |
| Missing | Raw file appears | Raw ready | Narrate becomes available without page reload after refresh. |
| Missing | Smoothed file appears | Smoothed ready | Narrate becomes available and prefers smoothed. |
| Raw editor dirty + raw active | GM invokes Narrate | Raw saved, state refreshed, then run | Edited raw content reaches Narrate. |
| Raw editor dirty + smoothed active | GM invokes Narrate | No source write; state rechecked | Smoothed file reaches Narrate; raw buffer remains visibly dirty. |

## Validation rules carried from requirements

| Rule | Requirement | Enforcement point |
|---|---|---|
| Recheck at run time | FR-001, FR-009 | Server command builder calls the resolver; frontend preflight refreshes display. |
| Smoothed wins per scene | FR-002, FR-004 | `NarrateSourceState` transition rule. |
| Raw is fallback only when smoothed is absent | FR-003, FR-010 | Present-unreadable branch blocks before raw. |
| UI and command use one source | FR-006, FR-007 | Same server resolver plus exact-file CLI override. |
| Ignored artifacts never activate smoothing | FR-012 | Shared `scene_extraction_files()` authority. |
| Scaffold precedence remains | FR-013 | Shared resolver collapses candidates before selection. |
| Source files are not mutated by use | FR-014 | Resolver read-only; conditional raw dirty-save; CLI reads only. |
| Other stages remain raw-configured | FR-016 | Smoothed resolver called only by selected-scene projection/Narrate builder. |
