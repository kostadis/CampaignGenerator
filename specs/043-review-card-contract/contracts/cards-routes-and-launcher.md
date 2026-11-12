# Contract: web face (routes and launcher)

Both routes are thin. Each builds one fixed argv and runs it through `run_bounded_json`, and relays the CLI envelope unchanged (constitution VI). They are mounted under `/api/reviews`.

## `POST /api/reviews/{review_id}/cards/export`

Body (`StrictRequest`): `{"items": [str], "actions": [str]}`. Both lists are optional and default to empty.

The argv is:

```text
summary_native review cards export {review_id} [--item I]... [--action A]... --campaign-dir ROOT --json
```

## `POST /api/reviews/{review_id}/cards/decide`

Body: `{"decisions_path": str, "reviewer": str, "write": bool, "plan_sha256": str | null}`.

- **The decisions path** is resolved with `_contained_file`: it must lie inside the campaign and exist. The file stays on disk and is never uploaded (constitution IX).
- **`write: true` requires `plan_sha256`.** The route does not check this; the CLI refuses (`REVIEW_CARDS_PLAN_REQUIRED`), so the rule lives in one place.

The argv is:

```text
summary_native review cards decide {review_id} --decisions PATH --reviewer R [--write --plan-sha256 H] --campaign-dir ROOT --json
```

## HTTP status for the new codes (`_status_for`)

| Code | Status |
|---|---|
| `REVIEW_CARDS_PACKET_UNKNOWN` | 404 (`_EXACT_STATUS`) |
| `REVIEW_CARDS_PACKET_STALE`, `REVIEW_CARDS_MEMBER_STALE` | 409 (STALE) |
| `REVIEW_CARDS_PACKET_CONFLICT` | 409 (`_CONFLICT`) |
| `REVIEW_CARDS_REVIEW_MISMATCH`, `REVIEW_CARDS_MEMBER_MISMATCH`, `REVIEW_CARDS_FINGERPRINT_MISMATCH` | 422 (`_MISMATCH`) |
| `REVIEW_CARDS_PLAN_CHANGED` | 409 (`_EXACT_STATUS`), because the store moved |
| other `REVIEW_CARDS_*` refusals | 400 |

## `ReviewLauncher.vue`: the "Card packet" fieldset

| Control | Action | Shows |
|---|---|---|
| **Export card packet** | POST export | The packet id, card and member counts, and skipped sign-offs with their codes |
| Decisions file (path input) and Reviewer (input) | | |
| **Plan** | POST decide with `write:false` | The plan grouped as Record, Supersede (old → new), No change, Unmarked and Refused, with `planSha256` |
| **Confirm and record** | POST decide with `write:true, plan_sha256:<the shown plan's>` | Disabled until a plan is shown, and reset whenever the path or reviewer changes. Shows the saved result |

- **Refusals.** The CLI message is shown in the existing `note` area, and `data` in the existing result `<pre>`, as for every other launcher action (US6 scenario 3).
- **No other state.** The launcher keeps nothing beyond the last plan's hash and the form fields.
