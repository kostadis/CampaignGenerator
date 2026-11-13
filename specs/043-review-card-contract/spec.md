# Feature Specification: Review Card Contract

**Feature Branch**: `043-review-card-contract`

**Created**: 2026-11-12

**Status**: Draft

**Input**: User description: "#643 slice 1: a versioned, tested contract between a review page and the review store. `review cards export` stores a card packet in the review; `review cards decide` applies a page's per-card verdicts against it, diffing, planning first, expanding cards and refusing anything it cannot prove. Fixes #655. Retires the Codex review-page fork into the shared kit. Minimal web face. No server (slice 2)."

## Context

The GM reviews NPC drafts on a page built by a shared kit. Today the page and the review store meet through an interface nobody tests:

- The kit reads the store's internal files directly to build its cards.
- The page saves `{card: verdict}`. The store needs more for each decision: the item's revision, the review digest, the expected decision revision and a disposition. **An agent translates one into the other by hand** when it runs `review decide` and `review npc sign`. A store change can break the GM's page, or that hand translation can record a wrong decision, and no test fails.
- The store does not validate verdict/disposition pairs for the NPC review's own item types (#655). So a wrong translation is accepted silently.
- Two copies of the page kit exist, one for Claude and an older fork for Codex. They have different formats.

The GM values throwaway pages: making a new page while prototyping or debugging is cheaper than changing CampaignGenerator. This feature keeps that, and makes it safe. CampaignGenerator owns both ends of one versioned, tested contract. A page only renders. Every scope, identity and expansion decision is made by CampaignGenerator when the decisions are applied.

GM rulings, recorded on #643 (2026-11-12):

- **Two slices.** This is slice 1. Serving pages over the tailnet is slice 2.
- **Re-saving.** When a page is saved again with a changed verdict, the new verdict supersedes the old and the change is listed.
- **Discuss** is recorded as a deferral with the note.
- **Scope.** The contract covers CampaignGenerator reviews, plus retiring the Codex kit fork. The other skills keep their per-skill formats.
- **Interface.** Slice 1 has a minimal web face.
- **Command names.** `review cards export` and `review cards decide`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A page's verdicts are applied without hand translation (Priority: P1)

The GM marks cards Approve, Reject or Discuss on a review page and saves. The agent hands the saved decisions file to `review cards decide`, with no editing. CampaignGenerator works out every store field. It shows a plan of what it will record, then records exactly that: one decision per finding behind each card. Unmarked cards stay unmarked.

**Why this priority**: This removes the untested hand translation, which is the defect behind #643. Everything else builds on it.

**Independent Test**: Export a card packet from a fixture review. Write a decisions file of the shape a page saves. Run decide in plan mode and then for real. Compare the recorded decisions with the expected set.

**Acceptance Scenarios**:

1. **Given** a review with undecided claim and sign-off items, **When** the GM exports a card packet, **Then** the packet is stored inside the review under a packet id. Each card lists its member findings. Already-decided findings are excluded.
2. **Given** a decisions file that approves one card with three member findings, rejects another and leaves a third unmarked, **When** decide runs in plan mode, **Then** it lists four decisions to record and one card left unmarked, and writes nothing.
3. **Given** the same file, **When** decide runs for real, **Then** exactly those four decisions are recorded. Each has the disposition its verdict maps to for its item type. The unmarked card's findings stay undecided.
4. **Given** a card marked Discuss with a note, **When** decide runs, **Then** each member is recorded as discuss/defer with that note.
5. **Given** a decisions file with more decisions than one store transaction allows, **When** decide runs, **Then** it either records all of them or reports exactly which were recorded and which were not. It is never silent about a partial save.

---

### User Story 2 - Nothing a page sends can record a decision CampaignGenerator cannot prove (Priority: P1)

A throwaway or buggy page sends something wrong. Examples: a card that isn't in the packet, a packet from another review, a packet the store has moved past, a card whose member set has changed, or a sign-off for a draft whose bytes have changed. CampaignGenerator refuses it, and says why, before recording anything.

**Why this priority**: Throwaway pages are only safe if CampaignGenerator is the gate. An accidental paste into the wrong session happened during the design discussion. A wrong file must be refused, not applied.

**Independent Test**: For each kind of bad input, run decide against a fixture packet and assert the refusal code and that the store is unchanged.

**Acceptance Scenarios**:

1. **Given** a decisions file naming a packet id that this review does not hold, **When** decide runs, **Then** it refuses and records nothing.
2. **Given** a decisions file whose review id differs from the packet's, **When** decide runs, **Then** it refuses and records nothing.
3. **Given** a card id that is not in the packet, **When** decide runs, **Then** it refuses the file and names the unknown id.
4. **Given** a packet exported before a `review refresh` changed the review's generation, **When** decide runs, **Then** it refuses and tells the GM to export a new packet.
5. **Given** a sign-off card, **When** the draft's bytes no longer match the fingerprint in the packet, **Then** decide refuses that sign-off and names the draft. Sign-off cards must carry the packet's draft fingerprint back.
6. **Given** a recommendation or pre-filled verdict in the packet, **When** the decisions file omits a verdict for that card, **Then** nothing is recorded for it. A recommendation is never recorded without an explicit GM verdict.
7. **Given** any NPC claim or presentation item, **When** a verdict/disposition pair that is not allowed for that item type reaches the store by any path, **Then** the store refuses it. An item type with no declared pairs is refused by default, not accepted (#655).

---

### User Story 3 - Saving a page again keeps every mark and shows every change (Priority: P2)

The GM saves a page, keeps going, and saves again. Or the GM changes their mind about a card. Decisions already recorded identically are left alone. A changed verdict supersedes the old one and is listed. New marks are recorded.

**Why this priority**: Today a second save is refused as stale. It is the most likely way for review work to be lost or for the GM to give up mid-review.

**Independent Test**: Apply the same decisions file twice and assert that the second run records nothing. Change one verdict, apply again, and assert that exactly one supersede is listed and recorded.

**Acceptance Scenarios**:

1. **Given** a decisions file already applied, **When** it is applied again unchanged, **Then** the plan shows no changes and nothing is recorded.
2. **Given** a card the GM approved and now rejects, **When** decide runs, **Then** the plan and result list that card as changed from approve to reject, and the store keeps both in its history.
3. **Given** a decision made through the CLI after the packet was exported, **When** a page's decisions file covers the same finding, **Then** the plan shows the difference. Identical means no-op, and different means a listed supersede. It is never a silent overwrite and never a whole-file refusal.

---

### User Story 4 - The contract is tested on both ends (Priority: P2)

A change to how CampaignGenerator builds cards or reads decisions fails a CampaignGenerator test before it can break the GM's page. The kit's NPC card builder and its decision reader use the packet and decide commands, and do not read the store's internals.

**Why this priority**: This makes the interface testable, which was the GM's first goal. Without it, the contract drifts again.

**Independent Test**: The contract has published schemas and golden example files. A change to the packet shape that is not reflected in the schema fails a test. The kit's NPC builder, run against a fixture review, produces cards that validate against the schema.

**Acceptance Scenarios**:

1. **Given** the packet and decisions schemas and their golden examples, **When** the test suite runs, **Then** every exported packet and every example decisions file validates, and the golden examples round-trip.
2. **Given** a packet or decisions file with an unknown major schema version, **When** decide runs, **Then** it refuses with a message naming the versions it accepts.
3. **Given** campaign text containing markup, **When** a packet is exported, **Then** the text is carried as text, not as trusted markup, so a page cannot be made to run it.
4. **Given** the shared kit, **When** an NPC review page is built, **Then** its cards come from `review cards export`. Its saved decisions are applied with `review cards decide`. No kit code reads the review store's files.

---

### User Story 5 - One page kit for both agents (Priority: P3)

The Codex skills that build review pages use the same shared kit as the Claude skills, so a page built for one agent works the same for the other.

**Why this priority**: This is the GM's frustration with Codex and Claude doing pages differently. Slice 1 removes the duplicate kit. Hosting is unified in slice 2.

**Independent Test**: Each Codex skill that used the forked kit builds and reads a review page through the shared kit, with that skill's existing per-skill format unchanged.

**Acceptance Scenarios**:

1. **Given** the Codex skills that used the forked kit, **When** they are pointed at the shared kit, **Then** they build their pages and read their decisions as before.
2. **Given** the shared kit, **When** a Codex skill serves a page locally as the fork did, **Then** that keeps working until slice 2 replaces it.
3. **Given** the fork has been retired, **Then** no Codex skill refers to it, and it is removed.

---

### User Story 6 - The GM can export and apply from the web app (Priority: P3)

From the review launcher in the web app, the GM can export a card packet for a review, apply a decisions file, and see the plan before confirming.

**Why this priority**: The constitution requires a web face for a new capability (XI), and the GM chose a minimal one.

**Independent Test**: In a component test, export a packet, choose a decisions file, see the plan, confirm, and see the result. Each step calls the same CLI command.

**Acceptance Scenarios**:

1. **Given** a review, **When** the GM exports a card packet from the launcher, **Then** the packet id and card count are shown.
2. **Given** a decisions file, **When** the GM applies it, **Then** the plan (records, no-ops, supersedes, unmarked, refusals) is shown first, and nothing is recorded until the GM confirms.
3. **Given** a refusal, **When** it is shown, **Then** the GM sees the same message the CLI gives.

### Edge Cases

- **A card with no members left.** All of a card's findings were decided elsewhere after export. The card is reported as already settled. If its verdict matches, it is a no-op. If it differs, it is a listed supersede.
- **The same finding in two cards.** A finding cannot belong to two cards in one packet. Export refuses to build such a packet.
- **A Discuss card later approved.** The approval supersedes the deferral and is listed.
- **A sign-off card and a rejected claim on the same draft in one file.** Recorded as the GM marked them, in this slice. Refusing contradictory sign-offs is #626, which will use the Discuss and Reject records this slice keeps.
- **The packet was deleted or edited by hand.** decide refuses. The packet's own digest no longer matches, or the packet is missing.
- **Two packets exported from one review.** Both stay valid until the generation moves. Each decisions file is checked against its own packet.
- **A very large review (about 800 items).** Export and decide both finish. A partial save across transactions is reported, never silent.
- **A non-ASCII NPC name.** Card text keeps the original name, and ids stay ASCII (#630 behaviour).

## Requirements *(mandatory)*

### Functional Requirements

**Card packet**

- **FR-001**: `review cards export` MUST build a card packet from a review's undecided items and store it inside that review under a new packet id. The GM or agent MUST NOT be handed the only copy.
- **FR-002**: A card packet MUST record:
  - the review id;
  - the review generation;
  - a schema version;
  - for each card, its member findings;
  - for each member, everything decide needs to record it (its revision, the review digest and its expected decision revision);
  - for each sign-off card, the draft's content fingerprint;
  - the text the page shows, carried as plain text.
- **FR-003**: Every card MUST have a member list, even a card with a single finding. A finding MUST belong to at most one card in a packet.
- **FR-004**: A packet MUST NOT contain a pre-selected verdict. Any recommendation it carries MUST be kept apart from verdicts, so that it cannot be mistaken for one.

**Applying decisions**

- **FR-005**: `review cards decide` MUST accept a decisions file that carries only the packet id, the review id, per-card verdicts and per-card notes. It MUST NOT accept a packet, item revisions or dispositions from the file.
- **FR-006**: decide MUST look the packet up in the review itself. It MUST refuse when the packet is missing, belongs to another review, has been altered, or comes from an earlier review generation.
- **FR-007**: decide MUST refuse a file that names a card not in the packet, or a card whose member set differs from the packet's. It MUST name the offending ids and record nothing from that file.
- **FR-008**: decide MUST expand each card verdict into one decision per member. It MUST use the same expansion that `review noise decide` uses, so there is one expansion rule.
- **FR-009**: decide MUST map each verdict to the disposition its item type requires. That mapping MUST live in CampaignGenerator only.
- **FR-010**: decide MUST record Discuss as discuss/defer carrying the GM's note. It MUST leave unmarked cards unmarked.
- **FR-011**: decide MUST compare each would-be decision with the store before writing. A decision identical to the current one is a no-op. A different one supersedes the current decision. A finding with no decision is recorded new.
- **FR-012**: decide MUST be able to produce its plan without writing anything. The plan lists, by card and member, what will be recorded, what is a no-op, what will be superseded (old and new verdict), what stays unmarked and what is refused. The real run MUST report the same categories for what it did.
- **FR-013**: When the decisions to record exceed one store transaction, decide MUST either commit all of them or report exactly which members were recorded and which were not. It is never silent.
- **FR-014**: For a sign-off card, decide MUST re-check the draft's current bytes against the packet's fingerprint. It MUST refuse that sign-off if they differ, with the same freshness rules `review npc sign` applies today.
- **FR-015**: Every decision decide records MUST say which packet it came from, so that a bad page's decisions can be found later.

**Store validation (#655)**

- **FR-016**: The store MUST validate verdict/disposition pairs for the NPC review's claim and presentation item types, on every path a decision can arrive by.
- **FR-017**: For an item type that declares no allowed pairs, the store MUST refuse decisions by default.

**Contract**

- **FR-018**: CampaignGenerator MUST publish schemas for the card packet and the decisions file, with golden example files. Tests MUST fail when an exported packet or an accepted decisions file does not match its schema.
- **FR-019**: decide MUST refuse a packet or decisions file with an unknown major schema version, and name the versions it accepts.

**Kit**

- **FR-020**: The shared kit's NPC card builder MUST get its cards from `review cards export`. Its decision reader MUST apply NPC decisions through `review cards decide`. No kit code may read the review store's files.
- **FR-021**: The Codex skills that used the forked kit MUST use the shared kit, with their per-skill page formats and local serving unchanged. The fork MUST be removed.

**Web face**

- **FR-022**: The review launcher MUST let the GM export a card packet, apply a decisions file, see the plan and confirm before anything is recorded. Each step MUST run the same CLI commands, per constitution VI.

**Behaviour carried over**

- **FR-023**: The existing `review decide`, `review npc sign`, `review noise` and `review export`/`import` commands MUST keep their current behaviour, apart from #655's added refusals.

### Key Entities

- **Card packet**: a stored, immutable snapshot of what a review page may decide. It has an id, the review id, the generation, the schema version and a list of cards. It belongs to one review and is valid until the review's generation moves.
- **Card**: one thing the GM rules on, such as a claim about one sentence, a noise class or a draft sign-off. It has a card id, display text, a member list and, for a sign-off, the draft fingerprint.
- **Member**: one finding in the review store, with the fields needed to record a decision on it.
- **Decisions file**: what a page saves. It holds the packet id, the review id, a verdict per card (approve, reject or discuss), and notes.
- **Decision plan**: the per-card and per-member list of what decide would do, or did.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Applying a GM's saved decisions to a review needs no hand-built decision batch. On the stormgiants-scale fixture review, 100% of recorded decisions come from `review cards decide`, applied straight from the page's file.
- **SC-002**: Each of the bad inputs in User Story 2 records zero decisions and leaves the store byte-identical.
- **SC-003**: Applying the same decisions file twice records nothing the second time. Changing one card's verdict and reapplying records exactly that card's members, all listed as supersedes.
- **SC-004**: For the NPC review's item types, 100% of disallowed verdict/disposition pairs are refused, whichever path they arrive by.
- **SC-005**: A deliberate change to the packet's shape that is not reflected in the published schema makes at least one test fail.
- **SC-006**: Zero kit files read the review store's files directly. Zero Codex skills refer to the retired fork.
- **SC-007**: For a review of about 800 items, export and a full decide each complete within one minute on the GM's machine.

## Assumptions

- The page workflow outside CampaignGenerator is unchanged for now. A Claude page saves through the artifact runtime, and a Codex page is served locally by the kit. The agent then hands the saved file to `review cards decide`. Serving pages over the tailnet, with decisions posted straight back, is slice 2.
- "Review generation" and "draft fingerprint" mean what the per-item custody work (spec 042) defined. A packet becomes stale whenever the generation moves, and per-item freshness at decide time still applies through the existing custody checks.
- The six non-NPC skills' per-skill page formats are out of scope. They move to the shared kit unchanged.
- Card grouping by sentence (#622), recommendations (#623), contradiction refusal (#626), split pages (#627) and carried approvals (#625) are follow-ups. This slice gives them the packet, the single expansion rule and the recorded Discuss and Reject decisions they need.
- mytools changes (the kit shims, retiring the fork) ship as a mytools pull request alongside this feature's CampaignGenerator pull request, as with spec 041. GM-owned uncommitted edits in mytools are never touched.
