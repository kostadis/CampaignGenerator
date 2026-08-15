# Contract — `<campaign>/config/players.yaml`

The new document. Owned exclusively by `PlayersConfigService`; modelled by
`campaignlib.players_config`. Strict (`extra="forbid"`).

Located via `campaignlib.constants.config_path(campaign_dir, "players.yaml")`.
**One declared location, no fallback probe** — see research D2.

## Shape

```yaml
players:
  - id: ben                          # required, unique, GM-authored slug
    name: Ben Pfaff                  # required — renders into prompts
    display_names: [Ben Pfaff]       # exact transcript labels, ordered, may be empty
    plays: [Gyrgum]                  # character names in this campaign's party.yaml
    dndbeyond_id: "67390528"         # optional; recorded, read by nothing (#312)

  - id: wade
    name: Wade Brown
    display_names: [Wade, Wade Brown]   # both, because the label drifted mid-campaign
    plays: [Soma]

  - id: kostadis
    name: Kostadis Roussos
    display_names: [Kostadis Roussos, kostadis1]
    gm: true                         # runs the game
    plays: [Calmer]                  # and plays a PC — both labels are recorded,
                                     # but the GM label wins for speakers (FR-021a)

  - id: gabe
    name: Gabe
    display_names: [Gabe]
    plays: [Zalthir]
    active: false                    # left the campaign; the archive still says "Gabe:"
```

## Field reference

| Key | Type | Default | Required |
|---|---|---|---|
| `players[].id` | string | — | **yes** |
| `players[].name` | string | — | **yes** |
| `players[].display_names` | list of string | `[]` | no |
| `players[].plays` | list of string | `[]` | no |
| `players[].gm` | bool | `false` | no |
| `players[].active` | bool | `true` | no |
| `players[].dndbeyond_id` | string or null | `null` | no |

Nothing else is accepted. An unknown key names itself and the entry, and the load
refuses.

## Write contract

- **Atomic** — `campaignlib.util.atomic_write_text`, so a crash mid-write leaves the
  previous document intact.
- **As authored** — the saver hand-builds the dict and omits defaults, so a
  load/save round-trip does not rewrite what the GM wrote or add `active: true` to
  every row.
- **Both ends, or nothing** — loader and saver each hand-build. A new field must be
  named in **both** or it round-trips to nothing. This has already happened once in
  this codebase, to `party.yaml`'s `selection`.

## Read contract

| Input | Result |
|---|---|
| file absent | `PlayersConfig(players=[])` — not an error |
| file empty, or parses to `null` | `PlayersConfig(players=[])` |
| top level not a mapping | `ValueError`, naming the file |
| duplicate `id` | `ValueError`, naming both entries |
| a `display_name` under two players | `ValueError`, naming both players and the value |
| unknown key | `ValueError`, naming the key and the entry |

## Derived helper

```python
speaker_map(players: PlayersConfig, party: PartyConfig) -> dict[str, str]
```

Display name → the label a transcript line becomes. Built in two passes:

1. every **player** display name → the first character in their `plays`;
2. then every **game master** display name → the game-master label, overwriting.

The second pass is last so a person who is both gets the game-master label, which is
FR-021a and is also exactly what `normalize_vtt_speakers` does today with its
`full_map[gm_player] = "GM"` line. Longest-key-first matching in
`normalize_vtt_speakers` is unchanged and is what handles `Mike` versus `Mike Hall`.
