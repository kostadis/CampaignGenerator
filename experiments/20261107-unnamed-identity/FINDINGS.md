# Unnamed-character identity proposals — Curse of the Hags

Run 2026-11-07. Same method family as `20261103-summary-entity-resolution`, but **no gold**:
the GM ruled the 65 unnamed people "leave unnamed", which settles the text, not identity.
Model: `claude-opus-5-5`, effort medium, `claude-code` backend. No campaign file written.
Runtime in the session scratchpad: `unnamed-run-20261107/`.

## Task
65 questions over 39 chapters (from `notes/unnamed_characters.md`). Context arm: full chapter
+ the question + canon entries (entity registry, party.yaml, vtt_known_additions.md) for every
name the question mentions. The Stage 4 agent's evidence was not sent. Control arm: question +
canon entries, no chapter.

## Results
| | context | question only |
|---|---:|---:|
| referents judged | 179 | 96 |
| same_referent | 56 (13 high, 41 medium, 2 low) | 1 |
| distinct_referents | 55 | 6 |
| ambiguous | 67 | 89 |
| validity errors | 1 (surface paraphrased, Ch. 46) | 0 |

- The control abstains almost entirely, so identifications come from the chapter text, not
  the question's framing or canon notes alone.
- Typical high-confidence proposals: unattributed lines resolved by the reply that follows
  (Ch. 13 "Bury Izek, Now!" -> Gaxim; Ch. 18 -> Slerdax; Ch. 37 -> Rictavio), self-naming
  (Ch. 29 arcanaloth -> Neferon), and class epithets (rogue -> Wukong, barbarian/half-orc -> Gaxim).
- Proposals that depend on a canon note rather than the chapter (Patrina Velikovna,
  Rictavio = van Richten, the Baron = Vargas Vallakovich) are flagged as such in their reasons.
- One Ch. 39 call returned two JSON objects; it was retried once and the failure kept in
  `failed-attempts/`.

## Status
Every identification is an unreviewed proposal. Nothing goes into the bible, the summaries or
the registry without a GM ruling (canon chain, CLAUDE.md "every name change is asked").

## GM outcome

All 57 positive identifications went to review (`cos-unnamed-identity-20261107`); the GM approved all 57. They are recorded in the campaign's `docs/identity/identity_rulings.yaml` for summary-native NPC work. Before/after: [series report](../20261107-cos-identity-series/README.md).
