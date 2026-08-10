# The extraction contract, as built

> **What this is.** The build record for issue #250 — what shipped, why it is
> shaped the way it is, what it found, and what it deliberately does not do.
> The *rulings* live in
> [`ExtractionContract_proposal.md`](ExtractionContract_proposal.md); this page
> is the implementation and the workflow.
>
> Task-oriented detail lives in two operator manuals:
> [quote verification](../cli/quote_verification_howto.md) and
> [transcript corrections](../cli/transcript_corrections_howto.md). Start with
> **[the workflow](#the-workflow-end-to-end)** below if you just want to run it.

---

## The one-paragraph version

A session's `.cleaned.vtt` is ground truth for every verbatim claim the
pipeline makes. It turned out to be a hand-edited file that a model had
changed 74 times with no record. The contract makes it **generated** — raw tape
plus a reviewable, cue-indexed record — and adds a second axis to quote
verification that answers *may the pipeline choose this*, separately from *is
this in the tape*. Both are deterministic and call no model.

---

## Two axes, and why they are not one

`sd_verify_quotes` already had three **verdicts**, and they answer one
question: *is this span in the tape?*

| verdict | meaning |
|---|---|
| `verified` | exact, or differing only by whitespace |
| `near` | traceable to a real line, but edited |
| `unverified` | no plausible source line — the fabrication signal |

The contract adds **refusals**, which answer a different question: *may the
pipeline choose this?* And the answer is routinely "no" for a span that is
perfectly verbatim.

```
> "The town has been protected by the strength of [Lathander]."
```

Strip the bracket and that matches the tape exactly — `verified`. It is also an
editorial hand sitting inside a span labelled verbatim, which is the defect
#250 was opened about. A single scale cannot hold both facts, and collapsing
them would have forced the wrong call on precisely the span that motivated the
work. So `Finding.verdict` and `Refusal` are computed independently, reported
separately, and a line can carry both `<!-- cg:unverified -->` and
`<!-- cg:refused:R3 -->`.

## What each rule is, in code

| rule | what it does | where |
|---|---|---|
| **R1** | Refuses a span the two sections carry differently that the tape cannot settle | `scan_section_conflicts` |
| **R3** | Refuses a span with an editorial insertion inside it | `find_bracket_refusals`, `editorial_brackets` |
| **R4** | Makes `.cleaned.vtt` generated from raw + a cue-indexed record | `campaignlib/vtt.py`, `campaignlib/transcript_corrections.py`, `session_doc/sd_corrections.py` |
| **R5** | Scopes the contract off in a section that declares it edits | `split_scene_sections`, `verify_artifact_contract` |
| **R6** | R1 still escalates a pair identical once brackets are stripped | (no code — the default) |

### R1 — the three outcomes

R1 pairs the inline-quoted spans of `## Scene summary` against the blockquotes
of `## Verbatim moments`. The human half is parsed **for pairing only** and can
never become a finding, so the worst a mis-parse can do there is fail to notice
a conflict.

- **consistent** — identical copies, or verbatim in both. *The load-bearing
  exclusion.* Without it the rule fires on any two similar-but-distinct real
  utterances and wakes the GM to adjudicate between two facts. It suppressed
  nine would-be interruptions on ch46.
- **settled** — exactly one copy is verbatim. The tape has named the faithful
  copy; the other is already reported by its own verdict.
- **refused** — neither copy is in the tape. Nothing mechanical can choose.

`near` never settles anything, because a similarity band says *an edit
happened*, never that the edit was *safe*.

### R3 — brackets by position, not by token

Four classes of bracket exist in a real extraction, and only one is a defect:

| class | example | disposition |
|---|---|---|
| speaker labels | `**[GM]**` | structural — preserve |
| sub-scene markers | `[scene tag — The Golden Eyes]` | structural — preserve |
| transcription markers | `[inaudible]`, `[unclear]` | a fact about the tape — preserve; deleting one fabricates certainty |
| **editorial insertions inside a quote** | `[the good stuff on]` | **refuse** |

Classifying by *token identity* across the file put the count at 3. Classifying
by *position* — every bracket inside a `> "…"` span — put it at 12. The
difference is that `[Lathander]` is a legitimate speaker label elsewhere in the
same file, and every marker carrying a comment matched no known token and fell
through uncounted.

A marker carrying a conjecture is a **hybrid**: `[inaudible — probable "I'll
fill you in"]` is half fact and half the editor's, and it is the editor's half
that would render. Hybrids are class 4. A quote that is *wholly* a marker is
`exempt` — there is no verbatim span for a bracket to sit inside.

### R4 — the tape becomes output

```
rec.transcript.vtt            raw, from Zoom. The archive. Never written.
transcript_corrections.yaml   hand-authored, one entry per cue. The record.
        │  sd_corrections apply
        ▼
rec.transcript.cleaned.vtt    generated. Everything downstream reads this.
```

Three properties carry the claim, each asserted directly in
`tests/test_transcript_corrections.py`:

1. **`was` is checked, never trusted.** A correction whose cue no longer says
   what it claims is refused. If the raw tape is ever replaced, every stale
   entry fails loudly instead of pasting yesterday's repair over today's words.
   `apply` is all-or-nothing for the same reason — a half-repaired tape is
   worse than an unrepaired one, because the record then describes a file that
   does not exist.
2. **Regenerating twice produces identical bytes.** No timestamp in the
   generated header; the record's `recorded` dates are where "when" lives.
3. **The raw tape is never written.**

`check` compares **cue sets, not whole files**, and that distinction is
load-bearing: a freshly imported session always differs from its regenerated
form in the NOTE header while being provably complete in every cue. Reporting
that as "unrecorded edits" would cry wolf on the one run where the record is
certainly right.

### R5 — the heading is the promise

A scene file whose moments heading reads `## Voiced moments` has declared its
quotes are tidied. R3 objects to an editorial hand inside a span *marked
verbatim*; R1 asks which of two copies is *faithful*. Neither question survives
the declaration, so both rules scope off.

**Verdicts do not.** `unverified` means untraceable to any line — a splice or a
fabrication — and that is still a defect in a layer that only claims to be
tidied. Measured by renaming the heading in a copy of ch46's `smoothed/`:
refusals **18 → 0**, verdict counts **completely unchanged**.

A file with no headings at all claims **nothing**, rather than defaulting to
verbatim. It has made no promise, and inventing one would let the contract fire
on a layout it was never shown.

---

## The workflow, end to end

Everything below is deterministic, calls no model, and costs nothing to re-run.

### Once per session, if the tape was ever hand-edited

```bash
cd ~/Phandalin/Phandalin/summaries/20260623

sd_corrections import --dir .     # capture what somebody already changed
$EDITOR transcript_corrections.yaml
sd_corrections apply  --dir .     # regenerate the cleaned tape
```

Every imported entry lands `verified: false`. They were never reviewed — that
is why the import exists. **Deleting an entry is how you revert an edit.**

### After each extraction stage

```bash
sd_verify_quotes --vtt *.cleaned.vtt --scene-extractions scene_extractions_new/
```

Read `## Refused` first, then `## Unverified`. A refusal is not a claim the
text is wrong; it is a claim the pipeline should not be the thing that decides.

### When a refusal turns out to be the tape's fault

This is the common case — on ch46 it was *every* case. Add an entry and
re-apply:

```yaml
- id: cue-0224-lathander
  cue: 224
  was: 'Gary Young: I mean, the town has been protected by the strength of the pandemic.'
  now: 'Gary Young: I mean, the town has been protected by the strength of Lathander.'
  recorded: 2026-08-11
  verified: true
  note: Zoom misheard Lathander; the tape reads it correctly 10x elsewhere.
```

```bash
sd_corrections apply --dir . && sd_verify_quotes --vtt *.cleaned.vtt …
```

**Where the tape is genuinely unclear, leaving it garbled is the right answer.**
`[inaudible]` exists for that, and approving a guess writes fiction into ground
truth.

### Whenever you like

```bash
sd_corrections check --dir .    # is the record complete? is the tape current?
```

---

## What the build found

The interruption counts were the cheap part.

**Every measurement in the design doc moved once the rules were real code.**

| | doc said | measured |
|---|---|---|
| R3 spans/session | 7–10 | **12** |
| R1 interruptions, `new/` | 2 | **4** (of 17 paired: 5 consistent, 8 settled) |
| R1 interruptions, `smoothed/` | 2 | **6** (of 15 paired) |
| clarifying brackets | "`[Lathander]` is the one" | **0 of 12** |
| unrecorded tape edits | not suspected | **74** |

The 2/2 figure came from a scratch pairing regex run over a whole section at
once, where one unbalanced quote character pairs across a line break and
swallows everything after it. The clarifying-bracket claim counted "Lathander"
occurrences across the whole file instead of at the cue in question — at cue
1211 the tape says *"much respect for **the thunder**"*, so that bracket
replaces rather than clarifies.

**One behaviour produced every finding.** Zoom mishears a word; the extraction
quietly repairs it inside a span marked verbatim.

| cue | tape says | extraction says |
|---|---|---|
| 224 | `the strength of **the pandemic**` | `the strength of Lathander` |
| 245 | `like a Brewbarry **bathroom**` | `like a Brewbarry bathrobe` |
| 1211 | `much respect for **the thunder**` | `much respect for [Lathander]` |
| 324 | `that's our next **system**` | `that's our next [stop]` |

**And the same behaviour, one layer down, in the ground truth itself.**
Importing ch46's tape found 74 substitutions made by `/vtt-spell-pass` — a
chat-driven pass with no reviewable output, not a repo tool. Most were
proper-noun repairs. Three inserted `Slipper-Shine`, a surname nobody spoke, at
cues 168, 206 and 414. One turned *"the Telosians have been defeated"* into
*"the Talosian have been defeated"*, fixing the spelling and breaking the
grammar.

That is the project's own anti-pattern — a model making scope decisions with
the changed file as the only record — applied not to an extraction but to the
document every verbatim guarantee is measured against.

**The completeness proof.** Regenerating ch46 from raw plus the imported record
reproduces the hand-edited tape with all **1,244 cues byte-identical**; only
the NOTE header differs. That is what says the record is complete rather than
merely plausible.

---

## Decisions, and the options that lost

**The record is per-session, not campaign-wide.** R4 as ruled said
`docs/corrections.yaml`. Ninety-odd entries per session cannot share a file
holding five document corrections, and Phandalin has 42 sessions. The ruled
*mechanism* is unchanged and the path is an argument.

**It does not extend `provenance/corrections.py`.** That package is statically
guarded against every write sentinel — `write_text`, `mkdir`, `.replace`
outright — and a tape generator is a writer. Extending it meant breaking the
guard or splitting one feature across two packages to satisfy it.

**Corrections apply on the tape, not at match time.** The rejected alternative
left the tape untouched and had `sd_verify_quotes` apply corrections while
matching. Every other VTT consumer — `enhance_summary`, `scene_extract`,
`vtt_voice_compare` — would then read the uncorrected tape, so the verifier and
the generators would disagree about what was said.

**R6: R1 still escalates a bracket-only pair.** Skipping them would drop `new/`
from 4 to 3. Rejected because the two copies are not saying the same thing
about the tape: at cue 224 the copy that renders repaired the garble
*silently*, and the copy that does not render *declared* the repair with a
bracket. Same words, opposite honesty.

**The model is not the flagger.** The tempting shortcut on R2 and R3 was "let
the model flag it when the oddity looks intentional". That experiment already
ran by accident: both #245 benchmark arms had the Vucherdin span in front of
them, and Fable kept the garble with no audit entry while Opus silently
reclassified it. Neither flagged anything, in opposite directions.

---

## What this does not do

- **Refusals do not block rendering.** `sd_narrate` still renders refused
  spans. Under R5 that is the settled end state rather than a gap: the layer
  narration reads has stopped claiming exactness, so there is nothing for a
  renderer-side block to enforce there.
- **Nothing is auto-corrected, ever.** The only writes are additive, idempotent
  HTML-comment markers. `scrub_mechanics.py` was an autonomous repair pass that
  stripped spells out of narration (#151); verbatim text is the one thing this
  code must never touch.
- **No threshold was calibrated.** 0.85 is spec 007's starting point and is
  explicitly not calibrated for a local model. Every number here is at that
  default.
- **ch46 was not re-extracted.** It is evidence, not a migration target. The 16
  proposed corrections ship as proposals with the evidence attached
  (`transcript_corrections_proposed.md`), not as edits — which word was really
  spoken is a judgement about the table.
- **No other session has been imported.** ch46 is the only tape with a record.
  Every other `.cleaned.vtt` in every campaign is still an unrecorded
  hand-edited file.

---

## Where to read next

| you want to | read |
|---|---|
| run the checks | [quote verification how-to](../cli/quote_verification_howto.md) |
| fix a tape | [transcript corrections how-to](../cli/transcript_corrections_howto.md) |
| know why a rule is what it is | [the rulings](ExtractionContract_proposal.md) |
| know what `near` really means | [quote verification how-to § the trap](../cli/quote_verification_howto.md) |
