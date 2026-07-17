# Component: mytools rpg-lib + pdf-translators

> The content factory. Turns PDFs into 5etools JSON and an enriched library
> index. Connected to CampaignGenerator by **data, not code**. [↑ index](index.md)

**Repo:** `~/src/mytools` (`rpg-lib/` and `pdf-translators/`) · **Deep docs:**
`mytools/rpg-lib/CLAUDE.md`, `mytools/pdf-translators/CLAUDE.md`

---

## What it is

Two cooperating toolsets in the `mytools` repo that *produce the raw material*
CampaignGenerator consumes:

- **`rpg-lib/`** — indexes a PDF library and enriches it with metadata
  (game system, product type, tags, series), serving it via REST + a Vue SPA +
  an MCP server. Output: `rpg_library.db`.
- **`pdf-translators/`** — converts a PDF adventure/book into **5etools JSON**
  (chapters, scenes, statblocks). Output: 5etools-format `.json`.

**Crucial:** CampaignGenerator does **not** import any of this. The connection
is entirely through files on disk (next section).

---

## rpg-lib pipeline

```
PDFs on disk
   │  pdf_indexer.py     scan folders, extract TOC/bookmarks/page counts
   ▼
rpg_library.db (SQLite)
   │  pdf_enricher.py    LLM classifies each book: game_system, product_type,
   ▼                     tags, series, description, level range
rpg_library.db (enriched)
   │  library_server.py  FastAPI + Vue SPA; /search, /nlq (Haiku query parser)
   │  library_mcp.py      MCP tools: search_books, get_book, find_books_by_tag, …
   ▼
(metadata consumed by CampaignGenerator at ingest time)
```

`pdf_enricher.py` is where the **LLM provider dispatch** lives:

```python
if args.provider == "dgx":
    import dgxlib as llm                  # shared package (github.com/kostadis/dgx-fun)
    endpoint = args.endpoint or llm.DEFAULT_ENDPOINT
    client   = llm.make_client(endpoint)  # local vLLM on the Spark
else:
    from lib import claudelib as llm       # Anthropic wrapper
    client   = llm.make_client()
```

Both providers expose the same `make_client` / `call_api` / `discover_model`
surface, so the rest of the script is provider-agnostic. `lib/claudelib.py` is
the Anthropic wrapper (extracted from CG originally); the old `lib/dgxlib.py` was
**deleted** and replaced by the shared `dgxlib` package — the same registry CG
uses for DGX per-model behavior. That shared library is the one genuine *code*
link between the mytools and CampaignGenerator worlds (both `pip install -e ~/src/dgx`).

---

## pdf-translators

The PDF → 5etools JSON converter. `pdf_to_5etools_v2.py` routes bookmarked
digital PDFs through a fast PyMuPDF path and everything else through Marker
(ML layout), chunks by TOC/headings, sends chunks to Claude, and assembles a
typed adventure model (`adventure_model.py`). `validate_adventure.py` checks the
output against official adventure patterns (a bad `{@tag}` reference renders as a
blank page in 5etools, so validation matters). A set of web UIs on ports
5100–5104 provide the human review/correction step: `app.py` (batch jobs, 5100),
`toc_editor` (5101), `toc_fixer` (5102), `monster_editor` (5103),
`adventure_editor` (5104).

> **Canonical path:** pdf-translators lives at `~/src/mytools/pdf-translators/`.
> Ignore any stale copies under `5etools-kostadis` / `5etools-src`.

---

## The seam to CampaignGenerator (data only)

CG reaches mytools' output through two on-disk artifacts:

| Artifact | Produced by | Consumed by CG | How |
|---|---|---|---|
| **5etools JSON files** | pdf-translators (`pdf_to_5etools_v2.py`) → land in the 5etools data/homebrew tree | `pipelines/rlm/fivetools_catalog.py` (name index), `pipelines/content_ingest/fivetools_ingest.py` (→ palace drawers) | filesystem |
| **`rpg_library.db` metadata** | rpg-lib (`pdf_enricher.py`) | `pipelines/content_ingest/fivetools_ingest.py` snapshots book metadata (id, title, publisher, system, tags, series, source filepath) into palace drawer metadata | SQLite read |

`pipelines/content_ingest/convert_book.py` in CG is a thin wrapper that calls pdf-translators as a
subprocess and then prints the exact `pipelines/content_ingest/fivetools_ingest.py` command to run next —
keeping the convert→review→ingest steps explicit (never automatic). See
[component-campaign-data](component-campaign-data.md) and [flow-rlm-retrieval](flow-rlm-retrieval.md).

```
   pdf-translators                rpg-lib
   PDF → 5etools JSON        PDF → rpg_library.db (enriched)
          │                          │
          └──────────┬───────────────┘
                     ▼   (files on disk — no code import)
          CampaignGenerator: pipelines/content_ingest/fivetools_ingest.py
                     ├─ 5etools JSON  → MemPalace drawers
                     └─ rpg_library.db metadata → drawer metadata
```
