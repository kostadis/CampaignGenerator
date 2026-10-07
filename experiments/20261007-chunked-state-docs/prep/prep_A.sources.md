# prep_A — sources

Campaign root: `/home/kostadis/out-of-the-abyss/out-of-the-abyss` (abbreviated `$C`). All reads were read-only.

## Files read

**Skill**
- `/home/kostadis/out-of-the-abyss/gm-assistant/skills/gm-session-prep/SKILL.md` (whole file)

**Required context**
- `$C/docs/campaign_state.md` (whole file)
- `$C/docs/world_state.md` (whole file, including the "How to read this document" header)
- `$C/docs/party.md` (whole file)
- `$C/docs/summaries/070-session-untitled.md` (whole file)
- `$C/docs/summaries/069-session-one-manshoon-dead-at-least-one-or-two-more-to-go.md` (whole file)

**Published NPC dossiers (`$C/docs/npcs/`)**
- `kalan-strongbranch.md` (whole file)
- `edvaldo-sedanur.md` (whole file)
- `teles-ahvoste.md` (whole file)
- `fheminor-scrivenbark.md` (whole file)
- `tadric.md` (lines 17–60: Identity, Personality, History)
- `alaundo-the-seer.md` (lines 17–40)
- `spanner.md` (lines 17–45)
- `manshoon.md` (grep hits only: lines 21, 24, 26, 49, 53–66, 82, 92–95, 131)
- "Last Observed State" sections only (grep), from `daral-yashenti.md`, `kazryn-nyantani.md`, `alkrist.md`, `a-lai-aivenmore.md` and `eldeth-feldrun.md`

**References (followed from world_state's pointers)**
- `$C/docs/reference/npcs.md` (grep hits for Miirym, Owlbear, Sylvira, Philemon, Yvenne, Vareth, Khell-Vire, Glabbagool, Kei Tigersteel, Hollypocket, Kazryn, Teles, Drow Spy, Council)
- `$C/docs/reference/factions.md` (grep hits: House T'sarran line 145, Council of Twelve line 226)
- `$C/docs/reference/items.md` (grep hits: Book of Vile Darkness line 52, Prismatic Gemstones 389, Prophecy Crystals 392, Robe 427, Staff of Power 502)
- `$C/docs/canon_events_timeline.md` (last 30 lines, which cover ch69–70)

**Following a world_state citation**
- `$C/docs/summaries/068-session-cryptograms-clockwork-and-caverns.md` (grep hits only, to check the Manshoon dossier's "third simulacrum" claim and Miirym's boon. Line numbers: 140, 144–188, 196, 218–220, 288, 435, 443–449)

**Background (selectively)**
- `$C/docs/background/candlekeep_murders_module_inventory.md` (lines 1–100 and 225–285, plus grep)
- `$C/docs/background/1073077-Candlekeep_Murders_-_192_Res_-_26th_Dec.json`. I read no full sections. I extracted the string entries matching Vile Darkness, B3, Echoes of Alaundo, doppelganger, Kei Tigersteel and Keepers of Secrets, plus every string from index 2620 to 2699 (Chapter 5: B2, B3, B4, Returning to the Surface, Final Confrontation, Restoring Calm, Adventure Rewards) and indices 2458, 2719 and 2720.
- `$C/docs/background/post_oota_vhaerun_arc.md` (first 40 lines. Judged out of scope as post-campaign material, and nothing from it is used)

**Not read, as the instructions require:** anything under `docs/summary_native/` or `docs/npcs/summary_native/`, or any other campaign. Also not read: `docs/tracking/`, `docs/heat.md`, `docs/planning.md`, `docs/campaign_master_plan.md` and the other root docs. None of these was on the required list.

## Where each status came from

| Entity | Status used in prep | Source |
|---|---|---|
| Party level 9 | Level 9 since Ch63 | `campaign_state.md` L402; `party.md` L9; `world_state.md` L17 |
| Party location and situation | Inner Book Chamber, Obsidian Tower | `campaign_state.md` L401; `party.md` L7; ch70 070.03–070.04 |
| Book of Vile Darkness | With Daz behind an ash illusion, read via Mage Hand. Daz chose "demons". Content unresolved | ch70 070.04 (summary L149–155, L186–188); `world_state.md` L22–23, L122, L139; `campaign_state.md` L359–361 |
| Book: touch damage, glyph, darkness, indestructibility | Module DC 18 Cha / 8d6, neutral with advantage. B2 suggestion glyph DC 17. Lava would not destroy it | module JSON idx 2622, 2635–2638, 2652 |
| Prophecy crystals | 4 survive, held by Gyrgum. 2 smashed by Edvaldo | ch70 070.03 (L88, L144); `party.md` L49, L176; `campaign_state.md` L415 |
| Echoes: who can coax them | Only the First Reader and the Keeper | module JSON idx 2851 |
| High Tower keys | Gyrgum: real #1, the fake, the sapphire. Glabbagool: real #2 | `party.md` L48–51; `campaign_state.md` L415–416 |
| Keepers of Secrets | Keeper of Tomes + Gatewarden | module JSON idx 2719; inventory L256 |
| Robe of the Archmagi | Daz wears it; attunement pending | ch70 070.01; `party.md` L222 |
| Staff of Power | Used to breach Candlekeep; whereabouts not recorded | ch70 070.01; `campaign_state.md` L365 |
| Manshoon (real) | Alive, location unknown, vengeance expected | `campaign_state.md` L352; `manshoon.md` L95; ch70 070.02 |
| Manshoon simulacra | Both destroyed. The dossier's "third simulacrum" claim conflicts with the ch68 summary (L220: "A *second* simulacrum remains concealed") | `manshoon.md` L21, L49, L95 vs `068-…md` L220; `campaign_state.md` L259, L353 |
| Edvaldo | Doppelganger, alive, fled in halfling form toward the anti-magic barrier | ch70 070.03 (L142–143); `campaign_state.md` L351; `world_state.md` L45. The dossier `edvaldo-sedanur.md` is stale (last_seen 68, "unexposed") |
| Miirym | Spectral guardian, "witness, not weapon". 10-min boon, 6 min elapsed at the start of ch70. Offered an identity-check boon. Surface summons needs a Keeper | ch68 L140, L182–188; ch70 locations (L319); `reference/npcs.md` L330–333; module idx 2458 |
| Iron Owlbear | Active, neutral, comments | `campaign_state.md` L350; ch69 069.02/069.04; `reference/npcs.md` L254, L487 |
| Avowed arrival | Expected within minutes; won't let artifacts leave unnoticed | ch70 070.04 (L155, L189–190); `world_state.md` L18, L141 |
| Avowed leadership | 4 of 9 leading Readers eliminated; Council split | ch70 locations (L311); `world_state.md` L57; `reference/factions.md` L226 |
| Kalan Strongbranch | Alive; reinstated Gatewarden and Head of the Avowed; last seen ch67 | `kalan-strongbranch.md` L19, L97–104; `campaign_state.md` L335 |
| Tadric | Alive; Watcher, Kalan's lieutenant; escorting A'lai; monograph co-author | `tadric.md` L19, L59–60; `campaign_state.md` L336; module idx 2671 (likely acting Gatewarden) |
| Kei Tigersteel | Lorekeeper, Oghma priest; module casts zone of truth at the trial | `reference/npcs.md` L308; module idx 1356, 2671 |
| Fheminor Scrivenbark | Alive (status not established past ch62); Keeper candidate; module: intended successor, wants the Keeper's will honoured | `fheminor-scrivenbark.md` L19, L34–37; inventory L26; module idx 2677; `campaign_state.md` L346 |
| Teles Ahvoste | Alive, unresolved suspect, Keeper candidate; module: archmage | `teles-ahvoste.md` L19, L43; inventory L27; `campaign_state.md` L346 |
| Kazryn Nyantani | Status not established after ch60. Lover conflict: Janussi (table) vs A'lai (module) | `kazryn-nyantani.md` L46–47; `reference/npcs.md` L305; inventory L28 |
| Daral Yashenti | Cured (ch62); later fate not established | `daral-yashenti.md` L85; `campaign_state.md` L338 |
| Sylvira Savikas | Alive, cooperative, does not know about Moziqodo. Location conflict: ch67 investigator's office vs "bedridden, Infernal Fortress" | `world_state.md` L150–151; `campaign_state.md` L337; `reference/npcs.md` L461 |
| A'lai Aivenmore | In custody, headed to the null-magic prison; holds the name of Daz's paymaster | `a-lai-aivenmore.md` L96; `world_state.md` L145 |
| Alkrist | Imprisoned, disgraced | `alkrist.md` L58–59; `world_state.md` L73 |
| Janussi, Bookwyrm | Dead | `campaign_state.md` L330–331 |
| Glabbagool | Alive, with the party, Zalthir's sidekick; holds key #2; standing order about death traps | ch69 069.03 (L90); `world_state.md` L41; `campaign_state.md` L313 |
| Dawnbringer | Thorin's sentient sunblade, displeased, in therapy | ch70 070.03; `world_state.md` L34, L121 |
| House T'sarran spy | Imprisoned; location unconfirmed | `campaign_state.md` L272, L663; `world_state.md` L149 |
| House T'sarran surveillance | Watching Daz to identify his protector | `world_state.md` L146 |
| Endless Chant / wards | Silent since ch64 / broken ch65; no restoration recorded | `campaign_state.md` L206–208, L374 |
| Spanner | Owed tools and a study; Dust ruling open | `spanner.md` L35–36; `campaign_state.md` L367–370 |
| Inda | Module only: House of Alaundo, secret Alaundo worshipper (not met at the table) | inventory L95; `campaign_state.md` L702 ("Inda: NOT FOUND IN SUMMARIES") |
| Fembris Lancer | Alive, loose-lipped; module doppelganger-swap precedent | `campaign_state.md` L339; module idx 2470, 2666 |
| Forge prophecy / Eldeth | "names of demons in her mouth"; Eldeth en route | ch69 069.04 (L103, L117–118); `eldeth-feldrun.md` L80–82 |
| Return route / Final Confrontation / B4 lever | Far bridge → reverse-gravity well → wall of force; simulacrum ambush; attic self-destruct lever | module idx 2646–2667 |
| Riddle-line 3/6 bookkeeping, "Manshoon Track" | Unsettled GM call | ch68 summary L166 (068.04 note) |
