# Contract: the speaker-label grammar

**Feature**: `specs/027-bracketed-speaker-labels` | **Date**: 2026-09-08

This feature exposes no API and no CLI flag. Its contract is a **grammar**: what counts as a
speaker label in a scene extraction, and what each form means. It is the interface between
whatever writes a scene extraction (`scene_extract`, the `/voice-smooth` skill, a GM editing
by hand) and the narrator-eligibility filter that reads one.

## Grammar

```ebnf
label-line   = line-start , "**" , label , "**" , rest-of-line ;
label        = bare | bracketed ;
bare         = ? any text without "*" ? ;
bracketed    = "[" , part , { separator , part } , "]" ;
part         = ? any text without "*", "/", "," or "]" ? ;
separator    = "/" | "," ;
```

- **`line-start` is literal.** A label is a label only at the beginning of a line. An indented
  bold run is prose emphasis, not attribution.
- A bare label is **never** tokenised. It is resolved whole, exactly as it is today.
- Whitespace around a part is insignificant. `[ GM ]` and `[GM]` are the same label.
- An empty part contributes nothing and is not reported as a name.

## Resolution

Each part is compared against the campaign's declared names after folding case and collapsing
whitespace, and in no other way.

| Part folds to | Resolution |
|---|---|
| a roster character's declared name | that character |
| the declared game-master label | the game master |
| anything else | nobody |

**Guarantees**

- **G1** — Resolution is exact after folding. A part that merely *contains*, abbreviates, or
  resembles a declared name resolves to nobody.
- **G2** — No part is admitted or rejected because of its length, capitalisation, word count,
  punctuation, or position within the label.
- **G3** — The roster and the declared game-master identity are the only authorities. Adding a
  name to the roster is what makes a label resolve; nothing else does.

## Label meaning

| Form | Example | Means |
|---|---|---|
| Bare character | `**Brewbarry**` | that character spoke |
| Bracketed character | `**[Vukradin]**` | that character spoke |
| Bare or bracketed GM | `**GM**`, `**[GM]**` | the game master spoke |
| Qualified GM | `**[GM, as the banker]**` | the game master spoke, voicing an NPC |
| Joint | `**[GM / Brewbarry]**`, `**[Brewbarry / Soma]**` | every roster character named spoke |
| Beat marker | `**[The Lead Established]**` | scene apparatus; nobody spoke |

## Effect on eligibility

- **E1** — A label naming at least one roster character makes every such character present in
  that scene, and contributes exactly one turn of evidence to each.
- **E2** — A label naming only the game master makes nobody present.
- **E3** — A **slot** naming nobody makes nobody present, and is reported to the GM — even
  when another slot of the same label resolved. Reporting only wholly-unresolved labels hid
  the case it mattered most in: `**[GM / Brewbarry / Valphine]**` credited Brewbarry and
  dropped `Valphine` with no trace at all.
- **E4** — Presence is a yes/no fact. One turn is full eligibility; counts are evidence for the
  GM's review and never a threshold.
- **E5** — Presence and counts derive from one reading of the text, so they cannot disagree.

## Reporting

Every label that resolves to nobody is surfaced. Which bucket it lands in is a verbosity
decision and carries no meaning about identity:

| Label | Bucket |
|---|---|
| an unresolved piece is a shortening of a roster name | listed individually — *"each one costs that character a scene"* |
| resolved a speaker, and a slot named nobody | listed individually — same notice |
| bare, unresolved, contains a roster name | listed individually — same notice |
| bare, unresolved, otherwise | counted, not listed |
| bracketed, no slot resolved | counted, not listed |

The first row's containment runs in one direction only — the piece inside the name, never
the name inside the piece. `valphine` sits inside `valphine sotorra`; `scene tag — vukradin
demands a meeting` sits inside nothing, because a beat marker is longer than any name it
mentions. The reverse test is the dangerous one and stays confined to bare labels.

The counted bucket names what is in it and points at `plan.eligibility.json`, which lists
every one. It does **not** call itself "expected": scene apparatus is expected, and a
short-form roster label reaching it would be a wrong exclusion filed as expected — which is
what `**[Valphine]**` (8 occurrences, against a roster spelling her `Valphine Sotorra`) did
until the first row above promoted it.

## Compatibility

- A scene extraction written entirely in bare labels produces byte-identical eligibility
  output before and after this feature. This is structural: tokenisation never touches a bare
  label.
- A form not in this grammar resolves to nobody and is reported. New conventions fail safe
  and visibly, never silently into presence.
- "Reported" means *surfaced in the printed report and listed in `plan.eligibility.json`*.
  A qualifier is the one piece deliberately not reported: a later piece of a slot that
  resolves to nobody describes the turn (`as the banker`) rather than failing to name a
  speaker.
