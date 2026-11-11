# Masked Marron/Merrin attribution — Curse of the Hags

Run 2026-11-07. Method from `20261103-summary-entity-resolution`: frozen targets,
gold withheld from the model, a reduced-context control, exact-quote evidence check.
Model: `claude-opus-5-5`, effort medium, `claude-code` backend, one call per chapter per arm.
No campaign file was written. Runtime (private text, prompts, responses) stayed in the
session scratchpad: `aasimar-run-20261107/`.

## Task
One aasimar PC, two personalities: Marron (Paladin), Merrin (Cleric). Every name token in
40 chapter files (Ch. 3 after L36 to Ch. 46) was replaced by `[A<n>]`; 774 targets. The model
decides which personality each marker names, or `ambiguous`. Chapters 1-2 and Ch. 3 to L36
are excluded (GM convention: "keep Marron" until the stated switch).

Gold tiers: `gm` = 49 mentions on the 46 Marron/Merrin lines the GM ruled card by card
on 2026-11-07 (31 approved changes, 18 "keep as written"); `current` = the other 725, the
current text, never individually ruled.

## Results

| | context | sentence only |
|---|---:|---:|
| GM-approved changes (31) | **31 match** | 29 match |
| GM "keep as written" (18) | 2 match, 12 disagree, 4 ambiguous | similar |
| Unruled current text (725) | 635 match, 13 disagree, 77 ambiguous | 407 match, 9 disagree, 309 ambiguous |
| Evidence quotes not exact | 9 (all quote-mark variants; match after normalising) | 0 |

- With names hidden, the model reproduced every change the GM approved.
- On the 18 "keep" cards it mostly reproduced the change the earlier (name-visible) scan
  had proposed and the GM declined: Ch. 4 L159-178 (text Merrin, model Marron) and Ch. 11
  L72-154 (text Marron, model Merrin), plus Ch. 7 L15 and Ch. 43 L75. The disagreement rests
  mostly on "control persists until a switch". "Keep" may mean "correct" or "not enough
  evidence to change"; this experiment cannot tell which.
- 13 confident-or-not disagreements on unruled text are new candidate questions:
  Ch. 4 L179; Ch. 21 L78; Ch. 22 L10; Ch. 23 L60, L74; Ch. 24 L74; Ch. 26 L76, L79, L92,
  L102, L112; Ch. 32 L14, L16. Two are high, most low (persistence only).
- The chapter context cuts abstention from 309 to 77: the wider text does most of the work.

## Protocol notes and limits
- One disclosed protocol change: the Ch. 3 smoke test (kept in `smoke-v1/`) abstained after
  the explicit switch, so a "control persists until a switch" rule was added to the system
  prompt before the full run. All reported numbers use the revised prompt.
- One model, one run per arm. `current` tier is not GM gold. Masking also hides switches
  that are expressed only by the two names, so some ambiguity is structural.
- The evidence check is exact-substring; curly vs straight quotes fail it (9 cases).

## GM outcome

All 24 disputed lines went to review (`cos-aasimar-masked-20261107`); the GM approved all 24, including 11 kept earlier that day. Before/after: [series report](../20261107-cos-identity-series/README.md).
