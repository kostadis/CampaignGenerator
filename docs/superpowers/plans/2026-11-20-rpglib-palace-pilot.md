# rpglib Palace Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Search inside ~50 converted DMsGuild books from a new, isolated mempalace palace. Each result is a whole section with its book, rpg-lib id, section path and page.

**Architecture:** A new package, `pipelines/rpglib_palace/`, runs five steps: select → fetch → render → mine → query.
- **select** reads the rpg-lib SQLite file directly.
- **fetch** copies each book's file into a local cache.
- **render** writes one markdown file per section using the existing `fivetools_render.render_entries_block`, so lists and tables are kept.
- **mine** calls `mempalace mine --direct`. Before running, it checks that the palace is not a live one.
- **query** calls mempalace's `search_memories`, then expands each hit to its whole section and keeps at most 2 results per book.

Mempalace itself is not modified.

**Tech Stack:** Python 3, sqlite3 (stdlib), pytest, mempalace CLI and `mempalace.searcher.query.search_memories`, the existing `pipelines/content_ingest/fivetools_render.py`.

**Spec:** `docs/superpowers/specs/2026-11-20-rpglib-palace-pilot-design.md`

## Global Constraints

- **Isolation.** The palace is selected per command with `MEMPALACE_PALACE_PATH`, and no command runs without it set.
  - Default palace: `~/rpglib-palace/palace`.
  - `mine` and `query` refuse if the path is unset, equals `~/.mempalace/palace`, sits under `~/.mempalace/`, or sits under any `~/src/campaigns/*/`.
  - `mine` always passes `--direct`. The shared daemon could be serving a live palace.
- **Source.** Book files are read from `/mnt/g/My Drive/DriveThru/Dungeon Masters Guild`. The book is the `.json` whose stem equals the PDF's stem. Ignore `*-extract.json`, `*-mistral-raw.json` and `*-parsed*.json`.
- **Cache.** Copies go to `~/rpglib-cache/dmsguild/<book_id>.json`.
- **Embedder and backend.** Unchanged hypostasis wiring: `MEMPALACE_BACKEND=turbovec`, Ollama `qwen3-embedding:0.6b` at `192.168.56.1:11434`. Override only the palace path.
- **Chunk cap.** `MEMPALACE_MAX_CHUNKS_PER_FILE` defaults to 500 chunks (about 400 KB). A rendered file must stay under `MAX_FILE_BYTES = 300_000`. Larger sections are split at sub-headings.
- **Selection.** About 50 books, `product_type IN ('adventure','setting','gm_aid')`, and only books whose finished file exists.
- **Naming.** Wing is `wing_dmsguild`. There is one room per book, named `b<book_id>`.
- **Query.** Over-fetch 50 hits and keep at most 2 per book. Page = the page where the section starts.
- **Code location.** All code lives in ONE worktree, `../CampaignGenerator-rpglib-palace` on branch `feat/rpglib-palace-pilot`.
  - Sonnet subagents write the code; Opus orchestrates and reviews.
  - Tests must import the worktree's code. Run with `PYTHONPATH=<worktree>` and assert `pipelines.rpglib_palace.__file__` is inside the worktree.
- **No LLM calls** anywhere in this package.

## Review Focus

1. **A book whose JSON has no `data` list, or no `page` fields.** It should be rendered with `page: null`, not crash the run. Owner: Task 3, `test_render_missing_pages`.
2. **A cached file whose source changed or vanished on the mount.** Fetch should re-copy when size or mtime differ. A missing source is recorded as `missing` and the run continues. Owner: Task 2.
3. **A palace path that is a symlink or `~`-relative and resolves into a live palace.** It must be refused after `resolve()`. Owner: Task 4, `test_guard_resolves_symlink`.
4. **A search hit whose `source_file` is not in the manifest** (a stale palace). Report it as `unmapped`; never drop it silently. Owner: Task 5.
5. **Duplicate rpg-lib rows for one PDF** (`is_old_version`, `is_duplicate`, `.old-001` files). Selection excludes them. Owner: Task 1.

---

### Task 1: Select books into a manifest

**Files:**
- Create: `pipelines/rpglib_palace/__init__.py`, `pipelines/rpglib_palace/select.py`
- Test: `tests/test_rpglib_palace_select.py`

**Interfaces:**
- Produces:
  - `select_books(db_path: Path, source_root: Path, limit: int = 50, types=("adventure","setting","gm_aid")) -> list[dict]`
    - Each dict has the keys `book_id:int, title:str, publisher:str|None, product_type:str, pdf_path:str, sidecar_path:str`.
    - Books are ordered by `id` so the result is deterministic.
  - `write_manifest(books, path: Path) -> None` writes `{"books": [...]}` as JSON.
  - `read_manifest(path) -> dict`.

- [ ] **Step 1: Write failing tests.** Use a temp SQLite file with the `books` columns `id, filepath, display_title, pdf_title, publisher, product_type, is_old_version, is_duplicate`, plus a temp tree of empty files.
  - `test_selects_only_finished_sidecars`: a PDF with `X.json` beside it is selected. A PDF that has only `X-extract.json` is not.
  - `test_excludes_old_and_duplicate`: rows with `is_old_version=1` or `is_duplicate=1`, and filenames containing `.old-`, are excluded.
  - `test_type_filter_and_limit`: only the listed types are returned, the limit is honoured, and the order follows `id`.
  - `test_title_fallback`: `title = display_title or pdf_title or pdf stem`.
  - `test_rejects_filepath_outside_root`: rows whose `filepath` does not start with `source_root` are skipped.
- [ ] **Step 2:** Run `pytest tests/test_rpglib_palace_select.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement. The sidecar is `Path(filepath).with_suffix(".json")`. Check it with `is_file()`.
- [ ] **Step 4:** Run the same command. Expected: all pass.
- [ ] **Step 5:** Commit with the message `feat(rpglib_palace): select books into manifest`.

### Task 2: Fetch sidecars into the local cache

**Files:**
- Create: `pipelines/rpglib_palace/fetch.py`
- Test: `tests/test_rpglib_palace_fetch.py`

**Interfaces:**
- Consumes: the manifest dicts from Task 1.
- Produces: `fetch_all(books: list[dict], cache_dir: Path) -> list[dict]`.
  - Each returned dict is the book dict plus `cache_path:str`, `bytes:int`, `src_mtime:float`, and `status` (one of `copied|cached|missing`).

- [ ] **Step 1: Write failing tests.**
  - `test_copies_new`: a new source gives `status == "copied"`, and the bytes in the cache equal the source.
  - `test_skips_unchanged`: a second call returns `"cached"`. Patch `shutil.copy2` to assert it is not called.
  - `test_recopies_on_change`: if the size or mtime differs, the result is `"copied"` again.
  - `test_missing_source_continues`: one missing and one present source give `["missing","copied"]` and no exception.
- [ ] **Step 2:** Run `pytest tests/test_rpglib_palace_fetch.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement with `shutil.copy2` into `cache_dir/f"{book_id}.json"`. Compare size and `st_mtime` before copying.
- [ ] **Step 4:** Run the same command. Expected: pass.
- [ ] **Step 5:** Commit with the message `feat(rpglib_palace): fetch sidecars to cache`.

### Task 3: Render each book to per-section markdown

**Files:**
- Create: `pipelines/rpglib_palace/render.py`
- Test: `tests/test_rpglib_palace_render.py`

**Interfaces:**
- Consumes: `pipelines.content_ingest.fivetools_render.render_entries_block(entries, depth=0) -> str` and `strip_tags`.
- Produces: `render_book(book: dict, book_json: dict, out_root: Path) -> list[dict]`.
  - Files are written under `out_root/f"b{book_id}"/NNN-<slug>.md`.
  - The function returns one record per file: `{file: str (relative to out_root, POSIX), book_id, title, publisher, section_path: list[str], page: int|None}`.
- Produces: `write_palace_layout(out_root: Path, records: list[dict], books: list[dict]) -> None`.
  - Writes `out_root/mempalace.yaml` with `wing: wing_dmsguild` and one room per book, `{name: f"b{id}", keywords: [f"b{id}"]}`.
  - Writes `out_root/sections.json`, a map from `file` to its record.

**Rendering rules:**
- A section is each top-level node of `book_json["data"]`. If a node is a `section` or `chapter` without a name, it is still its own file, titled `Untitled N`.
- **First line:** `# <title> > <Chapter> > <Section>` (a breadcrumb).
- **Second line:** an HTML comment `<!-- book_id=… page=… -->`. The manifest is the authority for this information; the comment is for human readers.
- **Body:** `render_entries_block(node["entries"])`.
- **Oversized sections:** if the rendered bytes exceed `MAX_FILE_BYTES = 300_000`, split at the node's direct child entries that have a `name`. Each part gets its own file. Its breadcrumb gains the child's name, and its page is the child's `page`, falling back to the parent's. If a single child is still over the limit, split it on paragraph boundaries into `-partK` files. Never truncate.

- [ ] **Step 1: Write failing tests.** Use small inline 5etools fixtures.
  - `test_one_file_per_top_section_with_breadcrumb`: 2 sections give 2 files. The first line of each starts with `# Book > `.
  - `test_lists_and_tables_survive`: a `list` item string and a table cell string both appear in the file text. This is the anti-goal from the spec.
  - `test_oversize_split_no_loss`: monkeypatch `MAX_FILE_BYTES=200`. Every child's text appears in exactly one output file, and no file exceeds the limit unless it holds one paragraph.
  - `test_render_missing_pages`: a missing page gives `page is None`, and the book still renders.
  - `test_layout_files`: `mempalace.yaml` parses and lists the room `b7`. The keys of `sections.json` equal the set of written files.
- [ ] **Step 2:** Run `pytest tests/test_rpglib_palace_render.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the same command. Expected: pass.
- [ ] **Step 5:** Commit with the message `feat(rpglib_palace): render books to section markdown`.

### Task 4: Palace guard + mine wrapper + CLI

**Files:**
- Create: `pipelines/rpglib_palace/guard.py`, `pipelines/rpglib_palace/cli.py`
- Modify: `pyproject.toml` `[project.scripts]` by adding `rpglib_palace = "pipelines.rpglib_palace.cli:main"`
- Test: `tests/test_rpglib_palace_guard.py`

**Interfaces:**
- Produces: `require_pilot_palace(env: Mapping[str,str] = os.environ, home: Path = Path.home()) -> Path`.
  - It raises `PalaceGuardError` with an explanatory message if the path is unset or, after `expanduser().resolve()`, is or sits under a live location: `home/.mempalace` or `home/src/campaigns`.
  - It returns the resolved path otherwise.
- Produces: `mine_command(render_root: Path, palace: Path) -> list[str]`, which returns `["mempalace","mine",str(render_root),"--direct","--wing","wing_dmsguild"]`.
- Produces the CLI `rpglib_palace {select,fetch,render,mine,query}`.
  - The defaults come from Global Constraints. The working directory is `~/rpglib-palace/` and holds `manifest.json`, `fetched.json` and `rendered/`.
  - `mine` runs the guard, then calls `subprocess.run(mine_command(...), env=os.environ, check=True)`, then prints the elapsed seconds and `du -sb` of the palace.

- [ ] **Step 1: Write failing tests.**
  - `test_guard_unset`: an unset path raises an error.
  - `test_guard_default_palace`: `home/.mempalace/palace` raises an error.
  - `test_guard_campaign_palace`: `home/src/campaigns/x/.mempalace` raises an error.
  - `test_guard_resolves_symlink`: a symlink in tmp that points into `home/.mempalace` raises an error.
  - `test_guard_ok`: `home/rpglib-palace/palace` returns the path.
  - `test_mine_command_direct`: `"--direct" in cmd` and `cmd[cmd.index("--wing")+1]=="wing_dmsguild"`.
  - `test_cli_mine_refuses_without_env`: `main(["mine"])` with the env cleared exits non-zero, and `subprocess.run` is never called.
- [ ] **Step 2:** Run `pytest tests/test_rpglib_palace_guard.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. Install into the worktree with `uv pip install -e . --python ~/.venvs/main/bin/python`, but **only if the user approves changing the shared venv**. Otherwise run as `python -m pipelines.rpglib_palace.cli`.
- [ ] **Step 4:** Run the same command. Expected: pass.
- [ ] **Step 5:** Commit with the message `feat(rpglib_palace): palace guard, mine wrapper, CLI`.

### Task 5: Query wrapper

**Files:**
- Create: `pipelines/rpglib_palace/query.py` (wired as `rpglib_palace query "<text>" [--per-book 2] [--fetch 50] [--top 10] [--json]`)
- Test: `tests/test_rpglib_palace_query.py`

**Interfaces:**
- Consumes: `sections.json` from Task 3 and the guard from Task 4.
- Produces: `run_query(text, palace: Path, render_root: Path, search_fn=None, fetch=50, per_book=2, top=10) -> dict`.
  - `search_fn` defaults to `mempalace.searcher.query.search_memories(query, palace_path=str(palace), wing="wing_dmsguild", n_results=fetch)`. Import it lazily, inside the function.
  - The return value is `{results: [{book_id, title, publisher, section_path, page, score, file, text}], distinct_books:int, cap_fired:int, unmapped:[source_file...], latency_s:float}`.
  - `text` is the whole section file, minus its comment line.
- Hits are read from the search result's hit list. Each hit's metadata `source_file` is made relative to `render_root` and looked up in `sections.json`. The implementer checks the actual return shape against `search_memories` and pins it in the fake.

**Behaviour:**
- Several chunks from the same file collapse to one result, keeping the best score.
- Results keep the search order.
- The per-book cap counts files per `book_id`.
- `cap_fired` counts the hits dropped by the cap.

- [ ] **Step 1: Write failing tests** with a fake `search_fn` and a tmp render root.
  - `test_expands_to_whole_section`: the result `text` equals the whole file body.
  - `test_dedupes_chunks_of_same_file`.
  - `test_cap_two_per_book`: 5 hits from one book and 1 from another give 3 results, with `cap_fired == 3` and `distinct_books == 2`.
  - `test_unmapped_reported`.
  - `test_query_refuses_live_palace`: the guard is invoked.
- [ ] **Step 2:** Run `pytest tests/test_rpglib_palace_query.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. Human output prints `[n] Title (book <id>) — A > B > C, p.<page>`, then the first 600 chars, then `--- distinct books: X, cap fired: Y, unmapped: Z, latency: Ns`. `--json` dumps the dict.
- [ ] **Step 4:** Run `pytest tests/test_rpglib_palace_*.py -v`. Expected: all pass.
- [ ] **Step 5:** Commit with the message `feat(rpglib_palace): query wrapper with section expansion and per-book cap`.

### Task 6: Pilot run + evaluation record (orchestrator, with the GM)

**Files:**
- Create: `docs/rlm/rpglib_palace_pilot.md`, a how-to plus results. It holds:
  - the commands;
  - the ingest time, palace size and per-query latency;
  - anything that broke (chunk cap, skips);
  - a table of the GM's ~10 queries with the columns *whole write-ups? / distinct books in top 10 / useful surprise?*

- [ ] **Step 1:** In the worktree, set `export MEMPALACE_PALACE_PATH=~/rpglib-palace/palace`, then run `select`, `fetch` and `render`.
  - Expected: about 50 books, with 0 `missing` or a listed few. The rendered tree exists.
- [ ] **Step 2:** Run `rpglib_palace mine` in the background.
  - Expected: it exits 0 and prints the elapsed seconds and palace bytes.
  - Then run `ls ~/.mempalace/palace` and confirm its mtime is unchanged from before the run. This is the isolation proof.
- [ ] **Step 3:** Smoke-test with `rpglib_palace query "druid hermit"` and `rpglib_palace query "tavern"`.
  - Expected: results with titles, section paths and pages, and `unmapped: 0`.
- [ ] **Step 4:** Hand the query command to the GM, who runs about 10 real prep queries. Record their judgments verbatim in the doc. The GM is the judge, so do not grade on their behalf.
- [ ] **Step 5:** Commit the doc. Run one `/code-review` pass on the branch. Fix confirmed findings; file the rest, plus any deferred gaps, as sub-issues of the pilot's parent issue (create it if absent).
