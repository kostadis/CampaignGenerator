# Feature Specification: Player Entity & Config Service

**Feature Branch**: `009-player-entity-service`

**Created**: 2026-08-15

**Status**: Draft

**Input**: User description: "Currently there is no player entity. I want a player
entity. That player entity should contain the player name and any data that uses
player information should render from that entity. CG#314 describes the scope of the
issue. I want a UI page that allows me to configure the player information and stores
it as a yaml. The information is a new config service that all others services use to
get the information about the players. The issue is described in CG#314. Use the
codememory-mcp to understand the code. Also look at previous issues to see if there
are any cases where this is not adequately handled."

**Clarifications resolved (2026-08-15)**:

1. **Scope reaches all the way into routing.** The feature covers player-scoped data
   *and* the character-scoped routing that fails alongside it: `session_doc.yaml`'s
   second hand-typed roster is retired, and each character explicitly declares its
   voice file and its example file instead of being matched to one by a first-name
   prefix. This kills the last similarity-based identity assertion in the codebase —
   the one that just failed (campaigns#175, #315).
2. **Per-campaign, with a stable person identifier.** One player document per
   campaign, matching every sibling config service. Each player carries an identifier
   that is the same string across campaigns, so a future cross-campaign view is a read
   over six files rather than a fifteenth store.
3. **The player entity owns the binding.** `players.yaml` records which characters
   each player plays; `party.yaml` **drops its `player:` field entirely** and goes back
   to being "character → its files".

---

## Context — what exists today *(evidence, not proposal)*

`docs/design/PlayerIdentity.md` (merged as CG#314) is the survey behind this spec.
Its findings are the premises here and are not re-derived:

- A player — the human at the table — is **not modelled anywhere**. What exists is
  **five join keys across fourteen stores**, none of which names the others.
- Four different things are routinely called "identity": the **person**, their
  **display name in the recording** (per-session, drifts without warning), the
  **character** they play, and the **sheet** (D&D Beyond's own record, carrying a
  numeric ID that nothing reads).
- `config/party.yaml`'s `player:` field is documented as holding the *display name*
  but is rendered into prompts as a *person's name*. One field, two jobs.
- That field has **exactly one production reader** — the sheet converter. Every
  downstream consumer reads the *sheet's* frontmatter instead, so editing the roster
  changes nothing until that character's PDF is converted again, and nothing compares
  the two.
- **Everything that fails loudly is a path or an exact-match refusal. Everything that
  fails silently is a name approximately matched.** That is the finding the whole
  feature turns on, and it is why ruling 1 above puts the routing rules in scope: a
  declared file is a path, and a path fails loudly.
- One campaign is broken right now and nothing reports it (the `Gyrgum` rename,
  campaigns#175/#176). The obvious one-line repair made it *worse*, converting a
  silent drop into a silent bleed, and the detector added for that exact bleed
  (#301) reported nothing in any of the three measured scenarios (#315).

Related issues that record the same failure class from other angles:

| Issue | What it shows |
|---|---|
| #129 (open) | Fragmented entity identity — 4+ hand-curated stores, none generated from another. The accepted fix shape is *one authored source → generated projections + a `check`*. |
| #260 (closed) | Two parsers over one file drifted; the player→character map parsed **empty for 3 of 6 campaigns**, so real player names reached the extractor as speaker labels. |
| #248 (closed) | The roster parser and the player-map parser covered different layout sets of the same document. |
| #247, #300, #301 (closed) | Three separate defects in voice-file and example-file delivery, all of them consequences of resolving a file by a name prefix rather than by a declaration. |
| #293 (open) | 15 sheets on disk, **0 with frontmatter**, so the sheet-sourced roster path is shipped and unexercised. toee's four sheets record the D&D Beyond *account handle* as the player. |
| #312 (open) | The D&D Beyond numeric ID is on disk in eight filenames and read by nothing. |
| #315 (open) | The bleed detector cannot see a rename. |
| #122 (open) | "Too many ad-hoc files and mechanisms" for identity tracking. |

The precedent to copy is `docs/entity_registry.yaml`: one authored authority,
generated projections, a `check` that reports drift for human review. The precedent
to avoid is `narrate.genre`: a config field holding a copy of something a file owns,
synced one way, which took three copies and two fixes to unwind.

---

## Clarifications

### Session 2026-08-15

- Q: When one person both runs the game and plays a character, what does transcript speaker normalisation label their lines? → A: Always the game-master label. One person, one label, regardless of who they were voicing.
- Q: What form does a player's stable identifier take, and who produces it? → A: A short slug the GM authors. Required, unique within a campaign, reused verbatim across campaigns for the same person.
- Q: How is campaign-wide example material declared, now that the filename convention is being deleted? → A: Two explicit declarations. A character names its own example file; the campaign holds a separate list of shared example files. Anything undeclared is unused.
- Q: What happens when two players in a campaign record the same display name? → A: Refuse at save. A display name belongs to at most one player; a duplicate is rejected, naming both players and the shared value.
- Q: What happens to a player who leaves the campaign while their character remains in the historical corpus? → A: Mark inactive, never delete. Their display names still resolve for archived transcripts; the prompt roster and the check treat them as no longer at the table.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Say who is at the table, once (Priority: P1)

The GM opens a Players page in the web UI and sees one row per human at the table.
Each row records that person's name, every display name the recording software has
ever labelled them with, the character or characters they play in this campaign,
whether they run the game, and their D&D Beyond identity. The GM adds a player,
corrects a spelling, records a second display name a player started using three
sessions ago, and saves. The information persists to a document the GM can also open
and hand-edit.

**Why this priority**: There is nowhere to write this down today. Everything else in
this feature depends on a place to put it, and even with no consumer wired up, a
single legible answer to "who plays whom, and what does the recording call them" is
worth having on its own — it is the fact the GM currently reconstructs from four
files.

**Independent Test**: Open the page on a campaign with no player document, add three
players with characters and display names, reload the page, confirm the values came
back. Open the file on disk and confirm it is readable and hand-editable. Break the
file by hand and confirm the page reports what is wrong and which entry, rather than
loading part of it.

**Acceptance Scenarios**:

1. **Given** a campaign with no player document, **When** the GM opens the Players
   page, **Then** an empty roster is shown and the page is usable — not an error.
2. **Given** a player recorded with the display names `Wade` and `Wade Brown`,
   **When** the GM saves, **Then** both survive a reload, in the order authored.
3. **Given** the GM binds a player to a character name that is not in the campaign
   roster, **When** they save, **Then** the save succeeds and the page reports the
   unresolved binding — the GM must be able to name a character they are about to add.
4. **Given** a hand-edited document with an unknown field, **When** the page loads,
   **Then** the field is reported by name and the load refuses, rather than the value
   being silently dropped.
5. **Given** a player who runs the game and also plays a character, **When** the GM
   records both, **Then** the document accepts it.
6. **Given** two campaigns in which the same human appears, **When** the GM types the
   same identifier slug in both, **Then** each campaign's document still stands alone and
   neither depends on the other being present.
7. **Given** the GM enters an identifier already used by another player in the same
   campaign, **When** they save, **Then** the save is refused and both entries are named.
8. **Given** the GM records a display name already listed under a different player,
   **When** they save, **Then** the save is refused, naming both players and the shared
   value.
9. **Given** a player who has left the campaign, **When** the GM marks them inactive,
   **Then** they remain in the document with their display names and bindings intact, and
   the page shows them as no longer at the table.

---

### User Story 2 - Every consumer of player information reads the entity (Priority: P2)

The GM corrects a player's display name in one place. On the next run, the speaker
labels in the transcript resolve to the right character, the roster block in the
narration prompt names the right person, and the GM's own lines are attributed to the
GM — with no other file edited, and without re-converting anybody's character sheet.

**Why this priority**: This is the user's headline ask, and it is what makes the
entity a *source* rather than a fifteenth store. It is second only because it needs
somewhere to read from.

**Independent Test**: Change one player's display name in the entity. Without touching
any other file, run the speaker-normalisation step over a transcript that uses the new
label and confirm that player's lines are attributed to their character. Confirm the
same change reaches the prompt roster line and needs no sheet conversion.

**Acceptance Scenarios**:

1. **Given** a player with two recorded display names, **When** a transcript uses
   either one, **Then** that player's lines resolve to their character.
2. **Given** the entity names who runs the game, **When** a transcript is normalised,
   **Then** the GM's lines are labelled as the GM, sourced from the same entity as
   everyone else — not from a separate field in another document.
2a. **Given** a person recorded as both running the game and playing a character,
   **When** a transcript is normalised, **Then** every one of their lines carries the
   game-master label and none carries the character's name.
3. **Given** a character with no player bound to it, **When** a run starts, **Then**
   the run names that character and refuses, rather than proceeding with a partial map.
4. **Given** a display name that is a strict prefix of another player's display name,
   **When** a transcript is normalised, **Then** the longer label wins and neither
   player's lines are misattributed.
5. **Given** a sheet conversion, **When** it stamps the player into the produced sheet,
   **Then** the value comes from the entity, and the sheet's copy is never read back as
   the authority.
6. **Given** a `party.yaml` that still carries a `player:` field, **When** anything
   loads it, **Then** the field is reported as retired and refused — not accepted as a
   second opinion.

---

### User Story 3 - A character's voice and examples arrive because it named them (Priority: P3)

The campaign roster gains two more file references per character, alongside the sheet
and backstory it already names: the character's voice specification and its style
examples. A render resolves them the same way it resolves the sheet — by following a
declared path — so a missing file is reported before the run starts and a renamed
character cannot silently lose its register rules.

**Why this priority**: This is the failure that is live in a campaign right now, and
it has already defeated three separate detectors. It is P3 rather than P1 because it
needs the roster to be the settled authority first; once it lands, an entire class of
silent failure becomes a missing-file report.

**Independent Test**: Replay the out-of-the-abyss state — roster says `Gyrgum`, files
are named `grygum` — and confirm the run refuses before the first API call, naming
both the character and the path it could not find. Confirm that no file reaches a
narrator it was not declared for, in a campaign whose example files are genuinely
shared house style.

**Acceptance Scenarios**:

1. **Given** a character that declares a voice file which does not exist, **When** a
   render starts, **Then** it refuses and names the character and the path.
2. **Given** a character that declares no example file, **When** a render runs,
   **Then** that narrator receives no per-character examples and this is stated, not
   inferred.
3. **Given** a campaign whose example files are shared house style, listed in the
   campaign's shared-examples declaration, **When** a render runs, **Then** they reach
   every narrator as intended and nothing is reported as mis-routed.
3a. **Given** an example file that neither a character nor the shared list declares,
   **When** a render runs, **Then** it reaches no narrator, and the check names it as an
   orphan.
4. **Given** a character renamed in the roster while its files keep the old names,
   **When** a render starts, **Then** it refuses — the case that is silent today in
   all three of its variants.
5. **Given** the campaign roster, **When** the narration pipeline needs the list of
   characters, **Then** it derives that list from the roster; a second hand-typed
   character list no longer exists anywhere.

---

### User Story 4 - Adopt six existing campaigns without retyping them (Priority: P4)

The GM runs a one-shot adoption step per campaign. It reads what the campaign already
records about its players across the existing stores, builds a first draft of the
player roster, and **reports every disagreement it found instead of choosing between
them**. The GM rules on each conflict and saves. Nothing is overwritten without an
explicit instruction.

**Why this priority**: Six campaigns, roughly two dozen people, and the existing values
genuinely disagree — toee's four sheets record an account handle where `party.md` has
the real names (#293), and out-of-the-abyss's stores disagree about a character's
spelling (campaigns#175). Adoption is worth automating precisely because the conflicts
are the interesting part; it is P4 because the roster is small enough to type by hand
if this slips.

**Independent Test**: Run adoption against a campaign whose stores are known to
disagree; confirm every disagreement is listed with both values and their sources, and
that nothing was silently picked. Run it twice and confirm the second run refuses to
clobber the first result without an explicit override.

**Acceptance Scenarios**:

1. **Given** a campaign whose stores disagree about a player's name, **When** adoption
   runs, **Then** both values and their sources are reported and neither is written as
   settled.
2. **Given** an existing player document, **When** adoption runs again, **Then** it
   refuses to overwrite without an explicit override.
3. **Given** a store holding a placeholder value (`(Not specified)`, `N/A`), **When**
   adoption runs, **Then** it is recorded as "no display name", not as a person named
   "N/A".
4. **Given** adoption has completed and the GM has ruled, **When** the retired fields
   are removed, **Then** nothing still reads them and no second location remains that
   would load.

---

### User Story 5 - Drift is reported before a run, not discovered after it (Priority: P5)

Before spending a token, the GM asks the system whether the player information is
coherent. It answers with a list: a character nobody plays, a player bound to a
character that does not exist, a declared file that is not there, a recorded display
name that appears nowhere in the session's transcript.

**Why this priority**: Every failure this feature exists to fix is currently silent. A
check turns the whole class from "discovered at the table" into "reported before the
run". It is last because the earlier stories remove most of the drift by removing the
duplicate stores and turning name matches into declared paths; the check catches what
remains and answers the question ahead of a run rather than during one.

**Independent Test**: Replay the out-of-the-abyss `Gyrgum` state and confirm the check
names it. Point a campaign at a transcript from a different campaign and confirm the
check reports which expected display names are absent — including the case where three
of four match and one does not.

**Acceptance Scenarios**:

1. **Given** a character in the campaign roster whom no player is bound to, **When**
   the check runs, **Then** that character is named.
2. **Given** a transcript in which one of four expected display names never appears,
   **When** the check runs against it, **Then** that one is named — the existing
   whole-transcript pre-flight only fires when *zero* match.
3. **Given** a coherent campaign, **When** the check runs, **Then** it reports nothing
   and spends no tokens.

---

### Edge Cases

- **One human, two characters in the same campaign.** The binding is
  one-player-to-many-characters, not one-to-one.
- **Two humans, one character** (a co-piloted PC). Today's stores already split a
  player field on `/` and `,` to express this, so the entity must express it too.
- **The GM also plays a character.** toee's `Calmer` is a GM-played PC, so "runs the
  game" and "plays a character" are independent facts about one person. Both are
  recordable; for speaker labelling the game-master label wins (FR-021a).
- **Two players share a first name.** No inference may collapse them.
- **Two players record the same display name.** Refused at save (FR-005b) — it is not a
  configuration the document can hold.
- **One display name is a strict prefix of another** (`Mike` / `Mike Hall`).
- **A display name changes mid-campaign.** Phandalin's Wade went from `Wade` to
  `Wade Brown` between recordings, so the back-catalogue of transcripts needs the old
  label to keep working.
- **A player has no display name at all.** Hillsfar records a placeholder for all four
  characters; that is a legitimate state, not an error.
- **A display name collides with an NPC's name, or with the literal label used for the
  GM.**
- **A character is renamed.** This is the case that broke out-of-the-abyss and the one
  the existing detector cannot see.
- **Two characters declare the same voice file, or the same example file.** Legitimate
  (two siblings sharing a register) — a declaration makes it explicit rather than
  ambiguous.
- **An example file that belongs to nobody**, such as toee's
  `combat_and_consequences.md`. Shared house style is a real configuration; after
  declarations arrive it lives in the campaign-level shared list (FR-030).
- **An example or voice file nothing declares.** It is unused, not shared — and the
  check names it (FR-030a, FR-030b). This is what a character rename produces.
- **The player document names a character the campaign roster does not have, and vice
  versa.** Both directions must be reported.
- **The same person identifier appears in two campaigns with different display names**
  — which is the normal case, not an error.
- **The document is absent, empty, or hand-broken.**
- **A player leaves the campaign** but their character remains throughout the
  historical corpus. Marked inactive, never deleted (FR-011a) — their display names must
  keep resolving for the back catalogue of transcripts.
- **Every player bound to a character is inactive.** The character is historical, not
  broken; the check stays quiet about it.

## Requirements *(mandatory)*

### Functional Requirements

#### The entity and its document

- **FR-001**: The system MUST model a **player** as a first-class entity with: a stable
  identifier; the person's name; zero or more recorded display names; zero or more
  bindings to characters in this campaign; an optional D&D Beyond identity; a flag for
  whether this person runs the game; and a flag for whether they are still at the table.
- **FR-002**: The person's name and the display names MUST be **separate fields**. They
  are two different facts about one person, used for two different jobs — one is
  rendered into prompts, the other is matched against transcript speaker labels — and
  conflating them is the defect this feature exists to remove.
- **FR-003**: Display names MUST be a **list**, ordered as authored, because a person's
  label in the recording drifts between sessions while the configuration is per
  campaign.
- **FR-004**: The stable identifier MUST be a **short slug authored by the GM**,
  required on every player, and independent of the person's name so that a name can be
  corrected without breaking any reference to that player. It MUST NOT be derived from
  the name, auto-generated, or opaque: a derived key goes stale silently, and an opaque
  one cannot satisfy FR-005 without a shared allocator — a fifteenth store, which is
  what this feature exists to avoid.
- **FR-005**: The identifier MUST be usable as **the same string in every campaign** the
  person appears in. Sameness is achieved by the GM typing the same slug, not by any
  shared registry. Nothing in this feature reads across campaigns; the requirement is
  that a later cross-campaign view needs no new store, only a read over the existing
  per-campaign documents.
- **FR-005a**: An identifier MUST be unique within a campaign's player document. A
  duplicate MUST be refused, naming both entries.
- **FR-005b**: A display name MUST belong to **at most one player** within a campaign. A
  duplicate MUST be refused **at save time**, naming both players and the shared value.
  Two humans cannot share one label in one recording without the transcript itself being
  ambiguous, so this is never a legitimate configuration — and allowing it would leave
  speaker normalisation with two valid answers and no way to choose, which is the silent
  misattribution this feature exists to remove.
- **FR-006**: The player roster MUST be stored in **one document per campaign**, in a
  format the GM can read and hand-edit, and that document MUST be the only place these
  facts are authored.
- **FR-007**: A dedicated service MUST own that document exclusively. Every other
  component MUST obtain player facts through that service and MUST NOT obtain them by
  parsing any other document.
- **FR-008**: The document MUST reject unknown fields, naming the offending field and
  entry, rather than accepting and ignoring them.
- **FR-009**: An absent or empty document MUST read back as "no players recorded", not
  as an error.
- **FR-010**: A save MUST be atomic and MUST preserve values exactly as authored — a
  load/save round-trip may not rewrite, reorder, or normalise what the GM wrote.

#### Who owns what

- **FR-011**: The **player entity owns the character binding**. It records which
  characters each player plays.
- **FR-011a**: A player who leaves the campaign MUST be **marked inactive, not deleted**.
  Deleting them breaks speaker resolution for every archived transcript that still
  carries their label. An inactive player:
  - keeps their display names, which still resolve when an old transcript is processed;
  - keeps their character bindings, so the historical join survives;
  - is **excluded** from the roster block rendered into prompts, which describes the
    table as it is now;
  - does **not** cause the check to report their character as unbound.
- **FR-012**: The campaign roster (`party.yaml`) MUST **lose its player field**. After
  adoption it describes a character and the files belonging to that character, and
  nothing about the human playing it.
- **FR-013**: A campaign roster still carrying the retired player field MUST be
  reported and refused, not accepted as a second opinion.
- **FR-014**: The character sheet remains canonical for character data. This feature
  changes nothing about that ruling; it only removes the *player* from the set of facts
  a sheet is trusted for.

#### The UI page

- **FR-015**: Users MUST be able to view, add, edit, reorder and remove players from a
  page in the web UI, editing the roster as a unit so that row order is preservable in
  a single write.
- **FR-016**: The page MUST show, per player, which characters they are bound to and
  whether each binding resolves to a character in the campaign's roster.
- **FR-017**: The page MUST report an unresolved reference **without refusing the
  save** — the GM must be able to name a character or a file they are about to create.
- **FR-018**: Everything the page can do MUST also be doable at the command line and by
  editing the file, and the file MUST be the interchange between all three (Constitution
  IX). The page MUST NOT hold player state that exists only in the browser.

#### Consumption — rendering from the entity

- **FR-019**: The roster block rendered into generation prompts MUST take the
  **person's name** from the entity, and MUST include only players still at the table
  (FR-011a).
- **FR-020**: Transcript speaker normalisation MUST match against **every** recorded
  display name for a player, not one of them.
- **FR-021**: The label applied to the game master's lines MUST be derived from the
  entity's "runs the game" flag. There MUST NOT be a separate GM-only player field in
  another document.
- **FR-021a**: When one person both runs the game and plays a character, **the
  game-master label always wins**. Every line spoken by that person is labelled as the
  game master, regardless of who they were voicing. A transcript label records who
  spoke, not in what capacity, and labelling that person's lines with their character's
  name would attribute narration and NPC speech to a player character — a false
  attribution, which is the most expensive failure this system can produce. The
  consequence is a real and accepted loss: that person's player-character lines are
  attributed to the game master and are not separable from the label alone.
- **FR-022**: Character-sheet conversion MUST take the player value it stamps into a
  produced sheet from the entity.
- **FR-023**: The value a conversion stamps into a sheet is a **rendered copy, not an
  authority**. No consumer may read player identity back out of a character sheet, and
  no consumer may read it out of a generated document.
- **FR-024**: When the entity cannot answer a consumer's question — no player bound to a
  character, a bound character that does not exist, a missing display name where one is
  required — the consumer MUST report the specific player or character by name and
  refuse, rather than continuing with a partial answer.
- **FR-025**: The system MUST NOT assert that a player or a character is the same as
  another because their names look alike. A binding exists because the GM recorded it.
  This restates the rule `provenance/identity.py` already enforces elsewhere ("`Vera`
  does not resolve to `Veyra` because they look alike") and extends it to the joins that
  predate it.

#### Declared routing — retiring the name-prefix match

- **FR-026**: A character MUST be able to **declare** the file holding its voice
  specification and the file holding its style examples, in the same way it already
  declares its sheet and its backstory.
- **FR-027**: Voice and example files MUST be resolved by following those declarations.
  Resolution by matching a file name against a character's first name MUST be removed,
  not merely supplemented.
- **FR-028**: A declared file that does not exist MUST be reported before the first API
  call of a run, naming the character and the path.
- **FR-029**: A character that declares no voice file, or no example file, MUST be
  treated as having none — stated in the run's output, never inferred from a file that
  happens to share a name.
- **FR-030**: Example material that belongs to the whole campaign rather than to one
  character MUST be declared as **a campaign-level list of shared example files**,
  separate from the per-character declaration of FR-026. The two declarations are what
  distinguish shared material from a character's own — not a file-naming convention.
- **FR-030a**: An example or voice file that no character and no campaign-level list
  declares MUST be **unused**. It reaches no narrator. There is no fall-through by which
  an undeclared file becomes shared material, which is the mechanism behind the #301
  bleed.
- **FR-030b**: The check MUST report a file present in the campaign's voice or examples
  directory that nothing declares, so an orphan is visible rather than silently inert.
  This is the state that a character rename produces, and the state three existing
  detectors cannot see.
- **FR-031**: The second, hand-typed character list in the session-document
  configuration MUST be **removed**. The list of characters a render works with is
  derived from the campaign roster.

#### Adoption and retirement

- **FR-032**: A one-shot adoption step MUST build a first draft of a campaign's player
  roster from what that campaign already records, and MUST **report every conflict it
  finds rather than resolving it**. A conflict is a GM ruling, not a merge rule.
- **FR-033**: Adoption MUST refuse to overwrite an existing player document without an
  explicit override, and MUST report values it did not recognise rather than dropping
  them.
- **FR-034**: Adoption MUST treat the established placeholder vocabulary (`""`,
  `not specified`, `n/a`, `none`, `unknown`, `tbd`, bracketed or not) as "no value
  recorded", never as a person's name.
- **FR-035**: Adoption MUST propose voice and example declarations from the files a
  campaign already has, and MUST report every file it could not attribute to a
  character, so the GM rules on it rather than the tool guessing.
- **FR-036**: Once a campaign is adopted, the retired fields MUST be **removed, not left
  in place as a second location that still loads**. The repo's standing rule is
  migrate-and-delete; a location that still parses is a split brain waiting to happen.
- **FR-037**: A retired location still present in a campaign's configuration MUST be
  reported when encountered, not silently ignored.

#### The check

- **FR-038**: A check MUST be able to report, spending no tokens and calling no model: a
  character in the campaign roster whom no player is bound to; a player bound to a
  character that does not exist; a player with no recorded display name; and any
  declared file that is absent. A character bound only to an **inactive** player is not
  reported as unbound (FR-011a).
- **FR-039**: When given a transcript, the check MUST report each expected display name
  that does not appear in it — including when only one of several is absent. The
  existing pre-flight only fires when *none* match, which is the case that has never
  been the problem.
- **FR-040**: The check MUST be read-only. It reports; it corrects nothing.

### Key Entities

- **Player** — a human at the table. Carries a stable identifier, the person's name, the
  display names a recording has used for them, whether they run the game, the characters
  they play in this campaign, and an optional D&D Beyond identity. The identifier is a
  short slug the GM writes (`ben`, `wade`), required, unique within the campaign, and
  typed the same way in every campaign that person appears in. It exists so a name can be
  corrected without breaking references. A player who leaves is marked inactive rather
  than removed, because the transcript archive still carries their label.
- **Display name** — one exact string that a recording has labelled a player with. A
  player has zero or more, because the label drifts between sessions and old transcripts
  keep the old one. Matched exactly; never approximately. Belongs to at most one player
  in a campaign — a duplicate is refused rather than resolved.
- **Character binding** — the recorded fact that a player plays a particular character in
  this campaign. Many-to-many in principle: one person may play two characters, and one
  character may be co-piloted by two people. Owned by the player entity.
- **Character** — already modelled by the campaign roster, which names the character and
  points at its files. This feature **references** the character, removes the player from
  its record, and adds two more file references to it (voice, examples).
- **Game master** — not a separate entity. A property of a player, because the same
  person may both run the game and play a character.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A GM changes a player's display name in one place and every downstream
  consumer uses the new value on the next run — no second file edited, no character
  sheet re-converted. Today this requires editing two to three locations and re-running a
  PDF conversion.
- **SC-002**: The number of places a player's identity is **authored by hand** drops
  from five to one. Every remaining copy is either generated or read through the service.
- **SC-003**: All six campaigns have a complete player roster after adoption, with every
  conflict presented for a ruling and none resolved automatically.
- **SC-004**: Each of the failure modes recorded as **silent** in
  `docs/design/PlayerIdentity.md` produces a named report before a run starts, in 100% of
  cases: one wrong display name of several; a stale duplicate roster; a character
  reference that resolves to nothing; a voice or example file that no longer matches its
  character.
- **SC-005**: The out-of-the-abyss `Gyrgum` state, replayed, is reported by name and the
  run refuses — the case that three existing detectors all missed, in all three of its
  measured variants (as found, after the obvious partial repair, and after a full
  repair).
- **SC-006**: Zero joins in the player and character-routing path resolve an identity by
  matching a name prefix. Every one of them is an exact match, a declared path, or a
  refusal.
- **SC-007**: A GM can add a new player, record two display names, and bind them to a
  character in under two minutes, without leaving the page and without knowing which file
  it lands in.
- **SC-008**: A campaign that has not been adopted yet, and a campaign that has, both
  behave predictably: the un-adopted one refuses with a message naming what is missing,
  and neither renders quietly from partial information.

## Assumptions

- **The sheet stays canonical for the character; the entity is canonical for the
  person.** `docs/design/PartyRosterCanonicalFormat.md` ruled that the D&D Beyond sheet
  is authoritative for character data. That ruling is untouched. The export stamps the
  *downloader's* name into every sheet, so the sheet was never authoritative about the
  player, and feature 008 already moved that one field to the roster.
- **Single user, no back-compatibility.** Retired fields are deleted after adoption
  rather than kept as fallbacks. Dual-location probes are what produced the live
  split-brain this repo has already had to unwind twice.
- **The service follows the established shape** used by the campaign's other
  configuration services: one strict document it owns exclusively, a routed read/write
  surface, a lenient save that reports unresolved references, and a one-shot adoption
  step that refuses to clobber.
- **The check is deterministic and free.** No model is called, matching the precedent of
  the repo's other verification passes.
- **Declared routing is a data change as well as a code change.** Six campaigns' voice
  and example files must be attributed to characters before the name-prefix rule can be
  deleted. Adoption proposes; the GM rules; the old rule goes only after that.
- **Scope excluded, deliberately:**
  - NPC and world-entity identity. That is `docs/entity_registry.yaml` and issue #129, a
    different bounded context.
  - The corpus-wide spelling correction for a renamed character (campaigns#172) — that is
    a propose/review/apply pass over 1600+ files, two of which are raw transcripts that
    must never be hand-edited.
  - Adopting the D&D Beyond numeric ID as the sheet-attribution key (#312). The entity
    gains a place to record the ID; using it as a join key is a separate change.
  - Migrating the six campaigns' sheets to frontmatter (#293).
  - Any cross-campaign read. FR-005 only requires that the identifier not stand in the
    way of one later.
- **Dependency:** the campaign roster and its path-resolution convention are assumed
  settled — #291 rewrote every campaign's paths campaign-root-relative, so a single base
  directory now works everywhere.
- **Constitution check, stated up front:** the entity is authored by a human and read by
  machines, so no LLM call is added and no precision decision is removed from the GM
  (Principles I and II). Adoption **reports** conflicts rather than resolving them, which
  is the human checkpoint. The check is read-only and model-free. Everything the page does
  is doable at the CLI, and the file is the interchange (Principles VI and IX). Replacing
  a prefix match with a declaration moves a silent inference into an explicit human
  statement, which is Principle II applied to configuration.
