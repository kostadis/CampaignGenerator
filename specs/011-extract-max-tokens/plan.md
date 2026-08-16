# Implementation Plan: Scene Extraction Token Limit from the UI

**Branch**: `011-extract-max-tokens` | **Date**: 2026-08-17 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/011-extract-max-tokens/spec.md`

## Summary

The Session Doc Editor's Config drawer lets a GM set the Narrate stage's
per-scene output token cap (`narrate.tokens`, persisted, forwarded to
`sd_narrate --narrate-tokens`), but the Extract stage has no equivalent: no
persisted config field, no drawer control, and `_build_reextract_cmd` never
forwards a value to `scene_extract`'s existing `--max-tokens` flag, so every
extraction silently runs on that CLI's own hardcoded default (8192).

The fix mirrors the Narrate knob exactly, one layer at a time: a new
`ExtractKnobs` group (`tokens: int = 8192`) alongside `NarrateKnobs`/
`ScrubKnobs` in the `session_doc.yaml` schema; `_build_reextract_cmd` forwards
it as `--max-tokens`, the same way `_build_narrate_cmd` forwards
`narrate.tokens` as `--narrate-tokens`; `GET`/`PUT /api/editor/config` and the
config store carry the new group; `KnobDrawer.vue`'s Stage ② Extract section
gains a "Token limit" field identical in shape to Stage ④'s. No change to
`session_doc/scene_extract.py` itself — its CLI flag already exists and
already does the right thing; the gap is entirely that nothing upstream of it
ever sets the flag.

## Technical Context

**Language/Version**: Python 3.11+ (backend, Pydantic v2 models), TypeScript + Vue 3 (frontend, `<script setup>`)

**Primary Dependencies**: FastAPI (router), Pydantic (`SessionEditorConfig` and its nested `*Knobs` models, `extra="forbid"`), Pinia (frontend config store)

**Storage**: Per-campaign `<config>/session_doc.yaml`, read/written exclusively through `SessionEditorConfigService` (`server/session_editor_config_service.py`) — no other writer, per Constitution VI/VIII

**Testing**: pytest — `tests/test_session_editor_config_service.py` (schema/service unit coverage, mirrors its existing `NarrateKnobs`/`ScrubKnobs` cases) and `tests/test_editor_pipeline.py` (route-level coverage of `_build_reextract_cmd`/`_build_narrate_cmd`, mirrors its existing narrate-tokens-forwarding case). No automated frontend test suite exists for this view; per repo convention, UI changes are additionally verified by running the dev server and exercising the Config drawer directly.

**Target Platform**: Local FastAPI + Vue dev server (single-user desktop web app, per project convention — no concurrent-user concerns)

**Project Type**: Web application (existing `server/` + `frontend/` split in this repo)

**Performance Goals**: N/A — a config value, not a hot path

**Constraints**: `SessionEditorConfig` and every nested knob group are `extra="forbid"` (Constitution: strict, single-authority config, no `ui_state.yaml` fallback). Must not change behavior for any campaign that hasn't set the new field (spec FR-004) — the new field's default MUST equal `scene_extract.py`'s existing argparse default (8192) so "unset" and "explicitly set to the tool's current default" are indistinguishable in effect.

**Scale/Scope**: One new Pydantic model (`ExtractKnobs`, one field) + wiring through 5 existing files (schema, service, router, frontend store, `KnobDrawer.vue`/`SessionDocEditor.vue`). No data migration — this is a new field, not a remap of a legacy flat key, so `TYPED_SESSION_DOC_TO_GROUPED` needs no new entry.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **VI. CLI is the Engine, UI is a Face** — ✅ `scene_extract.py`'s `--max-tokens` flag already exists and is unchanged. Exposing it is exactly "adding it to the corresponding `_build_*_cmd()` in the router" — the clause's own example. No pipeline logic moves into the router.
- **I. Disk is Truth** — ✅ The new knob lives in `session_doc.yaml`, the same disk file every other editor knob already lives in. Nothing new is cached in the browser only (Principle IX's file-is-the-interchange rule also applies cleanly: the value is inert to CLI/chat use exactly the way `narrate.tokens` already is).
- **X. Selection is Explicit; No Silent "All"** — ✅ Not implicated: this is a scalar tuning knob on an already-explicit, already-human-triggered action (clicking Extract/Re-Extract), not a batch scope selection.
- **II. Human Checkpoint** — ✅ Not implicated: no new LLM call or pipeline stage is introduced; this only changes what value an existing, already-gated call is capped at.

No violations. No entries needed in Complexity Tracking.

*Post-Phase-1 re-check*: unchanged — the design below stays entirely inside the pattern the gates above already cleared.

## Project Structure

### Documentation (this feature)

```text
specs/011-extract-max-tokens/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md         # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   └── editor-config-api.md
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
server/
├── session_editor_config_shared.py   # SessionEditorConfig, NarrateKnobs, ScrubKnobs
│                                      #   → add ExtractKnobs, wire into SessionEditorConfig
├── session_editor_config_service.py  # ResolvedEditorConfig, resolved_editor_config()
│                                      #   → add `extract: ExtractKnobs` field + resolution
└── routers/
    └── scene_editor.py               # _serialize_resolved, _build_reextract_cmd,
                                       #   _build_narrate_cmd (reference pattern)
                                       #   → emit "extract" in GET, forward --max-tokens

frontend/src/
├── stores/config.ts                  # editorConfig shape / updateEditor() passthrough
├── components/scene-editor/
│   └── KnobDrawer.vue                # Stage ② Extract section → add Token limit field
│                                      #   (mirrors Stage ④ Narrate's, lines ~251-262)
└── views/session/
    └── SessionDocEditor.vue          # extractTokens ref, load/build/watch/v-model wiring
                                       #   (mirrors narrateTokens throughout)

tests/
├── test_session_editor_config_service.py  # + ExtractKnobs default/persist/strict cases
└── test_editor_pipeline.py                # + --max-tokens forwarding case for extract
```

**Structure Decision**: No new files beyond the docs above and `tasks.md`. This is a narrow, additive change threaded through the existing web-application layout (`server/` FastAPI backend, `frontend/` Vue app) already documented in the repo's own `CLAUDE.md` — every touched file already exists and already carries the sibling `narrate`/`scrub` pattern this feature copies.

## Complexity Tracking

*No violations — table omitted.*
