# Implementation Plan: Remove scrub_mechanics.py (superseded by the /scrub skill)

**Branch**: `010-remove-scrub-mechanics` | **Date**: 2026-08-17 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/010-remove-scrub-mechanics/spec.md`

## Summary

Delete the retired autonomous LLM scrub pass (`session_doc/scrub_mechanics.py`)
and every piece of code that exists only to drive it — the two action routes,
the `ScrubKnobs` config model, the frontend Scrub/Scrub All buttons and their
wiring, the console-script entry, and its dedicated test file — while
preserving three things that only *look* like part of the same feature: the
`.scrubbed.md` file-preference contract in `assemble.py` (producer-agnostic,
untouched), the passive `has_scrubbed` status read the UI still shows (a
different file can produce that artifact now — the `/scrub` Claude Code skill),
and `split_frontmatter_raw()` (a real shared utility, relocated into
`campaignlib/textproc.py` rather than deleted).

Constitutionally this is a Principle II (*The Human Checkpoint is Non-
Negotiable*) cleanup: `scrub_mechanics.py` was exactly the anti-pattern the
constitution's own worked example (`campaignlib.py`'s `stream_api`/`call_api`
retry note aside) exists to prevent — an LLM call whose output fed the final
narration doc automatically, with no human gate, and issue #151 (the
spell-stripping incident) is the proof it failed in exactly the way the
principle predicts. The `/scrub` skill's propose→confirm→apply flow is the
correct replacement (human confirms every candidate before anything is
rewritten); this plan only removes the superseded half.

## Technical Context

**Language/Version**: Python 3.11 (backend, CLI), TypeScript/Vue 3 (frontend)

**Primary Dependencies**: FastAPI (`server/routers/scene_editor.py`), Pydantic
(`server/session_editor_config_shared.py`), Vue 3 + Pinia (frontend), pytest

**Storage**: Per-campaign `<config>/session_doc.yaml` (Pydantic-validated YAML,
`extra="forbid"`); per-scene `.scrubbed.md` sibling files on disk (unchanged)

**Testing**: `python -m pytest tests/`; `cd frontend && npm run build` as a
best-effort sanity check (not blocking if the frontend toolchain isn't
available in this environment)

**Target Platform**: Linux server (FastAPI + subprocess-shelled CLIs), browser
frontend

**Project Type**: Web application (FastAPI backend + Vue 3 frontend) plus a
library of standalone CLI tools sharing `campaignlib`

**Performance Goals**: N/A — this is a deletion; no new hot path

**Constraints**: Every removal must leave the app in a state where (a) an
existing, already-saved `session_doc.yaml` from before this change still loads
(FR-005), and (b) `python -m pytest tests/` passes end to end (FR-012)

**Scale/Scope**: ~10 files touched for the core removal (1 deleted CLI, 1
deleted test, 1 router, 2 config-shared files, 2 frontend components, 1
pyproject.toml line), plus 6 incidentally-referencing test files each patched
narrowly, plus 3–7 doc files

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Disk is Truth, the Model is a Draft** — PASS. Nothing here changes what's
  on disk being truth; `.scrubbed.md` remains a file, not a cache of anything.
- **II. The Human Checkpoint is Non-Negotiable** — PASS, and this is the
  principle this feature *serves*: it removes the one CG pipeline stage that
  let an LLM rewrite prose and hand it straight to `assemble.py` with no human
  gate in between. The replacement (`/scrub`) already has the gate; this repo
  just stops offering the ungated path alongside it.
- **III. Retrieval and Render are Separated** — N/A. `scrub_mechanics.py` did
  neither retrieval nor grounding-doc rendering; it's a standalone rewrite pass,
  not a `retrieve_render_isolation`-covered pipeline.
- **IV. Verbatim is Sacred** — PASS/supports. Consistent with the constitution's
  own framing: `scrub_mechanics.py`'s failure mode (rewriting spell names out of
  narration, #151) is precisely an unreviewed model touching text it should not
  have touched unaccompanied. Removing the ungated path reduces the surface for
  that failure to recur through the web UI.
- **V. One Seam per Boundary** — PASS. No new external dependency introduced;
  one fewer `console_script()` seam to keep in sync.
- **VI. CLI is the Engine, UI is a Face** — PASS. The router's `/scrub` routes
  were already a thin `console_script("scrub_mechanics")` shell-out; removing
  both the CLI and its two routes together keeps CLI and UI from drifting (no
  route survives pointing at a deleted script).
- **VII. Extract Once, Synthesize Deliberately** — N/A, not a grounding-doc
  generator.
- **VIII. State is Discoverable** — PASS, explicitly preserved: `has_scrubbed`
  keeps the `.scrubbed.md` artifact's presence discoverable from the UI even
  after its *producer* moves outside the app (FR-002).
- **IX. The UI Mechanizes; Claude Converses** — PASS, and this is the second
  principle this feature serves: scrubbing was a UI button *replacing* judgment
  (an autonomous rewrite) rather than mechanizing a step whose judgment stays
  with the human. Retiring it in favor of a Claude-conversation skill
  (`/scrub`) is this principle applied, not violated.
- **X. Selection is Explicit; There is No Silent "All"** — N/A to this removal;
  the retired `Scrub All` route already operated over an explicit
  `narration_dir` glob, not an implicit "all campaigns" — no new selection
  surface is introduced or removed here beyond the button itself (covered under
  Principle IX above).

No violations. No entries needed in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/010-remove-scrub-mechanics/
├── plan.md              # This file
├── tasks.md             # Phase 2 output (/speckit-tasks)
└── checklists/
    └── requirements.md  # Spec quality checklist
```

No `research.md`, `data-model.md`, `contracts/`, or `quickstart.md` — this is a
deletion/refactor against an already fully-understood codebase (the task brief
plus the research below constitute the "research phase" in miniature; there is
no new data model or API contract being introduced, only surfaces being
retired). This is a deliberate, documented deviation from the full template
scaffold, not an oversight — nothing in those templates would carry information
not already captured in this plan's "Removal inventory" below.

### Source Code (repository root)

```text
# Backend
session_doc/scrub_mechanics.py         # DELETE (after extracting split_frontmatter_raw)
campaignlib/textproc.py                # ADD split_frontmatter_raw() next to split_frontmatter()
server/routers/scene_editor.py         # REMOVE /scrub/{n}, /scrub-all, "scrub" serialization key
server/session_editor_config_shared.py # REMOVE ScrubKnobs, scrub field, scrub_* migration-map
                                        #   entries; ADD retired-field validator on SessionEditorConfig
server/session_editor_config_service.py # REMOVE ScrubKnobs import/usage
pyproject.toml                         # REMOVE scrub_mechanics console-script line

# Frontend
frontend/src/views/session/SessionDocEditor.vue    # REMOVE scrubbing ref, scrubScene/scrubAll,
                                                     #   Scrub All button, @scrub wiring
frontend/src/components/scene-editor/ExtractionEditor.vue  # REMOVE scrubbing prop, 'scrub' emit,
                                                             #   Scrub button
frontend/src/components/scene-editor/KnobDrawer.vue # EDIT label text (drop ", Scrub")
frontend/src/stores/config.ts                        # EDIT stale comment (drop "scrub/")
frontend/src/components/scene-editor/SceneList.vue   # KEEP has_scrubbed dot, unchanged
frontend/src/views/session/ReviewAssemble.vue        # KEEP lifecycle.scrub badge, unchanged

# Tests
tests/test_scrub_mechanics.py          # DELETE
tests/test_frontmatter_parsers.py      # EDIT import path only
tests/test_batch_flag_uniformity.py    # EDIT remove scrub_mechanics.py from REGISTRAR_CLIS
tests/test_editor_pipeline.py          # EDIT drop ScrubKnobs import + scrub= kwarg
tests/test_editor_verify_routes.py     # EDIT drop scrub=base.scrub kwarg
tests/test_editor_profiles_routes.py   # EDIT drop "scrub" from expected key set
tests/test_editor_service_integration.py # EDIT drop scrub-specific assertions/tests
tests/test_migrate_session_doc.py      # EDIT swap scrub.enabled assertion for "field is gone"

# Docs
docs/web/session_doc_editor.md         # EDIT remove button/CLI refs, note /scrub skill
docs/cli/cli_tools.md                  # EDIT remove scrub_mechanics entries (2 locations)
docs/config/schema.md                  # EDIT remove scrub row from schema table
docs/config/values.md                  # EDIT remove scrub row from value map
docs/config/master.md                  # EDIT drop "scrub" from schema-group list
docs/config/service-cut.md             # EDIT drop "scrub" from CLI column
CLAUDE.md (repo root)                  # EDIT reword to not cite a live command
session_doc/assemble.py                # EDIT one docstring line (attribution only, not logic)
session_doc/verify_quotes.py           # NO CHANGE (already past-tense historical framing)
```

**Structure Decision**: Existing monorepo layout (FastAPI backend +
`server/routers/`, Vue 3 frontend under `frontend/src/`, standalone CLIs under
`session_doc/` sharing `campaignlib`). This feature adds no new
directories or modules — it is a pure subtraction plus one relocation
(`split_frontmatter_raw`), fitted into the existing structure exactly where
each removed piece already lived.

## Removal inventory — reasoning captured explicitly (per the human-checkpoint
## instruction to document scope decisions, not just make them)

### Keep vs. drop: `has_scrubbed` status vs. the scrub action

**Decision: KEEP** `_scrubbed_for_scene()` / `has_scrubbed` (backend) and the
`SceneList.vue` "Stage 4½" dot + `ReviewAssemble.vue` "④½ Scrub" lifecycle badge
(frontend). **DROP** the two action routes and the two UI buttons that trigger
them.

**Reasoning**: `.scrubbed.md` is explicitly still a legitimate artifact per the
task brief — `assemble.py` prefers it over the raw `.md` regardless of what
produced it, and the `/scrub` Claude Code skill produces the identical file
shape outside the web UI. A GM who ran `/scrub` in a Claude conversation still
benefits from the UI telling them "this scene has a scrubbed variant on disk"
before they hit Assemble — that's Principle VIII (*State is Discoverable*)
working as designed: the seam moved to a skill, but the state stayed visible
on disk and in the UI that reads disk. Removing the status display would make
a real file invisible to the GM for no correctness gain — nothing forces status
display and the action trigger to live or die together; they were only ever
coupled by being two features of the same word "scrub."

### `SessionEditorConfig` retired-field validator (not in the original task brief)

**Decision: ADD** a `RETIRED_SESSION_DOC_FIELDS = ("scrub",)` tuple and a
`@model_validator(mode="before")` on `SessionEditorConfig` itself, mirroring the
existing `EditorPaths._drop_retired_fields` / `NarrateKnobs._drop_retired_fields`
pattern already in `server/session_editor_config_shared.py`.

**Reasoning**: `SessionEditorConfig` is `extra="forbid"`, and
`save_session_editor_config` dumps the *full* model including defaults — so any
campaign that has ever opened the Session Doc Editor's config drawer (or hit
`PUT /api/editor/config` once) already has a persisted top-level `scrub:` block
on disk today. Deleting the `scrub` field without a strip-on-load step would
make every such campaign's `session_doc.yaml` fail `model_validate` and take
the editor down on boot — a correctness regression far worse than the dead code
being removed. This wasn't named in the task's reference map, but it follows
directly from the same file's own established convention for exactly this
situation (two prior precedents already exist in the file) and is required for
spec FR-005. Documented here rather than silently added.

### `TYPED_SESSION_DOC_TO_GROUPED` migration-map cleanup (not in the original task brief)

**Decision: REMOVE** the `"scrub_enabled": ("scrub", "enabled")` and
`"scrub_tokens": ("scrub", "tokens")` entries from
`server/session_editor_config_shared.py`'s `TYPED_SESSION_DOC_TO_GROUPED`.

**Reasoning**: This dict is `server/migrate_session_doc.py`'s single authority
for mapping a legacy flat `ui.session_doc` field to its grouped-schema target.
Four other retirements already have precedent comments in this exact table
(`roleplay_dir`/`summary_dir`, `narration_genre`, `characters`/`gm_player`) —
each removed from the map, with a comment, when its target field retired, so
the migration reports the legacy key as unrecognised/left-behind instead of
constructing a `dict` path into a group that no longer exists on the model.
Leaving the `scrub_*` entries in place after deleting `ScrubKnobs` would not
crash (the map just builds a `{"scrub": {...}}` dict that
`SessionEditorConfig.model_validate` would then reject) — but it would break
`build_grouped_config` for any pre-Phase-5 campaign still carrying
`scrub_enabled` in an old `ui_state.yaml`, and it would silently contradict the
file's own stated convention. Removed for internal consistency, following the
exact precedent already in the file.

### Doc-scope: which docs are "live reference" vs. "historical/archival"

**Decision**: Treat `docs/web/session_doc_editor.md`, `docs/cli/cli_tools.md`,
`docs/config/schema.md`, `docs/config/values.md`, `docs/config/master.md`, and
`docs/config/service-cut.md` as **live reference** (update them). Treat
`docs/config/session-editor-isolation.md` (explicitly headed "Status: ✅ Done
(2026-07-24)" with five dated commit hashes — a completed-migration
postmortem) the same as the explicitly-named-out-of-scope historical docs
(`specs/004-claude-api-batch/*`, `docs/design/MarkdownAsInput.md`,
`docs/design/SourceTreeRestructure.md`, `docs/design/QuoteTriage_research.md`,
`docs/design/ExtractionContract_implementation.md`,
`specs/007-two-phase-extraction/data-model.md`) — **leave it alone**.
`session_doc/verify_quotes.py`'s docstring already refers to `scrub_mechanics.py`
in past tense ("was an autonomous LLM repair pass... and was replaced by...") —
**no change needed**, it already reads correctly after this feature lands.

**Reasoning**: The distinguishing test applied is authorial framing, not
directory: present-tense text describing *current* system shape (a schema
table, a value map, a how-to walkthrough) goes stale and misleads the next
reader if left unfixed; a dated, status-stamped record of a *completed past
decision* is supposed to describe the past and stays correct forever regardless
of what the code does today. `docs/config/schema.md`'s `scrub` row
(`| scrub | ScrubKnobs | enabled (bool=False), tokens (int=16000) |`) and
`docs/config/master.md`'s field list both assert, in the present tense, that
this is the schema *today* — false after this change if left alone. This
extends the task brief's own reasoning (which drew exactly this line for the
already-named docs) to two doc groups the brief's grep pass didn't surface.

## Non-goals (explicitly out of scope)

- Modifying or extending the `/scrub` Claude Code skill itself (`mytools` repo)
  — it already exists and is not part of this repo.
- Any change to `session_doc/assemble.py`'s scrubbed-file-preference *logic*
  (`collect_scene_files`, `--no-prefer-scrubbed`) — only a one-line docstring
  attribution fix.
- Rewriting any of the six explicitly-named historical docs, or
  `docs/config/session-editor-isolation.md` per the reasoning above.
- Adding any new "scrub status" feature — the existing `has_scrubbed` /
  lifecycle-badge display is preserved exactly as-is, not enhanced.
