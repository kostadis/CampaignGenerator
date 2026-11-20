# Research: Library Passage Search

The Technical Context left no NEEDS CLARIFICATION items. The pilot (`experiments/20261120-rpglib-palace-pilot/FINDINGS.md`) answered most of the unknowns. The decisions below record those answers.

## R1. Index unit and store

- **Decision**: One markdown file per top-level section of a book, mined with `mempalace mine` into a dedicated palace. The wing is `wing_dmsguild` and each book gets its own room, `b<book_id>`. A search hit is expanded back to its whole section file.
- **Rationale**:
  - The pilot worked end to end.
  - dgx-fun's chunker arm showed that mempalace `chunk_text` per section is in the same quality range as recursive-600.
  - Section files stay under the per-file chunk cap.
- **Alternatives considered**:
  - `fivetools_ingest` drawers: they drop list items and table rows.
  - A new structural importer inside mempalace: it changes mempalace before we know whether it copes.

## R2. Reaching mempalace (Principle V)

- **Decision**: Add two capabilities to `pipelines/rlm/mempalace_client.py`:
  1. `mine(render_root, *, palace, wing, env)`, which runs the `mempalace mine … --direct` subprocess;
  2. search against an explicit palace path, using the existing `MempalaceClient(palace=<path>).search(...)`.

  `pipelines/library` imports neither `mempalace` nor `subprocess` for mempalace work.
- **Rationale**: The constitution names `mempalace_client.py` as the only seam. The pilot's direct `mempalace.searcher` import already broke once, when it hit an "implementation fragment" ImportError.
- **Check during implementation**: the MCP `search` tool's hit shape must carry `source_path` (or `source_file` plus `room`) so that section mapping still works. If it does not, use the MCP `search` with a `room` filter, or read `source_path`, and record which.
- **Alternatives considered**: a direct `search_memories` import (what the pilot did); rejected because it is a second seam.

## R3. Configuration (FR-017)

- **Decision**: A new `library:` block in `~/.config/hypostasis/hypostasis.yaml` (contracts/authority-config.md) supplies `palace`, `source_root`, `cache_dir`, `work_dir` and `selection`. The embedder and backend come from the file's existing `env:` block. `config.py` merges `env:` into the subprocess environment and never overrides variables that are already set. The pilot's `envcfg.py` behaviour is kept.
- **Rationale**: The pilot fell back silently to chroma + minilm when the env was missing. The authority file is the single source of these settings, and hypostasis seeds it during setup (local_machine#1).
- **Alternatives considered**: per-campaign `config.yaml` (the library is not per campaign); CLI flags (they would drift across CLIs, against Principle XII).

## R4. Selection and version dedupe (FR-002/003)

- **Decision**: The `selection` key holds one of three forms:
  - `{product_types: [...]}`;
  - `{book_ids: [...]}`;
  - `{all_converted: true}`.

  A missing or empty `selection` means "not configured" (exit 3). Only finished sidecars count, meaning `<pdf-stem>.json`.

  Dedupe works as follows:
  - drop rpg-lib rows where `is_old_version=1` or `is_duplicate=1`, and any `.old-NNN` files;
  - prefer the non-"Print Friendly" title when two rows have the same title once "(Print Friendly)" or "(Printer Friendly)" is stripped;
  - `is_printer_friendly=1` is the tiebreaker.

  An explicit `book_ids` entry bypasses dedupe.
- **Rationale**: The pilot sample was full of print-friendly twins. Principle X forbids defaulting silently to "all".
- **Alternatives considered**: deduping by product_id (often null for DMsGuild).

## R5. Incremental refresh (FR-006, SC-005)

- **Decision**: A ledger (`library_ledger.json`) records, per book, the source size and mtime, a hash of the rendered output, and the list of section files.
  - A refresh re-renders only books whose source changed or that were added or removed.
  - For each changed book, it deletes that book's drawers from the palace (by room `b<id>`), then mines only that book's directory.
  - Deletion goes through `mempalace_client` (MCP `delete_drawer` by room, or the CLI equivalent; whichever is used is recorded).
- **Rationale**: The GM's model of messy books is "fix the JSON, refresh". A full re-mine of about 667 books would take roughly 40 minutes.
- **Check during implementation**: does `mempalace mine` re-file unchanged files idempotently? The pilot showed "Files skipped (already filed)", which suggests yes. If the delete-by-room path is not exposed, fall back to mining with `--files-from` and verify that replaced files do not leave stale drawers. Record the result as a test.
- **Alternatives considered**: always rebuilding (too slow at scale).

## R6. RLM tier position (FR-013)

- **Decision**: `kind="passage"` becomes a **new tier between drawer/statblock and cheap candidates**:
  1. drawer/statblock
  2. passage
  3. cheap
  4. expensive

  A book that has library passages is added to `covered_book_ids`, so it is never offered as an expensive conversion candidate (Story 3, scenario 3). `rpg_search` gains `include_library` (default true when a library is configured) and `k_library` (default 10).
- **Rationale**: Library passages are already-converted, ready-to-read text, so they rank above anything that still needs ingesting. They are not curated into a campaign palace, so they rank below campaign drawers. No scores are normalized across sources, which keeps RLM's existing rule.
- **Alternatives considered**: merging passages into the drawer tier (it blurs "curated for this campaign" with "somewhere in the library").

## R7. UI face (Principle XI)

- **Decision**: A panel on the Prep page, `LibrarySearch.vue`, with a query box, a per-book cap, and results showing book, section path and an expandable full passage. It also shows library status: configured, built, book count, stale books, and the embedder match.
  - Build and refresh are **not** buttons. The panel shows their state and the exact command, because hypostasis drives them and they run for minutes. This follows the pattern of the existing "show the copyable command" behaviour.
- **Rationale**: Principle XI requires a face unless the GM opts out. Principle IX: the UI runs the mechanical step and the judgement happens in chat.
- **Alternatives considered**: no UI (needs an explicit GM exemption); build buttons (they would duplicate hypostasis).

## R8. Agent surface (FR-012/014)

- **Decision**: A new MCP tool, `library_search(query, limit=10, per_book=2)`, in `mcp_server.py`. It returns the Search Result Set as JSON, with each passage's **full text**, so an agent can run several wordings, read the passages and quote them verbatim. `rpg_search` also returns passage hits (R6), truncated to a preview.
- **Rationale**: The pilot's value came from an agent iterating and reading. `rpg_search` truncates for list views, so a dedicated tool keeps the full text.
- **Alternatives considered**: a skill that shells out to the CLI. That is possible later, but the MCP server is CG's outward seam (Principle V).

## R9. Not repaired

- **Decision**: No structural repair of dirty JSON. `render --merge-fragments` stays an option, off by default. Page numbers are shown only when present.
- **Rationale**: The GM ruled on 2026-11-20: "stop tuning … the goal is to find things."
