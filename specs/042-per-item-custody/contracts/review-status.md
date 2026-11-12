# Contract: `review status` — stale items by NPC

`summary_native review status REVIEW [--json]`. It is read-only, and it is exposed at `GET /api/reviews/{review_id}/status`, which the launcher's "Refresh status" button calls.

The existing keys `review_id`, `generation`, `item_count` and `counts` are **byte-for-byte unchanged** (FR-007). `counts.stale` keeps its meaning: items marked stale by a refresh.

Two keys are added. Both are computed from the **current files** at call time:

```json
{
  "review_id": "npc-review-6ee694eebf5b",
  "generation": 5,
  "item_count": 781,
  "counts": {"pending": 0, "approved": 0, "rejected": 0, "discussed": 0, "withdrawn": 0, "stale": 0},
  "changed_files": [
    {"path": "docs/npcs/summary_native/ch001-086/draft/npc_nug.md", "role": "draft", "state": "changed", "stale_item_count": 3}
  ],
  "stale_by_npc": [
    {
      "npc": "nug",
      "npc_key": "docs/npcs/summary_native/ch001-086/draft/npc_nug.md",
      "stale_item_count": 3,
      "stale_item_ids": ["npc-…", "npc-…", "npc-signoff-…"],
      "changed_files": [{"path": "docs/npcs/summary_native/ch001-086/draft/npc_nug.md", "state": "changed"}]
    }
  ]
}
```

Rules:

- When no source changed, both lists are `[]` (US3 scenario 1).
- `changed_files` lists only custody sources that are not `current`, sorted by path. `stale_item_count` is the number of items in the review that depend on the file.
- `stale_by_npc` has one entry per `npc_key` with at least one stale item, sorted by `npc`, then `npc_key`. An NPC with no stale item never appears (US3 scenarios 2 and 3).
- A changed file that **no** item depends on, which cannot happen under R7's rule, would appear in `changed_files` with `stale_item_count: 0`.
- Text mode prints the existing message and the JSON data, as today.
