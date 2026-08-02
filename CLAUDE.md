# CLAUDE.md

Guidance for Claude Code working in this repo.

Codebase search policy (structural queries, non-code fallback, stale-index handling) lives in the global `~/.claude/CLAUDE.md` under "Codebase Semantic Search (codebase-memory-mcp)" — no repo-specific override here.

MemPalace memory-search policy (search-first for past work/decisions, mining freshness, grep fallback) lives in the same global `~/.claude/CLAUDE.md` under "MemPalace Memory Search" — no repo-specific override here.

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
pipelines/session_prep/prep.py  # CLI: session beat / session arc prep
session_doc/sd_consistency.py  # CLI: Pass 1 — consistency check (sd_*.py replaced session_doc.py)
session_doc/sd_plan.py         # CLI: Pass 3 — narrative plan
session_doc/sd_narrate.py      # CLI: Pass 5 — per-scene narration
session_doc/                # Post-session pipeline CLIs (sd_*, assemble, scene_extract,
                             #   enhance_summary, …) + shared helpers (io, voice,
                             #   roster, examples, narrate)
server/migrate_session_doc.py # CLI: one-shot ui_state.yaml → session_doc.yaml — python -m server.migrate_session_doc --campaign-dir /path/to/campaign
server/migrate_ensemble_config.py # CLI: one-shot ui.ensemble → ensemble.yaml — python -m server.migrate_ensemble_config --campaign-dir /path/to/campaign
pipelines/grounding/npc_table.py        # CLI: generate NPC reference table
pipelines/grounding/distill.py          # CLI: convert summaries → world_state.md
pipelines/grounding/campaign_state.py   # CLI: generate completed-content grounding doc
pipelines/grounding/make_tracking.py    # CLI: extract trackable events from a module
pipelines/rlm/query.py      # CLI: search summaries
pipelines/grounding/planning.py         # CLI: NPC dossiers + arc scores → planning.md
pipelines/grounding/party.py            # CLI: character sheets + summaries → party.md
pipelines/content_ingest/dnd_sheet.py  # CLI: D&D Beyond PDF → markdown (vision API)
pipelines/workspace/new_workspace.py  # CLI: create a new campaign workspace
pipelines/session_prep/transform.py  # CLI: NotebookLLM dossiers → prep input

# ── RLM tools ──
pipelines/rlm/rpg_retriever.py    # Tiered retrieval (drawer / statblock / cost-tagged candidate)
pipelines/rlm/fivetools_catalog.py # Mtime-cached name index over canonical 5etools data
pipelines/rlm/dossier_proposer.py # Run retrieval → write docs/dossier_proposal.md
pipelines/rlm/proposal_loader.py  # Render pipelines consume approved proposals
pipelines/rlm/mempalace_client.py # Writes via MemPalace MCP
pipelines/rlm/mcp_server.py       # MCP tools: rpg_search, propose_dossier, suggest_conversion
pipelines/content_ingest/convert_book.py     # PDF → 5etools JSON (pdf-translators)
pipelines/content_ingest/fivetools_ingest.py # 5etools JSON → MemPalace drawers
pipelines/rlm/resolve_refs.py     # Resolve refs.yaml + refs.local.yaml → concrete JSON paths
pipelines/rlm/launch_5etools_mcp.py # Per-campaign 5etools MCP server launcher (reads refs.yaml)

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
| `docs/core/architecture.md` | **Start here.** System map: layers, pipelines, on-disk state, recurring concepts, "common task → start here" table |
| `docs/cli/cli_tools.md` | Per-script invocations and flags (prep, campaign_state, planning, party, distill, query, …); typical new-campaign workflow |
| `docs/cli/session_doc_pipeline.md` | post-session pipeline: sd_consistency / sd_plan / sd_narrate flags, voice files, dialogue handling, recap context, player-name mapping, token scaling, plus design rationale |
| `docs/web/web_ui.md` | FastAPI/Vue UI: pages, Session Doc Editor, Quote Ledger, Connection Graph, `ui_config.yaml`, dev workflow |
| `docs/rlm/dossier_aliases.md` | Dossier merge rules and cross-pipeline alias propagation |
| `docs/rlm/rlm_pipeline.md` | Three-state retrieval, ingest flow, MCP tools, palace/rpglib path resolution |
| `docs/rlm/refs_yaml_reference.md` | Full field reference for `refs.yaml` + `refs.local.yaml` (5etools MCP scope declaration) |
| `docs/rlm/rlm_architecture.md` | RLM architecture deep dive — three-pile model, MCP surface, retrieval contract |
| `docs/rlm/retrieval_architecture.md` | Palace internals — hierarchical descent algorithm, dirty-flag index lifecycle, 100% recall guarantee, failure modes, operational checklist |
| `docs/cli/session_prep_workflow.md` | End-to-end session-prep walkthrough |
| `docs/cli/ensemble_extraction.md` | `ensemble` how-to: single-file, multi-file `--plan` YAML, key flags, output layout |
| `docs/cli/ensemble_workflow.md` | End-to-end ensemble workflow: chapters → `ensemble_batch` → `facts_to_state` → synthesis (API + subscription paths); Phandalin worked example |
| `docs/mcp/mcp_servers.md` | The four MCP servers a campaign can wire into `.mcp.json` (`campaign`, `5etools`, `registry`, `kanka`) — what each does, what gates it, how to wire one in via `configure_mcp` |
| `docs/README.md` | Full doc index — every doc, organised by audience |

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

### Per-service config files (don't reach for `ui_state.yaml`)

Three services own a dedicated, strict (`extra="forbid"`) config file instead of a `ui.<section>` blob in `ui_state.yaml`. Writing to their retired section returns **404** — use the service's own route.

| Service | File | Route | Migrate an existing campaign |
|---|---|---|---|
| Session Doc Editor | `<config>/session_doc.yaml` | `GET`/`PUT /api/editor/config` | `python -m server.migrate_session_doc --campaign-dir DIR` |
| Ensemble | `<config>/ensemble.yaml` | `GET`/`PUT /api/ensemble/config` | `python -m server.migrate_ensemble_config --campaign-dir DIR` |
| Planning | `<config>/planning.yaml` | `/api/planning/*` CRUD | *(no migration — same file all along)* |

Plus the platform tier: `<config>/platform.yaml` (`runtime.default_model`, `session_dir`) via `PUT /runtime`.

The migrations are one-shot and idempotent-ish (they refuse to clobber without `--force`) and report unrecognised keys rather than dropping them. **Skipping one is safe but not free:** `UIState` is `extra="allow"`, so a stale `ui.ensemble`/`ui.session_doc` block loads and is silently ignored — the page then starts from schema defaults, quietly losing hand-tuned selections like per-stage DGX backends and endpoint lists. Run the migration once per campaign before relying on those.

**Never add a default literal to `server/routers/ensemble.py`.** Every ensemble path and tuning knob is declared once, in `server/ensemble_config_shared.py`'s `EnsemblePaths`/`EnsembleTuning`; routes take a sentinel (`""`, or `None` for ints where `0` is meaningful) and resolve from `EnsembleConfigService.resolved()` at the route edge. `tests/test_ensemble_config_defaults.py` fails the build if a `docs/ensemble/`-shaped literal or `backend: str = "anthropic"` reappears there. Resolution happens *before* argv is built, so the copyable command `specs/002-ensemble-run-observability` promises stays fully explicit. See `docs/config/ensemble-isolation.md`.

### Entity registry (single authority for aliases)

`docs/entity_registry.yaml` is the single source of truth for entity identity — canonical spelling, aliases, and the anti-merge guards (`distinct`, `rejected_aliases`). It supersedes the legacy scattered stores (dossier `aliases:` frontmatter, `aliases.json`, `.alias_decisions.json`, module inventories, `.dedup_state.json`). Managed via `registry` (`init`/`add`/`alias`/`import-*`/`triage-candidates`/`check`/`project`); loaded via `campaignlib.registry` (`load_registry`, `find_registry`, `resolve_registry_arg`). Also exposed as an MCP server, `registry_mcp` (`entity_registry/registry_mcp.py`) — one tool per `registry` subcommand, registered per-campaign in `.mcp.json` (auto-added by `configure_mcp` when `docs/entity_registry.yaml` exists) — so a Claude session gets the CLI's full surface and ordering rules from the tool listing instead of re-deriving them each session.

**Consumers auto-adopt it when present:**
- `facts_to_state` and `synthesise_world_state`/`synthesise_facts`/`synthesise_polish` take `--registry` (an explicit dir/file wins; omit to auto-discover `docs/entity_registry.yaml` from the CWD). It supersedes the deprecated `--aliases`/`--known-names`, and errors if an explicit `--registry` is combined with them. The registry supplies **aliases only** — `--inventory` is separate human-authored module-canon grounding and is never substituted by it.
- The render CLIs (`distill`, `party`, `sd_narrate`, `scene_extract`, `campaign_state`, `planning`) call `load_alias_map(dossier_dir, registry_path=…)`: a resolved registry **replaces** the `docs/npcs/` dossier scan (via `find_alias_registry`, which prints an adoption notice so a partial registry never silently drops hand-curated dossier aliases).
- `planning --build-dossiers` seeds new dossiers' `aliases:` frontmatter from the registry.

**Building one:** there is no `import-source`. Produce a typed module inventory with the `gm-module-inventory` skill (published module → `docs/background/<module>-inventory.md`), then `registry import-inventory`. The `import-*` verbs fold the legacy stores in; `check` reports grouping drift + fuzzy near-dups for GM review.

### Retrieval/render separation (RLM)

Render pipelines (`prep`, `sd_narrate`, `planning`) must **not** consume raw `rpg_retriever` output. They consume a human-approved `docs/dossier_proposal.md` file instead. Retrieval is a scope decision; rendering is a prose decision; the proposal is the human checkpoint between them.

A CI test (`tests/test_retrieve_render_isolation.py`) fails if any function body contains both a retrieval call (`retrieve`, `search_hierarchical`, `rpg_search`, …) and a render call (`stream_api`, `call_api`). Don't bypass this — fix the structure.

See `docs/rlm/rlm_pipeline.md` for the proposal workflow and MCP tools.

### LLM renders, humans decide

Per the global rule in `~/.claude/CLAUDE.md`: scope/ordering/attribution are precision decisions and need a human checkpoint; rendering verified structure into prose is what LLMs do well. When designing new pipelines in this repo, the pattern is **LLM extracts → human reviews → LLM renders inside that structure** — never **LLM extracts → LLM structures → LLM renders**.

Concrete examples already in the codebase:
- `party` outputs candidate arc-score events with quoted triggers, never current values or thresholds
- `planning --build-dossiers` writes per-NPC files for human review before `--synthesize`
- The 4-stage `session_doc` pipeline (`docs/cli/session_doc_pipeline.md`) inserts a human review after each LLM pass
- `dossier_proposer` writes a proposal file; the GM approves it before render pipelines consume it

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

For the OpenRouter backend (ensemble workflow synthesis/extraction), `pip install
openai` and set `OPENROUTER_API_KEY` in the environment. OpenRouter is reached
only through `campaignlib/api` (`make_client(backend="openrouter")`); select it on
a CLI with `--backend openrouter --model <openrouter-id>`, or via the
`CG_BACKEND=openrouter` env var.

### The package MUST be editable-installed into the server's venv

The web UI runs every pipeline as a subprocess via `console_script(name)`
(`server/subprocess_runner.py`), which resolves to
`<server's python dir>/<name>` — an installed `pyproject.toml [project.scripts]`
console script, **not** a `$PATH` lookup or a repo-relative `*.py`. So after any
source-tree restructure, a `[project.scripts]` change, or a fresh venv you MUST
(re)install:

```bash
# venv is uv-managed (its python has no pip). Install into the SAME venv the
# server runs under — verify with: cat /proc/<server-pid>/environ | tr '\0' '\n' | grep VIRTUAL_ENV
uv pip install -e . --python "$VIRTUAL_ENV/bin/python"   # e.g. ~/.venv
```

**Symptom when missing:** a `/run/*` action fails and the Session Doc Editor
shows `Stream error — check terminal.` — the subprocess tried to spawn a
non-existent `<venv>/bin/sd_narrate` (or `scene_extract`, `enhance_summary`, …).
The server itself still boots fine because `startup` puts the repo on
`PYTHONPATH`, so imports resolve without the install — only the console scripts
are missing. **No server restart is needed** after installing; `console_script()`
resolves the path per-request.

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
`specs/006-state-projection-service/plan.md` (State-Projection Rendering as
its own service — the #213 projection engine (`event_spine`,
`thread_registry`, `grounding_sections`) becomes a service with its own
strict document `<config>/projections.yaml` (modelled in
`campaignlib/projection_config.py`, so both the CLIs and the service can read
it — `test_layering.py` forbids the engine importing `server/`), its own
output namespace `docs/projections/`, and a UI limited to section staleness +
per-section rebuild. Four services, not three: `ensemble_batch` +
`facts_to_state` are a shared **Extraction & State** service; **Per-Tool
Rendering**, **Dossier Synthesis** and **State Projection** are three sibling
renderers, each writing to its own subdirectory so they can run in any order
without clobbering each other. "Service" is the canonical term; "path" is
reserved for prose. `ensemble.yaml` is deliberately NOT split (research D11);
`synthesise_world_state` stays Dossier Synthesis's engine and State
Projection execs it as a declared dependency (D12); the corpus glob stays
`required=True` with no config default and a test asserts the field's absence
(D6, Constitution X); pre-move drafts are never moved or deleted — a renderer
refuses until the GM clears them (FR-007b). `research.md` D1–D14 holds the
codebase survey; extend it rather than re-deriving.
Predecessors: `specs/005-ui-batch-selection/plan.md` (batch as a selection
value; `SelectionPanel.vue`), `specs/003-model-selection-resolution/` (the
`resolve_selection` seam this service's `selection` field plugs into),
`specs/002-ensemble-run-observability/plan.md` (run streaming + abort).)
<!-- SPECKIT END -->
