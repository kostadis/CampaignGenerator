# prep_B — sources

Condition B: the campaign docs as they stood before 2026-10-07, with the world_state taken from the install backup.

## Files read

Read in full:
- `/home/kostadis/out-of-the-abyss/gm-assistant/skills/gm-session-prep/SKILL.md`
- `/home/kostadis/out-of-the-abyss/out-of-the-abyss/docs/campaign_state.md` (707 lines)
- `/home/kostadis/src/CampaignGenerator/.claude/worktrees/exp-chunked-state-docs/experiments/20261007-chunked-state-docs/install_backup/20261007T163036Z/world_state.md` (337 lines). Cited below as **WS**.
- `/home/kostadis/out-of-the-abyss/out-of-the-abyss/docs/party.md` (255 lines). Cited as **PARTY**.
- `/home/kostadis/out-of-the-abyss/out-of-the-abyss/docs/summaries/070-session-untitled.md`. Most recent. Cited as **S70**.
- `/home/kostadis/out-of-the-abyss/out-of-the-abyss/docs/summaries/069-session-one-manshoon-dead-at-least-one-or-two-more-to-go.md`. Cited as **S69**.

`campaign_state.md` is cited as **CS**.

Read selectively from `docs/background/`:
- `candlekeep_murders_module_inventory.md`: lines 1–120 and 190–285. Cited as **INV**.
- `1073077-Candlekeep_Murders_-_192_Res_-_26th_Dec.json`. This is the module text. I flattened it to a scratch text file and read these sections:
  - Ch4 "Enter Manshoon!" and "Players vs. Manshoon", including Potential Encounters and the simulacrum stat block.
  - Ch5 B2 The Vault, B3 Side Vault, B4 The Attic and its Rocket Alternative sidebar, Returning to the Surface, Final Confrontation, Restoring Calm to Candlekeep, and Adventure Rewards.
  - The "Echoes of Alaundo" sidebar (House of Alaundo).
  - The Kei Tigersteel mentions, found by grep.

  Cited as **MOD** with the section name.
- `post_oota_vhaerun_arc.md`: first 30 lines only. I judged it not relevant to this beat and did not use it.
- I grepped `Out of the Abyss.md` and `out-of-the-abyss-inventory.md` for "vile darkness", "candlekeep" and "manshoon". The grep found nothing relevant to this beat, and I used nothing from either file.

Not read, as instructed: `docs/world_state.md`, `docs/npcs/`, `docs/reference/`, `docs/canon_events_timeline.md`, `docs/summary_native/`, and any other campaign.

## Where each status came from

### PCs and level
| Entity | Status used | Source |
|---|---|---|
| Party level 9 | Level 9 since Ch63 | WS l.23; CS l.402; PARTY l.9 |
| Zalthir / Thorin / Gyrgum / Daz: class, level, player | Monk 9 Shadow (Gabe), Fighter 9 Battle Master (Joe Beda), Cleric 9 Life (Ben Pfaff), Wizard 9 Evoker (Mike Hall) | PARTY l.76, 114, 154, 198 |
| Daz alignment CN | Chaotic neutral | PARTY l.200; S70 l.172 |
| Daz attuned items (conflict) | WS says Ring of Protection and spectacles are attuned. PARTY says the Stonespeaker Crystal and Dustsight Spectacles are attuned and the Ring is not on the sheet | WS l.92; PARTY l.223 |
| Robe of the Archmagi | Worn by Daz; attunement pending a long rest | S70 l.9, 335–339; WS l.93 |
| Thorin's candor | Radical transparency; "be my faction" | WS l.34; PARTY l.120 |

### Companions and items
| Entity | Status used | Source |
|---|---|---|
| Glabbagool | Climbed the tower with the party in Ch69. Not mentioned in Ch70. Carries key #2, the Potion of Flying and Fembris's notes | S69 l.120; WS l.108; PARTY l.50 |
| Dawnbringer | Sentient, female, Netherese sunblade. Anxious in the dark. Can speak in Thorin's mind and impose her will. Cannot be dimmed | WS l.191 |
| Book of Vile Darkness | Sentient. Written or purportedly written by Vecna. Cannot be destroyed while evil exists. Under an ash illusion. Offered Daz demons or self; he chose demons. Its content was explicitly left unresolved | S70 l.147–190 (l.188: "left to be resolved when the party reconvenes"); WS l.192 |
| Book: module details | Darkness emanates from it. DC 18 Cha save or 8d6 necrotic on touch for good characters, with advantage for neutral ones. The module defers to the DMG artifact entry | MOD Ch5 B3 and the "Turn Up the Vileness" sidebar |
| Prophecy crystals (Echoes) | 10 total: 4 played, 6 unplayed. 2 smashed by Edvaldo. Gyrgum holds 4 | S69 l.142; S70 l.299, 347–351; WS l.193; CS l.652 |
| Echoes: who can coax them | Only the First Reader and the Keeper, per the module | MOD "Echoes of Alaundo" sidebar |
| Forge prophecy played unprompted | A disembodied voice spoke it in Ch69 | S69 l.103, 117 |
| Warded tomes | Hundreds of glyphs. B2 tomes cast *suggestion* (DC 17) on anyone carrying one more than 30 ft away | S69 l.147; WS l.166; MOD Ch5 B2 |
| Vault desk note | Consult but do not remove. The means to destroy the vault are above | WS l.166 (confirms the note is known); MOD Ch5 B2 (verbatim text) |
| Attic self-destruct; lava won't destroy the book | — | MOD Ch5 B4 and the Rocket Alternative sidebar |
| Modron tools / Spanner debt | Must be returned; Zalthir and Glabbagool owe Spanner a study | WS l.57, 196, 260; CS l.367–370 |
| Staff of Power | Used in the breach; recovery not recorded | S70 l.341–345; WS l.182 |

### NPCs
| Entity | Status used | Source |
|---|---|---|
| Edvaldo ("Sedanur") | A doppelganger serving Manshoon. Fled in halfling form toward the anti-magic barrier and is frightened of Thorin | S70 l.37, 142–145, 289–295; WS l.20, 140; CS l.351 |
| Edvaldo's rough answer on the tower's height | — | S69 l.86, 316 |
| Manshoon (real) | Alive and at large; vengeance promised | S70 l.39, 78; WS l.21, 183; CS l.352 |
| Manshoon's simulacra #1 and #2 | Destroyed in Ch69 and Ch70 | S69 l.52–62; S70 l.41; WS l.179–180 |
| Doppelganger and sending stone; Fembris as the doppelganger's target; the exit ambush | — | MOD Ch4 Potential Encounters; MOD Ch5 Final Confrontation |
| Manshoon's raiders wear a black "M" | — | MOD Ch4 "Enter Manshoon!" |
| Avowed Readers arriving | Minutes away, pleased the vault was found, will not let artifacts walk | S70 l.155, 189–190, 313 |
| Kalan Strongbranch | Gatewarden and reinstated Head of the Avowed. Fled in Ch65 and reappeared in Ch67 | WS l.135; CS l.335 |
| Kalan as a "Keeper of Secrets" | The Keeper of Tomes and the Gatewarden are the two Keepers of Secrets | INV l.256 |
| Teles Ahvoste / Fheminor | Tipped as the next Head of the Avowed | WS l.146; CS l.346 |
| Teles: archmage who makes a play for Keeper. Fheminor: no fighter, wants the Keeper's will honoured | — | MOD Ch4 Players vs. Manshoon; MOD Ch5 Restoring Calm; INV l.26–27 |
| Daral Yashenti | Cured by Dawnbringer and grateful; founding a field on sentient swords | WS l.138; CS l.338 |
| Kazryn Nyantani | Named as a suspect by Sylvira | WS l.146; CS l.347 |
| Kazryn: frail, A'lai's lover | — | INV l.28; MOD Ch4 |
| Tadric | Alive and escorting A'lai to the prison | WS l.136; CS l.336 |
| Tadric: monks are not soldiers | — | MOD Ch4 |
| Fembris Lancer | The party's minder; talks too much | WS l.139; CS l.339 |
| Kei Tigersteel | Appears only in the module (Lorekeeper, *zone of truth*). Not in any table doc I read | MOD Ch2 Chapter House scenes; MOD Ch5 Restoring Calm; INV l.30 |
| Miirym | Witness, not weapon. Her 10-minute boon was 6 minutes gone at the start of Ch70 | S70 l.35, 319; WS l.18, 162; CS l.349 |
| Miirym: summonable only by a legitimate Keeper of Tomes | — | MOD Ch4 Players vs. Manshoon |
| Iron Owlbear guardian | Active and neutral. Asks three questions (answers: the Hearth, the triumvirate, the High Tower's height). A previous owlbear lies broken | WS l.165; CS l.350, 626; S69 l.65–67 |
| Iron Owlbear conflict | Ch70 calls the debris "the dead owlbear's remains" | S70 l.41, 82, 93 |
| Sylvira | Bedridden and does not know about Moziqodo; was impersonated on the night of the murder | WS l.137; CS l.337 |
| A'lai | Imprisoned and cooperating | WS l.133; CS l.333 |
| Alkrist | Disgraced | WS l.132; CS l.332 |
| Candlekeep's state | 4 of 9 leading Readers gone; wards broken; Chant silent | WS l.121–124; S70 l.311 |

### Threads used as offstage noise or candidate book content
| Thread | Source |
|---|---|
| Zuggtmoy's wedding to Araumycos | WS l.208, 278; CS l.384 |
| Demogorgon's whereabouts | WS l.207, 279 |
| Narrak's dying words | WS l.281; CS l.79 |
| Madness on the surface; the "kraken under the keep" preacher | WS l.214–217, 280 |
| Daz'issin and the sealed drow house record | WS l.100, 269; PARTY l.214 |
| Dust of Mechanus ruling still open | WS l.171 |

### Module exit route (no table confirmation)
| Item | Source |
|---|---|
| Second bridge, reverse-gravity shaft, one-way *wall of force*, anti-flight wards underground | MOD Ch5 Returning to the Surface |

### Rules notes (not from any campaign doc)
- *Minor Illusion* lasts 1 minute.
- A doppelganger's shapechange is not a spell, so an anti-magic field does not suppress it.

Both are marked `[OVERLAY]` in the prep as my rules reading.
