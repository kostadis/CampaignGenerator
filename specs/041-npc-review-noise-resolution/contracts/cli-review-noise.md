# Contract: `summary_native review noise`

Both forms take the standard `_scope_args` (`--campaign-dir`, `--json`, …), like every other `review` verb.

## `review noise REVIEW`

This verb only reads.

`--json` output:

```json
{
  "review_id": "npc-review-…",
  "review_generation": 7,
  "classes": [
    {
      "noise_class": "label",
      "legacy_code": "noise-label",
      "count": 281,
      "undecided": 281,
      "approved": 0,
      "rejected": 0,
      "occurrences": [
        {"item_id": "npc-…", "npc": "Blasius", "draft_path": "…", "line": 14,
         "token": "036", "sentence": "In Chapter 036, Blasius warns…",
         "cited_scenes": ["ch 036 / 036.04"], "resolved_by": "Chapter 036",
         "decision": null}
      ]
    }
  ]
}
```

- Classes always appear in precedence order. A class with zero occurrences is listed with `count: 0`.
- Text mode prints one line per class: `label  281 (281 undecided)`.

## `review noise decide REVIEW --class C --verdict {approve,reject} --reviewer R --note N [--write]`

| Condition | Result |
|---|---|
| no `--class` | argparse error (Principle X: no implicit all) |
| `C` not in the six classes | exit 2, `REVIEW_NOISE_UNKNOWN_CLASS: <C>; expected one of label, idiom, …` |
| `C` has 0 undecided occurrences | exit 2, `REVIEW_NOISE_NOTHING_TO_DECIDE: class <C> has no undecided occurrences` |
| blank `--note` | exit 2, `REVIEW_NOISE_NOTE_REQUIRED` |
| note exceeds `max_note_chars` once prefixed | exit 2, `REVIEW_NOISE_NOTE_TOO_LONG` |
| no `--write` | dry run: prints the planned count and item ids, writes nothing, exit 0 |
| `--write` | one decision per undecided occurrence, through `submit_decisions`, exit 0; prints `decided <n> occurrence(s) of <C> as <verdict>` |

- Already-decided occurrences are skipped and reported under `already_decided`. They are never overwritten.
- `--json` returns `{review_id, review_generation, noise_class, verdict, planned: [item_id…], already_decided: [item_id…], written: bool}`.

## UI face (`server/routers/review_routes.py`)

- `GET  /{review_id}/noise` → `review noise REVIEW --json`
- `POST /{review_id}/noise/decide` with body `{noise_class, verdict, reviewer, note, write}` → `review noise decide …`

The routes build argv and shell out (Principle VI). There is no pipeline logic in the router.
