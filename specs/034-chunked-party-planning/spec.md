# Feature Specification: Chunked, Code-Checked Party and Planning Documents

**Feature Branch**: `worktree-034-chunked-party-planning`

**Created**: 2026-10-08

**Status**: Draft

**Input**: User description: "the planning.md and party.md documents are generated from one-shots, unlike world_state.md and campaign_state.md. I would like to change them to use the chunked system that we have built using the summaries as the base. I want the feature to be built in a separate worktree. I want opus to do orchestration and sonnet to do implementation." This feature extends the chunked build of spec 033 (`summary_native extract → synth → annotate → audit`) to the two remaining grounding documents, and builds on summary-native NPC dossiers (spec 032).

## Context

Session prep reads four grounding documents. Spec 033 rebuilt two of them, **world_state** and **campaign_state**, as a chunked build:

- a map step reads the full summaries a few chapters at a time;
- code checks every note before anything uses it;
- code owns the precision sections;
- a model writes only prose, from checked notes, within budgets;
- code annotates stale lines and never rewrites them.

The other two documents still come from the one-shot path of spec 031. Each is a single model call over scene synopses, memorable moments and entity dossiers, plus the GM's config:

- **party** gives each player character's current situation, the party overview and party dynamics, and candidate arc-score events.
- **planning** covers the threat tracker, NPC dossiers, faction states, active plots and DM notes.

The one-shot path for these two has the same three weaknesses spec 033 measured on the other two:

- It sees only synopses, so a fact that lives in a summary bullet is missed.
- It cites a minority of scenes.
- Nothing checks its prose after it is written, so a stale or invented line reaches session prep.

Two more weaknesses are specific to these documents:

- planning's NPC section re-derives each NPC from evidence instead of pointing to the published dossier, so an NPC is described in two places that can disagree.
- planning's "Active Plots" is ordered "most urgent first" by the model, which is a precision decision (ordering) left to a model.

The checked notes spec 033's map step already produces cover most of what these documents need:

- party-situation notes, one line per character per chunk (`- Daz: …`);
- thread changes;
- NPC status rows;
- tagged faction, NPC and threat facts;
- events.

On Out of the Abyss chapters 2–70 the cached notes hold 434 party notes, 564 thread notes, 490 status rows and 941 subject facts. Two measurements on those notes shape this feature.

- **Party notes do not say whose they are in a form code can read.** 258 of 434 have no leading name. Others lead with a field label ("Level or rank:", "Group name:") rather than a character. Player characters and NPC companions are mixed together (Ront, Prince Derendil and Jimjar sit beside Daz and Zalthir), and spell levels ("4th-level slot") look like character levels. So the extraction must state each party note's subject, and code must settle which character that is against the roster.
- **Thread names do not carry identity across chunks.** 550 of 554 thread names appear exactly once, because each extraction call sees only its own chapters. Deciding which notes are the same thread, and so which threads are still open, is an identity decision.

The grounding survey (`dgx-fun/survey-grounding`) settles who makes that identity decision:

- **F8:** identity is the precision decision, so it belongs to the GM, recorded once and read back on every run.
- **"Rulings must be inputs."**
- **Approach 9:** a GM-ratified thread registry with proposals already exists (`docs/thread_registry.yaml`, the Threads page). It failed on two counts: noisy inputs (ensemble facts) and a ratification queue the GM could not keep up with (4 ratified, 148 pending). The survey names retargeting it onto summary-native outputs as the natural next step.

This feature does that. Thread identity comes from the registry, fed by the checked thread notes. A model may *propose* groupings of notes for the GM to ratify, and never decides them. *(GM decision, 2026-10-08.)*

**What decision is removed from the human:** only prose, as in spec 033. The work splits like this:

- **Code** decides which character a note belongs to, which notes belong to a ratified thread (exact title or alias), whether a thread is open, the order of plots, which NPCs and factions appear, and which arc scores exist.
- **The GM's config** decides what is tracked.
- **The GM's thread registry** decides which notes are one thread.
- **A model** does three things:
  - writes readable sections from checked notes;
  - lists candidate arc-score events for the GM to judge;
  - proposes thread groupings for the GM to ratify.

  Code checks every candidate and every proposal before the GM sees it.

Every draft stays a draft until the GM promotes it.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Build party from checked notes (Priority: P1)

The GM builds party for a chapter range from the checked notes. The extraction's party section now names each note's subject: a character, or the party as a whole. A level statement is its own row, which code confirms against the cited chapter. This changes the extraction instructions, so the range is extracted once more. After that, party, planning, world_state and campaign_state all build from the same cached notes.

Code attributes each party note to a player character by exact name or alias from the player roster (`players.yaml` and the entity registry), and sets aside notes about NPC companions. It then builds, per character, the material for that character's section:

- the character's checked notes in chapter order;
- the latest stated level, with its citation;
- the character's sheet and backstory from the party config, as authored reference.

A model writes each character's section from only that material. It also writes the party overview and party dynamics from the party-wide notes. Where a sheet or backstory claims a current state the notes do not support, the section says so rather than carrying it forward. Every checked party note is kept verbatim in a per-character reference file the section points to.

**Why this priority**: party is read at every prep, and its most-wrong fact today (the party's level) is exactly what the chunked notes fixed for world_state.

**Independent Test**: Build party for Out of the Abyss chapters 2–70 from the cached notes. Then confirm:

- every configured player character has exactly one section, in config order;
- the level is reported as nine with a citation;
- no NPC companion has a character section;
- every line in a character section cites a chapter in the range;
- each character section links its reference file.

**Acceptance Scenarios**:

1. **Given** a party note beginning "Ront:", where Ront is not a player character, **When** party is built, **Then** the note does not reach any character's section and appears instead in the companions reference.
2. **Given** a party note for a character written in a form the roster does not know (e.g. a misspelling), **When** party is built, **Then** the note is listed as unattributed for the GM and is not guessed onto a character.
3. **Given** a character whose sheet says level 8 while a checked note says the party reached level 9, **When** party is built, **Then** the section states level 9 with the note's citation, and the sheet's figure is shown only as the sheet's.
4. **Given** a character with no checked notes in the range, **When** party is built, **Then** the section exists, states that the summaries in this range record nothing for the character, and is not filled from the sheet.
5. **Given** a level row claiming level 9 whose cited chapter states no level 9, **When** notes are checked, **Then** the row is dropped with the reason "level not in cited text". A "4th-level slot" never counts as a character level.

---

### User Story 2 - Build planning from checked notes and published dossiers (Priority: P1)

The GM builds planning for a chapter range:

- **Threat Tracker**: code lists exactly the arc scores the planning config configures. When none are configured, the section is the existing single-line sentinel.
- **Faction States**: code picks the factions from the config and from the checked faction notes, then a model writes each faction's entry from that faction's notes.
- **NPC Dossiers**: rendered from the published, verified NPC dossiers, like world_state's Key NPCs. It reads only the sections that carry current state, goals and relationships. Each entry points to its dossier. No Secrets text is ever read.
- **Active Plots**, in two layers, by certainty:
  - **Ratified threads.** These are the threads in the GM's thread registry that have checked notes in the range. Code decides whether each is open: a status the GM set in the registry wins; otherwise the tag of the latest note attached to the thread. Code orders them by most recent activity. A model writes one entry per open thread from that thread's attached notes, and may not add, drop or reorder threads.
  - **Unratified thread notes.** These are the checked thread notes no ratified thread claims. They are listed below the ratified threads under a heading that says they are not yet ruled on, verbatim, in chapter order, with a count and a pointer to the proposals queue. They are never presented as plots.
- **DM Notes**: written by a model from checked notes only, every line cited, and labelled as suggestions for the GM.

**Why this priority**: planning drives what the GM prepares next. Its open-plot list and NPC statuses are decision-driving and must be exact, so thread identity moves to the GM's registry, and the open/closed decision and the order move to code.

**Independent Test**: Build planning for Out of the Abyss chapters 2–70, with a registry holding a few ratified threads. Then confirm:

- the threat tracker matches the config exactly;
- every ratified thread that is open appears once in Active Plots and no resolved or abandoned one does;
- plots are in order of latest activity;
- every checked thread note not attached to a ratified thread appears under the unratified heading;
- every NPC entry names its dossier file;
- a unique marker string seeded into a dossier's Secrets appears in no output and no recorded prompt.

Then build again with an empty registry: planning builds, Active Plots says no thread is ratified yet, and every thread note is under the unratified heading.

**Acceptance Scenarios**:

1. **Given** a ratified thread whose latest attached note is `[RESOLVED]`, **When** planning is built, **Then** the thread is not in Active Plots.
2. **Given** a ratified thread the GM set to `resolved` in the registry, while its latest attached note is `[ADVANCED]`, **When** planning is built, **Then** the GM's status wins and the thread is not in Active Plots.
3. **Given** a ratified thread with registry status `open` (the default) whose latest attached note is `[RESOLVED]`, **When** planning is built, **Then** it is not in Active Plots.
4. **Given** a ratified thread the GM set to `dormant`, **When** planning is built, **Then** it appears under `### Dormant threads` as its title and latest attached note, verbatim, and not among the open plots.
5. **Given** a model's Active Plots output that omits, adds or reorders a thread, **When** it is checked, **Then** the entry is replaced by code with the thread's latest attached note, verbatim with its citation, and the substitution is reported.
6. **Given** an NPC selected for planning whose dossier is unpublished or failed verification, **When** planning is built with default settings, **Then** the build refuses before writing planning and names each such NPC with its dossier's state. This is the same rule and the same per-run fallback-lines option as world_state.
7. **Given** a planning config with no arc scores, **When** planning is built, **Then** the Threat Tracker section is exactly the single sentinel line.

---

### User Story 3 - Thread proposals the GM can actually ratify (Priority: P1)

The GM keeps a thread registry for the campaign. From the checked thread notes, code first attaches every note whose bold thread name exactly matches a ratified title or alias. The remaining notes become proposals.

A model reads the unattached notes, with the ratified threads' titles and latest notes, and proposes groupings, each of one of two forms:

- "these notes are one new thread, suggested title X";
- "these notes continue ratified thread T".

Code checks every proposal before the GM sees it:

- each member must be a real, unattached checked note;
- a note may sit in at most one proposal;
- a "continues T" proposal must name a thread that exists.

A note left out of every proposal stays a single-note proposal, so nothing is lost.

The GM reviews the proposals on the Threads page or at the command line, and for each one:

- ratifies it, editing the title, members and status as needed; or
- splits it; or
- rejects it.

Ratifying writes the thread, or the new log rows, to the registry, and records every member's thread name as an alias. The next run then attaches those notes, and any later note using the same name, by exact match. Rulings persist across runs, and a rejected grouping is not proposed again.

**Why this priority**: without it the registry starts empty and stays empty. The survey's approach 9 died with 148 proposals pending, one name each. Grouping turns roughly 550 one-note decisions into a reviewable number, and once the backlog is ratified, each new session needs only a few rulings.

**Independent Test**: On Out of the Abyss chapters 2–70 with an empty registry, run the proposal step. Then confirm:

- every unattached thread note is a member of exactly one proposal;
- no proposal cites a note that does not exist;
- the number of proposals is well below the number of notes.

Ratify three proposals and re-run: their notes are attached by exact match and are no longer proposed.

**Acceptance Scenarios**:

1. **Given** a model proposal that lists a note not in the checked notes, **When** proposals are checked, **Then** that member is removed, the removal is reported, and the rest of the proposal stands only if it still has a member.
2. **Given** two proposals that both claim one note, **When** proposals are checked, **Then** the note is kept in neither and is listed as a single-note proposal for the GM.
3. **Given** a ratified proposal, **When** the notes are re-checked on the next run, **Then** every member attaches to the ratified thread by exact name or alias, with no model involved.
4. **Given** a proposal the GM rejected, **When** proposals are generated again, **Then** the same grouping is not offered again; its notes return as single-note proposals.

---

### User Story 4 - Candidate arc-score events, checked (Priority: P2)

For each configured arc score, attached either to a player character in the party config or to an NPC or faction in the planning config, a model reads only:

- the checked notes routed to that subject;
- the score's mechanic text.

It lists candidate events. Code checks each candidate:

- it must cite a checked note's citation;
- its trigger text must be quoted verbatim from the mechanic file;
- it must not state a current value, a running total or a threshold crossed.

A candidate that fails is dropped and listed. A character or entity marked trackless never gets candidates.

**Why this priority**: arc scores are a GM decision. The documents may only surface candidates. It is P2 because the documents are useful without it, and on Out of the Abyss no arc scores are configured today.

**Independent Test**: With a test campaign configuring one arc score on a player character and one on an NPC, build both documents and confirm every candidate cites a checked note, every trigger is verbatim from its mechanic file, and no number appears as a current value.

**Acceptance Scenarios**:

1. **Given** a candidate whose trigger text is paraphrased, **When** candidates are checked, **Then** it is dropped with the reason "trigger not verbatim".
2. **Given** a candidate stating "score is now 3", **When** candidates are checked, **Then** it is dropped with the reason "states a value".
3. **Given** a trackless character, **When** party is built, **Then** no candidate events or arc-score suggestions appear for that character.

---

### User Story 5 - Annotation, reading contract and run record, as for the other two documents (Priority: P2)

After party and planning are built, the same code detectors spec 033 runs over world_state and campaign_state run over these documents' prose sections:

- stale versus later notes;
- a status change of a mentioned NPC;
- a player character in an NPC section;
- a non-verbatim quotation;
- an invalid citation.

Detector hits are answered with `⚠ later:`, `ℹ since:` or `⚠ unverified:` beneath the line. No line is reworded. Each document opens with the reading contract, and each build writes a run record of its inputs, backends, timings and outputs.

**Why this priority**: annotation is what makes a prose section safe for session prep to navigate by. It reuses spec 033's detectors, so it follows the two builds.

**Independent Test**: Build both documents for Out of the Abyss and confirm that a party line describing a companion whose status later changed carries an `ℹ since:` note, that no line's text differs from the built draft, and that both documents open with the reading contract.

**Acceptance Scenarios**:

1. **Given** a planning NPC entry for an NPC whose status changed after the entry's citations, **When** detection runs, **Then** the dossier-sourced entry is left as is: it is fixed in its dossier, as world_state's Key NPCs is.
2. **Given** a character section in party that quotes words not verbatim in the cited chapter, **When** detection runs, **Then** the line gains a `⚠ unverified:` note and keeps its text.

---

### User Story 6 - One build surface for all four documents (Priority: P3)

The GM uses the same steps, options and web page to build party and planning as world_state and campaign_state:

- the same extraction cache;
- separate backend and model choices for the extraction and prose steps;
- the same refusal and exit-code rules;
- the same draft location under the range's working area.

The one-shot path for party and planning is removed. The options that only existed for it (splitting the outline into several calls, per-document context selection that no longer applies) are refused with a message that says what replaced them.

**Why this priority**: two build paths for one family of documents is what made the four documents inconsistent. Removing the old path is the single-user, migrate-and-delete rule applied.

**Independent Test**: From the web page and from the command line, build all four documents for one range from one extraction run. Confirm no extraction call was made after the first document, and that an option of the retired path is refused with a message naming its replacement.

**Acceptance Scenarios**:

1. **Given** a completed extraction for a range, **When** the GM builds party and then planning, **Then** neither build makes an extraction call.
2. **Given** a request using a one-shot-only option for party, **When** the build starts, **Then** it refuses before any model call and names what replaced the option.

---

### Edge Cases

- **A character renamed mid-campaign:** the roster and registry carry both names, so notes under either name attribute to one character. A name neither knows is unattributed and listed, never guessed.
- **A party note naming two player characters:** the note is attributed to each named character and appears verbatim in both reference files.
- **A thread whose name drifts across chunks** (the normal case: each extraction call names threads independently). Code treats the names as separate until the GM ratifies them into one thread. The proposal step may suggest the grouping; nothing merges them by similarity.
- **A note that continues two ratified threads:** it attaches only by exact name or alias. A note whose name is an alias of two threads is unresolved and listed, never given to either.
- **A ratified thread with no notes in the range:** it is absent from Active Plots, which covers only this range's evidence. The registry still holds it.
- **A faction named only in the config, with no checked notes in the range:** its entry says the summaries in this range record nothing for it.
- **No checked notes exist for the range:** the build refuses and names the extraction step to run.
- **Extraction incomplete** (a chunk missing or cut off, including a chunk missing any of its sections; see #515): the build refuses, or proceeds only where the other documents' rules allow, and never claims to cover the missing chapters.
- **The party config or planning config is absent:** the build refuses and names the missing file, as today.
- **A dossier that contradicts the summaries:** the planning NPC entry passes the dossier's text through. The error is fixed in the dossier, and session prep's verification is the backstop.

## Requirements *(mandatory)*

### Functional Requirements

**Inputs and extraction**

- **FR-001**: party and planning MUST be built from the same checked notes as world_state and campaign_state. One extraction pass MUST feed all four documents.
- **FR-002**: The extraction's party section MUST name each note's subject (a character, or the party as a whole) in a form code can read, and MUST write level statements as their own rows. Code MUST drop a level row whose cited text does not state that level. The change MUST keep spec 033's checks: resolving citations, verbatim quotations and required tags. Cached chunks extracted under the old instructions MUST NOT be reused silently.

**Attribution (code-owned)**

- **FR-003**: Code MUST attribute each party note to player characters by its stated subject, using exact, case-insensitive name or alias from the player roster and entity registry. Notes whose subject is an NPC MUST go to a companions reference. Notes whose subject resolves to nothing MUST be listed as unattributed for the GM.
- **FR-004**: The level reported for a character or the party MUST come from the latest checked level row, with its citation. With no such note, the section MUST say the summaries record no level and show the sheet's figure as the sheet's.

**party**

- **FR-005**: party MUST have one section per configured player character, in config order, named exactly as configured. Each section MUST be written by a model from only that character's checked notes, plus that character's sheet and backstory as authored reference.
- **FR-006**: A claim from a sheet or backstory about a character's current state that no checked note supports MUST be shown as unsupported by the summaries, with its source, never as fact.
- **FR-007**: The party overview and party dynamics MUST be written from the party-wide checked notes (party notes and the latest party location and intentions) only. Party dynamics MUST also see the latest checked notes about each companion (a non-player entity the registry names as a party note's subject), so bonds with companions are covered *(GM ruling, 2026-10-08)*.

**planning**

- **FR-008**: The Threat Tracker MUST be built by code: exactly one row per arc score the planning config configures, or the single sentinel line when none are configured.
- **FR-009**: Thread identity MUST come from the GM's thread registry. Code MUST attach a checked thread note to a ratified thread only when the note's thread name exactly matches (case-insensitive, normalised) the thread's title or an alias. A name claimed by two threads MUST stay unattached and be reported.
- **FR-009a**: Whether a ratified thread is open MUST be decided by code: a registry status of `dormant`, `resolved` or `abandoned` (set by the GM) wins; a status of `open` (the default) defers to the latest attached note, open meaning its tag is OPENED or ADVANCED. Ratified threads the GM set to `dormant` MUST be listed under `### Dormant threads` in Active Plots, built by code: title and latest attached note, verbatim with its citation, never model prose. Active Plots MUST list exactly the open ratified threads with notes in the range, ordered by code by most recent activity. A model MUST NOT add, drop or reorder plots, and an entry that does MUST be replaced by the thread's latest attached note, verbatim with its citation, and reported.
- **FR-009b**: Checked thread notes no ratified thread claims MUST be listed verbatim in chapter order under a separate heading in Active Plots stating they are not yet ruled on, with their count and a pointer to the proposals queue. They MUST NOT be rendered as plots. planning MUST build when the registry is empty or absent.

**Thread proposals**

- **FR-009c**: A proposal step MUST turn the unattached checked thread notes into proposals for the GM: a model MAY group notes into "new thread, suggested title" or "continues ratified thread T" proposals. Code MUST check every proposal: each member is a real, unattached checked note; no note is in two proposals; a "continues" target exists. Every unattached note left out of a valid proposal MUST become a single-note proposal.
- **FR-009d**: Only the GM's ratification MAY write the registry. Ratifying a proposal MUST record the thread (or its new log rows, each with its citation) and add every member's thread name as an alias, so later runs attach those notes by exact match. The GM MUST be able to edit the title, members and status before ratifying, and to split or reject a proposal. Rulings MUST persist across runs: a rejected grouping MUST NOT be proposed again.
- **FR-009e**: The proposal step MUST be reachable from the existing Threads page and its command line, and MUST record its prompts, model and outputs like every other model step.
- **FR-010**: planning's NPC Dossiers MUST be rendered from published, verification-passing NPC dossiers. It MUST read only each dossier's Identity, Personality and Motivations, Last Observed State and Relationships sections, MUST never read Secrets into any prompt or output, and each entry MUST name its dossier file. It MUST follow world_state's rules: refuse by default when a selected NPC lacks a usable dossier, and offer a per-run fallback-lines option.
- **FR-011**: Which NPCs appear in planning MUST be chosen by code: every NPC the planning config tracks, plus the NPCs the existing recent/recurring selection rules pick. The model MUST NOT add, drop or reorder NPCs.
- **FR-012**: Which factions appear MUST be chosen by code: those named in the planning config plus those with checked faction notes in the range. Each faction entry MUST be written from that faction's notes only.
- **FR-013**: DM Notes MUST be written from checked notes only, every line cited, and labelled as suggestions for the GM, not as events.

**Arc-score candidates**

- **FR-014**: For each configured, non-trackless arc score, a model MAY list candidate events from that subject's checked notes and the mechanic text only. Code MUST drop any candidate that does not cite a checked note's citation, does not quote its trigger verbatim from the mechanic file, or states a current value, a running total or a threshold crossed. Drops MUST be listed with reasons.
- **FR-015**: A trackless character or entity MUST receive no candidates and no suggestion to create a score.

**Shared with spec 033**

- **FR-016**: Every checked note used by party or planning MUST be kept verbatim, grouped by subject, in a reference file the matching section points to.
- **FR-017**: Prose sections MUST use quotation marks only around words spoken or written in the summaries. Every line that states something drawn from the summaries MUST carry a citation into them. Code-built status and pointer lines carry none: an empty-section line, the no-ratified-threads line, the suggestions label, overflow lists and reference pointers.
- **FR-018**: Each document MUST open with the reading contract.
- **FR-019**: spec 033's annotation detectors MUST run over party and planning prose sections, and hits MUST be answered with appended evidence, never a rewrite. Excluded are the code-owned sections (Threat Tracker and the Active Plots order) and the dossier-sourced planning NPC entries. A player character in an NPC section MUST be removed and reported.
- **FR-020**: Code-built sections MUST be byte-identical across rebuilds from the same checked notes, registry, roster and config.
- **FR-021**: The backend and model for the prose step MUST be selectable separately from extraction, using the same options as the other two documents. No run may require an API key unless its backend needs one.
- **FR-022**: Each build MUST write a run record (inputs, config files, dossiers used, backends, models, timings, outputs) and all outputs MUST be drafts in the range's working area. No live document is written until the GM promotes it.

**Replacement and surfaces**

- **FR-023**: This build MUST replace the one-shot path for party and planning. Options that only applied to the one-shot path MUST be refused with a message naming their replacement, never silently ignored.
- **FR-024**: Every capability MUST be reachable from the web UI's summary-native grounding page, with the same options as the command line.
- **FR-025**: The summary-native how-to MUST document the party and planning builds, their refusals and their exit codes. The session-prep contract (documents are an index; the summary wins) MUST be stated as covering all four documents.

### Key Entities

- **Party note attribution**: the mapping from a checked party note to zero or more player characters, decided by code. The note is otherwise a companion note or an unattributed note.
- **Character section**: one player character's part of party, written from that character's attributed notes and authored sheet/backstory.
- **Thread registry**: the GM-ratified record of plot threads (`docs/thread_registry.yaml`): id, title, aliases, status, log rows with citations. The identity authority for threads; written only by ratification.
- **Thread proposal**: a code-checked grouping of unattached thread notes (new thread with a suggested title, or continuation of a ratified thread), pending until the GM ratifies, splits or rejects it.
- **Open thread**: a ratified thread whose registry status is `open` (the default) and whose latest attached note's tag is OPENED or ADVANCED, with the chapter of its latest activity, which sets its order. A status of dormant, resolved or abandoned, set by the GM, overrides the tag; dormant threads are listed separately.
- **Planning NPC entry**: one dossier-sourced line block per selected NPC, pointing to its dossier.
- **Arc-score candidate**: a proposed event for a configured score. It holds a cited checked note and a verbatim trigger, and is checked by code or dropped with a reason.
- **Reference file, reading contract, annotation, run record**: as defined in spec 033.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On Out of the Abyss chapters 2–70, party reports the party at level nine with a citation, and has exactly one section per configured player character and none for an NPC companion.
- **SC-002**: planning's Active Plots contains 100% of the open ratified threads with notes in the range and 0% of those resolved or abandoned, in order of latest activity; 100% of unattached thread notes appear under the unratified heading.
- **SC-002a**: On Out of the Abyss chapters 2–70 with an empty registry, the proposal step covers 100% of thread notes, each in exactly one proposal, with at most one-third as many proposals as notes. After the GM ratifies a proposal, its notes attach on the next run with no model call.
- **SC-003**: Every planning NPC entry names its published dossier. A marker seeded into a dossier's Secrets appears in zero outputs and zero recorded prompts.
- **SC-004**: Every citation in a code-owned section resolves. In prose sections at least 99% resolve, and every one that does not is annotated.
- **SC-005**: At least 90% of quotations in prose sections are verbatim, and 100% of the rest carry an `⚠ unverified:` annotation.
- **SC-006**: Each document (excluding reference files) is no larger than the one-shot draft of the same document for the same range.
- **SC-007**: With the extraction already cached, building party and planning together completes in under 10 minutes on the reference setup (the same as spec 033's prose-only rebuild), and makes zero extraction calls.
- **SC-008**: Every post-draft change to either document is an annotation or a player-character removal listed in the annotations report.
- **SC-009**: Every arc-score candidate that survives the check cites a checked note and quotes its trigger verbatim, and no surviving candidate states a value.

## Assumptions

- **The one-shot path is replaced, not kept beside it** (single user, migrate-and-delete). This applies to summary-native party and planning only. The older non-summary-native `party` and `planning` CLIs (`pipelines/grounding/`) are out of scope. On Out of the Abyss the live `party.md` and `planning.md` are hand-updated and come from neither path.
- The checked notes, reference-file layout, reading contract, annotation detectors, run record, backends and refusal style are spec 033's and are reused, not re-specified.
- The party config (`party.yaml`) and planning config (`planning.yaml`) keep their current meaning: what is tracked, sheets, backstories, arc-score mechanics and trackless flags. They say what to track, never what happened.
- `players.yaml` and the entity registry are the identity authorities for attributing party notes. A name they do not know is fixed at the source (the summary or the registry), never alias-mapped by similarity.
- The thread registry, its verbs and the Threads page already exist (state-projection work, #213). This feature changes what feeds them: summary-native checked thread notes instead of ensemble facts. It adds the grouping proposal step. The ensemble-fact harvest stays for campaigns that use it.
- Thread notes keep spec 033's grammar (`[TAG] **Name** — text [cite]`). The extraction is not told the registry's titles, because naming the same thread twice the same way would be the model making the identity decision.
- Published NPC dossiers come from spec 032. This feature reads them and never writes them. planning refuses by default on a missing dossier, consistent with the 2026-10-07 GM ruling for world_state, with the same per-run fallback-lines option.
- Word budgets for party and planning prose sections start from the size of today's one-shot drafts and are configurable, as for world_state.
- Building the feature: in its own worktree. The orchestrating model coordinates and reviews, and implementation is delegated to a coding model per phase (the user's process instruction; not a product requirement).

### Out of Scope

- The legacy `pipelines/grounding/party.py` and `planning.py` CLIs.
- Changing what the extraction step's checks accept, beyond what FR-002 allows.
- Deciding arc-score values, thresholds or triggers. The GM decides them; the documents only surface candidates.
- Any model pass that edits, rewrites, deletes or moves lines in a built document.
- Fixing errors in summaries, the registry, configs or dossiers. This feature surfaces them for the GM to fix at the source.
- campaign_state's thread sections, which today a model writes from the whole ledger, reading the thread registry instead. This is a follow-up once the registry is ratified.
- Incremental rebuilds after a new session (#512) and the missing-section chunk check (#515). Both are tracked separately; this feature inherits whatever they deliver.
