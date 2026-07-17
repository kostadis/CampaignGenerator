# Flow: RLM retrieval

> A query → three-pile retrieval → human-approved proposal → render. The seam
> where MemPalace, 5etools, and the rpg library meet. [↑ index](index.md)

**Deep docs:** [`docs/rlm/rlm_architecture.md`](../rlm/rlm_architecture.md) ·
[`rlm_pipeline.md`](../rlm/rlm_pipeline.md) · [`retrieval_architecture.md`](../rlm/retrieval_architecture.md)

---

## The core principle

**Retrieval is a scope decision; rendering is a prose decision; a human
checkpoint sits between them.** Deciding *what content belongs* in a dossier is
precision work — so the pipeline writes a proposal file, you approve it, and only
then may a render pipeline consume it. A CI test
(`tests/test_retrieve_render_isolation.py`) fails if any single function both
retrieves and renders.

## The three piles

`pipelines/rlm/rpg_retriever.py` gathers candidates from three sources, each tagged by cost:

```
query (a beat / NPC / faction)
        │
pipelines/rlm/rpg_retriever.py --retrieve
        ├─ MemPalace drawers     via pipelines/rlm/mempalace_client.py (subprocess JSON-RPC)   → "drawer" hits
        ├─ 5etools JSON on disk  via pipelines/rlm/fivetools_catalog.py (mtime-cached index)   → "statblock" hits  (cheap)
        └─ rpglib PDFs           via pipelines/rlm/suggest_conversion.py                       → "candidate" hits  (expensive)
        ▼
tiered hits:  drawer | statblock | candidate(cheap=5etools | expensive=needs PDF conversion)
```

- **MemPalace** — semantic search over ingested campaign memory and adventure
  prose. ([component-mempalace](component-mempalace.md))
- **5etools JSON** — exact entity lookup over the canonical data tree; cheap,
  already on disk. ([component-campaign-data](component-campaign-data.md))
- **rpglib PDFs** — books not yet converted; surfaced as *expensive* candidates
  because using them requires a conversion step. ([component-rpglib](component-rpglib.md))

## The human checkpoint

```
pipelines/rlm/dossier_proposer.py  → docs/dossier_proposal.md   (Status banner: "candidates only")
        ▼  (you review, edit scope, change the banner to
        ▼   "> **Status:** approved by <name> on <date>.")
proposal_loader.is_approved() / require_approved_proposal()   ← the gate
        ▼  (approved)
render pipelines may now consume it:  pipelines/session_prep/prep.py · session_doc/sd_plan.py · pipelines/grounding/planning.py
```

The proposal carries a `> **Status:**` banner; `proposal_loader.is_approved()`
treats anything other than the default "candidates only" as approved.
`require_approved_proposal()` raises until then, so a render pipeline **refuses to
run** against an unapproved proposal. This is the choke point — one function, one
file.

## The ingest path (explicit, never automatic)

When a candidate comes from an unconverted PDF, you bring it into the system by
hand, in explicit steps:

```
pipelines/content_ingest/convert_book.py   (wraps pdf-translators)  →  5etools JSON
        ▼  (it prints the next command; you review)
pipelines/content_ingest/fivetools_ingest.py  →  MemPalace drawers
        │   - 5etools entities rendered via pipelines/content_ingest/fivetools_render.py
        │     (resolving _copy refs via pipelines/content_ingest/fivetools_copy.py)
        └─ rpg_library.db metadata snapshotted into drawer metadata
```

After ingest, that content becomes a cheap "drawer" hit on the next retrieval —
the library grows as you use it.

## Tools exposed over MCP

`pipelines/rlm/mcp_server.py` surfaces this to a Claude Code session as `rpg_search`,
`propose_dossier`, and `suggest_conversion` — but the same approval gate applies:
the MCP tools can *propose*, you still approve the file before anything renders.

## Related

- The memory pile: [component-mempalace](component-mempalace.md)
- The data piles: [component-campaign-data](component-campaign-data.md), [component-rpglib](component-rpglib.md)
- What consumes an approved proposal: [flow-session-prep](flow-session-prep.md)
