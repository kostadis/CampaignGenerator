# Phase 0 Research — Player Entity & Config Service

**Feature**: `009-player-entity-service` | **Date**: 2026-08-15

Everything below was measured against the working tree at `origin/main` (`b2fcf64`)
and the six live campaigns in `~/src/campaigns`, not inferred. The reproduction
script is in the appendix. Extend this file rather than re-deriving it.

---

## M — Measurements taken 2026-08-15

These are the facts the decisions rest on. Several were surprises.

### M1. Only two of six campaigns record a player at all

```
Phandalin            4 chars, 4 with player
out-of-the-abyss     4 chars, 4 with player
stormgiants          3 chars, 0 with player
toee                 4 chars, 0 with player
Hillsfar             4 chars, 0 with player
obelisk              party.yaml DOES NOT LOAD
```

So adoption has very little to harvest, and "the migration will be nearly empty
for four campaigns" must be stated in its output rather than reading as a failure
(the lesson `server/migrate_grounding_config.py` records in its own docstring).

### M2. `obelisk/config/party.yaml` is not a roster

It is a PC-name **exclusion list** for the entity registry — entries carry `name`
and nothing else, and several are NPC titles (`"Professor"`, `"Veyra"`,
`"Sister Maela"`). Two readers, two contracts, one filename:

| Reader | Contract | On obelisk |
|---|---|---|
| `campaignlib.party.load_party_names` | needs `name` only | **works** — that is what it is for |
| `campaignlib.party_config.load_party_config` | needs `name` **and** `sheet` | **raises** `missing 'name' or 'sheet': {'name': 'Zenvon Forepot'}` |

This blocks obelisk from adoption and from declared routing, and it is not this
feature's job to rule on obelisk's data. Recorded as a known blocker (see D12).

### M3. Example routing today, measured by running the real loaders

| Campaign | Example files | Global block (reaches **every** narrator) | Narrators with no per-character examples | `examples_routing_problems` |
|---|---|---|---|---|
| Phandalin | 4 named after PCs | 0 chars | none | `[]` |
| out-of-the-abyss | 4 named after PCs | 0 chars | none | `[]` |
| obelisk | `house_style.md`, `zenvon.md` | **6,036** | none | `[]` |
| stormgiants | `orsik`, **`thistl`**, `unla`, `vardis` | **7,285** | **`Thistle`** | `[]` |
| toee | 6 house-style files | **51,073** | all four | `[]` |

Two findings here that were not previously known:

- **stormgiants has a live instance of the class.** `thistl.md` is a typo.
  `routes_to("thistl", "thistle")` is false, so it routes to nobody, falls into the
  global block, and reaches all four narrators — while `Thistle` receives no
  examples of their own. Identical in shape to campaigns#175, in a second campaign,
  and the detector is silent on it. (stormgiants has no `session_doc.yaml`, so it is
  not driving Pass 5 through the UI today; the misconfiguration is nonetheless real
  and on disk.)
- **obelisk's `house_style.md` and toee's six files are the legitimate shared case.**
  They work only because of the fall-through FR-030a deletes, which is exactly why
  FR-030 needs somewhere explicit to put them.

### M4. Voice resolution today, and four files no narrator can reach

| Campaign | Voice keys | All PC narrators resolve? | Files no PC narrator uses |
|---|---|---|---|
| Phandalin | `*_new_pipeline` ×4 | yes — via prefix rule step (c) only | none |
| out-of-the-abyss | `daz, gyrgum, thorin, vizeran, zalthir` | yes (post campaigns#176) | **`vizeran`** |
| obelisk | `maela, pip, veyra, zenvon` | yes | **`maela, pip, veyra`** |
| stormgiants | `orsik, thistle, unla_key, vardis` | yes — `unla_key` via step (c) | none |
| toee | four, exact | yes | none |

The four unreachable files are NPC voice specifications. **No narrator uses them
today** — narrators come from `sd_plan --characters`, which is a PC list. They are
already dead weight, which is what makes D11's simplification safe.

Phandalin resolves *only* through step (c) of the prefix rule (`brewbarry` →
`brewbarry_new_pipeline`). Deleting that rule without adding declarations would
break all four of Phandalin's narrators, so D5 and the migration are coupled.

### M5. Existing name drift across the stores

| Campaign | `party.yaml` | `session_doc.yaml` `roster.characters` | voice stem | examples stem |
|---|---|---|---|---|
| Phandalin | `Valphine Sotorra` | `Valphine` | `valphine_new_pipeline` | `valphine` |
| stormgiants | `Unla Key` | *(no file)* | `unla_key` | `unla` |
| stormgiants | **Thistle absent from the roster** | *(no file)* | `thistle` | `thistl` |
| out-of-the-abyss | `Thorin Giantfriend` | `Thorin` | `thorin` | `thorin` |
| obelisk | *(does not load)* | `Zenvon` | `zenvon` | `zenvon` |

Every one of these joins survives only because the prefix rule is lenient. Each is a
row the adoption step must present to the GM rather than resolve.

---

## D — Decisions

### D1. The models live in `campaignlib`, not `server`

**Decision.** `campaignlib/players_config.py` holds the pydantic models and the
YAML load/save, exactly as `campaignlib/party_config.py` does.

**Rationale.** `tests/test_layering.py` fails the build if anything in
`campaignlib`, `pipelines`, `session_doc`, `entity_registry` or `provenance`
imports `server`. The CLIs need these models (D8), so `server/` is not an option.
This is the same move `party_config.py` already made, and the layering test exists
because two CLIs had inverted the arrow.

**Alternatives rejected.** A `server/players_config_shared.py` — fails the layering
test the moment a CLI reads the document.

### D2. One document, one declared location: `<campaign>/config/players.yaml`

**Decision.** Resolved through `campaignlib.constants.config_path`. No candidate
list, no fallback probe.

**Rationale.** `config_path`'s own docstring records the incident: four probes for
`party.yaml` alone, disagreeing on candidate set *and* precedence, which left
obelisk's roster visible to PC-name filtering and invisible to the Party page at
the same time. A second location is how this feature becomes the fifteenth store.

### D3. Service and routes mirror `PartyConfigService`

**Decision.** `server/players_config_service.py` + `server/routers/players_routes.py`,
mounted `app.include_router(players_routes.router, prefix="/api/players")`.

Carry across the three lessons the sibling docstrings record:

1. **Do not set `prefix=` on the router** — `main.py` supplies it, or everything
   mounts at `/api/players/api/players/*`.
2. **An emptied document reads back as `[]`, not a 400** — the bug
   `docs/config/planning-isolation.md` had to fix twice.
3. **Lenient save, reporting read** — a save naming a character that does not exist
   yet succeeds and the warning rides on the response (`missing_files`'s shape).
   This is spec FR-017.

**Also.** `replace_all` (a single atomic `PUT /characters`-style write) rather than
per-row CRUD, because the page edits the table as a unit and row order is
meaningful — `PartyConfigService.replace_all`'s docstring records why the
delete-all-then-recreate alternative is worse.

### D4. The UI page lives at `/setup/players`

**Decision.** A new child route under `SetupTools.vue`, sibling to `dnd-sheet` and
`make-tracking`, with a cross-link from the Party Document page's roster editor.

**Rationale.** `/grounding/*` pages generate documents; `players.yaml` generates
nothing. `/setup` already means "configure this campaign", and `DndSheet.vue` — the
one pipeline that stamps the player value into a sheet — is already there.

**Alternative considered.** `/grounding/players`, adjacent to the existing
`PartyConfigEditor` inside `PartyDocument.vue`. Rejected on taxonomy, but it wins on
discoverability, which is why the cross-link is part of the decision rather than a
nicety. This is reversible in one line of `frontend/src/router.ts`.

### D5. A character declares its voice and example files in `party.yaml`

**Decision.** `PartyCharacter` gains two optional authored-path fields, `voice` and
`examples`, and both join `PATH_FIELDS`.

**Rationale.** `PATH_FIELDS = ("sheet", "backstory", "dossier", "arc_score")` is
already "this character's files"; `missing_files` already reports absences and the
Party page already renders them. A path is the join that fails loudly — that is the
entire finding of `docs/design/PlayerIdentity.md`, and adding two more paths turns
the last two silent joins into loud ones with no new machinery.

Paths are campaign-root-relative, exactly like `sheet:` (#291 made that uniform).

**Alternatives rejected.**
- A declaration inside `players.yaml`. A voice file belongs to a *character*, not to
  the human playing them; putting it on the player breaks when one player has two
  characters.
- A separate `voices.yaml`. A fifteenth store to hold four rows.

### D6. Campaign-wide shared examples are a root key in `party.yaml`

**Decision.** `shared_examples: [path, …]` at the root of `party.yaml`, beside the
existing root `selection:` key.

**Rationale.** Three reasons, in order of weight:

1. **Layering.** The obvious alternative — `session_doc.yaml`'s `paths` group, which
   already owns `voice_dir` and `examples_dir` — is a `server/` model. `sd_narrate`
   and the `players check` CLI both need the shared list, and neither may import
   `server` (D1).
2. **No new argv flag.** `sd_narrate` already takes `--party-config`. Putting the
   list there means the shared block arrives through a seam that exists.
3. `party.yaml` is not purely a roster already — it carries a root `selection:`.

**Consequence for `voice_dir` / `examples_dir`.** They stay, but they stop being the
routing mechanism. They are what the orphan check (FR-030b) enumerates to find files
nothing declares, and `pipelines/ensemble/polish.py` still scans `voice_dir`
directly.

### D7. Delete the prefix rule; keep the directory loader

**Decision.** Precisely scoped, so `polish.py` is not collateral damage:

| Symbol | Fate |
|---|---|
| `session_doc/voice.py :: _resolve_voice_key` | **delete** — steps (a)(b)(c) are the prefix rule |
| `session_doc/voice.py :: get_voice_note` | rewrite: exact character-name lookup over declared files |
| `session_doc/voice.py :: voice_resolution_problems` | rewrite: "declared file missing", not "no key matches" |
| `session_doc/voice.py :: load_voice_files` | **keep** — `polish.py` and the orphan check enumerate a directory |
| `session_doc/voice.py :: extract_contrast_sample` | keep, untouched |
| `session_doc/examples.py :: routes_to` | **delete** |
| `session_doc/examples.py :: examples_routing_problems` | **delete** — this closes #315 by removing the detector along with the thing it failed to detect |
| `session_doc/examples.py :: example_files` | **keep** — the orphan check needs it |
| `session_doc/examples.py :: get_char_examples` | rewrite: exact lookup |
| `session_doc/sd_narrate.py :: _load_examples` | rewrite: read declared paths; no fall-through |

**Rationale.** SC-006 is a countable outcome — zero prefix-matched identity joins —
and it is only countable if the functions are gone rather than bypassed. #315 is
resolved by deletion: a detector for a fall-through that no longer exists has
nothing to detect.

### D8. `--players-config` is the CLI seam; `--gm-player` and `--characters` go

**Decision.** Four CLIs gain `--players-config PATH`, mirroring `--party-config`:
`scene_extract`, `enhance_summary`, `sd_narrate`, `dnd_sheet`. Two flags are deleted:

- `--gm-player NAME` (`scene_extract`, `enhance_summary`, `sd_agent`) — it is one
  string, and a player has a *list* of display names (FR-003). Widening it to a list
  in argv reproduces the stringly-typed roster this feature is deleting.
- `--characters NAMES` (`sd_narrate`) — the routing key it fed no longer exists.
  `sd_plan --characters` **stays** (it is a scene-assignment input, not a routing
  key), but `server/routers/scene_editor.py:1651` sources it from the party roster
  instead of `cfg.roster.characters`.

**Rationale.** Constitution VI: the CLI is the engine and the UI shells out to it.
A flag per player attribute is the wrong seam; a config path is the right one, and
the repo already established it with `--party-config` in #265.

### D9. One function builds the speaker map

**Decision.** `campaignlib.players_config.speaker_map(players, party) -> dict[str, str]`
returns display-name → label for the whole campaign, GM entries written **last** so
they overwrite (FR-021a). `normalize_vtt_speakers` loses its `gm_player` parameter
and takes the finished map.

**Rationale.** `normalize_vtt_speakers` already does `full_map[gm_player] = "GM"`
after building from `player_map`, so the GM-wins ordering is preserved behaviour,
now stated once instead of assembled at three call sites. Longest-key-first matching
is unchanged and is what satisfies FR-020's `Mike` / `Mike Hall` case.

### D10. Adoption is a `server/` one-shot; the check is an engine CLI

**Decision.** Two programs, because they need different things:

| | Adoption | Check |
|---|---|---|
| Invocation | `python -m server.migrate_players_config --campaign-dir DIR [--force]` | `players check` (console script) |
| Lives in | `server/` | `pipelines/workspace/players.py` |
| Why there | must read **and strip** `session_doc.yaml`'s `roster.*`, which is a `server/` model | reads only `players.yaml` + `party.yaml` + an optional VTT — no server import, so it obeys D1 |
| Exit | 0 written / non-zero refused | 0 clean / 1 findings, matching `registry check` |

**Rationale.** Every existing one-shot migration in this repo lives in `server/` for
the same reason (`migrate_session_doc`, `migrate_ensemble_config`,
`migrate_grounding_config`, `migrate_narrate_genre`). The check must be runnable
from a campaign directory with no server, like `registry check` and
`provenance check`.

### D11. No `--extra-voice`; unreachable NPC voice files are reported, not rescued

**Decision.** The feature adds no mechanism for non-PC narrator voices. The four
files in M4 become orphans that `players check` names.

**Rationale.** M4 measured it: **no narrator reaches them today**. Narrators come
from `sd_plan`, which assigns from the PC list. Building a declaration mechanism for
a capability nothing exercises is a recurring tax against no benefit (Constitution,
"Architecture is Destiny"). If NPC narration is ever wanted, `sd_plan` has to change
first, and the declaration goes in with it.

### D12. obelisk is a known blocker, reported not worked around

**Decision.** Adoption detects M2's shape — a `characters:` list whose entries have
no `sheet:` — and refuses that campaign with a message naming the collision, rather
than crashing on the `ValueError` or inventing a roster.

**Rationale.** Which of obelisk's two uses of `party.yaml` wins is a GM ruling about
campaign data, and Constitution II puts that outside a migration's authority. Five
campaigns adopt; obelisk waits on the ruling. This must be visible in the plan, not
discovered when the migration throws.

### D13. The sheet keeps its `player:` value and stops being read for it

**Decision.** `apply_roster_player` keeps writing both channels (frontmatter and the
`## Identity` line) — sourced from the entity now (FR-022). The two readers change:

- `campaignlib/npc.py:331` `player_map_from_config` — stops reading
  `frontmatter.get("player")`; the map comes from the players service.
- `session_doc/roster.py:136` `roster_from_config` — stops reading the sheet's
  `player`, keeps reading `species` / `class_level` / `subclass`. The sheet stays
  canonical for character data (spec FR-014).

**Rationale.** FR-023 says the stamped value is a rendered copy. Leaving it written
keeps the document self-consistent for a human reading it; the
`apply_roster_player` docstring already argues "both, or the document contradicts
itself".

### D14. `extract_player_character_map` and `extract_character_roster` are unaffected

**Decision.** Out of scope. They parse `party.md`, they are already unreachable from
the render path (#265 deleted the fallback; `require_from_config` exits instead), and
`campaignlib/party_md.py` is shared with other consumers.

**Rationale.** Deleting them is a separate cleanup (#293's far side already names it).
Touching them here widens the diff with no requirement behind it.

### D15. Test surface

New, mirroring the sibling suites: `test_players_config.py`,
`test_players_config_service.py`, `test_players_routes.py`,
`test_migrate_players_config.py`, `test_players_check.py`.

Changed: `test_roster.py`, `test_sd_narrate.py`, `test_party_config.py`,
`test_party_config_service.py`, `test_party_routes.py`, `test_editor_pipeline.py`
(its `Roster(characters=…)` fixtures and the three `--characters` forwarding
assertions at lines 240–272 and 736–812), `test_prep.py`.

**One new guard test**, in the shape of `test_ensemble_config_defaults.py`: assert
that `routes_to`, `examples_routing_problems` and `_resolve_voice_key` do not exist,
and that no module in the render path resolves a name by `startswith`. That is what
makes SC-006 an assertion rather than a claim.

### D16. Worktree testing caveat

`tests/conftest.py` inserts `REPO_ROOT` because the editable-install `.pth`
hardcodes the main checkout, so `import campaignlib` in a worktree can resolve to
`main`'s copy. Six test files also skip silently in a worktree (#286). **A green
worktree run is not by itself evidence** — the quickstart's verification steps run
the real loaders against real campaign directories for that reason.

### D17. Implementation order is not priority order

The spec's P1…P5 is *value* order. FR-036 forbids leaving a retired field readable,
so the safe *build* order differs:

```
1. players.yaml + service + routes + page   (US1) — purely additive, nothing reads it
2. adoption                                  (US4) — fills it, before anything depends on it
3. flip the player consumers                 (US2) — retire party.yaml's player:, roster.gm_player
4. declared voice/examples routing           (US3) — retire the prefix rule, roster.characters
5. check                                     (US5) — reports what remains
```

Steps 3 and 4 each delete a field in the same commit that stops reading it. Step 2
must precede them per campaign or the campaign breaks loudly (which is the designed
behaviour, but not a state to ship through).

### D18. Scale and performance

Six campaigns, at most four players each, at most six example files. The document is
under 2 KB. No performance requirement, no caching, no pagination. Stated so the
plan does not invent one.

### D19. Where reports go — the outstanding item from `/speckit-clarify`

**Decision.** Follow the conventions already in the codebase; introduce none.

| Surface | Convention |
|---|---|
| Service / API | Lenient save; the report rides on the response body, as `missing_files` does today |
| Render CLI refusal | stderr, naming the character or player, then `sys.exit(1)` — the shape `require_from_config` and `voice_resolution_problems` already use |
| `players check` | findings on stdout in sections; exit 0 clean, 1 with findings (`registry check`) |
| Adoption | conflicts and unrecognised keys on stdout; refuses to clobber without `--force` |

---

## Appendix — how these facts were checked

```bash
# M1, M3, M4 — run the real loaders against the live campaigns
python3 specs/009-player-entity-service/contracts/measure.py

# M2 — the two contracts over one file
grep -n "def load_party_names" -A 14 campaignlib/party.py
python3 -c "import sys;sys.path.insert(0,'.');from pathlib import Path;\
from campaignlib.party_config import load_party_config;\
load_party_config(Path.home()/'src/campaigns/obelisk/config/party.yaml')"

# M5 — the four stores, side by side
grep -H 'player:' ~/src/campaigns/*/config/party.yaml
grep -H 'characters:\|gm_player:' ~/src/campaigns/*/config/session_doc.yaml
ls ~/src/campaigns/*/voice/ ~/src/campaigns/*/examples/

# D7 — every call site of the symbols being deleted
grep -rn "routes_to\|examples_routing_problems\|_resolve_voice_key" --include=*.py .

# D8 — the flags being deleted
grep -rn "gm_player\|--gm-player\|--characters" --include=*.py . | grep -v '^./tests/'

# D1 — the layering guard
sed -n '20,35p' tests/test_layering.py
```
