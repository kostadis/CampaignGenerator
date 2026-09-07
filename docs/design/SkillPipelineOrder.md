# Skill pipeline order — post-recording

Companion to [TheFlow.md](TheFlow.md), which describes the whole loop end to end
(prep → session → memoir → grounding → next prep). This doc covers **one
segment** of it in detail: the ordering of the Codex/Claude skills and CLIs that run
between a finished recording and an assembled session document, and *why each
one sits where it does*.

`TheFlow.md` was written against the older monolithic `session_doc.py`
(Pass 1–5, `quote_ledger.py`, the `QuotePicker` UI). The chain below is the
current split-CLI pipeline (`sd_plan` / `sd_narrate`), with upstream cleanup,
reviewed dialogue editing, and final voice/consistency checks. Where the two
disagree on post-recording ordering, this document is authoritative.

Skills live **outside this repo**. Codex sources are in
`~/src/mytools/dotfiles/codex/skills/`, linked through `~/.codex/skills/`;
Claude sources are in the sibling `dotfiles/claude/skills/` collection.
`dialogue-edit` is a Codex skill. `[ ]` marks an optional pass, not automatic
execution; every editing pass retains its own human checkpoint.

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
  → sd_narrate             ← continue using the existing UI
  → GM review of narration
  → [ /scrub ]            ← residual cleanup, if needed
  → [ /dialogue-edit ]    ← exact proposals → per-scene GM rulings → derived revision
  → /voice-critic         ← inspect the actual selected edited revision
  → /staged-consistency  phase 3, on that same selected narration
  → GM selects/promotes final scene versions
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
2. **Upstream defects get more expensive downstream.** A defect removed before
   `/scene-extract` costs nothing downstream. The same defect removed after
   `sd_narrate` costs a re-narration, and — if it changes the scene count — a
   re-plan and a full renumber.

Dialogue editing needs the context created by narration: it is deliberately
after `sd_narrate`. It improves how retained speech reads in the scene through
reviewed exact edits, without re-running the narrator. Source errors discovered
there are carried back to their owning stage rather than repaired by invented
dialogue.

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
| `sd_narrate` | Renders through the existing UI or CLI, using the selected reviewed smoothed extraction. Dialogue-edit changes neither its prompt nor its configuration. |
| `/scrub` | Residual cleanup when needed. Complete it before dialogue editing and voice fixes: a later scrub regeneration can discard downstream edits. |
| **`/dialogue-edit`** | After narration and any intended scrub pass, before final voice critique. Read the full scene, propose exact supported dialogue edits, obtain per-scene GM rulings, and write a separate revision. |
| `/voice-critic` | Review the actual approved revision for narrator/prose drift and register problems. Supply original scene identity and run provenance; do not accidentally critique an older raw/scrubbed file. |
| `/staged-consistency` phase 3 | Final consistency review names the same selected narration version. Missing events and source errors are carried to their owning stage. |
| GM promotion | Explicitly choose final reviewed scene versions for assembly. A dialogue-edit candidate or revision is not automatically collected. |
| `assemble` | Existing collection prefers `<scene>.scrubbed.md` per scene, falling back to raw `.md`. Confirm it selects the GM-approved final versions; the skill adds no new collection rule. |

## Placement details

The remove-recap and no-mech placements were established by the *obelisk*
chapter 10 pipeline run. Dialogue editing adds the later narration-context
checkpoint described below.

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

It also prevents a hard failure the audit hatch cannot be relied on to catch.
`sd_narrate` does write `<!-- table-speech reclassified: … -->` when it
reclassifies a mislabelled span (#396), but that is a best-effort record of the
calls it *did* make, not a detector. On ch10 scene 02 — a scene that was
*entirely* mechanical — it produced no hatch at all, and the tooling reached the
page as in-fiction dialogue: `"Quest log."` and `"I cannot see your pointer."`
narrated as things a character said aloud. Removing the mechanics upstream is
what stops that. The hatch is the review queue for whatever survives.

### `/dialogue-edit` — after narration, before final `/voice-critic`

The answer to “after no-mech or before voice-critic?” is **both**, with
narration between no-mech and dialogue-edit:

`voice-smooth → no-mech → UI narration → scrub if needed → dialogue-edit → voice-critic`.

no-mech removes table operation from the smoothed extraction. Dialogue-edit
uses the finished prose: it can join fragments, clarify a source-supported
utterance, or reduce accidental repetition while retaining cadence, uncertainty,
speaker identity, and inner narration. Meaningful pauses and separate speakers'
agreement are not automatically disposable.

The Codex skill lives at
`~/src/mytools/dotfiles/codex/skills/dialogue-edit/SKILL.md`. It runs in the
conversation, using approach B's editorial guidance and review-derived cadence
safeguards from CG #387 / campaigns PR #232. Its deterministic helper freezes
exact proposals and applies actual GM approvals. It adds no CG command or UI button.

**Continue narrating through the UI.** Single-scene and bundled generation now
share the accepted narration-v1 writing brief in
[`writing_brief.md`](../../config/agents/session_doc/narrate/writing_brief.md).
It applies across campaigns, with their declared voice and genre references.
The brief governs quotation selection, scene construction, knowledge boundaries,
and prose mode; references supply diction, cadence, register, and tense.
Dialogue-edit remains the subsequent GM-reviewed editing pass using approach B.

The generation brief comes from campaigns PR #232's archived
[`narration_v1.md`](https://github.com/kostadis/campaigns/blob/0355cdd28179650cf11ecb4435e4841fbe61d54c/experiments/sd-narrate/prompts/narration_v1.md).
Its seven writing paragraphs are unchanged bar one clause: v1 opened by
mandating **present tense**, and CG's brief defers tense to the campaign genre
reference instead (#395). Out-of-the-abyss and toee both mandate first-person
**past** across an existing bible; a shared brief declared to outrank them would
have flipped both campaigns on their next `sd_narrate` run. Present tense remains
the default when a campaign supplies no genre reference. The output instruction
retains CG's existing heading-free scene bodies (assembly supplies headings) and
bundle transport markers. Legacy word targets, mandatory inclusion of every quote,
and prose-mode speaker guessing no longer compete with v1. CG also drops v1's
blanket ban on an audit: the narrowly scoped table-speech hatch lives in its own
[`audit_hatch.md`](../../config/agents/session_doc/narrate/audit_hatch.md) block
and reaches every narration mode (#396), because the reclassification judgment
it records survived into the brief's sixth paragraph — and a judgment with no
review queue is an LLM scope decision with no human checkpoint. The hatch covers
mislabelled attribution only; the brief's licensed omission of incidental filler
is ordinary editorial work and is never logged there (#386). Existing narration
files remain as generated; future Narrate runs use the shared brief.

Each scene follows read → propose → GM review in chat or the shared standalone
page → apply exact approved changes → read the result and check adjacent seams.
Outputs live under `<session>/dialogue_edit/<scene-run>/`, outside active
narration inputs. The original remains intact. `dialogue_edit.sources.yaml`
records selected sources, decisions, revisions, and unresolved work. No
candidate is silently promoted into assembly.

Pass the exact approved revision to voice-critic with its original scene
identity, original `.knobs.json` location when available, and declared reference
provenance. Do not fabricate a new generation record for an edited scene.
The critic's prose scans often exclude dialogue: its report is not proof that
paraphrased dialogue is verbatim or faithful. The source review and GM ruling
carry that responsibility.

An early critique can diagnose systemic voice problems before local editing.
The final critique still follows the last approved edit; repeat affected checks
if further edits follow. If no-mech, scrub, or narration is rerun afterward,
reconcile the changed inputs and review revised proposals instead of replaying
stale edits.

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
