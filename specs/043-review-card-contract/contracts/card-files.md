# Contract: card packet and decisions file (schema version 1)

The normative schemas are generated from the models and checked in:

- `pipelines/summary_native/review/schemas/card-packet.v1.schema.json`
- `pipelines/summary_native/review/schemas/card-decisions.v1.schema.json`

The golden examples are in `tests/fixtures/review_cards/`. Field rules are in [data-model.md](../data-model.md). This file shows the shapes and the rules a **page author** must follow.

## Packet (what a page renders)

```json
{
  "schemaVersion": 1,
  "packetId": "packet-3f9c0a1b2c3d4e5f6a7b",
  "reviewId": "npc-review-6ee694eebf5b",
  "reviewKind": "npc_verification",
  "generation": 4,
  "cards": [
    {
      "id": "noise-class:label",
      "kind": "noise_class",
      "npc": null,
      "title": "Classified noise: label (3 occurrences)",
      "body": "…plain text…",
      "approveMeans": "Each listed line is fine as written (accept_no_change).",
      "rejectMeans": "Each listed line is wrong; the fix is made in its draft.",
      "evidence": [{"source": "docs/npcs/…", "anchor": "L12", "excerpt": "…", "missingReason": null}],
      "members": [
        {"itemId": "finding-a1", "action": "review_classified_noise", "itemRevision": 1,
         "reviewDigest": "…", "expectedDecisionRevision": 0, "line": 12}
      ],
      "draftSha256": null,
      "previousDiscussion": null
    },
    {
      "id": "npc-signoff-jimjar",
      "kind": "signoff",
      "npc": "Jimjar",
      "title": "Sign off Jimjar's draft",
      "body": "…the full draft text…",
      "approveMeans": "Sign these exact draft bytes for publishing.",
      "rejectMeans": "Keep the draft unsigned.",
      "evidence": [],
      "members": [{"itemId": "npc-signoff-jimjar", "action": "signoff_npc_draft", "itemRevision": 1,
                   "reviewDigest": "…", "expectedDecisionRevision": 0, "line": null}],
      "draftSha256": "9b1d…64 hex",
      "previousDiscussion": "Previously discussed by GM: check the quote"
    }
  ]
}
```

## Decisions file (what a page saves)

```json
{
  "schemaVersion": 1,
  "packetId": "packet-3f9c0a1b2c3d4e5f6a7b",
  "reviewId": "npc-review-6ee694eebf5b",
  "savedAt": "2026-11-12T21:04:00Z",
  "cards": {
    "noise-class:label": {"verdict": "approve", "note": "", "members": ["finding-a1"]},
    "npc-signoff-jimjar": {"verdict": "approve", "note": "", "members": ["npc-signoff-jimjar"],
                            "draftSha256": "9b1d…64 hex"}
  }
}
```

## Rules for anyone writing a page

1. **Render text as text.** Every string in the packet is plain text. Never insert one as HTML.
2. **Start unmarked.** Never pre-select a verdict. A card the GM did not mark is **absent** from `cards`, not present with a null verdict.
3. **Echo back what you were given.** For every marked card, send `members` exactly as the packet listed them. For a sign-off card, also send `draftSha256`. CampaignGenerator compares both echoes with its stored packet, and refuses the whole file on any difference.
4. **Send nothing else.** No dispositions, revisions, reviewer or recommendation. Unknown keys are refused.
5. **Show `previousDiscussion` when present.** It is optional plain text (`null` or absent when the item was not previously discussed): render it as text beside the card, never inside the draft. A sign-off card's `body` is always byte-identical to the draft the GM is signing; the discussed-before line is deliberately not part of it. On a noise class card the line sits per occurrence inside `body` and `previousDiscussion` is null. It is display only and decide ignores it.
6. **Use one verdict vocabulary.** `approve`, `reject` and `discuss`. What a verdict records is CampaignGenerator's decision (the `approveMeans`/`rejectMeans` text says what it will be), never the page's.
7. **Version.** `schemaVersion` is the major version. A file with a version CampaignGenerator does not accept is refused, and the message names the accepted ones.
