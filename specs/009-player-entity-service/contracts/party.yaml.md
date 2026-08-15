# Contract — `<campaign>/config/party.yaml` (changed)

Owned by `PartyConfigService`, modelled by `campaignlib.party_config`. This feature
adds two per-character path fields, adds one root list, and removes one field.

## After

```yaml
characters:
  - name: Gyrgum
    sheet: docs/Gyrgum.md
    backstory: docs/grygum_backstory.md
    dossier: docs/ensemble/merged_dossiers/npc_grygum.md
    voice: voice/gyrgum_voice.md          # NEW — declared, not matched
    examples: examples/gyrgum.md          # NEW — declared, not matched
    arc_score: null                       # (unchanged three-state encoding)
    # player: Ben Pfaff                   # REMOVED — players.yaml owns this

shared_examples:                          # NEW — reaches EVERY narrator, by declaration
  - examples/combat_and_consequences.md
  - examples/political_maneuvering.md

selection: {}                             # unchanged root key
```

## Changes

| Key | Change | Why |
|---|---|---|
| `characters[].voice` | **added**, optional authored path | A path fails loudly; a name prefix fails silently. Joins `PATH_FIELDS`. |
| `characters[].examples` | **added**, optional authored path | Same. |
| `characters[].player` | **removed** | FR-011/FR-012 — the player entity owns the binding. |
| `shared_examples` | **added**, list of authored paths, default `[]` | FR-030 — the only way campaign-wide example material reaches a narrator. |

```python
PATH_FIELDS = ("sheet", "backstory", "dossier", "arc_score", "voice", "examples")
```

`missing_files` walks `PATH_FIELDS`, so both new fields are reported by the existing
mechanism with no new code. `shared_examples` is reported alongside, keyed to the
campaign rather than to a character.

## Paths

Campaign-root-relative, exactly like `sheet`. #291 rewrote every campaign's paths
that way, so `load_party_config_arg`'s cwd default is correct everywhere; the two new
fields inherit that and introduce no new base-directory question.

## Refusals

| Condition | Behaviour |
|---|---|
| `characters[].player` present | `ValueError` naming the character and the retired field, with the adoption command in the message (FR-013, FR-037) |
| Unknown key | `ValueError` naming the key |
| `characters[]` entry without `name` or `sheet` | `ValueError` — unchanged, and the reason obelisk does not load (research M2) |
| A declared `voice`/`examples` file absent | **not** a refusal at save; reported by `missing_files`. A refusal at run time (FR-028) |

## Loader/saver warning

Both hand-build their dict; a field named in only one round-trips to nothing. Three
fields must be named in both: `voice`, `examples`, `shared_examples`. `player` must
be removed from both, and the loader must additionally *detect* it in order to refuse.
