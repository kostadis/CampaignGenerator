# Component: MemPalace

> Local-first **verbatim** memory with semantic + hierarchical retrieval. CG's
> "what actually happened / what's canon" lookup. [↑ index](index.md)

**Repo:** `~/src/mempalace` · **Deep docs:** `mempalace/README.md`, `mempalace/CLAUDE.md`, `mempalace/backends/base.py` (RFC 001)

---

## What it is

MemPalace stores text **verbatim** — no summarization, no paraphrase — and
retrieves it by semantic search and by a hierarchical walk. Nothing leaves the
machine unless you opt in. The retrieval layer is **pluggable**: ChromaDB by
default, turbovecdb optionally.

Why CG uses it: it's the long-term memory of the campaign. Session summaries,
adventure prose, and ingested 5etools entities live in a palace, and the RLM
pipeline searches it for grounding content. It is the **first of the three
retrieval piles** (palace · 5etools · rpglib).

---

## The hierarchy (the vocabulary you'll see in logs)

```
Palace                      one per campaign, at ~/.mempalace/palaces/<name>/
  └─ Wing                   broad category (a person, a project, a topic)
        └─ Room             a time/topic grouping within a wing (a day, a session)
              └─ Drawer     a verbatim content chunk — the original exact words
                    └─ Closet   a lossy AAAK index line pointing at drawers
```

| Term | Meaning |
|---|---|
| **Drawer** | The unit of verbatim storage. Exact words + embedding. |
| **Closet** | A compressed (AAAK) index line that summarizes and points at drawers. Lives in the `mempalace_closets` collection. |
| **AAAK** | The structured symbolic index format (emotion codes, flags, entities, quotes) — LLM-readable without a decoder. |
| **Tunnel** | An explicit cross-wing link (a domain relationship). |
| **Dirty flag** | Per-room/wing marker that the index needs rebuilding after closet changes. |
| **Wake-up layers** | L0–L3 hierarchical context retrieval (facts → rooms → drawers). |
| **Knowledge graph** | A separate SQLite temporal entity-relationship graph (`knowledge_graph.sqlite3`), present for all backends. |

---

## How it's consumed

Three surfaces; **CG uses the MCP one**:

| Surface | Entry | Who uses it |
|---|---|---|
| **MCP server** (`mempalace-mcp`, stdio JSON-RPC) | 31 tools: `search_hierarchical`, `add_drawer`, `update_drawer`, `kg_query`, … | **CampaignGenerator**, via `pipelines/rlm/mempalace_client.py` |
| Python import | `get_collection`, `search_memories`, `KnowledgeGraph` | direct library use |
| CLI | `mempalace mine / search / wake-up` | scripting, batch |

> **The seam from CG:** `~/src/CampaignGenerator/pipelines/rlm/mempalace_client.py` is the
> *only* file that talks to MemPalace. It spawns the `mempalace-mcp` subprocess
> and sends JSON-RPC. `pipelines/rlm/rpg_retriever.py` and `pipelines/rlm/mcp_server.py` call *it*, never
> MemPalace directly. Palace path resolves env → config → default
> (`~/.mempalace/palaces/<name>`). If MemPalace isn't installed, CG degrades
> gracefully (that pile just returns nothing).

---

## The pluggable backend (RFC 001)

The contract is two abstract classes in `mempalace/backends/base.py`:

- **`BaseBackend`** — palace-level factory: `get_collection()`, `close()`, `health()`.
- **`BaseCollection`** — per-collection: writes (`add`/`upsert`/`delete`/`update`), reads (`query`/`get` → `QueryResult`/`GetResult`), `count`/`health`.

**Available backends:**

| Backend | Storage | Selected by | File |
|---|---|---|---|
| **ChromaDB** (default) | palace root: `chroma.sqlite3` + index dirs (PersistentClient) | nothing — it's the default | `backends/chroma.py` |
| **turbovecdb** (optional) | `<palace>/turbovec/` (4-bit ANN + SQLite) | `MEMPALACE_BACKEND=turbovec`; `pip install mempalace[turbovec]` | `backends/turbovec.py` |

**Selection priority** (`backends/registry.py`): explicit flag → per-palace
config → `MEMPALACE_BACKEND` env → auto-detect on-disk artifacts → default
(`chroma`).

The turbovecdb seam is detailed on its own page: [component-turbovecdb](component-turbovecdb.md).

---

## On-disk state

```
~/.mempalace/
├─ config.json                        global config & aliases
├─ entity_registry.json               machine-global entity registry
└─ palaces/<campaign>/
   ├─ chroma.sqlite3 + index dirs      default backend, at palace root
   │     (or)  turbovec/               when MEMPALACE_BACKEND=turbovec
   ├─ knowledge_graph.sqlite3          SQLite temporal knowledge graph (all backends)
   └─ .mempalace/origin.json           corpus origin detection
```

Collections inside the palace: `mempalace_drawers` (verbatim content),
`mempalace_closets` (index summaries + embeddings), `mempalace_room_indices` and
`mempalace_wing_indices` (roll-ups), plus the KG.

---

## Where it sits in the flows

- **RLM retrieval** — pile #1. See [flow-rlm-retrieval](flow-rlm-retrieval.md).
- **Ingest** — `pipelines/content_ingest/fivetools_ingest.py` writes 5etools entities into palace drawers
  (with metadata snapshotted from `rpg_library.db`). See
  [component-campaign-data](component-campaign-data.md).
