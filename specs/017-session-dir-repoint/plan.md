# Implementation Plan: Session Directory Re-Points Editor Paths

**Branch**: `017-session-dir-repoint` | **Date**: 2026-08-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/017-session-dir-repoint/spec.md`

## Summary

Setting the session directory on Session Config must re-point every
session-scoped path the Session Doc Editor shows, and must never leave the
previous session pinned in `session_doc.yaml`.

The server side is already correct: session paths are stored relative to
`runtime.session_dir` and resolved absolute on read, and
`tests/test_session_editor_config_service.py:568` already proves a session
switch re-tracks them. The defect is entirely in how the resolved view is
used. `GET /api/editor/config` hands the frontend **absolute** paths; the
editor loads them into its inputs; the drawer's debounced auto-save PUTs them
back; `relativize_path` cannot collapse a path that is not under the current
session directory, so it stores it verbatim as a "genuine out-of-tree
override". A stale display value is thereby promoted to a permanent pin, and
the field stops tracking the session directory forever.

The approach (research D1) is to stop round-tripping the projection. The
editor binds to the **stored** relative values and lets `PathField` resolve
them for display and for its existing existence check; the absolute block
remains in the response for read-only consumers. Alongside that, the service
heals values already pinned to a *sibling* session directory — re-pointing
them on read, announcing each correction, and never writing during a read
(research D2–D4). Finally the store refetches the editor slice when
`session_dir` changes, and Session Config commits the session directory before
the paths that depend on it (research D5–D6).

User Story 4 needs **no** new code: `PathField` and `MultiPathField` both
already probe `GET /api/config/path-status` and render per-path existence, and
every path input in the drawer is one of the two. They report the wrong thing
today only because the value they are handed is stale, so US4 becomes a
verification phase once the value is right.

## Technical Context

**Language/Version**: Python ≥3.9 (backend, `pyproject.toml:5`); TypeScript
5.9 / Vue 3.5 (frontend)

**Primary Dependencies**: FastAPI + pydantic (config services), Pinia + Vue
Router (frontend state), Vite 8 + `vue-tsc` (build/typecheck)

**Storage**: YAML documents on disk — `<config>/session_doc.yaml`
(session-editor slice) and `<config>/platform.yaml` (`runtime.session_dir`).
No database. No schema shape change in this feature.

**Testing**: pytest (`pyproject.toml:94-96`). The frontend has **no** test
runner — `frontend/package.json` exposes `dev` / `build` / `preview` only — so
frontend verification is `npm run build` (which runs `vue-tsc -b`) plus the
manual `quickstart.md`. Adding vitest is explicitly out of scope.

**Target Platform**: Linux; a locally-run FastAPI server plus a browser SPA,
single operator.

**Project Type**: Web application — `server/` (FastAPI, config services,
routers) + `frontend/` (Vue SPA), sharing `campaignlib/` and the CLI scripts
the routers shell out to.

**Performance Goals**: Not a performance feature. The only new per-request
work is a path-prefix comparison per session-scoped field (5 fields), and one
extra `GET /api/editor/config` per session-directory change. Both are
negligible against the existing per-field `path-status` probes.

**Constraints**: A read must not write to disk (Principle XIII, research D3).
Path relativization must keep exactly one implementation, server-side
(Principle XII, FR-010). Run-command construction must not change — every
`cfg.paths.*` read in `server/routers/scene_editor.py` keeps working unmodified.

**Scale/Scope**: 5 session-scoped path fields, 4 campaign-scoped, across 5
campaigns in this workspace. Backend touch: 2 service modules, 1 router.
Frontend touch: 1 store, 2 views, 0–1 shared components. Estimated ~10 new or
extended pytest cases.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution v1.3.0. Every principle tested by name, as Governance requires.

| # | Principle | Verdict | Basis |
|---|---|---|---|
| I | Disk is Truth, the Model is a Draft | **PASS** | Reads never write (D3). The resolved block is explicitly a projection; `get_config()` keeps returning the raw stored document. No LLM anywhere in this path. |
| II | The Human Checkpoint is Non-Negotiable | **PASS** | No LLM call is added, so no decision is removed from the GM. The one automatic decision — "this sibling-session pin is stale" — is deterministic, announced with before/after (FR-006), and overridable by retyping the field. |
| III | Retrieval and Render are Separated | **PASS (not applicable)** | No retrieval or render call is touched. `tests/test_retrieve_render_isolation.py` must stay green. |
| IV | Verbatim is Sacred | **PASS (not applicable)** | No transcript, quote, or generated prose is read or written. |
| V | One Seam per Boundary | **PASS** | No external dependency is crossed. The filesystem-path seam stays exactly where it is: `PlatformConfigService.resolve_path` / `.relativize_path`. |
| VI | CLI is the Engine, UI is a Face | **PASS** | No pipeline logic moves into the server. `server/routers/scene_editor.py`'s `_build_*_cmd()` functions are untouched and keep reading `resolved_editor_config()`. |
| VII | Extract Once, Synthesize Deliberately | **PASS (not applicable)** | No extraction or synthesis pass is involved. |
| VIII | State is Discoverable | **STRENGTHENED** | The feature's whole point. A silently-pinned path is state visible only to whoever opens the YAML; FR-006 surfaces the correction and FR-009 surfaces which resolved targets do not exist. |
| IX | The UI Mechanizes; Claude Converses | **PASS** | No judgment moves into the UI. Files stay the interchange — the GM can still hand-edit `session_doc.yaml`, and a hand-authored relative value behaves exactly as before. |
| X | Selection is Explicit; No Silent "All" | **PASS (not applicable)** | No batch operation and no token-spending pass is added. |
| XI | Parity is Bidirectional | **PASS** | No new capability, so nothing to expose. The behaviour lands in `SessionEditorConfigService`, which is what a `--session-dir` boot-override run reads too (FR-011), so the CLI path inherits it without a second implementation. Nothing is deliberately UI-only. |
| XII | One Spelling per Option | **PASS** | No new flag or option. Relativization keeps one implementation server-side; the frontend is explicitly forbidden (research D1, alternative 3) from growing a second copy of the rule. |
| XIII | Breaking State Changes Migrate Out of Band | **PASS, with a recorded justification — see below** | |

### Principle XIII — the one gate that needs an argument

The spec's User Story 3 heals damaged values when the configuration is read.
Principle XIII prohibits "no lazy in-place upgrade" — a pipeline that rewrites
state because it happened to read it. The claim is that this feature is not
that, on three grounds, each nailed to a requirement:

1. **Nothing changes shape.** XIII governs changes to the *shape* of state — a
   schema, a layout, a filename convention. No field in `session_doc.yaml` is
   added, removed, renamed, or retyped. `EditorPaths` is unchanged. A campaign
   whose stored paths are already relative — which is every campaign in this
   workspace that has not hit the bug, including out-of-the-abyss today — is
   **byte-identical** after this change. This is value normalisation inside an
   unchanged schema.
2. **The read does not write.** FR-007 makes this binding:
   `resolved_editor_config()` computes the healed view and returns it;
   `get_config()` still returns the raw document; nothing calls `_save`. The
   corrected value reaches disk only through the existing write choke point,
   on a write the GM triggered for their own reasons. No workspace is mutated
   by being looked at.
3. **Nothing is silent.** XIII's stated enemy is "a state change that reaches a
   workspace as an unexplained failure, or as data quietly discarded". FR-006
   requires every correction to name the field, the stored value and the value
   now in use. This is the same posture `EditorPaths._drop_retired_fields`
   already takes — normalise on load, announce, never fail the boot.

**Precedent in-tree**: announced load-time normalisation is the established
pattern here (`EditorPaths._drop_retired_fields`,
`NarrateKnobs._drop_retired_fields`), and the retired `UIStateService`
carried a `_normalize_stored_paths` pass doing exactly this for the same
fields — still cited as the reference by
`session_editor_config_service.py:240`.

**If this is overruled at review**, the fallback is prescribed and cheap:
move the heal into a one-shot `server/migrate_session_doc_paths.py` following
the `server/migrate_*.py` shape (`--campaign-dir`, a `--force` that refuses to
clobber, reading the old file raw, a `tests/test_migrate_*.py`), and ship
`specs/017-session-dir-repoint/migration.md`. User Stories 1, 2 and 4 are
unaffected by that swap — only US3 moves.

**Decided by**: the GM, explicitly, when asked how to treat configs already
pinned to an old session (answer: "heal on load", with genuine out-of-tree
overrides preserved). Recorded here per Principle XI's requirement that a
scope ruling name who decided and why.

### Post-Design Re-Check

Re-evaluated after `data-model.md`, `contracts/` and `quickstart.md` were
written. No verdict changed. Two things the design review tightened:

- The wire shape gains `paths_stored` and `warnings` — **additive only**. No
  existing key changes meaning, so `_serialize_resolved` stays the single
  source of the wire shape for both `GET /config` and profile-activate, and
  the two cannot drift (Principle V's spirit at the wire boundary).
- The frontend was checked for a second relativization: there is none, and
  the plan forbids adding one. `frontend/src/utils/paths.ts` resolves for
  *display* only and never inverts.

**Complexity Tracking**: not required — no violation stands unjustified.

## Project Structure

### Documentation (this feature)

```text
specs/017-session-dir-repoint/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── editor-config.md # Phase 1 output — the wire shape delta
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
server/
├── session_editor_config_service.py   # heal-on-read; warnings; paths_stored
│                                      #   _SESSION_PATH_FIELDS, _relativized_paths,
│                                      #   resolved_editor_config, ResolvedEditorConfig
├── platform_config_service.py         # read-only here: resolve_path / relativize_path
│                                      #   are the seam and are NOT modified
└── routers/
    └── scene_editor.py                # _serialize_resolved: + paths_stored, + warnings
                                       #   (every _build_*_cmd() untouched)

frontend/src/
├── stores/config.ts                   # updateRuntime -> refreshEditor when session_dir
├── views/session/
│   ├── SessionConfig.vue              # write session_dir BEFORE typed sections
│   └── SessionDocEditor.vue           # bind paths_stored; watch editorConfig; re-hydrate
├── components/scene-editor/
│   └── KnobDrawer.vue                 # (verify only — already all PathField)
├── components/shared/
│   ├── PathField.vue                  # (verify only — existence check already present)
│   └── MultiPathField.vue             # (verify only — same path-status probe per entry)
└── utils/paths.ts                     # (verify only — display resolution, never inverts)

tests/
├── test_session_editor_config_service.py   # heal, override-preservation, idempotence,
│                                           #   announcement text, no-write-on-read
├── test_editor_service_integration.py      # switch -> resolved view re-points end to end
└── test_config_routes.py                   # wire shape: paths_stored + warnings present
```

**Structure Decision**: Existing web-application layout — `server/` (FastAPI
services + routers) and `frontend/` (Vue SPA) — with backend tests in
`tests/`. No new directory, module, or service is introduced. The change is
deliberately concentrated in `SessionEditorConfigService`, which is the one
object that already owns the session/campaign path split, so that the CLI
boot-override path (FR-011) inherits the behaviour without a second
implementation.

## Phasing and hand-off gates

Sized for the GM's Opus-orchestrates / Sonnet-implements split (research D8).
Each gate is a command that either passes or fails — no judgment call is
delegated to the implementer.

| Phase | Scope | Gate |
|---|---|---|
| 1. Setup | Create the worktree off `main`; confirm `pytest` green at baseline | `pytest` green, `npm run build` clean |
| 2. Service (US3 core) | Heal-on-read, warnings, `paths_stored` on `ResolvedEditorConfig` | New pytest cases green; no existing test modified to pass |
| 3. Wire (US1/US2 backend half) | `_serialize_resolved` additive keys | `tests/test_config_routes.py` green; `_build_*_cmd()` diff is empty |
| 4. Frontend (US1/US2 front half) | Bind stored values; refresh on switch; write ordering | `npm run build` clean; quickstart §1–§3 pass by hand |
| 5. US4 verification | Confirm existence marking on re-pointed fields | quickstart §4 passes by hand |
| 6. Polish | Warnings rendering, docs note in `docs/config/session-editor-isolation.md` | Full `pytest` + `npm run build`; quickstart end to end |

Phases 2 and 3 are fully machine-verifiable and are the safest Sonnet work.
Phase 4 has no test runner behind it, so it is the phase where Opus reviews the
diff before the gate is called.

**Worktree**: implementation happens in a dedicated git worktree off `main`
(this repo already keeps `.claude/worktrees/`), never on a shared checkout.
