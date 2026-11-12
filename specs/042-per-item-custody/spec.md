# Feature Specification: Per-Item Source Custody for NPC Review

**Feature Branch**: `042-per-item-custody`
**Created**: 2026-11-12
**Status**: Draft
**Input**: GitHub #624 (P1, "source custody is per item, not per review") and #633 (P3, "npc-publish races concurrent draft edits"). Both are sub-issues of #618. The rule: check only the bound sources of the items being decided; the error names the changed files and the affected items; `review status` shows stale items by NPC; publishing works from the signed bytes. **Precision rule: never weaken the check for the items actually being decided.**

## Background

An NPC review is one store of many items. In the stormgiants ch 1–86 build it held 781 items over 412 tracked source files: 164 drafts, 164 evidence files and 84 chapter summaries. Today every decision save re-checks **all 412 files**. If any one differs, the save is refused with `REVIEW_STALE_CUSTODY: source bytes changed`, which names neither the file nor the items. In one session this stopped every sign-off three times:

- a GM-ruled fix to one chapter summary;
- one edited draft line;
- a background publish that raced a draft edit.

Publishing has the same coupling. A draft sign-off counts as current only if every source of the review it came from is unchanged. So editing one NPC's draft makes the publish of every other NPC in the batch refuse. That is the "most of the batch failed" incident in #633.

What each item records about its sources today (read from the real review):

| Item kind | Count | Files it records |
|---|---|---|
| Claim against evidence | 452 | that NPC's draft and evidence file |
| Presentation | 165 | that NPC's draft and evidence file |
| Draft sign-off | 164 | that NPC's draft only |

No item records a chapter summary. Summaries are protected today only by the review-wide check. A per-item check that used only these recorded files would therefore *weaken* protection: a sign-off could be recorded after a summary that NPC depends on was corrected. That is exactly the case the precision rule forbids.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - An edit stales only what depends on it (Priority: P1)

The GM fixes one line in one NPC's draft, or corrects one chapter summary, in the middle of a review. The GM then keeps deciding on the other NPCs' cards and signs off other drafts, without any refresh. A decision on an item that depends on the changed file is refused.

**Why this priority**: this is the defect that stalled every sign-off three times in one session (#624).

**Independent Test**: build a review over several NPCs, change one NPC's draft bytes, then (a) decide on an item of another NPC, which must succeed, and (b) decide on an item of the edited NPC, which must be refused.

**Acceptance Scenarios**:

1. **Given** a review over NPCs A and B, **When** A's draft changes and the GM approves B's sign-off, **Then** the decision is recorded with no refresh.
2. **Given** the same change, **When** the GM decides on any item of A that depends on A's draft, **Then** the decision is refused and nothing is written for any item in the batch.
3. **Given** a review, **When** a chapter summary that A's evidence draws on changes, **Then** decisions on A's items are refused, and decisions on B's items (whose evidence does not draw on that chapter) succeed.
4. **Given** a decision batch that mixes current and stale items, **When** it is saved, **Then** the whole batch is refused (no partial write), and the refusal lists every stale item in it.

---

### User Story 2 - A refusal says exactly what changed and what it affects (Priority: P1)

When a decision is refused for stale custody, the GM sees which files changed and which of the submitted items depend on them, grouped by NPC. The GM does not have to guess or refresh the whole review to find out.

**Why this priority**: the current message names nothing, so the only remedy the GM has is a whole-review refresh.

**Independent Test**: change two files, submit a batch touching both, and read the refusal.

**Acceptance Scenarios**:

1. **Given** a refused decision, **When** the GM reads the refusal (CLI and web), **Then** it lists each changed file by its campaign-relative path, and for each, the submitted item ids that depend on it, with the NPC each item belongs to.
2. **Given** a refused decision, **When** the GM reads it, **Then** it names the command that brings the stale items current.

---

### User Story 3 - Review status shows stale items by NPC (Priority: P1)

Before deciding anything, the GM asks the review for its status and sees which NPCs have items whose sources changed since the review was built, and how many such items each has. This is computed from the current files, not only from past refreshes.

**Why this priority**: it lets the GM work on unaffected NPCs and see what a fix will cost before saving.

**Independent Test**: change one draft and one summary, then run `review status`.

**Acceptance Scenarios**:

1. **Given** unchanged sources, **When** the GM asks for status, **Then** no NPC is listed as stale.
2. **Given** A's draft changed, **When** the GM asks for status, **Then** A is listed with its stale item count and the changed file. No other NPC is listed.
3. **Given** a summary changed, **When** the GM asks for status, **Then** every NPC whose evidence draws on that summary is listed, and no other.

---

### User Story 4 - Publishing one NPC never fails because another NPC changed (Priority: P3)

The GM publishes a batch of signed NPCs while editing a different NPC's draft, or after it. Every signed NPC whose own sources are unchanged publishes. Only an NPC whose own signed sources changed is held, and its receipt says why. What is written to the published dossier is exactly the content behind the signed draft bytes.

**Why this priority**: it removes #633's batch failure. It is lower priority because it follows from US1's rule applied to publishing.

**Independent Test**: sign A and B, change A's draft, publish both.

**Acceptance Scenarios**:

1. **Given** A and B are signed and then A's draft changes, **When** the GM publishes A and B, **Then** B is published and A is held with a reason naming its changed draft.
2. **Given** a chapter summary that B's evidence draws on changes after B was signed, **When** the GM publishes B, **Then** B is held, naming the summary.
3. **Given** a draft that changes while a publish is running, **When** the publish writes an NPC, **Then** the published body is the one bound to the signed draft bytes, never bytes read after the check. An NPC whose draft changed between the check and the write is held, not published with mismatched content.

---

### Edge Cases

- **A file is deleted or renamed**: it counts as changed for every item that depends on it.
- **A change and then a change back** (the bytes are identical again): items are current again. Custody is by content, not by modification time.
- **An item that depends on no file at all**: this cannot be produced today. If one appears, it is treated as stale and refused (reported as `no_dependency`, since there is no file to name), never as trivially current.
- **The decision batch is a class or sentence card covering many items**: the batch is all-or-nothing, so one stale member refuses the batch and the refusal lists it.
- **A withdrawal (retracting a decision) on a stale item**: allowed. Withdrawing never asserts anything about the sources, and blocking it would trap a wrong decision behind a refresh.
- **Import of a decision bundle** (exported from another copy): per-item byte checks over the bundle's items, plus the existing whole-review digest comparison (FR-010).
- **The review was refreshed** (generation bumped) while the GM's page was open: the existing generation check still applies and is unchanged by this feature.
- **A summary's evidence mapping cannot be established for an item** (for example an evidence file with no recognisable chapter references): the item depends on all summaries of the review, the conservative case.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A decision save MUST check custody only for the items in that save, against each item's **dependency set** (FR-003). It MUST NOT check sources that none of those items depends on.
- **FR-002**: For every item in a save, every file in its dependency set MUST be byte-identical to the content recorded when the review was built (or last refreshed). If any differs, is missing or is unreadable, the whole save MUST be refused and nothing written. The check for the items being decided is never weaker than today's check restricted to the files those items depend on.
- **FR-003**: An item's dependency set MUST be:
  - the files the item records (its draft, its evidence file); **plus**
  - the chapter summaries that its NPC's evidence file names as a `Source:`. If none can be read, the set is all summaries recorded by the review (FR edge case).

  **GM ruling (2026-11-12):** a summary change stales only the items of NPCs whose evidence names that summary. It does not stale every item, and summaries are not ignored.
- **FR-004**: A draft sign-off MUST depend on that NPC's draft **and** its evidence file **and** the summaries per FR-003, even though today it records only the draft. A sign-off must never be recorded or honoured after the evidence it was verified against has changed.
- **FR-005**: A stale-custody refusal MUST name every changed file (campaign-relative path, and whether it changed or is missing). For each file it MUST name the submitted items that depend on it and their NPC. It MUST name the remedy that brings them current: `review refresh`, and, when a draft changed, a new `npc-verify` and review, because a sign-off records the exact draft bytes. The refusal code stays `REVIEW_STALE_CUSTODY`, so existing callers keep working.
- **FR-006**: The CLI (`--json` and text) and the web review routes MUST carry the same structured refusal detail (files → items → NPC).
- **FR-007**: `review status` MUST report, from the current files, each NPC with one or more stale items: the NPC, the count of stale items, and the changed files. It MUST report nothing stale when nothing changed. The existing counts it shows MUST be unchanged.
- **FR-008**: Bringing stale items current MUST remain the existing explicit refresh path. This feature MUST NOT refresh, rebind or re-verify anything automatically.
- **FR-009**: A withdrawal MUST be allowed on a stale item. It still records who withdrew and when.
- **FR-010**: Importing a decision bundle MUST check the bytes of each bundle item's dependency set under FR-002 and FR-003, and refuse with FR-005's detail. This is **in addition to** the existing whole-review custody-digest comparison. That comparison checks two records, not files, so file edits never trip it, and it still guards against a bundle exported from a copy that has diverged. Removing it would weaken protection.
- **FR-011**: When publishing, a sign-off MUST count as current if and only if the signed item's dependency set (FR-003/FR-004) is unchanged, whatever the state of other NPCs' sources in the same review. This applies whether or not the caller supplies a dependency graph; a supplied graph may narrow nothing below FR-003.
- **FR-012**: A publish MUST write, for each NPC, only content bound to the exact draft bytes whose sign-off was checked. If the draft bytes differ at write time from those checked, that NPC MUST be held with a reason, and the others continue. Each NPC still gets its own outcome; a hold for one never stops another.
- **FR-013**: A published NPC's receipt and a held NPC's reason MUST name the changed file(s) when custody is the cause.
- **FR-014**: The review-wide custody record (the review's source list and digest) MUST remain as it is, for export, refresh and audit. Only the decision-time and publish-time checks change.
- **FR-015**: No model is called anywhere in this feature.

### Key Entities

- **Item dependency set**: the files whose content an item's decision rests on: the item's recorded files plus the summaries its NPC's evidence draws on.
- **Stale item**: an item with at least one file in its dependency set whose current content differs from the recorded content, or is missing.
- **Custody refusal detail**: changed file → items depending on it → NPC, plus the remedy command.
- **Stale-by-NPC status**: per NPC, its stale item count and the changed files.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After editing one NPC's draft in the 164-NPC stormgiants review, decisions and sign-offs on every other NPC succeed with no refresh: 0 refusals for the other 163.
- **SC-002**: After editing one draft or one summary, the set of items refused equals exactly the set of items whose dependency set contains that file. There are no false refusals and **no missed refusals** (the precision rule).
- **SC-003**: Every stale-custody refusal names every stale item in the submitted batch, and for each one either the changed file(s) or `no_dependency`. No refusal is left unnamed.
- **SC-004**: Publishing N signed NPCs after editing one of them publishes N−1 and holds 1, with the held NPC's reason naming the file.
- **SC-005**: Replayed read-only on the stormgiants review: changing any one draft stales only that NPC's items: 4.8 on average and 19 at most (`bob_saget`), against all 781 today. Changing chapter 010's summary stales only the NPCs whose evidence draws on chapter 010.
- **SC-006**: No existing review test that exercises a refusal on a changed source the decided item depends on starts passing a decision it used to refuse.

## Assumptions

- The evidence file for an NPC names the summaries it was drawn from. Verified on stormgiants: the frontmatter has `chapters: [4]`, and each entry carries `- Source: docs/summaries/004-session-clan-licehair.md (line 171)`. FR-003 uses those exact summary paths and falls back to "all summaries" when none can be read.
- Refresh (`review refresh`), the generation check, export and the decision ledger format are unchanged. This feature changes when a save is refused, and what the refusal says.
- Single GM, single machine. The existing authority lock still serialises writers; the publish rule (FR-012) is about a draft edited by a person or another tool between the check and the write.
- The stormgiants checkout (`~/storm-giant/stormgiants`) is read-only and is used only for a replay measurement.
- A summary fix that *adds* a mention of an NPC whose evidence does not yet cite that summary stales nothing, because that NPC's evidence must be rebuilt first. Reporting this is #628.
- Out of scope: #628 (reporting which dossiers a summary fix affects and offering a rebuild), sentence cards (#622), the reject-with-fix loop (#625).
