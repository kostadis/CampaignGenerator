# Phase 1 Data Model: bracketed speaker labels

**Feature**: `specs/027-bracketed-speaker-labels` | **Date**: 2026-09-08

Nothing here is persisted. These are the in-memory shapes that carry a label from the text of
a scene extraction to a narrator-eligibility decision. Files on disk are unchanged.

## Entities

### RawLabel

The bold text at the start of a line in a scene extraction's `moments` body, exactly as
written. Produced by the reader in `session_doc/io.py`; the only thing that reads the text.

| Field | Type | Notes |
|---|---|---|
| `text` | str | Verbatim, brackets and separators included. `GM`, `[GM / Brewbarry]`, `[scene tag — The roll]` |
| `scene_index` | int | Which scene it was found in |

**Rules**

- A label is recognised only at the start of a line. An indented bold run is not a label.
- Order is preserved; one appearance is one `RawLabel`.
- No filtering happens here. The game master, beat markers and unknown names all come through.

---

### LabelPart

One candidate name obtained by tokenising a `RawLabel`. Tokenisation is textual and asserts
nothing about identity.

| Field | Type | Notes |
|---|---|---|
| `text` | str | One part, whitespace-trimmed |
| `source` | RawLabel | The label it came from |

**Rules**

- A bare label yields exactly one part: itself, unmodified.
- A bracketed label yields one part per segment after removing the outer `[` `]` and splitting
  on `/` and `,`.
- Empty and whitespace-only parts are discarded and are not reported as names.

---

### Resolution

What a `LabelPart` turned out to name. The only place identity is decided.

| Value | Meaning |
|---|---|
| `character(name)` | Folds exactly to a declared roster character; `name` is the roster's own spelling |
| `game_master` | Folds exactly to the declared game-master label |
| `unresolved` | Names nobody the campaign declares |

**Rules**

- Comparison folds case and collapses whitespace, and does nothing else. Containment,
  prefixes, abbreviations and edit distance are not resolution.
- The roster is the sole authority for `character`; the campaign's declared game-master
  identity is the sole authority for `game_master`.

---

### LabelClass

What a whole `RawLabel` means, derived from its parts' resolutions.

| Value | Derived when | Effect on presence |
|---|---|---|
| `speaker` | at least one part resolved to a character | each such character present, one turn of evidence each |
| `game_master` | no part resolved to a character, at least one resolved to the game master | none |
| `apparatus` | bracketed, no part resolved | none; reported in the quiet bucket |
| `stranger` | bare, unresolved | none; reported under today's containment heuristic |

**Rules**

- `speaker` outranks `game_master`: `[GM / Brewbarry]` is Brewbarry's presence, and the
  game-master part contributes nothing rather than suppressing the label.
- A character appearing twice in one label contributes one turn, not two.
- `apparatus` and `stranger` differ only in how they are *reported*. Neither creates presence.

---

### SceneEligibility *(existing, unchanged in shape)*

Already defined in `session_doc/plan_eligibility.py`. What changes is what reaches it.

| Field | Change |
|---|---|
| `candidates` | grows on bracketed-convention sessions, from empty to the real set |
| `counts` | now includes turns from bracketed and joint labels |
| `strangers` | now carries unresolved *bracketed* labels too, bucketed per Decision 3 |

## Flow

```text
moments text
   → RawLabel*          (io.py — reads, never filters)
   → LabelPart*         (tokenise: brackets, "/", ",")
   → Resolution*        (fold + exact match against roster / GM)
   → LabelClass         (derive)
   → presence + counts + report buckets   (plan_eligibility.py)
```

One parse feeds presence, counts and the report, so a turn count can never disagree with an
eligibility decision (FR-009).

## Worked examples

| Label | Parts | Resolutions | Class | Presence |
|---|---|---|---|---|
| `Brewbarry` | `Brewbarry` | character | speaker | Brewbarry +1 |
| `[Vukradin]` | `Vukradin` | character | speaker | Vukradin +1 |
| `GM` / `[GM]` | `GM` | game_master | game_master | none |
| `[GM, as the banker]` | `GM`, `as the banker` | game_master, unresolved | game_master | none |
| `[GM / Brewbarry]` | `GM`, `Brewbarry` | game_master, character | speaker | Brewbarry +1 |
| `[Brewbarry / Soma]` | `Brewbarry`, `Soma` | character ×2 | speaker | Brewbarry +1, Soma +1 |
| `[GM / Brewbarry / Valphine]` | 3 parts | gm, character, character | speaker | Brewbarry +1, Valphine +1 |
| `[scene tag — Vukradin demands a meeting]` | 1 part | unresolved | apparatus | none, counted quietly |
| `[Valphine]` *(roster says `Valphine Sotorra`)* | `Valphine` | unresolved | apparatus | none — out of scope, see spec Assumptions |
| `Vukradin (David)` | `Vukradin (David)` | unresolved | stranger | none, listed loudly *(unchanged)* |
