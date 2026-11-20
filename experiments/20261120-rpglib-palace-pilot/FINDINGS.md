# rpglib palace pilot: passage-level search over converted DMsGuild books

**Date:** 2026-11-20 · **Branch:** `feat/rpglib-palace-pilot` ·
**Spec:** `docs/superpowers/specs/2026-11-20-rpglib-palace-pilot-design.md` ·
**Plan:** `docs/superpowers/plans/2026-11-20-rpglib-palace-pilot.md`

## Verdict

**Useful enough to build.** The GM's verdict after a real prep request was: "this is useful enough". A plain mempalace palace over rendered sections finds write-ups that rpg-lib's title/description search cannot. The workflow that pays off is **an AI agent runs several queries, reads the hits, and comes back with an opinion**. A human reading raw top-10 lists gets much less from it.

## What was built

`pipelines/rpglib_palace/` is a pipeline with no LLM calls. Mempalace itself was not changed. It has five steps:

| Step | What it does |
|---|---|
| `select` | Picks books from `rpg_library.db`: DMsGuild, `adventure/setting/gm_aid`, finished sidecar present, not old/duplicate. |
| `fetch` | Copies each book's sidecar from `/mnt/g/My Drive/DriveThru/Dungeon Masters Guild` into `~/rpglib-cache/dmsguild/<id>.json`. Re-copies only when size or mtime changed. |
| `render` | Writes one markdown file per top-level section using `fivetools_render.render_entries_block`, so lists and tables are kept. Each file starts with a breadcrumb line. Oversize sections are split at sub-headings and never truncated. `--merge-fragments` is optional and off by default. |
| `mine` | Runs `mempalace mine --direct --wing wing_dmsguild`, with one room per book. The palace guard refuses any path under `~/.mempalace` or `~/src/campaigns`. Settings are read from `hypostasis.yaml`. |
| `query` | Over-fetches 50 hits through `mempalace.searcher.search_memories`, maps each hit to its section via `sections.json`, expands it to the whole section, and caps results at 2 per book. It reports distinct books, how often the cap fired, and unmapped hits. |

**Tests:** 49 (`tests/test_rpglib_palace_*.py`).

## Numbers (50 books, first 50 by rpg-lib id)

| | |
|---|---|
| Finished sidecars in the DMsGuild folder | 667 of 2,293 PDFs (144 MB) |
| Pilot sample | 50 books, 5.3 MB of JSON → 804 sections |
| Drawers | 7,073 |
| Mine, turbovec + Ollama `qwen3-embedding:0.6b` | 186 s, 46 MB on disk |
| Mine, chroma + minilm (accidental, kept as `palace-minilm`) | 260 s, 71 MB on disk |
| Query latency | about 1 s |
| Isolation | Live palaces under `~/.mempalace/palaces` unchanged (newest-file mtime identical before and after). |

## The real prep test

**Request:** "use the query to find me a statblock for a tavern keeper". The agent ran three wordings and read the candidates.

- **Answer found:** Wan Bai, keeper of the Dashing Satyr, in *Cottage on the Long Road* (book 2443), section "The Setup". She uses noble stats with History +3 and Nature +3, has two commoner innkeepers and an errand boy, and sources goods from Kara-Tur.
  - Only the second and third wordings surfaced it. The first wording ranked noise above it.
- **Fallbacks:** Spugnois, a tavern patron with a statblock (*Hommlet – Local Side Quests*), and the CR-indexed blocks in *Adaptable NPCs I and II*.
- **Recall check:** a grep over every heading in the corpus found no dedicated innkeeper or barkeep statblock in these 50 books, so the search did not miss one.
- **Noise:** *100 Monster Hunts* and *Alyth's Blueprints* ranked high. They mention taverns, but their structure is broken (see below), and their hits are 70–85K-character blobs.

Earlier smoke query "druid hermit NPC": the top hit was *Adaptable NPCs of the Guild — The Sewer Druid*.

## Findings

1. **Converted JSON is often structurally dirty. This is expected, not a bug to chase.** The PDF→markdown→5etools conversion was automated, and cleanup was deferred.
   - Junk top-level sections appear: book 2572 has `5 gp`, `10 gp`, `hit points.`, and book 2357 has `1/2`, `PCs)`, `Easy (4+`. The book's own `contents` lists the same names, so the renderer reproduces the split rather than causing it.
   - A rough heuristic flags about 12 of 50 books (8–10 genuinely broken).
   - **GM ruling:** stop tuning. "If I really care about a book, I fix the JSON. The goal is to find things, and this finds things."
2. **No page numbers.** None of the 50 sidecars has a `page` field, so every result shows `p.?`.
3. **The real sidecars are in homebrew shape** (`adventure`/`adventureData`, `book`/`bookData`), not a top-level `data`. The first render skipped all 50 books until this was fixed.
4. **Mempalace settings must come from `hypostasis.yaml`.** A shell without the `MEMPALACE_*` env silently fell back to chroma + minilm. `mine` and `query` now merge the hypostasis `env:` themselves.
5. **`search_memories` hits carry the basename as `source_file`.** Section names repeat across books (`001-intro.md`), so the mapping uses `source_path`, with `room/basename` as a fallback.
6. **`mempalace.searcher.query` cannot be imported directly.** It is a fragment; import it via `mempalace.searcher`.
7. **The fragment merge (optional) is only a partial fix:** 804 → 646 sections. Capitalised junk with 300+ characters of body survives, for example book 2357's `MKToF Required` ×8. It is kept as a flag and is not tuned further.
8. **The sample is weak.** Taking the first 50 by id skews toward small books and includes "Print Friendly" duplicates. A real build should bias toward large adventures and settings, and dedupe print-friendly variants.

## Not done / open

- The plan's one code-review pass has not been run on this branch.
- The 10-query GM evaluation was replaced by the single real request above, which the GM judged sufficient.
- No console-script install into `~/.venvs/main`. Run with `python -m pipelines.rpglib_palace.cli`.
- Mempalace emits an `EmbedderIdentityUnknownWarning` on the turbovec palace.
- Scaling past 50 books, to all 667 finished sidecars, has not been tried.

## Reproduce

```bash
cd <worktree>
export CG_BACKEND=claude-code MEMPALACE_PALACE_PATH=~/rpglib-palace/palace PYTHONPATH=$PWD
PY=~/.venvs/main/bin/python
$PY -m pipelines.rpglib_palace.cli select
$PY -m pipelines.rpglib_palace.cli fetch
$PY -m pipelines.rpglib_palace.cli render        # add --merge-fragments to try the merge
$PY -m pipelines.rpglib_palace.cli mine
$PY -m pipelines.rpglib_palace.cli query "tavern keeper statblock"
```

## Related

`~/src/dgx-fun` branch `exp/mempalace-chunker-arm`, which has the evidence this pilot rests on:
- mempalace `chunk_text` per section scores in the same range as recursive-600;
- `mempalace-chunker-arm-results.md`.
