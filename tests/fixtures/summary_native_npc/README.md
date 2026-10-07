# summary_native_npc fixture (spec 032)

A tiny campaign for the NPC-dossier tests: `docs/summaries/` (chapters 002-006, in the
031 format), `docs/entity_registry.yaml` and `config/config.yaml`. The tests copy it, then
build the 031 corpus with `summary_native build --since 2 --until 6` (see
`tests/conftest_npc.py` `npc_campaign`). Names are invented; the cases are what matter.

| Case | Where | What it exercises |
|---|---|---|
| NPC with entries and scene mentions | Jimjar: entries 002, 003, 006; scene mentions 002.01, 003.01, 004.01, 006.02 | evidence pack, ordering, `last_seen` |
| NPC mentioned in a chapter with no `## NPCs` entry | Jimjar in 004 (a scene and a moment, no entry) | mention-only chapter counts toward `chapters` |
| Moment (chapter-level, so outside any scene) | every `## Memorable Moments` block; multi-line (quote, attribution, context) in 002, 003, 004, 005 | moment-block boundary, `scene: none` |
| Possessive form | `Jimjar's` in 004.01 and in the 004 moment context | links through the apostrophe |
| First name that two entities own (ambiguous) | registry NPC Sarith Kzekarit has alias `Sarith`; ch 003 `## Locations` has a heading `Sarith` (a shrine). `Sarith` is used in 003.01, 004.02; `Sarith Kzekarit` in 006.01; registry NPC Sarith Vale is a second Sarith with no alias | the exact string `Sarith` belongs to an npc and a location: withheld, cannot be ruled; the full names still link. The registry refuses two entities sharing an alias, so a same-type clash cannot be seeded; a corpus heading is the only way a second owner arises |
| NPC named `Spider` (generic) | registry NPC `Spider`, entry in 003; `Spider` in 003.02, `Spider-silk` in 004.01 | generic single-token form withheld, rulable safe/never |
| Registry NPC with `scope: chapter-3` (local) | Kaelis (entry and moment in 003) | not global: `registry scope chapter-3: local` |
| Creature under `## NPCs` with no registry entry | Quaggoth (005) | `not in registry` exclusion |
| Name inside a longer word, and a lowercase occurrence | 005.01: `Jimjarr` and `jimjar` | neither links; ch 005 stays out of Jimjar's chapters |
| Registry `location` alias equal to an NPC heading | location Mantol-Derith has alias `Mantol`; NPC heading `Mantol` in 004 | cross-type ambiguity |
| Chapter with no `## Memorable Moments` | 006 | optional section absent |

## Seeded after the first cut

| Case | Where | What it exercises |
|---|---|---|
| Bold-paragraph moment with italic context | 002: `**Eldeth takes the rear.**` then `*She would not be argued with.*` | a `**` moment start; context attaches to it |
| Player character filed as an NPC | registry `Thorin` (alias `Thorin Giantfriend`), `### Thorin` in 005; `config/players.yaml` has `plays: [Thorin Giantfriend, Nobody Known]` | `exclusion: player character (players.yaml)`, still linked; `Nobody Known` resolves to nothing and is a report finding |

## Recorded `npc-link` result (quickstart S1, T018)

`summary_native npc-link --since 2 --until 6` on this fixture (no `canon.yaml`):

- 9 NPCs linked (every NPC corpus dossier, global or not), 9 scenes, 5 moments.
- Withheld: 2 ambiguous (`Sarith`, `Mantol`), 1 generic unruled (`Spider`). stderr:
  `warning: 2 ambiguous, 1 generic (unruled) name forms withheld from linking — see docs/npcs/summary_native/ch002-006/link_report.md`

| NPC (stem) | global / exclusion | entries | scenes | moments | chapters |
|---|---|---:|---:|---:|---|
| Jimjar (`npc_jimjar`) | global | 3 | 4 | 2 | 2, 3, 4, 6 |
| Eldeth Feldrun (`npc_eldeth_feldrun`) | global | 3 | 3 | 2 | 2, 5, 6 |
| Sarith Kzekarit (`npc_sarith_kzekarit`) | global | 1 | 1 | 0 | 2, 6 |
| Sarith Vale (`npc_sarith_vale`) | global | 1 | 0 | 0 | 3 |
| Spider (`npc_spider`) | global | 1 | 0 | 0 | 3 |
| Thorin (`npc_thorin`) | `player character (players.yaml)` | 1 | 0 | 0 | 5 |
| Kaelis (`npc_kaelis`) | `registry scope chapter-3: local` | 1 | 1 | 1 | 3 |
| Mantol (`npc_mantol`) | `not in registry` | 1 | 0 | 0 | 4 |
| Quaggoth (`npc_quaggoth`) | `not in registry` | 1 | 0 | 0 | 5 |

Notes: Jimjar's chapter 4 is mention-only (no entry); Sarith Kzekarit's `last_seen` is 6 on the
strength of a scene alone. Chapter 5 stays out of Jimjar's chapters (`Jimjarr`, `jimjar`).
With `{form: Spider, ruling: safe}` Spider links 2 scenes (003.02 and 004.01, through `Spider-silk`)
and the generic warning disappears; with `never` the form stays withheld, listed in the report.
`Sarith` occurs at 003.01, 003 `## Locations` heading, and 004.02; the 006.01 mention of
`Sarith Kzekarit` is not an occurrence of the bare form.
