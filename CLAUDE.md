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
session_doc_ui.py           # Flask web UI for the session_doc iterative workflow
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
from campaignlib import find_default_config, load_config, assemble_docs, make_client, stream_api, save_log

parser.add_argument("--config", default=find_default_config(__file__))
config, base_dir = load_config(args.config)
docs = assemble_docs(config, ["world_state"], base_dir)
client = make_client()
response = stream_api(client, SYSTEM_PROMPT, docs, args.model)
```

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
    --examples examples/vukradin_arrival.md \
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
| `--examples` | — | Handcrafted summary files as style references |
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

A browser-based editor for the extract → edit → narrate workflow. Three panels:

- **Left**: scene list (click to switch scene)
- **Centre**: extraction file editor + streaming narration output
- **Right**: VTT roleplay source browser

#### Starting the UI

From the campaign workspace directory:

```bash
# Via wrapper script (recommended)
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

Alternatively, launch from the Streamlit app (see below): navigate to **Session Doc Editor** and click **Launch Server**.

#### Workflow

1. Run extractions first (passes 1–4):
   ```bash
   python session_doc.py session-mar ... --by-scene \
       --extract-dir scene_extractions/ --extract-only --output /dev/null
   ```
2. Open the UI at `http://localhost:5000`
3. Click a scene → extraction text loads in the editor
4. Edit: add missing dialogue, remove hallucinated lines, adjust emphasis
5. Click **Save** to write changes to disk
6. Click **Edit in Typora** to open the extraction file in Typora (WSL-aware)
7. After editing in Typora: click **Reload** to pull changes back into the browser
8. Click **Narrate** to stream the narration (calls `session_doc.py --from-extractions --scene N`)
9. Click **Open narration in Typora** to open the saved output file

#### Token estimates

The scene list shows a token estimate for each extraction file. If the estimate exceeds `--narrate-tokens`, a warning is shown. To override for one scene, add a header line to the extraction file:

```
tokens: 6000
```

#### `ui_config.yaml` keys

```yaml
session_doc_session:              /path/to/session-mar
session_doc_extract_dir:          /path/to/scene_extractions
session_doc_roleplay_extract_dir: /path/to/vtt_roleplay_extractions
session_doc_summary_extract_dir:  /path/to/vtt_extractions
session_doc_output_dir:           /path/to/output
session_doc_voice_dir:            /path/to/voice
session_doc_narrate_tokens:       4000
session_doc_port:                 5000
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

## Running tests

```bash
python -m pytest tests/
```

## Dependencies

```bash
pip install anthropic pyyaml pyperclip
```

`ANTHROPIC_API_KEY` must be set in the environment.
