# The Player entity, isolated

**Feature 009.** `<campaign>/config/players.yaml`, owned exclusively by
`PlayersConfigService`. Sibling to
[grounding-isolation.md](./grounding-isolation.md) and
[planning-isolation.md](./planning-isolation.md), and built to the same shape —
but this one is not a config extraction. It models something that had no model
at all.

## Why

`docs/design/PlayerIdentity.md` (CG#314) surveyed where a player's identity
lived and found **five join keys across fourteen stores**, none naming the
others. The useful finding was not the count:

> Everything that fails **loudly** is a path, or an exact-match refusal.
> Everything that fails **silently** is a name *approximately* matched.

Five defects came out of the silent half — #247, #300, #301, #315 and
campaigns#175 — and the last of them was live in a campaign while the survey was
being written. This feature acts on that split rather than adding a fifteenth
store.

## What owns what, after

| Fact | Lives in | Read by |
|---|---|---|
| the person, and every label a recording has used for them | `players.yaml` | the roster block, speaker normalisation, the sheet stamp |
| who plays which character | `players.yaml` (`plays:`) | the same |
| the character, its sheet, backstory, dossier, arc score | `party.yaml` | every render pipeline |
| **the character's voice file and examples file** | `party.yaml` (`voice:`, `examples:`) | `sd_narrate`, `polish` |
| campaign-wide style examples | `party.yaml` (`shared_examples:`) | `sd_narrate` |

Three fields were **removed**, not deprecated:

| Retired | Was in | Replaced by |
|---|---|---|
| `player:` | `party.yaml`'s character entry | `players.yaml` |
| `roster.characters` | `session_doc.yaml` | derived from `party.yaml` |
| `roster.gm_player` | `session_doc.yaml` | the `gm: true` player |

A document still carrying `player:` is **refused by name**, with the migration
command in the message. A location that still parses is a split brain waiting to
happen — the repo's standing rule is migrate-and-delete.

## The two rules worth knowing

**1. A file reaches a prompt because something named it.** There is no
fall-through. A voice or example file that nothing declares is *unused*, not
shared, and `players check` reports it. Before this, an undeclared example file
joined a GLOBAL block passed to **every** narrator — measured across the live
campaigns, that was 6,036 characters in obelisk, 7,285 in stormgiants and 51,073
in toee, none of it chosen by anyone.

**2. The game-master label always wins.** A person who both runs the game and
plays a character (toee's `Calmer`) has every line labelled as the game master.
A transcript label records *who spoke*, not in what capacity; labelling their
lines with the character's name would attribute narration and NPC speech to a
player character, and a false attribution is the most expensive failure this
system can produce.

## Surfaces

| | Where |
|---|---|
| Models + YAML I/O | `campaignlib/players_config.py` |
| Service | `server/players_config_service.py` |
| Routes | `server/routers/players_routes.py` → `/api/players/*` |
| Page | Setup → Players (`frontend/src/views/setup/Players.vue`) |
| CLI seam | `--players-config` on `sd_narrate`, `scene_extract`, `enhance_summary`, `dnd_sheet`, `polish` |
| Check | `players check [--campaign-dir DIR] [--vtt FILE]` |
| Adoption | `python -m server.migrate_players_config --campaign-dir DIR [--force]` |

The models live in `campaignlib` and the check in `pipelines/` so neither
imports `server` (`tests/test_layering.py`). The adoption CLI is in `server/`
because it must read and then strip `session_doc.yaml`'s `roster` group, which
is a `server/` model — the same reason every other one-shot migration is there.

## Strict where it must be, lenient where it should be

**Refused** — shape, and two uniqueness rules:

- a duplicate `id`, which makes every reference to that player ambiguous;
- **a display name held by two players**, which would leave the speaker map
  with two valid answers and no way to choose.

**Reported, never blocking a save** — references: a binding to a character that
does not exist yet, a player with no display names, a declared file that is not
there. The GM must be able to name a character they are about to add (D4 in
`grounding-isolation.md`).

## Adoption

```bash
python -m server.migrate_players_config --campaign-dir ~/src/campaigns/<name>
players check --campaign-dir ~/src/campaigns/<name>
```

It harvests from `party.yaml`'s `player:`, each sheet's frontmatter, and
`session_doc.yaml`'s `gm_player`, and proposes `voice:`/`examples:` declarations
by running the *outgoing* prefix rule once — reproducing yesterday's answer
rather than inventing one.

**It reports; it does not decide.** Where two sources disagree about a person,
both values are printed and neither is written. Every file it cannot attribute
to a character is listed with a ready-to-paste `shared_examples:` block, because
"this file matched no character" and "this file belongs to the whole campaign"
are the same observation and three different decisions.

**Expect little from four of the six campaigns, and that is correct.** Only
Phandalin and out-of-the-abyss recorded a `player:` at all. obelisk is refused
by name: its `config/party.yaml` is a PC-name exclusion list read by
`campaignlib.party.load_party_names`, not a roster — two contracts over one
filename, and which wins is a GM ruling.

## Guarded by

- `tests/test_no_prefix_identity.py` — the deleted symbols stay deleted, and no
  module in the render path resolves one *name* against another with
  `startswith`. This is what makes "zero prefix-matched identity joins" a test
  result rather than a claim.
- `tests/test_layering.py` — nothing in `campaignlib`/`pipelines`/`session_doc`
  imports `server`.
- `tests/test_players_config.py`, `test_players_config_service.py`,
  `test_players_routes.py`, `test_players_check.py`,
  `test_migrate_players_config.py`.
