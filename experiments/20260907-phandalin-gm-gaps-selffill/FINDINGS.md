# Delegating the scope decision reproduces the original failure

Recorded 2026-09-07. Read with [../20260907-phandalin-gm-gaps-medium](../20260907-phandalin-gm-gaps-medium)
(the input draft) and [../20260907-phandalin-gm-gaps-hermetic](../20260907-phandalin-gm-gaps-hermetic).

## What was asked

Take the medium gap-marking draft and its 11 markers, and have fable resolve each
one itself: **description** — perceptible in the room at that moment — narrated in
the POV character's voice; **lore** — world or faction background nobody perceives
now — discarded.

## What happened

All 11 markers resolved, none left unresolved, 2,223 → 2,804 words. And the GM has
no voice anywhere in the output: every attributed line belongs to Soma (20),
Vukradin (8), or Valphine (8).

Nothing was discarded as lore. The one marker that is unambiguously lore — the
Order of the Gauntlet material — was neither narrated nor dropped. It was
**converted into player dialogue.**

The source records this exchange:

| speaker | line |
|---|---|
| **GM** *contrasting them with the Order of the Gauntlet* | "There's no… the only good people are the Order of the Gauntlet." |
| **Soma** *questioning that claim* | "Debatable." |
| **Vukradin** *renaming them* | "Basically, they're the Reformed order of the Gauntlet." |
| **GM** *describing their new outlook* | "Yes. They recognized that they were used by powerful forces, and now they're all about the little guy." |

The finished scene:

> "Which leaves the Gauntlet as the only clean hands in this," **Vukradin** says, as if that were a comfort.
>
> "Debatable," I say.
>
> "Reformed," **Vukradin** says. "They're reformed. Well, they had that whole thing with the barbarians, you know. They've been past that, they're reformed now. Basically, they're the Reformed Order of the Gauntlet."

Both real player lines survive correctly attributed — Soma's "Debatable", Vukradin's
"Reformed Order of the Gauntlet". Around them, **both GM lines were given to
Vukradin**, who did not say them. The fabrication is invisible: the passage reads
as a natural four-beat exchange between two players, and nothing in the prose
marks the seam.

## Why this matters more than the prose does

This is the exact failure the whole sequence set out to eliminate, reproduced on
the one passage the gap markers had successfully protected:

- **draft B** (spark, control) gave the GM's two-way-rock explanation to Valphine.
- **draft D** (fable, composition) dissolved the same explanation into Soma's
  observation.
- **the gap-marking runs** held the line — the GM's material stayed in a marker,
  unattributed, waiting for the human.
- **this run**, handed the ruling, put GM speech in a player's mouth again.

The instruction offered two outcomes, narrate or discard. The model found a third
that satisfied neither and looks better than both. Given a scope decision it
should not have, it did not refuse or hedge — it resolved the tension by inventing
attribution, which is the specific error class the campaign's own pipeline rule
names as requiring a human checkpoint.

## What it does not show

One sample, one scene, one model. It does not show fable cannot tell description
from lore — it was never asked in isolation; it was asked while also writing, and
writing well is what it optimized. A classification-only pass (label each marker,
write nothing) is a different experiment and might well succeed. That would still
be a scope decision for the GM to ratify rather than consume.

It also does not condemn the prose. The passage above is good; that is the
problem. Ten of the eleven markers were narrated in voice and read well, and if
the goal were a finished chapter with no human writing in it, this run is the best
of the sequence. The cost is that its errors are undetectable without going back
to the source line by line — which is what the markers made unnecessary.

## Method note, recorded because it misled the analysis

`run.py rulings` scores each marker by how much of its distinctive vocabulary
survives into the finished scene, and reports a low share as "discarded". It
reported the Gauntlet marker discarded at 0.47. It was not discarded; it was
rewritten as dialogue, which drops the marker's summary vocabulary while keeping
its content. The tool's own docstring says the match is lexical and can be wrong
in both directions, and here it was. The finding above comes from reading the
passage against the source, not from the tool.
