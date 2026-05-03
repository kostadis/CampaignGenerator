# CLAUDE.md

Guidance for Claude Code working in this repo.

# CampaignGenerator

A D&D session-prep CLI that assembles campaign documents and session beats, calls the Claude API to generate encounter/narration documents, and integrates with rpglib + MemPalace for verbatim retrieval from a local RPG library.

## Project structure

```
# ── Web UI ──
startup                     # Launch script — builds frontend, starts FastAPI server
server/                     # FastAPI backend (routers, subprocess SSE streaming)
frontend/                   # Vue 3 + TypeScript + Pinia + Vue Router

# ── CLI tools ──
campaignlib.py              # Shared library — all scripts import from here
prep.py                     # CLI: session beat / session arc prep
session_doc.py              # CLI: post-session narrative document generator
narrative.py                # Supporting module for session_doc.py
quote_ledger.py             # SQLite-backed VTT dialogue tracking
npc_table.py                # CLI: generate NPC reference table
distill.py                  # CLI: convert summaries → world_state.md
campaign_state.py           # CLI: generate completed-content grounding doc
make_tracking.py            # CLI: extract trackable events from a module
query.py                    # CLI: search summaries
vtt_summary.py              # CLI: Zoom .vtt → session summary
planning.py                 # CLI: NPC dossiers + arc scores → planning.md
party.py                    # CLI: character sheets + summaries → party.md
dnd_sheet.py                # CLI: D&D Beyond PDF → markdown (vision API)
new_workspace.py            # CLI: create a new campaign workspace
transform.py                # CLI: NotebookLLM dossiers → prep.py input

# ── RLM tools ──
rpg_retriever.py            # Tiered retrieval (drawer / statblock / cost-tagged candidate)
fivetools_catalog.py        # Mtime-cached name index over canonical 5etools data
dossier_proposer.py         # Run retrieval → write docs/dossier_proposal.md
proposal_loader.py          # Render pipelines consume approved proposals
mempalace_client.py         # Writes via MemPalace MCP
mcp_server.py               # MCP tools: rpg_search, propose_dossier, suggest_conversion
convert_book.py             # PDF → 5etools JSON (pdf-translators)
fivetools_ingest.py         # 5etools JSON → MemPalace drawers

# ── Config & docs ──
config/
  config.yaml               # Default paths to documents and agent prompts
  system_prompt.md          # Single-mode system prompt
  agents/                   # Pipeline-mode prompts (lore_oracle, encounter_architect, voice_keeper)
docs/                       # Default doc location (override via config)
  campaign_state.md, world_state.md, mechanics.md, planning.md, party.md
logs/                       # Auto-generated timestamped session logs
tests/test_prep.py          # Tests for campaignlib, prep, and session_doc logic
```

## Detailed docs (read on demand)

| File | When to read it |
|---|---|
| `docs/cli_tools.md` | Per-script invocations and flags (prep, campaign_state, planning, party, distill, query, …); typical new-campaign workflow |
| `docs/session_doc_pipeline.md` | session_doc.py 5-pass + 4-stage pipeline, all flags, voice files, dialogue handling, recap context, player-name mapping, token scaling, vtt_summary.py |
| `docs/web_ui.md` | FastAPI/Vue UI: pages, Session Doc Editor, Quote Ledger, Connection Graph, `ui_config.yaml`, dev workflow |
| `docs/dossier_aliases.md` | Dossier merge rules and cross-pipeline alias propagation |
| `docs/rlm_pipeline.md` | Three-state retrieval, ingest flow, MCP tools, palace/rpglib path resolution |
| `docs/rlm_architecture.md` | RLM architecture deep dive — three-pile model, MCP surface, retrieval contract |
| `docs/retrieval_architecture.md` | Palace internals — hierarchical descent algorithm, dirty-flag index lifecycle, 100% recall guarantee, failure modes, operational checklist |
| `docs/session_prep_workflow.md` | End-to-end session-prep walkthrough |

## Critical rules (apply to every task)

### `campaignlib.py` is the API surface

All file I/O, API calls, clipboard, and logging live in `campaignlib.py`. Every script imports from it.

| Function | Purpose |
|---|---|
| `find_default_config(script_file)` | Returns CWD `config.yaml` if present, else `<script_dir>/config/config.yaml` |
| `load_config(path)` | Loads YAML, returns `(dict, config_dir_path)` |
| `load_file(path, base_dir)` | Reads a file; resolves relative paths against `base_dir` |
| `assemble_docs(config, labels, base_dir)` | Loads named docs from config, joins with separators |
| `make_client()` | Returns an `anthropic.Anthropic()` client |
| `stream_api(client, system, user, model, max_tokens, silent, verbose)` | Streams a Claude API call, returns full response |
| `call_api(...)` | Non-streaming call; accepts a string or list of content blocks (multimodal) |
| `copy_to_clipboard(text)` | Copies text via pyperclip |
| `save_log(log_dir, sections, stem)` | Saves a timestamped markdown log file |

```python
from campaignlib import find_default_config, load_config, assemble_docs, make_client, stream_api, call_api, save_log

parser.add_argument("--config", default=find_default_config(__file__))
config, base_dir = load_config(args.config)
docs = assemble_docs(config, ["world_state"], base_dir)
client = make_client()
response = stream_api(client, SYSTEM_PROMPT, docs, args.model)
```

**Never import `anthropic` directly in scripts.** All Claude API calls go through `campaignlib`. `stream_api` and `call_api` handle retries (rate limits, overload, connection errors) automatically — do not implement retry logic in scripts.

### Config auto-detection

All scripts look for `config.yaml` in the CWD first, then fall back to `config/config.yaml` in the script directory. Run any script from a campaign workspace directory without passing `--config`.

### Retrieval/render separation (RLM)

Render pipelines (`prep.py`, `session_doc.py`, `planning.py`) must **not** consume raw `rpg_retriever` output. They consume a human-approved `docs/dossier_proposal.md` file instead. Retrieval is a scope decision; rendering is a prose decision; the proposal is the human checkpoint between them.

A CI test (`tests/test_retrieve_render_isolation.py`) fails if any function body contains both a retrieval call (`retrieve`, `search_hierarchical`, `rpg_search`, …) and a render call (`stream_api`, `call_api`). Don't bypass this — fix the structure.

See `docs/rlm_pipeline.md` for the proposal workflow and MCP tools.

### LLM renders, humans decide

Per the global rule in `~/.claude/CLAUDE.md`: scope/ordering/attribution are precision decisions and need a human checkpoint; rendering verified structure into prose is what LLMs do well. When designing new pipelines in this repo, the pattern is **LLM extracts → human reviews → LLM renders inside that structure** — never **LLM extracts → LLM structures → LLM renders**.

Concrete examples already in the codebase:
- `party.py` outputs candidate arc-score events with quoted triggers, never current values or thresholds
- `planning.py --build-dossiers` writes per-NPC files for human review before `--synthesize`
- The 4-stage `session_doc` pipeline (`docs/session_doc_pipeline.md`) inserts a human review after each LLM pass
- `dossier_proposer.py` writes a proposal file; the GM approves it before render pipelines consume it

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
