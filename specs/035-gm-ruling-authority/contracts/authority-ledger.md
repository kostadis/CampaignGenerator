# Authority Ledger Contract

## Canonical location

`<campaign>/docs/authority.yaml`

The file is strict YAML. Duplicate keys, unknown fields, duplicate record IDs, unsupported versions, unresolved identities, empty audiences, invalid state/field combinations, supersession cycles, and invalid intervals refuse the entire ledger. An absent ledger means the feature is not configured; it does not authorize inference from the three existing correction stores. Every mutation produces an immutable before/after event under `docs/authority/events/` using the same lock and journal as source apply.

## Minimal document

```yaml
version: 1
campaign: phandalin
revision: 1
records: []
conflicts: []
```

## Ruling example

```yaml
- id: earthstone-responsible-actor
  kind: ruling
  revision: 1
  classification: RULED
  subject:
    kind: entity
    id: earthstone
  claim_key: responsible_actor
  normalized_value: entity:correct-actor
  effective:
    from_chapter: 54
    through_chapter: 57
  audience:
    grants: [gm]
  projections: [world_state, campaign_state, planning]
  status: proposed
  recorded_at: 2026-10-09T00:00:00Z
  recorded_by: GM
  source:
    path: docs/summaries/chapter-054.md
    resolved_path: docs/summaries/chapter-054.md
    anchor: claim-earthstone-responsible-actor
    before_sha256: "<64 lowercase hex>"
    before_span_sha256: "<64 lowercase hex>"
  rejected_claim: "<exact reviewed source claim>"
  replacement_fact: "<reviewed corrected claim>"
  proposal_id: earthstone-responsible-actor-r1
```

This record does not override the source. It becomes effective only after the referenced proposal commits the authoritative summary change and the record reaches `applied`.

## Note example

```yaml
- id: commission-current-plan
  kind: note
  revision: 1
  classification: PREP
  subject:
    kind: thread
    id: neverwinter-commission
  effective:
    horizon: future
  audience:
    grants: [gm]
  projections: [planning]
  status: active
  recorded_at: 2026-10-09T00:00:00Z
  recorded_by: GM
  source:
    path: notes/neverwinter/the_commission.md
    anchor: current-plan
  content_digest: "<64 lowercase hex>"
  planning_date: chapter-54
  selection_label: Neverwinter commission current plan
```

### Complete deterministic support

Use the reserved anchor `__document__` only for a `note` that classifies a
complete read-only YAML, JSON, or Markdown support file for audience-filtered
deterministic adapters. Its `content_digest` must be the SHA-256 of the whole
file. It is invalid for `ruling` records and can never be proposed, applied,
or withdrawn as a maintained-summary replacement.

```yaml
- id: players-support
  kind: note
  classification: CANON
  source: {path: config/players.yaml, anchor: __document__}
  content_digest: "<whole-file SHA-256>"
```

## Precedence contract

- `RULED`: source-change instruction and audit trail; no independent override.
- `CANON` and `TABLE`: established evidence; neither intrinsically outranks the other. Only explicit same-claim supersession wins. Otherwise an overlapping incompatible value is a conflict.
- `OVERLAY`: current planning direction ahead of conflicting `PREP`, within its declared scope only.
- `PREP`: intended future material; never completed history.
- `OPEN`: unresolved; never establishes a value.
- Generated artifacts have no authority.
- Record/file recency is never precedence. Disjoint intervals represent change, not conflict.

## Existing-store boundary

- `docs/summary_native/canon.yaml` remains not-a-duplicate/link decisions.
- `docs/corrections.yaml` remains known-stale provenance context.
- `transcript_corrections.yaml` remains transcript repair.

Readers must not merge, import, or reinterpret these stores as authority records.
