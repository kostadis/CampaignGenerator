# Migrating `docs/npcs/` (spec 032)

`docs/npcs/` now holds only published NPC dossiers. The distilled pipeline's files move to
`docs/npcs/distilled/`, anything a person wrote moves to `docs/npcs/authored/`. You run the
migration once per campaign, deliberately. Nothing moves as a side effect of running a pipeline.
The feature's migration record is `specs/032-npc-dossiers-from-summaries/migration.md`.

## The workflow

```bash
python -m server.migrate_npc_dossiers --campaign-dir ~/src/campaigns/toee --propose
```

Writes `docs/npcs/migration_classification.yaml` and moves nothing. Every entry directly in
`docs/npcs/` gets a `disposition` and an `evidence` block:

- `distilled`: the file has the `source_extracts:` frontmatter marker, or it is a distilled
  sidecar or state file (`*.new_notes.*`, `.dedup_state.json`, `.sidecar_merge_state.json`,
  `merged_sidecars/`).
- `unknown`: everything else. **This is deliberate.** Git history is shown (the adding commit,
  later commits, `changed_since_added`) but never decides: commit messages such as
  "session outputs, dossier cleanup" bundle generated and hand-made files, so the wording cannot
  tell them apart. A hand-made dossier from `gm-npc-build` has no marker, so it lands here.
- `flags: [hand-edited]` marks a `distilled` entry that changed after it was added. The move is
  byte-identical, so the edit is kept.
- Outside a git repository, `evidence.git` reads `unavailable`.

Open the file and set each `unknown` to `distilled` or `authored`. Re-running `--propose` keeps
the dispositions you set for files that have not changed.

```bash
python -m server.migrate_npc_dossiers --campaign-dir ~/src/campaigns/toee --apply
```

Refuses (exit 1, nothing moved) while any entry is `unknown`; when a file was added, removed or
edited since `--propose` (re-propose); or when a target already exists (add `--force` to replace
files, never directories). It moves entries with `os.replace`, then rewrites two config values in
place, keeping comments:

- `config/grounding.yaml` `planning.dossiers.dossier_dir`: exactly `docs/npcs/` becomes
  `docs/npcs/distilled/`.
- `config/planning.yaml` `npcs[].dossier`: `docs/npcs/x.md` becomes `docs/npcs/distilled/x.md` or
  `docs/npcs/authored/x.md`, following that file's disposition.

Any other value (an absolute path, a path outside `docs/npcs/`, a published file) is reported, not
changed. A campaign with no loose files can run `--apply` just for the config rewrite. A move that
fails part way stops and lists what moved; fix the cause and run `--apply` again to resume.

`--propose` on a migrated campaign prints `nothing to classify`. The classification file stays as
the record.

## After `--apply`: republish the hand-built NPCs

`docs/npcs/` holds no loose dossiers now, so the gm-assistant skills see no NPCs. Republish the ones
you classified as `authored`:

```bash
summary_native npc-publish --authored-all
```

Each is copied verbatim to `docs/npcs/<slug>.md` under a header that marks it hand-built.

## What it reports but does not edit

- `~/src/campaigns/provenance.yaml`: globs over `docs/npcs/*.md` (the lines are printed). Update them
  by hand; `distilled/` and `authored/` are not covered by a `docs/npcs/*.md` glob.
- `gm-npc-build` writes straight into `docs/npcs/`; point it at `docs/npcs/authored/`
  (kostadis/campaigns#370).
- `/dossier-merge`, `vtt-spell-pass` and `consistency-check` read distilled dossiers under
  `docs/npcs/`; point them at `docs/npcs/distilled/`.

## If you never migrate

Readers refuse and say how to migrate: `distill`, `party`, `campaign_state`, `scene_extract`,
`sd_narrate`, `planning` (including `--build-dossiers`), `registry check` and `registry resolve`,
the Session Config path discovery, and the Connections graph routes (`/extract` and `/context`). Those two HTTP surfaces answer **409 Conflict** with the same message, so on an unmigrated campaign the Session Config prefill and the Connections graph fail until the migration is run. That is expected. A reader pointed at `docs/npcs/` itself is
refused as well ("wrong directory"). A campaign whose `docs/npcs/` holds only published files, or
does not exist, is not refused: it simply has no distilled dossiers.

## Search tools will see more

The recursive search tools (`connections` list-docs and context, the rlm MCP `grep_campaign` and
`list_files`) are not identity sources, so they still walk `docs/npcs/` recursively. They will find
authored files, GM dossiers and published dossiers, including **Secrets**. That is acceptable for
GM-only tools; do not point a player-facing tool at them.

## Verify

```bash
ls DIR/docs/npcs                                   # authored/ distilled/ migration_classification.yaml (+ published files)
python -m server.migrate_npc_dossiers --campaign-dir DIR --propose    # nothing to classify
grep dossier_dir DIR/config/grounding.yaml         # docs/npcs/distilled/
registry check DIR                                 # runs, no refusal
```

Quickstart S6 has the full check, including that an unmigrated copy makes `registry check` and
`planning --build-dossiers` refuse, and that a hand-set `dossier_dir: docs/npcs/` is refused.
