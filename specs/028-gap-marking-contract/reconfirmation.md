# Re-confirmation — the ported contract against the 31 accepted gaps

**Run 2026-09-08.** `claude-fable-5-1`, effort `medium` (explicit), backend `claude-code`,
32,000-token ceiling — the configuration the contract was tested at. Raw runs in
`experiments/20260908-454-reconfirm/`.

## What was held fixed, and what changed

One variable. The user turn is the **byte-identical** frozen prompt from the confirmation run —
same scene material, same campaign style, same character references, same POV plan, same prose
example. Only the system prompt differs: `build_narrate_system(gap_marking=True)` in place of
the standalone `prompts/system.md`.

## Result — the port passes

| Arm | Accepted | Run 1 | Run 2 | Accepted gaps covered | dialogue/narration |
|---|---|---|---|---|---|
| brewbarry | 6 | 3 | 5 | **6 / 6** | 5.4× |
| soma | 12 | 15 | 16 | **12 / 12** | 4.2× |
| valphine | 4 | 4 | 5 | **4 / 4** | 3.9× |
| vukradin | 9 | 11 | 10 | **9 / 9** | 6.2× |
| **total** | **31** | 33 | **36** | **31 / 31** | — |

Every one of the 31 gaps the GM accepted is covered in run 2, checked individually rather than
by count. Boundaries move in both directions — brewbarry's accepted #1 split into two markers
while #2+#3 and #5+#6 each merged into one — which the spec predicted and said settles nothing.

**Five markers have no accepted counterpart** and are for the GM to rule on, not for this
document to score: Aldric's concerned look as he opens the conversation, the receiving chamber's
occupants, Jenna Roscoe looking more appalled than before, Vukradin's band announcement, and
Aurelan taking out paper and quill. All are GM description, which is what the contract gaps.

### SC-009 — the bundle path, on its own evidence

| Scene | Per-scene | Bundle |
|---|---|---|
| brewbarry | 5 | 5 |
| soma | 16 | 15 |
| valphine | 5 | 5 |
| vukradin | 10 | 14 |
| **total** | **36** | **39** |

39 markers in one exchange against 36 from four separate calls; every scene emitted markers, none
came back empty, dialogue 222 lines against 39 of narration. The Q2 ruling admitted the bundle
path on per-scene evidence; it now has its own, and the failure condition — a bundle marking
materially fewer gaps — did not occur.

## What run 1 found, and why the run existed

Run 1 (preserved at `per-scene-run1-missing-npc-clause/`) failed in **two opposite directions**
from **one** cause, and neither would have been visible without rendering:

- **soma over-gapped.** Two `**GM** — *as the sun priest*` turns carrying verbatim NPC dialogue
  came back as markers. The accepted render had written them as
  `"But why do you insist on the pain?"`.
- **brewbarry under-gapped.** The opening GM recap was absorbed into the narrator's voice —
  *"The door of the Spire closes behind us. The necklace is gone."* — which is the contract's
  central prohibition.
- **valphine and vukradin were unaffected**, and that contrast is the diagnosis. valphine's
  labels are `**[GM, as the banker]**`, so the NPC's identity is in the label; vukradin has 40
  bare `**[GM]**` labels and no qualified ones. Only soma's form puts the identity in an italic
  context line.

The cause was a deleted clause: `writing_brief.md`'s sentence had two halves, only the first
conflicted with the contract, and the gap variant replaced both — removing "NPC speech voiced by
the GM remains NPC speech", which the contract never restates. `research.md` D3 had reasoned
this out correctly and it was applied to `prose_mode.md` and not to `writing_brief.md`.

Restoring it inside the GM-turn taxonomy — adjudication → dropped, NPC speech → dialogue,
description → gapped — fixed **both** symptoms. Guarded by
`tests/test_gap_marking_prompt.py::test_gap_mode_keeps_the_rule_that_gm_voiced_npc_speech_is_dialogue`.

## Corrections made while reading these runs

Recorded because each was stated before it was checked, and each was wrong:

1. **`writing_brief.md` ¶2 was not a third text needing reconciliation.** Offered as the cause of
   brewbarry's absorption from a single arm; the clause restoration fixed brewbarry with ¶2
   untouched. Withdrawn.
2. **The dialogue/narration ratios were mismeasured, twice.** The comparison harness counted a
   line as dialogue only if it *started* with a quote; the original counts a quote anywhere. Soma
   was reported as 1.4×, "below the band" — the comparable figure is 4.2×, and it rose rather
   than fell. Fixed in `run.py::_classify` and `compare.py`, stored classifications recomputed.
3. **Marker counts were read as directional verdicts.** "16 is the wrong direction" and "brewbarry
   lost accepted #6" were both wrong: soma's extra markers are description, and #6 merged into an
   adjacent marker. The spec says counts settle nothing on their own; that applies to the person
   reading them too.

## What this does not establish

That the five new markers are the right ones. Only the GM, against the source, can say — the same
limit the original confirmation recorded, and the reason `accepted_gaps.json` exists.
