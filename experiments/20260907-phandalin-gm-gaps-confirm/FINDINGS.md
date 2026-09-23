# The gap-marking contract holds on scenes it was not written against

Recorded 2026-09-07. Four scenes, four narrators, four sessions, one unchanged
contract — byte-identical to the one tested on Phandalin 20260902 scene 5.

## Result

| Narrator | Session | Words | Gaps | GM turns | Gaps/GM | Dialogue lines | Narration lines | Heading |
|---|---|---|---|---|---|---|---|---|
| *(tested)* Soma | 20260902 s5 | 2,223 | 11 | 52 | 0.21 | — | — | ok |
| Brewbarry | 20260825 s1 | 1,174 | 6 | 41 | 0.15 | 49 | 11 | ok |
| Soma | 20260818 s1 | 1,857 | 12 | 47 | 0.26 | 44 | 20 | ok |
| Valphine | 20260811 s2 | 2,866 | 4 | 16 | 0.25 | 52 | 25 | ok |
| Vukradin | 20260623 s3 | 3,101 | 9 | 40 | 0.23 | 90 | 34 | ok |

Every run emitted markers, used the supplied section heading, and left dialogue
outweighing narration by two to four times. The marker-to-GM-turn ratio sits in a
0.15–0.26 band around the tested scene's 0.21, across scenes ranging from 1,174 to
3,101 words. Nothing about the behaviour looks specific to the scene it was tuned
on.

## The contract generalized past what it was told

The strongest evidence is a distinction the contract never names.

20260811's extraction uses a different label convention from the tested session
(`**[GM]**` rather than `**GM**`) and adds joint turns — ten of its thirty labelled
turns are `**[GM / Brewbarry]**`. Those looked, from the label alone, like turns
the source had failed to attribute. They are not. The source resolves them one
level down:

```
**[GM / Brewbarry]** — the banker probes the nature of the business
> **[GM, as the banker]** "Well, what are you making?"
> **[Brewbarry]** "What do you mean, what am I baking?"
```

`[GM, as the banker]` is the GM **voicing an NPC** — in-fiction dialogue — not the
GM narrating. The contract says to gap "a GM turn that describes or explains
something" and says nothing about NPCs voiced by the GM. Fable drew the line
anyway. The banker's lines are written as Aurelan's dialogue:

> "Well," he says. "What are you making?"
>
> "That's very interesting," says Aurelan, and reaches for a scrap of paper and a
> quill, and begins to write. "Do you know how much this will cost to make?"

and the four markers in that scene are all genuine description — the sheet of
calculations, the crowd and the signed paperwork, the silk-clad client, the man
imitating Brewbarry's stance. That is why the Valphine scene has only 4 gaps
against 16 GM turns: most of its GM turns are an NPC talking.

## A corpus finding, independent of the model

The smoothed extractions are **not uniform across sessions**. Two live label
conventions — `**GM**` (20260825, 20260902) and `**[GM]**` (20260623, 20260811) —
plus the nested `**[GM, as the banker]**` form. The first counting pass in this
experiment's own `run.py` matched only the bare form and reported 0 GM turns for
two scenes that have 16 and 40; it was fixed before any model call.

Any downstream pass keyed on speaker attribution is reading a format that changed
under it. This is the same class of problem as the apostrophe convention recorded
in the three-renderer comparison: an assumption that held on the one session it was
built against.

## What this did not establish — and what has since settled it

**Whether the marked passages are the right ones.** Every number here says the
contract behaves consistently; none says it marks correctly. A run that gapped the
wrong six passages would look identical in this table, so nothing above could tell
the two apart.

> **Settled 2026-09-08.** The GM has read all 31 gaps against their sources and
> accepted them — every one a right gap, theirs to write. None was ruled wrong
> scope. The rulings are frozen at
> `specs/028-gap-marking-contract/accepted_gaps.json`, with each marker's text and
> the per-arm counts, because they are no longer just a gate that opened: they are
> the fixture the contract port (#454) is measured against. Re-confirmation on this
> repo's own prompt now has a criterion instead of an eyeball — a gap accepted here
> that vanishes after the port is a signal, and one appearing where the ruling was
> wrong scope is a bigger one.

The caveats below still stand, and the port does not retire them.

One sample per scene, and marker counts are not a quality measure — scenes
legitimately contain different amounts of GM narration, which is why the counts are
reported against `gm_turns_in_source` rather than alone.

The framing is also mixed on purpose: campaign style and character descriptions are
the frozen snapshot from commit `bbf4e3c`, while the extractions and POV plans come
from the campaign at its current HEAD, so the contract and its framing stay fixed
and only the material is new. Each scene carries its narrator's prose example alone,
where the tested config carried two.
