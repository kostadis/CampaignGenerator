# Contract: `REVIEW_STALE_CUSTODY` refusal detail

The code stays `REVIEW_STALE_CUSTODY` (FR-005). The exit code stays 3, from `_exit_for`, because the code contains "STALE". Nothing is written for any item in the batch (FR-002).

The detail is raised by:

- `review decide` (`save_decisions`), including `review npc sign`, `carry --write`, `policy --write` and `noise decide --write` through `submit_decisions`;
- `review import` (`import_review_bundle`), with `"operation": "import"`.

## CLI `--json` envelope

```json
{
  "ok": false,
  "code": "REVIEW_STALE_CUSTODY",
  "message": "REVIEW_STALE_CUSTODY: 2 source file(s) changed; 3 submitted item(s) depend on them; nothing was saved",
  "artifacts": [],
  "data": {
    "version": 1,
    "operation": "decide",
    "review_id": "npc-review-6ee694eebf5b",
    "review_generation": 5,
    "changed_files": [
      {
        "path": "docs/npcs/summary_native/ch001-086/draft/npc_nug.md",
        "source_id": "draft-…",
        "role": "draft",
        "state": "changed",
        "items": [
          {"item_id": "npc-signoff-…", "npc": "nug", "action": "signoff_npc_draft"},
          {"item_id": "npc-…",         "npc": "nug", "action": "review_claim_against_evidence"}
        ]
      },
      {
        "path": "docs/summaries/010-session-the-seer.md",
        "source_id": "summary-…",
        "role": "summary",
        "state": "missing",
        "items": [{"item_id": "npc-…", "npc": "blasius", "action": "review_presentation"}]
      }
    ],
    "stale_items": [
      {"item_id": "npc-…", "npc": "blasius", "paths": ["docs/summaries/010-session-the-seer.md"]},
      {"item_id": "npc-…", "npc": "nug", "paths": ["docs/npcs/summary_native/ch001-086/draft/npc_nug.md"]},
      {"item_id": "npc-signoff-…", "npc": "nug", "paths": ["docs/npcs/summary_native/ch001-086/draft/npc_nug.md"]}
    ],
    "by_npc": [
      {"npc": "blasius", "item_ids": ["npc-…"], "paths": ["docs/summaries/010-session-the-seer.md"]},
      {"npc": "nug", "item_ids": ["npc-…", "npc-signoff-…"], "paths": ["docs/npcs/summary_native/ch001-086/draft/npc_nug.md"]}
    ],
    "remedy": {
      "command": "summary_native review refresh npc-review-6ee694eebf5b --expected-generation 5",
      "note": "A changed draft also needs a new verification review before its sign-off can be approved."
    }
  }
}
```

Rules:

- `changed_files` contains **only** files that some submitted item depends on, sorted by `path`. Each lists **only** the submitted items that depend on it, sorted by `item_id`.
- `stale_items` lists **every** stale item in the batch (SC-003), sorted by `item_id`. An item with an empty dependency set appears with `"paths": []` and `"reason": "no_dependency"`.
- `by_npc` is sorted by `npc`, with `null` last.
- `npc` is `custody.npc_label(item)`: `registry_name`, else the draft stem without `npc_`. It may be `null`.
- `remedy.note` is present only when some changed file has role `draft` (research R14).
- `state` ∈ `changed`, `missing`, `unreadable`.

## CLI text mode

```
REVIEW_STALE_CUSTODY: 2 source file(s) changed; 3 submitted item(s) depend on them; nothing was saved
  changed  docs/npcs/summary_native/ch001-086/draft/npc_nug.md: nug — npc-…, npc-signoff-…
  missing  docs/summaries/010-session-the-seer.md: blasius — npc-…
Bring them current: summary_native review refresh npc-review-6ee694eebf5b --expected-generation 5
A changed draft also needs a new verification review before its sign-off can be approved.
```

## Local routes (`/api/reviews/*`, `server/routers/review_routes.py`)

The status is unchanged, from `_status_for("REVIEW_STALE_CUSTODY")`. The body is `{"ok": false, "code", "message", "data": <detail>}`. `data` is relayed verbatim when the envelope's `data` is a dict. Otherwise it is omitted.

## Capability service (`review/web/app.py`, phone)

The status is 409. The body is:

```json
{"ok": false, "code": "REVIEW_STALE_CUSTODY",
 "message": "Source files changed since this review was built. Nothing was saved.",
 "detail": {"changed_files": [{"path": "…", "state": "changed", "items": [{"item_id": "…", "npc": "…"}]}],
            "stale_items": ["npc-…"],
            "remedy": "summary_native review refresh … --expected-generation 5",
            "truncated": {"changed_files": 4, "items": 12, "stale_items": 30}}}
```

`truncated` is present only when a cap below left something out, and names how many entries were omitted: `changed_files` (files beyond the cap), `items` (items beyond the cap inside the files that are shown) and `stale_items`. Its values are non-negative integers; a key is absent when nothing was omitted of that kind.

`detail` is **rebuilt from a whitelist**. Only the keys above are kept, values must be `str` or `null` (except `truncated`'s integer counts, which the service computes), strings are capped at 512 characters, and lists at the configured `max_batch_decisions`. Any other shape drops `detail` entirely, and the rest of the body is unchanged. The other stale codes keep their current body.

`viewer.js` renders `detail.changed_files` as a list under `#save-state` and shows `#reload`; when `detail.truncated` is present it adds an "and N more" line for each omitted kind.
