# Feature Specification: Port the gap-marking contract onto the repo's narration prompt

**Feature Branch**: `feat/454-gap-marking-contract`

**Created**: 2026-09-08

**Status**: Draft

**Input**: User description: "454"

Tracking: [#454](https://github.com/kostadis/CampaignGenerator/issues/454). Sub-issue of
[#418](https://github.com/kostadis/CampaignGenerator/issues/418). Parallel with
[#455](https://github.com/kostadis/CampaignGenerator/issues/455) (the document model);
[#456](https://github.com/kostadis/CampaignGenerator/issues/456) (the block editor) needs both.

## Context

`sd_narrate` asks one call to do two jobs: reshape the players' recorded dialogue into prose,
and author the scene description around it. Where the source attributes a passage to the GM,
the prompt forbids "the GM as a character" and offers no third option — so **silent
reassignment is the compliant move**. Across six drafts of one scene by three renderers, four
gave the GM's explanation of a two-way drop to a player character, dissolved it into a PC's own
observation, or dropped it. The finished prose does not say which. That is an attribution
error, the class this project reserves for a human checkpoint.

A contract that fixes it has been drafted and tested: where the source attributes description
or explanation to the GM, the model emits a marker instead of writing it, and the human author
fills the gap. Run unchanged over four scenes it was never written against, it produced 31
markers (6, 12, 4, 9), and **the GM has since read all 31 against their sources and accepted
them**.

### What is not established

**The contract has never met the prompt this repo ships.** The evidence was gathered against
`experiments/20260907-phandalin-fable-gm-gaps/prompts/base_system.md`, a flat nine-paragraph
contract that exists only in that directory. The repo's narration prompt is assembled from
fragments, and two of those fragments instruct precisely the absorption the contract forbids.

`config/agents/session_doc/narrate/writing_brief.md`, ¶6:

> GM descriptions become experienced facts; NPC speech voiced by the GM remains NPC speech.

`config/agents/session_doc/narrate/prose_mode.md`, ¶2 — the same first clause, a different
second one:

> GM descriptions become experienced facts; speech the GM supplies for an identified NPC or PC
> stays with that character.

The experiment prompt carried neither, so **the contract has never been tested against
opposition**. Appending it and leaving these in place is not the task; reconciling the three
texts is.

The two fragments differ in reach, and it matters: `{writing_brief}` is interpolated into
**both** `base.md` (per-scene) and `bundle_base.md` (all scenes, one exchange), so its
contradiction is always on. `prose_mode.md` reaches a prompt only when prose mode is selected,
which is off by default.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A GM's description is marked, not silently reassigned (Priority: P1)

A GM narrates a session where they described a place, explained how something works, and
adjudicated a few rolls. They render a scene with gap marking on. The description and the
explanation come back as visible gaps addressed to them; the adjudication is dropped as table
operation, as it is today; and everything the players said and did is written normally.

**Why this priority**: This is the feature. Without it the GM's material is redistributed to
characters with no record of the substitution — the failure #418 exists to remove.

**Independent Test**: Render one scene from the confirmation corpus with gap marking on and
confirm markers appear where the source attributes description to the GM, and that no GM
description arrives as a character's speech, perception, memory or inference.

**Acceptance Scenarios**:

1. **Given** a scene whose source contains a GM passage describing a place, **When** it is
   rendered with gap marking on, **Then** a gap marker appears in that position and no
   character speaks or perceives that content.
2. **Given** a GM turn that only confirms or adjudicates a player's question, **When** the
   scene is rendered, **Then** it is dropped as table operation and produces no marker.
3. **Given** a GM turn voicing a named NPC, **When** the scene is rendered, **Then** it is
   written as that NPC's dialogue and produces no marker.
4. **Given** gap marking is off, **When** a scene is rendered, **Then** the assembled prompt is
   byte-identical to today's and no marker appears.

---

### User Story 2 - The prompt states one rule about the GM, not two (Priority: P1)

A GM turns gap marking on. The prompt they get must not simultaneously instruct the model to
absorb GM description into the narrator's experience and to leave it for a human. Whichever
rule is in force must be the only one present.

**Why this priority**: Co-equal with US1 and inseparable from it. An appended contract sitting
above a fragment that contradicts it is not a tested configuration — it is two rules, and which
one wins is a property of the model rather than of the prompt. This repo has already paid for
that once: `#435` collapsed two drifted restatements of the speech-selection rule into one
string precisely because a repeated rule becomes two rules.

**Independent Test**: Build the assembled prompt with gap marking on and confirm the absorbing
sentence is absent. Build it with gap marking off and confirm the assembled prompt is
byte-identical to the current one.

**Acceptance Scenarios**:

1. **Given** gap marking on, **When** the per-scene prompt is assembled, **Then** it contains
   no instruction to turn GM description into experienced fact.
2. **Given** gap marking on **and** prose mode on, **When** the prompt is assembled, **Then**
   the same holds — the second copy of the sentence is governed by the same switch.
3. **Given** gap marking off, **When** the prompt is assembled in either mode, **Then** it is
   byte-identical to the prompt built before this feature.

---

### User Story 3 - The bundle path marks gaps too (Priority: P2)

A GM renders every scene in one exchange rather than one call per scene, with gap marking on.
The GM's descriptions are marked there as they are per-scene — the mode is a property of the
render, not of which path was chosen to produce it.

**Why this priority**: Narrower than US1 and US2 — one flag combination — but the failure mode
is the expensive one, and it is the *silent* variant. A bundle rendered without the contract
produces a whole session of reassigned GM material that looks finished, in the mode where the
GM believes the contract is protecting them.

**Independent Test**: Render the confirmation scenes as a bundle with gap marking on and
confirm markers appear, then compare against the same scenes rendered one call each. This is
the one user story whose evidence does not yet exist — see "What Q2 costs, recorded".

**Acceptance Scenarios**:

1. **Given** gap marking on and bundle mode selected, **When** the prompt is assembled,
   **Then** it carries the contract, exactly as the per-scene prompt does.
2. **Given** gap marking on and bundle mode selected, **When** the run completes, **Then** the
   scenes carry gap markers where the source attributes description to the GM.
3. **Given** gap marking on, **When** either render path is used, **Then** no run completes
   with the mode on and the contract absent from the prompt.

---

### User Story 4 - A finished render says which contract produced it (Priority: P3)

Months later a GM asks why one scene has gaps and its neighbour does not. The answer is on
disk beside the scene: whether gap marking was on, and which contract text was in force.

**Why this priority**: Real but not blocking. The renders are still correct without it; the
cost is paid when reconstructing a decision, and it is the same cost the genre-file digest was
added to remove.

**Independent Test**: Render two scenes with different settings and confirm the recorded
identity differs, from disk, without re-deriving it.

**Acceptance Scenarios**:

1. **Given** a scene rendered with gap marking on, **When** its record is read, **Then** it
   states that gap marking was on and identifies the contract text by content, not by copy.
2. **Given** the contract file is edited mid-session, **When** two scenes' records are
   compared, **Then** the difference is visible.

---

### Edge Cases

- **A scene with no GM turns at all.** No markers, and the absence is not an error. Marker
  count is not a quality measure — the corpus ranges 4 to 12 against 16 to 47 GM turns.
- **A GM turn that both adjudicates and describes.** The contract splits on function, not on
  turn, so the describing half is gapped and the adjudicating half dropped. The corpus
  contains this and the accepted rulings cover it.
- **Ten of sixteen GM turns are the GM voicing an NPC** (`**[GM, as the banker]**`). The
  contract says nothing about NPCs voiced by the GM, and the tested model drew the line
  correctly anyway — the banker was written as dialogue and only the four descriptive passages
  gapped. The ported contract must not lose that behaviour, and it must not depend on it.
- **The contract file is missing or unreadable while gap marking is on.** Rendering without
  the contract is the outcome the feature exists to prevent, so this refuses rather than
  falling back — the genre file's opposite ruling does not transfer, because a missing genre
  costs register while a missing contract costs attribution.
- **Gap marking on, prose mode on.** Both fragments carry the absorbing sentence; both must be
  governed by one switch, or the contradiction returns through the second copy.
- **A model that ignores the contract.** Out of scope to enforce mechanically at render time;
  the markers are checkable after the fact, which is what US4's record and the re-confirmation
  below are for.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: When gap marking is on, the assembled narration prompt MUST instruct the model
  that a passage the source attributes to the GM may not become a character's speech,
  perception, memory or inference, nor be absorbed unmarked into the narrator's voice.
- **FR-002**: When gap marking is on, the prompt MUST instruct the model to emit a gap marker,
  on its own line, where the source has the GM describing or explaining something, and to carry
  the scene on around it.
- **FR-003**: When gap marking is on, the prompt MUST retain the existing instruction that a GM
  turn which only confirms or adjudicates is table operation and is dropped.
- **FR-004**: When gap marking is on, the assembled prompt MUST NOT contain any instruction to
  turn GM description into experienced fact. This binds every fragment carrying that
  instruction, not only the always-on one.
- **FR-005**: When gap marking is off, the assembled prompt MUST be byte-identical to the
  prompt assembled before this feature, in both per-scene and bundle modes, with prose mode on
  or off.
- **FR-006**: The gap-marking mode MUST be selectable from the CLI and reachable from the
  Session Doc Editor, per the bidirectional-parity principle.
- **FR-007**: The contract text MUST live in a file and MUST NOT be stored as a configuration
  string, following the genre-rulebook precedent. Per the Q1 ruling that file is a narration
  prompt fragment in this repository, not a per-campaign document, so no new path field is
  added to any campaign config.
- **FR-008**: When gap marking is on and the contract text cannot be read, the run MUST refuse
  and name the path, rather than rendering without it.
- **FR-009**: Gap marking MUST reach the all-scenes bundle template as well as the per-scene
  one (Q2). Neither path may render with the mode on and the contract absent.
- **FR-010**: A completed render MUST record whether gap marking was on and identify the
  contract text by content digest rather than by embedding a copy of it. The record MUST be
  written by the render CLI, so a terminal run and a Session Doc Editor run produce the same
  record (Q3); the server MUST NOT write a second, parallel one.
- **FR-011**: The gap marker MUST be registered as pipeline apparatus with a named producer, so
  that deleting the prompt that emits it fails the build.
- **FR-012**: The 31 accepted markers from the confirmation corpus MUST be frozen as a fixture
  in the repository, with the counts per narrator, so re-confirmation has a criterion rather
  than an eyeball.
- **FR-013**: Re-confirmation MUST be run with the ported prompt and its result recorded: a
  gap that vanishes and a gap that appears where none was accepted are both reportable, and
  neither is settled by counts alone. It MUST cover both render paths, because Q2 admits the
  bundle path on evidence that does not yet exist for it.

### Key Entities

- **Gap contract** — the text instructing the model to mark rather than absorb GM material.
  One document; addressed by path; identified downstream by content digest.
- **Gap marker** — a line the model emits in place of GM description, carrying a one-sentence
  statement of what the source establishes there. Required output, not commentary. Survives
  into the per-scene file for #455 to consume.
- **Gap-marking mode** — a per-render setting, off by default, that selects the contract and
  suppresses the contradicting instruction.
- **Accepted-gap fixture** — the 31 markers from the confirmation runs, ruled correct by the
  GM, frozen as the criterion the port is measured against.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With gap marking off, the assembled prompt is byte-identical to the pre-feature
  prompt in all four combinations of render path and prose mode.
- **SC-002**: With gap marking on, no fragment of the assembled prompt instructs absorption of
  GM description, in either render path and with prose mode on or off.

  *Narrowed 2026-09-08, during implementation.* US2 says "whichever rule is in force must be the
  only one present", which reads as binding both modes. It cannot bind gap-**off**: the absorbing
  clause lives in two fragments, so gap-off with prose mode on has always carried it twice, and
  SC-001's byte-identity forbids tidying that. The criterion binds the mode that is new.
- **SC-003**: A re-run of the four confirmation scenes on the ported prompt produces gap
  markers in the positions the GM accepted. Boundaries may shift and exact counts will not
  match; a gap accepted as correct that vanishes, and a gap appearing where the GM ruled the
  scope wrong, are each reported individually rather than summarised.
- **SC-004**: Across the four re-run scenes, dialogue lines continue to outnumber narration
  lines, as they did two to four times over in every confirmation run.
- **SC-005**: No re-run scene contains a GM description rendered as a player character's
  speech, perception, memory or inference.
- **SC-006**: A bundle render with gap marking on never produces prose without the contract —
  measured as: zero renders complete in that combination unless the contract is in the prompt.
- **SC-009**: The bundle path is re-confirmed on its own evidence, not inherited from the
  per-scene runs: a bundle render of the confirmation scenes marks the accepted gaps, and its
  dialogue-to-narration balance stays in the band the per-scene runs held. A bundle that marks
  materially fewer gaps than the per-scene run of the same scenes is a reportable finding.
- **SC-007**: A GM can tell, from disk alone, whether a given finished scene was rendered with
  gap marking and against which contract text — without re-deriving it and without reading a
  copy of the contract embedded in the record.
- **SC-008**: Deleting the fragment that asks for gap markers fails the build rather than
  silently producing renders with no markers.

## Assumptions

- **The tested sentence is appended, not substituting.** `#418`'s body says "One sentence
  **replaces** the anchor above"; `prompt.diff` shows it appended, with
  `"…or the GM as a character."` left in place. The append reading is the one built, and the
  issue text is corrected where it becomes actionable.
- **The reconciliation is one rule under a switch, not a deletion.** With gap marking off,
  today's behaviour is correct and stays. The absorbing sentence and the gap contract are two
  statements of one rule about GM attribution, selected by mode — the `#435` pattern, and the
  reason FR-005 can demand byte-identical output rather than merely equivalent output.
- **The heading discrepancy does not transfer.** The experiment prompt said "Output only the
  finished scene under the supplied section heading" and `writing_brief.md` says "Do not
  include a heading" — but `assemble` builds the heading itself from each scene's frontmatter
  (`## {narrator} — {scene_name}`). `#418`'s "every run used its supplied section heading" is a
  property of a prompt this repo does not use, and needs no port. Recorded because the issue
  raises it, not because it is a gap.
- **`experiments/20260907-phandalin-gm-gaps-confirm/FINDINGS.md` predates the GM's review.** It
  still says the marked passages "have not been read against their sources, and only the GM can
  do that". That is now false and is corrected as part of freezing the fixture.
- **Re-confirmation runs on `claude-fable-5-1` at effort `medium`**, because that is what was
  tested. A model or effort change invalidates the transfer and requires re-running.
- **Existing renders are not regenerated.** Scenes already narrated are inputs to the rest of
  the pipeline; re-rendering one is a token-spending scope decision for the GM, not a side
  effect of this feature.
- **The mode is off by default.** Gap marking changes what a render produces, so a GM who has
  not asked for it gets today's behaviour unchanged — which is also what makes FR-005's
  byte-identical requirement checkable rather than aspirational.
- **This feature does not build the authored/composed document model.** Markers are produced
  and survive into the per-scene file; `#455` gives them a place to be answered and `#456` an
  editor. Assemble gating is `#455`'s.

## Rulings

Three scope decisions, ruled by the GM on 2026-09-08. `#454` asks for each by name; of the
third it says "deciding it silently is how the guarantee becomes folklore."

- **Q1 — the contract is a repo prompt fragment**, in `config/agents/session_doc/narrate/`,
  selected by the mode. Not a per-campaign file.

  This overrides `#454`'s own recommendation, which was the campaign, beside `voice/_genre.md`.
  The reason the rulebook lives there does not transfer: register genuinely varies per campaign,
  while "a passage the source attributes to the GM may not become a character's" is a pipeline
  attribution rule that does not. It still honours the precedent `#454` cites — that precedent
  is *file, never a configuration string*, and a fragment is a file. The `EditorPaths` argument
  in `#454` is about where a **path** belongs if there is one; this ruling means there is not.

- **Q2 — gap marking reaches both render paths.** `bundle_base.md` carries the contract as
  `base.md` does; no combination is refused.

- **Q3 — the run record moves into `sd_narrate`.** The CLI writes the per-scene settings
  sidecar and the server delegates rather than writing its own, so a terminal render and a
  Session Doc Editor render record the same thing. A record only the UI produces is the
  engine's state living in the face.

### What Q2 costs, recorded

The contract's evidence is entirely per-scene: four scenes, four separate calls. Extending it
to the bundle template is cheap — one more placeholder on one more file — but the *behaviour*
in a context where one response carries every scene is untested, and a degraded bundle produces
a whole session of reassigned GM material that looks finished.

So the ruling is taken with its cost attached: **SC-003 does not transfer to the bundle path on
the strength of the per-scene runs.** Re-confirmation covers a bundle render as well, and
SC-009 below is what makes that a criterion rather than an intention. If the bundle run shows
marker discipline degrading, the finding is reportable and refusing the combination stays
available as the fallback — that is the option not taken here, not an option removed.
