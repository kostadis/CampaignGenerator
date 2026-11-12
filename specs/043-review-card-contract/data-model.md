# Data Model: Review Card Contract (043)

All models are strict pydantic models (`extra="forbid"`, frozen) in `pipelines/summary_native/review/cards.py`. The published JSON Schemas are generated from them (research R11). Field names in **camelCase** are the page-facing contract, read by the kit. Field names in snake_case never leave CampaignGenerator.

## CardPacket (stored: `docs/reviews/<review>/packets/<packetId>.json`)

| Field | Type | Rule |
|---|---|---|
| `schemaVersion` | int | `1` |
| `packetId` | str | `packet-<20 hex>` = sha256 of the canonical body with `packetId` omitted (R1) |
| `reviewId` | str | The review's id |
| `reviewKind` | str | `npc_verification` (the only kind in this slice) |
| `generation` | int | `manifest.generation` at export |
| `cards` | list[Card] | Non-empty. Card ids are unique. A member item id appears in at most one card (FR-003) |

There is no timestamp, no verdict, no `guess` and no recommendation field (FR-004). Recommendations (#623) will need a schema version bump and their own, clearly named field.

**Lifecycle**: the packet is created by `cards export` and never modified. It is valid while `generation == manifest.generation`. After that, decide refuses it with `REVIEW_CARDS_PACKET_STALE`. Old packets are never deleted by this feature, because they are provenance.

## Card

| Field | Type | Rule |
|---|---|---|
| `id` | str | `[A-Za-z0-9_.:-]{1,128}`, ASCII. For a single-member card it is the item id. For a noise class card it is `noise-class:<class>` |
| `kind` | `"finding"` \| `"noise_class"` \| `"signoff"` | |
| `npc` | str \| null | The NPC display label (custody `npc_label`). Null for a noise class card |
| `title` | str | Plain text |
| `body` | str | Plain text: the claim or sentence, or for a sign-off the full draft text |
| `approveMeans` / `rejectMeans` | str | Plain text: what each verdict does, written by CampaignGenerator |
| `evidence` | list[EvidenceRow] | May be empty |
| `members` | list[Member] | At least one entry (FR-003) |
| `draftSha256` | str \| null | Required for `signoff`, and null otherwise |

**EvidenceRow**: `source` (str), `anchor` (str \| null), `excerpt` (str \| null), `missingReason` (str \| null). All plain text.

## Member

| Field | Type | Source |
|---|---|---|
| `itemId` | str | `ReviewItem.item_id` |
| `action` | str | `proposed_action.action` |
| `itemRevision` | int | `ReviewItem.revision` at export |
| `reviewDigest` | str | `ReviewItem.review_digest` at export |
| `expectedDecisionRevision` | int | The active decision revision at export. It is informational: decide recomputes it from the live store (R5) |
| `line` | int \| null | `locator.display_line`, used for ordering and display |

## CardDecisions (the decisions file a page saves)

| Field | Type | Rule |
|---|---|---|
| `schemaVersion` | int | `1`. Anything else is refused with `REVIEW_CARDS_SCHEMA` (FR-019) |
| `packetId` | str | Must name a packet stored in `reviewId`'s review (FR-006) |
| `reviewId` | str | Must equal the packet's `reviewId` |
| `savedAt` | str | Non-empty ISO-8601. An unsaved page is not a save |
| `cards` | map[cardId → CardVerdict] | Every key is a card in the packet (FR-007). An absent card is unmarked |

**CardVerdict**:

- `verdict`: `approve`, `reject` or `discuss`.
- `note`: a string, default `""`, at most `max_note_chars`.
- `members`: a list of item ids, the echo. It must equal the packet card's member ids as a set.
- `draftSha256`: required if and only if the card is a `signoff`, and it must equal the packet's.

The file has no reviewer, disposition, revision or digest fields (FR-005). Any other key is refused with `REVIEW_CARDS_INVALID`.

## DecisionPlan (the `data` of `REVIEW_CARDS_PLAN` and `REVIEW_CARDS_SAVED`)

| Field | Type | Meaning |
|---|---|---|
| `reviewId`, `packetId`, `generation` | | Echoed |
| `planSha256` | str | sha256 of the canonical `cards` list below. `--write` must present it (R8) |
| `cards` | list[PlannedCard] | In packet order |
| `counts` | `{record, supersede, noop, unmarked, refused}` | Member counts, except `unmarked`, which counts cards |
| `saved` | list \| absent | Write mode only: the `submit_decisions` results (request ids and event ids) |

**PlannedCard**:

- `cardId`;
- `verdict`, or null when unmarked;
- `state`: `unmarked`, `refused` or `applied`;
- `refusal`: `{code, message, data}` or null;
- `members`, a list of PlannedMember.

**PlannedMember**:

- `itemId`;
- `category`, which is one of:
  - `record`: no fresh decision exists;
  - `supersede`: a fresh decision differs;
  - `noop`: identical;
- `disposition`;
- `previous`: `{verdict, disposition, note, decisionRevision}` or null;
- `decision`: the exact store decision dict, or null when the member is a `noop`.

### State transitions of one member under `cards decide --write`

```text
(no fresh decision) ──record──▶ decided(v, d, note)
decided(v, d, note) ──same (v, d, note)──▶ unchanged            (noop)
decided(v, d, note) ──different──▶ decided(v', d', note')        (supersede; old event kept, supersedes_event set by the store)
(any) ──card unmarked──▶ unchanged
(any) ──card refused (stale draft / member moved / custody)──▶ unchanged, listed
```

## Store changes (no on-disk shape change)

- **`_validate_action_decision`.** Every produced action is declared, and an undeclared action is refused (R4). Existing events are never re-validated, because validation runs on writes only.
- **`submit_decisions`.** A partial failure carries `detail = {recorded, not_recorded, cause}` (R9).
- **The packet store.** `packets/` is a new directory inside a review. Old reviews simply have none. There is no migration, because no existing file changes shape (XIII).
- **Provenance.** It is carried by `request_id = cards-<packetId>-<hex>` on ordinary `DecisionEvent`s (R6).
