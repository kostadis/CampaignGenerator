# Contract: `kind="passage"` in `rpg_retriever`

## Tier order

No scores are normalized across tiers.

1. `drawer` and `statblock`: the campaign palace, in MemPalace's native order.
2. **`passage`**: the library, in library search order, after the per-book cap. At most `k_library` passages (default 10).
3. `candidate`, `cost="cheap"`
4. `candidate`, `cost="expensive"`. A book that has any passage in tier 2 is excluded, just as drawer-covered books already are.

## Record

```json
{
  "kind": "passage",
  "book_id": 2443,
  "title": "Cottage on the Long Road",
  "publisher": "...",
  "section_path": ["The Setup"],
  "page": null,
  "score": 0.71,
  "preview": "first 600 chars …",
  "library_file": "b2443/003-the-setup.md"
}
```

The full text is **not** inlined in `rpg_search` output. An agent fetches it with `library_search` or by `library_file`.

## Parameters

| Surface | New parameters |
|---|---|
| `retrieve()` | `include_library: bool = True` and `k_library: int = 10` |
| `rpg_search` MCP tool | `include_library: bool = True` and `k_library: int = 10` |
| `rpg_retriever` CLI | `--no-library` and `--k-library` (names follow the existing `--k-cheap` and `--k-expensive`) |
| `propose_dossier` | The same two parameters. Passages render into the proposal like drawers, labeled `passage`, for the GM to approve. |

## Behaviour when the library is not configured or not built

- The tier is empty.
- `RetrievalResult` gains `library_status: "ok" | "not_configured" | "not_built" | "embedder_mismatch"` and a matching reason.
- Every other tier is unchanged: the existing tests pass unmodified (Story 3, scenario 2).
