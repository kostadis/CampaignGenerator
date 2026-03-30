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
# ── Web UI ──
startup                     # Launch script — builds frontend, starts FastAPI server
server/
  main.py                   # FastAPI app, CORS, static serving, CLI entry point
  config.py                 # ui_config.yaml management, path derivation
  subprocess_runner.py      # Async SSE streaming for CLI tool subprocesses
  routers/
    config_routes.py        # /api/config — load, save, path validation
    session_workflow.py     # /api/workflow — VTT summary, scene extraction
    scene_editor.py         # /api/editor — scenes, extractions, narrate, assemble
    ledger.py               # /api/ledger — quote sync, assign
    grounding.py            # /api/grounding — campaign_state, distill, party, planning
    prep.py                 # /api/prep — session_prep, npc_table, query
    setup.py                # /api/setup — dnd_sheet, make_tracking
    experimental.py         # /api/experimental — narrative, enhance_recap
    connections.py          # /api/connections — entity/relationship graph extraction
frontend/                   # Vue 3 + TypeScript + Pinia + Vue Router

# ── CLI tools ──
campaignlib.py              # Shared library — all scripts import from here
prep.py                     # CLI: session beat / session arc prep
session_doc.py              # CLI: post-session narrative document generator (5-pass pipeline)
narrative.py                # Supporting module for session_doc.py (narration passes, prompt assembly)
quote_ledger.py             # Quote Ledger: SQLite-backed VTT dialogue tracking and scene matching
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

# ── Config & docs ──
requirements.txt            # anthropic, pyyaml, pyperclip, fastapi, uvicorn, pyvis
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

## Web UI (FastAPI + Vue 3)

The primary UI is a FastAPI backend + Vue 3 frontend that wraps all CLI tools in a browser interface with SSE streaming output.

### Starting the UI

```bash
cd ~/campaigns/Phandalin
~/CampaignGenerator/startup --campaign-dir . --session-dir summaries/20260325
```

Or without CLI args (configure campaign_dir and session_dir in the Session Config page):

```bash
cd ~/campaigns/Phandalin
~/CampaignGenerator/startup
```

The `startup` script builds the frontend if needed, sets `PYTHONPATH`, and runs `python -m server.main`. Open http://localhost:5000 in your browser.

### Campaign layout

The UI expects a standard campaign directory structure:

```
<campaign>/
    docs/                → campaign_state.md, world_state.md, party.md
    voice/               → per-character voice files
    examples/            → handcrafted style references
    summaries/
        <session>/       → VTT, GM recap, extractions, outputs
```

Users specify **campaign directory** + **session directory** on the Session Config page — everything else is derived automatically. Relative paths in form fields resolve against the session directory.

### Pages

**Session Workflow** (wizard steps):
1. **Session Config** — set campaign_dir and session_dir; all paths auto-derived
2. **VTT Summary** — convert .vtt transcript to session summary + roleplay highlights
3. **Scene Extraction** — run session_doc.py passes 1–4 to produce per-scene extraction files
4. **Session Doc Editor** — three-panel editor (scene list / extraction editor / VTT source + quote ledger)

**Grounding Docs**: Campaign State, World State, Party Document, Planning Document

**Prep**: Session Prep, NPC Table, Query Summaries, Connection Graph

**Setup**: D&D Sheet, Make Tracking

**Experimental**: Enhance Recap, Session Narrative

**Settings**: Raw YAML editor for ui_config.yaml

### Session Doc Editor

Three-panel layout for the extract → edit → narrate → assemble workflow:

- **Left**: scene list with Extracted / Narrated badges
- **Centre**: extraction file editor with save/reload, token estimates, streaming narration output
- **Right**: tabbed — VTT Source (roleplay extractions for reference) and Quote Ledger

**Workflow**: click a scene → review/edit extraction → Narrate (streams `session_doc.py --from-extractions --scene N`) → repeat → Assemble Doc.

The editor has a config panel for setting paths (session recap, extract_dir, roleplay_extract_dir, etc.) that auto-populates from the Session Config page. The config panel also accepts characters, voice_dir, examples, and narrate_tokens.

**Typora integration**: Edit in Typora / Open narration buttons work on WSL via `wslpath -w` + `powershell.exe Start-Process`.

### Quote Ledger

The right panel's **Quote Ledger** tab tracks verbatim VTT dialogue and shows which quotes made it into scene extractions. **Sync** parses `vtt_roleplay_extractions/extract_*.md`, stores every quoted block in SQLite (`quote_ledger.db`), and fuzzy-matches against scene extraction dialogue (0.6 threshold).

Unassigned quotes appear at the top — likely missing from extractions. Click to expand, use **Move** to reassign to a different scene. The ledger is read-only with respect to extraction files — copy quotes into the editor manually.

`quote_ledger.py` contains the parsing, matching, and SQLite logic.

### Token estimates

Each extraction file shows an estimated output token count. If it exceeds narrate_tokens, the estimate turns orange. Override per-scene by adding `tokens: 6000` as the first line of an extraction file.

### `ui_config.yaml`

Config is stored in `ui_config.yaml` in the working directory (the campaign directory). The minimal config is:

```yaml
campaign_dir: /path/to/campaign
session_dir:  /path/to/campaign/summaries/20260324
```

All other paths are derived automatically. The UI saves config changes to this file. Key prefixes that are persisted: `cs_`, `distill_`, `party_`, `plan_`, `query_`, `prep_`, `npc_`, `sd_`, `sw_`, `vtt_`, `session_dir`, `campaign_dir`, `narr_`, `er_`, `cg_`, `dnd_`, `mt_`, `global_`, `summaries`.

### Architecture

- **Backend**: `server/` — FastAPI app with 9 route modules. CLI tools run as async subprocesses with SSE streaming via `subprocess_runner.py`
- **Frontend**: `frontend/` — Vue 3 + TypeScript + Pinia + Vue Router, Catppuccin Mocha theme
- **CLI tools**: All existing scripts are unchanged — the backend orchestrates them

### Development

```bash
# Two processes — hot reload on both
cd frontend && npm run dev &   # :5173, proxies /api/* to :8000
uvicorn server.main:app --reload --port 8000
```

### WSL / Windows / Typora

The UI runs in WSL but opens files in Typora on Windows. It uses `wslpath -w` to convert paths and `powershell.exe -c Start-Process "path"` to launch Typora. This handles UNC paths correctly (explorer.exe and cmd.exe do not).


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
pip install anthropic pyyaml pyperclip pyvis fastapi uvicorn
cd frontend && npm install   # Vue 3 frontend
```

`ANTHROPIC_API_KEY` must be set in the environment.
