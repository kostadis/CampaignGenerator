# rpglib palace pilot: passage-level search over converted DMsGuild books

## Intent

During session prep the GM wants **examples of a kind of thing from across their
library** — "druid NPCs so I can build a new druid", "a tavern", "a corrupt
harbourmaster" — to borrow from. rpg-lib already answers the book-level question
(which books), but only from titles, descriptions and tags: a search for "druid"
finds 8 adventures in 8,671 books. A druid hermit on page 47 of a book whose blurb
is about a haunted mill is invisible. The missing layer is **search inside the
books' text**, returning the write-up itself with its book and page.

This is a pilot: prove mempalace can hold and usefully search this corpus before
committing to the whole converted DMsGuild set.

## Goals

- A new, separate mempalace palace holding ~50 converted DMsGuild books.
- A GM query returns whole write-ups (an NPC, a location, a room), each tagged with
  book title, rpg-lib book id, section path and page.
- The GM can judge, by running real prep queries, whether it is useful.
- Learn whether mempalace copes, and what breaks, before scaling up.

## Non-goals

- The full DMsGuild set (comes after the pilot, if it passes).
- Other publishers or game systems.
- Re-converting PDFs; only existing 5etools JSON sidecars are used.
- Feeding results to any pipeline. Output is read by the GM only.

## Anti-goals (failure even if it "works")

- Touching any palace currently in use (campaign palaces, the default palace).
- Changing mempalace itself for the pilot.
- Results that are fragments (half a tavern) or dominated by one book.
- Silently losing content (lists, tables, boxed text) the way `fivetools_ingest`
  drops list items and table rows.

## Constraints

- **Isolation:** the palace lives at its own path, selected per command via
  `MEMPALACE_PALACE_PATH`; no command in this work runs without it set.
- **Source access:** sidecars are read from the local mount
  `/mnt/g/My Drive/DriveThru/Dungeon Masters Guild`. It was refusing publisher
  folders because the host's Drive folder was in streaming mode; the GM is switching
  it to local (it is already local on the GM's other machine). Fetch is therefore a
  plain, re-runnable file copy into a local cache. Fallback if the mount still fails:
  the Google Drive connector (folder id `1CPbfKd9zhL2ih42cND1gHb3_efCrJGsn`).
- **Which file is the book:** each book folder also holds intermediates
  (`*-extract.json`, `*-mistral-raw.json` up to 66 MB, `*-parsed.json` parts). The
  book is the `.json` whose stem equals the PDF's stem (rpg-lib's
  `get_book_fivetools` contract).
- Mempalace's per-file chunk cap (`MEMPALACE_MAX_CHUNKS_PER_FILE`, default 500 ≈
  400 KB) is what broke whole-book ingestion before.
- **Embedding/backend:** the pilot uses this host's existing mempalace wiring from
  `~/.config/hypostasis/hypostasis.yaml` (the single config authority) unchanged:
  `MEMPALACE_BACKEND=turbovec`, Ollama `qwen3-embedding:0.6b` at
  `192.168.56.1:11434` — the same embedder the chunking experiment measured. Only
  the palace path is overridden. Vectors are fixed at palace creation; a different
  embedder later means re-mining.
- **Book selection source:** rpg-lib's database (`~/src/mytools/rpg-lib/rpg_library.db`,
  per hypostasis `data_roots`).

## Evidence this rests on

`~/src/dgx-fun/mempalace-chunker-arm-results.md`: on two converted modules,
mempalace's `chunk_text` applied per section is in the same regime as the best
splitter tested (recursive-600), far ahead of fixed windows. Heading breadcrumbs
were module-dependent (+2 ToEE, −3/−4 Phandelver at tight budgets).

## Approaches

1. **Render each book to one markdown file per section, then `mempalace mine`
   (chosen).** Readable text that keeps lists, tables and boxed text; each file opens
   with a `Book > Chapter > Section` line. Per-section files stay under the chunk cap;
   the chunker is the measured one; no mempalace changes.
2. **`fivetools_ingest` → `add_drawer`.** Exists today and is structural, but drops
   list items and table rows and keeps only direct text (2/48 Phandelver answers were
   absent). Rejected: lists of rumours and tables of patrons are the content wanted.
3. **New structural-drawer importer in mempalace.** Cleanest units, most work, and
   changes mempalace before we know it copes. Deferred.

## Design

**Pipeline:** select → fetch → render → mine → query.

1. **Select** ~50 books with a finished sidecar from the DMsGuild folder, biased to
   product types where NPCs and places live (adventure, setting, gm_aid), using
   rpg-lib metadata. Record the list (book id, title, sidecar file id) in a manifest.
2. **Fetch** each sidecar from the mount into a local cache
   (`~/rpglib-cache/dmsguild/<book_id>.json`), recording size and modified time.
3. **Render** each book with the same renderer used in the chunking experiment
   (`dgx-fun/experiments/adaptive-chunking/prepare.py`'s 5etools renderer, lifted or
   imported): one markdown file per top-level section, first line
   `<Book title> > <Chapter> > <Section>`, and a small front-matter/metadata block
   carrying `book_id`, `title`, `publisher`, `section_path`, `page`. A section that
   would still exceed the chunk cap is split at its sub-headings.
4. **Mine** the rendered tree into the new palace with `mempalace mine`, one wing for
   the library (e.g. `wing_dmsguild`), rooms per book.
5. **Query** with a thin script *outside* mempalace (mempalace is unchanged) that:
   - runs mempalace's normal search against the pilot palace, over-fetching (e.g. 50 hits);
   - maps each hit's `source_file` through the pilot manifest to book id, title,
     publisher and section path (mine does not store custom front-matter);
   - expands each hit to its **whole section** file, so a result is a full write-up,
     not an 800-character chunk;
   - caps results at **2 per book** and reports how many distinct books appeared and
     how often the cap fired.
   "Page" in a result is the page where the section starts.

**Evaluation (the GM is the judge):** the GM runs ~10 real prep queries. For each,
record: were the top results whole write-ups, how many distinct books in the top 10,
did any hit surprise them usefully. Also record ingest time, palace size on disk,
query latency, and anything that broke.

## Decided

- Mempalace first, in a new palace; if it breaks, find another store.
- Corpus is converted DMsGuild 5etools JSON only.
- Results are book + passage, linked back to rpg-lib by book id.
- Approach 1.
- Embedder/backend: the existing hypostasis wiring (turbovec + Ollama
  qwen3-embedding:0.6b on the host), "built-in first" (GM, 2026-11-20).
- Source via the local mount once the GM makes the Drive folder local.
- All code for this effort in ONE dedicated git worktree (not the main checkout), implemented by Sonnet subagents,
  orchestrated and reviewed by Opus; one code-review pass; leftovers become
  sub-issues of the pilot's parent issue.

## Calls made by the designer (correct if wrong)

- A query wrapper outside mempalace is allowed (the anti-goal is changing mempalace).
- Book/section tags are recovered from `source_file` via the manifest, not stored per chunk.
- Diversity is enforced by a 2-per-book cap, not only measured.

## Left to the builder

Where the code lives, renderer reuse mechanics, the cache layout, the exact
selection script, the wing/room naming, and the over-fetch size.
