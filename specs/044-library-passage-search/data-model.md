# Data Model: Library Passage Search

All state lives on disk under `library.work_dir`, except the palace itself, which lives at `library.palace`. Both locations come from the authority file (see contracts/authority-config.md).

## LibraryConfig

This is read from `hypostasis.yaml` and is never written by CG.

| Field | Type | Rule |
|---|---|---|
| palace | path | Required. After `resolve()`, it must not be under `~/.mempalace` or `~/src/campaigns` (FR-001). |
| source_root | path | Required. The DMsGuild folder. It must be readable at build time, otherwise the build fails and is never reported as an empty success. |
| cache_dir | path | Default `<work_dir>/cache`. |
| work_dir | path | Required. Holds the manifest, ledger, rendered tree and stamp. |
| selection | Selection | Required. A missing or empty selection means "not configured" (FR-002). |
| env | map | From the top-level `env:` block (`MEMPALACE_BACKEND`, `MEMPALACE_EMBEDDING_*`). |

## Selection

Exactly one of these three forms:
- `product_types: [str]`
- `book_ids: [int]`
- `all_converted: true`

Optional `exclude_book_ids: [int]`.

## LibraryBook (`manifest.json` → `books[]`)

| Field | Type | Notes |
|---|---|---|
| book_id | int | rpg-lib `books.id` |
| title | str | `display_title` → `pdf_title` → pdf stem |
| publisher | str? | |
| product_type | str? | |
| pdf_path | str | |
| sidecar_path | str | The finished `<stem>.json` |

**Validation**: the sidecar exists. The book is not old or a duplicate. Print-friendly twins are deduped, except for explicit `book_ids` (FR-003).

## LedgerEntry (`library_ledger.json` → `{book_id: entry}`)

| Field | Type | Notes |
|---|---|---|
| src_size, src_mtime | int, float | Change detection (FR-006) |
| render_hash | str | sha256 of the concatenated rendered files |
| files | [str] | Section files, relative to `rendered/` |
| status | enum | `indexed`, `skipped`, or `failed` |
| reason | str? | Required when status is `skipped` or `failed` (FR-015) |
| updated_at | ISO str | |

**State transitions** for each book:

- (absent) → `indexed`, `skipped` or `failed`.
- `indexed` → `indexed` again on refresh, when the source changed.
- Any state → removed, when the book leaves the selection. The book's drawers are deleted from the palace.

## Passage (`rendered/b<id>/NNN-<slug>.md` + `sections.json[file]`)

| Field | Type | Notes |
|---|---|---|
| file | str | Relative POSIX path. This is the key. |
| book_id, title, publisher | | Copied from LibraryBook |
| section_path | [str] | The breadcrumb, excluding the title |
| page | int? | Null when the source has no page (it is never invented) |
| merged_titles | [str] | Only when `--merge-fragments` is used |
| text | str | The file body. It is returned verbatim. |

## EmbedderStamp (`work_dir/embedder.json`)

`{backend, provider, model, endpoint, built_at}`. It is written at build time. On search, it is compared with the current config: a mismatch makes the search refuse with a message naming both setups (FR-007).

## SearchResultSet

```
{ query, results: [{book_id, title, publisher, section_path, page, score, file, text}],
  distinct_books, cap_fired, unmapped: [str], latency_s }
```

**Invariants**:
- At most `per_book` results per `book_id` (FR-009).
- Each `file` appears at most once (FR-008).
- No hit is dropped silently; a hit that cannot be traced to a book goes into `unmapped` (FR-010).

## BuildReport

`{selected, indexed, skipped: [{book_id, reason}], failed: [{book_id, reason}], passages, elapsed_s, index_bytes, changed: [book_id], removed: [book_id]}` (FR-015).
