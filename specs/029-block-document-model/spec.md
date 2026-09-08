# Feature Specification: The block document model, and a reviewer that works on a phone

**Feature Branch**: `feat/455-block-document-model`

**Created**: 2026-09-08

**Status**: Draft

**Input**: User description: "455"

Tracking: [#455](https://github.com/kostadis/CampaignGenerator/issues/455). Sub-issue of
[#418](https://github.com/kostadis/CampaignGenerator/issues/418). Needs
[#454](https://github.com/kostadis/CampaignGenerator/issues/454) (shipped — the markers exist);
[#456](https://github.com/kostadis/CampaignGenerator/issues/456) (the block editor) needs this.

## Context

`sd_narrate --gap-marking` now writes `[GM NARRATION — TO BE WRITTEN: …]` where the source
attributes description to the GM, instead of letting a character absorb it. **Nothing consumes
those markers.** A scene comes back with gaps in it, the GM reads them, and there is no file
that records what they decided and no way to get their prose back into the chapter.

This is that layer: the block model, the authored record, the composed output, and the gate that
stops a chapter assembling with markers still in it. Deterministic — no model call anywhere in
it, which is the point rather than an implementation detail.

### The review happens on a phone

Ruling gaps happens **at work, on a mobile device**. That is the primary surface for this step,
and it is why the reviewer lands here rather than with the editor in `#456`: it needs no server,
no auth and no framework, only the block model this feature already builds.

The 31 gaps of the confirmation corpus were ruled on a page published to claude.ai. That page's
**UX is correct and is the one being kept**; its *delivery* is not. Three things change:

- **The page stops being generated per session.** One versioned reviewer file, saved to the
  device once; a session arrives as a JSON document pasted into it.
- **It cannot be an artifact.** The GM drafts with other models, and an artifact ties the surface
  to one of them.
- **Every block is editable**, not only the gaps — `#418`'s own framing, because the seam is
  where a sentence usually needs a tweak.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Rule a scene's gaps from a phone, with no network (Priority: P1)

A GM has fifteen minutes at work and a scene full of gap markers. They open a page already saved
on their phone, paste in the scene, and work down it: reading the model's prose, reading each gap
against the GM turns that produced it, and **ruling** it — mine to write, cut, or wrong marking.
Some they write on the spot. Most they mark *mine, later*, and finish properly at a desk.
Nothing is installed, nothing is logged into, and no machine of theirs needs to be switched on.

**Finishing the ruling is a complete outcome.** A scene where every gap is ruled and eight are
still to be written is a successful mobile session, not a half-done one, and the page must say
so rather than showing it as incomplete.

**Why this priority**: This is where the human checkpoint actually happens. Without it the
markers are produced and never ruled on, and the feature `#418` exists to deliver stops one step
short of the person it was built for.

**Independent Test**: Export one scene, open the reviewer on a phone with networking disabled,
paste the export, and rule every gap. Delivers the whole review step on its own — even with no
other part of this feature built.

**Acceptance Scenarios**:

1. **Given** a saved reviewer file and a scene export, **When** the GM pastes the export with
   the device offline, **Then** the scene renders with its prose and gaps interleaved in reading
   order.
2. **Given** a rendered scene, **When** the GM reads a gap, **Then** that scene's source GM turns
   are available on the same page, so the gap is ruled against the source rather than from
   memory.
3. **Given** a rendered scene, **When** the GM rules a gap without writing anything, **Then** the
   ruling is recorded and counts as ruled, and the gap is still shown as awaiting prose.
4. **Given** a scene where every gap has been ruled and some are unwritten, **When** the GM looks
   at the progress, **Then** ruling reads as complete and writing reads as outstanding — two
   figures, neither masking the other.
5. **Given** rulings already made, **When** the page is reloaded, **Then** either the work is
   still there or the GM was told plainly, before starting, that it would not be.

---

### User Story 2 - Take a gap to another model, and bring the prose back (Priority: P1)

The GM has ruled a gap "mine to write" but wants help drafting it. They copy from the reviewer,
paste into whatever chat they are using, draft there, and paste the result back into the gap's
field.

**Why this priority**: Co-equal with US1 — it is why the reviewer must not be tied to one
vendor's surface. Without it the mobile session ends at "I have opinions" rather than "I have
prose".

**Independent Test**: Rule a gap, copy, and confirm the clipboard holds enough for a model with
no other context to draft that passage: the scene so far, the gap, and the GM turns behind it.

**Acceptance Scenarios**:

1. **Given** a scene with gaps ruled, **When** the GM copies, **Then** the clipboard holds the
   scene's prose so far, the gaps awaiting the GM's own writing, and the source GM turns for
   each — enough for a model with no other context.
2. **Given** the copied text, **When** it is pasted into any chat, **Then** it reads as a request
   to draft those passages, not as a data structure.
3. **Given** a drafted passage, **When** the GM pastes it into that gap's field, **Then** it is
   recorded as the GM's authored text, indistinguishable in the record from one they typed.

---

### User Story 3 - The model's prose is editable, and the edit is recorded as an edit (Priority: P2)

The GM reads a paragraph the model wrote and wants to change one sentence. They edit it in place.
The record afterwards says that block was the model's and a human changed it — not that the
model wrote it, and not that the human wrote it from nothing.

**Why this priority**: Real and explicitly asked for, but the review is useful without it. It is
separable from US1 and US2, and it is the story that gives the block vocabulary its third state.

**Independent Test**: Edit one prose block, and confirm the record distinguishes it from both an
untouched block and a gap the GM authored.

**Acceptance Scenarios**:

1. **Given** a rendered scene, **When** the GM edits a block the model wrote, **Then** the edit
   is kept and the block is marked as model-written-and-edited.
2. **Given** an untouched prose block, **When** the record is written, **Then** it carries no
   authored text — only what the human contributed is stored.

---

### User Story 4 - The authored work is a file, and generated files are never hand-edited (Priority: P1)

The GM's rulings and prose live in one hand-authored file per scene. The narration the model
produced, and the finished document that merges the two, are both generated and are never edited
by hand. Re-running any generator reproduces them.

**Why this priority**: The rule the rest of the pipeline already runs on — the tape's
`transcript_corrections.yaml` is the same shape, and it exists because a chat-driven pass once
put 74 unrecorded substitutions into a transcript. Without this, a GM's writing lives only in a
generated file that the next run destroys.

**Independent Test**: Author a record by hand, compose, and confirm the composed document
contains the GM's prose in the right places and is reproducible from its two inputs.

**Acceptance Scenarios**:

1. **Given** a narration with markers and a record of rulings and prose, **When** composed,
   **Then** the output carries each authored passage where its gap was.
2. **Given** the same two inputs, **When** composed twice, **Then** the results are identical.
3. **Given** a record whose gaps are not all answered, **When** composed, **Then** the unanswered
   ones remain visible as gaps rather than vanishing.
4. **Given** a record authored against one draft, **When** the draft has since changed, **Then**
   the mismatch is detected and reported rather than silently composing the GM's prose against
   prose it was never written for.

---

### User Story 5 - A chapter is never assembled with open gaps in it (Priority: P2)

The GM assembles a session document. If any scene still has a gap nobody answered, assembly
refuses and names the scenes, rather than producing a chapter with `[GM NARRATION — TO BE
WRITTEN: …]` sitting in the middle of it.

**Why this priority**: The failure it prevents is loud and recoverable — a marker in a finished
chapter is embarrassing rather than dangerous. But an assembled chapter feeds the release append
and the chapter split, so a marker that reaches it travels.

**Independent Test**: Assemble a session where one scene has an unanswered gap, and confirm the
refusal names that scene.

**Acceptance Scenarios**:

1. **Given** a session where every scene is composed and answered, **When** assembled with the
   gate on, **Then** it assembles from the composed documents.
2. **Given** a session where one scene has an open gap, **When** assembled with the gate on,
   **Then** it refuses and names that scene.
3. **Given** a scene with both a composed and a scrubbed variant, **When** assembled, **Then**
   the outcome is the one ruled in Q2 below and is never a silent choice between them.

---

### User Story 6 - Re-narrating never silently destroys authored work (Priority: P2)

The GM re-runs narration on a scene they have already written gaps for. Their work is not
overwritten.

**Why this priority**: Narrower than the others, and it is a refusal rather than a capability —
but the work it protects is the only thing in this pipeline a human wrote from scratch.

**Independent Test**: Author a record for a scene, re-run narration on it, and confirm the run
refuses and says why.

**Acceptance Scenarios**:

1. **Given** a scene whose record has authored content, **When** narration is re-run on it,
   **Then** it refuses and names the file holding the work.
2. **Given** the same scene, **When** the GM explicitly asks to re-roll, **Then** the refusal is
   lifted and what happens to the existing record is stated before it happens.

---

### Edge Cases

- **A scene with no gaps at all.** Reviews as pure prose, composes to itself, and does not hold
  up assembly. Marker count is not a quality measure.
- **A gap the GM rules should never have been marked.** It is a ruling, not an error, and the
  composed output must not contain a marker for it.
- **A gap ruled "mine to write" and left empty.** The **normal** end state of a mobile session,
  not a half-finished one. It is distinct from a gap nobody has looked at, it counts as ruled and
  not as written, and assembly still refuses on it.
- **The GM edits a prose block to empty.** Deleting the model's paragraph is a legitimate
  editorial act; the record must distinguish it from an untouched block.
- **The export is pasted into the reviewer twice**, or a different scene is pasted over one
  part-way reviewed. The second paste must not silently discard the first scene's rulings.
- **The pasted text is not a valid export** — truncated by a mobile clipboard, or the wrong file.
  Says so plainly; never renders half a scene as if it were whole.
- **The export is from a newer reviewer than the one on the phone.** The device holds a file that
  is only replaced deliberately, so this will happen. It must be detected and named.
- **Two scenes in one session declare the same scene number** — the case `#429` refuses at
  assembly. Composition must not merge their records.

## Requirements *(mandatory)*

### Functional Requirements

**The block model**

- **FR-001**: A narration MUST be readable as an ordered list of blocks, each either prose or a
  gap, such that reading the blocks in order reproduces the narration.
- **FR-002**: Each block MUST carry a stable identifier and an anchor drawn from the text it was
  read from, so a record can be matched back to the draft it was authored against.
- **FR-003**: Every block MUST carry a state distinguishing at least: written by the model,
  written by the model and edited by a human, written by a human, removed by a human, a gap
  ruled the GM's to write but **not yet written**, and a gap nobody has ruled on.

**The authored record**

- **FR-004**: A per-scene record MUST store **only what the human contributed** — rulings,
  authored prose, and edits — never a copy of the model's untouched output.
- **FR-004a**: The record MUST distinguish a gap ruled "mine to write, not yet written" from a
  gap nobody has ruled on, because a completed triage pass consists entirely of the former.
- **FR-004b**: The record MUST support an optional critique of the *marking* — that the gap's
  scope was wrong, or that the model should have written it — separately from the disposition,
  and a critique MUST NOT change the composed document.
- **FR-005**: The record MUST identify the draft it was authored against by content, so a later
  draft can be detected as different.
- **FR-006**: Composing a narration and its record MUST be deterministic: the same two inputs
  produce byte-identical output.
- **FR-007**: The narration and the composed document MUST both be generated, and MUST NOT be
  hand-edited. Only the record is authored by a human.
- **FR-008**: Composing against a draft the record was not authored for MUST be reported, not
  performed silently.

**The reviewer**

- **FR-009**: The reviewer MUST be a single file that works with no network, no server, and no
  external resources, so it functions offline and from local storage on a mobile device.
- **FR-010**: The reviewer MUST NOT be regenerated per session. It is versioned once; a session
  is supplied to it as data.
- **FR-011**: A session's data MUST be supplied by pasting it into the page.
- **FR-012**: The session data format MUST carry a version, and the reviewer MUST refuse data
  whose version it does not understand, naming the mismatch.
- **FR-013**: Export MUST default to one scene per file, so that what the GM has to paste stays
  as small as the workflow allows.
- **FR-014**: The reviewer MUST show, for each scene: the prose and gaps interleaved in reading
  order, each gap's text, the scene's full source GM turns, and **two** progress figures — how
  much is ruled, and how much is written.
- **FR-015**: The reviewer MUST let the GM rule each gap, write a passage for it, and **edit any
  prose block**.
- **FR-016**: The reviewer MUST retain work across a page reload, or state plainly before work
  begins that it will not.
- **FR-017**: The reviewer MUST produce, on demand, text suitable for pasting into any chat as a
  request to draft the outstanding passages — carrying the scene so far, the gaps, and the
  source GM turns behind them.
- **FR-018**: Data exported for the reviewer MUST use the same block identifiers and anchors as
  the authored record, so a review can be reconciled with the draft later.

**The gate**

- **FR-019**: Assembly MUST offer a mode that refuses to assemble any scene holding a gap that is
  not written or cut, naming every such scene rather than the first, and distinguishing "ruled
  yours to write" from "not looked at" in what it reports.
- **FR-020**: Assembly MUST **refuse** a scene that has both a composed and a scrubbed variant,
  naming both files and the flag that records the choice — never picking by sort order (Q2).
- **FR-021**: Re-running narration over a scene whose record has authored content MUST refuse,
  naming the file, unless the GM explicitly asks otherwise.

**What must not happen**

- **FR-022**: No part of this layer may call a model. Enforced statically, not by review.
- **FR-023**: The gap marker's parser MUST be tied to the prompt that produces it, so the
  contract cannot be edited away from under a live parser without failing the build.

### Key Entities

- **Block** — one span of a narration: prose or gap. Carries an id, an anchor, and a state.
- **Gap** — a block the model declined to write, carrying a one-sentence statement of what the
  source establishes there.
- **Ruling** — the GM's decision about one gap. The vocabulary is Q1 below.
- **Authored record** — one per scene. Only the human's contributions, plus the identity of the
  draft they were made against.
- **Composed document** — narration plus record, generated, never hand-edited.
- **Session export** — the versioned data document a reviewer renders: blocks, gaps, source GM
  turns, and the scene's counts.
- **Reviewer** — one versioned file, saved to a device, that renders an export and produces
  rulings, prose and a drafting prompt.

## Success Criteria *(mandatory)*

- **SC-001**: A GM can rule every gap in a scene on a phone with networking disabled, having
  installed nothing and switched on no machine of their own.
- **SC-002**: Reviewing a second scene requires no new page — only new data.
- **SC-002a**: A GM can rule every gap in a scene without writing any prose, and the result is
  reported as a completed ruling pass with the writing outstanding — never as an unfinished one.
- **SC-003**: What the GM must paste in for one scene is small enough to be practical on a mobile
  clipboard; the four scenes of the confirmation corpus each fit comfortably.
- **SC-004**: A GM part-way through a review does not lose their rulings to a page reload; or, if
  they would, they were told before they started.
- **SC-005**: Text copied from the reviewer is enough for a model with no other context to draft
  the outstanding passages — verified by doing it.
- **SC-006**: Composing the same narration and record twice produces byte-identical documents.
- **SC-007**: A record authored against a stale draft is reported, in 100% of cases, rather than
  composed.
- **SC-008**: A chapter cannot be assembled with an unanswered gap in it while the gate is on,
  and the refusal names every scene responsible.
- **SC-009**: Re-running narration over authored work never destroys it without the GM having
  said so explicitly.
- **SC-010**: No model is called anywhere in this layer, proved by a build-breaking check rather
  than by inspection.
- **SC-011**: Deleting the prompt fragment that asks for gap markers fails the build rather than
  leaving a parser reading for something nothing emits.

## Assumptions

- **The reviewer reaches the device by whatever means the GM already has** — mail, a file
  service, a cable. Getting it there the first time is not this feature's problem; not needing to
  do it again is.
- **`--reroll` is a refusal in v1, not a merge.** Anchor matching for the re-narrate case is
  deferred: refusing is never wrong, only inconvenient, and an anchor that lands an authored
  block on the wrong prose is the same attribution error this whole feature exists to prevent,
  committed by us instead of by a model. Merge review is `#456`'s, with its UX.
- **The round trip stops at the clipboard.** Getting a review back into the authored record is
  explicitly out of scope: no paste-back command, no upload. The record is hand-edited, or
  written by `#456`. Designing the paste-back format before the workflow has been used for real
  is what this defers.
- **Copying out is not auto-resolution.** A human copies one gap out and pastes one passage back;
  the model is never handed the gaps unasked and never writes into the document. The guard
  against a button that resolves gaps automatically still stands and still needs its test — the
  evidence is on disk: asked to resolve its own 11 gaps, the model discarded nothing and gave
  both of the GM's Order-of-the-Gauntlet lines to a player character, on the one passage the
  markers had protected.
- **Existing narrations are not reprocessed.** Scenes already rendered without markers stay as
  they are; nothing migrates.
- **One session's scenes are reviewed independently.** There is no cross-scene state in a review.

## Rulings

Two scope decisions, ruled by the GM on 2026-09-08.

### Q1 — ruling and writing are two different completions

**Ruled: a disposition axis with an explicit "mine, not yet written" value, plus an orthogonal
critique axis.** The GM's own framing: *"'mine-to-write' and I will do later — so I can use the
mobile device to complete the majority of the reviews and then later on at my computer do the
proper edits."*

That is a better model than any option offered, and it corrects one of them. Option B was
presented with "a reviewer can rule every gap and still have a scene that won't assemble" as a
**cost** — as if it were the tool losing the GM's work. It is not a cost. It is the workflow:
the phone is a **triage** surface and the desk is a **writing** surface, and the record has to
be able to say "I have looked at all twelve and eight of them are mine to write" without
claiming the scene is finished.

| Disposition | Meaning | In the composed document |
|---|---|---|
| `unruled` | nobody has looked at it yet | stays a gap |
| `mine` | right gap, mine to write — **not written yet** | stays a gap |
| `authored` | mine, and the prose is here | the prose, in its place |
| `cut` | does not belong in the chapter | nothing |

`unruled` and `mine` both compose to a gap and are **not the same state**. Collapsing them would
throw away exactly the work a mobile session produces.

The critique axis is separate, optional, and never changes the output: `wrong-scope`,
`model-should-have-written`. It records that the *marking* was wrong rather than that the chapter
needs something, which is feedback on the contract — the signal `#454`'s re-confirmation showed
is worth having, since all 31 accepted gaps came back "right gap, mine to write" and the critique
axis is how the GM would have said otherwise.

**Consequence: two progress numbers, not one.** The reviewer reports how much is *ruled* — the
number a mobile session drives to completion — and how much is *written*, the number the
assembly gate reads. A page showing one number would either understate a finished triage or
overstate an unfinished chapter.

### Q2 — a scene with two final variants is refused, not guessed

**Ruled: refuse and make the GM name one.** `assemble` already does exactly this when two files
claim one scene (`#429`), for the same reason: which revision is final is knowledge only the
operator has, and this repo's convention is that a precision decision gets a human checkpoint
rather than a silent default. `--use` records the ruling in the command.

Never wrong, occasionally inconvenient. It also defers the ordering question — whether scrubbing
happens before or after reviewing — until the workflow has been run enough to have a habit,
rather than forcing one now.
