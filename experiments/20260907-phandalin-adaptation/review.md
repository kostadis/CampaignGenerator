# Evaluation: the record can support a freer adaptation

**Verdict: promising feasibility result, not a finished solution.** The new
chapter preserves the consequential events I checked and removes conspicuous
transcript debris without becoming a dry synopsis. It also loses a useful comic
qualification and retains much of the original short-beat paragraph rhythm.

Read the [unedited chapter](response.md) or the
[scene-by-scene comparison](comparison.html). The
[experiment design](README.md) records its limits. This is an editorial review,
not a full rerun of the production checking pipeline.

## What works

### Facts need not retain their original verbal packaging

In the historical chapter's first scene, Vukradin says “new drow advisor that
we will,” and the narrator explains that the sentence lacks an ending. The new
version simply conveys the established rumor and the suspicion that the advisor
could be Valphine's sibling, without confirming the identity.

Likewise, the old conclusion separately stages “level,” “Basement level,” and
“Went down, alright.” The new chapter supplies “Back office. Desk, papers,
supplies. Basement level.” in an intelligible report from Soma to the others.
It preserves the discovery, not the table's process of clarifying it.

Sources: [scene 1](inputs/Phandalin/summaries/20260902/scene_extractions_smoothed/01_rumors_and_preparations_at_the_common_chord.md)
and [scene 5](inputs/Phandalin/summaries/20260902/scene_extractions_smoothed/05_the_dead_drop_at_the_house_of_a_thousand_faces.md).
Compare their corresponding sections in [baseline.md](baseline.md) and
[response.md](response.md).

### The players still make the story

The new Common Chord scene retains the spontaneous Plus/Premier distinction,
Vukradin's refusal to pressure the patron who already gave to charity, Wick's
enthusiasm for a school whose bard he does not recognize, Sabbatha's interest
in Brewbarry, and Old Hesp's complaint about commercialization. Those exchanges
are not reduced to “the party raised money.”

The Rsolk scene keeps “Because I'm not over there,” celebrity recognition,
autographs, the poorly producing mine, the tunnel-manager exchange, and the
request for tickets. The landlord scene keeps the shell-as-house mistake,
“just asking questions,” “Money's money,” Valphine's love of sunlight, and
Soma's eventual sincere housing advice.

These are selective adaptations of recognizable interactions, not wholly new
dialogue substituted for the session. Some dialogue turns GM-described facts
into speech—for example, Brewbarry saying he previously could not afford the
tavern. Under this experiment's contract, that is dramatization rather than
an asserted verbatim quotation.

### Invented interiority supplies useful connective tissue

After receiving the ten-gold donation, Vukradin thinks about the people who want
the studio to exist. At Old Hesp's complaint, the plaque commemorates something
Hesp remembers without needing a plaque. These thoughts tie fundraising to a
sincere ambition rather than treating the studio as a recurring punchline.

Soma privately considers misleading the landlord, then gives him useful advice:
“Somewhere, eventually, someone may get a decent room out of the conversation.”
That dramatizes the source's established choice not to troll him. Her last wish
to have her bale out of the tavern expresses concern without falsely narrating
their departure.

These thoughts are adaptation, not newly discovered campaign facts. Their value
does not depend on finding them in the VTT.

## Consequential continuity checks

I read all five new scenes against all five frozen extractions. These are the
principal checks, not an exhaustive certification of every claim:

| Scene | Checked against the extraction | Result |
|---|---|---|
| 1 — Common Chord | Advisor remains a rumor; bathrobe funding already secured; ten-gold first donation and twenty-gold total; five-hundred likeness payment still pending; donor credits and unpressured refusal; low-tide plan | Preserved. Compression does not turn pending money into received funds or suspicion into a discovery. |
| 2 — Sewer stakeout | Nine crates divided eight/one; unmarked eight; separate carriers; brass-and-leather collector; party split and Sending Stones; promise not to spook Lim's contacts; diversion without amnesia | Preserved at event level. The magical diversion is explicitly enacted, including retained memory. A comic qualification to the promise is lost; see below. |
| 3 — Rsolk | Genuine disorientation; recognition changes the encounter; local rather than citywide tunnel control; Zeleen/mine link; losses and wrong-colored spiders; agreement to help, not a completed job; promise to ask for tickets, not supply them | Preserved. The text also avoids choosing an incorrect earlier location for the remembered strange webs. |
| 4 — Denvar | No early faction insignia; overpayment remains an inference; name learned from landlord; chits and unpaid seventh; rent due by day's end; reason to continue surveillance; sincere housing advice | Preserved in the principal facts. Calendar terminology needs the source-policy distinction noted below. |
| 5 — Dead drop | Familiar restored; bard reunites; payment collected; initial two-way-drop uncertainty; Brewbarry alone inside; performance remains proposed; Knock and rat reveal basement Harper HQ; Harper role and fame's sponsor remain unresolved | Preserved. The others learn the rat's discovery through Soma's report; the final party positions remain intact. |

This is evidence that a less transcription-bound chapter is feasible from the
existing smoothed layer. It is not evidence that future chapters can dispense
with factual review.

## What still gets in the way

### 1. Selection can preserve the fact while weakening the relationship

The [scene 2 source](inputs/Phandalin/summaries/20260902/scene_extractions_smoothed/02_the_sewer_stakeout.md)
has Vukradin remind Soma of the promise to Lim, then qualify it: “Or you promised
them.” Soma answers, “Thank you so much.”

The new chapter keeps the reminder and the sarcastic reply, but drops the
qualification. It preserves the obligation while losing Vukradin's comic
redistribution of responsibility. This is a small but revealing loss under the
goal of recognizable dialogue. It should be reviewed as an exchange, not as a
missing quotation count. Restoring every acknowledgment would not address the
underlying selection problem.

The lunar discussion is also substantially compressed, and the joke about
Soma speaking for all turtles is omitted. These are taste/coverage choices,
not automatically factual bugs. Whether they belong depends on which moments
the user wants the chapter to carry.

### 2. Removing quote locks did not produce sustained paragraph development

| Diagnostic | Existing final chapter | New adaptation |
|---|---:|---:|
| Words | 9,568 | 5,389 |
| Paragraphs | 675 | 411 |
| Median paragraph length, words | 10 | 9 |
| Quote-led paragraphs | 401 | 210 |
| Quote-led paragraphs of five words or fewer | 155 | 77 |

The chapter is about 44% shorter. The halving of very short quoted paragraphs
therefore must not be presented as a halving of the stylistic problem. Their
density falls only from approximately 16.2 to 14.3 per thousand words; the
median paragraph is slightly shorter. Definitions and exact counts are in
[metrics.json](metrics.json) and the runner's `metrics` function.

Short dialogue turns can be excellent. Here, however, passages such as the
Harper discovery still break into repeated isolated beats: finding the mark,
naming it, declaring it unmistakable, then stating certainty again. The narrator
also explains some comic effects after they have landed: “No committee. No
discussion of cover identities. A man who can now afford a tavern enters a
tavern.”

My reading is that selection improved more than prose rhythm did. Paragraph
development and trusting the reader remain useful editorial targets. This
sample does not establish whether the examples, character descriptions,
whole-chapter generation, or other model tendencies explain that rhythm.

### 3. A supporting character can still become a convenient stereotype

Soma observes that waiting comes more easily to Brewbarry when there is a person
to watch than a conversation to understand. As Soma's subjective impatience,
this is possible. It also leans toward the stock unintelligent brute, whereas
the [character reference](character_references.md) explicitly gives Brewbarry
surprising perception and sensitivity to fear.

I would flag that line for a voice judgment, not call it an invented canonical
fact or demand that all unrecorded thoughts be removed. That distinction is
exactly what the freer narration contract needs.

### 4. Provenance identifies a remaining calendar-policy ambiguity

The scene 4 extraction says “weekly settlement” and describes seven to ten days
of records, later specifying seven chits. The new chapter retains “Weekly
settlement” alongside “About a tenday's records.” The historical final chapter
instead says the work is reconciled at each tenday's end.

The new wording is traceable to the supplied record, so I would not label it a
new model fabrication. But if Faerun calendar normalization is intended to
change that settlement interval, the ruling belongs in the evidence/policy
trail. A literary chapter should not silently become the only place that
decision is recorded. No such correction was made in this test.

## What this supports changing in our understanding

The smoothed extractions already did the essential preparation for this test.
We did not need another factual rewrite before asking for an adaptation.
The new chapter could then select dialogue and invent inner life without losing
the major causal chain.

The appropriate next editorial question is therefore not “Did every protected
line survive?” It is “Did the important interactions survive, and does the
chapter make their experience enjoyable to read?” That is a different question
from whether the world facts are correct, and both matter.

This result supports the user's distinction between a provenance-backed record
and a literary adaptation. It does **not** yet demonstrate a final simplified
production pipeline, identify one causal prompt change, or establish that this
specific draft is the preferred final voice. The raw response is deliberately
left untouched so those judgments can be made honestly.
