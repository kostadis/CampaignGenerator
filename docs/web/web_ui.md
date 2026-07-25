# Web UI (FastAPI + Vue 3)

The primary UI is a FastAPI backend + Vue 3 frontend that wraps all CLI tools in a browser interface with SSE streaming output.

## Starting the UI

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

## Campaign layout

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

## Pages

**Session Workflow** (wizard steps):
1. **Session Config** — set campaign_dir and session_dir; all paths auto-derived
2. **Editor Config** — the Session Doc Editor's own knobs (`session_doc.yaml`)
3. **Enhance Summary** — run `enhance_summary` over the .vtt + gm-assist to produce `session-summary.md`
4. **Extract Quotes** — run `scene_extract` to produce per-scene extraction files
5. **Plan & Check** — run `sd_consistency` + `sd_plan` to produce `plan.md` and `consistency_report.md`
6. **Session Doc Editor** — two-panel editor (scene list / extraction editor)

**Grounding Docs**: Campaign State, World State, Party Document, Planning Document

**Ensemble** (four-stage extraction + synthesis workflow):
- **Stage 1 — Extraction**: Runs `ensemble_batch` over the selected chapters.
  - **Command bar**: Shows the exact, secret-free, copyable invocation emitted by the server. Paste it into a workspace terminal to reproduce the run. No API key ever appears in the command.
  - **Running state**: Button shows "Running…" while the stage is active; live output streams incrementally.
  - **Abort**: An Abort button appears while running. Clicking it closes the stream — the server group-kills the entire worker tree (including per-chapter `ensemble_extract` subprocesses) via SIGTERM → SIGKILL. A "connection lost" note appears if the browser drops the network mid-run (treated as an implicit abort; no unobserved token spending).
  - **Finished states**: "Done" (exit 0), "Exit N" (failure), or "Aborted" — each visually distinct.
  - **Durable record**: Every run writes `<campaign>/logs/<timestamp>_ensemble_batch.md` with the command, full output, result, and duration. Recoverable after closing the browser.
- **Stage 2 — Fact Bundling**: Human-gated scope review + alias correction + aggregate step. Each sub-run has a running state, abort button, and success/failure/aborted labels.
- **Stage 3 — Synthesis & Promotion**: Synthesizes draft grounding docs; human reviews diff before promoting.

**Prep**: Session Prep, NPC Table, Query Summaries, Connection Graph

**Setup**: D&D Sheet, Make Tracking

**Settings**: Raw YAML editor for ui_config.yaml

## Session Doc Editor

Two-panel layout for the extract → edit → narrate → assemble workflow:

- **Left**: scene list with the four lifecycle dots (E/R/N/S)
- **Centre**: extraction file editor with save/reload, token estimates, streaming narration output

**Workflow**: click a scene → review/edit extraction → Narrate (streams `sd_narrate --plan plan.md --scene N`) → repeat → Assemble Doc.

The editor has a config panel for setting paths (session recap, scene extractions dir, narration dir, etc.) that auto-populates from the Session Config page. The config panel also accepts characters, voice_dir, examples, and narrate_tokens.

**Typora integration**: Edit in Typora / Open narration buttons work on WSL via `wslpath -w` + `powershell.exe Start-Process`.

### Token estimates

Each extraction file shows an estimated output token count. If it exceeds narrate_tokens, the estimate turns orange. Override per-scene by adding `tokens: 6000` as the first line of an extraction file.

## Connection Graph

**Prep → Connection Graph** builds a queryable entity/relationship graph from campaign markdown. Fills the gap MemPalace can't: **multi-hop connection queries** ("how is A related to B?"). Use it for plot construction, not for narrative consistency checks — those still belong to MemPalace or `query`.

**Storage is per-campaign.** The cache file is always `<campaign_dir>/docs/connections.json` by default (derived from the Session Config `campaign_dir`). Every endpoint threads `cache_path` explicitly so switching campaigns in Session Config never mixes graphs across campaigns. The path is shown as a PathField — override it if you want a separate graph (e.g. one per session).

**Workflow:**

1. **Set paths** (auto-populated from Session Config):
   - *Campaign docs directory* → source files to scan (e.g. `<campaign>/docs`)
   - *NPC dossier directory* → optional, enables alias canonicalization (e.g. `<campaign>/docs/npcs`)
   - *Connections cache file* → per-campaign `connections.json`
2. **Select documents** to extract from (checkboxes + "additional files" for paths outside docs/)
3. **Extract** — calls Claude with the dossier roster prepended to the system prompt and alias-normalized input, then canonicalizes entity IDs to `{type}_{slug(label)}` for stability across runs. By default merges into the existing cache (new summaries win, edges union-deduped); check "Replace cache" to overwrite.
4. **Query the graph** (no further API calls):
   - Click any entity row to open the **Context Panel** — shows the entity, 1-hop neighbors (clickable to navigate), and which doc files mention it (via grep on label + aliases).
   - **Path Finder** — pick source and target from the dropdowns (or use the A/B buttons on any row), set max hops (default 4, capped at 8), click "Find Paths." Returns all simple paths, sorted shortest-first, with per-edge direction and labels. Undirected traversal — it'll find A↔B regardless of which side of the edge A was on.

**Why alias + dossier_dir matters:** without it, "Xalvos" and "Xalvosh" become separate nodes and no path is found. With it, input docs are rewritten to canonical names before the LLM sees them, and the roster is appended to the system prompt. Same mechanism as `planning --synthesize` (see [`docs/rlm/dossier_aliases.md`](../rlm/dossier_aliases.md)).

**Model choice matters — Haiku truncates full grounding-doc extractions.** Extraction is a single Claude call with `max_tokens=32000`, but the API clamps that to each model's actual output ceiling:

| Model | Output ceiling | Good for |
|---|---|---|
| Sonnet 4.6 | 64K | Seeding the graph from all 4 grounding docs in one call; full rebuilds with "Replace cache" |
| Haiku 4.5 | 8K | Incremental adds — one dossier, one session summary, one module doc at a time |

A full grounding-doc extraction (~100–300 entities + edges) produces 10–30K output tokens, which Haiku truncates mid-JSON and fails the parse. Two workarounds: (a) switch to Sonnet in the global model selector for that one run, or (b) split into two Haiku runs (e.g. `world_state.md` + `campaign_state.md`, then `party.md` + `planning.md`) — they merge into the same cache. Rule of thumb: **Sonnet for seeding and rebuilds, Haiku for iterative growth.**

**API surface** (under `/api/connections`, all accept `cache_path` and default to per-campaign location):

| Endpoint | Purpose |
|---|---|
| `GET /list-docs` | Enumerate `.md` files in a directory |
| `POST /extract` | LLM extraction → canonicalize → merge into cache (`replace: true` to overwrite) |
| `GET /data` | Return cached JSON |
| `POST /graph` | Render pyvis HTML from cache |
| `GET /paths` | Simple paths between two entities (`source`, `target`, `max_hops`, `max_paths`) |
| `GET /context` | Entity + 1-hop neighbors + doc files mentioning it (`docs_dir`, `dossier_dir` for alias-aware grep) |

**Pure functions** in `server/routers/connections.py` (unit-tested in `tests/test_connections.py`): `canonicalize()`, `merge()`, `find_simple_paths()`, `neighbors_of()`. The LLM only runs in `/extract`; every query endpoint is deterministic graph traversal.

## `ui_config.yaml`

Config is stored in `ui_config.yaml` in the working directory (the campaign directory). The minimal config is:

```yaml
campaign_dir: /path/to/campaign
session_dir:  /path/to/campaign/summaries/20260324
```

All other paths are derived automatically. The UI saves config changes to this file. Key prefixes that are persisted: `cs_`, `distill_`, `party_`, `plan_`, `query_`, `prep_`, `npc_`, `sd_`, `sw_`, `vtt_`, `session_dir`, `campaign_dir`, `narr_`, `er_`, `cg_`, `dnd_`, `mt_`, `global_`, `summaries`.

## Architecture

- **Backend**: `server/` — FastAPI app with 9 route modules. CLI tools run as async subprocesses with SSE streaming via `subprocess_runner.py`
- **Frontend**: `frontend/` — Vue 3 + TypeScript + Pinia + Vue Router, Catppuccin Mocha theme
- **CLI tools**: All existing scripts are unchanged — the backend orchestrates them

## Development

```bash
# Two processes — hot reload on both
cd frontend && npm run dev &   # :5173, proxies /api/* to :8000
uvicorn server.main:app --reload --port 8000
```

## WSL / Windows / Typora

The UI runs in WSL but opens files in Typora on Windows. It uses `wslpath -w` to convert paths and `powershell.exe -c Start-Process "path"` to launch Typora. This handles UNC paths correctly (explorer.exe and cmd.exe do not).
