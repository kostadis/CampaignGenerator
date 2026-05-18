# CampaignGenerator — TODO

Active backlog. For the live feature inventory (RLM pipeline, batch API,
session-prep flows that already shipped), see [`docs/core/architecture.md`](docs/core/architecture.md).
For background/conventions, [`CLAUDE.md`](CLAUDE.md).

---

## UI

### [ ] Session Doc Editor — vertical stepper redesign

**Context**
The post-session pipeline is split across two screens with a
horizontal wizard on top:
1. `SessionWorkflow.vue` + `WizardShell` — 6-step horizontal wizard
   whose steps are routes (`/workflow/config`, `/workflow/editor?stage=…`).
2. `SessionConfig.vue` — Step 1 fields (`campaignDir`, `sessionDir`,
   `vttInput`, `sdSession`, `characters`, `voiceDir`, `examplesDir`,
   `vttContext`, …).
3. `SessionDocEditor.vue` — Steps 2-6 share this single page. It has
   its own `configured: boolean` toggle that flips between a config
   form and a 3-column workspace, duplicating `characters`, `voiceDir`,
   `examplesDir`, `context` from `SessionConfig`, plus adding `session`,
   `sessionSummary`, `sceneExtractionsDir`, `narrationDir`, `party`,
   `narrateTokens`, and mode flags.
4. Stage buttons (1/2/Plan/Final) live in one header bar at
   `SessionDocEditor.vue:638-678`. Stage 1, Stage 2, and Plan & Check
   stream subprocess stdout via `connectSSE` into a single shared
   `narrationOutput` ref (lines 309/336/360/390), rendered by
   `NarrationOutput → StreamOutput`. Plan & Check is the third button
   even though the user thinks of it as a distinct phase that produces
   its own artifacts (`plan.md`, `consistency_report.md`,
   `enhanced_sections.md`).

The user has to (a) re-enter overlapping config across two screens,
(b) mentally translate the horizontal wizard into the actual data
flow, (c) interpret a single shared output pane reused for every
stage with no per-stage history, and (d) mode-switch between "config"
and "editor" inside one page that already represents 5 wizard steps.

**Outcome**
One page. Left-side vertical stepper. Center pane changes per step.
Config is unified. Each pipeline stage owns its own run controls,
streaming/batch output panel, and a post-run "ready" artifact preview.
The 3-column scene/extraction editor is itself one step. Assemble is
the last step.

**Recommended approach**

*1. Page shell.* Replace `SessionWorkflow.vue`'s `<WizardShell>` +
`<router-view/>` with a single page that owns a left-side vertical
stepper and a step-driven center pane. Keep the route
`/workflow/editor` (drop the `?stage=` query — local state, not the
URL, drives the active step). Drop `/workflow/config` and `?stage=…`;
redirect old links to `/workflow/editor`.
- Rewrite `frontend/src/views/SessionWorkflow.vue` as the new shell.
- Delete `frontend/src/components/wizard/WizardShell.vue` after
  callers are migrated (`grep -r WizardShell frontend/src` first).
- Update `frontend/src/router/index.ts` to drop `/workflow/config` and
  redirect to `/workflow/editor`.

*2. Left pane — vertical stepper.* New
`frontend/src/components/wizard/VerticalStepNav.vue`. Props:
`steps: { id, label, status }[]`, `activeId`. Emits `select(id)`.
Steps:
1. Session Config (unified form)
2. Stage 1 — Enhance Summary
3. Stage 2 — Re-Extract Quotes
4. Plan & Check
5. Session Doc Editor (3-column scene workspace)
6. Assemble

Status badge per step driven by file existence checks:
- Stage 1: `session-summary.md` exists
- Stage 2: `scene_extractions/` non-empty
- Plan: `narration_dir/plan.md` exists (reuse `_using_new_flow` from
  `server/routers/scene_editor.py:112-114`)
- Editor: derived from scene narration file count
- Assemble: hit existing `GET /api/editor/assembled-exists`

Steps with unmet prerequisites render disabled with a tooltip
("requires Stage 1 output"). Same dependency rules already enforced
by the backend (`scene_editor.py:332, 631`).

*3. Step 1 — unified config.* Merge `SessionConfig.vue` and the
`SessionDocEditor.vue` config form (lines 491-600) into one panel
`frontend/src/views/session/UnifiedConfigPanel.vue`. Group fields:
- **Workspace** — `campaignDir`, `sessionDir`
- **Inputs** — `vttInput`/`vtt`, `gm-assist (session)`
- **Outputs** — `sessionSummary`, `sceneExtractionsDir`, `narrationDir`
- **Party / characters** — `party`, `characters`, `voiceDir`,
  `examplesDir`
- **Context** — `vttContext` / context files (multi-path)
- **Run options** — `narrateTokens`, `proseMode`, `reflections`,
  `useEnhancedSections`

Reuse `PathField.vue` and `MultiPathField.vue`. Keep the existing
Pinia config store (`frontend/src/stores/config.ts`) as the single
source of truth — just stop writing the same value under two keys.
Drop the `sd_*` / `session_doc_*` legacy fallbacks once a one-time
migration step copies them to canonical keys
(`SessionDocEditor.vue:24-46, 64`). The "Open Editor" button goes
away; the stepper itself is the navigation.

*4. Steps 2/3/4 — stage runner panel.* New shared component
`frontend/src/components/session/StageRunPanel.vue`. Each instance
owns one stage. Props: `stageId`, `endpoint`, `supportsBatch`,
`outputArtifacts: { label, path, kind: 'file' | 'dir' }[]`. Layout:
- Header row — Run button, Batch toggle (when `supportsBatch`),
  status text.
- Center top — `<StreamOutput>` for live SSE / batch poll lines
  (reuse `frontend/src/components/shared/StreamOutput.vue` exactly
  as-is; already used by `NarrationOutput`, `RunPanel`,
  `ExtractSynthesizePanel`).
- Center bottom — once `event: done` returncode 0 arrives, swap to a
  "ready" view that previews artifacts:
  - Stage 1 → render `session-summary.md` content (a small new
    endpoint `GET /api/editor/file?path=...` scoped to allowed
    config dirs, or extend the `/extraction/{n}` pattern).
  - Stage 2 → list files under `scene_extractions/` with line counts.
  - Plan & Check → render `consistency_report.md`, `plan.md`,
    `enhanced_sections.md` as collapsible sections.
- Per-stage history — keep last run's stdout in a ref keyed by
  `stageId` so switching stages doesn't wipe it. Today the single
  `narrationOutput` ref (`SessionDocEditor.vue:143`) is shared across
  stages — split it.

Backend stays largely unchanged. The existing endpoints already
match this model: `GET /api/editor/enhance?batch=0|1`
(`scene_editor.py:565-575`), `GET /api/editor/extract?batch=0|1`,
`GET /api/editor/plan` (`scene_editor.py:659-669`). Add one new
endpoint to fetch artifact contents safely:
`GET /api/editor/artifact?key={session_summary|consistency_report|plan|enhanced_sections}`
— returns file text, mapping the key to a CONFIG-derived path so the
URL never carries a raw filesystem path. Mirror
`api_get_enhanced_sections` (`scene_editor.py:539`).

*5. Step 5 — Session Doc Editor.* Extract the existing 3-column
workspace from `SessionDocEditor.vue:602-775` into its own
`frontend/src/views/session/SceneWorkspace.vue`. It already contains
everything needed: `SceneList` (left), `ExtractionEditor` /
`QuoteAssignmentPanel` (center), `NarrationOutput` / `VttPanel` /
`QuoteLedger` (right). The header's Stage 1/2/Plan/Assemble buttons
get **removed** from this component — they belong to their own
steps. Keep the in-workspace Quotes/Editor mode toggle and the
per-scene Narrate button (`SessionDocEditor.vue:299-322`).

*6. Step 6 — Assemble.* Small panel: button calls
`POST /api/editor/assemble` (already exists at
`scene_editor.py:700`), shows result, exposes "Open in Typora" if
`/assembled-exists` returns true. Reuse logic from
`SessionDocEditor.vue:414-451`.

*7. State + step transitions.* A single `useSessionWorkflowStore`
Pinia store holds `activeStepId` and per-stage `lastRunOutput`
strings. Surviving across step switches matters because batch runs
may take minutes. Disable left-pane navigation while any subprocess
is streaming (any step's `running === true`); today the buttons gate
each other via `enhancing || extracting || narrating || planning`
(`SessionDocEditor.vue:642, 652, 662`) — lift that pattern into the
store. Step status badges refresh on `event: done` and on store
hydration.

**Reused, not reinvented**
- `StreamOutput.vue` — already auto-scrolls and renders `<pre>`,
  used by 4 places.
- `connectSSE` helper — already used at `SessionDocEditor.vue:191,
  214, 307, 334, 358, 388`.
- `PathField`, `MultiPathField`.
- `useConfigStore` — keep, just unify the keys.
- All `/api/editor/*` SSE endpoints — no protocol change needed.
- `_using_new_flow`, `_session_summary_path`,
  `_scene_extractions_dir`, `_narration_dir` helpers in
  `scene_editor.py:112-180` — drive both the new `/artifact`
  endpoint and frontend status badges.

**Where it lives**
- `frontend/src/views/SessionWorkflow.vue` — rewrite as new shell
- `frontend/src/views/session/SessionDocEditor.vue` — split into
  `UnifiedConfigPanel.vue`, `StageRunPanel.vue` (×3 instances),
  `SceneWorkspace.vue`, `AssemblePanel.vue`; this file shrinks to a
  thin wrapper or is removed
- `frontend/src/views/session/SessionConfig.vue` — merge into
  `UnifiedConfigPanel.vue`, then delete
- `frontend/src/components/wizard/WizardShell.vue` — delete after
  replacement
- `frontend/src/components/wizard/VerticalStepNav.vue` — new
- `frontend/src/components/session/StageRunPanel.vue` — new
- `frontend/src/views/session/UnifiedConfigPanel.vue` — new
- `frontend/src/views/session/SceneWorkspace.vue` — new (extracted)
- `frontend/src/views/session/AssemblePanel.vue` — new
- `frontend/src/stores/config.ts` — drop `sd_*` legacy fallbacks; add
  migration on load
- `frontend/src/stores/sessionWorkflow.ts` — new (active step +
  per-stage output)
- `frontend/src/router/index.ts` — collapse `/workflow/config` +
  `?stage=` into `/workflow/editor`
- `server/routers/scene_editor.py` — add
  `GET /api/editor/artifact?key=…` for previewing post-run files

**Verification**
1. `cd frontend && npm run typecheck && npm run build` passes.
2. `python -m pytest tests/` still green (no logic change to
   subprocess runner or stage endpoints, only the new `/artifact`
   GET).
3. `./startup` and walk the steps in a real campaign workspace:
   - Step 1: page hydrates from existing `config.values`; edit
     `session`, save persists via `PUT /config`.
   - Step 2 (Stage 1): Run streams; toggle Batch, Run again, watch
     poll lines. After completion the artifact pane shows
     `session-summary.md`. Step badge flips to "ready". Switching
     to Step 3 and back preserves the streamed output.
   - Step 3 (Stage 2): same flow; artifact list shows
     `scene_extractions/NN_*.md`.
   - Step 4 (Plan & Check): runs; artifact panel shows three
     collapsible files.
   - Step 5 (Editor): pick a scene, edit extraction, click Narrate
     per scene — existing flow unchanged.
   - Step 6 (Assemble): button produces final doc, "Open in
     Typora" appears.
4. A stage cannot start while another is running (button disabled +
   nav badge shows "running").
5. Mid-run reload: page rehydrates active step from store; running
   flag clears (we do not persist subprocess handles).
6. Old `/workflow/config` URL redirects to `/workflow/editor`.

### [ ] Web UI must accommodate two-phase extract→review→synthesize flow

**Context**
The `unified-pipeline` branch factors the shared extract→synthesize pipeline
into `campaignlib`. The next PR will expose an explicit review checkpoint
(e.g. `--extract-only`) between the two LLM passes. Today's UI for the four
affected scripts (`distill`, `campaign_state`, `party`, `planning`) is
single-click: one form, one button, one streamed run that produces the final
doc. That model no longer fits once the checkpoint exists.

**What needs to change**
Each affected page (`Campaign State`, `World State`/distill, `Party
Document`, `Planning Document`) needs a two-step interaction:

1. **Extract** — run the first pass, stream output, stop. Show the
   resulting extraction files in a browsable/editable list (one file per
   chunk). User reviews and optionally edits them in-place.
2. **Synthesize** — separate button. Runs the second pass against whatever
   is on disk in the extract dir. Produces the final doc.

Re-running extract should be resumable (already is at the CLI level —
existing files are skipped). Re-running synthesize without re-extracting
is the existing `--synthesize-only` path.

**Open questions**
- Where does the edit UI live? Options: inline textarea per extract,
  "open in Typora" buttons like the scene editor already uses, or just
  a read-only preview + a reminder to edit on disk.
- Should the "run both" single-click flow still exist as a convenience,
  or is forcing the checkpoint the point?
- Shared component vs four copies? Four scripts, same shape — a reusable
  `<ExtractSynthesizePanel>` probably pays for itself.

**Related files**
- `server/routers/grounding.py` — routes for all four scripts; will need
  an `extract_only` query param once the CLI flag lands
- `frontend/src/views/` — per-page Vue components for each of the four
  scripts
- `frontend/src/components/` — likely home for a shared
  extract→review→synthesize component

**Blocked on**
PR that adds the `--extract-only` checkpoint flag to the shared pipeline
(follow-up to the unified-pipeline refactor). UI work should happen after
that lands so the UI has a real flag to drive.

### [ ] Web UI config persistence is asymmetric — fix the load-but-never-save pages

**Context**
Most page components (Distill, Party, Planning, VttSummary, Query, Setup
pages, Experimental pages) read from `config.values` on mount but never write
back. Only `SessionConfig.vue`'s "Save Config" button, the sidebar model
dropdown, the Session Doc batch toggle, and the raw YAML editor actually
`apiPut('/api/config/')`. Edits made on the read-only-write pages live in
local refs and vanish on browser close.

Compounding this, several pages have OR-fallback key precedence
(`v.distill_input || v.summaries`, `v.plan_summaries || v.summaries`, etc.),
so fixing the fallback key in SessionConfig doesn't repair a stale preferred
key that some other page is loading from.

This is what made the "I changed the config but it still ran with the old
path" incident hard to diagnose. Pilot error in that specific case, but the
shape of the bug is structural.

**What needs to change**
Pick one of the four candidate fixes documented in
`docs/web_ui_config_persistence.md`:
1. Auto-save on field blur for every page
2. Drop the OR-fallbacks (one config key per field, no implicit defaults)
3. Have `derive_campaign_paths` predict-and-overwrite all per-page keys, plus
   `apiPut` after derive
4. Visible "unsaved changes" indicator (cheapest, signal-only)

**Related files**
- `docs/web_ui_config_persistence.md` — design doc with full failure flow
  and a Mermaid diagram
- `frontend/src/stores/config.ts` — central store; only `.save()` writes disk
- `frontend/src/views/session/SessionConfig.vue` — the only "normal" page
  with a working Save button
- `server/config.py:_SAVE_KEY_PREFIXES` — backend prefix filter that decides
  which keys land in `ui_config.yaml`

---

## CLI / pipeline machinery

### [ ] Generalize `--since` (per-chunk re-extract) to all extract→synthesize pipelines

**Context**
`planning.py --build-dossiers` accepts `--since N`, which restricts
Phase 2 aggregation and Phase 3 synthesis to extracts numbered ≥ N
(`planning.py:228-234, 526-530`). The intended use is "I just added
session 11; only roll the new extract into the existing dossiers
instead of re-processing all 10 historical chunks." Phase 1 is already
cache-skipping, so adding `--since` makes Phase 2/3 incremental too.

The same shape would help every other extract→synthesize pipeline —
`distill.py`, `party.py`, `campaign_state.py` — for the same reason:
when a single new session lands, the user wants to fold its content
into the existing canonical doc without re-synthesizing from all
historical extracts.

**What to do**
Lift `--since` into the shared extract→synthesize machinery in
`campaignlib.py` so all four pipelines accept it uniformly. Wire it
through:

- `distill.py` — Phase 2 (synthesis of `world_state.md`) skips extracts
  numbered < N
- `party.py` — Phase 2 (synthesis of `party.md`) skips extracts
  numbered < N
- `campaign_state.py` — Phase 2 (synthesis of `campaign_state.md`)
  skips extracts numbered < N
- `planning.py` — already implemented for `--build-dossiers`; lift the
  validator so `--since` works for the synthesis path too if it makes
  sense

Open question: for synthesis pipelines whose output is a single
canonical doc (not per-NPC), `--since N` means "fold extracts ≥ N into
the existing doc on disk, don't re-synthesize from scratch." That
implies these pipelines need an "incremental synthesis" mode that
takes the existing output as input alongside the new extracts. That is
a bigger change than just plumbing the flag through — flag the design
question separately if so.

**Where it lives**
- `planning.py:228-300` — existing `--since` implementation to copy
- `campaignlib.py` — likely home for the shared extract→synthesize
  helper if/when the four pipelines get unified
- `distill.py`, `party.py`, `campaign_state.py` — argparse + main
  flow updates
- `server/routers/grounding.py` — expose `--since` as a query param
  on the matching `/run/*` endpoints
- `frontend/src/components/shared/ExtractSynthesizePanel.vue` — add
  an optional "Since extract #" field

**Why this matters**
Re-synthesizing from all historical extracts after every session is
expensive (tokens) and slow, and the new content is almost always
isolated to the latest extract. `--since` turns the synthesis step
from O(history) into O(new) — same payoff `--build-dossiers` already
delivers for planning.

### [ ] Per-step batch-mode toggle for distill / party / planning / campaign_state extractions

**Context**
`scene_extract.py` and `session_doc.py` already support Anthropic
Message Batches API (`--batch`) for the per-scene extraction +
narration passes — 50% off list price in exchange for
non-streaming, poll-based progress. The shared infrastructure is in
`campaignlib.py:803-902` (`build_batch_request`, `submit_batch`,
`poll_batch`, sidecar files for resumability). The four
extract→synthesize grounding pipelines (`distill.py`, `party.py`,
`planning.py`, `campaign_state.py`) do **not** use batch mode today —
their Phase 1 extraction runs synchronously, one chunk at a time, at
full price.

A typical full re-extract (e.g. distill 10 sessions into world_state)
fans out into 10 independent chunk extractions with no inter-chunk
dependency — exactly the shape Message Batches is built for. Same
for `planning.py --build-dossiers` Phase 1 (per-chunk NPC mention
extraction), `party.py` Phase 1, `campaign_state.py` Phase 1.
Synthesis (Phase 2/3) is one inherently-sequential call per pipeline,
so batch doesn't apply there — only extraction.

**What to do**
Add a per-step batch toggle so the user can independently choose
live-streaming or batched extraction for each pipeline:

- `distill.py --batch-extract` → Phase 1 extraction goes through
  Message Batches; synthesis still streams.
- `party.py --batch-extract` → same.
- `planning.py --batch-extract` → applies to Phase 1 of both the
  synthesis path and the `--build-dossiers` path.
- `campaign_state.py --batch-extract` → same shape.

UI surface: each grounding page (`CampaignState.vue`,
`DistillWorldState.vue`, `PartyDocument.vue`, `PlanningDocument.vue`)
gets a single checkbox in the run panel — *"Use batch mode for
extraction (50% off, no live progress)"*. Persist as
`{pipeline}_batch_extract` in `ui_config.yaml` (matches the existing
`sd_batch` precedent at
`SessionDocEditor.vue:68, 71-78`).

UI also needs to show batch progress instead of streaming output
while a batch is in flight — `RunPanel.vue` would need a small
adapter (or a parallel `BatchRunPanel.vue`) that polls
`batch.request_counts` and displays the `processing/succeeded/errored`
counts, the way `scene_extract.py` already does on the CLI.

**Where it lives**
- `campaignlib.py:803-902` — existing batch infra to reuse:
  `build_batch_request`, `submit_batch`, `poll_batch`,
  `_sidecar_path`, etc.
- `scene_extract.py:_submit_pending` — the existing template for
  "fan a list of independent extractions out as one batch"
- `distill.py`, `party.py`, `planning.py`, `campaign_state.py` —
  factor Phase 1 to optionally route through the batch helpers
- `server/routers/grounding.py` — accept `batch_extract: bool` query
  param; if true, the runner needs to surface batch poll output as
  SSE lines
- `frontend/src/components/shared/ExtractSynthesizePanel.vue` —
  natural home for the checkbox (or each page's RunPanel)
- `frontend/src/views/session/SessionDocEditor.vue:68, 71-78` —
  reference implementation for the persistent toggle

**Why this matters**
A 10-session distill at ~60k chars/chunk costs roughly
10 × (~15k input + ~3k output tokens) at full price. Batch halves
the cost. The user gives up live streaming progress in exchange,
which is a fair trade for re-runs the user fires off and walks away
from. Making it per-step means the user can keep streaming on the
fast Phase 1 calls when they're iterating, then flip to batch for the
big "rebuild from all of history" runs.

