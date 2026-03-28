# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# CampaignGenerator

A D&D session-prep CLI that assembles campaign documents and session beats, then calls the Claude API to generate encounter design documents.

## Running the tool

```bash
python prep.py [options]
```

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

## Project structure

```
campaignlib.py              # Shared library — all scripts import from here
prep.py                     # CLI: session beat / session arc prep
session_doc.py              # CLI: post-session narrative document generator (5-pass pipeline)
narrative.py                # Supporting module for session_doc.py (narration passes, prompt assembly)
session_doc_ui.py           # Flask web UI for the session_doc iterative workflow
quote_ledger.py             # Quote Ledger: SQLite-backed VTT dialogue tracking and scene matching
app.py                      # Streamlit launcher / configurator (all campaign tools)
npc_table.py                # CLI: generate NPC reference table from lore docs
distill.py                  # CLI: convert session summaries into world_state.md
campaign_state.py           # CLI: generate completed-content grounding doc from summaries
make_tracking.py            # CLI: extract trackable events from an adventure module
query.py                    # CLI: search summaries for a specific event or topic
vtt_summary.py              # CLI: convert a Zoom .vtt transcript into a session summary
planning.py                 # CLI: generate planning.md from NPC dossiers + arc scores
party.py                    # CLI: generate party.md from character sheets + summaries
dnd_sheet.py                # CLI: convert D&D Beyond PDF to markdown via Claude vision
new_workspace.py            # CLI: create a new campaign workspace directory
transform.py                # CLI: convert NotebookLLM dossiers into prep.py input
requirements.txt            # anthropic, pyyaml, pyperclip
tests/
  test_prep.py              # Tests for campaignlib, prep, and session_doc logic
config/
  config.yaml               # Default paths to documents and agent prompts
  system_prompt.md          # Main system prompt (single mode) — the Campaign Architect
  agents/
    lore_oracle.md          # Stage 1: canon consistency checker
    encounter_architect.md  # Stage 2: tactical encounter designer
    voice_keeper.md         # Stage 3: tone and voice editor
docs/                       # Default doc location (override via config)
  campaign_state.md         # Completed content + current NPC states (grounding doc)
  world_state.md            # Living canon document — source of truth
  mechanics.md              # Arc score systems
  planning.md               # Enemy dossiers and planning docs
  party.md                  # Party roster, arc scores, relationships
logs/                       # Auto-generated timestamped session logs
```

## Shared library: campaignlib.py

All file I/O, API calls, clipboard, and logging live in `campaignlib.py`. Every script imports from it. **Do not duplicate these in new scripts.**

| Function | Purpose |
|---|---|
| `find_default_config(script_file)` | Returns CWD `config.yaml` if present, else `<script_dir>/config/config.yaml` |
| `load_config(path)` | Loads YAML, returns `(dict, config_dir_path)` |
| `load_file(path, base_dir)` | Reads a file; resolves relative paths against `base_dir` |
| `assemble_docs(config, labels, base_dir)` | Loads named docs from config, joins with separators |
| `make_client()` | Returns an `anthropic.Anthropic()` client |
| `stream_api(client, system, user, model, max_tokens, silent, verbose)` | Streams a Claude API call, returns full response. `silent=True` suppresses output. `verbose=True` prints system + user prompts before calling. |
| `copy_to_clipboard(text)` | Copies text to clipboard via pyperclip |
| `save_log(log_dir, sections, stem)` | Saves a timestamped markdown log file |

### Writing a new script

```python
from campaignlib import find_default_config, load_config, assemble_docs, make_client, stream_api, call_api, save_log

parser.add_argument("--config", default=find_default_config(__file__))
config, base_dir = load_config(args.config)
docs = assemble_docs(config, ["world_state"], base_dir)
client = make_client()
response = stream_api(client, SYSTEM_PROMPT, docs, args.model)
```

**Never import `anthropic` directly in scripts.** All Claude API calls must go through `campaignlib`:

- `stream_api()` — streaming text call (use for all standard calls)
- `call_api()` — non-streaming call; accepts a string or a list of content blocks (use for multimodal/vision calls, e.g. PDF documents)
- `make_client()` — creates the Anthropic client

Both functions handle retries automatically (rate limits, overload, connection errors). Do not implement retry logic in scripts.

## Config and workspaces

All scripts auto-detect the config: they look for `config.yaml` in the current working directory first, then fall back to `config/config.yaml` in the script directory. This means you can run any script from a campaign workspace directory without passing `--config`.

To create a new workspace:

```bash
python new_workspace.py ~/campaigns/icespire --name "Icespire Peak"
```

This generates a `config.yaml` with absolute paths so it works from any directory. Pass `--world-state`, `--mechanics`, `--planning`, `--party`, or `--campaign-state` to point at existing files instead of creating placeholders.

## Other scripts

### campaign_state.py

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

### make_tracking.py

Extracts a tracking list from an adventure module markdown. Items are phrased neutrally (subject + event type, no outcome) so `campaign_state.py` can determine whether each one has happened yet.

```bash
python make_tracking.py "Dragon of Icespire Peak.md" --output docs/tracking.txt
```

Then pass the result to `campaign_state.py --track-file`. Review and edit the list before use — the model may include events that have not yet occurred in your campaign.

### query.py

Ad-hoc search tool. Scans session summaries for a specific event, NPC, or topic and synthesizes a direct answer. Useful when `campaign_state.md` is missing something and you want to verify whether it happened.

```bash
python query.py summaries.md "Did the party clear Gnomengarde?"
python query.py summaries.md "What happened with Grundar at Icespire Hold?"
python query.py summaries.md "Xalvosh" --hits-only   # raw matching extracts only
python query.py summaries.md "Kraken Society arc score" -o notes/kraken.md
```

Uses a smaller default chunk size (40k) for more precise hits. The filter pass runs silently; only the synthesis streams to the terminal.

### planning.py

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

### party.py

Generates `party.md` from character sheets, session summaries, backstories, and arc score mechanics.

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

### dnd_sheet.py

Converts a D&D Beyond character sheet PDF to structured markdown using Claude's vision API.

```bash
python dnd_sheet.py Soma.pdf --output soma.md
python dnd_sheet.py *.pdf --output-dir ~/campaigns/characters/
```

### npc_table.py

Generates a markdown NPC reference table (Name / Faction / Current State / Motivations) from one or more campaign documents.

```bash
python npc_table.py                              # uses world_state
python npc_table.py --docs world_state planning  # combine multiple docs
python npc_table.py --output npc_state.md
```

### distill.py

Converts a large session-summary file into a structured `world_state.md` via a two-pass extract → synthesize pipeline. Intermediate extractions are saved so the synthesis can be re-run without re-extracting.

```bash
python distill.py summaries.md --output docs/world_state.md
python distill.py --synthesize-only --extract-dir docs/distill_extractions --output docs/world_state.md
```

### session_doc.py

Generates a post-session narrative document from a session recap, VTT roleplay extractions, and per-character voice files. Runs a five-pass pipeline:

1. **Consistency check** — compares the recap against campaign context documents
2. **Enhance structured sections** — rewrites Memorable Moments, appends Consistency Notes, preserves Scenes/NPCs/Locations/Items/Spells
3. **Narrative plan** — assigns each character a portion of the session to narrate
4. **Character extraction** (silent, per character/scene) — pulls that character's moments from their assigned chunk
5. **Narration** (per character/scene) — writes first-person prose from the extracted moments

Two narration modes:
- **Chunk mode** (default): each character covers a chronological slice of the session
- **Scene mode** (`--by-scene`): each scene is narrated by one rotating character — matches the handcrafted campaign summary style

```bash
# Full run, chunk mode
python session_doc.py session-mar \
    --roleplay-extract-dir vtt_roleplay_extractions/ \
    --summary-extract-dir  vtt_extractions/ \
    --context docs/campaign_state.md docs/world_state.md \
    --party partyfile.md \
    --characters "Vukradin, Valphine, Soma, Brewbarry" \
    --voice-dir voice/ \
    --examples examples/ \
    --output session-doc.md

# Scene-by-scene mode
python session_doc.py session-mar ... --by-scene --output session-doc.md

# Inspect plan only (no narration)
python session_doc.py session-mar ... --plan-only

# Dry run: print pass 4 prompts without calling API
python session_doc.py session-mar ... --by-scene --dry-run --output /dev/null

# Use a hand-edited plan (skip pass 3)
python session_doc.py session-mar ... --plan-file my_plan.md --output session-doc.md

# Single character only (skips passes 1–2, useful for voice tweaking)
python session_doc.py session-mar ... --narrator Brewbarry --output brewbarry.md
```

#### Iterative workflow (review extractions before narrating)

```bash
# Step 1: run passes 1–4, save per-scene extractions, stop before narration
python session_doc.py session-mar ... --by-scene \
    --extract-dir scene_extractions/ --extract-only --output /dev/null

# Step 2: review and edit files in scene_extractions/
#   Files are named: 01_vukradin_the_stone_giants.md, 02_soma_the_glacier.md, etc.
#   Add missing dialogue, remove hallucinated lines, adjust emphasis.

# Step 3: narrate from the edited extractions (skips passes 1–4)
python session_doc.py session-mar ... --by-scene \
    --from-extractions scene_extractions/ --output session-doc.md
#   plan.md is auto-loaded from scene_extractions/ — no --plan-file needed.

# Re-run a single scene after editing its extraction file
python session_doc.py session-mar ... --by-scene \
    --from-extractions scene_extractions/ --scene 7 --output scene7.md

# Re-run multiple scenes
    --scene 3 7
```

#### All flags

| Flag | Default | Description |
|---|---|---|
| `--roleplay-extract-dir` | required | VTT roleplay extractions (quoted dialogue and character moments) |
| `--summary-extract-dir` | — | VTT session extractions (action detail, events, environment) |
| `--context` | — | Campaign context files for pass 1 consistency check |
| `--party` | — | `party.md` — backstory, personality, relationships |
| `--characters` | — | Comma-separated narrator roster |
| `--voice-dir` | — | Directory of `{name}_voice.md` files written by players |
| `--examples` | — | Directory of handcrafted `.md` files as style references (all `*.md` in dir are loaded) |
| `--session-name` | recap filename | Document title |
| `--by-scene` | off | Scene-by-scene narration mode |
| `--plan-file` | — | Supply a hand-written plan; skip pass 3 |
| `--narrator NAME` | — | Single character only; skips passes 1–2 |
| `--scene N [M …]` | — | Run only the specified scene number(s) from the plan |
| `--extract-dir DIR` | — | Save pass-4 extractions to this directory (one file per scene, plus `plan.md`) |
| `--extract-only` | off | Stop after pass 4; don't narrate |
| `--from-extractions DIR` | — | Skip passes 1–4; load saved extractions and narrate only |
| `--plan-only` | off | Print the plan and exit |
| `--dry-run` | off | Print pass 4 prompts without calling the API |
| `--verbose` | off | Print all prompts before each API call |
| `--model` | `claude-sonnet-4-6` | Claude model (64K output cap required for long narrations) |
| `--fast` | off | Use Haiku (~4× cheaper, faster, slightly lower quality) |
| `--no-log` | off | Skip saving the log file |

#### Voice files

Per-character voice files live in `--voice-dir` (e.g. `voice/vukradin_voice.md`). Each file is injected only into that character's narration pass. Players write their own; see `PLAYER_VOICE_GUIDE.md` for the format.

#### Dialogue handling

- **Chunk mode**: strong mandate — "THE DIALOGUE IS THE STORY". Full sessions reliably have dialogue.
- **Scene mode**: conditional — "USE DIALOGUE IF PRESENT". If a scene had no dialogue (wordless combat, environmental crossing), the model narrates from action beats and environment only. It does not invent dialogue.

### session_doc_ui.py — Session Doc Editor (Flask web UI)

A browser-based editor for the extract → edit → narrate → assemble workflow. Three panels:

- **Left**: scene list with badges (Extracted / Narrated); click to switch scene
- **Centre**: extraction file editor, toolbar, and streaming narration output
- **Right**: tabbed panel — **VTT Source** (roleplay extraction files for reference) and **Quote Ledger** (SQLite-backed dialogue tracker)

#### Prerequisites

Before starting the UI you need:

1. **Session recap file** — the structured session notes passed to `session_doc.py` (e.g. `session-mar`)
2. **Scene extractions** — run passes 1–4 first to produce `scene_extractions/plan.md` and one extraction file per scene:
   ```bash
   python session_doc.py session-mar \
       --roleplay-extract-dir vtt_roleplay_extractions/ \
       --summary-extract-dir  vtt_extractions/ \
       --context docs/campaign_state.md docs/world_state.md \
       --party partyfile.md \
       --characters "Vukradin, Valphine, Soma, Brewbarry" \
       --voice-dir voice/ \
       --examples examples/ \
       --by-scene \
       --extract-dir scene_extractions/ \
       --extract-only \
       --output /dev/null
   ```
3. **VTT roleplay extractions** — the `vtt_roleplay_extractions/` directory produced by `vtt_summary.py --roleplay-output` (shown in the right panel for reference while editing)

Optional but recommended:
- `partyfile.md` — passed to each narration call
- `voice/` directory — per-character voice files injected into narration

#### Starting the UI

From the campaign workspace directory:

```bash
# Via wrapper script (recommended — reads ui_config.yaml)
./ui.sh

# Or directly
python ~/CampaignGenerator/session_doc_ui.py session-mar \
    --extract-dir scene_extractions/ \
    --roleplay-extract-dir vtt_roleplay_extractions/ \
    --output-dir . \
    --party partyfile.md \
    --voice-dir voice/ \
    --narrate-tokens 4000

# Then open http://localhost:5000
```

Alternatively, launch from the Streamlit app: navigate to **Session Doc Editor** and click **Launch Server**.

#### Scene-by-scene workflow

1. Click a scene in the left panel → the extraction text loads in the editor
2. Review and edit: add missing dialogue, remove hallucinated lines, adjust emphasis
   - The right panel shows the VTT roleplay source for that session — use it to find exact quotes
3. **Save** — writes the edited extraction back to disk
4. **Edit in Typora** — opens the extraction file in Typora (WSL-aware); click **Reload** afterwards to pull changes back into the browser
5. **Narrate** — streams the narration call (`session_doc.py --from-extractions --scene N`); output appears in the narration panel below the editor and is saved to `sceneN.md` in `--output-dir`
6. **Open narration in Typora** — opens the saved `sceneN.md` for review
7. Repeat for each scene; the left panel shows **Extracted** / **Narrated** badges per scene

#### Assembling the final document

Once all scenes are narrated, click **Assemble Doc** in the header bar. This:
- Collects all `sceneN.md` files from `--output-dir`
- Strips the per-scene title and surrounding dividers from each
- Joins them with `---` separators under a single title
- Saves the result as `{session-name}-doc.md` in `--output-dir`
- Shows an **Open in Typora** button for the assembled file

Scenes that have not yet been narrated are skipped (noted in the terminal). You can assemble a partial document at any point.

#### Quote Ledger

The right panel's **Quote Ledger** tab tracks verbatim VTT dialogue and shows which quotes made it into scene extractions. This surfaces the gap between what was said (VTT roleplay extractions) and what Claude chose to include (Pass 4 scene extractions), so you can find missing dialogue and paste it into the editor.

**Sync** parses `vtt_roleplay_extractions/extract_*.md`, stores every quoted block in a SQLite database (`scene_extractions/quote_ledger.db`), and fuzzy-matches each quote against the dialogue in scene extraction files (0.6 similarity threshold).

Quotes are grouped by scene. Unassigned quotes (no match found) appear at the top — these are the most likely to be missing from extractions. Click a quote to expand it, then use the **Move** dropdown to reassign it to a different scene or unassign it. Manual assignments are pinned and won't be overwritten by future syncs.

The ledger is read-only with respect to extraction files — it does not modify them. To include a missing quote in a narration, copy it from the ledger into the extraction editor (middle panel) and save.

`quote_ledger.py` contains the parsing, matching, and SQLite logic. The Flask routes are in `session_doc_ui.py`.

#### Token estimates

Each extraction file shows an estimated output token count in the editor header. If it exceeds `--narrate-tokens`, the estimate turns orange. To override the limit for one scene, add this as the first line of the extraction file:

```
tokens: 6000
```

#### `ui_config.yaml` keys

The minimal configuration is a single session directory; all sub-paths are derived automatically:

```yaml
# Minimal — everything derived from one directory
session_doc_session_dir:  /path/to/summaries/20260324

# Derived automatically (override only if non-standard):
#   scene_extractions/         → extract dir (plan.md + extraction files)
#   vtt_roleplay_extractions/  → roleplay source panel
#   vtt_extracts/              → summary extractions (narration context)
#   <session_dir>/             → output dir for sceneN.md files
#   session-recap.md (or most recently modified .md) → recap file

# Campaign-level settings (shared across sessions):
session_doc_voice_dir:      /path/to/voice
session_doc_characters:     "Zalthir, Grygum, Daz, Thorin"
session_doc_examples_dir:   /path/to/examples/   # directory of *.md style references
session_doc_narrate_tokens: 4000
session_doc_port:           5000

# Streamlit app pre-populates campaign_state and world_state from:
campaign_state_output: docs/campaign_state.md
world_state_output:    docs/world_state.md
```

Individual path keys (`session_doc_session`, `session_doc_extract_dir`, etc.) still work as overrides.

#### CLI usage with `--session-dir`

```bash
python session_doc_ui.py --session-dir summaries/20260324 \
    --voice-dir voice/ \
    --characters "Zalthir, Grygum, Daz, Thorin"
```

#### WSL / Windows / Typora

The UI runs in WSL but opens files in Typora on Windows. It uses `wslpath -w` to convert paths and `powershell.exe -c Start-Process "path"` to launch Typora. This handles UNC paths correctly (explorer.exe and cmd.exe do not).

## Streamlit app (app.py)

Central launcher for all campaign tools. Launch from the campaign workspace directory so it auto-detects `ui_config.yaml`:

```bash
cd ~/campaigns/Phandalin
streamlit run ~/CampaignGenerator/app.py
```

Pages: Campaign State, World State, Party, Planning, Session Doc Editor. Each page reads its defaults from `ui_config.yaml` in the current working directory.

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

## Pipeline mode

Three sequential API calls per beat:

1. **Lore Oracle** — verifies the beat against canon; returns CLEAR / FLAGS / GAPS
2. **Encounter Architect** — receives the beat + Oracle report; produces the full structured encounter document
3. **Voice Keeper** — receives the encounter document; tunes NPC dialogue and PC behavioral notes to match established voice

If the Lore Oracle response contains the word `FLAGS`, the user is prompted before continuing to Stage 2.

## Logs

Logs are saved to `log_dir` (from config) as timestamped markdown files. Single-beat logs include the system prompt, user prompt, and response. Session logs include all beats and all pipeline stages in one combined file (stem: `session_arc`).

## Transforming NotebookLLM dossiers

`transform.py` converts a NotebookLLM planning document into `prep.py` input format.

```bash
python transform.py dossier.txt
python transform.py dossier.txt --single          # extract as a single beat
python transform.py dossier.txt -o beats/out.txt  # save for later
```

## VTT transcript → session summary

`vtt_summary.py` converts a Zoom `.vtt` transcript into a structured session summary
using the same two-pass extract → synthesize pipeline as `distill.py`.

```bash
python vtt_summary.py session.vtt --output docs/summaries/session_12.md
python vtt_summary.py session.vtt -o session_12.md --date "2026-03-15" --session-name "Session 12 — Icespire Hold"
python vtt_summary.py --synthesize-only --extract-dir vtt_extractions/ -o out.md
```

Output is a `# Session Name` markdown document suitable for appending to your
summaries file and feeding into `campaign_state.py` or `distill.py`.

### Reference summaries (GMassistant anchor)

The `--reference-summaries` flag passes a pre-existing session summary (e.g. a GMassistant recap) to the extraction and synthesis passes. This is the recommended workflow when a GMassistant recap is available.

```bash
python vtt_summary.py session.vtt \
    --output summaries/20260318/session-summary.md \
    --roleplay-output summaries/20260318/session-roleplay.md \
    --reference-summaries summaries/20260318/gm-assist.md \
    --context docs/campaign_state.md docs/world_state.md docs/party.md
```

**Architecture**: the GMassistant recap is treated as the authoritative account of what happened — it is generated from the same VTT transcript, so every scene it describes has corresponding dialogue in the transcript. The extraction passes are anchored on it:

1. **Primary**: find verbatim dialogue for every scene and character moment the reference describes
2. **Bonus**: catch any significant exchanges the reference missed (side conversations, throwaway jokes that turned into moments)

Without `--reference-summaries`, the extraction falls back to an unguided scan — less precise because each chunk is processed independently with no knowledge of what matters in the full session.

The reference summary also feeds into the synthesis pass for cross-referencing, ensuring the final summary doesn't miss events that appear in the GMassistant recap.

### Session doc extraction (recap context)

`session_doc.py` Pass 4 (per-scene character extraction) now includes the GMassistant recap's `## Summary` and `## Memorable Moments` sections alongside the scene scope and roleplay extractions. This ensures narrative detail and character backstory beats (e.g. reflections, backstory triggers) that only appear in the recap — not in VTT dialogue — are available to the extraction model.

### Player name mapping

VTT roleplay extractions reference players by real name (e.g. "David (Vukradin)"), but scene scopes reference characters by name only. `session_doc.py` bridges this by parsing player names from `party.md`. The expected format in party.md is:

```
## Soma
**Tortle Druid 5, Player: Wade**
```

`extract_character_roster()` parses this into roster lines like `- Soma (Wade): Tortle Druid 5`, which are injected into Pass 4 extraction prompts so the model can match VTT player names to characters.

If a player is absent and someone else plays their character, update `party.md` temporarily (e.g. `Player: Wade/Kostadis`).

### Extraction token scaling

Pass 4 extraction output tokens scale dynamically with input size instead of using a fixed limit. The formula is `min(8192, max(1500, len(prompt) // 4))`. This prevents truncation on dense scenes while keeping short scenes efficient.

### Narration token defaults

The default `narrate_tokens` is 12000 for all modes (scene and chunk). Scene-mode narrations routinely need 3000–6000 tokens for dialogue-heavy scenes. The `--narrate-tokens` flag and `tokens:` extraction file header still override this.

## Running tests

```bash
python -m pytest tests/
```

## Dependencies

```bash
pip install anthropic pyyaml pyperclip streamlit pyvis
```

`ANTHROPIC_API_KEY` must be set in the environment.
