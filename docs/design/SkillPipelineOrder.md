# Skill pipeline order — post-recording

Companion to [TheFlow.md](TheFlow.md), which describes the whole loop end to end
(prep → session → memoir → grounding → next prep). This doc covers **one
segment** of it in detail: the ordering of the Claude skills and CLIs that run
between a finished recording and an assembled session document, and *why each
one sits where it does*.

`TheFlow.md` was written against the older monolithic `session_doc.py`
(Pass 1–5, `quote_ledger.py`, the `QuotePicker` UI). The chain below is the
current split-CLI pipeline (`sd_plan` / `sd_narrate`) and includes six skills
absent from that doc's inventory: `speaker-attribution`, `scene-extract`,
`voice-smooth`, `scrub`, `no-mech`, `remove-recap`. Where the two disagree on
ordering, this doc is newer.

Skills marked `[ ]` live **outside this repo**, in `~/.claude/skills/`.

## The order

```
VTT
  → /speaker-attribution
  → enhance_summary → gm-assist.md + session-summary.md
  → /staged-consistency  phase 0, phase 1
  → [ /remove-recap ]      ← scene list + summary prose, before extraction
  → /scene-extract
  → /staged-consistency  phase 2
  → /voice-smooth
  → [ /no-mech ]           ← mechanics, before narration
  → sd_plan
  → sd_narrate
  → /scrub
  → assemble
```

## The organising principle

> **Fix the input. Don't clean the output.**

Every skill above is placed at the earliest point where the defect it targets
becomes *visible* and the artifact it edits is still *cheap*. Two consequences
follow, and they are the reason the order is not arbitrary:

1. **`/scrub` is the fallback, not the plan.** It repairs mechanical residue that
   reached the narration. Everything that can be removed upstream should be, and
   `/scrub` should find less every session it runs.
2. **Cost rises monotonically to the right.** A defect removed before
   `/scene-extract` costs nothing downstream. The same defect removed after
   `sd_narrate` costs a re-narration, and — if it changes the scene count — a
   re-plan and a full renumber.

This is the design principle from `TheFlow.md` ("never feed an LLM's output to
another LLM without human review") applied to *sequencing* rather than to
review gates: each skill is a human checkpoint, so putting a checkpoint late
means an LLM consumed unreviewed input in the meantime.

## Why each position

| Step | Why here |
|---|---|
| `/speaker-attribution` | Must precede `/scene-extract`. Attribution is inherited by every quote, extraction and narration downstream, and nothing further along re-checks speaker identity. Running it after means re-extracting. |
| `enhance_summary` | Produces `gm-assist.md` and `session-summary.md`, including the `## Scenes` list that drives extraction. |
| `/staged-consistency` phase 0, 1 | Verifies the gm-assist and the summary **while the artifacts are still cheap**, and before the scene structure is used. Phase 1 is where the scene list gets its human sign-off. |
| **`/remove-recap`** | After the scene list is verified (Stage 0/1 can still move boundaries) and **before `/scene-extract`**, so no extraction, consistency, or smoothing budget is spent on the previous chapter. |
| `/scene-extract` | Needs a verified scene structure and a resolved speaker map. |
| `/staged-consistency` phase 2 | The per-scene quote layer is the one that silently re-injects errors into the narrator. This is the highest-leverage check in the chain. |
| `/voice-smooth` | Renders verbatim quotes readable and in-voice, into a derived `scene_extractions_smoothed/`. Must run *after* the consistency pass — smoothing a garbled quote produces a fluent mistake, which is much harder to catch than a garbled one. |
| **`/no-mech`** | After smoothing (so it operates on the layer narration actually reads) and **before `sd_narrate`**, so the narrator never has to convert a die roll into prose. |
| `sd_plan` | Assigns narrators to scenes. Numbers sections by directory order — see the renumbering hazard below. |
| `sd_narrate` | Renders. Must read `scene_extractions_smoothed/`, not `scene_extractions/`; it warns if pointed at the wrong one. |
| `/scrub` | Mechanical residue that still reached the prose, plus the classes only a reading pass finds (anachronism, transcript artifacts). |
| `assemble` | Prefers `<scene>.scrubbed.md` per scene, falling back to the raw `.md`, so a mixed directory assembles correctly. |

## The two new skills

Both were built from a full pipeline run of the *obelisk* campaign, chapter 10.
Neither is in `TheFlow.md`'s inventory.

### `/remove-recap` — before `/scene-extract`

A recorded session opens with the GM recapping the previous chapter. Narrated
again, the campaign gets the same events twice, in two chapters.

**Three surfaces carry the recap, and cutting the scene fixes only one:**

| # | Surface | Effect if left |
|---|---|---|
| 1 | the recap **scene** in `## Scenes` | narrated as this chapter's opening |
| 2 | the **`## Summary` prose** in `session-summary.md` | the chapter's summary retells the previous chapter |
| 3 | the **enhanced-summary file** (same prose) | **worst**: it is `sd_narrate`'s positional *recap* argument, so it is framing context in every scene's prompt and can bleed into any of them |

On obelisk ch10 all three were live: the summary's first three paragraphs are
chapter 8, and chapter 10 does not begin until *"With the party still at the
Miner's Exchange…"* One insertion point, before extraction, catches all three.

**The recap is not reliably redundant.** Three things die if it is cut blind:
GM asides that deliver new canon while recapping (ch10's recap is where the
party learns the sword is named Talon); *this* chapter's bookkeeping announced
at the top (a level-up and a subclass); and beats the previous chapter's record
genuinely missed — which is a gap upstream, not licence to keep the recap.

### `/no-mech` — before `sd_narrate`

Removes the quotes that are the table operating the game — die rolls, DCs,
virtual-tabletop and quest-log operation, rules Q&A, session scheduling — from
the smoothed extractions.

The classifier is *who is being spoken to*, not "is this mechanical":
in-character speech and GM read-aloud description are kept; GM-to-player-as-player
is cut.

**What it buys is room, not correctness.** On obelisk ch10, `/scrub` finished
with zero mechanical residue in any of the eight narrated scenes — by its own
standard the session was clean. Two of those scenes were nevertheless built from
extractions that were almost entirely table operation, which `sd_narrate` had
quietly converted to prose. Removing the mechanics upstream and re-narrating
produced *visibly better* prose: with die rolls gone from its input the narrator
stopped spending budget on conversion and spent it on character.

It also prevents a hard failure. When a scene is *entirely* mechanical and
`sd_narrate` writes no reclassification hatch, the tooling reaches the page as
in-fiction dialogue — ch10 scene 02 narrated `"Quest log."` and
`"I cannot see your pointer."` as things a character said aloud.

## The renumbering hazard

`sd_plan` numbers plan sections by directory order. **Removing a scene shifts
every index after it**, invalidating `plan.md`, every `--scene N` invocation, and
every `session_doc_scene_NN_*.md` filename already in `narration/`.

This is why `/remove-recap` belongs before extraction. Run after `sd_narrate`, it
costs a re-plan and a re-narration of *every* scene, not just the one removed.

Related, and easy to miss: **re-narrating any single scene changes the seams
around it.** The narrator sometimes opens a scene by echoing the previous scene's
closing sentence, so regenerating a scene can silently drop an echo its neighbour
relied on — or render the echo as *quoted dialogue*, making a character appear to
speak the previous narrator's prose aloud. Walk the seams after any re-narration.

## Relationship to `scrub_mechanics.py`

`TheFlow.md` step G5 ("strip mechanical language") is `scrub_mechanics.py`, wired
to the **Scrub** button in the Session Doc Editor: one LLM call with a filter
prompt and no review step. That is *LLM extracts → LLM decides scope → LLM
renders*, which the design principle forbids, and it has already gone wrong —
the bundled prompt treated in-world magic as mechanical residue and rewrote spell
names into euphemisms (issue #151).

`/no-mech` and `/scrub` are the propose → review → apply replacements, at the two
different layers (input and output). Neither touches `scrub_mechanics.py`; wiring
the editor's button to the reviewed flow is a CG-side change and remains open.

## What never moves

Regardless of ordering, two layers are immutable:

- **The VTT** is the permanent record of what was said.
- **`scene_extractions/`** is the verbatim extraction of it.

Every skill above that edits anything edits a *derived* layer —
`scene_extractions_smoothed/`, `plan.md`, `narration/`, or the scene list. A
recap *was* said; table mechanics *were* said. Removing them from the chapter is
an editorial decision about the document, never a claim about the tape.
