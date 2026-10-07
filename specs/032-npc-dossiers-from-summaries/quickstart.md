# Quickstart: Validating Summary-Native NPC Dossiers (032)

These are runnable validation scenarios, one per user story. Flags are in `contracts/cli.md`, files in `contracts/files.md`, entities in `data-model.md`.

## Prerequisites

- The package is editable-installed into the server venv: `uv pip install -e . --python "$VIRTUAL_ENV/bin/python"`.
- The OOTA workspace `~/out-of-the-abyss/out-of-the-abyss` has `docs/summaries/` (067-file corpus, with 070's title fixed per 031) and `docs/entity_registry.yaml`.
- The 031 corpus is built: `summary_native build --since 2 --until 70` (run from the campaign root).

```bash
cd ~/out-of-the-abyss/out-of-the-abyss
R=docs/npcs/summary_native/ch002-070
```

## S1 — Linking is complete, ordered and deterministic (US1)

```bash
summary_native npc-link --since 2 --until 70
grep -E '^(n_entries|n_scenes|n_moments|first_seen|last_seen):' $R/evidence/npc_jimjar.md
summary_native npc-link --since 2 --until 70 --force && git diff --no-index --stat <(cat $R/evidence/*.md) <(cat $R/evidence/*.md)
```

Expected:
- Jimjar's counts match SC-001 (33 / 71 / 43), less any withheld form listed in `link_report.md`.
- Ilvara's `chapters` lists 10 chapters (SC-002).
- A second run with `--force` leaves `evidence/`, `link_report.*` and `link_manifest.json` byte-identical. Check with `sha256sum` before and after.
- If any form is withheld, stderr shows the run-end warning.

**Seeded fixture check** (`tests/fixtures/summary_native_npc/`):
- An ambiguous shared first name is withheld and appears in the report.
- `Spider` is generic and withheld until `canon.yaml` has `{form: Spider, ruling: safe}`.
- A ruling on the ambiguous form makes `npc-link` exit 2, naming the collision.

## S2 — Draft a few global NPCs (US2)

```bash
summary_native npc-draft --since 2 --until 70 --name Jimjar Ilvara --dump-only   # inspect prompts first
ls $R/runs/*/                                # selection.json, record.json, npc_*.user.md
summary_native npc-draft --since 2 --until 70 --name Jimjar Ilvara --backend anthropic
```

Expected:
- `draft/npc_jimjar.md` has every outline section, and the computed header equals the evidence frontmatter facts.
- Every History bullet ends with a citation.
- `selection.json` lists included NPCs and excluded ones with reasons.
- `git status docs/npcs/distilled docs/summary_native` shows no changes (SC-005).
- `--name "Aquatic Troll"` refuses with `not in registry`.
- Moving `entity_registry.yaml` aside makes drafting refuse and name `registry init`.

## S3 — Verification catches drift (US3)

```bash
cp $R/draft/npc_jimjar.md /tmp/j.bak
sed -i '0,/\[ch 004 \/ 004.02\]/s//[ch 004 \/ 004.99]/' $R/draft/npc_jimjar.md   # invalid scene
# change one word inside a Notable Quotes line by hand
summary_native npc-verify --since 2 --until 70 --name Jimjar; echo "exit $?"
cp /tmp/j.bak $R/draft/npc_jimjar.md
```

Expected:
- Exit 5.
- `npc_jimjar.verify.md` lists the invalid citation and the not-verbatim quote, with draft lines.
- Restored, the draft passes with exit 0.
- **Spark A/B:** copy the Claude draft aside, re-draft the same NPC with `--backend dgx --force`, and verify both. Both get a verify report of the same shape, which makes their citation and quote fidelity directly comparable.

## S4 — Incremental re-draft (US4)

```bash
summary_native npc-draft --since 2 --until 70 --name Jimjar Ilvara     # both: skipped (unchanged)
# edit one summary line in a scene that names Ilvara only, then:
summary_native build --since 2 --until 70 --force && summary_native npc-link --since 2 --until 70 --force
summary_native npc-draft --since 2 --until 70 --name Jimjar Ilvara     # Ilvara drafted, Jimjar skipped
```

## S5 — Manual edits are synthesised in the draft; Secrets reach only the GM dossier

```bash
summary_native npc-compose --since 2 --until 70 --init Jimjar
$EDITOR docs/npcs/authored/jimjar.authored.yaml
#   manual: ["Jimjar is a deep gnome, not a drow.", "He has a standing bet with Eldeth."]
#   secrets: "SECRET-CANARY-7731 owes a Blingdenstone fence"
summary_native npc-draft --since 2 --until 70 --name Jimjar
grep -c 'SECRET-CANARY-7731' $R/draft/npc_jimjar.md $R/runs/*/npc_jimjar.*.md   # all 0
grep -c 'SECRET-CANARY-7731' $R/gm/npc_jimjar.md                                    # 1
grep -o '\[manual [0-9]\]' $R/draft/npc_jimjar.md | sort -u                     # [manual 1] [manual 2]
```

Expected:
- The draft dossier calls Jimjar a deep gnome, cites `[manual 1]`, and does not repeat "drow" as fact.
- `npc_jimjar.verify.md` lists both manual edits as `cited`, each beside its cited passage.
- **Dropped-edit check:** delete every `[manual 2]` from the draft dossier by hand and run `npc-verify --name Jimjar`. Expect exit 5 and `manual edit 2 dropped`, with its text. Restore the file afterwards.
- **Secrets-only edit:** change only `secrets` and run `npc-draft --name Jimjar`. Expect `skipped (unchanged)`, the new secret in `gm/npc_jimjar.md`, and no model call. Change a `manual` item instead and expect `drafted`.
- Hand-editing `gm/npc_jimjar.md` and running `npc-compose --name Jimjar` prints the "unrecorded hand-edit" warning.
- The authored file is byte-identical before and after every command above.

## S6 — Migration (FR-022a–d)

On copies of toee (101 dossiers from bundled commits) and stormgiants (all marked, plus `merged_sidecars/`):

```bash
git -C ~/src/campaigns worktree add /tmp/campaigns-mig HEAD      # a disposable copy that keeps git history
C=/tmp/campaigns-mig/toee
python -m server.migrate_npc_dossiers --campaign-dir $C --propose
less $C/docs/npcs/migration_classification.yaml                  # unknown entries carry their git evidence
python -m server.migrate_npc_dossiers --campaign-dir $C --apply   # refuses: unknown entries remain
$EDITOR $C/docs/npcs/migration_classification.yaml                # set each unknown to distilled | authored
python -m server.migrate_npc_dossiers --campaign-dir $C --apply
ls $C/docs/npcs                                                   # authored/ distilled/ migration_classification.yaml — no loose .md
python -m server.migrate_npc_dossiers --campaign-dir $C --propose # "nothing to classify"
grep dossier_dir $C/config/grounding.yaml                         # docs/npcs/distilled/
```

Expected:
- For stormgiants, the proposal marks every entry `distilled` from the marker, and `--apply` needs no edits.
- Every moved file is byte-identical at its new path.
- Editing a dossier between `--propose` and `--apply` makes `--apply` refuse.
- Against an unmigrated copy, `registry check` and `planning --build-dossiers` refuse with the migration commands.
- With `dossier_dir` hand-set to `docs/npcs/`, the same tools refuse (wrong directory) rather than reading published dossiers as distilled ones.

## S8 — Publish to `docs/npcs/` (US6)

```bash
summary_native npc-publish --since 2 --until 70                         # refuses: no selection
summary_native npc-publish --since 2 --until 70 --name Jimjar
head -1 docs/npcs/jimjar.md                                             # published by … source: summary_native … verify: pass
grep -c '\[manual [0-9]' docs/npcs/jimjar.md                            # 0 — rewritten to [GM]
grep -c 'SECRET-CANARY-7731' docs/npcs/jimjar.md                        # 1 — GM dossier, Secrets included
echo "edit" >> docs/npcs/jimjar.md && summary_native npc-publish --since 2 --until 70 --name Jimjar   # refuses: hand-edited
summary_native npc-publish --since 2 --until 70 --authored-all          # hand-built NPCs, verbatim, header says hand-built
```

Then, from a campaign session, ask `gm-npc-voice` to voice Jimjar and confirm it reads `docs/npcs/jimjar.md`.

## S7 — UI parity (US5)

1. Start the server with `./startup` and open **NPCs → Dossiers**.
2. Choose the summaries and range 2–70, then run Link. The warning badge matches stderr.
3. Choose "Named: Jimjar", then run Draft.
4. Run Verify, then Compose.
5. Confirm the files are identical to the CLI runs above, and that the server log shows the exact argv.
6. Confirm Draft is disabled until a selection mode is chosen, and that Publish needs explicit NPC names or an explicit "all".
7. Confirm the Grounding → Summary-native page shows no NPC stages.

## Test suite

```bash
python -m pytest tests/ -k "summary_native or npc_dossier or migrate_npc or no_loose_dossier"
cd frontend && npx playwright test e2e/sidebar-navigation.spec.ts
```

## Validation

Re-derived with this feature's linker (`summary_native build --since 2 --until 70`, then
`npc-link --since 2 --until 70`) on a copy of the OOTA campaign (`docs/summaries`,
`docs/entity_registry.yaml`, `config/` including `players.yaml`, `docs/summary_native/canon.yaml`);
the live campaign was not written to. These numbers are now the SC-001 goldens (GM ruling 2026-10-06), replacing the proposal's
scratch figures, which are kept in the last column for the record.

Moment boundaries follow the GM ruling in research R3 (a moment starts at a paragraph opening with
`>`, `**` or `- `; any other paragraph attaches to the moment before it).

Run totals: 222 NPCs linked, 1619 scenes, 1045 moments linked. Withheld: 8 ambiguous, 11 generic (unruled).
Run-end warning: `warning: 8 ambiguous, 11 generic (unruled) name forms withheld from linking`.

Moment items in range, by opening shape: 1242 in all: 896 `>` quote, 309 `**` bold, 37 `- ` list items,
0 orphan paragraphs. (The 37 are list lines: each `- ` line is its own moment, where the ruling's
"20 list items" counts paragraphs.)

| NPC | entries | scenes | moments | SC-001 scratch (entries / scenes / moments) |
|---|---:|---:|---:|---|
| Jimjar | 33 | 71 | 43 | 33 / 71 / 17 |
| Glabbagool | 30 | 94 | 48 | 30 / 94 / 21 |
| Eldeth Feldrun | 24 | 36 | 8 | 24 / 36 / 6 |
| Stool | 16 | 0 (withheld, generic) | 0 | 16 / 29 / 9 |
| Sarith Kzekarit | 13 | 33 | 15 | 13 / 33 / 12 |
| Buppido | 12 | 32 | 28 | 12 / 32 / 16 |
| Ilvara Mizzrym | 6 | 26 | 14 | 6 / 26 / 5 |
| Jorlan Duskryn | 4 | 10 | 4 | 4 / 10 / 2 |

- Entries and scenes match the scratch counts for every NPC. Stool is withheld, as SC-001 predicts.
- **Moments are higher than the scratch counts for seven of eight NPCs** and the gap widened with the
  corrected boundaries (Jimjar 43 vs 17), because bold and list moments now count and each item is
  matched whole, context paragraph included. The scratch script is not available, so how it counted
  is unknown; nothing was adjusted to match. The GM accepted the linker's counts as SC-001 (2026-10-06).
- SC-002: Ilvara's chapters are `[2, 3, 31, 32, 49, 50, 51, 52, 53, 54]`, ten chapters. Jimjar spans 39 chapters.
- Player characters: `npc_thorin` reads `global: false`, `exclusion: player character (players.yaml)`
  (`Thorin Giantfriend` resolves to registry `Thorin` by alias), and is still linked (2 entries, 282 scenes,
  261 moments). Every `plays` name in OOTA's `players.yaml` resolves; none is reported unresolved.
- Withheld ambiguous forms: Bahamut (deity), Clan Ironhead, Clan Thrazgad, Council of Savants, Gray Ghosts
  (factions), Dawnbringer (item, 236 occurrences; to be fixed in campaign data), Entemoch, Ogremoch (deities).
- Withheld generic forms: Gargoyle, Irony, Nibbles, Rust, Sergeant, Skeletons, Spanner, Spectator, Specters, Sprig, Stool (122 occurrences).
- `mention-without-heading` lists 19 registry NPCs named in scenes or moments that have no `## NPCs` heading,
  including the player characters Daz, Gyrgum and Zalthir, and a registry NPC named `Y`.

### Chunked Spark, pipeline (T063, 2026-10-06)

Default flags (`dgx`, `qwen3.8-flash-next`, `chunked`, 60000) on the OOTA copy; the endpoint had to be passed with `--endpoint` because neither `DGX_ENDPOINT` nor wiring `dgx_endpoint` is set. Quotes may come from any evidence item (GM ruling), so counts exceed the moments-only prototype.

| NPC | Chunks | Spark time | Citations valid/total | Notable Quotes (moment / scene / entry) | Map drops | npc-verify |
|---|---|---|---|---|---|---|
| Jimjar | 6 | 300 s | 271 / 271 | 67 (32 / 35 / 0) | 1 uncited History bullet | fail: not-found 7 |
| Ilvara Mizzrym | 3 | 135 s | 150 / 150 | 14 (7 / 7 / 0) | 1 quote not-found | fail: not-found 4 |
| Eldeth Feldrun | 3 | 153 s | 149 / 150 | 14 (3 / 9 / 2) | 1 History, 1 quote (invalid citation) | fail: invalid 1, not-found 9; 2 status advisories |

Every Notable Quote passed. Every `not-found` is a `"…"` span inside a History bullet, an Arc-Score candidate or a reduce section: paraphrases presented as quotes, nested single quotes, punctuation moved inside the quote. The map check (R17) does not check those spans; verify (R10) does. Open for the GM.

### SC-005a — migration before/after (T057, 2026-10-06)

Fresh clones of `~/src/campaigns`. "Before" ran main's code on the unmigrated campaign; "after" ran this branch's code after `--propose`/`--apply`. All three outputs are model-free (`planning --dump-input … --dump-only` stopped before the API call with no keys set).

| Campaign | Classification | registry check | alias map (as CLIs call it / scan only) | planning prompt | moved files byte-identical |
|---|---|---|---|---|---|
| stormgiants | 268 distilled (all marked) | identical (vacuous: no registry) | identical 266 / 266 | identical | yes (271 files) |
| toee (i) SYNTHETIC: 101 unknown → distilled | 1 + 101 distilled | identical | identical 918 / 101 | identical | yes (102) |
| toee (ii) SYNTHETIC: 101 unknown → authored | 1 distilled, 101 authored | differs: 11 "MISSING" grouping-drift findings disappear (42 → 31) | identical 918 / 0 | not comparable: no distilled dossiers left as planning input | yes (102) |

Result: **pass** where the classification preserves what the readers see. Variant (ii) shows the real consequence of classifying a dossier `authored`: it leaves the distilled readers (`registry check`'s frontmatter drift, the scan-only alias map, `planning`'s synthesis input). That is the expected effect of the layout, and it is a decision for the GM when classifying toee's 101 unmarked files for real.

### S4 / S5 / S8 on the OOTA copy (T057, 2026-10-07)

Real CLI, Spark default, Ilvara Mizzrym and Eldeth Feldrun, npc root `docs/npcs/summary_native_e2e`.

- **S4 pass.** First draft 4m14s (3 map calls + reduce each). Identical re-run: both `skipped (unchanged)`, 1.8 s, no model calls. `--force`: both re-drafted.
- **S5 pass.** `--init` created `authored/eldeth-feldrun.authored.yaml`. Two manual edits → re-drafted; `[manual 1]` cited twice, `[manual 2]` once. The Secrets canary appears only in `gm/npc_eldeth_feldrun.md`, never in `draft/` or `runs/`. A Secrets-only change: `skipped (unchanged)`, no model call, `gm/` updated.
- **S8 pass.** No selection → exit 2. Failed verify → refused; `--force` → `verify: fail(forced)`. Published file: 0 `[manual N]`, 3 `[GM]`, 86 chapter citations kept, Secrets last. Hand-edit → refused naming the authored file; `--force` overwrites. `publish_log.json` under the chosen npc root. `authored/` byte-identical except the YAML written by hand.
- **Observed:** the verify verdict varies between drafts of the same NPC (fail → pass on `--force` → fail after manual edits; all failures are `not-found` spans in reduce prose), and `npc-draft` exits 0 regardless — gate on `npc-verify`. On a draft that fails verify, the verify refusal is reported before the hand-edit refusal.
- **S7 (UI)** was exercised by the route tests and the sidebar e2e, not against a live server: the console script is not reinstalled into the server venv until after merge (T058).
