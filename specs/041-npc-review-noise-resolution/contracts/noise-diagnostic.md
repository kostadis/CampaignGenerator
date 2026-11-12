# Contract: noise and finding diagnostics in the review store

## Classified-noise item diagnostic

```json
{
  "legacy_code": "noise-other-citation",
  "blocking": false,
  "message": "\"200\" is in ch 085 / 085.07, which this sentence also cites",
  "details": {
    "check": "number",
    "noise_class": "other-citation",
    "token": "200",
    "sentence": "Hekaton's fleet of 200 ships gathers [ch 085 / 085.07] [ch 085 / 085.08].",
    "cited_scenes": ["ch 085 / 085.07", "ch 085 / 085.08"],
    "resolved_by": "ch 085 / 085.07",
    "line": 22
  }
}
```

Item-level: `categories = {classified_noise}`, `severity = advisory`, `assignment_basis = mechanical`, `proposed_action.action = "review_classified_noise"`, `details.legacy_code = "noise-<class>"`.

## GM-facing number/ordinal/status diagnostic (changed fields only)

```json
{
  "legacy_code": "number-inconsistency",
  "message": "draft says \"40\"; no scene this sentence cites contains it (cited: ch 085 / 085.07, ch 085 / 085.08)",
  "details": {
    "check": "number",
    "tokens": ["40"],
    "sentence": "…",
    "cited_scenes": ["ch 085 / 085.07", "ch 085 / 085.08"],
    "line": 22,
    "text": "<sentence>",
    "detail": "<message>",
    "verdict": "advisory"
  }
}
```

`claim_text` on the item stays the exact draft line, because custody and locator binding depend on it. `details.sentence` is what a page leads with.

## Policy compatibility

A policy file `{noise-label: "chapter labels are not story facts"}` passed to `review policy` approves exactly the `noise-label` items. This needs no code change, because each noise item has a single legacy_code.

## Stability

The legacy codes `noise-label`, `noise-idiom`, `noise-negated-status`, `noise-spelled-number`, `noise-synonym` and `noise-other-citation` are a public contract, because GM policy files key on them. Renaming one is a breaking change.
