NPC verification review that spends the GM's attention only on real decisions (summary_native)

Context. The first full summary_native NPC build of a long campaign (stormgiants, chapters 1–86, 177 NPC drafts) produced a single review of 781 items. Most of the GM's time went on cards that the tooling could have settled itself, or that asked the same question several times. The GM reported, in their own words: "I can't parse this", "it's hard to follow what sentence you are objecting to", "you are asking the same question 4 different ways… it's about the same sentence", and "if you did a grep and read around you could tell me what the answer is. You just brought the deterministic answer to me without any thinking." Measured on that run:
- 400 of the 480 number/ordinal findings were noise:
  - ~281 were chapter labels ("Chapter 036", "chapters 028–064");
  - ~119 were numbers present in another scene the same paragraph cites;
  - the rest were idioms ("third person", "at first"), spelled-out numbers ("five gold pieces", "a thousand") and comma splits ("5,000" read as "5" and "000").
- Status-word findings fired on plain synonyms ("departed"/"leaves", "died"/"dies") and on sentences that say a status is NOT established.
- When an agent read the cited scene and grepped the summaries for each of the 101 remaining claims, it settled 97 with a verbatim quote: 57 supported, 40 wrong, each with a replacement. Only 4 needed the GM's judgment.
- Repeat cards: 134 claim cards collapsed to 61 once findings on the same sentence were merged.
Related existing issues: #616 (review page style), #617 (number/ordinal and status checker false positives).

The design rule still holds: the LLM drafts, deterministic checks flag, and the GM decides every precision call. This feature must cut what the GM has to read, never what the GM decides.

User stories (priority order):

P1 — Deterministic noise never reaches the GM.
The number/ordinal and status checks resolve the cases they can prove on their own, and say exactly which word they object to.
- A number/ordinal is checked against all the scenes the sentence cites (sentence-level, not paragraph-level and not per-citation).
- Chapter and scene labels are recognised as labels, not story facts.
- Spelled-out numbers match their digits ("five" = 5, "a thousand" = 1,000).
- Comma-grouped numbers are one token.
- A curated list of ordinal idioms ("third person", "at first", "first time") is exempt.
- Status words match a reviewed synonym table (departed ~ leave/left/leaves; died ~ dies/dead/killed).
- A sentence that says a status is "not established" is not a status claim.
- Each remaining finding records the flagged token, the sentence (not the paragraph), and the scene(s) that sentence cites.
- Findings resolved this way are recorded as classified noise with their class (label, other-citation, spelled-number, idiom, synonym, negated-status), so the GM can audit them. The GM can turn any class into a standing auto-approve through `review policy`, the same way `typography-normalised` works today. The resolution itself is never silent.

P1 — One card per sentence, and the card shows the evidence.
- All findings on the same draft sentence become one review card. One GM verdict applies to every finding behind it, and each finding still gets its own decision record.
- The card leads with:
  - the sentence, with the flagged tokens highlighted;
  - the text of the scenes it cites;
  - for a status word, any synonyms present in those scenes.
- Raw checker output is folded away.
- The review page uses the shared Approve/Reject/Discuss card kit (#616). The native review UI is not used for GM review.

P1 — Evidence-assisted recommendation for what's left.
For each remaining sentence, an optional assist step:
1. Reads the cited scenes and searches the published summaries.
2. Produces a recommendation: supported / not supported / needs GM. It includes a verbatim quote with file:line, a one-or-two sentence reason, and, when not supported, a full replacement sentence that the summaries do support.
Requirements:
- Every quote is mechanically verified to appear verbatim in the cited file. A recommendation with an unverifiable quote is dropped back to needs-GM.
- The page sorts needs-GM first, then not-supported, then supported, grouped per NPC with the sign-off card after that NPC's claims.
- A recommendation is never recorded as a decision.
- The assist can run on the configured local backend (DGX) or on Claude.

P1 — Source custody is per item, not per review.
Today one edit anywhere stales the whole 781-item review and blocks every sign-off with REVIEW_STALE_CUSTODY. Real triggers that did this: a GM-ruled fix to one chapter summary, one edited draft line, and a background publish racing a draft edit. Instead:
- Only items bound to changed sources go stale.
- The error names the changed files and the affected items.
- `review status` shows stale items by NPC.
- A refresh is never needed to sign off a draft whose bytes, evidence and summaries did not change.

P2 — Reject-with-fix is a first-class path.
When the GM rejects a sentence and accepts the proposed replacement (or writes one in a note), the tool:
1. Replaces exactly that sentence in the draft. The edit must match exactly once, or it refuses.
2. Re-runs npc-verify.
3. Opens a follow-up review for the changed drafts. The sign-off card shows the before/after diff.
4. Carries approvals for identical findings on unchanged lines into the new review, keyed on draft path + finding code + message + exact line text. Today `review carry` carries nothing, because the item ids are new.
If the replacement fails verification (for example, it cites a scene the NPC's evidence lacks), the tool says so on the card, and any adjusted wording is shown to the GM as a change.

P2 — Contradictory decisions are caught before they are recorded.
- Approving a draft sign-off while any claim on that draft is rejected, under discussion or unmarked is refused, with a message. Hit twice in this run: a GM approved a sign-off and rejected a claim on the same draft, and a Discuss note was left on a draft whose sign-off was approved.
- Two cards on the same sentence with conflicting verdicts are surfaced to the GM.
- The page itself explains: "reject a claim → leave the sign-off unmarked; it comes back after the fix."

P2 — Split review pages by work type.
Offer separate pages, each with its own save state:
- "NPCs that need sign-off only": drafts with no open findings, one card per NPC.
- "NPCs with claims to check".
A page is rebuilt from the review's current undecided items. Re-publishing a page never discards the GM's saved marks; it reads them back first.

P2 — Summary fixes propagate visibly.
When a chapter summary (the origin under summaries/) is changed and republished, the tool reports:
- which evidence files changed;
- which drafts cite the changed scenes;
- which published dossiers are now out of date.
It then offers the deterministic rebuild (build → npc-link) and a re-draft for directly affected NPCs. In this run, ruling "Belg is dead" in ch 010 silently changed three NPCs' evidence and staled their approvals.

P3 — Smaller defects hit in this run:
- The linker misses possessive mentions: "Hyuth's mansion" in scene 036.07 was not linked to Hyuth Kolstaag. A GM-approved fix citing it then failed verification as outside-evidence.
- `review create` fails on non-ASCII dossier ids (e.g. "aerasumé"). Ids should be ASCII-slugged.
- `review show --limit 100` returns `data: null` silently. It should cap the limit or raise a clear error.
- `npc-publish` errors with "no summaries directory" unless `--summaries-dir` is passed. It should default to the configured or `docs/summaries`.
- `npc-publish` and draft edits can race. Publishing should take a lock on the review, or snapshot the signed bytes, so a concurrent edit can't make most of a batch fail.
- The drafter emits placeholder speakers ("— Speaker", or an empty speaker) in Notable Quotes. The drafter should be told never to do this, and the verifier should fail the draft instead of advising.
- 4 drafts still fail on a single non-verbatim quote after re-drafting. Offer a targeted quote-repair pass (restore the verbatim text from evidence) before a full re-draft.
- Cross-summary canon conflicts surfaced only by accident: Methrammar's mother is Laeral Silverhand in ch 055 and Alustriel Silverhand in ch 085. Add a check that reports a relationship stated differently in two summaries, as a GM question.

Success criteria (measured on a rerun of the same stormgiants ch 1–86 build):
- Number/ordinal findings reaching the GM: no more than 100 (from 480). Status findings on synonym or negated sentences: 0.
- Claim cards shown to the GM equal the number of distinct sentences (no repeats).
- Every claim card shows the flagged token, the sentence and the cited scene text. With assist enabled, ≥90% of claim cards carry a recommendation with a verified verbatim quote.
- Editing one draft or one summary stales only items bound to the changed files. Sign-offs on unrelated drafts succeed without a refresh.
- A rejected sentence with an accepted fix reaches a follow-up sign-off page with a diff, with no hand-editing of drafts and no hand-built review selections.
- The tool refuses a sign-off that contradicts a recorded claim decision.
- No GM verdict is ever inferred: unmarked stays unmarked, and recommendations are never recorded as decisions.
