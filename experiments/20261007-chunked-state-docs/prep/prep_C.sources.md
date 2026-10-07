# prep_C — sources and verification log

Condition C (pointer skill: state docs = INDEX, summaries = AUTHORITY). Campaign root:
`/home/kostadis/out-of-the-abyss/out-of-the-abyss`. Nothing in the campaign directory was written.

## Files read

**Skill**
- `experiments/20261007-chunked-state-docs/skills_variant/gm-session-prep-pointer/SKILL.md` (full)

**Index pass (generated docs)**
- `docs/campaign_state.md` (full, 707 lines)
- `docs/world_state.md` (full, 163 lines)
- `docs/party.md` (full, 255 lines)
- `docs/canon_events_timeline.md` (tail, last ~25 events only)
- `docs/npcs/*.md` — `Last Observed State` sections + `last_seen` only, for: kalan-strongbranch, teles-ahvoste, fheminor-scrivenbark, kazryn-nyantani, daral-yashenti, tadric, fembris-lancer, spanner, edvaldo-sedanur, manshoon, alaundo-the-seer, a-lai-aivenmore, alkrist, eldeth-feldrun, elian, irony, orrin-glass (plus section-heading list of kalan-strongbranch)
- `docs/reference/npcs.md`, `docs/reference/factions.md`, `docs/reference/threats.md` — grep hits only (Sylvira, Kei Tigersteel, Teles, Fheminor, Kazryn, Miirym, Owlbear, Edvaldo, Avowed)

**Module material**
- `docs/background/candlekeep_murders_module_inventory.md` (lines 1–60, 180–285)
- `docs/background/1073077-Candlekeep_Murders_-_192_Res_-_26th_Dec.json` — flattened to scratchpad text; read sections B2 The Vault, B3 Side Vault, Turn Up the Vileness, B4 The Attic, Rocket Alternative, Returning to the Surface, Final Confrontation, Restoring Calm to Candlekeep, Resurrection inset, Bookwyrm's Reward (plus a grep for "vile darkness / side vault / reward")

**Authority (session summaries)**
- `docs/summaries/070-session-untitled.md` (full)
- `docs/summaries/069-session-one-manshoon-dead-at-least-one-or-two-more-to-go.md` (full)
- `docs/summaries/068-session-cryptograms-clockwork-and-caverns.md` (targeted grep: Sylvira/Spanner/Miirym/simulacrum/Edvaldo/tools/Kalan)
- `docs/summaries/067-session-ninety-seven-steps-and-a-fall.md` (scene index + targeted grep; Potion of Flying item block)
- `docs/summaries/065-session-look-who-s-coming-to-candlekeep.md` (065.03 scene, NPCs, Locations, Items sections)
- `docs/summaries/064-*.md` (grep: chant; scene index)
- `docs/summaries/063-session-the-key-is-secured.md` (grep: level, deputize, Moziqodo kill; 063.04 lines)
- `docs/summaries/062-session-academic-vindication-and-an-assault.md` (grep: prison / Teles / Fheminor / naming ceremony / reinstate; scene index)
- `docs/summaries/059-session-questions-answers-and-a-key.md` (grep: Kei Tigersteel; scene index)
- `docs/summaries/056-*.md` (grep: spy / Polly / cell; scene index)
- Chapter-membership grep across `docs/summaries/05*-07*.md` for: Teles, Fheminor, Kazryn, Sylvira, Kalan, Daral, Fembris, Philemon, Yvenne, Vareth, Khell, Tadric, Spanner, Miirym, "third simulacrum", Elian, Staff of Power, Polly, spy

**Not read (per instructions):** anything under `docs/summary_native/`, `docs/npcs/summary_native/`, other campaigns.

## VERIFICATION LOG

| # | Entity | What the index doc said (doc:line) | What the latest summary says (file + scene) | Verdict |
|---|---|---|---|---|
| 1 | Manshoon — simulacrum count | npcs/manshoon.md:95 "A third simulacrum remains concealed in the vault … [ch 068 / 068.05]" | 068 (068.05 bullets): "A *second* simulacrum remains concealed in the vault"; that one is found in 069.05 and thrown in lava 070.02 | **disagree** |
| 2 | Edvaldo — exposure/status | npcs/edvaldo-sedanur.md:34 "remains with them, unexposed" (last_seen 68) | 070 (070.02) revealed as doppelganger; (070.03) smashes 2 crystals, flees as halfling toward anti-magic barrier | **disagree** |
| 3 | Edvaldo — Key NPCs line | world_state.md:77 "Unexposed doppelganger scholar; remained with party" | 070 (070.02, 070.03) as above | **disagree** |
| 4 | Edvaldo — Companions line | world_state.md:45 "doppelganger … smashed two prophecy crystals, fled toward the anti-magic barrier" | 070 (070.03) | agree |
| 5 | Edvaldo Sedanur — reference | reference/npcs.md:130 "GM-only, still unexposed" | 070 (070.02) | **disagree** |
| 6 | Sylvira — status/location | campaign_state.md:337 "Alive, bedridden (abyssal plague) / Infernal Fortress" | 067 (067.03) arrives at the investigator's office, weakened by illness, helps solve cryptogram | **disagree** |
| 7 | Sylvira — unaware of Moziqodo's death | campaign_state.md:337; party.md:27 | 067 (067.03) "does not yet know that the party killed her son" | agree |
| 8 | House T'sarran spy — location | campaign_state.md:272, :663 "location [Unconfirmed]" | 056 (056.04) "The party decides to keep the spy under Glabbagool's watch rather than hand her over" | **disagree** |
| 9 | Book of Vile Darkness — state | world_state.md:22–23; campaign_state.md:360 | 070 (070.03, 070.04) illusion of ash, Mage Hand, chose demons, untrustworthy narrator | agree |
| 10 | Book — "information about Underdark events" verifier flag | world_state.md:140 "⚠ unverified: … not in the summaries" | 070 (070.04) "The book begins revealing information about events in the Underdark" | **disagree** (false flag) |
| 11 | Avowed Readers arriving | world_state.md:18; party.md:17 | 070 (070.04) "expected to arrive shortly … will not be able to walk away … unnoticed" | agree |
| 12 | Prophecy crystals — 4 held by Gyrgum | world_state.md:28; campaign_state.md:366 | 070 (070.03) Gyrgum secures the four surviving crystals | agree |
| 13 | Robe of the Archmagi | world_state.md:21; campaign_state.md:413 | 070 (070.01; Items) attunement at next long rest; may displace Ring of Protection or spectacles | agree |
| 14 | Miirym's anti-magic boon | party.md:16 "30-ft anti-magic field for 10 minutes … expiring or has expired" | 068 (Locations: bridge) widen to 30 ft for 10 min; 070 (070.02) six minutes already elapsed | agree |
| 15 | Kalan Strongbranch — alive, back | world_state.md:78; campaign_state.md:257, :335 | 067 (067.03) arrives late, huffing; 065 (NPCs) had fled | agree |
| 16 | Kalan — out of shape / falls behind | npcs/kalan-strongbranch.md:104 | 063 (063.04) "huffing and puffing" | agree |
| 17 | Tadric — escorting A'lai | campaign_state.md:336; npcs/tadric.md:65 | 067 (067.02) marches A'lai to the null magic prison | agree |
| 18 | A'lai — in custody | npcs/a-lai-aivenmore.md:96; campaign_state.md:333 | 067 (067.02) | agree |
| 19 | Alkrist — imprisoned | npcs/alkrist.md:58–59; campaign_state.md:332 | 062 (062.04) "Kalan ordered Alkrist imprisoned" | agree |
| 20 | Teles / Fheminor — tipped for head | campaign_state.md:346; npcs/teles-ahvoste.md:43 | 062 (062.02) Kalan expects Teles Ahvoste or Fheminor | agree |
| 21 | Kei Tigersteel | reference/npcs.md:308 "Lorekeeper … priest of the Temple of Oghma" | 059 (059.01) | agree |
| 22 | High Tower keys ledger | world_state.md:29; party.md:49–51 | 065 (065.03; Items: Real/Fake key, Sapphire) Gyrgum: Tadric's real key + sapphire + fake; A'lai's real key in Glabbagool | agree |
| 23 | Potion of Flying in Glabbagool | party.md:50 | 067 (Items: Potion of Flying) "concealed inside Glabbagool" | agree |
| 24 | Glabbagool — with the party | world_state.md:41 (⚠ later) | 069 (069.04) "Glabbagool remains with the party"; absent from 070 | agree (070 silent) |
| 25 | Spanner — tools on loan, study owed | npcs/spanner.md:31; campaign_state.md:368–369 | 067 (067.05) | agree |
| 26 | Dust of Mechanus ruling | campaign_state.md:370 "still open" | 068 (Items) "never ruled on tape and is open" — but 067 (Items) says GM ruled tool an alternative | agree with latest (summaries conflict internally) |
| 27 | Party level 9 | party.md:9 "reached it in Ch63" | 063 (063.06) "ended the session at level nine" | agree |
| 28 | Deputized Watchers | party.md:13 | 063 (063.03) "I hereby deputize you as Watchers of Candlekeep" | agree |
| 29 | Moziqodo killed by Thorin | party.md:147 | 063 (063.05) Dawnbringer's critical kills him | agree |
| 30 | Iron Owlbear / dead owlbear | campaign_state.md:350, :626 | 068 (068.03) previous owlbear statue damaged; 069 (069.04) live owlbear commentary; 070 (070.02) "bones of a dead owlbear" | agree |
| 31 | Staff of Power — fate | campaign_state.md:365 "not recorded" | 070 (070.01; Items) used to breach; no later mention | agree |
| 32 | Forge prophecy / Eldeth | world_state.md:76; campaign_state.md:381–382 | 069 (069.04) | agree |
| 33 | Four of nine Readers eliminated | world_state.md:102 | 070 (Locations: Candlekeep) | agree (065 Locations says "five key Avowed defenders") |
| 34 | Endless Chant silent | world_state.md:156 | 064 (064.01) | agree |
| 35 | Orrery strangers | reference/threats.md:158 | 067 (067.03) | agree |
| 36 | Bookwyrm received party at Candlekeep (incidental) | campaign_state.md:573 "the First Reader received them; Bookwyrm did not" | 056 (056.04) "received by Bookwyrm, the First Reader" | **disagree** |

**Totals:** 36 entity verification lookups (one per row), carried out through 2 full summary reads (069, 070) and 11 targeted grep/sed passes over summaries 056, 059, 062, 063, 064, 065, 067, 068, plus one cross-chapter membership grep.
**Disagreements:** 8 (rows 1, 2, 3, 5, 6, 8, 10, 36).
