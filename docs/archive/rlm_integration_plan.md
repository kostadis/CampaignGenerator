> **STATUS: ARCHIVED — plan shipped.** All phases described here (Gates
> 0–3) are complete in the current codebase. Preserved for historical
> context on the design decisions and risk mitigations that shaped the
> final system. **For the current architecture, read
> [`docs/rlm/rlm_architecture.md`](../rlm/rlm_architecture.md). For a quick
> entry point, [`docs/rlm/rlm_pipeline.md`](../rlm/rlm_pipeline.md).**

---

# Plan — CampaignGenerator orchestrates rpglib + pdf-translators + MemPalace (MIT RLM pattern, two-repo split)

## Context

The work described here exists at the intersection of four tools you already have. Only the orchestration code is new:

| Tool | Location | Role |
|---|---|---|
| **rpglib** | `/home/kroussos/src/mytools/rpg-lib/` | Book-level discovery. 14,291 PDFs indexed in `rpg_library.db` (SQLite, 79 MB). 8,508 enriched via Claude Haiku with `game_system`, `product_type`, `tags`, `series`, `description`. 944K bookmarks extracted. MCP server (`library_mcp.py`) exposes `search_books`, `get_book`, `get_topic`, `get_related_books`, `list_filters`, `get_stats`, `find_books_by_tag`. NLQ engine (`nlq.py`) parses free-text queries. **Unchanged by this plan.** |
| **pdf-translators** | `/home/kroussos/src/5etools-kostadis/pdf-translators/` | PDF → structured 5etools JSON. PyMuPDF fast path + Marker (ML) for OCR. Claude (Haiku) renders prose inside extracted structure. Human review UIs: `toc_editor`, `toc_fixer`, `monster_editor`, `adventure_editor`. **Unchanged by this plan.** |
| **MemPalace** | `/home/kroussos/src/mempalace/` (branch `kostadis-dev`) | Verbatim-memory palace. Two in-tree miners (`miner.py` for files, `convo_miner.py` for chat). RFC 002 source-adapter plugin spec exists but no third-party adapters yet. **Gets one narrow, generic addition.** |
| **CampaignGenerator** | `/home/kroussos/src/CampaignGenerator/` | D&D session-prep orchestrator. Existing MCP server, Vue frontend, workspace model (config.yaml, grounding docs). **Gets all the RPG-specific orchestration.** |

### The architectural decision driving the shape of this plan

Two rules, answered up-front:

1. **The 5etools-JSON adapter lives in CampaignGenerator, not MemPalace.** MemPalace today understands exactly two data types (files, chats). Any new RPG-schema awareness belongs in the repo that actually cares about RPG content. Even though RFC 002 technically permits first-party adapters, the user has explicitly decided that MemPalace upstream will not absorb this — so it must live outside. CampaignGenerator writes into MemPalace via `tool_add_drawer` over MCP, exactly like any other MCP client.
2. **CampaignGenerator orchestrates the retrieval; MemPalace provides the retrieval primitive.** MemPalace gains one generic hierarchical-search capability (useful to *any* large palace). All RPG-specific glue, dossier-proposal artifacts, and pdf-translators awareness live in CampaignGenerator.

### Why this stack already respects the LLM-pipeline rule

Your global rule: **LLM extracts → human imposes structure → LLM renders inside structure.**

- **Marker** (in pdf-translators) extracts structure deterministically from PDF layout — no LLM.
- **Human** reviews structure via `toc_editor` / `toc_fixer` / `adventure_editor` — imposes correction where needed.
- **Claude** (in pdf-translators) renders prose inside the approved structure — bounded by the human-approved skeleton.
- **MemPalace** stores and retrieves the resulting JSON verbatim — no LLM in the ingest or index path.
- **CampaignGenerator** produces a `dossier_proposal.md` for human review before any render pipeline runs.

The rule is enforced by **API shape**: retrieval and render are separate MCP invocations, not separate function calls within one flow.

### What MIT's RLM pattern contributes

The paper describes hierarchical retrieval over multi-million-token corpora with sub-corpus pruning at each level. MemPalace has flat AAAK today — sufficient for chat-scale palaces, but weaker at pruning large collections before drawer-level search. The plan borrows RLM's **hierarchical pruning** idea while rejecting its **LLM-summarized intermediate levels** (which would violate verbatim storage and introduce drift).

**The insight:** MemPalace's existing leaf closets (`mempalace/dialect.py` + `palace.build_closet_lines`) are already a deterministic, rule-based compression of drawers. We can **deterministically aggregate** leaf closets into room-level and wing-level indices — giving hierarchical pruning with zero LLM involvement at index time. This is a generic property of MemPalace, so it lives in MemPalace.

---

## The two sub-plans

### Sub-plan A — MemPalace (narrow, generic)

Small, schema-agnostic. Makes any palace better at hierarchical retrieval.

**New files (in-tree):**
- `mempalace/recursive_indexer.py` — deterministic room + wing index aggregator. Pure function of leaves; idempotent. Runs under `mine_lock`. Dirty-flag pattern per room/wing so aggregation is batched, not per-drawer.
- `tests/test_recursive_indexer.py`
- `tests/test_search_hierarchical.py`
- `tests/benchmarks/hierarchical_aaak.json` — ~15 **generic** palace queries (research-note scale, chat-archive scale) to prove the hierarchical property, not RPG content. Load test fixture is synthetic or a chat palace.

**Modified (in-tree):**
- `mempalace/searcher.py` — add `search_within(query, wing_filters=None, room_filters=None, ids=None, ...)` primitive. Generic scoped search used as the leaf step of hierarchical descent.
- `mempalace/palace.py` — expose `get_room_indices_collection`, `get_wing_indices_collection`; schema bump for the two new collections; dirty-flag plumbing.
- `mempalace/dialect.py` — export the rank-bucketed projection helpers `recursive_indexer.py` reuses to preserve AAAK grammar at intermediate levels.
- `mempalace/mcp_server.py` — add `tool_search_hierarchical(query, wing_filter?, room_filter?, max_depth?, budget?)`. Returns wing → room → drawer path + drawer hits + citations. **No RPG awareness; no pointer-kind results.** Generic over any palace.
- `mempalace/layers.py` — optional Phase 3: wing-index-only retrieval path (`max_depth=0`) integrated into L1/L2 wake-up.

**Not added:**
- No 5etools miner. No pdf-translators knowledge. No rpglib client. No pointer-kind results. No dossier-proposal concept. No `suggest_conversion` tool. No campaign-generator awareness.

**Indices (new collections, non-breaking):**

| Layer | Collection | Content | Generation |
|---|---|---|---|
| Drawer | `mempalace_drawers` (existing) | Verbatim text | existing miners |
| Leaf closet | `mempalace_closets` (existing) | Per-file AAAK | `palace.build_closet_lines` |
| **Room index** (NEW) | `mempalace_room_indices` | Rank-bucketed projection of room's leaf closets | `recursive_indexer.py` |
| **Wing index** (NEW) | `mempalace_wing_indices` | Union + top-N of room indices | `recursive_indexer.py` |

Intermediate levels contain no new prose. They are arithmetic projections — frequency sorts, top-N selections, histograms. Drift-free, rebuildable from leaves at any time.

---

### Sub-plan B — CampaignGenerator (orchestration, RPG-specific)

Everything else. Lives alongside `prep.py`, `session_doc.py`, `planning.py`. Uses `campaignlib.py` patterns.

**New files:**
- `CampaignGenerator/rpg_retriever.py` — the orchestrator. Takes a query, calls rpglib MCP (`search_books` / `nlq_search`) for candidate book IDs, calls MemPalace MCP (`tool_search_hierarchical` + `tool_search`) for drawers within those candidates, produces the three-state result (drawer / pointer / statblock). **All RPG knowledge lives here.**
- `CampaignGenerator/fivetools_ingest.py` — CLI (`python fivetools_ingest.py adventure.json`). Reads a 5etools adventure JSON (validates via pdf-translators's `adventure_model.parse_document`), walks typed entries, calls MemPalace `tool_add_drawer` once per entry with wing/room/metadata. Stat blocks routed to `wing_bestiary/room_{source}`; prose drawers routed to `wing_rpglib/room_{sanitized_book_title}`.
- `CampaignGenerator/dossier_proposer.py` — produces `docs/dossier_proposal.md` in the campaign workspace: slot candidates (NPCs, locations, encounters, stat blocks) with drawer IDs + citations + raw excerpts, formatted for human review. Never renders.
- `CampaignGenerator/convert_book.py` — thin CLI wrapper around `pdf_to_5etools_v2.py`. After conversion, prints the exact `python fivetools_ingest.py <json>` command to run as the explicit next step. Does not auto-ingest. Does not auto-convert; user runs the conversion.
- `CampaignGenerator/suggest_conversion.py` — helper called by `rpg_retriever.py` when a hit is a pointer-kind result. Returns `{filepath, convert_command, ingest_command, estimated_cost_tokens}` for the AI to surface in a suggestion to the user. The user approves and runs the two commands.
- `CampaignGenerator/tests/benchmarks/rlm_benchmark_rpg.json` — ~15 **RPG-specific** queries (creature lookup, location lookup, adventure seeds, cross-book themes, stat blocks, rules lookup). This is the yardstick for CampaignGenerator's gates.

**Modified:**
- `CampaignGenerator/mcp_server.py` — add MCP tools: `rpg_search`, `propose_dossier`, `suggest_conversion`. Thin wrappers over the new modules above.
- `CampaignGenerator/prep.py`, `session_doc.py`, `planning.py` — grow a convention: when `docs/dossier_proposal.md` is present in the workspace, they consume it as a grounding doc (alongside `world_state.md`, `planning.md`, `party.md`). They **refuse to render from a raw `rpg_search` call** — only from an approved proposal file.
- `CampaignGenerator/CLAUDE.md` — document the rpglib → pdf-translators → MemPalace pipeline, the explicit-ingest convention, and the retrieval/render separation rule.

**CI grep:** zero call sites in CampaignGenerator where `rpg_search` / `propose_dossier` output co-locates with a render function in the same function body.

---

## Retrieval flow at query time

```
Query (from user, or from prep.py, etc.)
  │
  └─▶ CampaignGenerator/rpg_retriever.py
        │
        ├─▶ rpglib MCP (search_books / nlq_search)      [discovery]
        │     └─▶ candidate book IDs + metadata
        │
        ├─▶ MemPalace MCP (tool_search_hierarchical)    [retrieval, generic]
        │     └─▶ wing/room pruning + drawers within candidate rooms
        │
        └─▶ Assemble three-state result:
              { kind: "drawer",  ... verbatim prose or stat block ... }
              { kind: "pointer", ... book in rpglib but not ingested, convert-suggestion ... }
              { kind: "drawer",  ... from wing_bestiary ... }
```

### The three-state retrieval result

```
{
  query: "fey forest encounter for mid-level 5e",
  hits: [
    { kind: "drawer",
      source: "wing_rpglib/room_temple-of-elemental-evil/section-3",
      book_id: 7421, title: "...", page: 47, entry_type: "inset",
      drawer_text: "<verbatim prose>",
      citations: [...] },
    { kind: "pointer",
      source: "rpglib only — not converted",
      book_id: 11203, title: "...", publisher: "...", tags: [...],
      suggest_conversion: { filepath: "/mnt/g/...", convert_command: "python pdf_to_5etools_v2.py ...",
                            ingest_command: "python fivetools_ingest.py ..." } },
    { kind: "drawer",
      source: "wing_bestiary/room_temple-of-elemental-evil",
      entry_type: "statblock", name: "Bugbear Chieftain", cr: 3, ... }
  ]
}
```

---

## Ingest flow — explicit user step

Chosen: **explicit user step after conversion**. No filesystem watcher, no auto-queue.

```
1. User: `python convert_book.py /mnt/g/...Obojima.pdf`
     - Runs pdf_to_5etools_v2.py (Marker or fast path)
     - Produces adventure-obojima.json
     - Prints: "Review in adventure_editor, then run: python fivetools_ingest.py adventure-obojima.json"

2. User (reviews in adventure_editor / toc_editor / monster_editor as needed)

3. User: `python fivetools_ingest.py adventure-obojima.json`
     - Validates via adventure_model.parse_document
     - Walks typed entries
     - For each entry: calls MemPalace tool_add_drawer (via MCP) with
       wing + room + metadata + entry_type + page + section_path + rpglib metadata
     - Stat blocks → wing_bestiary/room_{source}; prose → wing_rpglib/room_{title}
     - No MemPalace code changes; uses only existing MCP surface
```

### Drawer metadata (written by `fivetools_ingest.py`, opaque to MemPalace)

- `book_id` (FK into `rpg_library.db`)
- `display_title`, `publisher`, `game_system`, `product_type`, `tags[]`, `series` (looked up from rpglib at ingest time)
- `section_name`, `section_path`
- `page`
- `entry_type` (`section` / `entries` / `inset` / `quote` / `table` / `statblock` / ...)
- `source_filepath` for audit

MemPalace stores these as generic metadata fields. It does not interpret `entry_type`; that's CampaignGenerator's concern.

---

## Unconverted-book handling — pointer + suggest-conversion

When `rpg_retriever` finds a candidate book that rpglib knows about but MemPalace has no drawers for, it emits a pointer entry. The AI surfacing results may suggest "Book X looks relevant — want me to convert it?". Conversion is **never** auto-triggered — it enters the existing pdf-translators pipeline (with Marker structure extraction + human review). This preserves the LLM-pipeline rule by making LLM-rendered content an explicit user decision, not a side-effect of querying.

---

## Access patterns (how the pieces talk)

- **CampaignGenerator → rpglib:** via rpglib's MCP server (`library_mcp.py`). Consistent with existing CampaignGenerator MCP-client patterns.
- **CampaignGenerator → MemPalace:** via MemPalace's MCP server (`tool_search_hierarchical`, `tool_search`, `tool_add_drawer`, `tool_list_wings`, etc.). Read and write both go over MCP.
- **CampaignGenerator → pdf-translators:** via subprocess (invoking `pdf_to_5etools_v2.py`). Same pattern CampaignGenerator uses for the Claude API calls in `campaignlib.py` — subprocess + structured output.
- **MemPalace ↔ rpglib:** never. MemPalace has zero awareness of rpglib.
- **MemPalace ↔ pdf-translators:** never. MemPalace has zero awareness of pdf-translators.

---

## Files summary

### MemPalace (sub-plan A)

**New (5 items):**
- `mempalace/recursive_indexer.py`
- `tests/test_recursive_indexer.py`
- `tests/test_search_hierarchical.py`
- `tests/benchmarks/hierarchical_aaak.json` (~15 generic palace queries)
- `mempalace_room_indices` + `mempalace_wing_indices` collections (schema addition)

**Modified (6 files):**
- `mempalace/searcher.py` — `search_within` primitive
- `mempalace/palace.py` — collection accessors + dirty-flag plumbing
- `mempalace/dialect.py` — rank-bucketed projection helpers exposed
- `mempalace/mcp_server.py` — `tool_search_hierarchical` handler + registration
- `mempalace/layers.py` — optional `max_depth=0` path (Phase 3)
- `mempalace/config.py` — startup warning when `~/.mempalace` resolves onto a non-ext4 / DrvFs / 9P path (`/mnt/c/…`, `/mnt/d/…`). One warn log on palace open; no-op on `/mnt/data` and `$HOME`.

**Reused unchanged:**
- `mempalace/palace.py::build_closet_lines / purge_file_closets / upsert_closet_lines / mine_lock / file_already_mined`
- `mempalace/palace_graph.py::traverse` (available for lateral expansion but not required)
- `mempalace/backends/base.py` (per-wing collection split available if scale ever needs it)

### CampaignGenerator (sub-plan B)

**New (8 items):**
- `CampaignGenerator/rpg_retriever.py`
- `CampaignGenerator/fivetools_ingest.py`
- `CampaignGenerator/dossier_proposer.py`
- `CampaignGenerator/convert_book.py`
- `CampaignGenerator/suggest_conversion.py`
- `CampaignGenerator/tests/test_rpg_retriever.py`
- `CampaignGenerator/tests/test_fivetools_ingest.py`
- `CampaignGenerator/tests/benchmarks/rlm_benchmark_rpg.json` (~15 RPG queries)

**Modified (4 files):**
- `CampaignGenerator/mcp_server.py` — add `rpg_search`, `propose_dossier`, `suggest_conversion`
- `CampaignGenerator/prep.py` — consume `docs/dossier_proposal.md` as grounding when present
- `CampaignGenerator/session_doc.py` — same
- `CampaignGenerator/CLAUDE.md` — document the pipeline + retrieval/render separation rule

---

## Phased rollout with gates

Each gate runs its repo's benchmark. Do not start phase N+1 before gate N passes.

### Phase 0 — Host + baselines (~1 week)

- **Host decision (settled).** All four tools (rpglib, pdf-translators, MemPalace, CampaignGenerator) run inside **WSL2**. Storage-critical state (MemPalace palace, ChromaDB, SQLite, rpglib DB, pdf-translators outputs) lives on a **dedicated 80 GB VHD mounted at `/mnt/data`** formatted as ext4. From WSL2's perspective this is native Linux filesystem — no DrvFs, no 9P crossing, correct `mmap` / `fsync` / `flock` semantics. The VHD sidesteps every footgun the original VM plan was trying to avoid, without the VM overhead.
- **Palace location.** `~/.mempalace/` is a symlink (or bind mount) into `/mnt/data/mempalace/`. 80 GB is enough for the palace plus rpglib DB (79 MB) plus pdf-translators JSON outputs with healthy headroom.
- **Corpus (the 2 TB of PDFs) access — open decision, not blocking Phase 0.** Two viable patterns; the corpus itself is **not** copied onto `/mnt/data` (80 GB can't hold 2 TB). Access it in place:
  - *Rclone mount* (`rclone mount gdrive: /mnt/gdrive --vfs-cache-mode full`) — Linux-native Google Drive access inside WSL2. Sequential reads are fine for pdf-translators's one-time conversion pass.
  - *Windows Drive mirror via `/mnt/g/`* — the existing path. Read-only access; pdf-translators opens files directly. Works as-is.
  The retriever/ingest code is corpus-location-agnostic (it gets filepaths from rpglib, opens files at those paths); either pattern works.
- **DrvFs startup warning (in scope).** Users may still misconfigure `~/.mempalace` onto `/mnt/c/` or another DrvFs path. MemPalace's `config.py` gets a startup check that warns when the palace resolves onto a non-ext4 / DrvFs / 9P path. No-op on `/mnt/data` and `$HOME`.
- **Benchmarks checked in.** ~15 generic palace queries in MemPalace; ~15 RPG queries in CampaignGenerator. Baseline numbers (flat AAAK, book-level-only retrieval) recorded against the VHD-backed palace.

**Gate 0:** VHD mounted at `/mnt/data` and `~/.mempalace` relocated onto it; palace + Chroma operate on `/mnt/data` with correct `flock` + `fsync` + `mmap` behavior verified by smoke test; corpus-access strategy chosen and working; two benchmark sets committed; baseline numbers on record.

### Phase 1 — MemPalace sub-plan: hierarchical AAAK (~2–3 weeks, MemPalace repo)

Ship `recursive_indexer.py`, `search_within`, `tool_search_hierarchical`, new collections. Test against the **generic** 15-query benchmark on a synthetic or chat-palace fixture.

**Gate 1 (the critical gate — answers: does aggregated AAAK preserve navigation signal on a generic palace?):**
- Recall@10 within 5% of baseline; precision@10 ≥ baseline.
- ≥2× reduction in drawers-scored per query.
- Room + wing indices < 50 MB on the test fixture.
- Human spot-check: 10/10 queries where the returned AAAK path is interpretable without opening drawers.

**If Gate 1 fails, stop the MemPalace side.** CampaignGenerator falls back to flat `tool_search` — still works, just without hierarchical pruning.

### Phase 2 — CampaignGenerator sub-plan: ingest + retriever (~2 weeks, CampaignGenerator repo)

Ship `fivetools_ingest.py`, `convert_book.py`, `rpg_retriever.py`, `suggest_conversion.py`. Ingest currently-converted adventures + bestiaries + official 5etools into MemPalace via MCP. Wire `rpg_retriever` to call rpglib MCP + MemPalace MCP.

**Gate 2:**
- Full RPG benchmark (15 queries) passes: top-3 correct entity/topic on ≥ 90% of queries against the ingested corpus.
- Three-state result shape correct: queries that hit unconverted books emit pointer-kind entries with valid `suggest_conversion` payloads.
- `fivetools_ingest.py` is idempotent: re-running on unchanged JSON is a no-op (mtime + size check).

### Phase 3 — CampaignGenerator sub-plan: dossier + render separation (~1 week)

Ship `dossier_proposer.py`, add MCP tools, refactor `prep.py` / `session_doc.py` / `planning.py` to consume `docs/dossier_proposal.md` when present. Render pipelines refuse to run without an approved proposal.

**Gate 3:**
- CI grep: zero call sites where `rpg_search` and a render function co-locate in the same function body.
- Integration test: `prep.py` refuses to render if `docs/dossier_proposal.md` is absent but is demanded by a given workflow mode.
- Human-approved proposal round-trips through a render pipeline successfully.

### Phase 4 — Wake-up integration (optional, ~1 week, MemPalace repo)

Wire `max_depth=0` hierarchical search into L1/L2 wake-up.

**Gate 4:** L0+L1 wake-up stays < 900 tokens and < 100 ms startup.

### Phase 5 — Scale stress test (conditional, ~1 week)

Only if/when you convert a much larger fraction of the 14 K-book library.

**Gate 5:** `tool_search_hierarchical` p50 < 100 ms / p95 < 500 ms across full palace; hooks still < 500 ms. If strain shows, shard `wing_rpglib` using the existing `backends/base.py` per-wing split. No code changes assumed to be needed.

---

## Storage architecture

All four tools run inside **WSL2**, with storage-critical state on a **dedicated 80 GB VHD mounted at `/mnt/data`** (ext4). Rationale: WSL2's DrvFs / 9P bridge layers are what create the footguns — `/mnt/c/` hosts do not give correct `mmap` / `fsync` / `flock` semantics for ChromaDB and SQLite. A VHD is native Linux filesystem from WSL2's perspective, so the bridge layer is simply not in the path. This achieves the same correctness the VM plan was reaching for, without the VM.

- **Palace:** `~/.mempalace/` is a symlink (or bind mount) into `/mnt/data/mempalace/`. 80 GB covers all MemPalace state comfortably.
- **Source PDFs (2 TB on Google Drive):** accessed in place via rclone mount or the existing `/mnt/g/` Windows Drive mirror. **Not copied onto `/mnt/data`** — 80 GB can't hold them. Read-only by pdf-translators; never touched by MemPalace.
- **rpglib DB:** `/mnt/data/` (79 MB). CampaignGenerator reads via rpglib's MCP, never directly.
- **pdf-translators outputs:** `/mnt/data/`. `fivetools_ingest.py` takes explicit paths.
- **CampaignGenerator workspaces:** `/mnt/data/` for anything sharing Chroma/SQLite state; workspaces that are purely doc-scale can stay in `$HOME`. `docs/dossier_proposal.md` joins the existing grounding-doc family inside each campaign workspace directory.

The DrvFs footguns the original plan feared apply *only* if the palace lands on `/mnt/c/` (or another DrvFs mount). Putting it on a dedicated VHD at `/mnt/data` takes WSL2's bridge layer out of the path entirely — no VM required. MemPalace's `config.py` keeps a startup warning for the misconfiguration case (palace resolving onto DrvFs / 9P).

---

## Risks and unknowns

Ordered by load-bearingness.

1. **Hierarchical AAAK preserves navigation signal.** The whole plan assumes frequency-sorted top-N projections of leaf closets prune correctly at room and wing levels. **Gate 1 measures this on a generic palace.** If it fails, MemPalace side stops; CampaignGenerator falls back to flat `tool_search`.
2. **MCP round-trip cost at ingest time.** `fivetools_ingest.py` calls `tool_add_drawer` once per typed entry. A book with 200 entries = 200 MCP round-trips. If this is too slow, the fallback is a batched `tool_add_drawers` (plural) added to MemPalace — but that's an additive MCP tool, not a disruptive change.
3. **pdf-translators output schema drift.** `fivetools_ingest.py` imports from pdf-translators's `adventure_model.parse_document`. Schema changes in pdf-translators surface as validation errors in the ingest step — loud, local, fixable.
4. **rpglib metadata freshness.** rpglib is updated manually. `fivetools_ingest.py` snapshot-copies rpglib metadata into MemPalace drawer metadata at ingest time. If rpglib metadata changes later (tag normalization, re-enrichment), MemPalace drawers show old values until re-ingested. Acceptable — rpglib is authoritative for search-by-metadata; MemPalace's copy is a denormalized cache for fast filtering inside a single query.
5. **Bestiary wing de-duplication.** A creature in multiple sourcebooks generates one statblock drawer per source. Intentional — different sources have different stat blocks for the "same" creature. Mitigation: always include `source` in bestiary result metadata.
6. **Orchestrator over-trust of AAAK paths.** Claude may treat a returned AAAK path as authoritative without opening drawers. Mitigation: `tool_search_hierarchical` default return format includes top drawer text alongside the path.
7. **Pointer fatigue.** If a query surfaces 40 pointers and 3 drawers, result is noise. Mitigation: CampaignGenerator-side default pointer limit (top 5 by rpglib relevance); `include_unconverted_pointers=false` flag.
8. **VHD exhaustion.** Palace + ChromaDB + rpglib DB + pdf-translators outputs all share the 80 GB `/mnt/data` VHD. The 2 TB corpus is accessed in place, not copied, so the dominant growth is the palace itself (proportional to how much of rpglib gets converted). Mitigation: Gate 0 includes a disk-usage smoke test; a startup warning fires when `/mnt/data` is >80% full. Fallback is growing the VHD (WSL2 supports online resize via `wsl --manage … --resize`).

---

## Verification

| Gate | Repo | Measured against | Pass criterion |
|---|---|---|---|
| 0 | both | Benchmark files committed; storage verified | Baseline precision@10, recall@10, p50/p95 recorded in each repo |
| 1 | MemPalace | 15 generic palace queries vs. recursive palace | Recall within 5% of baseline; precision ≥ baseline; ≥2× drawer-read reduction; indices < 50 MB; 10/10 human-readable paths |
| 2 | CampaignGenerator | 15 RPG queries against the three-state retriever | Top-3 correct ≥ 90%; three-state shape correct; ingest idempotent |
| 3 | CampaignGenerator | Static grep + integration test on prep/session_doc/planning | Zero retrieve+render co-location; render refuses without approved proposal |
| 4 | MemPalace | Wake-up benchmark | L0+L1 < 900 tokens, < 100 ms startup |
| 5 | MemPalace | Full-palace latency at realistic convert-out scale | p50 < 100 ms, p95 < 500 ms; hooks < 500 ms |

---

## Explicitly out of scope

- **MemPalace learning RPG schemas.** 5etools-JSON awareness lives entirely in CampaignGenerator.
- **MemPalace learning about rpglib or pdf-translators.** Zero awareness in MemPalace code of either dependency.
- **PDF ingestion by MemPalace.** pdf-translators owns PDF → JSON.
- **OCR by MemPalace.** Marker (in pdf-translators) owns it. Books that can't be extracted stay at rpglib-metadata level, surfaced as pointer-kind results.
- **Re-deriving rpglib metadata.** rpglib is authoritative; CampaignGenerator's `fivetools_ingest.py` snapshot-copies at ingest time.
- **Auto-conversion of unconverted books.** Always user-approved.
- **Auto-ingest of conversion output.** Explicit user step (runs `fivetools_ingest.py`).
- **Bulk ingest of all 14 K rpglib books.** Ingestion is demand-driven by the user running conversions.
- **Cloud/SaaS storage.** Violates local-first.
- **Telemetry on retrieval queries.** Violates privacy-by-architecture.
- **LLM-generated intermediate summaries in any index path.** Violates verbatim + the LLM-pipeline rule.
- **Render pipelines reading directly from `rpg_search` output.** Must go through `docs/dossier_proposal.md`.
