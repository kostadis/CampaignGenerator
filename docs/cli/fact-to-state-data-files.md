# `facts_to_state` — the data files it needs

`facts_to_state` is the **compression layer** of the ensemble pipeline: it
takes the tens of thousands of atomic facts produced by `ensemble_extract` /
`ensemble_batch` and bundles them into one current-state dossier per entity.

Getting good bundles depends on inputs beyond the obvious one (the corpus).
**`--aliases`**, **`--known-names`**, and **`--exclude-names`** are curated,
per-campaign, and their formats are non-obvious enough that it is easy to
produce a silently-degenerate run. This document is the reference for building
those files for a new campaign.

> **2026-07-04 update:** `type=="npc"` subjects are now known-by-default (a
> campaign never gives two different NPCs the same name — see
> [How the pieces interact](#how-the-pieces-interact-order-of-operations)).
> `known_names.md` is no longer the primary mechanism for NPCs; it's now
> mostly an override list. It's still the primary mechanism for
> locations/factions/objects, which don't have that same-name guarantee.

> The failure modes here are silent: a wrong-format file exits `0` and produces
> a plausible-looking list. Always sanity-check with `--list` (see
> [Verifying](#verifying-a-run)).

---

## The mental model: two fragmentation axes

An entity fragments in the bundle list for two independent reasons. Each is
fixed by a **different** file. It is easy to fix one and forget the other.

| Axis | Symptom | Fixed by |
|------|---------|----------|
| **Spelling** | Same entity under variant spellings becomes separate bundles (`Sequoia` + `Sequioa`, `Harch` + `Hartsch`) | `--aliases aliases.json` |
| **Named vs generic** | A named entity shatters into one bundle per location (`Zephyr (Water Temple)`, `Zephyr (Hommlet)`, …), OR a generic subject (`orc`) becomes one meaningless campaign-wide omnibus | For `npc`: automatic (known by default), with `--known-names`/`--exclude-names` as overrides. For other types: `--known-names …` |

Everything below is in service of these two axes.

---

## How the pieces interact (order of operations)

For every fact, in `load_bundles`:

1. `display = aliases.get(raw_subject, raw_subject)` — **alias canonicalisation first**.
2. `norm = _norm_subject(display)` — normalise: `lowercase, strip every non-alphanumeric char`.
   So `"Thorne (the Duke)"` → `thornetheduke`, `"St. Cuthbert"` → `stcuthbert`.
3. Classification, in order of precedence:
   ```
   if norm in exclude_names:      is_known = False   # explicit override, wins over everything
   elif norm in known_names:      is_known = True    # explicit override
   elif type == "npc":            is_known = norm not in monster_vocab
   else:                          is_known = (known_names is None)
   ```
   `monster_vocab` is every normalised `type=="monster"` subject anywhere in the
   corpus, computed automatically — no file to maintain. It catches creatures
   that get mistagged `npc` in some chapters (a fact framing "the ghoul" as
   having agency) and `monster` correctly in others.
   - **Known** → one global bundle, keyed by `(type, norm)`.
   - **Not known** → location-scoped bundle, keyed by `(type, norm, dominant_location_of_chapter)`.

**Why `npc` defaults to known:** a GM never gives two different NPCs the same
name — players would confuse them. So unlike a generic monster type (`orc`,
where many different orcs legitimately share the label), any `npc`-typed
subject with a real name is, by construction, a unique individual across the
whole campaign. This means `known_names.md` no longer needs to *enumerate*
NPCs — it only needs the residual overrides:
- an NPC whose name collides with `monster_vocab` for a reason other than
  actually being generic — e.g. a polymorphed/disguised NPC whose true form
  gets fact-tagged `type: monster` under the same name (seen in practice:
  an NPC revealed mid-campaign to be a dragon, and another who fights under a
  monster stat block). Add these to `known_names.md`.
- a genuinely generic role-phrase with no `monster_vocab` match at all
  (`"Bandit Chief"`, `"the freed prisoner"`, `"Gnome guard"` — a title with no
  name attached, and not a creature species either). Add these to
  `exclude_names.md` (see [File 4](#file-4--exclude-namesmd---exclude-names-optional)).

`known_names.md` remains the *primary* mechanism (not just an override) for
`location`, `faction`, and `object` — those types don't have an equivalent
"never reused" guarantee (a room can generically be called "the great hall" in
many different dungeons; a named location like "Moathouse" cannot).

Two consequences that trip people up:

- **`--known-names` should list _canonical_ names, not variants.** Because aliases
  are applied *before* the known check, a variant like `Sequioa` is already
  rewritten to `Sequoia` by the time we test membership. Put `Sequoia` in
  known-names; let `aliases.json` handle `Sequioa`.
- **`_norm_subject` already collapses case and punctuation.** You only need an
  alias entry when two spellings still differ *after* normalisation
  (`goodingoat` vs `goodingoot`). `Ostler` vs `ostler` needs no alias.

Only these entity types are bundled at all (`STATEFUL_TYPES`):
`npc, faction, location, object, monster`. (`event`, `date`, `thread` are
cross-cutting and handled on a separate track via `--render-only`.)

---

## File 1 — the corpus (`--corpus`, required)

**What:** the ensemble's per-chapter fact files. A glob, e.g.
`docs/ensemble/per_chapter/*/merged.json`.

**Format:** each `merged.json` is a JSON array of atomic facts. `facts_to_state`
reads these keys:

```json
[
  {
    "type": "npc",                       // one of npc|faction|location|object|monster|event|…
    "subject": "Zephyr",                 // the entity this fact is about (the bundling key)
    "fact": "Zephyr signed a contract in blood.",
    "source_quote": "...verbatim VTT..." // optional; shown with --quotes
  }
]
```

**Where it comes from:** generated by the extraction stage — you do **not**
hand-write this. Chapter number is parsed from the path label
(`gen-ch03` / `…ch03…` → chapter 3), which drives chronological ordering
(later chapter overrides earlier for "current state").

**Note — dominant location:** for anonymous entities, the scope suffix is the
chapter's *dominant* location = the `type: "location"` subject with the most
facts in that chapter. So `Tarokka deck (Hall of the Scarlet Moon)` in `--list`
does **not** assert the deck is in that hall — it just means chapter 17's
busiest location was the Hall. It is a disambiguation tag, not a claim.

---

## File 2 — `aliases.json` (`--aliases`, optional but usually needed)

**Purpose:** merge spelling/nickname variants of the *same* entity so they land
in one bundle. Fixes the **spelling** axis.

**Format:** `{canonical: [variants]}`. Loaded by `load_aliases` into a flat
`{variant: canonical}` map (canonicals self-map). The **canonical** string
becomes the display name for every variant.

```json
{
  "Sequoia":  ["Sequioa"],
  "Zinnia":   ["Zinia"],
  "Hartsch":  ["Harch"],
  "Ostler Gundigoot": ["Ostler Goodingoat", "Ostler Goodingoot", "Osler Goodingut", "Ostler"],
  "Thorne":   ["The Duke", "Duke", "Thorne (Duke)", "Thorne (the Duke)"]
}
```

**Matching is exact-string, pre-normalisation.** `aliases.get(raw)` looks up the
raw fact `subject` verbatim (after `.strip()`). So a variant entry must match
the fact subject as it actually appears (case included) *unless* the two already
normalise the same — in which case you don't need the entry at all. When in
doubt, mirror the exact strings seen in the corpus.

**Where the variants come from:**
- **`docs/npcs/.dedup_state.json`** is the natural seed. Its
  `clusters_confirmed[*]` entries are human-approved merges:
  `canonical` (a dossier filename) + `aliases_recorded` (the variant strings).
  Reshape each into `{<dossier display name>: aliases_recorded}`. Use the
  dossier's frontmatter `name:` as the canonical display, not the raw filename
  stem.
- **PC spelling drift** — PCs are transcribed inconsistently and are usually
  *not* in the dedup pass (see below). Add them by hand
  (`"Zinnia": ["Zinia"]`).
- **Parenthetical fact-subject forms** the dedup pass never saw
  (`"Thorne (the Duke)"`), found by scanning corpus subjects.

`aliases.json` is shared: `synthesise_world_state` and the threads render
(`--render-only`) consume the same file.

---

## File 3 — known-names sources (`--known-names`, one or more)

**Purpose:** decide which entities are **named individuals** (→ one global
dossier) vs **anonymous/generic** (→ location-scoped). For `location`,
`faction`, and `object`, this is the primary mechanism. For `npc`, it's now
only for overrides — see
[How the pieces interact](#how-the-pieces-interact-order-of-operations) for
why `npc` defaults to known without curation.

Accepts **multiple** sources; pass several (the runner and CLI both accumulate
them). Two file kinds are recognised, by extension:

### 3a. Inventory `.md` — bold-marked proper nouns

`load_known_names` reads **only `**bold**` spans** (`_BOLD_RE = \*\*([^*]+)\*\*`).
Each bold name is normalised and added. For a multi-word bold name, the **first
word** is also added if it is ≥ 4 chars (so `**Adabra Gwynn**` also registers
`adabra`, catching short-name fact subjects).

```markdown
## Player Characters
- **Zephyr**
- **Sequoia**
- **Zinnia**
- **Calmer**

## Named Locations
- **Moathouse**
- **Water Temple**
```

> ⚠️ **The #1 trap.** A plain bullet list (`- Boccob`, no `**`) loads **zero**
> names. The header then prints `Known names: 0 … from N source(s)` and — because
> an *empty* known set is not the same as *no* known set — **every** entity is
> forced to location-scope. This is a silent catastrophe. See
> [Verifying](#verifying-a-run).

### 3b. `.dedup_state.json` — dedup-pass output (JSON)

Read natively; no conversion needed. Contributes:
- every string in `clusters_confirmed[*].aliases_recorded`;
- each `canonical` filename stem, split on `_`, words ≥ 4 chars
  (`ostler_gundigoot.md` → `ostler`, `gundigoot`);
- `pc_files_skipped` stems by the same rule (so PCs filtered out of the dedup
  pass are still treated as named — **but only if they were in that directory**).

### PCs no longer need explicit registration

PCs are `type: "npc"` like everyone else, so they're known-by-default now —
you don't need to hand-add them to `known_names.md` for the named-vs-generic
axis. (Historically this section said the opposite: PCs were the #1 thing that
had to be added by hand, since they appear in neither an adventure dictionary
nor `docs/npcs/.dedup_state.json`. That gap is closed by the default flip.)

What PCs still need is **`aliases.json`** for transcription/spelling drift
(`"Zinnia": ["Zinia"]`) — that's a different axis, unaffected by this change.

### If you use a module proper-noun dictionary

Now mainly relevant for **named locations** and the residual npc overrides
(monster-vocab collisions, faction names). Include the **clean, named**
sections — deities, named module NPCs (for the override cases above), named
magic items, and hand-curated **named locations**. **Exclude:**
- **Creatures** (`orc`, `ghoul`, `bugbear`): you *want* these location-scoped, so
  each encounter is a coherent bundle rather than one campaign-wide "state of ghoul".
  (For `npc`-typed creature mentions specifically, `monster_vocab` now does
  this automatically — see above.)
- **Heuristic "Places" dumps**: these often mislabel creatures/NPCs/items as
  places; registering them as known pollutes the named set. Curate named
  locations from the *corpus* instead (the `type: location` subjects that are
  proper places — `Moathouse`, the temples — not generic rooms like
  `great hall`, `bone corridor`, `antechamber`).

  > **Before you discard the Places dump, skim it for misfiled NPCs.** A
  > heuristic extraction sometimes tags a real named NPC as a "place" (e.g.
  > `Jaroo Ashstaff` or `Commander Hedrack` ending up under "Places, Realms &
  > Notable Locations" instead of an NPCs section). This used to silently drop
  > those NPCs from known-names entirely; now the npc-default-known rule means
  > a misfiled NPC still resolves correctly on its own. It's still worth a
  > skim before deleting the source file — the same section can hide misfiled
  > **locations** or **factions** too, and those two types still rely on
  > `known_names.md` as their primary mechanism, not just an override.

---

## File 4 — `exclude_names.md` (`--exclude-names`, optional)

**Purpose:** the inverse of `known_names.md` for `npc` — forces a normalised
name to stay anonymous/location-scoped even though the default-known rule
would otherwise treat it as a unique individual. Only needed for genuine
generic role-phrases that `monster_vocab` doesn't already catch (no matching
`type=="monster"` subject in the corpus): bare titles or roles with no
personal name attached, e.g. `"Bandit Chief"`, `"the freed prisoner"`,
`"Gnome guard"`.

**Format:** identical to `known_names.md` — bold-marked spans in a `.md` file,
read by the same `load_known_names` loader.

**How to build it:** run `--list --min-facts 1 --types npc` with no
`--known-names`/`--exclude-names` at all, and read the `[known]` rows for
anything that's a role/title rather than a name. In practice this list is
short (a handful of entries per campaign) — most generic creature mentions
resolve automatically via `monster_vocab`. When a case is ambiguous (is
`"Gnoll King"` a unique boss or a generic leader-of-gnolls title?), check it
against 5etools: if the name matches an official bestiary entry or a
recognizable variant of one, it's generic; if it returns nothing, it's more
likely a genuine proper name.

---

## Behaviour when a flag is absent

| Situation | Effect |
|-----------|--------|
| No `--known-names` at all, non-npc types | `known_names` is `None` → **every** non-npc entity is global (no location-scoping). Generic subjects like a location called `great hall` become one omnibus bundle. |
| No `--known-names` at all, `npc` type | Unaffected — npc classification never depended on `known_names` being set; it's always known-by-default minus `monster_vocab`/`exclude_names`. |
| `--known-names` given but loads **0** entries | Empty set → every non-npc entity is location-scoped (the bullet-list trap); npc classification is unaffected, same as above. |
| `--known-names` reasonably complete (non-npc types) | Named → global, generic → location-scoped. The intended split. |
| No `--exclude-names` | Every npc-typed subject not in `monster_vocab` stays known-by-default, including any un-curated generic role-phrases. |
| No `--aliases` | Spelling variants stay separate. |

Because "complete-enough known set" determines correctness, treat known-names as
something to iterate: run `--list`, find named things that wrongly scattered,
add them, repeat.

---

## Per-campaign setup checklist

1. **Confirm the corpus glob** resolves (`--corpus '…/*/merged.json'`).
2. **Build `aliases.json`** — seed from `docs/npcs/.dedup_state.json` clusters
   (canonical `name:` ← `aliases_recorded`), add PC spelling variants and any
   parenthetical corpus-subject forms. *This is a scope/attribution decision —
   review the merge list before it feeds synthesis.*
3. **Build a bold `known_names.md`** for the types that still need it — clean
   module sections (deities, named items) + curated named locations/factions
   from the corpus. No creatures, no heuristic "places" dump. Leave NPCs out
   entirely at first; they resolve on their own now.
4. **Dry-run `--list --types npc --min-facts 1`** with no known/exclude-names
   at all and read the `[known]` rows for genuine role-phrases (not names).
   Put those in `exclude_names.md`. This list is usually short.
5. **Wire everything**: `--known-names known_names.md docs/npcs/.dedup_state.json --exclude-names exclude_names.md`.
6. **Dry-run `--list`** (all types) and read the header + the `[known]` /
   `[location]` tags — for npc, watch specifically for a real named individual
   who got excluded because their name also matches a `type=="monster"`
   subject (a disguised/polymorphed NPC, or one who fights under a monster
   stat block) — add those to `known_names.md` as overrides.
7. Iterate until the split looks right, then run the real aggregation
   (`--out-dir …`, drop `--list`), and **review the `## Uncertainty` blocks**
   before synthesis.

Canonical command:

```bash
facts_to_state \
  --corpus 'docs/ensemble/per_chapter/*/merged.json' \
  --aliases docs/ensemble/aliases.json \
  --known-names docs/ensemble/known_names.md docs/npcs/.dedup_state.json \
  --exclude-names docs/ensemble/exclude_names.md \
  --min-facts 3 --list          # drop --list and add --out-dir DIR to generate dossiers
```

Suggested per-campaign locations: `docs/ensemble/aliases.json`,
`docs/ensemble/known_names.md`, `docs/ensemble/exclude_names.md`. The dedup
file lives at `docs/npcs/.dedup_state.json`.

---

## Verifying a run

Run with `--list` (deterministic, no model calls) and read the header first:

```
Known names: 175 normalised entries from 2 source(s)     ← count AND sources must match expectation
Excluded names: 8 normalised entries from 1 source(s)
Entities: 1636 …  (254 known / 1382 location-scoped)
Selected: 304 for aggregation
```

Failure signatures:

| You see | Meaning |
|---------|---------|
| `… 0 normalised entries …` | A known-names/exclude-names source loaded nothing — almost always a `.md` with no `**bold**`. |
| `… from 1 source(s)` when you passed two | Only one source survived (historically, repeated `--known-names` flags were dropped — fixed, but check your invocation). |
| Named locations/factions tagged `[location]` and split by site | They're missing from `known_names.md` — add them. (Doesn't apply to npc — see below.) |
| A named NPC tagged `[location]` and fragmented across many sites | Check `monster_vocab` — the name probably also appears as a `type=="monster"` subject somewhere (a disguised/polymorphed NPC, or one who fights under a monster stat block). Add it to `known_names.md` as an override; don't assume the whole npc mechanism is broken. |
| A role/title with no name (`"Bandit Chief"`, `"the freed prisoner"`) shows `[known]` with one big global bundle | A generic npc role-phrase with no `monster_vocab` match. Add it to `exclude_names.md`. |
| `Sequoia` **and** `Sequioa` both present | Missing alias entry — add to `aliases.json`. |
| A generic monster (`type != "npc"`) with one huge global bundle | It was wrongly marked known in `known_names.md` — remove it. |

Useful flags: `--min-facts N` (floor; below it there's nothing to collapse),
`--known-only` (synthesise only named entities; list anonymous but skip them),
`--render-only FILE` (deterministic dump, e.g. for the `thread` track).

---

## Quick reference — who reads what

| File | Flag | Format | Hand-authored? | Also read by |
|------|------|--------|----------------|--------------|
| `*/merged.json` | `--corpus` | JSON fact array | No (generated) | — |
| `aliases.json` | `--aliases` | `{canonical:[variants]}` | Yes (seed from dedup) | `synthesise_world_state`, threads render |
| `known_names.md` | `--known-names` | Markdown, `**bold**` names | Yes | — |
| `.dedup_state.json` | `--known-names` | dedup-pass JSON | No (dedup output) | dossier-merge tooling |
| `exclude_names.md` | `--exclude-names` | Markdown, `**bold**` names | Yes (short, npc-only) | — |
| *(no file)* | — | `monster_vocab`, computed from the corpus each run | No | — |

Related: this is the concern behind CampaignGenerator issue #122 (too many
ad-hoc files/mechanisms for tracking inventories and aliases).
