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
- Ingest is idempotent via `(size, mtime)` sidecar state in `<json_dir>/.fivetools_ingest/`. Sidecars are keyed on `(json_path, palace, filter)` so the same JSON ingested into multiple palaces, or with different filters, gets independent records. `--force` bypasses; `--dry-run` prints the plan without writing.

## Per-campaign ingest manifest (recovery + reproducibility)

The MemPalace is a derived store; the *list* of which slices belong in a given campaign is the curation work that's expensive to recreate. Record it as `ingest_manifest.yaml` checked into the campaign workspace and replay it with `apply_ingest_manifest.py`:

```yaml
# <campaign-dir>/ingest_manifest.yaml
palace: abyss                                 # optional; falls back to config.yaml mempalace.palace

ingests:
  - source: ~/src/5etools-kostadis/data/adventure/adventure-oota.json
    filter: "chapter=0"
    note: "Velkynvelve opening — session 1 grounding"
  - source: ~/src/5etools-kostadis/data/bestiary/bestiary-oota.json
    filter: "name=Drow Priestess of Lolth"
  - source: ./converted/icespire-homebrew.json
    book_id: 7421
    note: "Homebrew faction, converted 2026-04-20"
```

Each entry maps 1:1 to a `fivetools_ingest.py` invocation. Run:

```bash
python apply_ingest_manifest.py            # replay every entry (idempotent)
python apply_ingest_manifest.py --status   # report never-run / ingested / stale / missing-source per entry
python apply_ingest_manifest.py --dry-run  # print the fivetools_ingest.py commands without executing
python apply_ingest_manifest.py --only 1,3 # 1-based entry selection
```

**Why this exists:** if `~/.mempalace/palaces/<campaign>/` is lost (disk failure, accidental wipe, ChromaDB corruption), the sidecars alone aren't enough to rebuild — they live next to the *source* JSON, not the palace, and historically didn't record which palace they belonged to. The YAML manifest is the authoritative recipe; sidecars are a local cache. Treat the manifest as your campaign's bill of materials and commit additions as you make them.

## Per-campaign navigation scope (refs.yaml + 5etools MCP)

The palace is the **retrieval** layer (semantic drawer search, grounding for render pipelines). It is not built for "read the whole adventure" or "summarise this book without burning tokens on mechanics." For those use cases the campaign also exposes a **navigation** layer: a per-campaign instance of the `5etools-mcp` server, scoped to exactly the WotC content + purchased PDFs + homebrew this campaign uses.

### New campaign setup

```bash
# 1. Create refs.yaml in your campaign directory (see format below)
#    At minimum: canonical: all  (no refs: block needed to start)

# 2. Generate refs.local.yaml with detected defaults, then edit paths to match your machine
python launch_5etools_mcp.py --campaign-dir . --init-local

# 3. Verify what the resolver sees before launching
python launch_5etools_mcp.py --campaign-dir . --status

# 4. Launch the MCP server
python launch_5etools_mcp.py --campaign-dir .
```

`refs.yaml` is git-tracked and lives at the campaign root alongside `config.yaml`. `refs.local.yaml` is git-ignored (paths differ per machine). You need `refs.yaml` to exist before running `--init-local`.

Scope is declared in two sibling files (see [`refs_yaml_reference.md`](refs_yaml_reference.md) for the full field reference):

```yaml
# <campaign-dir>/refs.yaml — git-tracked, portable across machines
canonical: all                    # or: [OotA, MM, XPHB] for explicit whitelist
canonical_exclude:                # only meaningful when canonical: all
  - VRGtR
  - RotFM

refs:
  - rpglib: "DriveThru/Wizards of the Coast/Adventures/T14.pdf"
    book_id: 7421
    note: "Tales from the Yawning Portal"
  - homebrew_private: "cross_campaign_canon/setting_bible/"
  - homebrew_private: "1e_modules/desert_of_desolation.json"
```

```yaml
# <campaign-dir>/refs.local.yaml — git-ignored, per-machine
roots:
  fivetools_data: ~/src/5etools-kostadis/data/
  rpg_library: /mnt/g/                                  # varies per machine
  homebrew_private: ~/src/homebrew-private/
```

Authoring a `rpglib:` ref:

```bash
# Find a book in your rpg-lib catalog (offline — reads rpg_library.db directly)
python query_rpg_lib.py "tales yawning portal"

# Emit a paste-ready refs.yaml block for one match
python query_rpg_lib.py --book-id 7421
```

Launching the per-campaign MCP:

```bash
python launch_5etools_mcp.py --campaign-dir .            # build runtime tree + exec MCP
python launch_5etools_mcp.py --campaign-dir . --status   # show resolved scope, no launch
python launch_5etools_mcp.py --campaign-dir . --dry-run  # show planned DATA_DIRS, no launch
python launch_5etools_mcp.py --campaign-dir . --init-local  # write a starter refs.local.yaml
```

The launcher builds `~/.5etools-mcp-runtime/<campaign>/` containing a (possibly filtered) view of canonical 5etools data plus a generated `homebrew/` tree for the campaign's refs, then `exec`s the MCP server with `DATA_DIRS` set to those two roots. Idempotent via a sha256 sidecar over `refs.yaml + refs.local.yaml` — repeated launches with unchanged refs reuse the tree.

**Layering:** palace = surgical drawer-level retrieval (grounding for render pipelines); 5etools MCP = bulk-read navigation (read whole adventures, summarise books, look up monsters by name). They complement each other — the palace can be empty for a brand-new campaign and the MCP still gives Claude the full WotC+purchased+homebrew catalog to work from.

**No runtime dependency on rpg-lib.** Once `refs.yaml` is authored, the launcher and MCP run fully offline — they don't talk to rpg-lib's HTTP service or touch its DB. Authoring (via `query_rpg_lib.py`) does need the DB read-only, but that's a one-time step per book added to the campaign.

## Retrieval/render separation (required)

Render pipelines (`prep.py`, `sd_plan.py`, `planning.py`) must **not** consume raw `rpg_retriever` output — they consume a human-approved `docs/dossier_proposal.md` file instead.

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
python sd_plan.py --scene-extractions scene_extractions/ --characters "…" --campaign-dir . --require-proposal …
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
- `--campaign-dir` / `CAMPAIGN_DIR` — campaign workspace root. Default: CWD for CLIs, the config file's parent directory for `prep.py`, the scene_extractions parent for `sd_plan.py`.

The MCP server picks up `MEMPALACE_PALACE_PATH` / `RPGLIB_DB` from the environment and from `config.yaml` keys `mempalace.palace` / `rpglib_db`.
