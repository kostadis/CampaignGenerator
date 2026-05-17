# CLI tools reference

Per-script invocations and flags. All scripts auto-detect `config.yaml` from CWD, falling back to `<script-dir>/config/config.yaml`.

## prep.py

Single-beat or session-arc encounter generation.

### Common invocations

```bash
# Single beat, interactive input
python prep.py

# Single beat, inline
python prep.py --beat "The party enters Icespire Hold"

# Pipeline mode (Lore Oracle → Encounter Architect → Voice Keeper)
python prep.py --mode pipeline --beat "The party enters Icespire Hold"

# Session arc: full numbered outline, interactive entry
python prep.py --session

# Session arc: inline outline
python prep.py --session "1. Travel to Hold 2. Confront Carver 3. Cryovain reveal"

# Copy assembled prompt to clipboard instead of calling API
python prep.py --clipboard --beat "..."

# Skip saving a log file
python prep.py --no-log --beat "..."
```

### All flags

| Flag | Default | Description |
|---|---|---|
| `--beat` / `-b` | interactive | Single session beat |
| `--session` / `-s` | interactive | Numbered session outline |
| `--mode` / `-m` | `single` | `single` or `pipeline` |
| `--clipboard` / `-c` | off | Copy output instead of (or after) API call |
| `--config` | CWD `config.yaml` or `config/config.yaml` | Path to config YAML |
| `--model` | `claude-sonnet-4-20250514` | Claude model to use |
| `--no-log` | off | Skip saving log file |

### Pipeline mode

Three sequential API calls per beat:

1. **Lore Oracle** — verifies the beat against canon; returns CLEAR / FLAGS / GAPS
2. **Encounter Architect** — receives the beat + Oracle report; produces the full structured encounter document
3. **Voice Keeper** — receives the encounter document; tunes NPC dialogue and PC behavioral notes to match established voice

If the Lore Oracle response contains the word `FLAGS`, the user is prompted before continuing to Stage 2.

## campaign_state.py

Generates `campaign_state.md` — a grounding document that tells all planning scripts what has been completed and what is currently true. Prevents hallucination of completed content as still active.

```bash
python campaign_state.py summaries.md --output docs/campaign_state.md

# With a tracking list to ensure specific events are never missed
python campaign_state.py summaries.md \
    --track-file docs/tracking.txt \
    --output docs/campaign_state.md

# Re-synthesize without re-extracting (delete state_extractions/ to re-extract)
python campaign_state.py --synthesize-only \
    --extract-dir docs/state_extractions \
    --output docs/campaign_state.md
```

The output contains: Completed Encounters & Quests, Resolved Plot Threads, NPC Current States table, Active Quests & Open Threads, Party Current Situation, and (if a tracking list was provided) a Tracked Items Status section where missing items are flagged as `NOT FOUND IN SUMMARIES`.

`campaign_state.md` is loaded first in `config.yaml` so it is the first context `prep.py` sees.

## make_tracking.py

Extracts a tracking list from an adventure module markdown. Items are phrased neutrally (subject + event type, no outcome) so `campaign_state.py` can determine whether each one has happened yet.

```bash
python make_tracking.py "Dragon of Icespire Peak.md" --output docs/tracking.txt
```

Then pass the result to `campaign_state.py --track-file`. Review and edit the list before use — the model may include events that have not yet occurred in your campaign.

## query.py

Ad-hoc search tool. Scans session summaries for a specific event, NPC, or topic and synthesizes a direct answer. Useful when `campaign_state.md` is missing something and you want to verify whether it happened.

```bash
python query.py summaries.md "Did the party clear Gnomengarde?"
python query.py summaries.md "What happened with Grundar at Icespire Hold?"
python query.py summaries.md "Xalvosh" --hits-only   # raw matching extracts only
python query.py summaries.md "Kraken Society arc score" -o notes/kraken.md
```

Uses a smaller default chunk size (40k) for more precise hits. The filter pass runs silently; only the synthesis streams to the terminal.

## planning.py

Generates `planning.md` from NPC dossiers, threat arc score documents, and session summaries. Two modes:

```bash
# Standard: dossiers + arc scores + summaries → planning.md
python planning.py \
    --npc grundar.md xalvosh.md \
    --arc-scores brundar_echo.md kraken_echoes.md \
    --summaries summaries.md \
    --output docs/planning.md

# Build individual per-NPC dossier files from summaries (run once, then edit)
python planning.py \
    --summaries summaries.md \
    --build-dossiers \
    --dossier-dir docs/npcs/

# Re-synthesize without re-extracting
python planning.py \
    --npc grundar.md xalvosh.md \
    --synthesize-only \
    --extract-dir docs/planning_extractions \
    --output docs/planning.md
```

`--build-dossiers` extracts per-NPC information from summaries into individual files (`docs/npcs/grundar_quartzvein.md`, etc.) for review and editing before the synthesize pass.

For dossier merge rules and cross-pipeline alias propagation, see `docs/dossier_aliases.md`.

## party.py

Generates `party.md` from character sheets, session summaries, backstories, and arc score mechanics.

**Preferred: `--party-config` YAML.** Maps each PC explicitly to their sheet, backstory, and arc score mechanic so the synthesizer can't misattribute which file belongs to which character. `arc_score: null` is a first-class "intentionally trackless" signal — the synthesizer will not invent a track for that PC or suggest creating one.

```bash
python party.py \
    --party-config config/party.yaml \
    --summaries summaries.md \
    --context docs/campaign_state.md \
    --output docs/party.md
```

See `config/party.example.yaml` for the full schema. Every referenced file is validated at load time; missing paths fail loud.

**Legacy flat flags** still work unchanged (mutex with `--party-config`):

```bash
python party.py \
    --character soma.md vukradin.md valphine.md \
    --summaries summaries.md \
    --arc-scores soma_arc.md vukradin_arc.md \
    --backstory soma_backstory.md valphine_backstory.md \
    --context docs/campaign_state.md \
    --output docs/party.md

# Re-synthesize without re-extracting
python party.py \
    --character soma.md \
    --synthesize-only \
    --extract-dir docs/party_extractions \
    --output docs/party.md
```

**Output shape — candidates, not decisions.** Each non-trackless PC gets a "Candidate Arc Score Events" bullet list: session events with the verbatim trigger text quoted from the mechanic file and a proposed direction (+/-). The GM decides which candidates actually fire. The synthesizer never commits to a current value, running total, or threshold claim — adjudicating score changes is a precision decision, not a rendering one. Trackless PCs have no candidate section at all.

**Output file — draft, not in-place rewrite.** `party.md` is hand-edited downstream (session summaries and the GM add content the LLM never sees), so if `--output` already exists `party.py` writes a sibling `<stem>.candidate<ext>` (e.g. `docs/party.candidate.md`) and prints a `diff -u` command for manual merge. The live `party.md` is never clobbered. Pass `--overwrite` only when bootstrapping a fresh party.md.

## dnd_sheet.py

Converts a D&D Beyond character sheet PDF to structured markdown using Claude's vision API.

```bash
python dnd_sheet.py Soma.pdf --output soma.md
python dnd_sheet.py *.pdf --output-dir ~/campaigns/characters/
```

## npc_table.py

Generates a markdown NPC reference table (Name / Faction / Current State / Motivations) from one or more campaign documents.

```bash
python npc_table.py                              # uses world_state
python npc_table.py --docs world_state planning  # combine multiple docs
python npc_table.py --output npc_state.md
```

## distill.py

Converts a large session-summary file into a structured `world_state.md` via a two-pass extract → synthesize pipeline. Intermediate extractions are saved so the synthesis can be re-run without re-extracting.

```bash
python distill.py summaries.md --output docs/world_state.md
python distill.py --synthesize-only --extract-dir docs/distill_extractions --output docs/world_state.md
```

## transform.py

Converts a NotebookLLM planning document into `prep.py` input format.

```bash
python transform.py dossier.txt
python transform.py dossier.txt --single          # extract as a single beat
python transform.py dossier.txt -o beats/out.txt  # save for later
```

## Post-session pipeline (Stage 1 → 4)

The recommended way to turn a finished session into a narrative document
runs four scripts back-to-back with a human-review checkpoint after each.
For the full reference (flags, batch mode, voice files, examples,
dialogue handling), see [`docs/session_doc_pipeline.md`](session_doc_pipeline.md).

```
gm-assist.md                                       (human-authored recap)
    │
    ▼  Stage 1 — enhance_summary.py                (single cached call · --batch ✓)
session-summary.md                                 ◄── HUMAN REVIEW
    │
    ▼  Stage 2 — scene_extract.py                  (per-scene · cached VTT · --batch ✓)
scene_extractions/NN_<slug>.md                     ◄── HUMAN REVIEW
    │
    ▼  Stage 3 — session_doc.py --per-scene-output (5-pass narration; per-scene files)
narration/session_doc_scene_NN_<slug>.md           ◄── HUMAN REVIEW
    │
    ▼  Stage 4 — assemble.py
session_doc.md
```

### enhance_summary.py

Stage 1: enrich a `gm-assist.md` recap with VTT detail. Single cached
call. Output preserves the recap's section structure (Summary, Memorable
Moments, Scenes, NPCs, Locations, Items, Spells) and fills in details +
verbatim moments the recap missed.

```bash
python enhance_summary.py session.vtt \
    --gmassist  gm-assist.md \
    --output    session-summary.md

# Batch mode (Anthropic Message Batches API; 50% off list price)
python enhance_summary.py ... --batch                # block + poll
python enhance_summary.py ... --batch --submit-only  # detach; sidecar in <output>.batch.json
python enhance_summary.py ... --batch --collect      # retrieve from sidecar
```

Default model: `claude-sonnet-4-6`. `--fast` switches to Haiku.

### scene_extract.py

Stage 2: per-scene verbatim quote extraction. The full VTT is cached as a
system prefix; the script issues one call per scene named in the
session-summary's `## Scenes` section. Output is one
`scene_extractions/NN_<slug>.md` per scene. Resume semantics: existing
files are skipped.

```bash
python scene_extract.py session.vtt \
    --summary    session-summary.md \
    --output-dir scene_extractions/ \
    [--dossier-dir docs/npcs/]      # rewrites NPC aliases to canonical names

# Batch mode — N scenes submitted as one batch; cache hits compound
python scene_extract.py ... --batch                # block + poll
python scene_extract.py ... --batch --submit-only  # detach; sidecar in <output-dir>/.batch.json
python scene_extract.py ... --batch --collect      # retrieve from sidecar
```

Default model: `claude-sonnet-4-6`.

### session_doc.py

Stage 3: per-scene first-person narration (5-pass internal pipeline). For
the four-stage flow, run it with `--per-scene-output` to write one
narration file per scene. For full pass-by-pass details, all flags, voice
files, and the older single-shot mode, see
[`docs/session_doc_pipeline.md`](session_doc_pipeline.md).

```bash
# Stage 3 of the 4-stage flow — writes one file per scene
python session_doc.py session-summary.md \
    --scene-extractions scene_extractions/ \
    --voice-dir         voice/ \
    --characters        "Vukradin, Valphine, Soma, Brewbarry" \
    --per-scene-output  narration/

# Re-narrate a single scene after editing its quote file
python session_doc.py ... --scene 3
```

Default model: `claude-sonnet-4-6`. `--fast` switches to Haiku.

### assemble.py

Stage 4: concatenate the per-scene narration files into a single session
document.

```bash
python assemble.py narration/ \
    --output session_doc.md \
    --title  "Chapter 37 — A Gem of a Problem"
```

### vtt_summary.py

Convert a Zoom `.vtt` transcript into a structured session summary using
the same two-pass extract → synthesize pipeline as `distill.py`. Use
this to seed `summaries.md` from a recording before running grounding
docs. The Stage 1 / Stage 2 flow above is preferred when you have a
`gm-assist.md` recap.

```bash
python vtt_summary.py session.vtt --output summaries/session_12.md

# With a pre-existing recap as anchor (recommended when available)
python vtt_summary.py session.vtt \
    --output           session-summary.md \
    --reference-summaries gm-assist.md \
    --context docs/campaign_state.md docs/world_state.md docs/party.md
```

### quote_ledger.py

SQLite-backed VTT-quote ↔ scene matching. Used by the Web UI's Scene
Editor to surface quotes that didn't make it into a `scene_extractions/`
file. Not typically run from the CLI; see
[`docs/web_ui.md`](web_ui.md) for the editor workflow.

## new_workspace.py

Creates a new campaign workspace.

```bash
python new_workspace.py ~/campaigns/icespire --name "Icespire Peak"
```

Generates a `config.yaml` with absolute paths so it works from any directory. Pass `--world-state`, `--mechanics`, `--planning`, `--party`, or `--campaign-state` to point at existing files instead of creating placeholders.

## Logs

Logs are saved to `log_dir` (from config) as timestamped markdown files. Single-beat logs include the system prompt, user prompt, and response. Session logs include all beats and all pipeline stages in one combined file (stem: `session_arc`).

## Typical workflow for a new campaign

```bash
# 1. Create workspace
python new_workspace.py ~/campaigns/icespire --name "Icespire Peak"
cd ~/campaigns/icespire

# 2. Convert character sheets
python ~/CampaignGenerator/dnd_sheet.py *.pdf --output-dir docs/characters/

# 3. Extract tracking list from adventure module
python ~/CampaignGenerator/make_tracking.py "adventure.md" --output docs/tracking.txt
# (review and edit tracking.txt)

# 4. Generate grounding documents from session summaries
python ~/CampaignGenerator/campaign_state.py summaries.md \
    --track-file docs/tracking.txt --output docs/campaign_state.md
python ~/CampaignGenerator/distill.py summaries.md --output docs/world_state.md
python ~/CampaignGenerator/party.py \
    --character docs/characters/soma.md \
    --summaries summaries.md --output docs/party.md

# 5. Build NPC dossiers, then synthesize planning doc
python ~/CampaignGenerator/planning.py \
    --summaries summaries.md --build-dossiers --dossier-dir docs/npcs/
# (review docs/npcs/*.md)
python ~/CampaignGenerator/planning.py \
    --npc docs/npcs/*.md --arc-scores arc_scores/*.md \
    --output docs/planning.md

# 6. Run session prep
python ~/CampaignGenerator/prep.py --beat "The party arrives at Icespire Hold"
```
