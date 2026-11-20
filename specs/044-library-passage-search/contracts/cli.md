# Contract: `library` CLI

The console script is `library`, registered in `pyproject.toml [project.scripts]`. Every subcommand is non-interactive (FR-018), and every subcommand reads its configuration only from the authority file (see authority-config.md). Every subcommand takes `--config PATH` (short `-c`; `~` is expanded; default `~/.config/hypostasis/hypostasis.yaml`) to read a different authority file; a missing file at that path exits 3 naming the path. The flag goes after the subcommand, e.g. `library status --json --config PATH`.

| Subcommand | Purpose | Output |
|---|---|---|
| `library build [--config PATH]` | Full build from the declared selection | BuildReport (human-readable; `--json` for machine-readable) |
| `library refresh [--config PATH]` | Re-processes only books that were changed, added or removed | BuildReport, including `changed` and `removed` |
| `library search "<query>" [--limit 10] [--per-book 2] [--json] [--config PATH]` | Whole-section search | SearchResultSet |
| `library verify-citation <file> "<quote>" [--json] [--config PATH]` | Checks that a quoted span appears verbatim in a library passage (SC-002). Whitespace is normalized and nothing else is. | `{file, found: bool, offset}`; exit 0 if found, 1 if not |
| `library status [--json] [--config PATH]` | Health check. Counts selection drift as staleness. | `{configured, built, books, stale: [id], added: [id], removed: [id], embedder_match, palace, index_bytes}`. `stale` = changed sources + `added` + `removed`; `added` = selected but not in the ledger; `removed` = in the ledger but no longer selected (the same sets `refresh` adds/removes). Exit codes unchanged: drift alone is exit 0. |

## Exit codes (shared by every subcommand)

| Code | Meaning |
|---|---|
| 0 | ok |
| 1 | failed (an exception, an unreadable source root, or a mine error) |
| 2 | usage error |
| 3 | not configured (the `library:` block is missing, or there is no selection) |
| 4 | library not built (search, refresh or status run before any build) |
| 5 | embedder mismatch (search or status) |
| 6 | refused: the palace path resolves into a live palace |

Codes 3 and 4 match `local-machine hypostasis`'s "not configured" and "not set up" codes, so hypostasis can pass them straight through.

## Refusal messages

Each refusal message:
- names the cause;
- gives the exact fix, either the authority-file key to set or the command to run;
- for exit 4, names the hypostasis step that provides the library.
