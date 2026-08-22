# Contract: `scene_extract` CLI Surface

**Feature**: 013-batched-scene-extraction | Governs FR-007, FR-017, FR-018

## 1. New flags

| Flag | Type | Default | Meaning |
|---|---|---|---|
| `--batch-scenes` | store_true | off | Send all pending scenes in one exchange (grouped if needed) |
| `--no-batch-scenes` | store_false | — | Explicitly force the per-scene loop |
| `--batch-max-tokens` | int | `32000` | Output ceiling for a batched run (FR-017) |

`--batch-scenes` / `--no-batch-scenes` share one dest so the editor can always
render an explicit flag (DM-19). The CLI's own default is off — an unadorned
`scene_extract` invocation behaves exactly as today (FR-009).

### Unchanged

`--max-tokens` keeps its `8192` default and keeps applying to the per-scene loop
only (FR-017b). `--force`, `--batch` (Message Batches), `--submit-only`,
`--collect`, `--summary`, `--output-dir`, `--dossier-dir`, `--party*`,
`--players-config`, `--backend`, `--model` are untouched.

**`--batch` vs `--batch-scenes`** are different things and compose independently:

| | `--batch` | `--batch-scenes` |
|---|---|---|
| What | Submits N per-scene requests as one Message Batch job | Collapses N scenes into one exchange |
| Calls | N requests, one job | 1 (or a few) |
| Backend | `anthropic` only | Any; the point is the subscription |
| Buys | 50% list discount | Removes transcript repetition |

**Both set is REFUSED.** `session_doc/scene_extract.py:478` gates the live path
on `if not args.batch:` and returns, so a composed run would silently ignore
`--batch-scenes` and pay the transcript N times while the GM believed they had
batched — a confident-looking success doing the expensive thing (Constitution I,
Optimistic Lies). Implementing the composition instead was rejected because it
buys nothing: `--batch` only works on the metered backend, where `cache_system`
already makes the repeated transcript cheap. The saving `--batch-scenes` exists
for does not exist on the path `--batch` runs on.

## 2. Refusals

| Condition | Behaviour |
|---|---|
| `--batch` **and** `--batch-scenes` together | **Refused, exit 1**: "--batch-scenes cannot be combined with --batch. --batch submits per-scene requests to the Message Batches API (metered backend only), where the repeated transcript is already cached; --batch-scenes removes the repetition for backends that have no cache. Pick one." |
| `--batch-max-tokens` without `--batch-scenes` | Accepted, ignored, with a note — the same shape as other inert-knob cases |
| `--batch-scenes` with no `## Scenes` section | Existing exit-1 refusal, unchanged (the Stage 1→2 gate, FR-019) |
| `--batch-scenes` with every scene on disk, no `--force` | Zero calls; "all scenes already extracted" (FR-008b, DM-3). Exit 0 |
| Group fails reconciliation | Nothing from that group written; exit non-zero naming the failure (FR-005) |
| Some scenes missing | Written scenes kept; exit non-zero naming the missing (FR-012, DM-16) |

## 3. Run report

Written to stdout at the end of every batched run (FR-018):

```
[Batched scene extraction | model: claude-opus-5 | ceiling: 32,000 tok]
  Scenes in summary:     8
  Already extracted:     5  (skipped — pass --force to redo)
  Requested:             3
  Projected output:      9,240 tok  -> 1 group
  Transcript sent:       1x  (per-scene mode would have sent 3x)

  [group 1/1] 3 scene(s)
    06_the_notary_of_house_margaster.md      written
    07_the_shut_down_shipping_hub.md         written
    08_confrontation_at_margaster_logistics  written

  Wrote 3 scene file(s) to scene_extractions/
```

Incomplete run:

```
  Projected output:     52,180 tok  -> 2 groups (projection exceeds ceiling;
                                      raise --batch-max-tokens for one call)
  Transcript sent:       2x  (per-scene mode would have sent 14x)

  [group 2/2] 7 scene(s)
    ...
    13_the_long_negotiation.md               INCOMPLETE — response ended mid-scene
    14_leaving_the_quay.md                   not returned

  Wrote 12 of 14 scene file(s).
  NOT extracted: 13_the_long_negotiation, 14_leaving_the_quay
  Re-run without --force to request only those.
```

**Required fields** (`RunReport`, data-model §6): scenes total / skipped /
requested / written, empty, missing (**named**, FR-012), groups used, transcript
transmissions, and whether the ceiling was exceeded (FR-006d).

The "per-scene mode would have sent Nx" line is what makes SC-001 checkable from
the run output rather than by instrumenting the backend.

## 4. Exit codes

| Code | Meaning |
|---|---|
| `0` | Every requested scene written, or nothing to do |
| `1` | Input refusal (no summary, no scenes, bad paths) — existing behaviour |
| `2` | VTT speaker-mismatch guard — existing behaviour |
| `3` | **New.** Run completed partially: some scenes written, some missing (FR-012) |
| `4` | **New.** A group failed reconciliation; nothing from it written (FR-005) |

Exit `3` is distinct from `1` because it is a *resumable* state with valid files
on disk, not a refusal. The editor surfaces it as "partial", not "failed".
