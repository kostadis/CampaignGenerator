# Result: a modest change in emphasis, not a solved writing problem

Read the [A/B drafts](comparison.html) before this page if you want an independent
first impression. This page reveals the prompt assignment.

## User preference, recorded after the comparison

The user selected **B**: “i like b more”. In follow-up, the user identified this
passage in A as an irritating narrative sentence structure:

> Nothing has happened to him. I have found a symbol, not a knife at his back.
> I make myself keep that distinction too.

The user then clarified the positive target: **“my prose is straightforward and
simple.”**

Further clarification: the user dislikes the recurring narrative pattern of
“oh i thought x, and then corrected it,” and describes the characters as
“adventurers, men of action.” The desired emphasis is direct perception,
judgment, speech, and action rather than habitual commentary about revising their
own thoughts. This does not require inventing new actions or removing genuine
changes of mind established in the session. Investigation, bargaining, and
conversation remain part of the adventure.

Assistant interpretation: the quoted passage manufactures a dramatic contrast,
negates it, and explains the narrator's self-correction. The adjacent sentence,
“Still, I would like him close enough to hear me,” already expresses Soma's
concern plainly. More explicit interior commentary is not automatically an
improvement under the user's stated preference. Simple prose can still carry
character, humor, feeling, and physical experience.

The treatment's instruction to avoid inventing immediate danger may have
encouraged that conspicuous self-correction; this is a hypothesis, not an
established cause. The preference is recorded as evidence about the desired
writing, not a new production ban on negation, contrast, or interiority.

B is the control: the general adaptation brief from the preceding experiment,
including its cleaned character references and relaxed dialogue-preservation
contract. It is **not** the unchanged production narration pipeline.

For this pair, the intended reader preferred the version without the new
scene-specific composition guidance. The trial therefore does not support
adopting that addition. This is one preference on one pair, not proof that such
guidance is always worse or that a particular feature caused the preference.

The assistant's earlier notes below remain unchanged as a separate judgment.
No draft has been edited or promoted, and no pipeline change follows automatically
from this preference.

## Assignment and initial preference

- **A** used the scene-specific composition block.
- **B** used the existing general adaptation brief.

I recorded my [initial reading notes](blind_review.md) before opening that mapping.
Their SHA-256 at reveal was
`78b5f89762e0b7b8d40ee91548bc21455465553361eb947bfa8fb740667a555d`.
I knew both prompts and the hypothesis; this was not a double-blind study.

My initial preference was small and localized: **A gives the discovery and ending
more character-specific development; B sometimes handles the dialogue more
briskly.** There was no decisive overall winner. The user's judgment may differ.

## What the composition brief visibly changed

In [A](version-A.md), Soma settles her body before borrowing the familiar's senses,
experiences the room at rat scale, returns with her hand tight around Meril's
staff, and later reconsiders the tavern's comforts in light of the office below.
The detail that matters most to me is her recognition that Brewbarry entered
because he could finally afford to: the discovery changes the meaning of an
earlier action without changing that action.

That closely matches the requested editorial direction. It is evidence of
following the brief, and a small literary improvement to my taste. It is not
proof that the improvement is robust, or that every added reflection helps.

A also gives the performance discussion more room. But B already preserves its
complete setup and payoff: two spells versus a contract, the chance of getting
paid, Vukradin admitting that he enjoys performing, and Soma proposing both.
A's extra explanation about an audience and studio income may be redundant.
The test therefore does not show that the new block was necessary to retain
that interaction.

## What it did not fix

| Diagnostic | A: composition | B: control |
|---|---:|---:|
| Words | 1,699 | 1,781 |
| Paragraphs | 117 | 115 |
| Median paragraph length, words | 10 | 11 |
| Quote-led paragraphs | 62 | 58 |
| Quote-led paragraphs of five words or fewer | 20 | 18 |

The broad paragraph rhythm is nearly unchanged. The treatment did not produce
consistently more sustained paragraphs. Those counts are not quality scores;
they simply do not support a claim that fragmentation was substantially reduced.

Both drafts still explain some comic actions after they occur. Both turn
Brewbarry's entry into a short sequence explaining what he did not deliberate
about. A sometimes explains the epistemic boundaries as well: the symbol does
not explain their fame; finding the symbol does not mean finding a knife at
Brewbarry's back. The factual caution is correct, but its presentation can feel
more like a reviewer anticipating errors than Soma spontaneously thinking.

B keeps the theft/rat joke, but removes its original GM provocation. The resulting
denial and Soma's explanation that she never accused Vukradin are less naturally
motivated. A omits that exchange. That is a selection tradeoff, not a simple
quote-coverage win for either draft.

## Factual integrity

Against the supplied reviewed extraction, I found **no consequential factual
contradiction in either version**. The full scope and individual checks are in
the [predeclared criteria](evaluation_criteria.md) and [initial notes](blind_review.md).

Both preserve the investigation, means of entry and discovery, party positions,
unperformed performance proposal, unresolved Harper role, and unresolved source
of the band's fame. Both give the others access to the discovery through Soma's
report. Both maintain the campaign's faction context. Neither invents an attack,
rescue, departure, or confirmed connection between the Harpers and the fame.

This is a source-scene review, not exhaustive certification against the full VTT
or all campaign lore. Imagined thoughts and mundane connective actions were
allowed and were not classified as errors merely because they were unrecorded.

## What this means for the proposed simplification

My earlier proposal should now be narrowed: **specific editorial direction can
shift a scene's emphasis, but this pair does not show that it reliably produces
better scene composition overall.** The control independently accomplishes much
of what the new direction requests.

The intervention also supplied a scene interpretation, not merely a generic
instruction to plan. Even a strong win would not prove that an unattended planner
could devise equally useful interpretations for other sessions. This is not yet
a reason to add another mandatory stage, set paragraph quotas, or change the
production narrator.

The useful next input is the user's reading preference and the particular
passages behind it. Both responses remain unchanged, so that judgment can happen
without a second round of fixes obscuring the comparison.

## Execution checks

Both independent calls completed with attested `gpt-6-astra` / `medium` selection.
The composition call ran for approximately 73 seconds; the control for 77 seconds.
The shared user-message hash is identical. The system prompts differ only in the
declared block. Sources, settings, and output format are unchanged between arms.
There were exactly two generation calls, with no retries, post-generation edits,
or production/campaign changes.
