# Phase 0 Research: Session Directory Re-Points Editor Paths

**Feature**: `017-session-dir-repoint` | **Date**: 2026-08-28

All Technical Context unknowns are resolved here. No `NEEDS CLARIFICATION`
remains.

## Ground truth established before deciding anything

Read directly from the tree, not assumed:

| Fact | Evidence |
|---|---|
| Session-scoped paths are *stored relative* and *resolved absolute on read* | `SessionEditorConfigService._relativized_paths` / `.resolved_editor_config` (`server/session_editor_config_service.py:244`, `:366`) |
| The re-tracking the feature asks for is already **correct and tested** server-side | `tests/test_session_editor_config_service.py:568` — "Switching session_dir alone must retrack the relative value" |
| out-of-the-abyss' live `session_doc.yaml` stores relative session paths today | `config/session_doc.yaml`: `scene_extractions_dir: scene_extractions` |
| `refreshEditor()` has **no caller outside the store** | `grep -rn "refreshEditor" frontend/src` → only `stores/config.ts:177,210,218,225,231,243` |
| `updateRuntime()` refetches `/api/config/` only | `frontend/src/stores/config.ts:197-201` → `refresh()` at `:159` |
| `session_dir` is written from exactly one place | `SessionConfig.vue:191`. `AppSidebar.vue` calls `updateRuntime` only for backend/model/batch |
| Every run command is built **server-side** from `resolved_editor_config()` | `server/routers/scene_editor.py:100`, and ~14 `cfg.paths.*` reads at `:259,:270,:292,:299,:606,:777,:851,:889,:1198,:1213,:1816,:1891,:2100` |
| The frontend never sends paths to a run route | no `paths` in any run-route body; the router reads the service |
| `PathField` **already** renders ✅ / ❌ not-found per field | `frontend/src/components/shared/PathField.vue:37-54,72-73` via `GET /api/config/path-status` |
| Every path in the editor drawer is a `PathField` / `MultiPathField` | `KnobDrawer.vue:104,111,117,124,130,136,142,148,161,271` |
| A load-warning channel already exists and already reaches the UI | `PlatformConfigService.load_warnings` (`:552`) → `"migration_warnings"` (`config_routes.py:47`) → `configStore.migrationWarnings` |
| Load-time *announced* normalisation is an established pattern here | `EditorPaths._drop_retired_fields`, `NarrateKnobs._drop_retired_fields` — strip + print to stderr rather than fail |
| `UIStateService` (the cited `_normalize_stored_paths` precedent) is **retired** | referenced only in comments: `platform_config_service.py:33`, `session_editor_config_service.py:240` |
| Backend tests are pytest; the frontend has **no** test runner | `pyproject.toml:94-96`; `frontend/package.json` has `dev`/`build`/`preview` only |

## Decisions

### D1 — Fix the round-trip, not just the refresh

**Decision**: The Session Doc Editor binds its path inputs to the **stored**
(relative) values and lets `PathField` resolve them for display. The resolved
absolute block stays in the response for read-only consumers, but it is no
longer the editing buffer, and it is never PUT back.

**Rationale**: The defect has two halves and only one of them is a refresh
bug. `GET /api/editor/config` returns paths already resolved absolute; the
editor loads those into its refs; the drawer's debounced auto-save PUTs them
back; `relativize_path` cannot collapse a path that does not sit under the
current `session_dir`, so it stores it verbatim (`platform_config_service.py:
805-808` — "genuine out-of-tree override"). A stale absolute is therefore
*promoted into a permanent override*. Refreshing more often shrinks the race
window; it does not close it. Binding to the stored value removes the
absolute from the write path entirely, so there is nothing to promote.

**Alternatives considered**:

- *Add `refreshEditor()` to `updateRuntime` and stop.* Rejected: leaves the
  poisoning mechanism intact. A second tab, an in-flight debounce, or an SSE
  reconnect still writes a pre-switch absolute. It also fails FR-003 by
  construction.
- *Make `relativize_path` smarter at write time.* Rejected: at write time the
  service cannot distinguish "stale value from the session we just left" from
  "deliberate override the GM typed" — the two are byte-identical. Only a read
  that can see the current session directory's siblings has enough context.
- *Have the frontend relativize before PUT.* Rejected: a second, independent
  derivation of a rule the server already owns (FR-010; the Split-Brain the
  code comments at `session_editor_config_service.py:232-243` exist to prevent).

### D2 — Stale-pin detection: sibling-of-current-session, not a hardcoded `summaries/`

**Decision**: An absolute session-scoped value is a **stale pin** iff it
resolves under the *parent directory of the current `session_dir`* but **not**
under `session_dir` itself. Anything else absolute is a **deliberate
override** and is left alone.

**Rationale**: Derives the "session-directory tree" from the value the GM
actually set instead of assuming a `summaries/` convention, so a campaign with
a different layout behaves identically. It is also exactly the FR-004 /
FR-005 boundary: a sibling session folder is never a meaningful target, while
a path on another volume plainly is.

**Alternatives considered**:

- *Hardcode `<campaign>/summaries/`.* Rejected: re-derives a layout the
  session directory already encodes, and silently misfires on any campaign
  that does not use that name.
- *Treat every absolute session-scoped value as stale.* Rejected: destroys
  genuine overrides, violating FR-005.
- *Match on a date-shaped basename.* Rejected: session folders are not
  required to be dates, and this smuggles in a naming convention.

### D3 — Heal on read, write only through the existing choke point

**Decision**: `resolved_editor_config()` computes healed paths and warnings.
`get_config()` keeps returning the raw stored document. Nothing writes. The
healed value reaches disk on the next write that happens for an independent
reason, through the unchanged `_relativized_paths` choke point.

**Rationale**: This is what makes the GM's "heal on load" answer survive
Principle XIII ("no lazy in-place upgrade"). A read never mutates a workspace;
the correction is announced (D4); no schema changes shape, so there is nothing
for an out-of-band migrator to migrate. Keeping `get_config()` raw also
preserves round-trip fidelity for `server/migrate_session_doc.py` and for the
service's own tests.

**Alternatives considered**:

- *Heal and immediately save.* Rejected outright: this is the lazy in-place
  upgrade the constitution names, performed at the moment the GM is least
  expecting it.
- *Ship a one-shot `server/migrate_session_doc_paths.py`.* Rejected as the
  primary path — no schema shape changes, so the migrator would exist purely to
  normalise values a read can normalise safely. Retained as the documented
  fallback if the Constitution Check in this plan is overruled at review.

### D4 — Announce through a `warnings` list on the editor-config wire shape

**Decision**: `ResolvedEditorConfig` gains `warnings: list[str]`, serialized as
`"warnings"` by `_serialize_resolved` and rendered by the editor. Each entry
names the field, the stored value, and the value now in use.

**Rationale**: Mirrors the channel that already works —
`PlatformConfigService.load_warnings` → `"migration_warnings"` →
`configStore.migrationWarnings` — so the UI has a proven place to put it and no
second mechanism is invented. Satisfies FR-006 and Principle VIII (state is
discoverable, seams visible).

**Alternatives considered**:

- *stderr only*, as `_drop_retired_fields` does. Rejected as insufficient: the
  server usually runs detached and the GM never sees its stderr. Kept
  *additionally*, because it is the pattern for config-load notices and costs
  nothing.
- *A transient toast.* Rejected: the condition persists until the next write,
  so the notice must persist too.

### D5 — Refresh the editor slice when `session_dir` changes; re-hydrate on `editorConfig` identity

**Decision**: `updateRuntime()` also calls `refreshEditor()` when its partial
carries `session_dir`. `SessionDocEditor` watches `config.editorConfig` and
re-runs `loadConfigFields()` when it changes, guarded so the re-hydration does
not echo back through the debounced auto-save.

**Rationale**: `refreshEditor()` already exists and is already the documented
"call after any write that touches the session-editor slice" (`stores/config.ts:
175-179`); it simply has no caller. Watching `editorConfig` — the slice the
component actually reads — rather than `resolved.runtime.session_dir` keeps one
derivation (FR-010) and also covers profile activation and any other write that
replaces the slice.

**Alternatives considered**:

- *Refetch on route enter.* Rejected: does not cover an editor already mounted,
  and `config.load()` is memoized (`loadPromise`, `stores/config.ts:119`) so a
  second `load()` is a no-op for the life of the page.
- *Refresh the editor on every `updateRuntime`.* Rejected: backend/model/batch
  changes from the sidebar do not touch session-scoped paths; refetching there
  is a wasted round trip on the app's most-clicked control.

### D6 — Order the two writes on Session Config

**Decision**: `SessionConfig.saveConfig()` writes `runtime.session_dir` first,
then the typed sections.

**Rationale**: FR-002 acceptance scenario 2. Today `persistTypedSections()`
runs first (`SessionConfig.vue:186` before `:191`), so every path in that write
is relativized against the session the GM is leaving. The values happen to be
relative today, so the bug is latent rather than live — which is exactly why it
should be closed now rather than discovered later.

### D7 — User Story 4 is almost entirely already built

**Decision**: No new existence-checking machinery. Confirm coverage, and let
D1 make it correct.

**Rationale**: `PathField` already debounces a `GET /api/config/path-status`
call on its *resolved* path and renders ✅ / ❌ not found, and every path in the
drawer is a `PathField`. It reports the wrong thing today only because the
value it is handed is stale. A second consequence of D1 arrives free: because
the editor will hold relative values, `PathField`'s `isRelative` hint
(`→ /abs/path`, `PathField.vue:82`) starts rendering in the editor, where it has
never fired.

**Confirmed, not assumed**: `MultiPathField` (narrate context, the one
non-`PathField` path input) probes the same `GET /api/config/path-status`
endpoint and renders a per-entry status
(`MultiPathField.vue:35-36,68-69`). So *every* path input in the editor
already reports existence, and US4 adds no new machinery at all — it is a
verification phase. The one thing the quickstart still asserts rather than
assumes is that `resolvePathWithBase` re-evaluates on a `session_dir` change:
it reads a pinia ref inside a `computed`, so it should, but that is the hinge
US4 rests on.

### D8 — Delivery: worktree, and an Opus/Sonnet split

**Decision**: Implementation runs in a dedicated git worktree off `main`
(`.claude/worktrees/` already exists in this repo). Task decomposition,
sequencing, the Constitution Check and review gates are Opus's; individual
task execution is Sonnet's.

**Rationale**: GM-stated constraint. It also shapes `tasks.md`: each task must
name its files and its acceptance check inline, because the implementer holds
no orchestration context. The natural gate boundaries are the phase edges —
service layer green before the wire shape changes, wire shape green before the
frontend binds to it.

**Consequence for the plan**: the backend/frontend split is not merely a
directory split, it is the hand-off contract. Phase 2 (service) and Phase 3
(wire) are fully pytest-verifiable; Phase 4 (frontend) has no test runner in
this repo, so its gate is `npm run build` (which runs `vue-tsc -b`) plus the
manual quickstart.

## Resolved unknowns

| Unknown | Resolution |
|---|---|
| Does re-pointing break the run commands? | No. Every command is built server-side from `resolved_editor_config()`; the frontend sends no paths. Storage stays relative, so run-time resolution is already correct. |
| Is a schema migration required? | No. No field is added, removed, or retyped in `session_doc.yaml`. A campaign whose paths are already relative is byte-identical after this change. |
| Where do warnings surface in the UI? | The editor's existing header/status area, fed by a new `warnings` key, mirroring `migrationWarnings`. |
| How is the frontend verified without a test runner? | `npm run build` (`vue-tsc -b` typecheck) plus `quickstart.md`. Adding vitest is out of scope and would be its own feature. |
| Does the boot override (`--session-dir`) get the same behaviour? | Yes, for free: it flows through `platform.resolved()` into `resolved_editor_config()`. The persisted-only rule in `_relativized_paths` (`:244-250`) already prevents a boot override from being written to disk. |
