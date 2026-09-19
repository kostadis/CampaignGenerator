# 20260919-phandalin-event-kg

Measurement pass behind **[docs/design/EventOrdinalKG_proposal.md](../../docs/design/EventOrdinalKG_proposal.md)**
— read that first.

Successor to [`20260911-retrieval-time-kg/`](../20260911-retrieval-time-kg/),
which established the method on Obelisk (12 sessions). This retargets it at
Phandalin (53 sessions, 20 MB) to see what survives at 4.4× the corpus.

**Evidence only.** No campaign canon, no chapter revision, no production change.
Both scripts are **read-only** against `~/phandalin`; they write only a SQLite
file next to themselves.

## Scripts

| File | What it does |
|---|---|
| `phandalin_kg.py` | Builds the event-ordinal graph from `Phandalin/docs/summaries` into `phandalin_kg.sqlite3`. ~0.8 s. |
| `diag.py` | Reports the `STATE_GENERATION_METHOD` §8 hazards measured against that graph. |

Run `phandalin_kg.py` first. Absolute paths to `~/phandalin` are hard-coded, as
in the predecessor — for another corpus, copy and edit `SRC` / `REG`.

## Campaign source is not copied

Per this repo's convention, campaign material stays in the `campaigns` repo.
Used as **inputs**, not vendored here:

- `Phandalin/docs/summaries/*.md` — the 53 session summaries
- `Phandalin/docs/entity_registry.yaml` — 594 GM-reviewed entities
- `Phandalin/summaries/*/` — the 54 raw session directories, for the reconcile check

## What it produced

```
sessions      53   (50 written; 001, 020, 023 are not-written stubs)
events       356
beats      5,255
snapshots    883
mentions   2,752
entities     987   (594 registry + 393 heading-only)
```

Counts cross-checked against an independent `awk` extraction: scenes 356 = 356,
snapshot entries 883 = 883, beats 5,255 vs 5,251 (Δ4 indented sub-bullets).
Positive control `Valphine` → 764 in-scene hits.

## Three changes from the predecessor's `event_kg.py`

1. Identity resolves through `entity_registry.yaml` (typed, carries
   `rejected_aliases`) rather than the flat `aliases.json` projection.
2. **Snapshot keys resolve through the alias map** — §8.2, listed in the
   predecessor as a known bug (§10 item 1). Fixed here.
3. Session id, chapter number, and ordinal are three separate fields (§8.7) —
   Phandalin has two sessions numbered "Chapter 49".
