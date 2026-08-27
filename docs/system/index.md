# The Campaign Toolchain — System Wiki

> **Why this exists.** The campaign-prep system is now ~120K lines spread across
> five repos that talk to each other through files, subprocesses, and HTTP. No
> single repo's `CLAUDE.md` shows the *whole* shape. This wiki is the map you
> come back to when you've forgotten how the pieces fit. It links out to each
> repo's deep docs rather than duplicating them.

**Audience:** you (the GM/author), six months from now, trying to remember
where a thing lives and what calls what.

---

## The 30-second picture

You run **CampaignGenerator** (CG). Everything else exists to feed it or to be
called by it.

```
                          ┌──────────────────────────────────────────────┐
                          │              YOU (GM / author)               │
                          │   CLI scripts · Web UI · Claude Code (MCP)    │
                          └───────────────────┬──────────────────────────┘
                                              │
                 ┌────────────────────────────▼────────────────────────────┐
                 │                  CampaignGenerator                       │
                 │  the orchestrator — assembles docs, calls LLMs, runs     │
                 │  the prep / post-session / RLM pipelines.                │
                 │  Markdown-on-disk is the source of truth.                │
                 │  ALL LLM calls funnel through campaignlib/api/.          │
                 └──┬───────────┬───────────┬───────────┬──────────┬───────┘
                    │           │           │           │          │
        LLM backends│   memory  │  content  │  per-camp │   campaign data
        (pick one)  │  retrieval│  factory  │  reference│   (read/write)
                    │           │           │           │          │
        ┌───────────▼──┐  ┌─────▼──────┐  (data,    ┌───▼─────┐  ┌─▼──────────────┐
        │ Anthropic API│  │ MemPalace  │   not code) │ 5etools │  │ campaign        │
        │ DGX / vLLM   │  │ (verbatim  │  ┌────────┐ │  MCP    │  │ workspace       │
        │ Claude Code  │  │  memory +  │  │ mytools│ │ (node,  │  │ docs/ voice/    │
        │ Codex CLI    │  │            │  │        │ │         │  │                  │
        └──────┬───────┘  │  semantic) │  │ rpg-lib│ │ scoped  │  │ summaries/      │
               │          └─────┬──────┘  │ + pdf- │ │ by      │  │ refs.yaml       │
         dgxlib│registry        │ backend │ trans- │ │refs.yaml)│ └─────────────────┘
        (shared w/ mytools)     │         │ lators │ └─────────┘
                                ▼         └───┬────┘        ▲
                          ┌───────────┐       │            │
                          │turbovecdb │       │  produces  │
                          │  OR Chroma│       └──> 5etools JSON files
                          │ (vec DB)  │            + rpg_library.db
                          └───────────┘            (machine-global, shared)
```

**The one sentence per box:**

| Box | What it is | This wiki page |
|---|---|---|
| **CampaignGenerator** | The hub. CLI + Web UI + MCP server; runs every pipeline; the only thing you launch directly. | [component-campaigngenerator](component-campaigngenerator.md) |
| **MemPalace** | Local-first **verbatim** memory with semantic + hierarchical retrieval. CG's "what happened / what's canon" lookup. | [component-mempalace](component-mempalace.md) |
| **turbovecdb** | Embedded vector DB that can sit *behind* MemPalace as its backend (alternative to ChromaDB). CG never touches it directly. | [component-turbovecdb](component-turbovecdb.md) |
| **mytools rpg-lib + pdf-translators** | The content factory: turns PDFs into 5etools JSON and an enriched library index. Connected to CG by **data, not code**. | [component-rpglib](component-rpglib.md) |
| **Campaign workspace + 5etools trees** | The data layer: per-campaign `docs/`/`voice/`/`refs.yaml` vs. machine-global 5etools data, palace, library DB. | [component-campaign-data](component-campaign-data.md) |
| **dgxlib** | Shared library (in `dgx-fun`) owning per-model DGX behavior. Used by both CG and mytools for local-LLM calls. | (cross-cutting — see backends below) |

---

## The mental model that makes it click

Three ideas explain almost every design choice in the system:

1. **Markdown/YAML on disk is the source of truth, not any database.** The LLM
   is a renderer between human checkpoints — it drafts; you review; the reviewed
   file feeds the next step. (This is the rule in the root `CLAUDE.md` and
   `~/.claude/CLAUDE.md`.) Databases (palace, vector DB, library DB) are
   *indexes over* or *caches of* that truth, never the truth itself.

2. **Retrieval and rendering are separated by a human checkpoint.** Deciding
   *what content is in scope* is a precision decision (a human approves
   `docs/dossier_proposal.md`); turning that approved scope into prose is what
   the LLM does. A CI test fails if one function both retrieves and renders.
   See [flow-rlm-retrieval](flow-rlm-retrieval.md).

3. **Every external thing is reached through exactly one seam.** All Anthropic
   calls go through `campaignlib/api/`. All MemPalace I/O goes through
   `pipelines/rlm/mempalace_client.py`. All DGX per-model behavior comes from `dgxlib`. When
   you need to change how CG talks to X, there is one file to open.

---

## How data flows (the four pipelines)

The system has four top-level flows. Each has its own page with the file-by-file sequence.

| Flow | One line | Page |
|---|---|---|
| **Session prep** | Grounding docs (+ approved dossiers) → encounter/beat notes for the next session. | [flow-session-prep](flow-session-prep.md) |
| **Post-session** | Zoom `.vtt` → summary → scenes → per-character narration → assembled session doc. | [flow-post-session](flow-post-session.md) |
| **Ensemble → grounding docs** | Chapters → extract-once on Spark → human-reviewed dossiers → API synthesis → the four grounding docs. The path you take *when you have a DGX Spark* (~10× cheaper). | [flow-ensemble](flow-ensemble.md) |
| **RLM retrieval** | A query → three-pile retrieval (palace + 5etools + rpglib) → human-approved proposal → render. | [flow-rlm-retrieval](flow-rlm-retrieval.md) |

The four grounding docs (`world_state.md` / `campaign_state.md` / `party.md` /
`planning.md`) have **two refresh paths, gated on hardware** — not old vs new.
**With a DGX Spark**, the **ensemble** flow extracts once locally (≈free) and
spends the API only on synthesis. **Without local GPU**, the fallback is the
per-tool API path where each tool re-extracts from the chapter bible
([`docs/cli/grounding_docs.md`](../cli/grounding_docs.md)).

---

## The integration seams (who calls whom, and how)

This is the table to consult when something breaks at a boundary.

| From → To | Mechanism | Entry file(s) |
|---|---|---|
| CG → **Anthropic API** | Python `import anthropic`, retry loop | `campaignlib/api/client.py`, `api/backends.py` |
| CG → **DGX / vLLM** | HTTP, OpenAI-compatible client; per-model knobs from dgxlib | `campaignlib/api/backends.py` (`_OpenAICompatClient`) + `dgxlib.resolve_model_config` |
| CG → **Claude Code** (Pro/Max) | Subprocess, `claude` CLI headless (`CG_BACKEND=claude-code`) | `campaignlib/api/backends.py` (`_ClaudeCodeClient`) |
| CG → **Codex CLI** (ChatGPT subscription) | Isolated, ephemeral `codex exec`; saved login, stripped API-key variables, no tools or provider fallback (`CG_BACKEND=codex-cli`) | `campaignlib/api/codex_cli.py` (`_CodexCliClient`) |
| CG → **MemPalace** | Subprocess **stdio JSON-RPC** to `mempalace-mcp` | `pipelines/rlm/mempalace_client.py` (the *only* file that talks to it) |
| MemPalace → **turbovecdb / ChromaDB** | Python import; backend chosen by `MEMPALACE_BACKEND` | `mempalace/backends/{turbovec,chroma}.py` |
| CG → **5etools JSON** | Filesystem read (mtime-cached index) | `pipelines/rlm/fivetools_catalog.py`, `pipelines/content_ingest/fivetools_ingest.py` |
| CG → **5etools MCP** (per campaign) | Builds a scoped symlink farm, `exec`s a Node MCP server | `pipelines/rlm/launch_5etools_mcp.py` + `pipelines/rlm/resolve_refs.py`; scope from `refs.yaml` |
| **Claude Code → CG** | FastMCP **stdio** server (read docs, write `notes/` only) | `pipelines/rlm/mcp_server.py` (registered via `.mcp.json`) |
| CG ← **mytools** | **Data only** — consumes 5etools JSON + `rpg_library.db` metadata | `pipelines/content_ingest/fivetools_ingest.py`, `pipelines/content_ingest/convert_book.py` (no code import) |
| CG + mytools → **dgxlib** | Shared installed package (`pip install -e ~/src/dgx`) | `dgxlib` (in `dgx-fun`) |

> **Note the asymmetries that bite:** MemPalace is reached *only* through
> `pipelines/rlm/mempalace_client.py`; turbovecdb is *never* reached by CG directly (always
> behind MemPalace); mytools and CG share **no code** — only files on disk.

---

## Where state lives (local vs. global)

The single most confusing thing about this system is that some state is
*per-campaign* and some is *machine-wide and shared*. Getting this wrong is how
you end up re-ingesting the same book five times.

| Per-campaign (in the workspace dir) | Machine-global (shared by all campaigns) |
|---|---|
| `docs/*.md` (world_state, campaign_state, planning, party) | `~/src/5etools-kostadis/data/` — canonical 5etools JSON |
| `voice/`, `examples/`, `summaries/{session}/` | `~/.mempalace/palaces/<name>/` — one palace per campaign, under the shared root |
| `refs.yaml` (+ git-ignored `refs.local.yaml`) | `~/src/mytools/rpg-lib/rpg_library.db` — the enriched PDF index |
| `config.yaml`, `ui_config.yaml`, `.mcp.json` | `~/src/homebrew-private/` — shared homebrew JSON |
| `logs/`, `notes/` | `~/src/5etools-img/` — image assets; `dgxlib` model registry |

Full breakdown: [component-campaign-data](component-campaign-data.md).

---

## Where to read deeper (existing docs, by topic)

This wiki is a *map*. The territory is documented in each repo:

**CampaignGenerator**
- [`docs/core/architecture.md`](../core/architecture.md) — CG-internal layers & flows (start here for CG)
- [`docs/core/configuration.md`](../core/configuration.md) — config.yaml / platform.yaml / per-service config resolution
- [`docs/cli/cli_tools.md`](../cli/cli_tools.md) — per-script invocations & flags
- [`docs/cli/session_doc_pipeline.md`](../cli/session_doc_pipeline.md) — post-session deep dive
- [`docs/cli/ensemble_workflow.md`](../cli/ensemble_workflow.md) · [`ensemble_extraction.md`](../cli/ensemble_extraction.md) — ensemble grounding-doc generation
- [`docs/rlm/rlm_architecture.md`](../rlm/rlm_architecture.md) · [`rlm_pipeline.md`](../rlm/rlm_pipeline.md) · [`retrieval_architecture.md`](../rlm/retrieval_architecture.md)
- [`docs/rlm/refs_yaml_reference.md`](../rlm/refs_yaml_reference.md) — refs.yaml field reference
- [`docs/web/web_ui.md`](../web/web_ui.md) — Web UI

**Other repos** (outside this checkout)
- `~/src/mempalace/` — `README.md`, `CLAUDE.md`, `backends/base.py` (RFC 001 backend contract)
- `~/src/turbovecdb/docs/` — `ARCHITECTURE.md`, `core/data-model.md`, `mempalace-backend-gaps.md`
- `~/src/mytools/rpg-lib/CLAUDE.md` and `~/src/mytools/pdf-translators/CLAUDE.md`
- `~/src/dgx/dgxlib/` — `README.md`, `ARCHITECTURE.md`

---

*Generated 2026-06-19 from a structural sweep of all five repos. Treat the
file/line references as a starting point — verify against the code before
relying on a specific detail, since the system moves.*
