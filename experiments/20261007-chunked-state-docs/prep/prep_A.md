# Custody of the Unburnable Book

Co-GM working doc. Not canon yet. Staging for the session after Ch70 (2026-09-28).
**Party:** level 9 [TABLE ch63; campaign_state "Party Current Situation"]. Zalthir (Gabe), Thorin Giantfriend (Joe Beda), Gyrgum (Ben Pfaff), Daz (Mike Hall). All four are player-run. Glabbagool is the GM-run sidekick and is with the party.
**Register:** a chamber piece about institutional custody. The fight is over and the paperwork is lethal. Think of a university tenure committee that has walked in on a crime scene, with a sentient evil book in the room listening to everyone.

> **Scope.** Open **in the Inner Book Chamber, seconds after Ch70 ended**. Daz is turning the Book of Vile Darkness's pages with Mage Hand behind an ash illusion, Gyrgum holds the four surviving crystals, and Edvaldo is loose somewhere below. **Stop** when the question of who holds what has been answered (Book, crystals, keys) and the party is either walking out of the Vault or under escort out of it.
>
> **Intended order:** (1) The last quiet minutes, when the party decides what the Readers will see. (2) The Readers arrive and the custody hearing happens on the spot. (3) Edvaldo's last card. (4) Optional: the walk out.
>
> **Do NOT pull forward:** the content of the four crystals (unless you decide one plays, see Open Decisions), the Keeper of Tomes succession *vote*, Gauntlgrym or Eldeth's return, telling Sylvira about Moziqodo (let it threaten, don't resolve it), or the real Manshoon on stage.

---

## How to read this doc: provenance legend

| Tag | Means | Trust |
|---|---|---|
| `[MODULE §x]` | *Candlekeep Murders* adventure text (`docs/background/1073077-Candlekeep_Murders…json`), with a section name | Canon, unless the table already played it differently |
| `[TABLE chNN]` | Already played (session summary NN), or a fact in the state docs | Canon |
| `[OVERLAY]` | **Mine.** Invention, staging, connective tissue, recommendations | **Cuttable. Nothing downstream breaks** |

**Tiebreak:** if an overlay item and a module item disagree, **the module wins and the overlay is what I got wrong.** If the module and something *already played* disagree, the table wins. Example: the module's B3 door riddle is a rhymed verse with the answer "candle", but the table played Alaundo's inscription, and the table's version stands [MODULE ch5 "B3. Side Vault"; TABLE ch70 070.01].

---

## THE CAST: everyone who can walk on tonight

Module-supplied support NPCs come first. These are the ones that arrive automatically.

| Who | What they are | Why they can be here tonight | Tag |
|---|---|---|---|
| **Miirym, the Sentinel Wyrm** | Translucent ghost silver dragon, guardian of the vaults. True name *Vydykyq*. "Bound to be witness, not weapon." | She is in the lava cavern right now. Her 30-ft, 10-minute anti-magic boon is running out. **She watched everything.** She is the one witness every Reader will trust. The module says she can only be summoned to the surface by a legitimate Keeper of Tomes, and there isn't one. | [MODULE "Players vs. Manshoon"; TABLE ch68 068.04; ch70 070.02] |
| **The Flying Iron Owlbear** | Tiny winged iron sentinel. Neutral after its test, and gives colour commentary. | It is at the tower. It saw the party's whole Vault visit. It is a comic witness, and also a second channel of testimony for Kalan. | [MODULE "Vault guardians"; TABLE ch68–69] |
| **Tadric** | 23-year-old Watcher, bowl cut, Kalan's lieutenant, Gyrgum's monograph co-author. | Last seen marching A'lai to the null-magic prison [ch67]. The module names him the likely *acting Gatewarden* at the post-Vault reckoning. He is the party's friendliest face in any delegation. | [MODULE ch5 "Restoring Calm"; TABLE ch67 067.02] |
| **Kei Tigersteel** | Lorekeeper, priest of Oghma, slender human of about fifty, the library's spiritual head. | The module has him cast *zone of truth* at the post-Vault council. At the table he was seen only directing Janussi's body to the Shrine of Oghma. He is the neutral arbiter. | [MODULE ch5 "Restoring Calm"; TABLE ch59 npcs, `reference/npcs.md` "Kei Tigersteel"] |
| **Fheminor Scrivenbark** | Great Reader. Dowdy halfling, "steely nature", "unfriendly girl gnome" (per Nibbles). | The module calls her Janussi's intended successor. After the Vault she presses for *the previous Keeper's will* to be honoured. Kalan tipped her (or Teles) for Keeper. | [MODULE inventory; MODULE ch5 "Restoring Calm"; TABLE ch62 062.02; dossier `fheminor-scrivenbark.md`] |
| **Kalan Strongbranch** | Gatewarden and reinstated Head of the Avowed. Threefold Proof methodologist. Says "Gadzooks". | Alive. He arrived late and out of breath in ch67, and nothing is recorded after that. Module: the Gatewarden is one of the two "Keepers of Secrets". | [TABLE ch67 067.03; dossier `kalan-strongbranch.md` "Last Observed State"; MODULE "High Tower Library"] |
| **Teles Ahvoste** | Great Reader. Module: archmage. Passed over for Keeper about twenty years ago. Shouted "hypocrite!" at Janussi. Unwanted advances toward Irony. | Kalan tipped him (or Fheminor) for Keeper. The investigation never cleared or charged him. | [MODULE inventory; TABLE ch58, ch61, ch62; dossier `teles-ahvoste.md`] |
| **Kazryn Nyantani** | Great Reader and chief cleric. | Last seen acting at the Deadwinter supper. **The sources disagree on whose lover she was** (see Open Decisions). | [TABLE ch60 060.06; ch61 061.05; MODULE inventory; dossier `kazryn-nyantani.md`] |
| **Daral Yashenti** | Great Reader, a recovering drunk. Cured by Dawnbringer, and swore to make sentient swords his research field. | Alive per campaign_state. His fate after ch63 is not established in his dossier. He is a likely gawker and a Dawnbringer fan. | [TABLE ch62 062.05; ch63; campaign_state NPC table; dossier `daral-yashenti.md`] |
| **Sylvira Savikas** | Tiefling Great Reader, demonologist, has the abyssal plague. Mother of Moziqodo, and **does not know the party killed him.** | She cooperated in the investigator's office in ch67. She is a **time bomb if she comes down**. | [TABLE ch67 067.03; world_state "Sylvira's grief deferred"; campaign_state NPC table] |
| **"Edvaldo"** (doppelganger) | Manshoon's agent, posing as an Avowed researcher. Took 53 damage and stood. Last seen in halfling form fleeing toward the anti-magic barrier. | He is still in the cavern. Whether he can get out is a GM decision. | [TABLE ch69 069.01; ch70 070.03; campaign_state "Edvaldo 'Sedanur'"] |
| **The Book of Vile Darkness** | Sentient artifact, "written or purportedly written" by Vecna. It offered Daz a choice, and he chose the demons. It is an untrustworthy narrator. | It is in the room, and it talks. Treat it as a cast member with an agenda. | [TABLE ch70 070.04; MODULE "B3. Side Vault"] |
| **Glabbagool** | Sentient grey ooze, Zalthir's shadow-apprentice sidekick, earnest hero-worshipper. Carries real High Tower key #2, the Potion of Flying, and Fembris's notes. | He is with the party. Standing order from Zalthir: point out any instant-death trap Zalthir has forgotten. | [TABLE ch69 069.03; campaign_state "Assets"; party.md "Key ledger"] |
| **Dawnbringer** | Thorin's sentient sunblade. Displeased with the chaos, and in therapy with Philemon. | She is the light source in a dark room that holds the Book. She will have *opinions*. | [TABLE ch70 070.03; ch56 056.06] |
| **Two Watchers** (unnamed) | Gatehouse security under the Gatewarden. The module calls Watchers "priests" in one passage. | Escort and lantern-bearers for the delegation. **One of them may be Edvaldo** (Scene 3). | [MODULE "Watchers" rank and "Daral Found Dead!"; OVERLAY count] |
| *Offstage, can be named:* **the real Manshoon** (never on stage tonight), **Philemon** (Dawnbringer's therapist), **Spanner** (owed his modron tools and a study), **Inda** (module: House of Alaundo, secretly worships Alaundo as a god), **Fembris Lancer** (adjutant, loose-lipped) | — | Speakable only as references or messengers. **None of them walks on** without first being added to this table. | [TABLE; MODULE inventory] |

> GM-only: **no Reader has a confirmed reason to be in the delegation except "the surviving Avowed Readers" collectively** [ch70 070.04]. Who exactly comes down is an Open Decision. The table above is the *pool*. My recommended delegation is in Scene 2.

---

## ALREADY IN MOTION: running whether or not the party touches it

| Clock | Where it stands tonight | Tag |
|---|---|---|
| **The Avowed delegation descending** | It arrives "within minutes" of Ch70's end. The Readers are "delighted that the hidden books had been found" but will not let artifacts of this power leave unnoticed. | [TABLE ch70 070.04] |
| **Miirym's anti-magic curtain** | It is a 10-minute boon, and six minutes were already gone when Ch70 opened [ch70 locations]. **It expires during Scene 1 at the latest.** When it drops, spells work on the bridge again: Edvaldo can be magicked, and so can the party. | [TABLE ch70; party.md "Immediate pressures"]; expiry timing [OVERLAY] |
| **Edvaldo's escape** | He is in halfling form near the anti-magic band. The only ways out are back up the Great Shaft (the way the Readers are coming down) or the far bridge and tunnel (module: the one-way exit). | [TABLE ch70 070.03; MODULE ch5 "Returning to the Surface"] |
| **The real Manshoon** | He has lost two simulacra. Both promised vengeance. A "dead-man switch" was feared and never confirmed. The **Staff of Power's whereabouts are not recorded**. | [TABLE ch70 070.02; campaign_state Open Thread 4] |
| **The Book talking to Daz** | It has *begun* revealing Underdark and demon information. The content is unresolved: "to be resolved when the party reconvenes." | [TABLE ch70 070.04] |
| **The succession vacuum** | Four of the nine leading Readers are gone: Janussi and Bookwyrm dead, Alkrist imprisoned, A'lai imprisoned. There is no Keeper of Tomes. The Council of Twelve is split. | [TABLE ch70 locations; ch65 065.03; ch62 062.02] |
| **Broken wards, silent Chant** | The wards were broken in Ch65. The Endless Chant went silent in Ch64, which "never happens". Neither is recorded as restored. | [TABLE ch64, ch65; campaign_state Open Thread 8] |
| **A'lai in the null-magic prison** | He is still holding back the name of "the person in Menzoberranzan who has been paying to keep your drow breathing." | [TABLE ch65, ch67; world_state "A'lai's pending judgment"] |
| **Sylvira doesn't know** | Tadric insists someone must tell her. Nobody has. | [TABLE ch64 064.01; ch67] |
| **House T'sarran watching Daz** | They want to identify his protector. The shrunken spy's current location is **unconfirmed** (bag of holding, or a Candlekeep cell). | [TABLE ch54, ch56; campaign_state NPC table] |
| **Background weather** | The surface madness, Zuggtmoy's pending wedding, Demogorgon's whereabouts unknown, and Eldeth en route to Gauntlgrym with "the names of demons in her mouth." | [TABLE ch56, ch32, ch69 069.04] |

> **Visibility rule:** the Manshoon clock and the T'sarran clock must *show up as noise* tonight even though neither pays off. Ways to do that: a Reader mentions the Staff of Power scorch-trail through the shields; Daz feels the familiar "watched" itch [OVERLAY].

Co-GM working doc. Not canon yet. Staging for the session after Ch70.

---

## The Win Condition (state plainly to yourself)

The session has landed when **the party walks out of the Vault with a custody arrangement for the Book of Vile Darkness that Candlekeep has *witnessed and recorded*,** whichever way it goes: Candlekeep keeps it, the party keeps it under conditions, it is re-sealed, or it is sent somewhere else. The party's standing as deputized Watchers either survives the hearing or is visibly spent on it. The two smashed crystals are put on the record as **Edvaldo's** act, not theirs. "Witnessed and recorded" is what matters. What the module and the table have both been building is that Candlekeep's legitimacy comes from evidence and witness: Kalan's Threefold Proof, Miirym bound as witness, a door that opens only to sincere intent. A smuggled book is a theft. A witnessed book is a *custody*. [OVERLAY framing on TABLE facts]

## The Default Trajectory (what happens if the party does nothing)

- **The Readers arrive** and find a burnt-looking ash pile on the pedestal, two crystal shards on the floor, a dead owlbear, and a strange drow in Manshoon's robe. The first reading is *the party destroyed Alaundo's prophecies and the forbidden book*. [OVERLAY]
- **Kalan** demands three independent proofs before he believes anything, and declares the scene a crime scene. Procedure stalls everything, and nobody is allowed to leave. [OVERLAY, grounded in dossier personality]
- **The illusion breaks** to an Investigation check or a *detect magic*, or simply because Mage Hand is visibly turning invisible pages. The Readers realise the Book is intact *and Daz has been reading it*. Teles wants it studied, Fheminor wants it sealed by the Keeper's will, and Kei wants *zone of truth* on Daz. [OVERLAY]
- **Edvaldo** waits for the delegation to cross the bridge and **joins it wearing a Reader's face** (see Scene 3). He walks out with the Avowed and tells Manshoon *exactly* where the Book went. [OVERLAY; MODULE "Final Confrontation" offers the same doppelganger-swap move]
- **The Book keeps talking to Daz.** Each untrusted "fact" it gives him is one more reason the Readers think Daz is compromised. [OVERLAY]
- **The crystals** get confiscated as Candlekeep property "pending a Keeper," and nobody alive is known to know how to play them (see Scene 2). [MODULE "Echoes of Alaundo"; OVERLAY consequence]

## The Clever Play (what the optimal party would do; the GM should know this)

1. **Drop the illusion themselves before the Readers arrive.** Being caught concealing it is far worse than declaring it.
2. **Call Miirym as witness first.** She saw Zalthir throw the simulacrum and Edvaldo smash the crystals, and she knows the door was opened by a verified Reader. She also offered "is everyone who they claim to be" as a boon. **Asking her that now unmasks Edvaldo.** [TABLE ch68 068.04]
3. **Give Kalan his three proofs:** Miirym's testimony, the owlbear (or the shards and the owlbear-bone debris), and the party's own testimony, ideally *volunteered* under Kei's *zone of truth*. Gyrgum's monograph habit is the right tool here.
4. **Separate the questions.** The crystals are Alaundo's legacy and Candlekeep's to keep, but Gyrgum can ask to be *present* when they are played. The Book is a hazard, and the party argues for a *custody* role, not ownership. The keys: the party holds **both real High Tower keys**, and that is leverage they should *return*, not spend [TABLE party.md "Key ledger"].
5. **Make Daz report what the Book said, in public, before anyone asks.** Tell it all and label it untrustworthy. That turns "Daz is compromised" into "Daz is the only one who has resisted it."
6. **Do not let Sylvira find out from a stranger.** If she is in the delegation, Thorin or Tadric tells her.

---

## Scene 1: The Last Quiet Minutes

### Setup
- **Where:** the Inner Book Chamber, top of the Obsidian Tower, beneath Candlekeep. It is dark, and Dawnbringer is the only light [TABLE ch69 069.07; ch70]. Just outside the door, the warded chamber holds about a hundred glyph-trapped books, the desk, and the velvet tray with its dark and empty sockets [TABLE ch69 069.05].
- **Present:** Daz at the podium, Mage Hand turning pages, the ash illusion up. Gyrgum holds four crystals and has Guiding Bolt readied at the stair. Thorin stands between the stair and the gems. Zalthir is just back from dragging Edvaldo toward the stairs. Glabbagool is with the party.
- **Offstage:** Edvaldo is somewhere below. Miirym is in the cavern, with her curtain about to drop. The Readers are coming down the Great Shaft.
- **Clock:** give this scene **a real-time cap of about 15 minutes**, then the Readers' lanterns appear far above in the shaft. [OVERLAY]

### Approach: the Book keeps talking
The Book has already answered Daz's first question. Pick the actual content **before the session** (see Open Decisions). Whatever you choose, deliver it so it *feels* useful and *smells* wrong.

> GM-only, three options for the content [all OVERLAY. Choose one or none]:
> **(a) True bones, false meat.** It gives Daz *the names of demons*: the very phrase Alaundo's forge prophecy uses about Eldeth ("the names of demons in her mouth") [TABLE ch69 069.04]. The names are real, and the "how to defeat them" attached to each is a ritual that requires the Book. That gives the party corroboration later, when Eldeth returns, and turns it into temptation now.
> **(b) A map with a hole in it.** It says the demon lords are converging, with Demogorgon's hunger turned on Zuggtmoy's wedding [TABLE ch47 Juiblex threat; Zuggtmoy's pending wedding]. Everything checks out against what the party knows, except one location, which is wrong in a way that would put them in Menzoberranzan.
> **(c) It answers the question Daz didn't pick.** It "accidentally" mentions Daz'issin. Then it apologises: "you chose the demons; forgive me." This is a hook, not a fact. It must not resolve his origin.

**Lines the Book can use** [OVERLAY]:
- "You turn my pages without touching me. Prudent. Your mother was prudent too." *(Only if you pick (c). Otherwise cut.)*
- "They are coming down the well. They will want me back on the stone. Ask yourself who taught them to put things on stones."
- "I do not lie, Daz'… Daz. I *select*."

### Branch: if the party drops the illusion and prepares to declare
- **Consequence:** Scene 2 opens as a *briefing*, not a discovery. Kalan's first proof is already satisfied: the party disclosed voluntarily. Shift Teles's opening hostility down one step.

### Branch: if the party tries to hide or stash the Book
- **Touching it** [MODULE "B3. Side Vault" note]: a good creature that touches it makes a DC 18 Charisma save or takes 8d6 necrotic damage. A neutral creature makes the same save with advantage. Daz is chaotic neutral [TABLE party.md], and has *not* touched it yet: he used Mage Hand [TABLE ch70 070.04].
- **Bag of holding:** Mage Hand can lift it in. But **the shrunken T'sarran spy may be in that bag** (unconfirmed) [campaign_state NPC table]. If she is, she spends the session in the dark with the Book. That is GM-only horror and a decision for you.
- **Glabbagool swallows it:** he would, cheerfully, if asked. His alignment is unestablished, so any damage roll is your call. He is already "holding" key #2 inside himself, so he is effectively the party's safe [TABLE campaign_state]. Failure is comedic and material: something in Glabbagool *changes* (a new vocabulary word, a darker googly eye). [OVERLAY]
- **Carrying it from the room:** the module puts a *suggestion* glyph on **B2's** books ("Put the book back, leave the Vault of Secrets, and forget its location!", DC 17 Wisdom) that triggers when a tome is carried 30+ ft from the shelf [MODULE "B2. The Vault"]. The Book sits in **B3**, and the module doesn't say whether the glyph covers it. **GM decision.** If you apply it, the failure is losing the memory of the Vault's location, not taking damage.

### Branch: if the party goes hunting Edvaldo now
Edvaldo hides in the owlbear wreckage or under the bridge lip as the curtain drops. Zalthir can find him, but that splits the party right as the Readers arrive, and **the Readers meet whoever is at the top of the tower first**. Go straight to Scene 3's "caught early" variant. [OVERLAY]

### NPC notes
- **The Book.** *Wants:* to leave this room in someone's hands, anyone's. *Tic:* speaks only when Daz is about to stop reading. *From this scene:* a second question.
- **Glabbagool.** *Wants:* to help, and to be told he helped. *Tic:* "Is this an instant-death trap? You told me to say." *From this scene:* a job. [TABLE ch69 standing order]
- **Dawnbringer.** *Wants:* the Book *out of her light*. *Tic:* her glow dims every time a page turns. *From this scene:* for Thorin to say no to something. [OVERLAY behaviour on TABLE personality]

---

## Scene 2: The Custody Hearing at the Top of the Tower

### Setup
- **When:** minutes after Ch70's end. The FR date is a few days after Deadwinter. **Exact day: your call.** [TABLE ch57 Deadwinter; date OVERLAY]
- **How they arrive:** down the Great Shaft (about 1,000 ft, with the free-fall section), across the Mechanus-tool bridge, past the owlbear. **The route is your call.** [TABLE ch68–69]
- **Recommended delegation** [OVERLAY, pick from the cast pool]: **Kalan** leads it as Head of the Avowed. With him come **Kei Tigersteel** as arbiter, **Fheminor** and **Teles** as the two succession candidates (neither will let the other arrive alone), **Tadric** as escort, and **two unnamed Watchers**. Leave **Sylvira** and **Kazryn** upstairs unless you want Scene 2's optional landmine.
- **Light:** the Watchers carry *continual flame* lanterns. The B3 chamber in the module has continual-flame torches that "light only the corners"; the darkness radiates from the Book itself [MODULE "B3. Side Vault"]. The Readers' light doesn't penetrate the centre of the room, and Dawnbringer's does. *Stage direction:* the only thing that lets the Readers see the Book is the dwarf's sword.

### Approach: the first look
The Readers' first sight is what Scene 1 left them. Read the room, then **let Kalan speak first, and badly**:

> "Nobody. Moves. Nobody touches anything. This is a scene. Gadzooks. *Two* of them?" *(the shards)*

**Teles** goes straight to the shelves. He is not looking at the party. He is looking at the hundred books he has been forbidden for forty years. [OVERLAY]
**Fheminor** goes straight to the empty sockets in the velvet tray and counts. [OVERLAY]
**Kei** goes straight to the Book. Then he stops and does not cross the threshold. [OVERLAY]

### The Threefold Proof (the scene's actual engine)
Kalan wants three *independent* channels for each claim [TABLE dossier "Personality": Threefold Proof]. Give the players the structure out loud. They love a framework they can game.

| Claim | Channel 1 | Channel 2 | Channel 3 |
|---|---|---|---|
| "Edvaldo smashed the crystals" | Party testimony | Miirym (bound witness) | Physical: shards plus owlbear-bone debris (Edvaldo threw a piece of the dead owlbear) [TABLE ch70 070.03] |
| "The door was opened lawfully" | Gyrgum's verification by Miirym [TABLE ch68 068.04] | The door itself: it opens only to a verified Reader's sincere answer | The owlbear's riddles [TABLE ch68] |
| "Daz is not corrupted" | Kei's *zone of truth* [MODULE ch5 "Restoring Calm"] | Dawnbringer's judgement (Daral will *insist* she counts as a witness, if he is present) | Daz's own disclosure of what the Book said |

### Branch: if the party calls Miirym
She comes, coughing, with lava through her ribs [TABLE ch68]. She will testify to what she saw and **nothing she didn't**: she is "witness, not weapon". If anyone asks the identity question ("is everyone here who they claim to be?"), go to **Scene 3, "unmasked"**. [OVERLAY staging on TABLE character]
> GM-only: the module says she can be summoned to the surface **only by a legitimate Keeper of Tomes** [MODULE "Players vs. Manshoon"]. Down here she is in her own domain. Use the line anyway: "When there is a Keeper again, I will tell them what you did here." Whoever *becomes* Keeper will hear her account.

### Branch: if the party claims the Book
- **Teles** (archmage, passed over) argues *for study*. *Interiority* [OVERLAY]: he thinks Janussi's caution is why Candlekeep was breached at all, and a Keeper who *understood* the Book would have seen Manshoon coming. He is not evil. He is twenty years of resentment wearing an argument. He will offer the party a *joint* custody that happens to put him in the room.
- **Fheminor** argues for *the Keeper's will*: put it back on the stone and seal the door [MODULE "Restoring Calm": she wants the previous Keeper's will honoured]. *Interiority* [OVERLAY]: she was the intended successor, and if the Book leaves on her first day, her whole tenure is "the Keeper who lost the Book."
- **Kalan** wants procedure, not an outcome. He will accept *any* disposition that has three proofs and a report attached.
- **Kei** sides with whoever accepts *zone of truth*. *Interiority* [OVERLAY]: he is the only person in the room thinking about Oghma rather than politics, and he is quietly appalled that the god of knowledge's library has *this* in its basement.
- **The material cost of winning:** the Book leaves with the party only if someone signs for it. The likely price is the Watchers' badges (deputisation suspended "pending report"), or the High Tower keys, or a promise that the Book goes to a named place (Gauntlgrym's forge? a Bahamut temple?). **The party loses a title, not hit points.** [OVERLAY]

### Branch: if the party surrenders the Book
The Readers have to put it back without touching it. *Nobody in the delegation is willing to touch it.* So they ask Daz to Mage Hand it back onto the stone, which makes him the only person who has ever handled it. The Book has the last word as it goes down: "We'll speak again. You still have a question left." [OVERLAY]

### Branch: if the party demands the crystals
> GM-only [MODULE "House of Alaundo / The Echoes of Alaundo"]: only **the First Reader and the Keeper** know how to "coax forth" an Echo. **Both are dead** [TABLE ch57, ch63]. Nobody alive is *known* to be able to play the four crystals. The one forge echo played *by itself* [TABLE ch69 069.04].
- This is the fair compromise: Candlekeep keeps the crystals, and Gyrgum is named to the committee that tries to coax them. That gives Gyrgum his "personal assignment" thread [TABLE party.md] at no cost to the scope rule.
- **Inda** (module, House of Alaundo, a secret Alaundo worshipper) can be *named* as the person who might know how. She does **not** walk on tonight. [MODULE inventory]

### Branch (optional landmine): Sylvira is in the delegation
She is ill and leaning on a Watcher. She thanks Thorin again for saving Tadric [TABLE ch67]. Tadric looks at the party. *Stage direction: do not make Sylvira ask. Make Tadric's silence the clock.* If nobody tells her, she learns from a Watcher's careless line ("…like the Beast in the Rotunda"), and the party loses her trust for good. If Thorin tells her, see the stage directions. [OVERLAY]

### The keys
The party holds **both real High Tower keys**: Gyrgum has key #1, Glabbagool has key #2. They also hold the fake and the sapphire [TABLE party.md "Key ledger"]. The module calls the two keyholders the "Keepers of Secrets," meaning the Keeper of Tomes and the Gatewarden [MODULE "High Tower Library"]. Kalan *is* the Gatewarden, so **one key is arguably his by office.** Returning them unprompted is the single best reputation move available tonight. Holding them is leverage, and the Readers will know it. [OVERLAY analysis]

### NPC notes
- **Kalan Strongbranch.** *Wants:* a report with his method's name on it. *Tic:* "Gadzooks", and counting things on three fingers. *From this scene:* to be the man who *processed* the Vault, since he wasn't the man who found it. [TABLE dossier; OVERLAY motive]
- **Teles Ahvoste.** *Wants:* access to the shelves. *Tic:* talks to the books, not to the people. *From this scene:* to be seen as the scholar who understood the find. [OVERLAY]
- **Fheminor Scrivenbark.** *Wants:* the Keeper's will honoured, and to be that Keeper. *Tic:* counts things (sockets, people, exits). *From this scene:* the Book back on its stone, under her seal. [MODULE motive; OVERLAY tic]
- **Kei Tigersteel.** *Wants:* the truth spoken aloud in a holy place. *Tic:* he will not cross the threshold of B3. *From this scene:* to cast *zone of truth* and have someone *step into it*. [MODULE role; OVERLAY tic]
- **Tadric.** *Wants:* the party to be OK, and Sylvira told. *Tic:* stares at things he is afraid will come alive (it was a candle last time) [TABLE ch58]. *Tonight it is the Book.* *From this scene:* to stand next to Gyrgum. [TABLE; OVERLAY]
- **Miirym.** *Wants:* to be relieved of this duty. *Tic:* grouchy, and repeats the things she approves of ("Well chosen."). *From this scene:* to say what she saw, once. [TABLE ch68]
- **The Iron Owlbear.** *Wants:* entertainment. *Line:* "Better than the *last* lot." [TABLE ch69 voice]

---

## Scene 3: Edvaldo's Last Card

### Setup
Edvaldo cannot go back to Manshoon empty-handed, and both of his remaining exits are bad [TABLE ch70 070.03: "his master does not tolerate failure"]. He believes the Book is ash, because Daz's illusion fooled him [TABLE ch70 070.04], **unless** the party dropped the illusion in Scene 1 within his earshot. Decide where he is the moment the delegation crosses the bridge.

> GM-only [all OVERLAY, built on TABLE ability and MODULE precedent]: the module's own Manshoon plan includes a doppelganger switched in for **Fembris Lancer**, using a sending stone to report the party's location [MODULE "Players vs. Manshoon", "Final Confrontation"]. Edvaldo is that doppelganger by another name. **His move tonight is to become one of the two unnamed Watchers in the delegation.** Is a real Watcher dead or unconscious in the shaft? Your call.

### Variant A: unmasked
If anyone asks Miirym the identity question, or if Kei's *zone of truth* is cast on "everyone present", Edvaldo is exposed in front of the Avowed. That is the party's **third proof for free**: the delegation sees what the party fought. He runs for the far bridge, toward the module's one-way exit tunnel [MODULE "Returning to the Surface"]. **Recommendation:** let Zalthir catch him if Zalthir wants to. If Zalthir doesn't, he gets away, and the Manshoon clock ticks forward one notch.

### Variant B: undetected
He stays a Watcher, is "first to volunteer" to escort the Book or the crystals, and asks one odd question: "Which of you carries the keys?" *(He's still working.)* If nobody catches him, he walks out with the delegation, and **the real Manshoon learns exactly how custody was settled.** That outcome is fine. It turns Manshoon's revenge into a known clock for the next session.

### Variant C: caught early (the party hunted him in Scene 1)
A grapple under the bridge lip as the Readers' lanterns come down the shaft. The Readers arrive to find **Zalthir holding a halfling over the lava**. It looks *terrible*. Kalan: "Is that… a Reader?" The party now has to prove a doppelganger is a doppelganger *before* proving anything else.

### What Edvaldo knows, if he talks
> GM-only: the summaries establish only that he served Manshoon and that a decade of planning (Alkrist, the wards, "an intended army") collapsed [TABLE ch70 070.03]. **Whether a real Edvaldo Sedanur exists (dead, imprisoned, or on sabbatical) is unestablished.** That makes it a GM decision, and a good one: the Readers may *know* the real Edvaldo.

### NPC notes
- **Edvaldo.** *Wants:* not to die, and not to go back empty-handed. Those wants conflict. *Tic:* academic self-interest under pressure ("second author on the paper") [TABLE ch69 069.04]. *From this scene:* one fact for Manshoon, or one deal with the party (his life for the name of the real Edvaldo's fate?). [OVERLAY]

---

## Scene 4 (optional): The Walk Out

- **The route:** the module's exit is the far bridge, then a ten-minute tunnel, then a **reverse-gravity well** with a feather-fall zone at the top, then a one-way *wall of force*, then a hidden door into a disused Candlekeep outhouse or turret [MODULE ch5 "Returning to the Surface"]. Climbing the 1,000 ft shaft is possible only for "the most talented climbers," and Candlekeep's flying wards still apply underground [MODULE same].
  > GM-only: the wards are *broken* at the table [TABLE ch65]. Whether flight works down here now is your call. Zalthir's Draconic Flight and the Potion of Flying both care.
- **The module's "Final Confrontation":** it assumes Manshoon's simulacrum is waiting at the exit with henchmen [MODULE ch5]. **At the table both simulacra are destroyed** [TABLE ch69, ch70]. Don't run it. If Edvaldo escaped in Variant B, it becomes a *next-session* threat. **Do not pull it forward.**
- **The B4 "self-destruct" lever:** the module puts a lever in the tower's attic that drops the tower into the lava [MODULE "B4. The Attic"]. **Nobody at the table has found the attic.** Mention it only if a player asks "is there anything above us?" If you reveal it, the Readers will *want* to know it exists. If you don't, it's a gun on the wall for later. **GM decision.**
- **Spanner's tools:** the bridge was extended with them [TABLE ch68]. Someone has to retract it, or leave it extended, and Spanner will ask which. A quiet reminder that the Mechanus debt is still open [TABLE campaign_state Open Thread 6].

---

## Anticipated player questions

- **"Can we just take the Book and go?"** → Physically, maybe. The Readers can't stop four level-9 heroes in a cavern. But Miirym watches, and she *will* tell the next Keeper [OVERLAY]. The cost is Candlekeep: the badges, the library, Philemon's therapy for Dawnbringer, Spanner, and Gyrgum's school. Leave the path open and make the price visible.
- **"Can Gyrgum Raise Dead / restore the prophecies?"** → The crystals are objects, not people. Nothing in the docs says they can be restored. **Not answered:** whether *mending* or *wish* would work. GM decision. Say "the light is gone out of them" and let that stand.
- **"What did the Book actually tell Daz?"** → Whatever you picked in Open Decisions. **Not answered:** whether it is *true*. That stays unanswered all session.
- **"Can we destroy it? Throw it in the lava like Manshoon?"** → *Daz knows* it cannot be permanently destroyed while evil exists [TABLE ch70 070.04]. The module agrees that lava "would not technically be enough", though it would make the Book inaccessible [MODULE "Rocket Alternative"]. So throwing it in is *sealing* it, not *destroying* it. If they do it, it is gone for now, and the Book should say something as it falls.
- **"Who's in charge here now?"** → Kalan, by office, as Head of the Avowed and Gatewarden. The Keeper of Tomes seat is empty. **Not answered tonight:** who gets it.
- **"Did killing the simulacrum trip a dead-man switch?"** → Unknown to everyone. Let a Reader *also* worry about it. **Not answered.**
- **"Where's the Staff of Power?"** → Not recorded [campaign_state Open Thread 4]. **GM decision before play.**
- **"Can Miirym check who everyone is?"** → She offered exactly that boon once [TABLE ch68]. Whether she'll grant it *again*, unbanked, is your call. My recommendation is yes, at a cost: she has to look *at* Daz too, and say aloud what she sees. [OVERLAY]

## Stage directions (timing and silence cues)

- **When the Readers' lanterns first appear far above in the shaft, stop talking.** Let the players hear them coming. Count it down in lanterns, not minutes.
- **When Kei stops at the threshold and won't enter, hold the beat.** The holiest man in Candlekeep is afraid of the room the party is standing in.
- **When Daz's illusion is seen through (by anyone), don't narrate a reaction for a full second.** Let the players feel caught.
- **When Dawnbringer's light falls on the Book,** describe the light *bending away from it*, once only. Don't repeat it.
- **If Thorin tells Sylvira about Moziqodo, don't fill the silence.** She says nothing for a long time. Then: "Thank you for telling me yourself." [OVERLAY]
- **If Edvaldo is unmasked in front of the delegation,** let Kalan finish counting on his fingers before anyone else reacts: "…three."
- **The Book's last line of the session should be the session's last line.**

## Open decisions (for the GM; I have not decided these)

1. **What the Book told Daz.** The summaries explicitly defer it "to be resolved when the party reconvenes" [TABLE ch70 070.04]. Pick (a), (b), (c) from Scene 1 or your own.
2. **Who is in the delegation.** The docs say only "surviving Avowed Readers." Kalan's presence, Sylvira's, and Kazryn's are all unconfirmed.
3. **Kazryn Nyantani's lover.** The table (Sylvira's testimony) says *Janussi's* former lover [TABLE ch61 061.05]. The module says *A'lai's* lover [MODULE inventory]. If she's on stage, which is true matters: A'lai is the imprisoned traitor.
4. **Exact timing of Miirym's curtain dropping.** Six of ten minutes were gone at Ch70's start. The docs don't say how long Ch70's events took.
5. **Does B2's *suggestion* glyph apply to the Book in B3?** The module doesn't say.
6. **Where the shrunken T'sarran spy is.** It is unconfirmed whether she is in the bag of holding or a Candlekeep cell [campaign_state]. This matters if the Book goes into the bag.
7. **Staff of Power:** did it go into the lava with simulacrum #2, or is it still upstairs? Not recorded.
8. **Was there a real Edvaldo Sedanur?** Unestablished.
9. **A third Manshoon simulacrum?** `docs/npcs/manshoon.md` says "a third simulacrum remains concealed in the vault" [citing ch68 068.05]. **The ch68 summary actually says a *second* simulacrum was concealed**, and that is the one met in ch69. I believe the dossier is wrong and **there is no evidence for a third**. Rule on it before anyone at the table reads the dossier as canon.
10. **Riddle-line bookkeeping from ch68:** whether cryptogram lines 3 and 6 are closed "needs a GM call — the Manshoon Track reductions and the obsidian door both key off it" [TABLE ch68 068.04 note]. The door is now open. The Manshoon Track is still affected.
11. **Does Kalan, as Gatewarden and a "Keeper of Secrets", already know the Vault exists?** The module implies the two keyholders do [MODULE "High Tower Library"]. At the table he needed the cryptogram like everyone else [TABLE ch67]. If he knew, he lied.
12. **Has the Endless Chant resumed?** It has been silent since ch64, with no recorded restart.
13. **Does flight work underground now that the wards are broken?** This matters for the walk out.
14. **Alignment of Glabbagool,** if he is asked to swallow the Book (the module's touch damage keys off alignment).
15. **FR date stamp** for the session. The docs place it shortly after Deadwinter but give no day count.
