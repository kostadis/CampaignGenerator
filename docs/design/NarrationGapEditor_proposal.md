# Narration gap marking and the block editor

**Status:** proposal. Nothing here is implemented. Tracking:
[#418](https://github.com/kostadis/CampaignGenerator/issues/418) — merging the PR
that adds this document must not close it. Evidence is frozen under
[`experiments/`](../../experiments/README.md); the runs it rests on are
`20260907-phandalin-gm-gaps-medium` and `20260907-phandalin-gm-gaps-confirm`.
Implementation is tracked in #418's sub-issues: #453 (speaker labels), #454
(contract port), #455 (document model), #456 (editor).

## Summary

Narration currently asks one model call to do two jobs at once: reshape the
players' recorded dialogue into readable prose, and author the scene description
around it. It does the first well and the second badly — and the way it fails is
invisible, because when the GM's narration has to go somewhere and the contract
forbids showing the GM, the model silently gives it to a player character.

The proposal splits the job at that seam:

- **The model writes the dialogue.** Everything the players said and did, shaped
  into prose, at the quality it already reaches.
- **The GM writes the scene.** Every passage the source attributes to the GM's
  own description or explanation comes back as a marked gap stating plainly what
  the source establishes there, and nothing else.
- **A block editor is where the two meet** — and every block is editable, the
  model's prose as much as the gaps, because the seam between them is exactly
  where a sentence usually needs a tweak.

The editor is the feature. Gap marking is what makes it possible.

## The problem, in one passage

The source records the GM explaining a mechanism:

```
**GM** — *explaining the ambiguity of the two-way drop*
> "It's a two-way rock. You don't know whether the person who put the payment
>  inside was on this side or inside the house, so you'd have to enter the
>  house to find out."
```

Six drafts of that scene, from three renderers, did five different things with
it:

| Draft | What became of the GM's explanation |
|---|---|
| DeepSeek, control arm | `"It's a two-way rock," **Valphine** says` — a PC given the GM's line |
| Fable, composition arm | dissolved into Soma's own observation: *"It is a two-way box. Somebody on the far side can put a thing in…"* |
| Astra, both arms | dropped; only a player's in-fiction question about it survives |
| DeepSeek, composition arm | `"It's a two-way rock," **the GM** says` — the seam marked, by breaking the rule that forbids staging the GM |

Four of six either **reassign** the GM's material to a character or **drop** it,
and from the finished prose a reader cannot tell which happened. The current
narration contract causes this directly. It says:

> Present the fictional consequences of mechanics without roll results, rules
> administration, software operation, **or the GM as a character**.

Forbidding the GM as a character while offering no third option makes silent
reassignment the compliant move. This is an attribution error — the precise class
the repo's own rule (`CLAUDE.md`, "LLM renders, humans decide") reserves for a
human checkpoint — and it is produced by the prompt, not by any model's weakness.

## The insight this rests on

From the GM, after reading six blind drafts:

> I hate writing dialogue. But love writing scenes. I was trying to get the
> models to clean up the dialogue and leave me the scene writing.
>
> The scene writing was what the models sucked at because they were asked to do
> too much.

The split is not "make the model do less". It is **stop asking it for the half
that is authorship**. Dialogue cleanup is mechanical work the GM does not enjoy
and the model does well. Scene description is authorship the GM wants and the
model was only ever doing because the contract left it nowhere to put the GM's
words.

## The contract

One sentence replaces the anchor above. Full text in
`experiments/20260907-phandalin-fable-gm-gaps/prompt.diff`; the operative part:

> Where the source attributes a passage to the GM, do not transfer it to a player
> character: GM description and explanation must not become a character's speech,
> perception, memory, or inference, and must not be absorbed unmarked into the
> narrator's voice. A GM turn that only confirms or adjudicates a player's
> question is table operation and is dropped as before. A GM turn that describes
> or explains something — a place, an event, a world fact, how something works —
> is the human author's to write, so leave a gap for it rather than writing it
> yourself: emit, on its own line,
> `[GM NARRATION — TO BE WRITTEN: one plain sentence stating what the source
> establishes there]`, and carry the scene on around it.

Two properties matter for implementation:

- **It distinguishes adjudication from narration.** A GM turn that is `"Yep."`
  stays dropped as table operation. Only description and explanation become gaps.
  In the tested scene that is 11 markers against 52 GM turns.
- **It generalized past its own wording.** The contract says nothing about NPCs
  voiced by the GM. Given a scene where ten of sixteen GM turns are
  `**[GM, as the banker]**`, fable wrote the banker as NPC dialogue and gapped
  only the four descriptive passages — a distinction it was never given.

### Which variant

**v1 is the `medium` contract as quoted above**, confirmed across four scenes.
Two tested alternatives are recorded and deliberately not adopted:

| Variant | Result | Why not v1 |
|---|---|---|
| effort `low` | 17 markers instead of 11 — the same material cut into fragments rather than whole beats | The GM wants scenes to write, not fragments to stitch |
| **sealed** (one more sentence: don't lean on what you withheld) | narration leaks 2 → 0, dialogue up 12%, but 15 finer gaps | Real improvement on a real defect; see [Hermeticity](#hermeticity-and-why-the-editor-answers-it) — the editor makes it optional rather than necessary |

## Evidence

Every run is one sample. Marker counts are not a quality measure; scenes contain
different amounts of GM narration, so each is read against its own GM-turn count.

**Tuned on** Phandalin 20260902 scene 5 (Soma): 11 gaps / 52 GM turns.

**Confirmed on** four scenes it was not written against —

| Narrator | Session | Words | Gaps | GM turns | Gaps per turn | Dialogue lines | Narration lines |
|---|---|---|---|---|---|---|---|
| Brewbarry | 20260825 s1 | 1,174 | 6 | 41 | 0.15 | 49 | 11 |
| Soma | 20260818 s1 | 1,857 | 12 | 47 | 0.26 | 44 | 20 |
| Valphine | 20260811 s2 | 2,866 | 4 | 16 | 0.25 | 52 | 25 |
| Vukradin | 20260623 s3 | 3,101 | 9 | 40 | 0.23 | 90 | 34 |

Every run used its supplied section heading, emitted markers, and left dialogue
outweighing narration two to four times. The ratio band (0.15–0.26) brackets the
tuned scene's 0.21 across drafts from 1,174 to 3,101 words.

**What the evidence did not establish — and what has since settled it:** whether
the marked passages are the *right* ones. A run that gapped the wrong six would
produce an identical table. That judgement belongs to the GM against the source,
and it has now been made: the 31 confirmation gaps were read against their
sources and accepted. Those rulings are the fixture the contract port is checked
against (#454). The editor still puts the source's GM turns beside the gaps
rather than in a file, because the same judgement is owed on every future scene.

### The ruling is not delegable

Asked to resolve its own 11 gaps — narrate description, discard lore — fable
discarded nothing and produced the best-reading draft of the whole sequence. On
the Order of the Gauntlet exchange it kept the two real player lines and gave
**both** of the GM's lines to Vukradin, who never said them. Offered
narrate-or-discard, it found a third option that satisfies neither and hides the
seam.

That is the same failure the markers exist to prevent, reproduced on the one
passage they had protected. It is the argument against ever adding an
"auto-resolve gaps" affordance, however cheap it looks.

## The document model

Three files per scene, mirroring the `transcript_corrections.yaml` pattern
already established for the tape (raw generated → hand-authored record →
generated output). The same rule applies: **the generated files are never
hand-edited, and the authored file is the only thing a human touches.**

```
narration/
  session_doc_scene_NN_<slug>.md            generated by sd_narrate, with markers
  session_doc_scene_NN_<slug>.knobs.json    run identity (exists today)
  session_doc_scene_NN_<slug>.authored.yaml hand-authored: rulings + GM prose
  session_doc_scene_NN_<slug>.composed.md   generated by merging the two
```

`assemble` consumes `.composed.md` where it exists and falls back to `.md`, so a
scene nobody has edited still assembles.

### Blocks

The narration parses into an ordered list of blocks. A block is either **prose**
(model-written) or **gap** (a marker). Every block carries provenance:

| provenance | meaning |
|---|---|
| `model` | as generated, untouched |
| `model-edited` | model prose the GM changed — the tweak case |
| `authored` | a gap the GM wrote |
| `cut` | ruled out of the chapter; omitted from `.composed.md` |
| `open` | a gap with no ruling yet — blocks assembly of a finished chapter |

`.authored.yaml` stores only what the human contributed:

```yaml
scene: 05_the_dead_drop_at_the_house_of_a_thousand_faces
generated_sha256: 3b9296…            # the .md this was authored against
blocks:
  - id: gap-03
    anchor: "the hollow opens from either side, so there is no way to tell…"
    provenance: authored
    text: |
      The stone comes away clean, and behind it the hollow runs deeper than an
      arm…
  - id: prose-07
    anchor: "Brewbarry is in there somewhere, happy, in the place he couldn't…"
    provenance: model-edited
    text: |
      Brewbarry is in there somewhere. The rest of my bale drifts in around me…
```

### Block identity is the hard problem

Human work is keyed to generated blocks, and re-running `sd_narrate` produces
different prose. Keying by position silently lands an edit on the wrong block.

**v1 answer, and it is deliberately conservative:**

- Each block gets `id` = `{kind}-{ordinal}` plus `anchor` = the first ~80
  characters of the generated block it was authored against, and the file records
  `generated_sha256` of the whole draft.
- On load, if `generated_sha256` matches, ids are trusted outright.
- If it does not match — the scene was re-narrated — **nothing is auto-applied.**
  The editor enters a merge review: each authored block is matched to the new
  draft by anchor similarity and shown as a proposal the GM accepts or relocates.
  Unmatched authored blocks are shown as orphans, never dropped.
- `sd_narrate` **refuses** to overwrite a `.md` whose `.authored.yaml` has content,
  unless given `--reroll`, which writes the new draft alongside and opens merge
  review rather than replacing anything.

A later version could anchor gaps to source-extraction line ranges, which would
survive re-rendering properly. That needs `sd_narrate` to emit a source anchor
per marker, which is itself an attribution claim by the model, so it needs its own
evidence before it is trusted. **Do not build it into v1.**

## The editor

Extends the **Session Doc Editor** (`docs/web/web_ui.md`) rather than adding a
page: the workflow is the existing extract → edit → narrate → assemble loop, with
one new state between narrate and assemble.

A working prototype of the reading and ruling surface is published as an artifact
and was used for the GM review that produced this proposal; it is the reference
for layout and interaction, not for code.

### Layout

One reading column, the scene top to bottom in order. Not a two-pane diff — the
GM is reading a chapter, and a gap should interrupt the read exactly where the
writing is owed.

- **Prose blocks** render as prose. Click to edit in place. An edited block is
  marked `model-edited` and shows a revert-to-generated control.
- **Gap blocks** render as a recessed well breaking the column: the marker's
  plain statement of what the source establishes, four rulings — *right gap, mine
  to write* / *wrong scope* / *model should have written it* / *cut from the
  chapter* — and a text area.
- **The scene's source GM turns** sit at the foot: every turn, its line number,
  its label as written, its contextual note, its quote. Ruling a gap means
  checking it against these. This is the check no count can make, so it is on the
  page, not in a file.
- **Progress** is *n of m gaps resolved*, and a next-open-gap control.

### Interactions that matter

- **Editing a rendered block is a first-class action**, not an escape hatch. The
  GM's words: *"the rendered section … should have the option to edit as well —
  because sometimes it needs a tweak."*
- **Nothing auto-resolves a gap.** No "let the model try" button. See
  [The ruling is not delegable](#the-ruling-is-not-delegable).
- **Save is per block**, and writes only `.authored.yaml`.
- **Assemble is gated on zero `open` gaps**, and says which scenes hold it up.

### Hermeticity, and why the editor answers it

The v1 contract's gaps are not sealed: the model gaps a fact and then lets the
narrator lean on it. Both tested runs gap Brewbarry's history and then write
*"in the place he couldn't afford once."* A passage the GM writes must agree with
prose that already assumed an answer.

The sealing sentence fixes this at the prompt (leaks 2 → 0) at the cost of finer
gaps. **The editor fixes it differently and better**: because the surrounding
prose is editable, the GM writes the gap and adjusts the neighbouring sentence in
the same pass. Editability of rendered blocks is not a convenience here — it is
what makes the unsealed contract usable, and it is why v1 takes the 11-gap
variant over the 15-gap one.

Ship v1 unsealed. Revisit the sealing sentence if GMs report fighting the
surrounding prose more than tweaking it.

## Pipeline integration

```
scene_extract → sd_plan → sd_narrate (gap mode) → BLOCK EDITOR → assemble
                                                  ↑ new gate
```

- `sd_narrate` gains a mode that swaps in the gap-marking contract. It is a
  narration mode, not a check, so a config switch is legitimate:
  `session_doc.yaml` → `narrate.gap_marking: true`.
- The contract text is a **file**, addressed by path, exactly as the genre
  rulebook is (`docs/cli/genre_rulebook_howto.md`) — never a string pasted into
  config. The `narrate.genre` incident is the precedent.
- `.knobs.json` records `gap_marking: true` and the contract file's digest, so
  two scenes are comparable and a mid-session contract edit is visible.
- `assemble` prefers `.composed.md`; `--require-composed` fails on any scene with
  open gaps rather than assembling a chapter with markers in it.
- **`/scrub` and `/no-mech` run before this**, on the extractions, unchanged.

## Interaction with existing work

- **#397** (conflicting quote contracts) — this proposal takes a side: dialogue is
  editable dramatic material, GM narration is not the model's to write at all.
- **#386** (meaningful event and interaction coverage) — a gap is a positive record
  that a GM-narrated event reached the document, which coverage checking can read.
- **Quote verification** (`docs/cli/quote_verification_howto.md`) — unaffected;
  it checks player quotes, and gaps contain none.
- **Provenance** — `.composed.md` is generated and belongs in the `generated_by`
  tier; `.authored.yaml` is hand-authored and is the authoritative record of the
  GM's writing. This is the first pipeline stage where a *generated* file has
  human prose inside it, which is exactly why the authored file exists separately.

## Corpus problems this surfaced

Both are independent of any model and will affect implementation:

- **Speaker-label conventions are not uniform.** `**GM**` in 20260825 and
  20260902, `**[GM]**` in 20260623 and 20260811, plus a nested
  `**[GM, as the banker]**` form and joint `**[GM / Brewbarry]**` turns. A first
  counting pass in the experiment's own runner matched only the bare form and
  reported 0 GM turns for scenes that have 16 and 40. Anything keyed on speaker
  attribution is reading a format that changed under it. **Worth its own issue.**
- **Typographic drift between renderers.** Astra emits `’` and no ASCII
  apostrophes; fable and DeepSeek emit ASCII and no `’`. The extractions and plans
  use `’`. Any verbatim check keyed on that character fails against two of three
  renderers. Fold typography before comparing headings or quotes.

## Open questions for implementation

1. **Merge review UX on re-narrate** — the sketch above (anchor similarity,
   orphans shown never dropped) is a shape, not a design. It needs one.
2. **Multi-scene view** — the prototype is per-scene. Does the GM want the whole
   chapter in one column, with gaps from every scene in one queue?
3. **Does `model-edited` prose need a diff view** against what was generated, or
   is revert-to-generated enough?
4. **Assemble gating strictness** — should `cut` on every gap in a scene be
   allowed to produce a chapter, or does that mean the scene was mis-narrated?
5. **Where the contract file lives** — `config/agents/`, beside the genre
   rulebook in the campaign, or both with campaign override.

## What this proposal is not

It is not a claim that fable is the right model — the confirmation ran on
`claude-fable-5-1` at effort `medium` because that is what was tested, and the
contract's behaviour should be re-confirmed on any model swap. It is not a
finished chapter, a canon change, or a revalidation of the current narration path
at HEAD; the runs are pinned to generator `d9c5de8` and campaign `bbf4e3c` /
`421041f3`. The marked passages have since been reviewed against their sources
and accepted, which closes the question this section originally left open; what
is still unestablished is that the contract holds against *this repo's* narration
prompt, a fragment assembly rather than the flat experiment prompt these runs
used (#454).
