# Migration: `docs/npcs/` layout (spec 032, Constitution XIII)

Operator instructions with the full workflow are in `docs/cli/npc_dossiers_migration.md`.
This file is the feature's migration record.

## What changed shape

`docs/npcs/` used to hold the distilled pipeline's dossiers loose (`<name>.md`, `.new_notes.*`
sidecars, `.dedup_state.json`, `merged_sidecars/`). It now holds only **published** dossiers
(`<slug>.md` written by `npc-publish`, each with a `<!-- published by summary_native npc-publish`
header). Everything else moves into a subdirectory:

| Path | Holds |
|---|---|
| `docs/npcs/<slug>.md` | published dossiers (what the gm-assistant skills read) |
| `docs/npcs/distilled/` | the retired distilled pipeline's dossiers, sidecars and state |
| `docs/npcs/authored/` | everything a person made: hand-built dossiers, `<slug>.authored.yaml` |
| `docs/npcs/summary_native/` | this feature's generated output |

Config values that named the old location change with it:
`grounding.yaml` `planning.dossiers.dossier_dir` (`docs/npcs/` becomes `docs/npcs/distilled/`,
also the new default) and `planning.yaml` `npcs[].dossier` (`docs/npcs/x.md` becomes
`docs/npcs/distilled/x.md` or `docs/npcs/authored/x.md`).

## Affected workspaces

| Workspace | State today | Needs |
|---|---|---|
| `toee` | 101 loose `.md` + `.dedup_state.json`, no `source_extracts:` marker on the dossiers, 18 changed since added | `--propose`, GM classification of every `unknown`, `--apply` |
| `stormgiants` | 266 `.md` (all marked) + `merged_sidecars/` + `.dedup_state.json` | `--propose`, `--apply` (no edits needed) |
| `Phandalin`, `obelisk` | no files; `grounding.yaml` still says `dossier_dir: docs/npcs/` (Phandalin's `planning.yaml` also names `docs/npcs/*.md`) | `--apply` (config only) |
| `out-of-the-abyss` | no files; commented examples only | `--apply` is optional |

## Exact commands

```bash
python -m server.migrate_npc_dossiers --campaign-dir DIR --propose
$EDITOR DIR/docs/npcs/migration_classification.yaml     # set each `unknown` to distilled | authored
python -m server.migrate_npc_dossiers --campaign-dir DIR --apply
summary_native npc-publish --authored-all                # republish the hand-built NPCs
```

`--force` (with `--apply` only) replaces same-named files already in `distilled/` or `authored/`.

## A workspace that never migrates

Nothing is moved for it and nothing guesses. Every reader of distilled dossiers refuses, with the
migration command in the message, while `docs/npcs/` directly holds a `.md` that lacks the publish
header: `load_alias_map` (so `distill`, `party`, `campaign_state`, `scene_extract`, `sd_narrate`,
`planning`), `planning --build-dossiers`, `registry check`/`resolve`, the Session Config path
discovery and the Connections graph routes (HTTP 409, so those pages fail until the migration is run). A reader pointed at `docs/npcs/` itself is refused too, since that directory now holds
published dossiers and reading them as distilled ones would feed generated output back into identity.
A campaign with no loose files (nothing in `docs/npcs/`, or only published files) is never refused.

## How to verify

Quickstart S6. In short: after `--apply`, `ls DIR/docs/npcs` shows `authored/ distilled/
migration_classification.yaml` and no loose `.md`; every moved file is byte-identical; `--propose`
prints `nothing to classify`; `grep dossier_dir DIR/config/grounding.yaml` shows `docs/npcs/distilled/`.
SC-005a: the alias map read from `distilled/`, `registry check`, and `planning --dump-input FILE
--dump-only` give the same results as before.
