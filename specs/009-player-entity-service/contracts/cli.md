# Contract — the CLI surface

Three things change at the command line: a flag arrives, two flags leave, and two
programs are new.

## 1. `--players-config PATH` — the new seam

Added to four CLIs, mirroring `--party-config` (#265):

| CLI | Uses it for |
|---|---|
| `scene_extract` | the speaker map for `normalize_vtt_speakers` |
| `enhance_summary` | the speaker map, and expected-speaker pre-flight |
| `sd_narrate` | the person's name in the prompt roster block |
| `dnd_sheet` | the player value stamped into a converted sheet |

Conventionally `<campaign>/config/players.yaml`. Resolution and refusal follow
`load_party_config_arg`'s established shape: a missing path and malformed YAML each
print to stderr; a consumer that cannot proceed without it exits 1 naming what is
missing and how to create it.

**A config path, not a flag per attribute.** Passing display names on the command
line would reproduce the stringly-typed roster this feature deletes.

## 2. Deleted flags

| Flag | On | Replaced by |
|---|---|---|
| `--gm-player NAME` | `scene_extract`, `enhance_summary`, `sd_agent` | the `gm: true` player in `players.yaml`. One string cannot hold a list of display names (FR-003). |
| `--characters NAMES` | `sd_narrate` | nothing — it was the routing key for a rule that no longer exists (FR-031). |

`sd_plan --characters` **stays**. It assigns a narrator per scene; it is not a routing
key. `server/routers/scene_editor.py:1651` sources its value from `party.yaml`'s
character names instead of the deleted `cfg.roster.characters`.

## 3. `players` — new console script

`pipelines/workspace/players.py`, registered in `pyproject.toml`. Engine layer: it
reads `players.yaml`, `party.yaml` and an optional transcript, and imports nothing
from `server` (research D1, D10).

```
players check [--campaign-dir DIR] [--vtt FILE]
```

Read-only. No model call, no writes — the same guarantee `provenance` and
`registry check` carry.

Reports, in sections:

| Section | Finding |
|---|---|
| Characters nobody plays | in `party.yaml`, in no **active** player's `plays` |
| Unknown character references | a `plays` entry with no matching character |
| Players with no display name | cannot be resolved in any transcript |
| Declared files that are missing | a `voice`/`examples`/`shared_examples` path that does not exist |
| Files nothing declares | present in `voice_dir`/`examples_dir`, declared by nobody — the orphan a rename produces |
| Display names absent from this transcript | with `--vtt`; **each one**, including when only one of four is absent |

Exit `0` when every section is empty, `1` when anything is found — matching
`registry check`. The last section is the one the existing wrong-VTT pre-flight
cannot produce: that pre-flight fires only when *zero* expected names match, which is
the case that has never been the problem (FR-039).

## 4. `server.migrate_players_config` — new one-shot

```
python -m server.migrate_players_config --campaign-dir DIR [--config-dir config] [--force]
```

Lives in `server/` because it must read and then strip `session_doc.yaml`'s `roster`
group, which is a `server/` model — the same reason every other one-shot migration in
this repo lives there.

**Reads** (all of them, and reports where they disagree):

| Source | Contributes |
|---|---|
| `party.yaml` `characters[].player` | a person's name, and the character binding |
| each character's sheet frontmatter `player` | a second opinion on the same person |
| `session_doc.yaml` `roster.gm_player` | the game master's display name |
| `voice_dir` / `examples_dir` listings | proposed `voice` / `examples` declarations, by the current prefix rule |

**Writes**, only with the GM's agreement to the reported result:

- `players.yaml` — the drafted roster;
- `party.yaml` — `voice`/`examples` declarations added, `shared_examples` populated
  from files the prefix rule attributed to nobody, `player:` removed;
- `session_doc.yaml` — the `roster` group removed.

**Rules:**

| Rule | Behaviour |
|---|---|
| Conflict between two sources | **reported with both values and their origins; neither written.** A conflict is a GM ruling, not a merge rule (FR-032). |
| Existing `players.yaml` | refuses without `--force` (FR-033) |
| Placeholder value (`""`, `not specified`, `n/a`, `none`, `unknown`, `tbd`, bracketed or not) | recorded as no display name, never as a person (FR-034) |
| A file the prefix rule attributed to nobody | proposed for `shared_examples`, and **listed**, so the GM rules rather than the tool guessing (FR-035) |
| Unrecognised key | reported, not dropped |
| `party.yaml` that is a bare name list with no `sheet:` | **refuses this campaign by name.** obelisk (research M2) — two incompatible uses of one filename, and which wins is a GM ruling |

**Expect very little for four campaigns, and say so.** Only Phandalin and
out-of-the-abyss record any `player:` (research M1). An almost-empty result is the
correct outcome there, not a failure — the lesson `migrate_grounding_config.py`
records in its own docstring.

## 5. Argv changes in `server/routers/scene_editor.py`

| Builder | Before | After |
|---|---|---|
| narrate | `--voice-dir`, `--examples`, `--characters` from `cfg.paths` / `cfg.roster` | `--party-config`, `--players-config` |
| plan | `--characters` from `cfg.roster.characters` | `--characters` from `party.yaml`'s character names |
| extract | `--gm-player` from `cfg.roster.gm_player` | `--players-config` |

The two pre-flights at `scene_editor.py:760` (`_load_examples_args`) and `:827`
(`_load_voice_dir`) keep their job — refuse before a run rather than warn during one —
and change what they check: a declared path that is absent, instead of a name that
matches no file.
