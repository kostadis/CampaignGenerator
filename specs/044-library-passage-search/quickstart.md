# Quickstart: validating Library Passage Search

## Prerequisites

- `~/.config/hypostasis/hypostasis.yaml` has an `env:` block and a `library:` block (see contracts/authority-config.md). Use a small selection, for example `book_ids` with about 50 entries.
- The Drive folder is readable (local, not streaming).
- The embedder endpoint answers.

## Scenarios

1. **Not configured** (FR-002, exit 3). Remove `library.selection`, then run `library status`. Expected: exit 3, and the message names the key.
2. **Isolation** (FR-001, exit 6). Point `library.palace` at `~/.mempalace/palaces/x`, then run `library build`. Expected: exit 6, and nothing is created.
3. **Build** (FR-015). Run `library build`. Expected: exit 0, and a BuildReport with selected, indexed and skipped books (each with a reason), plus passage count, time and size.
   - Before and after the build, record the newest file mtime under `~/.mempalace/palaces`. The two must be equal (SC-006).
4. **Search** (FR-008/009/010). Run `library search "tavern keeper statblock" --json`. Expected:
   - every result is a whole section file;
   - no book appears more than twice;
   - the output contains `distinct_books`, `cap_fired` and `unmapped`.
5. **Refresh** (FR-006, SC-005). Run `touch` on one selected book's sidecar in the cache source, or edit it. Then run `library refresh`. Expected: `changed` contains exactly that book, and it takes far less time than the build.
6. **Embedder mismatch** (FR-007, exit 5). Change `MEMPALACE_EMBEDDING_MODEL` in the shell, then run `library search x`. Expected: exit 5, and the message names both models.
7. **RLM tier** (FR-013). Run `rpg_retriever "tavern keeper"`. Expected:
   - `kind="passage"` hits appear after drawers and before candidates;
   - a book with passages does not also appear as an expensive candidate.
   Then run with `--no-library`. Expected: the same output as before this feature.
8. **Agent** (Story 1). In a Claude session with the campaign MCP server, ask: "use the library to find me a statblock for a tavern keeper". Expected: the answer cites `title (book id) — section`, and every quoted detail appears in that passage.

## Automated

```bash
python -m pytest tests/test_library_*.py tests/test_rpg_retriever*.py tests/test_retrieve_render_isolation.py
```
