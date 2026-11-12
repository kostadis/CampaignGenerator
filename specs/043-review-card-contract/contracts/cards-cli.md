# Contract: `summary_native review cards`

A nested subparser (`review cards export|decide`), following the `review npc sign` pattern. Every leaf takes `--campaign-dir`, `--config` and `--json`. The output is the standard envelope `{ok, code, message, artifacts, data}`, and exit codes come from `_exit_for`: a code containing STALE exits 3; BLOCK or CONFLICT exits 5; any other refusal exits 2.

## `review cards export REVIEW [--item ID]... [--action NAME]... [--out FILE]`

It builds a packet from REVIEW's undecided items and stores it in the review (research R1, R2).

| Outcome | Code | `data` |
|---|---|---|
| Written | `REVIEW_CARDS_EXPORTED` | `{packetId, reviewId, generation, path, cards, members, byKind:{finding,noise_class,signoff}, skippedSignoffs:[{itemId, npc, code, message}], reused:false}` |
| Same packet exists | `REVIEW_CARDS_EXPORTED` | as above, with `reused:true` |
| Nothing undecided | `REVIEW_CARDS_NOTHING_TO_EXPORT` (refusal, exit 2) | `{skippedSignoffs}` |
| Wrong review kind | `REVIEW_CARDS_KIND` | |
| A different packet already stored under the id | `REVIEW_CARDS_PACKET_CONFLICT` (exit 5) | |
| A member item in two cards (defensive) | `REVIEW_CARDS_DUPLICATE_MEMBER` | `{itemId, cards}` |
| Unknown review, pending transaction, … | existing store codes | |

- `--out FILE` also writes a byte-identical copy of the stored packet to FILE, for the kit. The stored copy remains the authority.
- `artifacts` lists the stored path, and FILE when given.
- The text mode prints one line: `packet <id>: <n> cards (<k> members) for review <r>`. Any skipped sign-offs follow, one per line.

## `review cards decide REVIEW --decisions FILE|- --reviewer NAME [--write --plan-sha256 HEX]`

| Outcome | Code | `data` |
|---|---|---|
| Dry run (the default) | `REVIEW_CARDS_PLAN` | DecisionPlan (data-model.md) |
| Written | `REVIEW_CARDS_SAVED` | DecisionPlan plus `saved` |
| `--write` without `--plan-sha256` | `REVIEW_CARDS_PLAN_REQUIRED` | |
| The hash differs from the rebuilt plan | `REVIEW_CARDS_PLAN_CHANGED` (exit 5) | the new plan |
| Nothing to record (all noop or unmarked) with `--write` | `REVIEW_CARDS_SAVED` with `saved: []` | idempotent re-apply (SC-003) |
| A batch failed after earlier batches committed | the inner code (for example `REVIEW_STALE_DECISION`) | `{recorded, not_recorded, cause}` (R9) |

Whole-file refusals record nothing (research R7):

- `REVIEW_CARDS_SCHEMA`, whose message names the accepted versions;
- `REVIEW_CARDS_INVALID`;
- `REVIEW_CARDS_PACKET_UNKNOWN`;
- `REVIEW_CARDS_PACKET_ALTERED`;
- `REVIEW_CARDS_REVIEW_MISMATCH`;
- `REVIEW_CARDS_PACKET_STALE` (exit 3). The message says "export a new packet: summary_native review cards export REVIEW".
- `REVIEW_CARDS_UNKNOWN_CARD`, with `data.cards` listing them;
- `REVIEW_CARDS_MEMBER_MISMATCH`, with `data.cards` listing them;
- `REVIEW_CARDS_FINGERPRINT_MISMATCH`, with `data.cards` listing them;
- `REVIEW_CARDS_NOTE_TOO_LONG`;
- `REVIEW_INVALID_BATCH` for a blank reviewer.

Per-card refusals appear in the plan under `state: refused`, and the rest of the file proceeds:

- the `npc_signoff_blocker` codes, on an Approve of a sign-off;
- `REVIEW_CARDS_MEMBER_STALE`;
- `REVIEW_STALE_CUSTODY`, carrying the spec 042 detail.

The text mode prints:

- one line per card: `approve noise-class:label → 12 record, 0 supersede, 2 noop`;
- each supersede as `item X: reject/reject_action → approve/accept_no_change`;
- the refused cards, with their codes;
- a final line `plan <sha256>` and the exact `--write --plan-sha256 …` command to run.

### Recorded decision (each member with category `record` or `supersede`)

```text
verdict        = the card verdict
disposition    = DISPOSITION_FOR[(member.action, verdict)]        (R4)
note           = "GM card verdict [<cardId>]" + (": <note>" if note else "")
item_revision, review_digest = the packet member's (must still equal the live item's)
expected_decision_revision   = live active revision                (R5)
request_id     = "cards-<packetId>-<sha256(reviewer, batch)[:20]>" (R6)
```

## Unchanged commands (FR-023)

`review decide`, `review npc sign`, `review noise`, `review noise decide`, `review carry`, `review policy`, `review export` and `review import` keep their arguments, codes and outputs. There are two exceptions:

1. They refuse a verdict and disposition pair that #655's table does not allow (`REVIEW_ACTION_MISMATCH`).
2. A partial multi-batch failure in `noise`, `carry` or `policy` now carries `{recorded, not_recorded, cause}` as `data`. That is additive.
