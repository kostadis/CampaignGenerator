# prep_D: sources and verification log

Condition D (pointer skill, pre-today docs). Campaign root: `/home/kostadis/out-of-the-abyss/out-of-the-abyss`.

## Files read

**Skill**
- `experiments/20261007-chunked-state-docs/skills_variant/gm-session-prep-pointer/SKILL.md` (full)

**Index (generated docs)**
- `experiments/20261007-chunked-state-docs/install_backup/20261007T163036Z/world_state.md`, in place of `docs/world_state.md` (full, 337 lines)
- `docs/party.md` (full, 255 lines)
- `docs/campaign_state.md`: lines 1–30, 170–429 and 560–707 (completed encounters for Candlekeep, resolved threads, NPC state table, open threads, party situation, module-coverage audit). Lines 31–169 (the Underdark arcs) were skipped as irrelevant to the beat.

**Authority (summaries)**
- `docs/summaries/070-session-untitled.md` (full)
- `docs/summaries/069-session-one-manshoon-dead-at-least-one-or-two-more-to-go.md` (full)
- `docs/summaries/068-session-cryptograms-clockwork-and-caverns.md`: 068.04, 068.05, and NPCs and Items (lines 134–200 and 420–472), plus a grep for Edvaldo
- `docs/summaries/067-session-ninety-seven-steps-and-a-fall.md`: 067.01, 067.02, and NPCs and Items (lines 1–60 and 385–469)
- `docs/summaries/065-session-look-who-s-coming-to-candlekeep.md`: NPCs and Session-End State (lines 195–240 and 360–399), plus a grep for Alkrist and wards
- `docs/summaries/062-…`, `063-…`, `059-…`: targeted grep hits and NPC blocks only (Kalan, Alkrist, Fembris, Kei Tigersteel, Teles, Fheminor, First Reader)
- `docs/summaries/054-…`, `056-…`, `057-…`, `058-…`, `060-…`, `061-…`, `064-…`: grep-hit lines only (First Reader, Fheminor, Teles, Vareth, Daral, Kazryn, Philemon, Yvenne, Khell-Vire, Ring of Protection)
- `docs/summaries/052-…`, `045-…`: grep-hit lines only (level-up, spectacles)
- A filename listing of `docs/summaries/` (050–070)

**Module**
- `docs/background/candlekeep_murders_module_inventory.md` (first ~100 lines, the NPC roster)
- `docs/background/1073077-Candlekeep_Murders_-_192_Res_-_26th_Dec.json`: extracted text of Chapter 5 (Vault of Secrets), sections B2, B3, B4, Rocket Alternative, Returning to the Surface, Final Confrontation, Restoring Calm, Resurrection and Adventure Rewards, plus a keyword scan for "Vile Darkness" and "Keeper of Secrets" (the Chapter 4 hits on Manshoon's motive)

**Not read (as instructed):** `docs/world_state.md`, `docs/npcs/`, `docs/reference/`, `docs/canon_events_timeline.md`, `docs/summary_native/`, other campaigns. `notes/` was also not read.

## Verification log

| # | Entity | What the index doc said (doc:line) | What the latest summary says (file + scene) | Verdict |
|---|---|---|---|---|
| 1 | Book of Vile Darkness: location, illusion, Daz's choice | world_state:16, :192; campaign_state:651; party.md:218–221 | 070 §070.04 + Items: on a podium in the Inner Book Chamber, Minor Illusion of ash, Mage Hand reading, chose the demons, intel untrustworthy | agree |
| 2 | Avowed arrival imminent | world_state:19; party.md:17; campaign_state:362–363 | 070 §070.04 + Locations/Candlekeep: "expected to arrive shortly… would not allow artifacts… to disappear unnoticed" | agree |
| 3 | Edvaldo: doppelganger, fled as a halfling, believes the book is ash | world_state:20, :140; campaign_state:351 | 070 §070.03, §070.04, NPCs | agree |
| 4 | Edvaldo's name form ("Sedanur" as nickname) | world_state:140 `Edvaldo "Sedanur"` | 068 NPCs "Edvaldo Sedanur", a hired scholar who presents as Avowed | disagree (cosmetic) |
| 5 | Prophecy crystals: 10 total, 4 played, 2 smashed, Gyrgum holds 4 | world_state:14, :193; party.md:176 | 070 §070.03 + NPCs/Alaundo + Items; 069 §069.05 (ten gems, four dark) | agree |
| 6 | Miirym's boon: 30 ft for 10 min, 6 min elapsed | world_state:18; party.md:16 | 068 §068.04; 070 §070.02 + Locations | agree |
| 7 | Miirym: spectral silver dragon, witness not weapon, verified Gyrgum | world_state:162 | 068 §068.04 + NPCs | agree |
| 8 | Real Manshoon's vengeance promised | world_state:21, :183 | 070 §070.02 | agree |
| 9 | Staff of Power used in the breach, recovery not recorded | world_state:182; campaign_state:365 | 070 §070.01 + Items (used, no recovery) | agree |
| 10 | Glyphs of warding: explosion causes a chain reaction | world_state:22; party.md:20 | 070 §070.02 + Spells; 069 §069.05 | agree |
| 11 | Vault room layout (tomes vs. door chamber) | world_state:166–167 (two separate rooms) | 069 §069.05 (one chamber holding the 100 books, desk, note, tray and Obsidian Door); 068 §068.05 | disagree |
| 12 | "Means to destroy the collection" are above | world_state:166 | 068 §068.05 note text | agree |
| 13 | Iron Owlbear active, previous one broken | world_state:165; campaign_state:627 | 068 NPCs; 069 §069.02 | agree |
| 14 | Robe of the Archmagi with Daz, attunement pending | world_state:93; party.md:222 | 070 §070.01 + Items | agree |
| 15 | Daz's Ring of Protection | party.md:223 ("not on the sheet"); world_state:92 (has it) | 056 Items (acquired); 070 Items (a candidate to give up for attunement) | disagree (party.md) |
| 16 | Party level 9 since ch63 | world_state:23; party.md:9; campaign_state:402 | 063 §063.06 "The party leveled up to level nine" | agree |
| 17 | Bookwyrm's rank | world_state:131 ("Great Reader"), :121 (First Reader heads it, as if a separate living person); party.md:91 ("First Reader") | 056 §056.04 "Bookwyrm, the First Reader"; 062 NPCs; 065 NPCs "Bookwyrm (First Reader) — Dead" | disagree (world_state); agree (party.md) |
| 18 | Who received the party at the gate | campaign_state:573 ("the First Reader received them; Bookwyrm did not") | 056 §056.04 "received by Bookwyrm, the First Reader" | disagree |
| 19 | Four of nine leading Readers eliminated | world_state:121 | 070 Locations/Candlekeep; 065 Session-End (Bookwyrm dead, Alkrist neutralized, A'lai captured) | agree |
| 20 | Kalan: reinstated Head of the Avowed and Gatewarden, fled ch65, back ch67 | world_state:135; campaign_state:257, :335 | 062 §062.03; 063 NPCs; 065 Session-End; 067 NPCs | agree |
| 21 | Tadric alive, escorting A'lai to the null magic prison | world_state:136; campaign_state:336 | 067 §067.02 + NPCs | agree |
| 22 | Sylvira does not know about Moziqodo, bedridden, supplied Miirym's name | world_state:137; campaign_state:337 | 067 NPCs; 068 NPCs/Miirym (latest mention) | agree |
| 23 | Teles / Fheminor tipped as next head | world_state:146; campaign_state:346 | 062 NPCs/Kalan (latest mention, ch62) | agree |
| 24 | Fembris Lancer: loose-lipped minder | world_state:139 | 063 §063.06 + NPCs (latest) | agree |
| 25 | Kei Tigersteel: Lorekeeper and Oghma priest | not in the index docs | 059 NPCs (latest) | n/a (summary only) |
| 26 | Alkrist alive, disgraced, neutralized | world_state:132; campaign_state:332 | 065 Session-End (GM ruling); 070 mentions him only as Manshoon's disrupted plan | agree |
| 27 | A'lai's trade for a prison cell, Baenre deduction | world_state:133 | 067 §067.02 | agree |
| 28 | High Tower keys: Gyrgum (real + fake + sapphire), Glabbagool (A'lai's real key) | world_state:150–153; party.md:49–51 | 065 Session-End key ledger; 067 Items/High Tower Key | agree |
| 29 | Modron tools owed to Spanner; Dust of Mechanus ruling open | world_state:171, :196; campaign_state:367–370 | 067 NPCs/Spanner + Items (GM rules the tool an alternative); 068 Items ("never ruled on tape and is open"). The summaries conflict with each other, and the doc reports the conflict faithfully | agree |
| 30 | Wards broken ch65, chant silent ch64 | world_state:122, :124 | 065 §065.01–.03 + footer (chant belongs to ch64) | agree |
| 31 | Forge prophecy (Eldeth, Thorin, Zalthir, Daz, Dawnbringer) | world_state:272; party.md:25 | 069 §069.04; 070 NPCs/Alaundo | agree |

**Total verification lookups: 31 entity verifications** (rows above), done in **11 search/read tool calls** against the summaries beyond the two required full reads of ch70 and ch69. **Disagreements: 5** (rows 4, 11, 15, 17, 18). Row 17 is one disagreement but implicates two world_state lines.
