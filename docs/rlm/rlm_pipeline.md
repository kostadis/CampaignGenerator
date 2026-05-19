# RLM pipeline — rpglib + pdf-translators + MemPalace

CampaignGenerator integrates with three external tools to give the AI and the GM a searchable, local-first RPG knowledge base:

| Tool | Role |
|---|---|
| **rpglib** (`~/src/mytools/rpg-lib/`) | 14K+ PDFs indexed in `rpg_library.db`. Source of book-level discovery and metadata. |
| **pdf-translators** (`~/src/mytools/pdf-translators/`) | Converts a PDF into structured 5etools JSON. Human review in `adventure_editor` / `toc_editor` / `monster_editor`. |
| **MemPalace** (`~/src/mempalace/` or a sibling worktree) | Verbatim-memory palace with hierarchical retrieval (`mempalace_search_hierarchical`). Source of prose hits + bestiary stat blocks. |

## Tiered retrieval

`python rpg_retriever.py "fey forest encounter mid-level 5e"` returns a single ranked list using a `kind` discriminator, with a `cost` discriminator on candidates:

- `kind: "drawer"` — MemPalace hit (verbatim prose / table) joined with rpglib metadata.
- `kind: "statblock"` — MemPalace hit in `wing_bestiary`. Compact creature reference.
- `kind: "candidate"`, `cost: "cheap"` — entity in the canonical 5etools tree (`fivetools_catalog`) that's not yet in the palace. Carries a `fivetools_ingest.py --filter` one-liner.
- `kind: "candidate"`, `cost: "expensive"` — PDF in rpg-library with no canonical-JSON equivalent. Carries a `pdf_to_5etools_v2.py convert` + `fivetools_ingest.py` command pair plus the `(book_id, relative_path, product_id)` identifier triple.

Hard tier order: drawer/statblock > cheap > expensive. No score normalization across sources. See `rlm_architecture.md` §9 for the canonical contract.

Writes go through **MemPalace's MCP server** (`mempalace_client.py`); reads from rpg-library go through its HTTP API (stdlib `urllib`); reads from the canonical 5etools tree go through `fivetools_catalog` in-process. No CG module opens MemPalace's ChromaDB directly.

## Ingest flow (explicit user step, never automatic)

```bash
# 1. Convert (runs pdf-translators; review the JSON in adventure_editor afterwards)
python convert_book.py /mnt/g/path/to/book.pdf

# 2. Ingest the approved JSON into MemPalace
python fivetools_ingest.py /mnt/g/path/to/book.json --book-id 7421
```

- Stat blocks route to `wing_bestiary/room_<sanitized-book-title>`.
- Prose / section / inset / quote / table route to `wing_rpglib/room_<sanitized-book-title>`.
- Every drawer carries `book_id`, `display_title`, `publisher`, `game_system`, `product_type`, `tags`, `series`, `section_path`, `page`, `entry_type`, `source_filepath` in its metadata so retrieval filters stay a single Chroma query.
- Ingest is idempotent via `(size, mtime)` sidecar state in `<json_dir>/.fivetools_ingest/`. `--force` bypasses; `--dry-run` prints the plan without writing.

## Retrieval/render separation (required)

Render pipelines (`prep.py`, `session_doc.py`, `planning.py`) must **not** consume raw `rpg_retriever` output — they consume a human-approved `docs/dossier_proposal.md` file instead.

```bash
# 1. Produce a candidates file from a retrieval query
python dossier_proposer.py "party arrives at Icespire Hold"
#    → <campaign-dir>/docs/dossier_proposal.md

# 2. Review the file. Delete / reorder / edit candidates. Change the
#    header line
#        > **Status:** candidates only. Review, delete, reorder, and edit…
#    to something like
#        > **Status:** approved by Kostadis on 2026-04-24.

# 3. Render pipelines consume it:
python prep.py --campaign-dir . --require-proposal --beat "The party enters Icespire Hold"
python session_doc.py recap.md --output session-doc.md --campaign-dir . --require-proposal …
python planning.py --npc docs/npcs/*.md --output docs/planning.md --campaign-dir . --require-proposal
```

Without `--require-proposal`, the scripts still auto-attach an approved proposal when present (via `proposal_loader.attach_proposal_to_documents`) so the proposal's excerpts flow into the user prompt as grounding alongside `world_state.md`, `campaign_state.md`, `party.md`.

**Why this matters** (per the global LLM-pipeline rule in `~/.claude/CLAUDE.md`): retrieval is a scope decision; rendering is a prose decision. The proposal file is the human checkpoint between them. A CI test (`tests/test_retrieve_render_isolation.py`) walks every `.py` module in the repo and fails if any function body contains both a retrieval call (`retrieve`, `search_hierarchical`, `rpg_search`, …) and a render call (`stream_api`, `call_api`).

## MCP tools (exposed by `mcp_server.py`)

| Tool | Purpose |
|---|---|
| `rpg_search` | Run `rpg_retriever.retrieve`; returns tiered JSON (drawer / statblock / cost-tagged candidate). Args: `query`, `k_cheap`, `k_expensive`, `include_cheap`, `include_expensive`, `source`, `book_id`, `file_path`, `filter`, `palace`. Three modes through one tool: search (with `query`), scoped search (`query` + `source` or `book_id`), pin (`file_path`+`filter` or `book_id`). No side effects. |
| `propose_dossier` | Run `rpg_search` and write `docs/dossier_proposal.md`. Cheap and expensive ingest blocks are formatted differently so cost is legible at GM-review time. Returns a status string. |
| `suggest_conversion` | Build the `pdf_to_5etools_v2.py convert` + `fivetools_ingest.py` command pair for a specific unconverted book (by id or filepath). `product_type` maps to v2's `--type` / `--monsters-only`. |

None of these tools calls Claude. They are retrieval / slotting / command-building only.

## Palace + rpglib path resolution

All CLI scripts accept explicit flags, with env var fallbacks:

- `--palace` / `MEMPALACE_PALACE_PATH` — passed through to `mempalace-mcp`.
- `--rpglib-db` / `RPGLIB_DB` — path to `rpg_library.db`.
- `--campaign-dir` / `CAMPAIGN_DIR` — campaign workspace root. Default: CWD for CLIs, the config file's parent directory for `prep.py`, the recap's parent for `session_doc.py`.

The MCP server picks up `MEMPALACE_PALACE_PATH` / `RPGLIB_DB` from the environment and from `config.yaml` keys `mempalace.palace` / `rpglib_db`.
