# CampaignGenerator

A D&D session-prep and post-session documentation toolkit powered by the [Claude API](https://docs.anthropic.com/). Runs as a **FastAPI + Vue 3 web UI** or a suite of **CLI tools** — generate encounter documents, keep campaign canon consistent, process Zoom VTT transcripts, and produce multi-voice narrative session documents.

---

## What it does

| Layer | What you get |
|---|---|
| **Web UI** | Browser dashboard — run every pipeline step, edit scene extractions, review narrations, manage config, visualize NPC connection graphs, and track VTT dialogue |
| **CLI tools** | Python scripts for session prep, post-session pipelines, grounding-doc generation, and RPG library retrieval |
| **RLM** | Retrieval pipeline over a local RPG library (5etools + MemPalace) — tiered search, dossier proposals, MCP tools |

---

## Setup

**Requirements:** Python 3.10+, Node.js (web UI only), [uv](https://github.com/astral-sh/uv)

```bash
uv venv
source .venv/bin/activate
uv pip install anthropic pyyaml pyperclip pyvis fastapi uvicorn
export ANTHROPIC_API_KEY=sk-ant-...
```

### Web UI

```bash
# Build the frontend and start the FastAPI server
./startup
```

Then open `http://localhost:8000`.

### CLI only

No build step needed — run scripts from a campaign workspace:

```bash
new_workspace ~/campaigns/mycamp --name "My Campaign"
cd ~/campaigns/mycamp
prep --beat "The party enters Icespire Hold"
```

---

## Quick start

### 1. Create a workspace

```bash
new_workspace ~/campaigns/mycamp --name "My Campaign"
cd ~/campaigns/mycamp
```

Generates a `config.yaml` with absolute paths — every script auto-detects it when run from the workspace directory. No `--config` flag needed.

### 2. Before a session — prep

```bash
# Single encounter beat
prep --beat "The party enters Icespire Hold"

# Three-stage pipeline: Lore Oracle → Encounter Architect → Voice Keeper
prep --mode pipeline --beat "The party enters Icespire Hold"

# Full session arc
prep --session "1. Travel to Hold 2. Confront boss 3. Dragon reveal"
```

### 3. After a session — documentation pipeline

```bash
# Convert Zoom transcript to summary
python ~/CampaignGenerator/vtt_summary.py session.vtt -o summaries/session_12.md

# Regenerate grounding docs
python ~/CampaignGenerator/campaign_state.py summaries.md -o docs/campaign_state.md
python ~/CampaignGenerator/distill.py summaries.md -o docs/world_state.md

# Session doc pipeline — see sd_*.py section below
```

---

## Post-session narrative pipeline (`sd_*.py`)

The recommended path for producing narrative session documents is a four-script pipeline with a human-review checkpoint after each stage:

```
VTT transcript + recap
        │
 enhance_summary.py   ← enhance raw summary
        │
 scene_extract.py     ← extract per-scene dialogue and action beats from VTT
        │  [human review]
 sd_consistency.py    ← Pass 1: consistency check vs. campaign state / world state
        │
 sd_plan.py           ← Pass 3: narrative plan — assigns characters to scene chunks
        │  [human review]
 sd_narrate.py        ← Pass 5: per-scene first-person narration in each character's voice
        │  [human review]
 assemble.py          ← combine narrated scenes into the final session document
```

Each script is standalone — run it, review the output, then proceed. See [`docs/cli/session_doc_pipeline.md`](docs/cli/session_doc_pipeline.md) for flags, voice files, player-name mapping, token scaling, and design rationale.

---

## Script reference

### Pre-session prep

| Script | What it does |
|---|---|
| `prep.py` (`pipelines/session_prep/`) | Session beat and arc prep — single mode or Lore Oracle → Encounter Architect → Voice Keeper pipeline |
| `planning.py` | Generate `planning.md` from NPC dossiers and arc scores |
| `npc_table.py` | Generate a quick NPC reference table (Name / Faction / State / Motivations) |
| `query.py` | Search session summaries for a specific event, NPC, or topic |

### Post-session pipeline

| Script | What it does |
|---|---|
| `vtt_summary.py` | Zoom `.vtt` transcript → structured session summary |
| `enhance_summary.py` | Enhance a raw session summary before extraction |
| `enhance_recap.py` | Enhance a raw session recap |
| `scene_extract.py` | Extract per-scene dialogue and action beats from VTT |
| `sd_consistency.py` | Pipeline Pass 1 — consistency check vs. campaign docs |
| `sd_plan.py` | Pipeline Pass 3 — narrative plan: assign characters to scene chunks |
| `sd_narrate.py` | Pipeline Pass 5 — per-scene first-person narration |
| `assemble.py` | Assemble narrated scenes into the final session document |
| `quote_ledger.py` | SQLite-backed VTT dialogue tracking and speaker review |
| `narrative.py` | Standalone experimental VTT-anchored narration CLI |

### Grounding docs

| Script | What it does |
|---|---|
| `campaign_state.py` | Generate a grounding doc tracking completed content and current NPC states |
| `distill.py` | Synthesize session summaries → living `world_state.md` |
| `party.py` | Generate `party.md` from character sheets, summaries, and arc scores |

### Kanka CE integration

[Kanka Community Edition](https://github.com/owlkeep/kanka) is a self-hosted campaign wiki. Three scripts bridge it to CampaignGenerator's grounding layer:

| Script | Direction | Description |
|---|---|---|
| `kanka_sync.py` (`pipelines/integrations/kanka/`) | Kanka → `world_state.md` | Pull all NPCs, factions, locations, events, notes into a grounding doc |
| `kanka_push.py` (`pipelines/integrations/kanka/`) | `world_state.md` → Kanka | Push an edited grounding doc back (create or update; never delete; dry-run by default) |
| `kanka_mcp.py` (`pipelines/integrations/kanka/`) | MCP server | Expose pull/push as MCP tools (`kanka_pull`, `kanka_push_preview`, `kanka_push_apply`) |

**Setup:**

```bash
export KANKA_TOKEN=<your-api-token>
export KANKA_BASE_URL=http://localhost:8081   # default; omit if correct

# Pull Kanka campaign 1 → scratch file, review, then promote
kanka_sync --campaign 1 --output /tmp/world_state.generated.md

# Push edited world_state.md back → dry run (safe default; shows plan, writes nothing)
kanka_push --campaign 1 --input docs/world_state.md

# Commit the push
kanka_push --campaign 1 --input docs/world_state.md --apply
```

**MCP wiring** (`.mcp.json`):

```json
{
  "mcpServers": {
    "kanka": {
      "command": "kanka_mcp",
      "env": {
        "KANKA_TOKEN": "<your-api-token>",
        "KANKA_BASE_URL": "http://localhost:8081"
      }
    }
  }
}
```

### MCP server setup

Three MCP servers can be wired into campaign workspaces so Claude has direct access to campaign data, 5etools, and Kanka:

| Server | Script | Registered when |
|---|---|---|
| `campaign` | `mcp_server.py` | always (campaign has `config.yaml`) |
| `5etools` | `launch_5etools_mcp.py` | campaign has `refs.yaml` |
| `kanka` | `kanka_mcp.py` (`pipelines/integrations/kanka/`) | `--kanka-token` is passed |

Use `configure_mcp` to write `.mcp.json` for all campaign workspaces at once:

```bash
# Preview — show what would be written without changing anything
configure_mcp --dry-run

# Write .mcp.json to all campaigns under ~/src/campaigns/
configure_mcp

# Include the Kanka server
configure_mcp --kanka-token <your-api-token>

# Target a single campaign
configure_mcp ~/src/campaigns/toee

# Overwrite existing .mcp.json entirely (default: merge, preserving extra servers)
configure_mcp --force
```

By default the script **merges** into any existing `.mcp.json`, so manually added servers are preserved. `5etools` is only added when the campaign directory contains a `refs.yaml`.

### RPG Library Module (RLM)

| Script | What it does |
|---|---|
| `rpg_retriever.py` | Tiered retrieval from local RPG library (drawer / statblock / cost-tagged candidate) |
| `dossier_proposer.py` | Run retrieval → write `docs/dossier_proposal.md` for human approval |
| `fivetools_catalog.py` | Mtime-cached name index over canonical 5etools data |
| `fivetools_ingest.py` | Ingest 5etools JSON into MemPalace drawers |
| `convert_book.py` | PDF → 5etools JSON (pdf-translators) |
| `mcp_server.py` | MCP server — `rpg_search`, `propose_dossier`, `suggest_conversion` tools |
| `mempalace_client.py` | MemPalace MCP write client |

### Utilities

| Script | What it does |
|---|---|
| `new_workspace.py` (`pipelines/workspace/`) | Create a new campaign workspace with a `config.yaml` |
| `dnd_sheet.py` | D&D Beyond character sheet PDF → markdown (vision API) |
| `make_tracking.py` | Extract trackable events from an adventure module |
| `transform.py` (`pipelines/session_prep/`) | Convert NotebookLLM dossiers to `prep` input |

---

## RLM — RPG Library Module

The RLM pipeline lets prep and narration tools pull statblocks, encounter tables, and canon lore from a local library without hallucination:

1. **Retrieve** — `rpg_retriever.py` searches in tiers: MemPalace drawer → statblock → cost-tagged candidate
2. **Propose** — `dossier_proposer.py` writes `docs/dossier_proposal.md` — a ranked candidate list for human review and approval
3. **Render** — approved proposals are consumed by render pipelines (`prep`, `sd_narrate.py`, `planning.py`)

The human checkpoint between retrieval and rendering is enforced by a CI test — render pipelines cannot call retrieval functions directly. See [`docs/rlm/rlm_pipeline.md`](docs/rlm/rlm_pipeline.md) and [`docs/rlm/rlm_architecture.md`](docs/rlm/rlm_architecture.md).

---

## Docs

| File | Contents |
|---|---|
| [`docs/core/architecture.md`](docs/core/architecture.md) | System map — layers, pipelines, on-disk state, "start here" table |
| [`docs/cli/session_doc_pipeline.md`](docs/cli/session_doc_pipeline.md) | Post-session pipeline: flags, voice files, player-name mapping, token scaling, design rationale |
| [`docs/cli/cli_tools.md`](docs/cli/cli_tools.md) | Per-script flags and typical new-campaign workflow |
| [`docs/web/web_ui.md`](docs/web/web_ui.md) | Web UI: pages, Session Doc Editor, Quote Ledger, Connection Graph |
| [`docs/rlm/rlm_pipeline.md`](docs/rlm/rlm_pipeline.md) | RLM three-state retrieval, ingest flow, MCP tools |
| [`docs/README.md`](docs/README.md) | Full doc index |

---

## Config

All scripts auto-detect config: CWD `config.yaml` first, then `config/config.yaml` in the script directory. Running from a campaign workspace means no `--config` flag needed.

Override with `--config path/to/config.yaml` when necessary.

---

## Running tests

```bash
python -m pytest tests/
```

---

## Model choice

All scripts default to **Claude Sonnet** (`claude-sonnet-4-6`) and accept `--model` for overrides. Narration scripts accept `--fast` for **Claude Haiku** (~4× cheaper), useful for iterating before a final run.

```bash
python sd_narrate.py ... --fast                       # Haiku — iterate quickly
python sd_narrate.py ... --model claude-opus-4-8      # Opus — highest quality
```

---

## License

MIT
