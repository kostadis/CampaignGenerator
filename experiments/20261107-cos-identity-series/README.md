# Who is who in Curse of the Hags: masked-name and unnamed-identity experiments

Experiment record, 2026-11-07. This applies the method of the 2026-11-03/04 provenance-identity series
([20261104-provenance-identity-series](../20261104-provenance-identity-series/README.md), especially
[20261103-summary-entity-resolution](../20261103-summary-entity-resolution/README.md)) to a real campaign
problem: the Curse of Strahd campaign "Curse of the Hags" in the `kostadis/campaigns` workspace.
Unlike the orc/ogre trial, the expectations here are **GM rulings**, not researcher drafts, and the
outputs were taken through a GM review gate and applied.

Code: [aasimar](../20261107-aasimar-control-resolution/) and [unnamed](../20261107-unnamed-identity/)
(`prepare.py`, `run_models.py`, `evaluate.py`, `FINDINGS.md`). Private text, prompts and raw responses are in each
directory's git-ignored `private-runtime/`.

## Questions

1. **Marron/Merrin.** One aasimar PC has two personalities, Marron (Paladin) and Merrin (Cleric). The GM's rule:
   each mention names the personality *in control*. An earlier pass had read the names with the names visible.
   Can a model decide who is in control from context alone, with the names hidden, and does that find errors?
2. **Unnamed people.** 65 chapter questions ask whether an unnamed person (the corpulent man, the rogue, an
   untagged line) is a known character. Can a model propose identities a GM will accept?

## Method

Shared with the 2026-11-03 series: exact targets are frozen before any call; expectations are kept apart and never
sent; every evidence quote must be an exact substring of what the model saw; a reduced-context control arm runs
with identical instructions; failures and the one protocol change are kept. Model `claude-opus-5-5`, effort medium,
CampaignGenerator's `claude-code` backend, one call per chapter per arm.

**Aasimar (masked).** In 40 chapter files every `Marron`/`Merrin` token became `[A<n>]` (774 targets). Chapters
1-2 and Ch. 3 to L36 were left out (GM convention: "keep Marron" until the stated switch). The model answered
Marron, Merrin or ambiguous for each marker. Context arm: the whole masked chapter. Control: the target lines
alone. Gold tier `gm`: 49 mentions on lines the GM ruled card by card that morning (31 changed, 18 kept);
tier `current`: the other 725, unruled text. *Protocol change, disclosed:* the Ch. 3 smoke test abstained after an
explicit switch, so "control persists until the text shows a switch" was added before the full run.

**Unnamed (no gold).** Per chapter: the full chapter, the question, and the canon entries (entity registry,
party.yaml, known additions) for every name the question mentions. The earlier agent's evidence was **not** sent,
so the model read the chapter itself. Control: question and canon entries, no chapter. Output per referent:
same / distinct / member-of / ambiguous, with quotes.

**Review gate.** Every disagreement (aasimar) and every positive identification (unnamed) went to the GM as a
review card with the exact before → after, the model's quoted cues, a guess, and a keep-as-is option.

## Outcomes

### Aasimar

| | context | target lines only |
|---|---:|---:|
| GM-approved changes (31) | **31 match** | 29 match |
| GM "keep" lines (18) | 2 match, 12 disagree, 4 ambiguous | |
| Unruled text (725) | 635 match (88%), 13 disagree, 77 ambiguous | 407 match, 9 disagree, 309 ambiguous |
| Evidence quotes not exact | 9 (all curly vs straight quotes) | 0 |

24 disputed lines went to review. **The GM approved all 24**, including all 11 lines kept on the earlier page
(guess was "keep" on 20 of them). So the earlier "keep" verdicts meant "not enough evidence", and the GM accepts
"control persists until a switch" as evidence. With the names hidden, the model reproduced every earlier approved
change and found 24 more.

### Unnamed

| | context | question only |
|---|---:|---:|
| referents judged | 179 | 96 |
| same / member-of | 57 (13 high, 42 medium, 2 low) | 1 |
| distinct | 55 | 6 |
| ambiguous | 67 | 89 |

**The GM approved all 57** (the guess was "reject" on canon-note-dependent ones; approved anyway). 32 of the 65
questions now have GM-ruled identities. The control abstained almost entirely, so the identifications come from
the chapter text. Most successful patterns: an untagged line resolved by the reply that follows; self-naming;
a role epithet ("the rogue", "the barbarian") tied to a PC elsewhere in the chapter.

## Before and after

### Aasimar: 24 bible lines changed (changed name in bold)

| Ch. | Line | | Before | After |
|---|---|---|---|---|
| 4 | 159 | re-ruled (kept earlier same day) | **Merrin** walks up to the heavy wooden doors of the church that are covered with claw marks and scarred by fire and knocks. **Merrin** is convinced that wolves made the claw marks. Gaxim agrees. | **Marron** walks up to the heavy wooden doors of the church that are covered with claw marks and scarred by fire and knocks. **Marron** is convinced that wolves made the claw marks. Gaxim agrees. |
| 4 | 169 | re-ruled (kept earlier same day) | **Merrin** – “ I hear many voices.” | **Marron** – “ I hear many voices.” |
| 4 | 174 | re-ruled (kept earlier same day) | **Merrin** says, “Well, as you know, there is no cure for vampirism.” | **Marron** says, “Well, as you know, there is no cure for vampirism.” |
| 4 | 178 | re-ruled (kept earlier same day) | **Merrin,** “I am opposed to vampires and cannot abide their continued existence.” | **Marron,** “I am opposed to vampires and cannot abide their continued existence.” |
| 4 | 179 | new | Wukong says, “I go where **Merrin** goes.” | Wukong says, “I go where **Marron** goes.” |
| 7 | 15 | re-ruled (kept earlier same day) | **Marron** kills the wolf she is facing. | **Merrin** kills the wolf she is facing. |
| 11 | 72 | re-ruled (kept earlier same day) | Merrin looks at him, confused, “I have no idea.” **Marron** was not present at her death, so she is honest. Gaxim, meanwhile has lost track of all of the characters involved in this plot and grunts. Slerdax says, “I can’t co | Merrin looks at him, confused, “I have no idea.” **Merrin** was not present at her death, so she is honest. Gaxim, meanwhile has lost track of all of the characters involved in this plot and grunts. Slerdax says, “I can’t co |
| 11 | 98 | re-ruled (kept earlier same day) | **Marron** is confused. | **Merrin** is confused. |
| 11 | 120 | re-ruled (kept earlier same day) | Everyone else just stares. **Marron** looks angry, the stench of evil on Wukong and Slerdax is evident. She wondered why their features have changed, and now she knows: these two have been touched by the dark forces. | Everyone else just stares. **Merrin** looks angry, the stench of evil on Wukong and Slerdax is evident. She wondered why their features have changed, and now she knows: these two have been touched by the dark forces. |
| 11 | 123 | re-ruled (kept earlier same day) | **Marron,** “Destroying evil, sign me up!” | **Merrin,** “Destroying evil, sign me up!” |
| 11 | 154 | re-ruled (kept earlier same day) | **Marron** glares. | **Merrin** glares. |
| 21 | 78 | new | It’s important to note that Gaxim had taken the Sunsword from **Merrin.** Gaxim, who is a trusting soul, would ask the sword what to do. The sword convinced that this good soul would give him the revenge that he craves, took | It’s important to note that Gaxim had taken the Sunsword from **Marron.** Gaxim, who is a trusting soul, would ask the sword what to do. The sword convinced that this good soul would give him the revenge that he craves, took |
| 22 | 10 | new | **Marron,** who understands only too well that a revenant cannot be killed, warns Wukong to run away. Wukong stares at death itself and fires an arrow. | **Merrin,** who understands only too well that a revenant cannot be killed, warns Wukong to run away. Wukong stares at death itself and fires an arrow. |
| 23 | 60 | new | That’s not lawful. What do you have to say for yourself – **Merrin** intones disapprovingly. | That’s not lawful. What do you have to say for yourself – **Marron** intones disapprovingly. |
| 23 | 74 | new | “That’s our next stop,” says **Merrin.** | “That’s our next stop,” says **Marron.** |
| 24 | 74 | new | **Marron** then proposes to say grace; Slerdax says, “wait, Strahd is all about his ego? Why don’t we ask him about his life? Offer to listen to his stories?” | **Merrin** then proposes to say grace; Slerdax says, “wait, Strahd is all about his ego? Why don’t we ask him about his life? Offer to listen to his stories?” |
| 26 | 76 | new | **Merrin** strikes with the blood spear twice, and Slerdax’s chromatic orb flies past the intended target. | **Marron** strikes with the blood spear twice, and Slerdax’s chromatic orb flies past the intended target. |
| 26 | 79 | new | Ezmerelda, with a lightning bolt, and **Merrin** finish the Warlock off. | Ezmerelda, with a lightning bolt, and **Marron** finish the Warlock off. |
| 26 | 92 | new | “Cool. Where are the horses?” **Merrin** asks quizzically. | “Cool. Where are the horses?” **Marron** asks quizzically. |
| 26 | 102 | new | Wukong is too cool for that. **Merrin** is confused, but Slerdax and Gaxim join in. | Wukong is too cool for that. **Marron** is confused, but Slerdax and Gaxim join in. |
| 26 | 112 | new | Meanwhile, **Merrin** has been thinking, “if this is a place of residence, can The Vampire enter it?” | Meanwhile, **Marron** has been thinking, “if this is a place of residence, can The Vampire enter it?” |
| 32 | 14 | new | The nothics are intrigued and see that **Merrin** is two warring souls. And they see that the rest of the group hasn’t figured out what’s going on. | The nothics are intrigued and see that **Marron** is two warring souls. And they see that the rest of the group hasn’t figured out what’s going on. |
| 32 | 16 | new | “What are you talking about?” glares Marron. For when Marron or Merrin are in control, they forget about the other. But when they are not in control, they know and see everything. **Merrin** screams. | “What are you talking about?” glares Marron. For when Marron or Merrin are in control, they forget about the other. But when they are not in control, they know and see everything. **Marron** screams. |
| 43 | 75 | re-ruled (kept earlier same day) | “The Church of Barovia,” shouts **Marron,** and with that, they escape and hurry into Mordenkainen’s Mansion. KP notes that they were handed a marginal defeat. | “The Church of Barovia,” shouts **Merrin,** and with that, they escape and hurry into Mordenkainen’s Mansion. KP notes that they were handed a marginal defeat. |

The same changes were mirrored into the 10 chapter summaries and republished.

### Unnamed: 57 identities (the text stays unnamed; recorded in the campaign's `docs/identity/identity_rulings.yaml`)

| Ch. | Kind | Surface in the chapter | Before | After (GM ruling) | Model confidence |
|---|---|---|---|---|---|
| 1 | mention | the girl | unidentified | **Rosavalda Durst** | medium |
| 1 | mention | The boy | unidentified | **Thornboldt Durst** | medium |
| 1 | mention | a well-dressed corpulent man | unidentified | **Drog Halftooh** | medium |
| 2 | mention | The barbarian throws an ax. | unidentified | **Gaxim** | medium |
| 2 | mention | down one rogue, one barbarian | unidentified | **Wukong** | medium |
| 6 | mention | The rogue misses again | unidentified | **Wukong** | high |
| 6 | speaker | I will tell my story the way I want! | unidentified | **Alyek** | medium |
| 6 | mention | the Vistani | unidentified | **Alyek** | medium |
| 8 | mention | the Baron | unidentified | **Vargas Vallakovich** | medium |
| 8 | mention | the Baron’s wife | unidentified | **Lydia Petrovna** | low |
| 10 | mention | Nikolai Wachter’s room | unidentified | **Nikolai Wachter** | medium |
| 10 | mention | she’s sleeping | unidentified | **Fiona Wachter** | medium |
| 13 | speaker | “Bury him!” | unidentified | **Gaxim** | medium |
| 13 | speaker | “Bury Izek, Now!” | unidentified | **Gaxim** | high |
| 13 | speaker | Gaxim marches up to him, “Bones?” | unidentified | **Gaxim** | high |
| 13 | speaker | “Bones?”  / “Upstairs.”  / “Bring bones!” | unidentified | **Gaxim** | medium |
| 14 | mention | Rictavio | unidentified | **Rudolph van Richten** | medium |
| 17 | mention | The mage | unidentified | **Slerdax** | medium |
| 18 | speaker | So Strahd, what do you do for fun? | unidentified | **Slerdax** | medium |
| 18 | speaker | Aw, come on, man, right to work? | unidentified | **Slerdax** | high |
| 20 | mention | a short humanoid with bat wings and spider mandibles | unidentified | **mongrelfolk** (member) | medium |
| 23 | mention | the smiling cleric | unidentified | **Merrin** | medium |
| 23 | speaker | Ah, Oui! Of course! | unidentified | **Ezmerelda d'Avenir** | medium |
| 23 | mention | Haut-couture, it’s HAUT-COUTURE, you philistine. | unidentified | **Wukong** | medium |
| 24 | mention | The butler | unidentified | **Cyrus Belview** | medium |
| 26 | mention | I thought I was working for a hero; instead, I was working for a monster that killed monst | unidentified | **Ezmerelda d'Avenir** | medium |
| 26 | mention | The barbarian | unidentified | **Gaxim** | medium |
| 26 | mention | The genasi magic-user | unidentified | **Slerdax** | medium |
| 26 | mention | the elf | unidentified | **Wukong** | high |
| 28 | mention | The vistani vampire hunter | unidentified | **Ezmerelda d'Avenir** | medium |
| 28 | mention | the magic-user | unidentified | **Slerdax** | medium |
| 28 | mention | the mage | unidentified | **Slerdax** | low |
| 29 | mention | the arcanaloth | unidentified | **Neferon** | high |
| 29 | mention | He fondles his ring | unidentified | **Kasimir Velikov** | high |
| 29 | mention | his ring | unidentified | **ring of warmth** | high |
| 32 | mention | The Fire Genasi | unidentified | **Slerdax** | medium |
| 32 | mention | The orc | unidentified | **Gaxim** | high |
| 33 | speaker | Ah, zee Wolf Pack is beck! | unidentified | **Ezmerelda d'Avenir** | medium |
| 35 | mention | The Dusk elf | unidentified | **Kasimir Velikov** | high |
| 35 | mention | this wizard | unidentified | **Slerdax** | medium |
| 35 | mention | a werewolf encouraging them | unidentified | **Zuleika Toranescu** | medium |
| 37 | mention | I do not work with other men. | unidentified | **Rudolph van Richten** | medium |
| 37 | speaker | The Vampire hunters! | unidentified | **Rudolph van Richten** | medium |
| 37 | mention | I wouldn’t bother trying to kill the hags. | unidentified | **Rudolph van Richten** | high |
| 37 | speaker | Where are you, friends? | unidentified | **Morgantha** | medium |
| 37 | speaker | Your friends have met their doom? | unidentified | **Morgantha** | medium |
| 37 | mention | Yes, silly me. You wish to forget. | unidentified | **Morgantha** | medium |
| 40 | mention | our rogue | unidentified | **Wukong** | medium |
| 40 | mention | the barbarian | unidentified | **Gaxim** | medium |
| 41 | mention | the Barbarian | unidentified | **Gaxim** | medium |
| 41 | speaker | “He planned to turn her into a vampire and have this be her crypt?” | unidentified | **Slerdax** | medium |
| 41 | speaker | “Well done! You are correct!” | unidentified | **Ezmerelda d'Avenir** | medium |
| 42 | mention | the half-orc | unidentified | **Gaxim** | high |
| 43 | mention | The vistani | unidentified | **Ezmerelda d'Avenir** | high |
| 45 | mention | his sister | unidentified | **Patrina Velikovna** | medium |
| 45 | mention | the Banshee | unidentified | **Patrina Velikovna** | medium |
| 46 | mention | Kasimir's sister | unidentified | **Patrina Velikovna** | medium |

Eight of these are summary NPC headings that would otherwise become separate dossiers in summary-native
(e.g. Ch. 1 "The Well-Dressed Corpulent Man" → Drog Halftooh); the campaign file lists them under `npc_headings`.

## What this establishes, and limits

- Hiding the label is a strong test for attribution: the model cannot copy a wrong name, and its agreement with
  every approved change shows the context carries the answer. It also caught errors a name-visible pass let stand.
- A reduced-context control is cheap and informative here (abstentions 77 → 309; 1 positive vs 57).
- Evidence checks should normalise quote marks; all 9 failures were typographic.
- One model, one run per arm, one campaign. GM approval of 81/81 cards is a strong acceptance signal but not an
  independent accuracy estimate: the GM saw the model's argument. Nothing here changes CampaignGenerator code;
  summary-native does not yet read the identity file.
