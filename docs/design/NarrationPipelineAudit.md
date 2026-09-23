# Narration pipeline audit: factual precision and literary freedom

Date: 2026-09-07

Saved from the discussion of the post-recording pipeline, from VTT spell pass
through voice critique. Analysis only; no implementation changes were requested.

Evidence scope: CampaignGenerator history from its first narration scripts,
the current pipeline and external skills, relevant GitHub issues, Phandalin
session outputs, and the archived narration experiments. The checkout was at
`d9c5de8`; the audit also inspected `origin/main` at `9daed21`, including the
already-merged #395 fix. Campaign evidence was read at
`bbf4e3c064b4e13b47ed523606a62936638a0cc6` in `kostadis/campaigns`.

## Assessment

The history and the outputs support your diagnosis: **the system recovered the
life of the players by protecting their words, then gradually made protecting
those words more important than writing a good story.**

Your intended contract is now clearer than the implementation:

- Events, outcomes, discoveries, and the state of the world remain accurate.
- Dialogue preserves recognizable personalities, intentions, humor, and relationships.
- Interior thoughts and literary presentation can be invented within those boundaries.
- The VTT and reviewed summary preserve the detailed record independently.

The system only partially makes that distinction today.

## What the Phandalin comparison shows

I compared the latest `session_doc.md` with the preceding four session narratives.
The change is not simply increasing length:

| Session | Approximate words | Paragraphs | Quote-led paragraphs of five words or fewer |
|---|---:|---:|---:|
| July 29 | 9,800 | 365 | 27 |
| August 11 | 12,600 | 516 | 59 |
| August 18 | 8,400 | 417 | 58 |
| August 25 | 10,400 | 569 | 108 |
| September 2 | 9,600 | 675 | 155 |

These are descriptive counts, not quality scores. Different sessions, voices,
and generation conditions prevent attributing the trend to one change. But the
passages make the problem tangible.

The [July 29 opening](https://github.com/kostadis/campaigns/blob/bbf4e3c0/Phandalin/summaries/20260729/session_doc.md)
gives Soma sustained observations through which the conversation unfolds. It also
has defects, including repeated material across adjoining scenes.

The [latest chapter](https://github.com/kostadis/campaigns/blob/bbf4e3c0/Phandalin/summaries/20260902/session_doc.md)
repeatedly preserves fragments and supplies narration to explain them. It retains
“new drow advisor that we will,” then explains that the sentence has no proper
ending. Near the conclusion, “level,” “Basement level,” and “Went down, alright”
become separate beats.

That is prose doing repair work around transcription artifacts. Neither factual
precision nor recognizable dialogue requires it.

Measurement note: counts used the pinned campaign snapshot above. Files were
`Phandalin/summaries/<session>/session_doc.md`, except August 18, which used
`session-summary-fable-doc.md`. YAML frontmatter was excluded; paragraphs were
blank-line-separated blocks excluding headings and separator blocks. A quote-led
paragraph began with a straight double quote or an opening curly quote. Words
were counted by whitespace. Short quote-led paragraphs are a diagnostic, not
automatically defects.

## The most consequential findings

### 1. The successful narration experiment was not fully reproduced in production

This is the strongest concrete finding.

The v1 experiment did more than substitute a writing brief. Its runner:

- Extracted only the actual character description from each voice file.
- Excluded the surrounding editing instructions and failure-prevention rules.
- Changed genre guidance about sparse description, minimal dialogue attribution,
  and mandatory stock phrases.

That is explicit in the [experiment runner](https://github.com/kostadis/campaigns/blob/0355cdd2/experiments/sd-narrate/narration-tests/phandalin-20260902/run_experiment.py#L123).

Production still [loads the entire declared voice file](../../session_doc/voice.py).
Phandalin’s [Vukradin voice file](https://github.com/kostadis/campaigns/blob/bbf4e3c0/Phandalin/voice/vukradin_new_pipeline.md#L7),
for example, prohibits removing, merging, shortening, expanding, or reordering
quoted lines. Soma has the same wrapper.

The shared brief now permits dialogue selection, but those old instructions
remain inside its references. Adding a sentence that declares the brief superior
leaves the model surrounded by competing instructions.

**The experiment’s improvement cannot be credited solely to the brief, and
installing that brief alone does not reproduce the experiment.** This is a
verified implementation mismatch; how much it explains any particular historical
render remains uncertain.

### 2. Quote fidelity became a substitute for character fidelity

The tension existed early. The March 19 narrator asked for three to five
paragraphs while also insisting that every line of an exchange appear.

Later changes addressed real damage. The [August 4 fix](https://github.com/kostadis/CampaignGenerator/commit/253952de7c724fcf6bcbc7efd268da7e4f0600c0),
for example, stopped alias normalization corrupting quoted names and stopped
mechanical-language conversion changing a speaker’s asserted meaning.

Those were legitimate problems. But the resulting protection treated quotations
in the finished story as archival evidence.

Your revised goal needs a finer distinction:

- Changing who made a promise changes a fact.
- Changing an uncertain answer into a confident assertion changes characterization.
- Joining fragments into a readable sentence need not change either.
- Removing repeated acknowledgments need not lose the exchange.
- Inventing Vukradin’s private response can enrich the scene without inventing a
  campaign event.

This matters for [#397](https://github.com/kostadis/CampaignGenerator/issues/397):
the contradictory instructions are a real problem, but restoring the strongest
verbatim restriction would reinforce the direction you now want to leave.

### 3. Several stages compensate for ambiguity about what the narrator may do

`voice-smooth`, `no-mech`, narration, `scrub`, and `dialogue-edit` repeatedly
address overlapping questions: what counts as speech, what belongs in the story,
how fragments become readable, and how table procedure becomes fictional action.

Each has a defensible origin. Collectively, they produce a costly pattern:

> Preserve awkward material → render around it → identify the awkwardness →
> obtain permission to edit it.

The latest session’s dialogue-edit review needed an individual proposal to
complete Valphine’s question using information already established in the
extraction.

For your goal, ordinary literary editing should have standing permission. Human
attention should concentrate on uncertain meaning, characterization, consequential
omissions, and factual changes—not routinely granting permission to make a
sentence readable.

### 4. Passing the checks is insufficient evidence that the chapter reads well

The latest [voice review](https://github.com/kostadis/campaigns/blob/bbf4e3c0/Phandalin/summaries/20260902/voice_critic/20260907-r1/voice_critique_summary.md)
carefully documents seven approved fixes, resolved stylistic budgets, and zero
lint errors. It also explicitly limits what those results certify.

Nevertheless, the chapter retains substantial fragmentation. The system can
satisfy its individual review contracts without achieving the overall reading
experience.

The existing [#340 investigation](https://github.com/kostadis/CampaignGenerator/issues/340)
documents a related problem: banned phrases disappeared while different narrators
continued sharing the same underlying prose habits.

I would retain useful diagnostic scans, but stop treating additional bans and
numerical caps as the primary route to better writing. Character perspective,
comic timing, atmosphere, and momentum need whole-scene judgment.

### 5. The transition away from narration as factual authority is incomplete downstream

Your explanation makes the earlier architecture understandable: when the
narrative carried the factual record, extensive preservation rules protected
future campaign continuity.

Some consumers still embody that arrangement. [TheFlow.md](TheFlow.md) explicitly
sends the memoir into world-state and dossier generation. Phandalin’s ensemble
configuration still selects `docs/chapters/` files, and the latest narrative also
exists there as Chapter 51.

That does not prove its invented interiority has contaminated current grounding.
It does mean the architectural separation is unfinished.

Future factual updates should principally consume the reviewed factual layer.
Narration can remain available as literary context, but an invented thought must
not silently become a new canonical motive merely because it appeared in an
approved chapter.

## Bugs worth separating from the design problem

| Finding | Consequence |
|---|---|
| **Assembly selects alternate titles as additional scenes.** I exercised the actual collector against the latest session’s saved filenames: it selected **seven files for five scenes**, duplicating scene numbers 01 and 05. | Reassembly can include discarded alternatives. The existing final chapter contains five scenes; this is a reproducible reassembly risk. |
| **Single-scene CLI generation does not refresh the editor’s `.knobs.json` record.** Confirmed in code and tracked as [#370](https://github.com/kostadis/CampaignGenerator/issues/370). | Reviews can rely on settings from an older render and recommend unnecessary regeneration. |
| **The checker ignores campaign `extra_tics` rules.** Tracked as [#376](https://github.com/kostadis/CampaignGenerator/issues/376), and acknowledged in the latest review. | A successful exit does not mean every configured rule ran. |
| **#395’s tense override was real, but is already fixed on `origin/main`.** [Issue #395](https://github.com/kostadis/CampaignGenerator/issues/395). | It illustrates conflicting policy ownership; it is not an explanation for Phandalin’s present-tense fragmentation. |

The assembly problem comes from [deduplicating filenames rather than scene
identity](../../session_doc/assemble.py). It is another place where the operator
currently supplies knowledge the program lacks: which revision is actually final.

## How I would simplify it

I would organize the workflow around three responsibilities:

1. **Establish the record.** Preserve the original transcript, recorded
   corrections, reviewed event summary, identities, and unresolved ambiguities.
   Keep quote extraction as supporting evidence and a source of distinctive
   exchanges. It was valuable; it does not need to dictate the narrative’s
   paragraph structure.

2. **Write the adaptation.** Give the narrator the reviewed facts, clean
   character descriptions, genre guidance, and relevant dialogue. Explicitly
   permit readable reconstruction, compression, developed interiority, and
   literary pacing. Protect decisions, promises, knowledge boundaries, outcomes,
   and the recognizable substance of memorable exchanges.

3. **Edit the chapter.** Review continuity and literary quality together, with
   distinguishable findings. Repair local prose locally. Return upstream only
   when the underlying record is wrong or incomplete. Select final revisions
   explicitly for assembly.

That could absorb much of mandatory smoothing, mechanics removal, scrub, and
dialogue editing into coherent preparation and editing work, while retaining
those tools for difficult cases.

The important simplification is **fewer competing contracts and fewer
independently maintained copies of the same information**, not merely fewer
model calls.

Before implementing that change, I would compare the current production path
with a genuinely equivalent version of the successful experiment: same scenes,
facts, model, and references, with the contradictory wrappers removed. Judge
factual integrity separately from recognizable voices and reading enjoyment.
The archived Astra medium/high trials already show that increasing reasoning
effort alone did not resolve the coverage problem.
[Experiment findings](https://github.com/kostadis/campaigns/blob/0355cdd2/experiments/sd-narrate/narration-tests/phandalin-20260902/astra_high_review.md).

My priority would be to reconcile that writing contract before restoring
restrictions removed by v1 or adding another mandatory review stage. The upstream
factual work has earned the narrator more freedom; the narration inputs and
downstream consumers have not fully caught up.

No code or campaign files were changed during this audit. This document saves
the analysis and recommendations only.

## Subsequent clarification and isolated test

The user clarified that improved session summaries have reduced the narrative's
burden as the authoritative record. The architecture need not force a single
source of authority: provenance can connect the VTT, reviewed summaries,
corrections, and derived extractions while making their respective roles and
any adjudications explicit.

Accordingly, “establish the record” above should not imply another mandatory
rewrite or one canonical mega-document. For the proposed test, the existing
reviewed smoothed extractions already supply that preparation. Narration must
respect the established world and consequential events, but it need not preserve
every evidentiary detail or the table's path to clarifying them. Invented
interiority belongs to the adaptation, not automatically to campaign canon.

At the user's request, an isolated
[five-scene adaptation experiment](../../experiments/20260907-phandalin-adaptation/README.md)
was subsequently run against those unchanged extractions. Its prompts, pinned
inputs, unedited response, comparison, and evaluation are saved separately.
Only experiment artifacts were created; production code and campaign documents
were not changed.
