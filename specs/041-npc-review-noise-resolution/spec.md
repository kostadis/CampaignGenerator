# Feature Specification: NPC Review Noise Resolution

**Feature Branch**: `041-npc-review-noise-resolution`

**Created**: 2026-11-12

**Status**: Draft

**Input**: GitHub issue #621 (P1 sub-issue of tracking issue #618, extends #617): "NPC review: deterministic noise never reaches the GM" — the summary_native NPC verification number/ordinal and status checks should resolve the cases they can prove on their own, and say exactly which word they object to. Source document: `docs/design/NpcReviewBurden_specify_input.md` (PR #620).

## Background

The first full summary_native NPC build of a long campaign (stormgiants, chapters 1–86, 177 NPC drafts) produced one review of 781 items. Of the 480 number/ordinal findings, 400 were noise:

| Noise class | Approx. count | Example |
|---|---:|---|
| Chapter/scene label read as a story fact | 281 | "In Chapter 036, Blasius…", "chapters 028–064", a leading list numeral "1." |
| Number present in another scene the same line cites | 119 | line cites 085.07 and 085.08; "200" is in 085.07 only |
| Ordinal idiom, spelled-out number, comma split | remainder | "third person", "at first", "five gold pieces", "a thousand", "5,000" read as "5" and "000" |

Status-word findings fired on plain synonyms ("departed" vs "leaves", "died" vs "dies") and on sentences that say a status is *not* established ("No further status (alive, dead, escaped) is established").

Two further problems made the real findings hard to act on. The card never named the flagged word, and the "claim" it showed was a whole paragraph. The GM said: "I can't parse this", and "it's hard to follow what sentence you are objecting to".

This feature cuts what the GM has to read. It must never cut what the GM decides.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Labels, idioms and number spellings are not flagged as story facts (Priority: P1)

The GM runs NPC verification on a draft whose prose mentions chapter labels ("In Chapter 036…", "chapters 028–064"), a list numeral, an ordinal idiom ("for the first time", "at first", "third person"), a spelled-out number whose scene states it in digits ("five gold pieces" vs "5 gp"), and a comma-grouped number ("5,000"). None of these becomes a number/ordinal finding asking the GM to judge a story fact. Each is recorded as classified noise with its class, and the GM can audit it.

**Why this priority**: Labels alone were 281 of the 480 findings. This story removes the largest share of noise with the least risk, because a label or idiom is never a story fact.

**Independent Test**: Verify a fixture draft that contains each pattern above alongside one genuinely unsupported number. Exactly one number/ordinal finding reaches the GM, and every other occurrence appears in the classified-noise record under its class.

**Acceptance Scenarios**:

1. **Given** a draft sentence "In Chapter 036, Blasius warns the party [ch 036 / 036.04]", and scene 036.04 contains no "036", **When** verification runs, **Then** no number/ordinal finding is raised, and "036" is recorded as classified noise of class `label`.
2. **Given** a sentence that says "five gold pieces" and a cited scene that says "5 gp", **When** verification runs, **Then** the numbers match, no finding is raised, and the occurrence is recorded as class `spelled-number`.
3. **Given** a sentence that says "a thousand giants" and a cited scene that says "1,000 giants", **When** verification runs, **Then** the numbers match.
4. **Given** a sentence that says "5,000 gold", **When** verification runs, **Then** "5,000" is treated as one number. If the number is unsupported, the finding names "5,000", never "5" and "000".
5. **Given** a sentence that says "for the first time", **When** verification runs, **Then** "first" is recorded as class `idiom` and raises no ordinal finding.
6. **Given** a sentence that says "the third giant to fall" and no cited scene that supports "third", **When** verification runs, **Then** an ordinal finding IS raised, because the phrase is not on the curated idiom list.

---

### User Story 2 - Numbers are checked against every scene the sentence cites (Priority: P1)

A sentence that cites two scenes is not flagged when its number appears in either of them. A number absent from every scene the sentence cites is still flagged, and the finding names the token, the sentence and the scenes.

**Why this priority**: This class accounts for about 119 findings. The current per-citation comparison is what flags them, and the finding never says which number is meant.

**Independent Test**: A fixture sentence cites scenes A and B. It contains "200", which is present only in A, and "40", which is present in neither. Exactly one finding is raised, for "40". It names "40", the sentence, and both A and B.

**Acceptance Scenarios**:

1. **Given** a sentence citing [ch 085 / 085.07] and [ch 085 / 085.08], where "200" appears only in 085.07, **When** verification runs, **Then** no number finding is raised for "200", and the occurrence is recorded as class `other-citation`.
2. **Given** a sentence citing two scenes with "40" in neither, **When** verification runs, **Then** one finding is raised. It records the flagged token "40", the sentence (not the paragraph), and both cited scenes. Its message reads in the form: draft says "40"; no scene this sentence cites contains it.
3. **Given** a paragraph of three sentences that each cite different scenes, **When** verification runs, **Then** each sentence's numbers are compared only against that sentence's own citations, and each finding shows only its own sentence.

---

### User Story 3 - Status words accept reviewed synonyms and ignore negated statements (Priority: P1)

A draft that says an NPC "departed" is supported by evidence that says the NPC "leaves" or "left". "Died" is supported by "dies", "dead" or "killed". A sentence that says a status is *not* established is not treated as a status claim at all. A status word with no supporting word or synonym is still flagged, and the finding names the word and the sentence.

**Why this priority**: Status findings on synonyms and negations are pure noise, and they look like serious claims ("dead"), which makes them expensive to dismiss.

**Independent Test**: A fixture draft contains "departed" (evidence: "leaves"), "No further status (alive, dead) is established", and "captured" (evidence has no word for it). Exactly one status finding is raised, for "captured".

**Acceptance Scenarios**:

1. **Given** a draft that says "Hekaton departed Maelstrom" and evidence that says "Hekaton leaves Maelstrom", **When** verification runs, **Then** no status finding is raised, and the occurrence is recorded as class `synonym`, naming the evidence word matched.
2. **Given** a draft sentence "No further status (alive, dead, escaped) is established", **When** verification runs, **Then** no status finding is raised for "alive" or "dead", and both occurrences are recorded as class `negated-status`.
3. **Given** a draft that says "Belg was captured" and evidence with no synonym of "captured", **When** verification runs, **Then** a status finding is raised that records the word, the sentence and the scenes the sentence cites.
4. **Given** a synonym pair that is not in the reviewed table, **When** verification runs, **Then** the status word is flagged. The checker never guesses synonyms beyond the table.

---

### User Story 4 - The GM can audit classified noise and choose to auto-approve a class (Priority: P1)

After verification, the GM can see every occurrence the checks resolved as noise, grouped by class, each with its token, sentence and cited scenes. Nothing is resolved silently. The GM can also state, through the existing review policy mechanism, that a class is always approved, in the same way `typography-normalised` is handled today.

**Why this priority**: The resolution is deterministic, but the classes are heuristics. The GM must be able to check that "label" really was a label before trusting it. Without the audit, this feature would be an Optimistic Lie.

**Independent Test**: Run verification on a fixture with occurrences of every class. Open the audit record and confirm that each class lists its occurrences with token, sentence and scenes. Apply a review policy naming one class and confirm that only that class's items are approved, each with a note naming the policy and the class.

**Acceptance Scenarios**:

1. **Given** a verified draft, **When** the GM inspects its verification output, **Then** a classified-noise section lists every resolved occurrence by class (`label`, `other-citation`, `spelled-number`, `idiom`, `synonym`, `negated-status`), with counts.
2. **Given** classified noise in a review, **When** no policy covers its class, **Then** the GM sees one batch card per class. The card shows the class, its count and every occurrence (token, sentence, cited scenes), and the GM approves or rejects the class once. Each occurrence still gets its own decision record from that one verdict.
3. **Given** a class batch card that the GM leaves unmarked, **When** the GM views the review, **Then** every occurrence in that class remains undecided. No verdict is inferred.
4. **Given** a class batch card that the GM rejects, **When** the decision is recorded, **Then** that class's occurrences are rejected, and the rejection is visible as GM disagreement with the classification, for follow-up on the tables or rules.
5. **Given** a review policy that names the class `label`, **When** the GM applies it, **Then** every `label` item is approved with a note naming the policy and class, and no item of any other class is touched.

---

### Edge Cases

- **A sentence with no citation of its own** (for example, the citation sits at the end of the bullet): the sentence inherits the citations of the line it is on. It never inherits the citations of other lines.
- **Comma-grouped number vs. a list of numbers**: "5,000" (grouping: 1–3 digits, then groups of exactly three) is one token. "5, 6 and 7" is three tokens.
- **Ranges in prose** ("chapters 028–064", "ch 12-14"): the whole range is a label when it follows a chapter or scene word. A bare story range ("3–4 giants") is a number claim.
- **A label word that is also a story number** ("the giant lost 36 hit points in Chapter 36"): only the occurrence attached to "Chapter" is a label. The "36" in "36 hit points" is still checked.
- **Spelled-out numbers above the curated range or in compound form** ("three hundred and twelve"): if the spelled form cannot be converted confidently, it is checked as written and never silently passed.
- **Ordinal idiom that is also a literal claim**: only the exact curated phrases are exempt. "first" on its own is checked.
- **Negation scope**: only an explicit not-established construction ("no … status … is established", "status is not established", "not known whether … alive or dead") makes a sentence a non-claim. A sentence that merely contains "not" elsewhere ("he did not flee; he died") is still a status claim for "died".
- **Synonym table vs. a draft word in a different form** ("dying" vs "died"): matching covers the table's listed forms only. An unlisted form is flagged, and the table is the place to fix it.
- **An occurrence that would fall into two classes**: it is recorded under exactly one class, chosen by a fixed, documented precedence order, so counts never double-count.
- **Existing reviews built before this feature**: their items keep their recorded codes and decisions. The new classification applies to verification runs after the feature lands.

## Requirements *(mandatory)*

### Functional Requirements

**Number/ordinal check**

- **FR-001**: The check MUST compare each number/ordinal in a draft sentence against the union of the text of every scene that sentence cites. A number found in any of them is supported.
- **FR-002**: The unit of comparison MUST be the sentence, not the line or paragraph, and not a single citation. A sentence with no citation of its own inherits the citations of the line it is on (see Edge Cases).
- **FR-003**: The check MUST recognise chapter and scene labels as labels and exclude them from comparison: `Chapter N`, `Chapters N–M`, `ch N`, `scene N`, a citation-format scene id, a chapter range after a chapter word, and a leading list numeral.
- **FR-004**: Spelled-out numbers MUST match their digit forms in both directions ("five" = 5, "a thousand" = 1,000, "twelve" = 12), within a documented supported range.
- **FR-005**: Comma-grouped numbers ("5,000", "1,250,000") MUST be one token for both extraction and comparison.
- **FR-006**: A curated list of ordinal idioms (at least "first time", "at first", "third person") MUST be exempt from the ordinal check. The list MUST be a reviewable data file, separate from the matching logic.

**Status check**

- **FR-007**: A status word in a draft MUST be supported by the word itself or by any synonym listed for it in a reviewed synonym table (at least: departed ~ leave/left/leaves; died ~ dies/dead/killed). The table MUST be a reviewable data file, separate from the matching logic.
- **FR-008**: The check MUST treat a sentence that states a status is not established as a non-claim, and raise no status finding for the status words inside it.
- **FR-009**: The status check MUST NOT infer synonyms beyond the table. A word or form not in the table that has no literal support is flagged.

**Finding content**

- **FR-010**: Every number/ordinal or status finding that reaches the GM MUST record the flagged token or tokens, the sentence containing them (not the paragraph or line), and the scene(s) that sentence cites.
- **FR-011**: The finding's human-readable message MUST name the flagged token, for example: draft says "40"; no scene this sentence cites contains it.

**Classified noise**

- **FR-012**: Every occurrence the checks resolve on their own MUST be recorded as classified noise, with its class (`label`, `other-citation`, `spelled-number`, `idiom`, `synonym`, `negated-status`), the token, the sentence, the cited scenes and, for `synonym` and `other-citation`, the evidence word or scene that resolved it.
- **FR-013**: Resolution MUST never be silent. The classified-noise record MUST be visible in the verification output a GM reads, with per-class counts.
- **FR-014**: Each occurrence MUST belong to exactly one class, chosen by a fixed precedence order that is documented alongside the class definitions.
- **FR-015**: The GM MUST be able to make any class a standing auto-approve through the existing review policy mechanism, exactly as `typography-normalised` works today. A policy approval MUST carry a note naming the policy and the class.
- **FR-016**: Classified noise MUST NOT be recorded as a GM decision unless the GM's own standing policy says so. The handling of classified noise not covered by a policy is defined in FR-017.
- **FR-017**: Classified noise not covered by a standing policy MUST be presented to the GM as one batch card per class per review, not one card per occurrence. The card MUST list every occurrence in the class (token, sentence, cited scenes, resolving evidence). One GM verdict on the card applies to every occurrence in it, and each occurrence MUST receive its own decision record carrying that verdict. An unmarked class card leaves every occurrence undecided. *(Clarified 2026-11-12, Q1 → option B.)*
- **FR-017a**: A class covered by a standing policy MUST NOT be shown as a batch card. Its occurrences are approved by the policy (FR-015), and they remain visible in the classified-noise audit record (FR-013).

**Invariants**

- **FR-018**: The checks MUST remain deterministic and make no model call. Classification is code, not a model judgment.
- **FR-019**: A genuinely unsupported number, ordinal or status word MUST still reach the GM. The fixture suite MUST include at least one true positive per class boundary (for example, a non-idiom "first", an unlisted synonym, a number absent from every cited scene).

### Key Entities

- **Sentence-scoped claim**: one draft sentence, its citations (its own, or inherited from its line), and the number/ordinal/status tokens it contains.
- **Finding (number/ordinal/status)**: a GM-facing objection. It carries the code, the flagged token(s), the sentence, the cited scenes and a message that names the token.
- **Classified-noise occurrence**: a token the checks resolved without the GM. It carries its class, token, sentence, cited scenes and the resolving evidence where applicable. It is never a decision by itself.
- **Noise class**: one of `label`, `other-citation`, `spelled-number`, `idiom`, `synonym`, `negated-status`, with a documented precedence order.
- **Reviewed tables**: the ordinal-idiom list and the status-synonym table. They are data files changed through normal code review, never by a model.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a rerun of the stormgiants chapters 1–86 NPC build, no more than 100 number/ordinal findings reach the GM (down from 480).
- **SC-002**: On the same rerun, 0 status findings are raised on sentences whose status word has a listed synonym in the evidence, or on not-established sentences.
- **SC-003**: Every number/ordinal or status finding that reaches the GM names its flagged token, shows a single sentence and lists the cited scenes: 100% of findings, checked by inspection of the rerun's review.
- **SC-004**: Every one of the 80 genuinely unsupported number/ordinal findings identified in the #617 analysis (42 lines, 26 drafts) still reaches the GM on the rerun, checked against the GM noise rulings recorded in `~/storm-giant/stormgiants/docs/reviews/npc-review-6ee694eebf5b/requests/`. No true positive is lost.
- **SC-005**: Every occurrence the checks examine ends up in exactly one of: supported by its cited scenes, classified noise (one class), or a GM-facing finding. The three counts are reported and sum to the total examined, so nothing goes unaccounted for.
- **SC-006**: Applying a single-class review policy approves only items of that class, each with a note naming the policy and the class.
- **SC-007**: On the stormgiants rerun with no standing policy, the GM sees at most one batch card per noise class (at most 6 cards) in place of about 400 individual noise cards.

## Assumptions

- The stormgiants chapters 1–86 build and its two existing reviews (`npc-review-6ee694eebf5b`, `npc-review-8e7e7ca1760a`) remain available as the measurement baseline.
- The ordinal-idiom list and status-synonym table are repo-level data shipped with the tool and changed by pull request. Per-campaign extensions are out of scope for this feature.
- The supported range for spelled-out numbers covers units, teens, tens, "hundred", "thousand", "million" and the article forms ("a hundred", "a thousand"). Anything outside it is checked as written.
- Merging findings into one card per sentence (#622), evidence-assisted recommendations (#623) and per-item custody (#624) are separate features. This feature only changes what the checks emit and how classified noise is recorded and audited.
- The status check keeps comparing against the NPC's full evidence text, as it does today. Its findings additionally record the scenes the sentence cites, for the GM's reference.
- Reviews created before this feature are not rewritten. Re-verifying a draft after this feature lands produces findings in the new form.
