# Data Model: Per-Item Source Custody (042)

Everything below is an in-memory value object in `pipelines/summary_native/review/custody.py`, unless it is marked as wire format. **Nothing new is persisted** (research R2). The review store, custody generations, items, events and ledger are unchanged.

## SourceRole

`draft` | `evidence` | `summary` | `other`, decided by the `source_id` prefix (R4). Every item depends on an `other` source.

## FileState

| Value | Meaning |
|---|---|
| `current` | the current bytes hash to the custody generation's `sha256` (R3) |
| `changed` | the file exists, and its bytes hash differently |
| `missing` | there is no regular file at the path (deleted or renamed) |
| `unreadable` | an `OSError` while reading |

A symlink in the path still raises `REVIEW_PATH`, as `_reject_symlinks` does today. That is a security refusal, not a staleness state.

Provider: `state: Callable[[CustodySource], FileState]`. `custody.disk_probe(root)` hashes each path at most once per call. Tests and the replay inject their own provider.

## DependencySet

| Field | Type | Notes |
|---|---|---|
| `item_id` | str | |
| `npc` | str \| None | `npc_label(item)` (R12) |
| `npc_key` | str | the bound draft-role path, or else `item.locator.source_path` |
| `source_ids` | frozenset[str] | the full set the item depends on |
| `evidence_basis` | `bound` \| `sibling` \| `layout` \| `fallback_all_evidence` \| `not_applicable` | the strongest basis that contributed (R6). `not_applicable` is for non-NPC domains |
| `summary_basis` | `evidence_sources` \| `fallback_all_summaries` \| `unbound_sources` | R5 for NPC items, R7 for others |

**Construction** for an `npc_finding` item:

```
bound      = item.input_bindings source ids
E          = npc_evidence(item, items, custody)               # R6 union; empty → all evidence-role
S          = ⋃ evidence_summary_paths(e) for e in E           # only when state(e) == current (R2)
             → all summary-role sources if any e is not current, or parses to None (R5)
other      = all `other`-role sources
source_ids = bound ∪ E ∪ S ∪ other
```

For any other domain: `source_ids = bound ∪ {custody sources no item binds}` (R7).

**Invariant**: `source_ids` is never empty for a real item. If it is, the item is stale, with reason `no_dependency` (spec Edge Cases).

## ChangedFile

| Field | Type |
|---|---|
| `path` | str (campaign-relative) |
| `source_id` | str |
| `role` | SourceRole |
| `state` | `changed` \| `missing` \| `unreadable` |

## StaleReport

The result of `custody.stale_report(custody, items, item_ids, state)`:

| Field | Type | Notes |
|---|---|---|
| `stale` | dict[item_id, tuple[ChangedFile, ...]] | the items among `item_ids` with at least one non-current dependency |
| `changed_files` | tuple[ChangedFile, ...] | the union over `stale`, sorted by path |
| `dependency_sets` | dict[item_id, DependencySet] | for the items examined |

`item_ids=None` examines every item, which is what `review status` does.

**Rule (FR-002, SC-002)**: an item is in `stale` **if and only if** some source in its `source_ids` is not `current`. There is no other path into or out of `stale`.

## CustodyRefusalDetail (wire format)

This is the `data` of a `REVIEW_STALE_CUSTODY` refusal. See [contracts/custody-refusal.md](contracts/custody-refusal.md). It is built only by `custody.refusal_detail(report, review_id, generation, operation)`.

## StaleByNpc (wire format)

These are the new keys of `review status`. See [contracts/review-status.md](contracts/review-status.md).

## SignoffFreshness (npc_publish)

| Field | Type |
|---|---|
| `current` | bool |
| `changed` | tuple[ChangedFile, ...] |
| `review_id` | str \| None |
| `generation` | int \| None |

`_current_draft_signoff(...)` returns `signoff_freshness(...).current`, so the bool API is unchanged.

## PublishItem (amended)

Adds `draft_path: Path | None`, the draft whose bytes were signed. It is used by the pre-write re-hash (R13 point 4).

## Publish receipt (amended, wire format)

A `held` receipt may carry `custody_changed: [{"path": str, "state": str}]`. It is absent otherwise. This is additive (spec 039 receipts).

## ReviewStoreError (amended)

`ReviewStoreError(message, code=None, *, detail: dict | None = None)`. `detail` is optional. Every existing raise is unchanged.
