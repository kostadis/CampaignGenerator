# Data Model: NPC Review Noise Resolution (041)

All of these are in-memory value objects in `pipelines/summary_native/noise.py`, except the last two sections, which are persisted through the existing review store.

## SentenceClaim

| Field | Type | Notes |
|---|---|---|
| `line` | int | 1-based draft line |
| `sentence` | str | exact sentence text, with citation brackets kept |
| `claim` | str | the sentence with citation brackets removed, used for token scanning |
| `citations` | tuple[(chapter:int, scene_id:str)] | the sentence's own citations, or the line's when it has none |
| `inherited` | bool | True when `citations` came from the line |

Rule: `citations` never includes another line's citations.

## Token

| Field | Type | Notes |
|---|---|---|
| `surface` | str | exactly as written, e.g. "5,000", "five", "third" |
| `kind` | `cardinal` \| `ordinal` | |
| `value` | int \| None | None when a spelled form could not be fully converted, in which case it is compared by surface |
| `span` | (start, end) | offsets within `claim` |
| `spelled` | bool | the surface is a word form |
| `label` | bool | R4 label context |
| `idiom` | str \| None | the curated phrase it sits inside |

## Occurrence outcome (closed partition, SC-005)

```
examined ──► supported                         (count only)
         ├─► noise(class ∈ CLASSES)            (one NoiseRecord)
         └─► finding(code)                     (one GM-facing Finding)
```

`CLASSES`, in precedence order (FR-014): `label`, `idiom`, `negated-status`, `spelled-number`, `synonym`, `other-citation`.

## NoiseRecord

| Field | Type | Notes |
|---|---|---|
| `check` | `number` \| `status` | |
| `noise_class` | one of `CLASSES` | |
| `line` | int | |
| `token` | str | surface form |
| `sentence` | str | |
| `cited_scenes` | tuple[str] | `"ch 085 / 085.07"` form |
| `resolved_by` | str | evidence word (`synonym`), scene id (`other-citation`), idiom phrase (`idiom`), label phrase (`label`), negation phrase (`negated-status`), or evidence surface (`spelled-number`) |

Legacy code is `noise-<noise_class>`.

## Finding (GM-facing), extended detail

The existing `npc_verify.Finding(code, line, text, detail)` is kept. For number, ordinal and status findings:
- `text` = the **sentence**, not the whole line (FR-010);
- `detail` = a message naming the token (FR-011): `draft says "40"; no scene this sentence cites contains it (cited: ch 085 / 085.07, ch 085 / 085.08)`.

The structured fields (`token`, `sentence`, `cited_scenes`) are carried into `Diagnostic.details` by the adapter.

## CheckAccounting

Per draft and per check: `{examined, supported, noise: {class: n}, findings}`. Invariant: `examined == supported + sum(noise) + findings`. It is exposed in `verify.md` (status check) and in `review noise --json` (both checks).

## Review store (persisted, additive)

- `FindingCategory.CLASSIFIED_NOISE` is a new enum member.
- A noise ReviewItem has exactly one diagnostic: `legacy_code="noise-<class>"`, `blocking=False`, `severity=ADVISORY`, `assignment_basis=MECHANICAL`, `proposed_action.action="review_classified_noise"`, and `details` = the NoiseRecord fields.
- Item identity: the existing `_stable_payload` fingerprint (selection, draft path, group, ordinal, code, line, text, detail). Noise items use group `"noise"`.

## Class decision (no new persisted type)

A class verdict expands to N ordinary `DecisionEvent`s, one per undecided occurrence of the class:
- `verdict=approve` → `disposition=accept_no_change`;
- `verdict=reject` → `disposition=reject_action`.

`note` = `GM class verdict on batch card [noise-<class>] (<k> occurrences): <GM note>`.

State per occurrence: `undecided → approved | rejected`. Retract uses the existing `review retract`. Unmarked stays undecided (FR-017).
