# Library passage search — how-to

**Command:** `library` · **MCP tools:** `library_search`, `library_verify_citation` (in `pipelines/rlm/mcp_server.py`) · **Spec:** `specs/044-library-passage-search/`

This page is task-oriented: "I want to do X, what do I type." Everything below was checked
against the code in `pipelines/library/`, not against the spec. Where the two differ, the code
is what you get (see "Where the spec and the code differ" at the end).

---

## What this is, and what it is not

The library is a **searchable index of your converted DMsGuild books**. A book is *converted* when
`pdf-translators` has written a 5etools-shaped JSON sidecar next to its PDF. `library build` reads
those sidecars, renders **one markdown file per section** (a section is the unit of every hit),
mines them into its own isolated MemPalace palace under the `wing_dmsguild` wing, and
`library search` returns **whole sections**, with the full text, so an agent can quote them.

It is not:

- **A UI.** There is no web page and no button. The commands below are the whole surface.
- **Bring-up.** Creating the config, choosing the palace path, picking the embedder and
  deciding *when* to build or refresh belongs to hypostasis (`local_machine#1`). This is "option A":
  **CampaignGenerator owns build and refresh, hypostasis decides when to run them.** CG
  only reads the config; it never writes it and has no defaults of its own.
- **A live palace.** The library palace is refused if its path resolves under `~/.mempalace` or
  `~/src/campaigns` (exit 6). Your campaign memory is never touched.
- **A model call.** Nothing in `pipelines/library/` calls an LLM. Search, rendering, citation
  checking are all deterministic.
- **A fixer of dirty books.** Converted JSON is dirty (promoted table cells, stray headings, missing
  pages). That is expected. You fix the book's JSON and refresh; the library does not clean it
  for you.

---

## The config: `~/.config/hypostasis/hypostasis.yaml`

CG reads two blocks, plus one top-level key, from this file (`pipelines/library/config.py`).
Hypostasis seeds and owns it. The path is fixed; there is no `--config` flag.

```yaml
rpg_library_db: ~/path/to/rpg_library.sqlite   # top-level; the books table is read from it, read-only

env:                                            # merged into the mine/search environment
  MEMPALACE_BACKEND: turbovec                   # REQUIRED
  MEMPALACE_EMBEDDING_PROVIDER: ollama
  MEMPALACE_EMBEDDING_MODEL: qwen3-embedding:0.6b
  MEMPALACE_EMBEDDING_ENDPOINT: http://192.168.56.1:11434

library:
  palace: ~/.local/share/hypostasis/library/palace   # REQUIRED; must not be under ~/.mempalace or ~/src/campaigns
  work_dir: ~/.local/share/hypostasis/library        # REQUIRED; same live-location refusal (exit 6); rendered tree, ledger, manifest, embedder stamp
  source_root: "/mnt/g/My Drive/DriveThru/Dungeon Masters Guild"   # REQUIRED; a book must live under it
  cache_dir: ~/.local/share/hypostasis/library/cache # optional; defaults to <work_dir>/cache; same refusal as work_dir
  selection:                                         # REQUIRED; exactly ONE of the three forms
    product_types: [adventure, setting, gm_aid]
    # book_ids: [2443, 2475]
    # all_converted: true
  exclude_book_ids: []                               # optional
```

Rules the code enforces:

- **`env:` never overrides your shell.** Only keys starting `MEMPALACE_` are merged, and only if
  not already in the process environment. `MEMPALACE_BACKEND` must be in one or the other, or
  every command refuses (exit 3). There is no default backend.
- **Selection forms.** `product_types` filters by the DB's `product_type`; `book_ids` names books
  explicitly and is the GM's word (old-version and duplicate rows are *not* dropped for it, and
  twin-dedupe is skipped); `all_converted: true` takes every book. For the first and third forms, rows
  flagged `is_old_version` / `is_duplicate` are dropped, files named `*.old-*` are dropped, and
  printer-friendly twins of the same title *and publisher* are collapsed to one book (two
  publishers with the same title are both kept).
- **Explicit ids that are not selected are reported.** A `book_ids` entry that is dropped (id not in
  the DB, no filepath, outside `source_root`, `.old-` file, no sidecar) and any book hit by
  `exclude_book_ids` appear in the report's `skipped` list with a reason, and count in `selected`.
  For `product_types` / `all_converted`, a book with no finished sidecar is simply not selected and
  is not reported.
- **A book is selected only if** its `filepath` is under `source_root` **and** the `.json`
  sidecar next to the PDF exists. An unconverted book is silently not selected.
- **The embedder is stamped at build time** (`<work_dir>/embedder.json`: backend, provider, model,
  endpoint). Search, refresh and status compare backend/provider/model against the current `env:`.

---

## Task: build the library

```
library build            # human summary
library build --json     # full BuildReport
```

Output: `built: 612/667 books, 41210 passages, 55 skipped, 0 failed, 2310.4s`.

A build **replaces** the previous one: it deletes the previous build's drawers (room per book,
`b<book_id>`), wipes `<work_dir>/rendered`, re-copies sidecars to the cache (a sidecar whose
size and mtime already match is reused), re-renders every selected book and mines the whole tree.
Budget on the order of tens of minutes for the full library (the design estimate was about 40
minutes for roughly 667 books). Run it in a terminal that will stay open.

Per-book outcomes in the report:

| Bucket | Meaning |
|---|---|
| `skipped`, reason `sidecar missing` | The selected book's JSON vanished between selection and copy. |
| `skipped`, reason `unreadable sidecar: ...` | The JSON does not parse. Fix the file. |
| `skipped`, reason `no sections` | The JSON parsed but has no `data` (nor `adventureData`/`bookData`) sections. |
| `failed`, reason `render error: ...` | One book raised during render. It is dropped; the rest of the build continues. |

| `failed`, reason `could not delete old drawers: ...` | The old drawers of a previously built book could not be removed; the book is not re-mined (no mining over stale drawers). The next build/refresh retries it. |
| `failed`, reason `mine failed: ...` | The mine itself raised. Every book of that run is marked `failed` (never `indexed`), the command exits 1, and (for `build`) the embedder stamp is removed so the library reads as not built. The next `refresh`/`build` retries. |

One bad book never sinks a build. Exit is 0 even with skips and failures; read the counts.

## Task: refresh after fixing a book's JSON

You edited a book's sidecar (or added or removed a book in the selection):

```
library status           # "stale: N" tells you how many sidecars changed since the build
library refresh
```

Refresh compares each selected book's sidecar **size and mtime** against the ledger
(`<work_dir>/library_ledger.json`). Changed, newly selected or previously non-indexed books are
re-rendered; books that left the selection are dropped. For each changed or removed book it
**deletes that book's drawers first**, then mines only the new files, so stale text never
survives next to fixed text. Unchanged books are not touched. A book is marked `indexed` (and its new size/mtime saved) only
after its mine succeeds; a failed mine or failed delete leaves it `failed`, so the next refresh retries it.
Output:
`refreshed: changed [2443], removed [], 612 books / 41210 passages, 0 skipped, 0 failed, 18.2s`.

Refresh requires a built library and a matching embedder (exits 4 and 5, below). If you
changed the embedder, you must `library build`, not refresh.

## Task: search

```
library search "haunted lighthouse with a sympathetic villain"
library search "mushroom folk trading post" --limit 5 --per-book 1
library search "..." --json
```

`--limit` (default 10) is the number of passages returned; `--per-book` (default 2) caps how many
come from one book so one big adventure cannot fill the page. Hits from the palace are expanded to
the **whole section**, ranked by best chunk similarity. Human output:

```
[1] The Lost Lighthouse (book 2443) — Chapter 2 > The Keeper's Quarters, p.14
<first 600 characters of the section>

--- distinct books: 6, cap fired: 3, unmapped: 0, latency: 0.84s
```

`p.?` means the source JSON carried no page. `cap fired` counts hits dropped by `--per-book`.
`unmapped` counts palace hits whose file is not in the current section manifest (a sign the
palace and `rendered/sections.json` have drifted; rebuild). With `--json` each result has
`book_id`, `title`, `publisher`, `section_path` (list), `page` (int or null), `score`, `file`
(path under the rendered tree, e.g. `b2443/007-the-keepers-quarters.md`) and the **full** `text`.

## Task: check health

```
library status
library status --json
```

Prints `configured: yes, built: yes, books: 612, stale: 0, embedder match: True, palace: ..., index bytes: ...`
and fails when appropriate (exit 4 not built, exit 5 embedder mismatch). `stale` counts books whose
sidecar size/mtime differs from the ledger (or whose sidecar is gone); the fix is `library refresh`.
`status` never touches the palace and calls no model.

## Task: verify a quotation

```
library verify-citation b2443/007-the-keepers-quarters.md "the lamp has not burned in forty years"
library verify-citation b2443/007-the-keepers-quarters.md "..." --json
```

`file` is the result's `file` field. The check is deterministic: whitespace runs are collapsed
and **nothing else is normalised** (case, punctuation and spelling must match). Output is
`found at offset N` (exit 0) or `NOT FOUND` (exit 1). JSON: `{"file", "found", "offset"}`. A file
that does not exist, or an empty quote, is `NOT FOUND`. A path that escapes the rendered tree is
refused (exit 1, `library: <file> is outside the rendered library tree; refusing`). It needs the
config (for `work_dir`) but not a built palace or a matching embedder.

---

## Exit codes and refusals

Every message is printed to stderr as `library: <message>`. Exit codes are shared by all
subcommands (`pipelines/library/__init__.py`). Codes 3 and 4 match hypostasis's "not configured"
and "not set up" so it can pass them through.

| Exit | Meaning | Message (abridged) | Fix |
|---|---|---|---|
| 0 | OK | | (`--help` also exits 0) |
| 1 | Failed | `library: failed: <exception>`; or `library.source_root <path> is not readable; mount it or fix library.source_root ... (no library was written)`; or a failed mine | Mount the source drive / fix `source_root`; read the exception. A `verify-citation` miss is also 1. |
| 2 | Usage | argparse error | Check the subcommand and flags. |
| 3 | Not configured | `hypostasis config not found: <path>; run hypostasis setup` | Run hypostasis setup, or create the file. |
| 3 | | `<path> has no library: block; add one` | Add the `library:` block (see above). |
| 3 | | `<path> library.palace\|work_dir\|source_root is not set` | Set that key. |
| 3 | | `<path> has no top-level rpg_library_db key` | Add `rpg_library_db`. |
| 3 | | `library.selection is missing` / `is empty; set exactly one of product_types / book_ids / all_converted under library.selection` | Declare one selection form. |
| 3 | | `library.selection uses more than one form (a, b); ...` | Keep exactly one form. |
| 3 | | `library.selection.<form> must be a list` / `all_converted must be true` | Fix the value's type. |
| 3 | | `<path> has no env.MEMPALACE_BACKEND; refusing to use a default backend` | Set `env.MEMPALACE_BACKEND` in the file (or the shell). |
| 4 | Not built | `the library at <work_dir> has not been built; run \`library build\` (hypostasis setup builds it when no library exists)` | `library build`. Also what `search` and `refresh` say before the first build; `status` prints `library: not built; ...` after its output. |
| 5 | Embedder mismatch | `the library was built with A/B/C but the current config uses X/Y/Z; searching would return garbage. Restore the embedder in hypostasis.yaml env: or rebuild with \`library build\`.` | Restore the old `env:` values, or `library build` with the new embedder. `status` prints a shorter `library: embedder mismatch; ...`. |
| 6 | Refused | `library.palace <p> resolves to <q>, inside live location <root>; refusing. Set library.palace ... to an isolated path.` | Point `library.palace` somewhere isolated. The guard refuses a path that equals, is inside, or is an ancestor of any live location: the mempalace config dir (`$MEMPALACE_CONFIG_DIR`, else `~/.mempalace`), every palace in that dir's `config.json` (`palaces` map and `palace_path`), hypostasis `paths.mempalace`, or `~/src/campaigns` (symlinks resolved first; so `~` and `~/src` are refused). The message names which live location matched and how. |
| 6 | Refused | `... an unmarked existing palace (non-empty, no .library-palace marker)` | `library.palace` already holds files that `build` did not create (an unregistered palace). Pick an empty/new path. `build` writes a `.library-palace` marker into the palace dir (and `refresh` rewrites it after a mine); a palace built before this check needs `touch <palace>/.library-palace` once. Applies to the palace only, not `work_dir`. |

Through MCP the same conditions come back as `{"error": "<code>", "message": ...}` with code
`not_configured`, `not_built`, `embedder_mismatch`, `refused` or `failed`.

---

## The agent workflow

The same steps apply to an agent using the MCP tools or the CLI.

1. **`library_search(query, limit=10, per_book=2)`.** Try two or three wordings before concluding
   nothing matches. The result carries each passage's full text.
2. **Read the passage.** Never recommend from a title or a section name alone.
3. **`library_verify_citation(file, quote)`** on **every** quotation before presenting it, using the
   result's `file`. Drop or flag any quote that returns `found: false`.
4. **Cite** every recommendation as `title (book id) — section`, for example
   `The Lost Lighthouse (book 2443) — Chapter 2 > The Keeper's Quarters`. Add a page only if the
   result has one.
5. **Say plainly when nothing matches.** Do not invent a source.

This is a precision step, not a rendering step: the agent surfaces candidates; the GM judges
them, and only the GM decides what enters campaign material.

---

## Passages in `rpg_search`, `rpg_retriever` and dossier proposals

The library is also a **tier** in the existing tiered retrieval (`docs/rlm/rlm_pipeline.md`).
It is on by default:

- **`rpg_search` (MCP)** and **`rpg_retriever` (CLI)** gain `kind: "passage"` hits, ranked after
  drawer/statblock hits and before cheap and expensive candidates. Controls: `include_library`
  (MCP; default true), `k_library` (default 10), and `--no-library` / `--k-library N` on the CLIs
  (`rpg_retriever`, `dossier_proposer`).
- A passage hit carries `book_id`, `title`, `publisher`, `section_path`, `page`, `score`,
  `library_file`, and a **600-character preview** (ending `…` when cut). The preview is not the
  passage: fetch the whole text with `library_search`.
- **The tier never fails a search.** If the library is not configured or built, or the embedder
  has changed, the other tiers return as usual and the result carries
  `library_status` (`ok`, `not_configured`, `not_built`, `embedder_mismatch` or `unavailable`) and a
  `library_reason`. With `--no-library` / `include_library=False` neither field appears and the
  output is unchanged from before the feature.
- **Dossier proposals** (`docs/dossier_proposal.md`) get a "Library Passages (DMsGuild library; read
  in full with library_search)" slot, shown only when there are passages. Render pipelines still
  consume the approved proposal, never raw retrieval; the GM approves a passage before it is
  used.

---

## Known limits

- **Dirty converted JSON is expected.** Section boundaries come from the JSON's own headings,
  so a promoted table cell can become a section and a real section can be split. You fix the JSON
  (the library has no cleanup mode) and run `library refresh`.
- **Pages only when present.** `page` is an int only when the JSON carries an integer `page` for
  that section; otherwise it is `null` and shown `p.?`. Never cite a page the result does not have.
- **A section is capped at 300,000 bytes.** An oversized section is split at paragraph breaks into
  `-part1`, `-part2` files; nothing is truncated.
- **Hits are ranked by chunk similarity, one score per section** (the best chunk). Scores from
  different embedders are not comparable, and the library score is never merged with drawer scores.
- **Only converted books are searchable.** No sidecar, no passages.
- **Staleness is size + mtime.** An edit that preserves both (rare) will not be seen by `refresh`;
  `library build` always re-does everything.

---

## Where the spec and the code differ

- Contract: `verify-citation` exit 1 on "not found". Code also returns 1 for a path outside the
  rendered tree (a refusal, not a miss), printing `library: ... refusing`.
- `--help` exits 0, not 2.
- The tier's `library_status` and `library_reason` are an addition not described by the spec's
  CLI contract; see `specs/044-library-passage-search/contracts/retrieval-kind.md`.


## Hit-cap shortfall

The palace search returns at most 100 raw hits. Expanding hits to sections, dropping duplicates and the
per-book cap can leave fewer than `--limit` results. When the raw request hit the cap and results fell
short, the human output ends with `note: shortfall N ...`, and `--json` / the MCP tool carry `raw_hits`,
`raw_cap` and `shortfall` (0 when the cap was not hit). Refine the query or raise `--per-book`.
