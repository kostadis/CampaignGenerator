# Session Doc UI — Operator Flow

The flow that runs from the **Session Doc Editor** page in the web UI.

---

## TL;DR — what to click in order

1. Sidebar → `① Session Config` → set Campaign Dir + Session Dir → all paths auto-derive.
2. Sidebar → `② Session Doc Editor`. The editor opens; if it's a cold start the **Config drawer** slides out automatically.
3. (Drawer) Set at minimum the **GMassistant recap file** and the **Scene extractions dir** — the editor enables as soon as both are filled.
4. Header → **`STAGE 1 — Enhance Summary`** → wait for `session-summary.md`.
5. **Open `session-summary.md` in Typora and review/edit it** — this is the human checkpoint.
6. Header → **`STAGE 2 — Re-Extract Quotes`** → produces `scene_extractions_new/NN_<slug>.md`.
7. Header → **`STAGE 3 — Plan & Check`** → produces `narration/plan.md` + `consistency_report.md`. **Review the consistency report.**
8. For each scene: select it on the left, edit the extraction, click **`Narrate`**, optionally **`Scrub`**, mark **Reviewed** when the order looks right. The four lifecycle dots on the scene card fill in (E · R · N · S).
9. Header → **`Assemble →`** → opens the **Review** screen.
10. On the Review screen: confirm every scene is narrated (any scene that isn't blocks Assemble). Click **`Assemble Doc`** → optionally **`Open in Typora`**.

That's the full loop.

---

## Page shape

```
┌─ Header ───────────────────────────────────────────────────────────────────┐
│ Session Doc  [Profile ▾]  ① ● 2h  ② ● 1h  ③ ● 5m  ④ ● 5/8         [Cfg ⚙] │
│             [Batch] [Backend] [① Enhance] [② Re-Extract] [③ Plan & Check]  │
│             [Scrub All] [Assemble →]                                       │
├─ Three-column body ────────────────────────────────────────────────────────┤
│ Scene list      │ Extraction editor + narration output      │ VTT panel    │
│ • dot dot dot   │ ……                                         │ ……           │
│ • dot dot dot   │                                             │              │
└─────────────────┴─────────────────────────────────────────────┴──────────────┘
                                                          [Config ⚙ drawer →]
```

- **Profile picker** — names a preset of Stage-④ knobs. Switching profiles rewrites the drawer's Stage-④ section. A `*` next to the active profile name means the local knobs diverge from the saved values; the inline `Save` / `Revert` buttons appear.
- **Pipeline strip** — read-only stage status (`ok` / `warn` / `cold`) with a human-friendly "ago" string. Refreshes after every stage run.
- **Stage buttons** — the same stage actions as before, but now disabled until the editor is `configReady`.
- **Config ⚙** — toggles the right-edge drawer (see below). State persists in `localStorage`.

If the editor isn't `configReady` (no session or no scene-extractions dir set yet), the three-column body is replaced by an empty-state card pointing the user back at the drawer.

---

## The Config drawer

Right-edge slide-out (~360px). Replaces the old pre-flight config form. Every field auto-applies on change via a 350 ms debounced `PUT /api/editor/config`.

Sections, top to bottom:

| Section | Fields |
|---|---|
| **Paths** | GMassistant recap · Session summary · Scene extractions dir · Narration dir · Output dir · Party doc · Voice files dir · Examples dir · Characters · Context files |
| **① Enhance** | Batch (Anthropic Message Batches API) · Backend (anthropic / dgx) |
| **② Extract** | (no separate knobs — uses Batch + Backend; the Re-Extract button always forwards `--force`) |
| **③ Plan & Check** | Reuse enhanced sections for downstream Narrate |
| **④ Narrate** | Token limit · Prose mode · Reflections · Narration genre |
| **⑤ Assemble** | (placeholder for a polish toggle once `polish.py` is wired) |

Backend uses the existing `_TYPED_TO_CONFIG_KEY` mapping in `scene_editor.py`: typed `ui.session_doc.*` ↔ legacy `CONFIG[*]`. The path fields formerly under "Show overrides" (`extract_dir`, `roleplay_extract_dir`, `summary_extract_dir`) are gone from the UI — they're populated server-side by `derive_campaign_paths` and not part of the editor's PUT payload.

The drawer opens automatically on cold start (when neither `session` nor `scene_extractions_dir` is set). A "Ready" pill at the top turns green once required fields are filled.

---

## Profiles

A profile is a named set of Stage-④ knobs:

```json
{
  "name": "Memoir mode",
  "knobs": {
    "narrate_tokens": 16000,
    "prose_mode": true,
    "reflections": true,
    "narration_genre": "First-person comic-noir fantasy memoir",
    "backend": "anthropic"
  }
}
```

Stored in `ui_state.yaml` under `ui.profiles`. Two operations:

- **Pick a profile** — rewrites the drawer's Stage-④ knobs. The editor's normal auto-apply watcher carries them through to the server.
- **Save current as new** — appended via the same dropdown; the new profile becomes active.

If you tweak a knob after picking a profile, the dropdown gains a `*` and a `Save` / `Revert` pair appears next to it. `Save` overwrites the profile's knobs with the current values; `Revert` re-applies the stored ones.

Paths are deliberately **not** in profiles — they're per-session and don't belong in a preset that travels across sessions.

---

## The stages

### Stage 1 — Enhance Summary

- **Input**: raw `.vtt` + `gm-assist.md`.
- **Output**: `session-summary.md` in the session directory.
- **Script**: `enhance_summary.py` (single LLM call, VTT cached as system prefix).

Stop after this. Open `session-summary.md` and read it. Edit by hand if anything is wrong. This is the only structural human checkpoint; everything downstream inherits from this file.

### Stage 2 — Re-Extract Quotes

- **Input**: reviewed `session-summary.md` + the raw VTT.
- **Output**: per-scene quote files `NN_<slug>.md` in `scene_extractions_new/`.
- **Script**: `scene_extract.py`.

After this runs, the scene list on the editor's left column populates and each row gets its **E** lifecycle dot.

### Stage 3 — Plan & Check

- **Input**: `session-summary.md` + per-scene Stage-2 files.
- **Output** in `narration/`:
  - `consistency_report.md` — Pass 1 flags contradictions / ambiguities.
  - `plan.md` — Pass 3 narrator assignments per scene.
- **Scripts**: `sd_consistency.py` (if `--context` configured) followed by `sd_plan.py`. The editor chains them into one streaming response.

Review `consistency_report.md` before narrating — it flags anything the model thinks is contradictory in the recap.

### Per-scene work

For each scene:

1. Click the scene in the left column. The center pane loads the Stage-2 file.
2. Edit the extraction freely. Save.
3. Click **Narrate** → produces `narration/session_doc_scene_NN_<slug>.md`. The **N** dot fills in.
4. (Optional) **Scrub** → produces `*.scrubbed.md` sibling. The **S** dot fills in.
5. Mark **Reviewed** when the order looks right. The **R** dot fills in.

The four lifecycle dots are green when complete, grey when cold. (Amber-when-the-input-is-newer-than-the-output rendering is not yet wired into the per-scene dots; the header pipeline strip conveys it globally.)

### Stage 4½ — Scrub All

Header button. Runs `scrub_mechanics.py` against the whole `narration_dir`, producing a `*.scrubbed.md` sibling for every per-scene narration. Already-scrubbed files are skipped.

### Final — Review & Assemble

The **Assemble →** button in the header navigates to `/workflow/editor/review`. It does not call `/api/editor/assemble` directly any more — every Assemble goes through the Review gate.

See the next section.

---

## The Review screen

Route: `/workflow/editor/review`. Three blocks plus a footer.

### Pipeline readiness strip

The same four-stage strip the editor header shows, with verbose labels and timestamps. Green across is the "safe to assemble" signal.

### Activity timeline (left)

Tails `<session_dir>/.cg/activity.jsonl`. Every Enhance / Extract / Plan / Narrate / Scrub run appends one JSON line with timestamp, stage, scene (if applicable), returncode, the knobs in effect, and the output path(s). Newest first; failed rows highlight red.

The file survives server restarts — the timeline is a real audit log, not in-memory state.

### Per-scene roster (right)

For every scene the Review screen shows:

- The four lifecycle dots (`E R N S`).
- Token estimate (extraction-based).
- Applied-knobs chips — `prose`, `reflections`, `enh`, `anthropic` / `dgx`, `genre` — read from the per-narration `*.knobs.json` sidecar. If a scene was narrated with `prose_mode` on, it shows the `prose` chip; otherwise it doesn't.
- First ~120 characters of the narration text (frontmatter stripped).

A scene that hasn't been narrated yet gets a red border and a "Not narrated yet — Assemble is blocked" callout.

### Footer

A rollup line ("prose: 5/8 · reflections: 3/8 · enhanced: 8/8 · backends: anthropic=8 · genre: …") plus the **Assemble Doc** button. The button is disabled with a one-line reason ("blocked: scene 8 not narrated") if any scene is still cold.

On success the button is replaced by an **Open in Typora** affordance.

### Endpoints

| Endpoint | What it returns |
|---|---|
| `GET /api/editor/pipeline-status` | `{enhance, extract, plan, narrate}` stage status (ok / warn / cold) with ago + counts |
| `GET /api/editor/scene-roster` | `{scenes: [{index, narrator, scene, tokens, lifecycle, applied_knobs, preview}]}` |
| `GET /api/editor/activity?limit=N` | `{entries: [...]}` from `activity.jsonl`, newest entries last |
| `POST /api/editor/assemble` | Unchanged. Called from the Review footer, not from the editor header |

---

## File layout (per session directory)

```
summaries/YYYYMMDD/
├── <session>.vtt                       # Zoom transcript
├── <session>.cleaned.vtt               # /vtt-spell-pass output (optional)
├── gm-assist.md                        # GMassistant structured recap (Stage 1 input)
├── session-summary.md                  # Stage 1 output — REVIEW BEFORE STAGE 2
├── scene_extractions_new/              # Stage 2
│   ├── 01_<slug>.md                    # Stage 2 source — the file you edit
│   ├── 01_<slug>.md.reviewed           # sidecar marker (R dot)
│   ├── 02_<slug>.md
│   └── …
├── narration/                          # Stage 3 + Stage 4
│   ├── consistency_report.md           # Pass 1 output (read this!)
│   ├── plan.md                         # Pass 3 output (narrator assignments)
│   ├── session_doc_scene_01_<slug>.md           # Stage 4 narration
│   ├── session_doc_scene_01_<slug>.knobs.json   # which knobs were used (Review screen reads this)
│   ├── session_doc_scene_01_<slug>.scrubbed.md  # Stage 4½ scrub output
│   └── …
├── .cg/
│   └── activity.jsonl                  # append-only audit log (Review timeline)
└── session_doc.md                      # Final assembled doc
```

---

## Required environment

- `ANTHROPIC_API_KEY` must be exported in the shell that launches the server. The sidebar shows a yellow warning if it isn't set.
- Python deps installed in the active venv:
  ```bash
  uv pip install -r ~/src/CampaignGenerator/requirements.txt --python ~/.venv/bin/python3
  ```

---

## Common gotchas

**"I see the wrong `scene_extractions_*` directory."** Open the Config drawer (`Config ⚙` in the header) and change the **Scene extractions dir** field. The change auto-applies; no "Apply" button to click.

**"The Assemble button doesn't do anything."** Click `Assemble →` — it routes to the Review screen now. Assemble actually runs from there, and only when every scene is narrated.

**"My drawer keeps closing on reload."** Drawer state is in `localStorage` under `session-doc-editor.knob-drawer.open`. Clear it if you want to reset.

**"The activity timeline is empty."** Activity is recorded into `<session_dir>/.cg/activity.jsonl` the first time a stage runs *after* the upgrade. Older runs (pre-rebuild) don't appear.

**"`fastapi` not installed."** Install dependencies (see Required environment above).

---

## Backend pipeline scripts (reference)

- `enhance_summary.py` — Stage 1
- `scene_extract.py` — Stage 2
- `sd_consistency.py` + `sd_plan.py` — Stage 3 plan & check (chained when `--context` is configured)
- `sd_narrate.py --scene N` — per-scene narration (reads cached `plan.md`)
- `scrub_mechanics.py` — Stage 4½ scrub
- `assemble.py` — Final assembly

The web server (`server/main.py`) wires these to UI buttons via routers in `server/routers/`, primarily `scene_editor.py`. The `ledger.py` router that drove the old Quotes mode has been removed.

---

## CHANGELOG (relative to the pre-rebuild flow)

- **Removed**: Quotes mode, the `Editor` / `Quotes` toggle, `Scaffold from Quotes`, the `QuoteLedger` / `QuoteAssignmentPanel` / `QuotePicker` components, the `/api/ledger/*` routes, the `LEGACY` sidebar group, the `VttSummary` page, and the legacy `extract_dir` / `roleplay_extract_dir` / `summary_extract_dir` fields from the editor's PUT payload.
- **Added**: KnobDrawer, Profiles (typed `ui.profiles` section), header pipeline-status strip with stage dots, per-scene lifecycle dots (E · R · N · S), `<session_dir>/.cg/activity.jsonl` recording, per-narration `*.knobs.json` sidecars, and the Review-before-Assemble screen at `/workflow/editor/review`.
- **Phase 5 of SessionDocRefactor (this PR):** `session_doc.py` has been deleted. The three live LLM passes now live in `sd_consistency.py` / `sd_plan.py` / `sd_narrate.py`. The shared helpers are under the `session_doc/` package. Legacy CLI flags (`--from-extractions`, `--by-scene`, `--roleplay-extract-dir`, `--plan-only`, `--extract-only`) are all gone — invoking the right tool replaces the flag.
