# Feature Specification: Chunked, Code-Checked Grounding Documents

**Feature Branch**: `worktree-033-chunked-grounding-docs`

**Created**: 2026-10-07

**Status**: Draft

**Input**: User description: issue #505 and the experiment in `experiments/20261007-chunked-state-docs/` (`RESULTS.md` rounds 1–7, PRs #507 and #508). This feature extends summary-native grounding (spec 031) and builds on summary-native NPC dossiers (spec 032).

## Context

A GM preparing a session relies on two grounding documents: **world_state** (where the world stands: party, factions, NPCs, places, items, threats) and **campaign_state** (what is done and what is open: completed encounters, resolved and open threads, NPC current status, and a check of the tracking files). The reader of both is Claude running session prep (the gm-assistant `gm-session-prep` skill), which reads them as background for the session it is preparing.

Today summary-native grounding (spec 031) writes each of them in **one model call** from scene synopses, memorable moments and entity dossiers. On the Out of the Abyss campaign (chapters 2–70, 409 scenes) that call:

- **sees only synopses,** so it misses facts that live in summary bullets: it reported the party at level 8 when the summaries say nine;
- **cites 22% of scenes** (world_state) and 47% (campaign_state);
- **is not checked** after it is written, so a stale or invented sentence reaches session prep, which treats it as canon.

The experiment showed a different shape works: read the full summaries a few chapters at a time, have code check every extracted note before anything else uses it, let code own the sections where precision matters, and use a model only to write prose from checked notes. On the same campaign this cited 99–100% of scenes, caught the level-nine fact, and, with a word budget and reference files, produced a world_state smaller than today's. The session-prep A/B in the experiment also showed that the best prep comes from treating these documents as an **index** that points at the summaries, not as an authority.

**What decision is removed from the human:** only prose — writing readable sections from notes code has already checked. Scope, identity, ordering and attribution stay with the summaries, the entity registry, deterministic code and the GM. The precision sections (event timeline, completed encounters, NPC current status, audit verdicts) are built by code. Every draft stays a draft until the GM promotes it, and nothing a model writes feeds another model call without passing a code check first.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Build both documents from checked notes (Priority: P1)

The GM runs a single build for a chapter range. The system reads the full session summaries a few chapters at a time and extracts notes from each group: events, concluded encounters, thread changes, NPC status rows, facts about factions, NPCs, places, items and threats, and the party's situation. Before any note is used, code checks it: every citation must point at a real scene or section **within that group of chapters**, every quoted span must appear verbatim in the summaries, and every note must carry its required tag. Notes that fail are dropped and listed with the reason. From the surviving notes, code builds the event timeline, the completed-encounters list and the NPC current-status table; a model writes the remaining sections from the notes routed to each. One extraction pass feeds both documents. The result is a pair of drafts the GM reviews; no live document is touched.

**Why this priority**: This is the core of the feature: complete, cited, checked drafts of both documents. Every other story refines or consumes it.

**Independent Test**: Build both documents for Out of the Abyss chapters 2–70. Confirm the drafts cite at least 95% of scenes (counting the timeline), every citation resolves, the party is reported at level nine, and the drop list names a reason for each dropped note. Change nothing and rebuild from the cached notes: the code-built sections are byte-identical.

**Acceptance Scenarios**:

1. **Given** a note whose citation points at a chapter outside the group it was extracted from, **When** notes are checked, **Then** the note is dropped and the drop list records "outside chunk" with the note's text.
2. **Given** a note that puts quotation marks around words not found verbatim in the summaries, **When** notes are checked, **Then** the note is dropped and listed with the offending span.
3. **Given** a note that cites a section by its heading text in a different letter case (e.g. "NPCs" for the NPCs section), **When** notes are checked, **Then** the citation is accepted as that section, while a citation to a section the summary does not have is still rejected.
4. **Given** two status rows for the same NPC written as "Ilvara" and "Ilvara Mizzrym", which the registry maps to one entity, **When** the status table is built, **Then** it has one row for that entity, holding the latest status (Dead, chapter 53).
5. **Given** an NPC whose latest row says "Unknown" after an earlier row stated a status, **When** the table is built, **Then** the known status is kept and the later Unknown report is shown beside it with its citation.
6. **Given** a player character named in `players.yaml`, **When** the status table is built, **Then** the character has no row.
7. **Given** a group of chapters whose extraction fails or is cut off, **When** the build finishes, **Then** the GM is told which chapters are missing, no draft claims to cover them, and re-running extracts only the missing group.

---

### User Story 2 - A world_state that fits beside the other prep documents (Priority: P1)

Session prep reads world_state alongside three other documents, so it must stay short. Each prose section of world_state is written within a word budget, choosing what matters at the end of the range. Nothing is lost by that choice: every checked note is kept verbatim, grouped by subject, in reference files that each section points to, and the full event timeline lives in its own file. The document opens with a reading contract that tells the reader what each marker means, where a citation points, and where the reference files are.

**Why this priority**: Without the budget the chunked world_state was ten times today's size (237K characters) and could not be loaded for prep. With it, the experiment's world_state was 16.5K characters, smaller than today's.

**Independent Test**: Build world_state for Out of the Abyss chapters 2–70 and confirm each prose section is within its budget, every section links its reference file, the timeline is a separate file holding every event in chapter order, and the reading contract is the first thing in the document.

**Acceptance Scenarios**:

1. **Given** a section that would exceed its word budget, **When** world_state is built, **Then** the overrun is reported for the GM and the text is never truncated mid-sentence.
2. **Given** any checked note about a subject, **When** the build finishes, **Then** that note appears verbatim under its subject in the matching reference file.
3. **Given** a prose section, **When** it is written, **Then** quotation marks appear only around words spoken or written in the summaries, never around note text such as a status or disposition.

---

### User Story 3 - Key NPCs come from the published dossiers (Priority: P2)

world_state's Key NPCs section is rendered from the published, verified NPC dossiers (spec 032), not re-derived from notes. Code picks the NPCs that matter at the end of the range, reads only each dossier's Identity and Last Observed State, and a model writes one line per NPC; each line names its dossier so the reader can open it. A player character never appears. Fixing an NPC means fixing the dossier, and the next build carries the fix.

**Why this priority**: In the experiment the model-written Key NPCs listed a player character as an NPC and carried stale statuses; the dossier-sourced version had neither problem. It depends on spec 032's published dossiers, so it follows Stories 1–2.

**Independent Test**: With published dossiers for the selected NPCs, build world_state and confirm each Key NPCs line cites only its own dossier, names its dossier file, and that no Secrets text appears anywhere in world_state or in any prompt. Seed a dossier whose Secrets section contains a unique marker string and confirm the marker appears in no output and no recorded prompt.

**Acceptance Scenarios**:

1. **Given** a published dossier, **When** its Key NPCs line is written, **Then** every citation on the line comes from that dossier and every quotation is verbatim.
2. **Given** a line the model writes that fails those checks, **When** world_state is built, **Then** the dossier's own first Last Observed State sentence (with its citation) is used instead, and the substitution is reported.
3. **Given** a selected NPC whose dossier is unpublished or failed verification, **When** world_state is built with default settings, **Then** the build refuses before writing world_state and names every such NPC with its dossier's state (not drafted, failed verification with the failing checks, or drafted but not published), so the GM can fix and publish them *(GM ruling, 2026-10-07)*.
4. **Given** the same NPC, **When** the GM explicitly asks for fallback lines, **Then** world_state is built and that NPC's line is assembled by code alone (no model) from its latest status row and its checked notes, verbatim with their citations, and marked "no published dossier — from checked notes"; the build report lists every fallback line. Once the dossier is published, the next build uses it instead *(GM ruling, 2026-10-07)*.

---

### User Story 4 - Stale lines are annotated, never rewritten (Priority: P2)

After both drafts are built, code looks for lines that later evidence contradicts or overtakes: a line citing an earlier chapter than the latest notes about its subject; a claim mentioning an NPC whose status changed after the claim's own citation; the same subject described differently in two sections; a player character in an NPC section; a non-verbatim quotation; an invalid citation. Instead of a model rewriting the line, code appends the later evidence beneath it, verbatim and cited: `⚠ later:` for newer information about the same subject, `ℹ since:` for the later status of someone the line mentions, `⚠ unverified:` for a quotation or citation code could not confirm. A player character in an NPC section is the one case code removes outright. The reading contract tells the reader how to use each marker.

**Why this priority**: The experiment tried a model fix pass under every gate it could add; about a third of its rewrites made a document worse, including one that attached a real citation to a wrong claim, which no gate catches. Annotation keeps every line traceable and lets session prep see both facts.

**Independent Test**: Build the Out of the Abyss drafts and confirm that the line calling Jimjar a travelling companion (chapter 26) carries a `⚠ later:` note citing chapter 48, that a claim saying Kalan fled (chapter 65) carries an `ℹ since:` note citing his chapter 67 status, and that no line was reworded.

**Acceptance Scenarios**:

1. **Given** a line whose own citations are all earlier than a later note about the same subject, **When** detection runs, **Then** the line keeps its text and gains a `⚠ later:` note quoting that later note with its citation.
2. **Given** a line with two claims, one citing chapter 67 and one citing chapter 65 that mentions an NPC whose status changed in chapter 67, **When** detection runs, **Then** the chapter-65 claim is caught even though the line also cites chapter 67.
3. **Given** a mentioned NPC with no earlier recorded status, **When** detection runs, **Then** a later status alone does not produce a note (a status must have changed).

---

### User Story 5 - Choose where each step runs (Priority: P2)

The GM chooses the backend for the extraction step and for the prose step separately. Extraction (dozens of calls) can run on the local Sparks, with several endpoints sharing one queue of chapter groups so a slower box simply takes fewer; the prose step (a handful of calls) can run on a faithful hosted model through the subscription. Every step's notes and outputs are cached, so a rebuild after changing only the prose step re-uses the extraction, and a failed or interrupted run resumes without redoing finished groups.

**Why this priority**: The experiment's best configuration split the work: Qwen3-Next on two Sparks extracted all 60 chapter groups in about 30 minutes, and Sonnet 5.5 at medium effort wrote all prose sections in about 2 minutes with 94% verbatim quotations, against 61% when the local model also wrote the prose.

**Independent Test**: Run extraction against two local endpoints and confirm both received work and the run record says which endpoint did each group. Then rebuild with a different prose backend and confirm no extraction call was made.

**Acceptance Scenarios**:

1. **Given** two endpoints, one unreachable or serving a different model, **When** a build starts, **Then** it refuses before any call and names the endpoint and the problem.
2. **Given** a hosted backend that needs no API key, **When** a build runs, **Then** nothing checks for or requires a key.
3. **Given** a completed extraction and a changed prose prompt, **When** the GM rebuilds, **Then** only the prose calls run.

---

### User Story 6 - The tracking audit is its own step (Priority: P3)

campaign_state's "Audit: Tracking Claims" answers, for each item in the campaign's tracking files, whether the summaries show it happening. This runs as its own step: code finds each item's candidate chapters, a model judges the item against only those chapters, and a verdict of "supported" must quote a verbatim span from a cited scene. Items the summaries do not support are marked not found, with any partial evidence listed. The audit no longer rides inside the extraction step.

**Why this priority**: Inside every extraction call the audit list degraded: recall was weak, one model listed all 443 items as shown "in a prior session", and another spent 42% of its output on audit noise. It is P3 because the rest of campaign_state does not depend on it.

**Independent Test**: Run the audit for Out of the Abyss and confirm each supported verdict carries a citation and a verbatim span, and that the items the experiment hand-verified come out right (e.g. Bloppblippodd's confrontation and Alkrist's confession supported; Droki's capture not found).

**Acceptance Scenarios**:

1. **Given** an item a model marks supported without a verbatim span from a cited candidate chapter, **When** verdicts are checked, **Then** the verdict is not accepted and the item is reported as unverified.
2. **Given** an extraction run, **When** it runs, **Then** no audit list is included in any extraction call.

---

### User Story 7 - Session prep reads the documents as an index (Priority: P3)

The documents carry everything session prep needs to verify them: a citation on every line, pointers to dossiers, reference files and the timeline, and the reading contract. Session prep (the gm-assistant skill, changed in its own repository) reads the state documents as an index, verifies every entity it puts on stage against the latest summary, prefers the summary when they disagree, and ends its prep document with a "Doc errors found" list naming the document, its claim, the summary's claim and both citations. That list is the GM's queue for fixing errors at their source.

**Why this priority**: In the experiment this contract produced the best prep at no extra time and found eight real document errors, including a missing registry alias and an invented dossier fact. The documents' side of the contract is cheap once Stories 1–4 exist; the skill's change ships separately.

**Independent Test**: Run session prep with the contract on a beat that puts at least five generated-doc entities on stage, and confirm every entity it verified is tagged with its summary citation and every disagreement appears in "Doc errors found".

**Acceptance Scenarios**:

1. **Given** a state document that disagrees with the latest summary about an on-stage NPC, **When** prep runs under the contract, **Then** the prep uses the summary's version and lists the disagreement with both citations.

---

### Edge Cases

- A chapter group larger than the extraction size limit: it is extracted on its own; chapters are never split.
- A summary chapter missing from the range (a gap in numbering): the build proceeds, and the drafts and run record say which chapters were absent.
- A model output that invents note IDs, tags or audit item numbers outside the defined set: dropped and counted, never used.
- One extraction call degenerating into repetitive output: its drops are reported per group, so a runaway group is visible; a group whose drop rate is an outlier is flagged.
- The registry lacks an alias the summaries use (e.g. "Edvaldo" for "Edvaldo Sedanur", kostadis/campaigns#379): handled by FR-009's unresolved-name rule. The fix is a registry alias, made by the GM at the source.
- A dossier contradicts itself or the summaries (e.g. an invented "third simulacrum"): Key NPCs passes the dossier's own text through; the error is fixed in the dossier, and session prep's verification is the backstop.
- The tracking files are absent: the audit section says so; the rest of campaign_state builds.
- The summaries change after a build: the build is reported stale, as in spec 031, and cached extractions for changed chapters are not reused.

## Requirements *(mandatory)*

### Functional Requirements

**Extraction and checking**

- **FR-001**: The system MUST read the full reviewed session summaries for the chosen range, in groups of whole consecutive chapters bounded by a size limit, never splitting a chapter.
- **FR-002**: The system MUST extract, per group, notes in a fixed set of kinds (events, concluded encounters, thread changes, NPC status rows, subject facts tagged by kind, party situation), each note carrying at least one citation.
- **FR-003**: The system MUST check every note before use: each citation resolves to a real scene or section in that group's chapters (a section cited by its own heading text, in any letter case, counts as that section); each quoted span appears verbatim in the summaries; each note carries its required tag and format. Notes failing any check MUST be dropped.
- **FR-004**: The system MUST record every dropped note with its group, kind, reason and text, and report counts per group and per reason.
- **FR-005**: One extraction pass MUST feed both documents.
- **FR-006**: The system MUST cache each group's extraction and reuse it when the group's chapters, the extraction instructions and the extraction model are unchanged.

**Code-owned sections**

- **FR-007**: The event timeline MUST be built by code from checked event notes, in chapter order, and written to its own file; world_state MUST point to it.
- **FR-008**: The completed-encounters list MUST be built by code from checked concluded notes, in chapter order.
- **FR-009**: The NPC current-status table MUST be built by code: names resolved to registry entities by exact (case-insensitive) name or alias only; a form claimed by two entities left unresolved; player characters from `players.yaml` excluded; the latest row with a known status kept; a later "Unknown" row shown beside the known status rather than replacing it; unresolved names marked and listed for the GM.
- **FR-010**: Code-built sections MUST be byte-identical across rebuilds from the same checked notes, registry and player roster.

**Prose sections**

- **FR-011**: Each prose section MUST be written by a model from only the checked notes routed to that section (plus, where stated, the code-built status table or the last group's summaries).
- **FR-012**: world_state's prose sections MUST each have a word budget; an overrun MUST be reported and MUST NOT be truncated.
- **FR-013**: Every checked note MUST be written verbatim, grouped by subject, to a reference file per kind (factions, NPCs, locations, items, threats, and the thread ledger: every opened, advanced, resolved or abandoned thread note), and each world_state section, and campaign_state's thread sections, MUST point to its file.
- **FR-014**: Prose sections MUST use quotation marks only around words spoken or written in the summaries.
- **FR-015**: world_state MUST open with a reading contract describing the markers, what a citation points to, where the reference files and timeline are, and that anything the document does not settle is a decision for the GM.

**Key NPCs from dossiers**

- **FR-016**: world_state's Key NPCs MUST be rendered from published, verification-passing NPC dossiers, reading only each dossier's Identity and Last Observed State; the Secrets section MUST never be read into any prompt or output.
- **FR-017**: Each Key NPCs line MUST be checked (exactly one line per selected NPC, citations only from that NPC's dossier, quotations verbatim) and MUST fall back to the dossier's own first Last Observed State sentence when it fails; each line MUST name its dossier file.
- **FR-018**: Which NPCs appear MUST be chosen by code using the existing recent/recurring selection rules, never by the model; the model MUST NOT add, drop or reorder NPCs.
- **FR-018a**: By default, if any selected NPC lacks a published, verification-passing dossier, the build MUST refuse before writing world_state and MUST name each such NPC with its dossier's state (not drafted / failed verification and why / not published).
- **FR-018b**: When the GM explicitly requests fallback lines, the build MUST instead write, for each such NPC, a line assembled by code alone (no model call) from the NPC's latest status row and checked notes, verbatim with citations, marked "no published dossier — from checked notes", and MUST list every fallback line in the build report. The request is per run; it is never a saved default.

**Annotation**

- **FR-019**: After building, code MUST run the detectors (stale versus later subject notes; per-claim status change of a mentioned NPC; cross-section disagreement; player character in an NPC section; non-verbatim quotation; invalid citation) over both documents' prose sections, **except world_state's Key NPCs**, which is fixed in its dossiers (User Story 3), not annotated. The code-owned sections (timeline, completed encounters, NPC status table, audit) are not scanned: they are built from checked notes and already carry their own handling of later evidence.
- **FR-020**: A detector hit MUST be answered by appending the later evidence verbatim with its citation under the line (`⚠ later:`, `ℹ since:`, `⚠ unverified:`), except a player character in an NPC section, which MUST be removed. No model may reword, delete or move a line after the drafts are built.
- **FR-021**: Every annotation and removal MUST be listed in an annotations report.

**Backends and runs**

- **FR-022**: The GM MUST be able to choose the backend and model for extraction and for prose separately, using the same backend and model options every other model-calling command uses.
- **FR-023**: Extraction MUST accept several local endpoints sharing one queue of groups, MUST refuse before any call if an endpoint is unreachable or serves a different model, and MUST record which endpoint handled each group.
- **FR-024**: A run MUST NOT require or check for an API key unless the chosen backend needs one.
- **FR-025**: Each run MUST write a record of its inputs (range, summaries, registry, roster, dossiers used), backends, models, timings, per-group results and outputs, so a run is reproducible and comparable.

**Audit**

- **FR-026**: The tracking audit MUST run as its own step: code chooses each item's candidate chapters; a model judges the item against only those; a "supported" verdict MUST include a citation to a candidate chapter and a verbatim span from it, or it is not accepted.
- **FR-027**: Extraction calls MUST NOT include the tracking-file list.

**Drafts, promotion and surfaces**

- **FR-028**: All outputs MUST be drafts in the range's working area; no live document is written until the GM promotes it, as in spec 031.
- **FR-029**: For world_state and campaign_state this build MUST replace the one-shot summary-native draft path; the one-shot path remains for party and planning.
- **FR-030**: Every capability in this feature MUST be reachable from the web UI's summary-native grounding page, with the same options as the command line.
- **FR-031**: The feature MUST document the session-prep contract (index reading, verification against the latest summary, "Doc errors found") for the gm-assistant skill to adopt.

### Key Entities

- **Chapter group** (the plan and tasks call it a *chunk*): whole consecutive chapters extracted together; identified by its chapter range.
- **Note**: one extracted, cited statement of a fixed kind (event, concluded, thread change, status row, subject fact, party situation); either kept or dropped with a reason.
- **Drop record**: a dropped note with its group, kind, reason and text.
- **Code-owned section**: a section built only by code from kept notes (timeline, completed encounters, NPC status table, audit verdicts).
- **Prose section**: a section written by a model from the kept notes routed to it, within a budget where one applies.
- **Reference file**: all kept notes of one kind, verbatim, grouped by subject.
- **Reading contract**: the opening block of world_state that tells its reader how to read markers, citations and pointers.
- **Annotation**: later evidence appended under a line by code (`⚠ later:`, `ℹ since:`, `⚠ unverified:`).
- **Audit verdict**: per tracking item, supported (with citation and verbatim span) or not found (with partial evidence).
- **Run record**: the inputs, backends, timings and outputs of one build.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On Out of the Abyss chapters 2–70, the drafts plus the timeline cite at least 95% of scenes (today: 22% world_state, 47% campaign_state).
- **SC-002**: Every citation in the code-owned sections resolves to a real scene or section; in prose sections, at least 99% resolve, and every one that does not is annotated.
- **SC-003**: At least 90% of quotations in prose sections are verbatim, and 100% of the rest carry an `⚠ unverified:` annotation.
- **SC-004**: world_state (excluding the timeline and reference files) is no larger than the one-shot `summary_native synth world_state` draft for the same range (on Out of the Abyss chapters 2–70: 23K characters, kept in `experiments/20261007-chunked-state-docs/baseline_backup/drafts/`).
- **SC-005**: The NPC status table has zero player-character rows, zero entities split across two rows when the registry resolves their names, and matches the hand-verified statuses for Ilvara Mizzrym, Sarith Kzekarit, Buppido, Eldeth Feldrun and Glabbagool.
- **SC-006**: Of the experiment's 16 hand-verified facts, the drafts get at least as many right as the best configuration measured (12), and the audit gets the five hand-verified audit items right.
- **SC-007**: A full build of a 67-chapter campaign completes in under 45 minutes on the reference hardware (two local inference boxes plus a hosted prose step; see quickstart Prerequisites), and a rebuild that changes only the prose step completes in under 10 minutes.
- **SC-008**: No model rewrites any line after drafting: every post-draft change to a document is an annotation or a player-character removal listed in the annotations report.
- **SC-009**: A session prep run under the contract on these documents reports its doc errors with both citations, and no fact it marks verified contradicts the latest summary.

## Assumptions

- **The one-shot path is replaced, not kept beside it** (single user, migrate-and-delete): for world_state and campaign_state, this build supersedes the one-shot draft; party and planning keep the one-shot path.
- Summaries are the reviewed, structured summary-native summaries of spec 031, and a built corpus for the range exists; the entity registry and `players.yaml` are the identity authorities.
- Published NPC dossiers come from spec 032's pipeline; this feature reads them and never writes them. Because the default refuses on a missing dossier, building world_state assumes the GM has drafted, verified and published the dossiers for the NPCs selection picks (or opts into fallback lines for that run).
- Promotion of drafts to live documents stays a manual GM step, as in spec 031; reference files and the timeline are promoted with world_state.
- The gm-session-prep skill lives in the gm-assistant repository; this feature specifies its contract and the documents' side, and the skill change ships there.
- Default backends follow the experiment (local Sparks for extraction, a hosted faithful model at medium effort for prose) but are choices, not requirements; the specific models will change.
- Word budgets start from the experiment's (world_state prose sections ~450–900 words each) and are configurable.
- world_state is a summary and may be slightly wrong; campaign_state's NPC table, threads and audit are decision-driving and held to exactness.

### Out of Scope

- Party and planning documents (they keep the existing path).
- Any model pass that edits, rewrites, deletes or moves lines in a built document.
- Fixing errors in summaries, the registry or dossiers; this feature surfaces them (drop lists, unresolved names, annotations, session prep's doc-errors list) for the GM to fix at the source.
- Changing the gm-assistant skill itself (separate repository).
