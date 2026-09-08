# Feature Specification: A bracketed speaker label is a speaker, not a scene tag

**Feature Branch**: `feat/453-bracketed-speaker-labels`

**Created**: 2026-09-08

**Status**: Draft

**Input**: User description: "453"

Tracking: [#453](https://github.com/kostadis/CampaignGenerator/issues/453). Sub-issue of
[#418](https://github.com/kostadis/CampaignGenerator/issues/418), but **independent of it** —
this is a live defect in the narrator-eligibility filter shipped by
[#385](https://github.com/kostadis/CampaignGenerator/issues/385), and it would be worth
fixing if #418 were abandoned.

## Context

Scene extractions mark who spoke with a bold label at the start of a line. Sessions do not
agree on how that label is written. Across the four sessions frozen in
`experiments/20260907-phandalin-gm-gaps-confirm/inputs/`, four conventions appear:

| Form | Example | Occurrences |
|---|---|---|
| bare | `**GM**`, `**Brewbarry**` | 2 sessions |
| bracketed | `**[GM]**`, `**[Vukradin]**` | 2 sessions |
| bracketed, qualified | `**[GM, as the banker]**` | ~10 turns in one scene |
| bracketed, joint | `**[GM / Brewbarry]**`, `**[Vukradin / GM]**` | 10 turns in one session |

Scene extractions also use the same bold-bracket shape for something that is **not** a
speaker — a beat or scene marker: `**[Reroll With Advantage]**`, `**[The Lead
Established]**`, `**[scene tag — The roll]**`.

The system that reads these labels treats every bracketed label as a non-speaker. That is
correct for the beat markers and wrong for the other three forms, and on a session written
entirely in the bracketed convention it means **no character is recorded as having spoken
in any scene**. Two of the four sessions above are in that state:

```
brewbarry  ->  Soma 18, Brewbarry 21, Vukradin 12, Valphine Sotorra 2
soma       ->  Vukradin 19, Valphine Sotorra 31, Soma 5, Brewbarry 10
valphine   ->  (nothing)
vukradin   ->  (nothing)
```

`vukradin` has 39 turns labelled for Vukradin and 21 for Soma. None are counted.

**What that costs the GM.** Narrator eligibility is decided by two filters. Filter B asks
"did this character speak in this scene?" and a character who did not cannot narrate it.
When every label is discarded, every character is ineligible for every scene, and the
planner refuses an empty pool rather than falling back to the campaign roster. On these
sessions narrator selection does not degrade quietly — it stops, and the GM cannot plan the
session at all.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Plan a session recorded in the bracketed convention (Priority: P1)

A GM has a session whose scene extractions label every speaker in brackets. They ask the
system to propose narrators for each scene. Today it refuses, reporting that no character
is eligible anywhere. It should instead offer the same choice it offers for a session in
the bare convention: for each scene, the characters who actually spoke in it.

**Why this priority**: This is the whole defect. Without it a class of session cannot be
planned at all, and the failure gives the GM no usable signal about why — the pool is empty
and every character carries the same "no speaker label in this scene" exclusion, which
reads as a claim about the session rather than about the parser.

**Independent Test**: Take the two sessions that currently produce nothing, ask for
narrator eligibility, and confirm each scene lists the characters whose labelled turns
appear in it. Delivers a working planning step for sessions that have none.

**Acceptance Scenarios**:

1. **Given** a scene whose speaker labels are all written `**[Name]**`, **When** eligibility
   is computed, **Then** every roster character with at least one such labelled turn in that
   scene is listed as present in it.
2. **Given** a session written entirely in the bracketed convention, **When** eligibility is
   computed, **Then** the narrator pool is non-empty and planning proceeds.
3. **Given** a character with exactly one labelled turn in a scene, **When** eligibility is
   computed, **Then** they are fully eligible to narrate it — presence is not a threshold on
   turn count.

---

### User Story 2 - A game master's turn is recognised however it is written (Priority: P2)

The game master's turns are excluded from character presence: the GM is not a narrator, and
a GM turn must never make a player character look present in a scene they were not in. That
exclusion works for `**GM**` and, by accident, for every other bracketed form — they are all
thrown away for being bracketed. Once bracketed labels are read, the GM's forms have to be
recognised **as the game master** rather than falling through as unrecognised names.

**Why this priority**: Getting this wrong in the permissive direction is the expensive
failure — a GM turn credited to a player character is a false attribution, the class this
project treats as its most costly error. Getting it wrong in the other direction floods the
GM's review list with turns that need no review.

**Independent Test**: Run eligibility over a scene containing each GM form and confirm no
character gains presence from any of them, and that none is reported as an unrecognised
name.

**Acceptance Scenarios**:

1. **Given** a scene containing `**[GM]**` turns, **When** eligibility is computed, **Then**
   no character gains presence from them and they are not reported as unrecognised.
2. **Given** a scene where the GM voices an NPC as `**[GM, as the banker]**`, **When**
   eligibility is computed, **Then** the turn is treated as the game master's and no roster
   character gains presence from it.
3. **Given** a scene containing both `**GM**` and `**[GM]**` turns, **When** eligibility is
   computed, **Then** both are treated identically.

---

### User Story 3 - A jointly labelled turn credits the character named in it (Priority: P3)

Some turns carry two attributions: `**[GM / Brewbarry]**`, `**[Brewbarry / GM]**`,
`**[Vukradin / GM]**`. One session has ten of them. Under today's behaviour they are
discarded entirely, so a character whose only turn in a scene is a joint one is recorded as
absent from a scene they spoke in.

**Why this priority**: Real but narrow — ten turns in one session of four. It is separable
from US1 and US2 and can ship after them without leaving either incomplete.

**Independent Test**: Give a character exactly one turn in a scene, written jointly with the
GM, and confirm they are listed as present in that scene.

**Acceptance Scenarios**:

1. **Given** a turn labelled `**[GM / Brewbarry]**` and a roster containing Brewbarry,
   **When** eligibility is computed, **Then** Brewbarry is present in that scene.
2. **Given** the same turn, **When** eligibility is computed, **Then** it is counted once,
   not once per named party.
3. **Given** a joint label naming two roster characters, **When** eligibility is computed,
   **Then** both are present in that scene.

---

### User Story 4 - A beat marker is still not a speaker (Priority: P3)

`**[Reroll With Advantage]**` and `**[scene tag — The roll]**` are scene apparatus, not
people. They must not create presence, and — because the same file contains both forms —
they cannot be told apart from a speaker by shape alone.

**Why this priority**: A regression guard on behaviour that is correct today. It carries no
new value on its own, but US1 cannot ship without it, because US1's change is what puts
these labels back in play.

**Independent Test**: Run eligibility over a scene containing beat markers alongside real
speakers and confirm the markers create no presence and the speakers do.

**Acceptance Scenarios**:

1. **Given** a scene containing `**[Reroll With Advantage]**`, **When** eligibility is
   computed, **Then** no character gains presence from it.
2. **Given** a scene containing both a beat marker and a bracketed speaker label, **When**
   eligibility is computed, **Then** the speaker is present and the marker contributes
   nothing.
3. **Given** a bracketed label that matches neither a roster character nor the game master,
   **When** eligibility is computed, **Then** it is reported to the GM as an unrecognised
   label rather than silently dropped.

---

### Edge Cases

- **A bracketed label naming a character the roster does not have** — reported as
  unrecognised, never resolved by resemblance. Nothing in this feature asserts an identity
  from a name that merely looks right.
- **A joint label naming two roster characters** — `**[Brewbarry / Soma]**`,
  `**[Vukradin / Brewbarry]**`. Both are present. See Assumptions.
- **A joint label naming more than two parties** — `**[GM / Brewbarry / Valphine]**`. Every
  roster character named is present; the game-master part establishes presence for nobody.
- **A short-form name against a longer roster spelling** — `**[Valphine]**` where the roster
  says `Valphine Sotorra`. Comparison folds case and whitespace only, so this does not match
  and is reported as unrecognised. See Assumptions: resolving short forms is a separate
  concern and is out of scope here.
- **Mixed conventions inside one file** — one session carries `**[Vukradin]**` and
  `**[scene tag — The roll]**` together, so the two cannot be separated by shape.
- **Empty or whitespace-only brackets** — `**[]**` contributes nothing and is not reported
  as a name.
- **An indented bold label** — remains excluded. A label is only a label at the start of a
  line; loosening that would let a smoothed extraction report turns for a character the
  filter had already excluded.
- **A label carrying surrounding whitespace inside the brackets** — `**[ GM ]**` is treated
  as `**[GM]**`.
- **A session in the bare convention** — must be entirely unaffected.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST treat a bracketed speaker label as naming the same speaker the
  equivalent unbracketed label would name.
- **FR-002**: The system MUST continue to treat a bracketed label that names neither a roster
  character nor the game master as a non-speaker, contributing no presence.
- **FR-003**: The system MUST decide whether a bracketed label is a speaker by whether its
  contents resolve to a known participant — never by the shape, length, or wording of the
  label.
- **FR-004**: The system MUST recognise the game master in every observed form — bare,
  bracketed, and bracketed with a qualifier such as an NPC the GM is voicing — and MUST NOT
  let any of them establish presence for a roster character.
- **FR-005**: The system MUST count a jointly labelled turn as presence for **every** roster
  character it names. Each named character receives at most one turn of evidence from that
  label, and a game-master half establishes presence for nobody.
- **FR-006**: The system MUST report every label it cannot resolve to the GM, in the existing
  review channel, rather than discarding it silently.
- **FR-007**: The system MUST produce unchanged eligibility results for sessions written in
  the bare convention.
- **FR-008**: Presence MUST remain a yes/no fact about whether a character has at least one
  labelled turn in a scene. Turn counts remain evidence shown to the GM and MUST NOT become
  a threshold.
- **FR-009**: The set of labels used to decide presence and the set used to count turns MUST
  come from one parse, so a reviewer can never be shown a turn count for a character the
  filter excluded.
- **FR-010**: The two filters MUST remain separate. Attendance resolves player display names
  from the recording; presence resolves character names from the extraction. They read
  different label spaces and MUST NOT be merged.

### Key Entities

- **Speaker label**: the bold text at the start of a line in a scene extraction, as written.
  May be bare or bracketed, may carry a qualifier, may name two parties.
- **Roster character**: a player character the campaign declares. The authority on which
  labels name someone who can narrate.
- **Game master turn**: a turn spoken by the person running the game, including NPC speech
  they voice. Never a narrator, never presence for a player character.
- **Beat marker**: bold bracketed scene apparatus that names no one.
- **Unrecognised label**: a label that resolves to nobody. Surfaced for GM review; never
  presence, never silently dropped.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All four sessions in the confirmation corpus yield a non-empty narrator pool.
  Today two of four yield none.
- **SC-002**: For a session in the bracketed convention, every character with at least one
  labelled turn in a scene is listed as present in that scene — 100% of labelled turns are
  counted, against 0% today.
- **SC-003**: No labelled turn disappears without a trace: every bold label that resolves to
  nobody appears in the GM's review output.
- **SC-004**: Sessions in the bare convention produce identical *presence* output before and
  after the change — no character gained, none lost, every turn count identical.

  *Narrowed 2026-09-08 during implementation.* This first read "no new unrecognised labels",
  which contradicts FR-006 and SC-003: a bare-convention file may still contain a bracketed
  beat marker, and those were previously discarded in silence. Surfacing them is the point of
  FR-006, so the counted-not-listed total does grow (by 1 and 3 on the two bare files). The
  guarantee that matters — presence, counts, and the loud report bucket — holds exactly.
- **SC-005**: A game master turn produces presence for zero roster characters, in all four
  label forms.
- **SC-006**: A GM planning a session in the bracketed convention reaches a narrator choice
  without editing the extraction files by hand.
- **SC-007**: A turn labelled with two roster characters makes both of them present in that
  scene, and contributes one turn of evidence to each. The corpus contains three such turns.
- **SC-008**: No beat marker is reported to the GM as "looks like a roster character but did
  not resolve". That channel exists to catch a mis-normalised character name that silently
  costs a scene; markers such as `**[scene tag — Soma's Arcana check]**` must not dilute it.

  *Narrowed 2026-09-08, after review.* As first written this said the channel's **count** must
  not grow, which turned out to forbid the one thing it exists for. `**[GM / Brewbarry /
  Valphine]**` resolves two speakers and leaves `Valphine` naming nobody — the strongest
  evidence of a mis-normalised character in the corpus, and precisely what the GM must see.
  It now lands there, taking the count 0 → 1 on `valphine_source.md`. The criterion binds
  what may *not* appear; the expected set is pinned per file in `baseline.json`, because
  `loud <= 0` was satisfied by deleting the channel altogether.

## Assumptions

- **Resolving short-form names is out of scope.** `**[Valphine]**` against a roster
  `Valphine Sotorra` stays unrecognised and is reported. Name comparison folds case and
  whitespace and nothing else; treating a shorter name as the same person is an identity
  assertion from resemblance, which this project forbids by rule and by test. If the GM wants
  short forms resolved, that is a separate feature built on the declared alias registry, not
  a widening of this one.
- **A joint label grants presence to every roster character it names** — ruled by the GM on
  2026-09-08, over the conservative alternative of reporting a multi-character joint as
  unresolved. It is deliberately the permissive reading: a turn that may have been spoken by
  only one of the named characters can make both eligible to narrate the scene. The turn
  counts shown beside the pool remain the GM's evidence for overriding it.

  *Corrected 2026-09-08 during planning:* the question was put to the GM on the understanding
  that no such label existed in the corpus. It does — `**[Brewbarry / Soma]**` and
  `**[Vukradin / Brewbarry]**` appear once each, and `**[GM / Brewbarry / Valphine]**` names
  three parties. The ruling stands and is now evidence-backed rather than hypothetical, and
  the three-party form is covered by FR-005 as written.
- **The set of conventions is the four observed**, drawn from the frozen corpus. A fifth form
  encountered later resolves to nobody and is reported — the safe direction.
- **Downstream consumers are unaffected in shape.** The only consumer of scene presence is
  the narrator-eligibility filter; this feature changes what it sees, not who reads it.
- **The GM's review of unrecognised labels already exists** and is the reporting channel;
  this feature adds entries to it rather than building a new surface.
- **`#418`'s block editor will need GM turns enumerated, not merely excluded.** That is
  [#456](https://github.com/kostadis/CampaignGenerator/issues/456)'s requirement and depends
  on the classification here being correct, but exposing them is not in this feature.
- **No model call is involved.** This is a parsing and resolution change in a deterministic
  filter; it spends no tokens and adds no LLM-rendered judgement.

## Dependencies

- The campaign roster (the declared list of player characters) is the authority for resolving
  a label to a character.
- The campaign's declared game-master identity is the authority for recognising a GM turn.
- The frozen four-session corpus under `experiments/20260907-phandalin-gm-gaps-confirm/inputs/`
  is the evidence set for SC-001, SC-002 and SC-004.
