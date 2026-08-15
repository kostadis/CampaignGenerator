# Players and their characters — how-to

**Page:** Setup → Players · **Command:** `players` · **Spec:** `specs/009-player-entity-service/`

This is the task-oriented page: *"I want to do X, what do I type."* Its companion,
[`../config/players-isolation.md`](../config/players-isolation.md), is the reference —
ownership, the strict document, the service contract, what was retired and why. When the
two overlap, the reference wins.

Read this one when a narrator sounds wrong, a player's lines are not being attributed, or
you are setting up a campaign. Read the reference before you hand-edit `players.yaml`.

---

## What this actually is

Four different things get called "identity", and conflating any two of them has already
caused a defect:

| | What it is | Example | Stability |
|---|---|---|---|
| **person** | the human | Ben Pfaff | stable |
| **display name** | what the recording labels their speech | `Ben Pfaff`, `Dave`, `ncroussos` | **per session** — drifts without warning |
| **character** | the PC they play | Gyrgum | stable until a rename |
| **sheet** | D&D Beyond's record of that character | `kostadis1_67390528.pdf` | stable |

Two files hold all of it, and they divide cleanly:

```
config/players.yaml     the PEOPLE   — who is at the table, what the recording
                                       calls them, and which characters they play
config/party.yaml       the CHARACTERS — and every file that belongs to one:
                                       sheet, backstory, dossier, arc score,
                                       voice spec, style examples
```

Everything else that mentions a player — the roster block in a narration prompt, the
speaker labels in a transcript, the `Player:` line inside a converted sheet — is
**rendered from `players.yaml`**. Nothing reads any of them back. Editing one of those
copies changes nothing and will be reported as drift.

---

## Setting up a campaign

### If the campaign already exists

```bash
python -m server.migrate_players_config --campaign-dir ~/src/campaigns/<name>
```

One shot. It reads what the campaign already records — `party.yaml`'s old `player:`
field, each sheet's frontmatter, `session_doc.yaml`'s `gm_player` — drafts
`players.yaml`, and proposes `voice:`/`examples:` declarations by reproducing what the
old filename rule resolved to yesterday.

**Read the output.** It reports three kinds of thing it will not decide for you:

- **CONFLICTS** — two sources disagree about who plays a character. Neither is written,
  and the value stays in `party.yaml` so it is not lost. `party.yaml` refuses to load
  until you move the answer to `players.yaml`, which is the right kind of stuck.
- **Files attributed to nobody** — see [below](#a-file-nothing-declares).
- **Notes** — characters with no player recorded anywhere. Fill them in on the page.

Then:

```bash
players check --campaign-dir ~/src/campaigns/<name>
```

### If it is a new campaign

Open **Setup → Players** and add a row per human. Then open **Grounding → Party
Document** and give each character its sheet, its voice file and its examples file.

---

## The recurring tasks

### A player's Zoom name changed

**Add** the new one; do not replace the old one. Display names are a list, in the order
you wrote them, and every archived transcript still carries the old label.

```yaml
- id: wade
  name: Wade Brown
  display_names: [Wade, Wade Brown, wbrown]     # all three keep working
  plays: [Soma]
```

That is the whole fix. No sheet is re-converted, no other file is edited, and the next
run picks it up.

### A player left the campaign

Mark them inactive. **Do not delete them** — deleting breaks speaker resolution for every
session they were in.

```yaml
- id: gabe
  name: Gabe
  display_names: [Gabe]
  plays: [Zalthir]
  active: false
```

An inactive player keeps resolving in old transcripts, drops out of the roster block in
new prompts, and does not make their character look unplayed.

### You run the game and also play a PC

Record both. `gm` and `plays` are independent facts.

```yaml
- id: kostadis
  name: Kostadis Roussos
  display_names: [Kostadis Roussos, kostadis1]
  gm: true
  plays: [Calmer]
```

**Every** line you speak is labelled `GM`, including the ones you spoke as Calmer. That
is deliberate: a transcript label records *who spoke*, not in what capacity, and
labelling your narration and NPC dialogue with a PC's name is a false attribution — the
most expensive failure this system produces. The cost is real and accepted: your PC's
lines are not separable from the label alone.

### Two people share one character

List that character under both.

```yaml
- id: wade
  name: Wade Brown
  display_names: [Wade]
  plays: [Soma]
- id: gabe
  name: Gabe
  display_names: [Gabe]
  plays: [Soma]
```

### One person plays two characters

```yaml
  plays: [Soma, Brewbarry]
```

### A character was renamed

Rename it in `party.yaml`, then fix the three things that point at it:

1. the `voice:` and `examples:` paths on that character (or rename the files);
2. any `plays:` entry in `players.yaml` naming the old spelling;
3. the corpus, which is `spell_canon.py`'s job and not this feature's.

`players check` names 1 and 2 for you. This is the failure that ran for months
undetected (campaigns#175) and it now stops the run.

---

## When something is wrong

```bash
players check --campaign-dir ~/src/campaigns/<name> [--vtt path/to/session.vtt]
```

Read-only. No model call, no writes, no tokens. Exit 0 clean, 1 with findings.

### The six sections

| Section | Means |
|---|---|
| **Characters nobody plays** | `party.yaml` has them, no `plays:` entry anywhere names them |
| **Unknown character references** | a `plays:` entry naming a character the roster does not have — usually a rename, or a typo |
| **Players with no display name** | legitimate, but that person resolves in no transcript |
| **Declared files that are missing** | a `voice:`/`examples:`/`shared_examples:` path that is not there. **This one stops a render.** |
| **Files nothing declares** | present on disk, named by nobody, reaching nobody |
| **Display names absent from this transcript** | with `--vtt`. Each one, individually |

That last section is the reason to pass `--vtt`. The wrong-VTT pre-flight inside
`scene_extract` fires only when **zero** expected names match — it catches the whole map
being wrong and sails past three-of-four matching while the fourth player's every line
silently keeps a raw label. That second case is the one that actually happens.

### A file nothing declares

The report is telling you a file reaches nobody. It is one of three things, and only you
can say which:

| It is | Do this |
|---|---|
| campaign-wide style, meant for every narrator | add it to `shared_examples:` in `party.yaml` |
| one character's file whose name no longer matches | add a `voice:`/`examples:` entry to that character |
| an orphan from a rename, or a non-PC narrator's file | delete it, or leave it and accept the report |

There is no fourth option where it quietly reaches everyone. That used to be the default
and it is what this feature removes: measured before the change, **51,073 characters of
toee's house style, 7,285 of stormgiants' and 6,036 of obelisk's** were reaching every
narrator by falling through, because nothing matched them to a character.

---

## Every refusal, and what it means

### `character 'X' still carries the retired 'player' field`

`party.yaml` no longer holds who plays a character. Run the migration. It is refused
rather than ignored because a second location that still parses is how the two drift
apart silently.

### `duplicate player id 'wade' — held by 'Wade Brown' and 'Wade Other'`

An id identifies one person. Give one of them a different slug.

### `display name 'kostadis1' is held by two players`

A transcript line starting with that label would have two valid answers and no way to
choose. Record it under exactly one player. This is refused at save time, not reported,
because there is no correct guess.

### `these characters have no player bound to them: …`

A run refuses rather than proceeding with a partial map — that character's lines would
keep a raw transcript label. Bind them on the Players page, or run the migration.

### `no player entity was given`

`--players-config` was omitted. Pass `<campaign>/config/players.yaml`, or run the
migration if the campaign has not been adopted.

### `narrator 'Gyrgum': declared voice file does not exist — voice/grygum_voice.md`

The roster names a file that is not there. This fires **before the first API call**, so
nothing has been spent. Fix the path or create the file.

### `narrator 'Bob': not a character in party.yaml`

The plan and the roster disagree about a name. That disagreement *is* the finding —
nothing will match it approximately for you.

### `lists characters but none of them names a sheet` (adoption)

This is obelisk. Its `config/party.yaml` is a PC-name exclusion list for the entity
registry, read by `campaignlib.party.load_party_names` — two contracts over one filename.
Which use wins is your ruling, so the migration declines rather than inventing a roster.

---

## Why it works this way

One sentence from `docs/design/PlayerIdentity.md`, which surveyed the fourteen stores this
replaced:

> Everything that fails **loudly** is a path, or an exact-match refusal. Everything that
> fails **silently** is a name *approximately* matched.

So every join here is a declared path or an exact match. A character's voice file is
named, not found. A display name is matched literally, never by prefix. `Gyrgum` does not
resolve to `grygum_voice.md` because they look alike — and if you want them joined, you
say so.

Five defects came from the other approach: #247 (a voice file that never reached the
prompt for five months), #300 (a typo'd directory that dropped every spec), #301 (one
character's style steering all of them), campaigns#175 (a rename that broke a campaign
silently), and #315 (the detector for #301, which could not see a rename).

`tests/test_no_prefix_identity.py` fails the build if any of it comes back.

---

## Reference

- [`../config/players-isolation.md`](../config/players-isolation.md) — the service, the
  document schema, what was retired
- [`../design/PlayerIdentity.md`](../design/PlayerIdentity.md) — the survey this came from
- `specs/009-player-entity-service/` — spec, plan, research, contracts, quickstart
