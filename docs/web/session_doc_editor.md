# Session Doc UI — Operator Flow

The new flow that runs from the **Session Doc Editor** page in the web UI.

---

## TL;DR — what to click in order

1. Sidebar → `① Session Config` → set Campaign Dir + Session Dir → all paths auto-derive.
2. Sidebar → `② Session Doc Editor` → `Open Editor`.
3. Header `STAGE 1` → **`Enhance Summary`** → wait for `session-summary.md`.
4. **Open `session-summary.md` in Typora and review/edit it** — this is the human checkpoint.
5. Header `STAGE 2` → **`Re-Extract Quotes`** → produces `scene_extractions_new/NN_<slug>.md`.
6. Header `STAGE 3` → **`Plan & Check`** → produces `narration/plan.md` + `enhanced_sections.md` + `consistency_report.md`. **Review the consistency report.**
7. For each scene: select it on the left, in `Quotes` mode click **`Scaffold from Quotes`** to get a clean beat→quotes layout (`NN_<slug>.scaffold.md`).
8. Switch the top-left mode toggle to **`Editor`**, click **`Narrate`** for each scene.
9. Header `FINAL` → **`Assemble Doc`** → optionally run `polish.py`.

That's the full loop.

---

## Sidebar layout

```
SESSION WORKFLOW
  ① Session Config
  ② Session Doc Editor

GROUNDING DOCS
  Campaign State / World State / Party Document / Planning Document

PREP / SETUP / EXPERIMENTAL
  …

LEGACY
  VTT Summary
  Scene Extraction
```

The two `LEGACY` pages are not part of the new flow — they exist only for sessions started under the old four-step pipeline.

The wizard breadcrumb at the top of `/workflow/*` pages has 6 steps:

```
1 Session Config → 2 Editor Config → 3 Enhance Summary → 4 Extract Quotes → 5 Plan & Check → 6 Editor
```

Steps 2–6 all live on the same `/workflow/editor` page; the breadcrumb is a progress indicator using `?stage=` query params. Clicking a step changes the URL but doesn't change page contents (yet — see TODO).

---

## The stages

Header buttons on the Session Doc Editor page:

```
STAGE 1 [Enhance Summary] | STAGE 2 [Re-Extract Quotes] | STAGE 3 [Plan & Check] | FINAL [Assemble Doc] [Open in Typora] [Config]
```

### Stage 1 — Enhance Summary (global, one click)

- **Input**: raw `.vtt` transcript + `gm-assist.md` (the structured recap)
- **Output**: `session-summary.md` in the session directory
- **Script**: `enhance_summary.py` (single LLM call, VTT cached as system prefix)
- **Why**: enrich the gm-assist recap with detail and verbatim quotes from the VTT, preserving the recap's section structure as the contract. Produces a *human-reviewable* document.

**STOP after this. Open `session-summary.md` in Typora and read it. Edit it by hand if anything is wrong.** This is the only structural human checkpoint; everything downstream inherits from this file.

### Stage 2 — Re-Extract Quotes (global, one click)

- **Input**: reviewed `session-summary.md`
- **Output**: per-scene quote files `NN_<slug>.md` in `scene_extractions_new/`
- **Script**: `scene_extract.py`
- **Why**: split the reviewed summary into per-scene files with frontmatter `source: gmassist`, beats from the gm-assist `## Scenes` section, and `## Verbatim moments` blocks pulling quotes from the VTT.

After this runs, the scene list on the editor's left column populates.

### Stage 3 — Plan & Check (global, one click)

- **Input**: `session-summary.md` + per-scene Stage-2 files
- **Output**: in `narration/`:
  - `consistency_report.md` (Pass 1 — flags contradictions / ambiguities)
  - `enhanced_sections.md` (Pass 2 — corrected event list per scene)
  - `plan.md` (Pass 3 — narrator assignments per scene)
- **Script**: `session_doc.py --plan-only --no-plan-review`
- **Why**: the heavy upstream passes that the per-scene Narrate would otherwise run lazily on the first scene. Doing them once up front means: (a) consistency issues surface before you spend tokens on narration, (b) every per-scene Narrate is fast because it reuses the cached artifacts.

**Review `consistency_report.md` before narrating** — it'll flag anything the model thinks is contradictory in the recap.

### Per-scene work — Scaffold + Narrate

The scene editor has two modes (top-left toggle): **Quotes** (default) and **Editor**.

#### In Quotes mode

- Select a scene on the left.
- Center pane shows the Stage-2 file's content + per-scene quote count.
- Click **`Scaffold from Quotes`**: deterministic reformat of the Stage-2 file into beats followed by a "## Quotes to place" section. Output goes to `scene_extractions_new/NN_<slug>.scaffold.md` (sibling — **the Stage-2 file is never overwritten**, since it's the expensive LLM artifact).
- Hand-curate: drag/move quotes under the beat where they belong, delete OOC lines.

#### Switch to Editor mode

- The center pane now shows whichever file Narrate will actually consume — the `.scaffold.md` if it exists, else the raw Stage-2 file.
- Click **`Narrate`** for that scene.
- Output: `narration/session_doc_scene_NN_<slug>.md`.
- Repeat for every scene.

### Final — Assemble + Polish

- **`Assemble Doc`** stitches all `session_doc_scene_NN_*.md` into the final session document (uses `assemble.py`).
- **`Open in Typora`** appears once an assembled doc exists.
- Polish: run `polish.py` separately for the final cleanup pass.

---

## Why the human checkpoint between Stage 1 and Stage 2

LLMs are renderers, not architects. Stage 1 is rendering (enrich a recap); Stage 2 is structure (split scenes, attach quotes). If Stage 2 runs on an unreviewed Stage 1 output, errors compound silently into the per-scene files and then the narration.

`session-summary.md` is the cheap, human-verifiable artifact. Fixing scope mistakes here is a 5-minute edit; fixing them after Stage 2 means re-running both stages and burning tokens.

`consistency_report.md` (from Stage 3) is the second checkpoint — it surfaces contradictions before you commit to per-scene narration.

---

## File layout (per session directory)

```
summaries/YYYYMMDD/
├── <session>.vtt                       # Zoom transcript
├── gm-assist.md                        # GMassistant structured recap (Stage 1 input)
├── session-summary.md                  # Stage 1 output — REVIEW BEFORE STAGE 2
├── scene_extractions_new/              # Stage 2 + scaffolds
│   ├── 01_<slug>.md                    # Stage 2 source (rich, never overwritten)
│   ├── 01_<slug>.scaffold.md           # Scaffold-from-Quotes output (the file you edit)
│   ├── 02_<slug>.md
│   ├── 02_<slug>.scaffold.md
│   └── …
├── narration/                          # Stage 3 + per-scene narration
│   ├── consistency_report.md           # Pass 1 output (read this!)
│   ├── enhanced_sections.md            # Pass 2 output (cached for Narrate)
│   ├── plan.md                         # Pass 3 output (narrator assignments)
│   ├── session_doc_scene_01_<slug>.md  # per-scene Narrate output
│   └── …
└── session_doc.md                      # Final assembled doc
```

Legacy directories that may exist from old-flow sessions:
- `scene_extractions/` (old per-scene files; used as fallback only when the new dir is empty — configurable under "Show overrides")
- `vtt_extractions/`, `vtt_roleplay_extractions/` (reference panels in the editor's right column; not pipeline inputs in the new flow)

### File precedence rules

- **Editor / Narrate input for a scene**: prefers `NN_<slug>.scaffold.md`, falls back to `NN_<slug>.md`.
- **`Scaffold from Quotes`**: reads the Stage-2 file (`NN_<slug>.md`) directly when it exists. Falls back to the legacy ledger + recap otherwise.
- **`_using_new_flow()`** (backend): true when `narration/plan.md` exists OR any `scene_extractions_new/NN_*.md` has frontmatter `source: gmassist`.

---

## Editor configuration

Set once on the Session Doc Editor's config form (the pre-Apply screen). Required fields:

| Field | Default | What it is |
|---|---|---|
| GMassistant recap file | `gm-assist.md` | Stage 1 input |
| Session summary file | `session-summary.md` | Stage 1 output |
| Scene extractions directory (Stage 2) | `scene_extractions_new` | Stage 2 output dir |
| Narration directory (Stage 3) | `narration` | Stage 3 output dir |

Behind **"Show overrides"**: legacy extractions dir, roleplay reference dirs, party/voice/examples paths, campaign context files.

The form's `Open Editor` button POSTs all values to `/api/editor/config`, which seeds the running server's editor `CONFIG` dict. The backend's `_scene_extractions_dir()` and `_narration_dir()` helpers read from there, preferring the new keys and falling back to the legacy ones if unset.

---

## Required environment

- `ANTHROPIC_API_KEY` must be exported in the shell that launches the server. The sidebar shows a yellow warning if it isn't set.
- Python deps installed in the active venv:
  ```bash
  uv pip install -r ~/src/CampaignGenerator/requirements.txt --python ~/.venv/bin/python3
  ```

---

## Common gotchas

**"I see the old `scene_extractions/` content even though I have files in `scene_extractions_new/`."** The server's editor CONFIG was seeded at startup before the new keys existed. Click `Config` in the editor header, then `Open Editor` again — that pushes the new field values into CONFIG. Verify with:

```bash
curl -s http://localhost:5000/api/editor/config \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('scene_extractions_dir'))"
```

It should print the absolute path to `scene_extractions_new/`.

**"Clicking Prose mode / Reflections on the config form jumps me into the editor."** Was a bug — the checkboxes had `@change="applyConfig"`. Fixed; if it recurs, hard-reload to drop a cached bundle.

**"Scaffold from Quotes overwrote my Stage 2 file."** Shouldn't happen anymore — Scaffold writes to `NN_<slug>.scaffold.md` (sibling). If you see otherwise, the server is running old code; restart it.

**"The page is blank in Chrome but works in Edge."** Chrome cache. Clear site data via DevTools → Application → Storage, or use Incognito. The hashed JS filenames mean rebuilds don't otherwise invalidate the entry HTML.

**"`fastapi` not installed."** Install dependencies (see Required environment above).

---

## TODO

- [ ] Auto-advance the wizard breadcrumb (`?stage=...`) as the user moves through the pipeline. Today the breadcrumb is a manual progress indicator: clicking a step changes the query param, but running `Enhance Summary` / `Re-Extract Quotes` / `Plan & Check` / switching to Editor mode doesn't update it. `SessionDocEditor.vue` should `router.replace` the matching `?stage=` value when each Stage button is clicked and when `editorMode` flips to `editor`.

- [ ] **Rip out legacy flows once all in-progress sessions have migrated.** The codebase still carries dead-weight paths kept around for backward compatibility:
    - **Sidebar `LEGACY` group** — `VTT Summary`, `Scene Extraction` pages and their routes/components.
    - **Backend** in `server/routers/scene_editor.py`: `_build_narrate_cmd_old`, `_build_extract_cmd_old`, `_api_assemble_old`, the `_using_new_flow()` branches, fallback to `extract_dir` in `_scene_extractions_dir()` / `_narration_dir()`.
    - **Backend** in `server/routers/ledger.py`: the legacy ledger fallback branch in `_stream_generate_extraction` (everything below `# ── Legacy fallback`), plus `Sync Quotes`, `Auto-Assign`, `bulk-assign`, `make-exclusive` routes if no longer needed.
    - **Frontend** in `SessionDocEditor.vue`: the `extractDir` / `roleplayExtractDir` / `summaryExtractDir` / `roleplaySummary` fields under "Show overrides".
    - **Frontend** components: `QuoteLedger.vue`, `QuoteAssignmentPanel.vue`, `QuotePicker.vue`, `VttPanel.vue` if Quotes mode + right-side reference panels are no longer used.
    - **`session_doc.py`** old extract paths (`--from-extractions`, `--by-scene`, `--roleplay-extract-dir`) — keep `--plan-only` / `--scene-extractions` / `--per-scene-output` and drop the rest.
    - **Trigger condition**: only do this once every session in `summaries/*` has a `scene_extractions_new/` directory and no campaign still references the legacy dirs. Until then, keep the fallbacks so half-migrated sessions don't break.

---

## Backend pipeline scripts (reference)

- `enhance_summary.py` — Stage 1
- `scene_extract.py` — Stage 2
- `session_doc.py --plan-only` — Stage 3 (consistency + plan + enhanced sections)
- `session_doc.py --scene N` — per-scene narration (uses cached plan + enhanced sections)
- `assemble.py` — Final assembly
- `polish.py` — Final polish pass

The web server (`server/main.py`) wires these to UI buttons via routers in `server/routers/`, primarily `scene_editor.py` (extraction, plan, narrate) and `ledger.py` (Scaffold-from-Stage-2; legacy ledger sync/auto-assign).

For the older internal pass-by-pass design notes, see the "Design rationale" section of [`docs/cli/session_doc_pipeline.md`](../cli/session_doc_pipeline.md) (describes the 5-pass flow that `session_doc.py` still implements internally — what's new is exposing the planning passes as their own UI button instead of bundling them into the first per-scene Narrate).
