# NPC Dossier Review: The Human Flow

**Status:** Design record of a flow run by hand, input to a future driver skill and UI work.
**Origin:** Obelisk ch1–12, 2026-10-11 (campaigns PR #393): 6 failing → 32 verified, signed off and published.
**Related:** spec 032 (NPC dossiers from summaries), spec 036 (review adjudication), issue #569
(triage-candidates ignores summary_native), the global rule "LLMs render, humans decide".
**Mechanics** (commands, payloads, scripts) live in the campaigns repo at
`gm-assistant/working/summary-native-npc-dossiers/WORKFLOW.md`. This document covers the
**human** side: what the GM decides, when, from what evidence, and where the tool got in the way.

---

## TL;DR

The pipeline is sound: deterministic verification plus a GM sign-off bound to exact draft bytes.
In practice, a GM cannot get from "N need verifying" to "published" through the UI alone. A
helper (Claude) had to:

1. turn verifier failures into concrete, minimal fix proposals,
2. hand-build the review selection file,
3. separate ~96 advisory flags into a handful of real problems and checker artifacts,
4. present all of it as one reviewable page,
5. check the GM's rejections against the transcripts, and
6. work around a custody rule that voids every sign-off in a review when one draft changes.

Every one of those steps kept a human checkpoint. A driver should mechanise the *evidence
gathering* and *presentation*, and never the rulings.

---

## The GM's decisions, in order

| # | The GM decides | Shown | Volume (Obelisk) | Channel that worked |
|---|---|---|---|---|
| 1 | How to fix each verify failure | before → after line, the evidence span, the failure code | 9 items / 6 NPCs, then 2 sibling fixes | Chat table, one "apply" |
| 2 | Whether each real error the checker *missed* is wrong | claim vs. cited source, side by side | 2 (Mirna, Elsa) | 1×1 questions with keep-verbatim |
| 3 | Approve / reject / discuss each advisory flag | claim, cited source with the number highlighted, the helper's read | 65 line-cards (96 items) | Artifact page, grouped by noise class |
| 4 | Sign off each exact draft | full dossier text + sha256 | 32 | Same artifact page |
| 5 | Resolve rejects that contradict the source | VTT excerpt with timestamps | 3 (Gog ×2, Harbin) | 1×1 questions |
| 6 | Re-rule anything whose bytes changed | the changed line + new sign-off | 2 | 1×1 questions |
| 7 | Ship | — | 1 | Chat |
| 8 | Identity of undrafted names (new / alias / ignore / fix-at-source) | the entry text, related registry entries, the exact registry command | 22 | Artifact page |

The **channel rule** is from the campaigns workspace: over about 12 rulings, use one page the GM marks at
their own pace, not a serial chat queue. An exhausted reviewer rubber-stamps.

---

## What the GM actually needs to see per decision

- **The claim and its cited source, side by side.** The flag code alone is useless to a GM.
- **Why the flag fired**, in plain terms ("the number is in the other citation", "this is a chapter reference").
- **A recommendation that is never pre-selected.**
- **For anything that changes text: the full before → after sentence**, plus a keep-verbatim option.
- **For a sign-off: the whole dossier**, because that is what is being approved.
- **For a reject: the primary source.** The GM's memory and the summary disagreed three times out of three.
  The transcript settled it: the GM accepted two flips and one rewording.

---

## Friction observed (product findings)

### F1. Verify failures arrive as codes, not fixes
`not-found`, `outside-evidence` and `invalid` each have a small set of mechanical causes (paraphrase in
quote marks, case, a citation to an item not in this NPC's evidence, a malformed citation shape).
Each has an obvious minimal fix. The UI shows the report; nothing proposes the fix.
**Want:** a per-failure fix proposal (deterministic where possible) that the GM accepts or edits.

### F2. Fixing a quoted paraphrase leaves its unquoted siblings
After dropping quotes from "substantial gold reserves", the same overreach survived in a History
bullet. Verify cannot see it because it has no quote marks.
**Want:** when a span fails `not-found`, flag near-duplicates of it elsewhere in the draft.

### F3. The review needs a hand-built selection file
`/npcs/review` asks for a JSON file of literal paths. Ticking NPCs on `/npcs/dossiers` does not produce it.
**Want:** "Create review for the ticked / all drafted NPCs" that writes the selection itself, using
all in-range summaries, as `npc-verify` does.

### F4. The number/ordinal advisory is ~97% noise
`_deterministic_semantic_advisories` requires every marker on a line to appear in *each* cited
item separately. Multi-citation lines always fire, and "In Chapter 009, …" counts as the number 009.
Obelisk: 31 chapter-reference lines and 19 covered-number lines, against 0 wrong numbers.
The real errors on flagged lines were semantic (wrong referent, wrong "first"), not numeric.
**Want:** compare against the union of the line's citations; ignore "Chapter N" when N is cited;
then label what remains "needs judgment".

### F5. The checker doesn't catch entailment errors, and says so
"Used a red cloak to signal safety" vs. "the skeletons stood aside because of the red cloaks" passes
every mechanical check. Only reading caught it. This is by design (sign-off is the entailment check).
But the sign-off card should make that the GM's explicit job, with the claim and its source adjacent.

### F6. Custody voids every sign-off when one draft changes
A review snapshots every source's sha256. Editing one draft after creating the review makes
decisions unsaveable (`REVIEW_STALE_CUSTODY`) and makes `_current_draft_signoff` false for **all**
NPCs in it. Obelisk had to rebuild as two reviews (31 + 1) and re-map rulings by item id.
**Want, either:** custody scoped per NPC (each draft's sign-off depends on its own draft and evidence and
the summaries, not on its siblings' drafts); or a "rebind unchanged items" path that carries decisions
for items whose inputs did not change. Item ids are already deterministic, which makes this cheap.

### F7. The review launcher is an operator console, not a review surface
`ReviewLauncher.vue` exposes ~40 fields (grants, TLS, migrations, guard resolutions). Reaching the
actual queue takes Review ID → Start reviewer → Issue private link → open the one-time link.
**Want:** "Review this" opens the queue directly, grouped by decision class, with the side-by-side
evidence from the section above.

### F8. Rejections need a source check before they become actions
All three rejections contradicted the summaries. A reject note is a claim about the world, and it
can be wrong, like any claim. **Want:** a reject on a claim item opens a "check the transcript" panel
(VTT excerpt around the cited scene), and the GM confirms or flips.

### F9. Undrafted NPCs are a registry problem the dossier page doesn't explain
25 NPCs were `exclusion: not in registry` or PCs. Publish says "run npc-draft", which is the wrong
advice. They need registry rulings first. `registry triage-candidates` then surfaced none of them,
because it reads the ensemble corpus (#569).
**Want:** the dossier page routes "not in registry" rows to triage with their evidence. Triage reads
summary_native.

### F10. Summary headings leak into subjects
`Dosa Rook *(Chapter 8 — carried forward, not present this session)*` became an NPC subject.
**Want:** the linker flags subjects containing annotation markup as fix-at-source.

---

## Design for a driver (skill first, UI later)

The driver mechanises the evidence and the paperwork. Each **[GM]** step is a stop.

1. **Assess:** read `/api/npc-dossiers/state`; report fail / pass / undrafted / published.
2. **Propose fixes** for verify failures, plus sibling-span warnings (F1, F2). **[GM]** accept or edit.
3. **Apply, verify, compose** for the touched NPCs.
4. **Read the drafts for semantic errors** on flagged and unflagged lines alike, and propose fixes (F5). **[GM]**
5. **Freeze:** no draft edits after this point (F6).
6. **Build the selection and create the review** (F3).
7. **Classify the advisories:** chapter-ref / covered / needs-judgment (F4).
8. **Publish the review page:** grouped cards, sign-offs with full text, no pre-selection. **[GM]**
9. **Read the record back:** re-ask undecided; for each reject, show the VTT excerpt (F8). **[GM]**
10. If a ruling changes a draft: apply, re-verify, then rebuild only what custody forces, and re-ask only
    the changed items (F6). **[GM]**
11. **Write the decisions** through the decisions API; confirm with the publish gate itself.
12. **Publish** (the UI or CLI). **[GM]** ship.
13. **Route undrafted rows to entity triage** (F9). **[GM]** each identity ruling.

**Never automated:** fix wording, whether a claim is wrong, any verdict, any sign-off, memory vs.
transcript, identity. **Always automated:** state reads, verify/compose, selection files, noise
classification, card building, mapping recorded rulings to item ids, gate checks.

## Numbers from the Obelisk run

| Stage | Count |
|---|---|
| Drafted / failing verify at start | 32 / 6 |
| Verify failure items fixed | 9 (+2 siblings) |
| Real errors found by reading (not flagged as such) | 3 (Mirna, Elsa, Harbin) |
| Review items | 128: 32 sign-off + 96 advisory (number, ordinal, status, typography) |
| Advisory lines on the GM page / real errors among them | 65 / 1 (Harbin); Mirna and Elsa were caught before the page |
| GM rulings: approve / reject / discuss / undecided | 94 / 3 / 0 / 0 (cards) |
| Rejects contradicted by source | 3 of 3 (2 flipped, 1 reworded) |
| Reviews created to satisfy custody | 4 (2 superseded) |
| Published | 32; 25 refused (not in registry or PCs) |
