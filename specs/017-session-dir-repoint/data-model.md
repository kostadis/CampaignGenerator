# Phase 1 Data Model: Session Directory Re-Points Editor Paths

**Feature**: `017-session-dir-repoint` | **Date**: 2026-08-28

No stored schema changes shape. `session_doc.yaml` and `platform.yaml` parse
before and after this feature identically; a campaign whose session paths are
already relative is byte-identical afterwards. What changes is the **derived**
view and one **classification rule**.

## Stored entities (unchanged)

### `EditorPaths` — `<config>/session_doc.yaml` → `paths`

`server/session_editor_config_shared.py`, `extra="forbid"`. Unchanged: no
field added, removed, renamed or retyped.

| Field | Scope | Stored as |
|---|---|---|
| `session_recap` | session | name relative to `runtime.session_dir` |
| `session_summary` | session | name relative to `runtime.session_dir` |
| `scene_extractions_dir` | session | name relative to `runtime.session_dir` |
| `narration_dir` | session | name relative to `runtime.session_dir` |
| `output_dir` | session | name relative to `runtime.session_dir` |
| `party` | campaign | name relative to `campaign_dir` |
| `voice_dir` | campaign | name relative to `campaign_dir` |
| `examples_dir` | campaign | name relative to `campaign_dir` |
| `genre_file` | campaign | name relative to `campaign_dir` |

Scope membership is service-owned metadata, not per-field storage:
`_SESSION_PATH_FIELDS` / `_CAMPAIGN_PATH_FIELDS`
(`server/session_editor_config_service.py:42-51`). This feature does not move
any field between the two tuples.

### `runtime.session_dir` — `<config>/platform.yaml`

The single declaration of the current session. Written from
`SessionConfig.vue` via `PUT /api/config/runtime`; optionally overridden for
one process by `--session-dir` at boot, which is **never** persisted.

## The classification rule (new)

Given a stored session-scoped value `V` and the current session directory `S`,
`V` falls into exactly one of four states. This is the whole of the new logic.

| State | Condition | Resolved to | Stored form after next write | Warns |
|---|---|---|---|---|
| **Relative** | `V` is not absolute | `S / V` | unchanged | no |
| **In-session absolute** | `V` is absolute and under `S` | `V` | collapsed to `V` relative to `S` | no |
| **Stale pin** | `V` is absolute, **not** under `S`, but under `parent(S)` | `S / basename-relative-to-its-own-session` | that relative name | **yes** |
| **Deliberate override** | `V` is absolute and not under `parent(S)` | `V` | `V`, verbatim | no |

Notes that make this precise:

- `parent(S)` is the parent directory of the *current* session directory —
  derived, never a hardcoded `summaries/` (research D2).
- The stale-pin re-point preserves the **name the value carried within its own
  session directory**, not merely its basename: a stale
  `…/20260811/narration/pass5` re-points to `narration/pass5` under `S`, not to
  `pass5`. This is what keeps FR-008 ("re-pointing preserves the name a field
  carries") true for nested values.
- Comparison is on resolved, symlink-normalised paths, matching the existing
  `Path.resolve()` / `is_relative_to` treatment in `relativize_path`
  (`platform_config_service.py:803-808`), so a trailing slash or a `~` is not a
  difference (spec edge case: cosmetic differences).
- When `S` is unset, **no** state applies and every session-scoped value passes
  through untouched — preserving the existing defensive rule that a
  session-scoped field is never relativized against `campaign_dir`
  (`relativize_path` docstring, `:770-781`).
- The rule is idempotent (FR-012): applying it to an already-relative or
  already-in-session value is the identity and emits no warning.

## Derived entities

### `ResolvedEditorConfig` (extended)

`server/session_editor_config_service.py:126`. Request-scoped, never
persisted. Two additive fields:

| Field | Type | Meaning |
|---|---|---|
| `paths_stored` | `EditorPaths` | The **healed stored** form — what the GM edits and what gets PUT back. Relative for anything session- or campaign-relative; absolute only for a deliberate override. |
| `warnings` | `list[str]` | One entry per stale pin re-pointed this read. Each names the field, the stored value, and the value now in use. Empty on a healthy config. |

Existing `paths` keeps its meaning exactly — absolute, resolved, what every
`_build_*_cmd()` in `server/routers/scene_editor.py` already reads. It is now
resolved *from the healed values*, which is what makes FR-001 true for a
damaged config as well as a healthy one.

**Invariant**: `paths` == `resolve(paths_stored)` for every field, always. A
test asserts this over all four classification states.

### Relationship to the write path

`_relativized_paths` (the write-time choke point,
`server/session_editor_config_service.py:244`) is **unchanged**. It becomes
mostly a no-op because the frontend now sends `paths_stored` — already
relative — rather than the absolute projection. It is deliberately kept: a
hand-authored absolute, a CLI caller, or a future consumer still gets
collapsed, and removing the only server-side inverse would be exactly the
Split-Brain the module docstring warns against.

## State transition — what a session switch does

```text
GM edits session_dir on Session Config
        │
        ├─► PUT /api/config/runtime   {session_dir: S'}     ◄── FIRST (D6)
        │      platform.yaml: runtime.session_dir = S'
        │
        ├─► PUT /api/editor/config    {paths: <relative names>}
        │      _relativized_paths against S'  →  no-op (already relative)
        │
        └─► GET /api/editor/config    (refreshEditor, D5)
               classification rule applied against S'
               paths_stored = healed relative names
               paths        = resolve(paths_stored, S')
               warnings     = [] unless a stale pin was found
                     │
                     ▼
        SessionDocEditor re-hydrates from paths_stored
        PathField resolves each for display + existence probe
```

Nothing in this sequence writes a value derived from the *previous* session
directory, which is the property FR-002 and FR-003 assert.

## Validation rules carried from requirements

| Rule | Source | Where enforced |
|---|---|---|
| A read never writes | FR-007 | `resolved_editor_config()` calls no `_save`; asserted by a test that stats `session_doc.yaml` mtime across a read |
| Deliberate overrides survive every switch | FR-005 | classification rule, "not under `parent(S)`" branch |
| Every re-point is announced | FR-006 | `warnings` non-empty ⟺ a stale pin was re-pointed |
| Re-pointing preserves the carried name | FR-008 | re-point uses the value's path relative to its own session directory |
| One rule for every session-scoped field | FR-010 | iteration over `_SESSION_PATH_FIELDS`; no per-field special case |
| Idempotent | FR-012 | second read of the same config yields identical `paths_stored` and empty `warnings` |
| Campaign-scoped fields unaffected | FR-013 | classification applies only to `_SESSION_PATH_FIELDS` |
