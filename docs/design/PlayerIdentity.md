# Player Identity — Where It Lives Today, 2026-08-15

## Why this doc exists

There is no `players.yaml`. A player — the human at the table — is not modelled
anywhere as a thing with attributes. What exists instead is **five join keys
across fourteen stores**, each recording some projection of the same person, and
none of them naming the others.

This document is an inventory and a measurement, not a proposal. It records what
is true on disk today so that a future `players.yaml` (or a decision not to build
one) starts from evidence rather than from the assumption that the pieces already
line up. **They do not: one campaign is broken right now**, and the break is
silent. See "Measured drift" below.

Companion docs:

- **`docs/design/PartyRosterCanonicalFormat.md`** — the GM ruling that the D&D
  Beyond sheet is canonical for character data and `party.yaml` only references
  it. This doc does not revisit that ruling; it maps what "reference it" costs.
- **`docs/design/MarkdownAsInput.md`** — the six `party.md` dialects, and why
  reading identity back out of generated documents is the recurring defect.
- **`specs/008-sheet-naming-archival/`** — the feature that made `party.yaml`
  authoritative for `player` and renamed sheets to roster names. Both changes
  moved identity around; this doc measures where it landed.

---

## The four things called "identity"

They are routinely conflated, and every conflation is a bug that has already
happened at least once.

| | What it is | Example | Stability |
|---|---|---|---|
| **Person** | The human being | Ben Pfaff | Stable |
| **Zoom display name** | What the recording labels their speech | `Ben Pfaff`, `Dave`, `ncroussos` | **Per-session.** Drifts without warning |
| **Character** | The PC they play | Gyrgum | Stable until a rename, then a corpus-wide problem |
| **Sheet** | D&D Beyond's own record of the character | `kostadis1_67390528.pdf` | Stable; carries a numeric ID |

The person and the Zoom name are not the same field even when the strings match.
`config/party.yaml`'s `player:` is documented as holding the **Zoom display
name** (`campaignlib/party_config.py:88–92`), because
`campaignlib.npc.normalize_vtt_speakers` matches speaker prefixes exactly. But it
is *rendered* as a person's name — `session_doc/roster.py:70` emits
`- Gyrgum (Ben Pfaff): Cleric 8` into the prompt. One field, two jobs, and the
one that fails does so silently.

---

## The inventory

Fourteen places a player's identity is recorded, and what reads each.

| # | Store | Field | Written by | Read by | Join key |
|---|---|---|---|---|---|
| 1 | `config/party.yaml` | `characters[].name` | GM by hand; Party page | `sheet_naming.attribute`, `load_pc_names`, registry `known_names` | character name |
| 2 | `config/party.yaml` | `characters[].player` | GM by hand; Party page | **`dnd_sheet` only** — see below | (none) |
| 3 | `config/party.yaml` | `sheet` / `backstory` / `dossier` / `arc_score` | GM | every render pipeline | path |
| 4 | Sheet YAML frontmatter | `player`, `name`, `species`, `class_level`, `subclass` | `dnd_sheet`, `sheet_frontmatter --apply` | `player_map_from_config`, `roster_from_config` | player string |
| 5 | Sheet `## Identity` block | `- **Player:**`, `- **Class & Level:**` | `dnd_sheet` | `sheet_identity.read_player`, `read_class_level` | — |
| 6 | `config/session_doc.yaml` | `roster.characters` (comma string) | GM in the editor UI | `--characters` → examples routing | character **first name** |
| 7 | `config/session_doc.yaml` | `roster.gm_player` | GM in the editor UI | `--gm-player` → rewritten to `GM` | Zoom display name |
| 8 | `voice/<name>[_voice].md` | the filename | GM | `voice.get_voice_note` | character **first name** |
| 9 | `examples/<name>.md` | the filename | GM | `examples.routes_to` | character **first name** |
| 10 | `docs/entity_registry.yaml` | canonical + aliases | `registry` CLI | alias resolution, `known_names` | canonical string |
| 11 | `docs/party.md` | six hand-authored layouts | `pipelines/grounding/party.py` (generated) | `parse_party_md` consumers | character name |
| 12 | D&D Beyond export filename | `<account>_<id>.pdf` | D&D Beyond | **nothing** | — |
| 13 | The VTT itself | `Speaker Name:` prefixes | Zoom | `normalize_vtt_speakers` | Zoom display name |
| 14 | `vtt_voice_compare --player/--character` | typed per invocation | GM at the shell | that script only | both, by hand |

### `party.yaml`'s `player:` has exactly one reader

Feature 008 made the roster authoritative for `player` (FR-008). It is worth
being precise about what that means, because it is narrower than it sounds.

`PartyCharacter.player` is read in **one** production call site:

```
pipelines/content_ingest/dnd_sheet.py:387    markdown = apply_roster_player(markdown, character.player)
```

Every downstream consumer of player identity reads the **sheet**, not the roster:

```
campaignlib/npc.py:331     player_raw = str(frontmatter.get("player") or "")   # player_map_from_config
session_doc/roster.py      frontmatter.get("player")                          # roster_from_config
```

So the roster is authoritative *at conversion time only*, and the sheet is the
carrier thereafter. That is coherent with the canonical-format ruling — but it
means **editing `player:` in the Party page changes nothing** until that
character's PDF is re-converted. The value is copied one way, once, and nothing
detects the two drifting apart.

This is the same shape as the `narrate.genre` defect (`docs/cli/genre_rulebook_howto.md`):
a config field holding a copy of something a file owns, synced in one direction,
with the copy silently winning or silently rotting depending on which end you
edit. That one took three copies and two fixes to unwind.

---

## The five join keys

Every relationship between the stores above is one of these. Three of the five
are fragile, and they are the three that fail quietly.

### A. Character name — exact, case-insensitive, whitespace-trimmed

Used by `sheet_naming.attribute` to decide which sheet a conversion overwrites.

**There is deliberately no fuzzy matching**, and a test asserts none can be
added. A mismatch refuses, names both spellings, and writes nothing. This is the
one join key with no silent failure mode, and it is the newest.

### B. Character *first name*, lowercased — voice files and example files

`voice._resolve_voice_key` and `examples.routes_to` both resolve a narrator to a
file by:

1. exact full name (lowercased), else
2. first token only, else
3. the unique key beginning with that first token followed by `_` or `-`.

Two names collapse to one key whenever they share a first token. `Thorin` and
`Thorin Giantfriend` both resolve to `thorin_voice.md`, which is why the #311
roster widening did not break OOTA's Thorin — by luck, not by design.

Step (3) is why `Valphine Sotorra` finds `valphine_new_pipeline.md`. It is also a
prefix-similarity rule being used to *assert identity*, which is precisely what
`provenance/identity.py`'s FR-016 forbids elsewhere in this codebase:

> Nothing here computes a string distance in order to *assert* a match. `Vera`
> does not resolve to `Veyra` because they look alike — it resolves only if a GM
> has recorded the link.

The voice and example loaders predate that doctrine and have not been held to it.

### C. Zoom display name — exact string prefix

`normalize_vtt_speakers` rewrites a line only when it literally starts with
`<name>:`. A near-miss drops that player's every line from every extraction.

Two mitigations exist and both are partial:

- `_apply_first_name_aliases` (`campaignlib/npc.py:257`) adds `Joe` → the same
  character as `Joe Beda`, but skips ambiguous first names. It cannot help with
  `Nicholas Roussos` vs `ncroussos`.
- A **wrong-VTT pre-flight** in `scene_extract` and `enhance_summary` aborts when
  *zero* expected names appear. It catches the whole map being wrong. It does not
  catch one player of four being wrong — three matching speakers satisfy it while
  the fourth vanishes.

The placeholder vocabulary (`campaignlib/npc.py:231`) is the escape hatch:
`""`, `not specified`, `n/a`, `none`, `unknown`, `tbd`, with or without brackets.
Hillsfar uses it for all four characters.

### D. Filesystem path — `sheet`, `backstory`, `dossier`, `arc_score`

Explicit, hand-authored, and checked. `missing_files` reports what is absent and
the CLI refuses to render. This is the other join key that fails loudly, and the
reason is structural: it is a path, not a name, so nothing can approximately
match it.

Note the consequence for renames — OOTA's roster now reads:

```yaml
- name: Gyrgum
  sheet: docs/Gyrgum.md
  backstory: docs/grygum_backstory.md
  dossier: docs/ensemble/merged_dossiers/npc_grygum.md
```

The paths keep the old spelling and that is *fine*, because a path is an address.
Only the join keys that are names had to change — which is the entire argument
for identifier-based joins in one example.

### E. The D&D Beyond character ID — present, and read by nothing

Eight exports on disk are named `<account>_<id>.pdf`:

```
stormgiants/docs/party/kostadis1_{21636618,67390528,67557915,67558842}.pdf
Hillsfar/docs/{kosadis_80444987,kostadis1_21637306,kostadis1_80462412,kostadis1_107615571}.pdf
```

**No character name appears in those filenames at all**, and the account prefix
is junk (one is misspelled `kosadis`). `dnd_sheet.py` reads the filename only for
progress output and for the legacy `<stem>.md` output path (`:417`); grep finds
no reference to a D&D Beyond ID anywhere in the codebase, and the IDs do not
appear inside the converted sheets either.

The four toee PDFs were hand-renamed (`zephyr.pdf`, and a transposed
`sequioa.pdf`) and have lost their IDs entirely.

Tracked as **CampaignGenerator#312**.

---

## Measured drift, 2026-08-15

Not hypothetical. Run against the live campaigns after #311/#173 merged.

### out-of-the-abyss is broken right now, silently

The roster and sheet were corrected to the sheet's own spelling, **Gyrgum**. Four
stores still say **Grygum**:

| Store | Value | Consequence |
|---|---|---|
| `config/party.yaml` `name` | `Gyrgum` | — (the new truth) |
| `voice/grygum_voice.md` | `grygum` | **voice spec never reaches the prompt** |
| `examples/grygum.md` | `grygum` | **style examples never reach the narrator** |
| `config/session_doc.yaml` `roster.characters` | `Grygum` | routes the examples to a key nobody reads |
| `docs/entity_registry.yaml` canonical | `Grygum` | two spellings both in `known_names` |

Trace it through `_resolve_voice_key` for a narrator named `Gyrgum`, against keys
`{daz, grygum, thorin, vizeran, zalthir}`:

1. full `gyrgum` — miss
2. first name `gyrgum` — miss
3. keys starting `gyrgum` + `_`/`-` — none

Returns `None`. `get_voice_note` warns to stderr and renders **with no voice
spec** — the #247 failure mode the warning was added for.

The examples file fails differently, and the difference matters — **the obvious
one-line fix makes it worse.** `_load_examples` keys the per-character bucket off
`--characters` (still `Grygum`), while `get_char_examples` looks the bucket up by
the narrator's first name (`gyrgum`). The file routes into a bucket nobody reads.

Measured, by running `_load_examples` and `get_char_examples` against the live
campaign directory:

| Scenario | Global block | `Gyrgum` gets examples | Detector reports |
|---|---|---|---|
| **A.** Today | none | **no** | nothing |
| **B.** Fix `session_doc.yaml` only → `Gyrgum` | **12,572 chars to every narrator** | **no** | nothing |
| **C.** Rename the file *and* fix the config | none | yes | nothing |

Scenario B is the trap. Correcting the stale name in `session_doc.yaml` — the
first thing anyone would do — leaves `grygum.md` matching no character, so it
falls through to the GLOBAL block that every narrator receives. That is the #301
bleed, newly created by a repair.

`examples_routing_problems` reports nothing in **all three** rows, including B
where a real bleed exists. It keys off the narrators' first names, and
`routes_to("grygum", "gyrgum")` is false for those too. The detector added for
#301 cannot see a rename.

The registry half is bigger than a rename: **1608 files use `Grygum` against 75
using `Gyrgum`**, two of them raw `*.transcript.vtt` that must never be
hand-edited. Tracked as **campaigns#172**; it is a `spell_canon.py` pass, not an
edit.

### Phandalin survives by accident

`config/session_doc.yaml` still says `Valphine`; `party.yaml` now says
`Valphine Sotorra`. Nothing breaks — but only because rule B(3) matches
`valphine_new_pipeline.md` on the first token. Had the GM ruling widened the name
at the *front* rather than the back, Phandalin would have failed exactly as OOTA
did.

### `roster.characters` is a second, hand-typed roster

`session_doc.yaml`'s `roster.characters` is a comma-separated string of character
names, authored independently of `party.yaml` and never reconciled with it. It is
not decoration — it is the routing key for per-character examples, and
`tests/test_editor_pipeline.py:243` says so explicitly. Two of the two campaigns
that have this file are currently stale against their own roster.

### `gm_player` is not in the roster at all

The GM's Zoom display name lives only in `session_doc.yaml`
(`roster.gm_player: Kostadis Roussos`). It is the one player identity that never
touches `party.yaml`, and toee's `calmer` is a GM-played PC — so the GM is
simultaneously a `gm_player` string and, arguably, a roster `player:` value.
Unresolved; tracked in **campaigns#174**.

### Three copies of every `player` value

`party.yaml`'s `player:`, the sheet's frontmatter `player:`, and the sheet's
`## Identity` → `- **Player:**` line. `apply_roster_player` writes the latter two
together and deliberately so — "both, or the document contradicts itself" — but
the first is synced to them only by re-conversion.

---

## Failure-mode ranking

What actually matters is not how many stores exist but how loudly each join
fails.

| Join | Failure | Detected? |
|---|---|---|
| Path (D) | missing file | **Loud** — refuses before the API call |
| Character name (A) | attribution mismatch | **Loud** — refuses, names both spellings, writes nothing |
| Zoom name (C), all wrong | no speaker matches | **Loud** — wrong-VTT pre-flight aborts |
| Zoom name (C), one wrong | that player's lines vanish | **Silent** |
| First name (B), voice | narration renders with no voice spec | Warns to stderr; easy to miss in a long run |
| First name (B), examples | the narrator gets no style examples | **Silent** |
| First name (B), examples, after a partial repair | one character's style reaches everyone | **Silent** — the #301 detector cannot see a rename |
| `party.yaml` `player:` edited | roster and sheet disagree | **Silent** — nothing re-syncs, nothing compares |
| `roster.characters` stale | routing key wrong | **Silent** |

Everything loud is a *path* or an *exact-match refusal*. Everything silent is a
*name approximately matched*. That is the finding.

---

## What a `players.yaml` would and would not fix

It would fix the **person** being unrepresented: today there is no place to say
"Ben Pfaff is a person, whose Zoom name has been `Ben Pfaff` since session 1, who
plays Gyrgum, whose D&D Beyond ID is 67390528." Every one of those facts exists
somewhere; the *relation between them* exists nowhere.

It would **not** fix anything by merely existing. A fifteenth store that must be
kept in sync by hand makes the problem worse, not better. It is only worth
building if it is the **source** and the others become **derived**:

- `voice/` and `examples/` filenames would be checked against it, or generated
  into an explicit map, rather than matched on a first-token prefix.
- `session_doc.yaml`'s `roster.characters` would go away — it is a projection of
  `party.yaml` and should never have been typed twice.
- The D&D Beyond ID would become the attribution key (#312), retiring the one
  Constitution deviation feature 008 recorded.
- A `check` verb, in the shape of `registry check`, would report drift instead of
  waiting for a silent render to be wrong.

The precedent to copy is `docs/entity_registry.yaml`: one authority, generated
projections, a `check` that reports drift for human review, and importers that
fold the legacy stores in. The precedent to avoid is `narrate.genre`: a second
copy of something a file owns, synced one way.

---

## Open questions — GM rulings, not lookups

1. **Is `player:` the Zoom name or the person's name?** It is documented as the
   Zoom name because `normalize_vtt_speakers` demands it, but it is rendered into
   prompts as a person's name. If a player's Zoom label is `ncroussos`, the
   roster prompt currently says `Sequoia (ncroussos)`. These want to be two
   fields.
2. **Zoom names drift per session; config is per campaign.** Phandalin's Wade
   went from `Wade` to `Wade Brown` between recordings. One current value cannot
   be right for a back-catalogue of VTTs. Does a player carry a *list* of known
   display names?
3. **Does the GM get a roster entry?** `gm_player` is separate today, and toee's
   Calmer is GM-played.
4. **Should voice/examples routing move off first-name matching** to an explicit
   declaration? It is the last similarity-based identity assertion in the
   codebase, and it is the one that just failed.
5. **Is a player's identity campaign-scoped or global?** The same four humans
   appear across Phandalin, stormgiants and toee under different display names.

---

## Appendix — how these facts were checked

```bash
# 2 — the single production reader of the roster's player field
grep -rn 'apply_roster_player' --include=*.py . | grep -v '^./tests/'

# 4 — downstream reads the sheet, not the roster
grep -n 'frontmatter.get("player")' campaignlib/npc.py session_doc/roster.py

# B — the first-name + prefix rule
sed -n '27,66p' session_doc/voice.py
sed -n '20,32p' session_doc/examples.py

# drift — roster vs session_doc vs voice vs examples
cat  ~/src/campaigns/out-of-the-abyss/config/party.yaml
grep -A3 '^roster:' ~/src/campaigns/out-of-the-abyss/config/session_doc.yaml
ls   ~/src/campaigns/out-of-the-abyss/voice ~/src/campaigns/out-of-the-abyss/examples

# the three scenarios above, reproduced against the live campaign
python3 - <<'PY'
import sys; sys.path.insert(0, ".")
from pathlib import Path
from session_doc.sd_narrate import _load_examples
from session_doc.examples import get_char_examples, examples_routing_problems
ex = Path.home() / "src/campaigns/out-of-the-abyss/examples"
narrators = ["Zalthir", "Gyrgum", "Thorin Giantfriend", "Daz"]
for label, chars in [("A today", ["Zalthir","Grygum","Thorin","Daz"]),
                     ("B config-only fix", ["Zalthir","Gyrgum","Thorin","Daz"])]:
    g, per = _load_examples(ex, chars)
    print(label, "| global:", len(g) if g else 0,
          "| Gyrgum examples:", bool(get_char_examples(per, "Gyrgum")),
          "| detector:", examples_routing_problems(ex, chars, narrators))
PY

# E — the ID is on disk and read by nothing
find ~/src/campaigns -name '*.pdf'
grep -rniE 'dndbeyond|ddb_id|character_id' --include=*.py --include=*.vue .
```
