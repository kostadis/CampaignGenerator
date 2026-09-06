# Feature Specification: A narrator must have been in the scene

**Feature Branch**: `022-absent-player-narrator`

**Created**: 2026-09-06

**Status**: Draft

**Input**: User description: "I want you to fix https://github.com/kostadis/campaigns/issues/231#issuecomment-5560106398. If a player isn't present, then the player should not narrate."

## Context

`sd_plan` (Pass 3) assigns one first-person narrator per scene. In `~/phandalin/Phandalin/summaries/20260902` it assigned Scene 5 to **Brewbarry** in three independent runs — a character who speaks **zero** lines across all five scenes of that session, because his player (Stéphane Bourdeaud) was not at the table. Stéphane has no cues in the session VTT at all; the four speakers are the GM and the three players who attended.

Speaker labels per scene, counted from `scene_extractions/`:

| Scene | GM | Vukradin | Soma | Valphine | Brewbarry |
|---|---|---|---|---|---|
| 01 rumors_and_preparations | 91 | 89 | 29 | 9 | **0** |
| 02 the_sewer_stakeout | 50 | 46 | 43 | 13 | **0** |
| 03 encounter_in_the_sewers | 74 | 66 | 2 | — | **0** |
| 04 the_stakeout_of_denvar | 76 | 19 | 71 | 11 | **0** |
| 05 the_dead_drop | 73 | 63 | 54 | 16 | **0** |

The narrator *distribution* is byte-identical across the three runs (Vukradin ×2, Soma, Valphine, Brewbarry) despite each run rewording titles and focus lines, which rules out sampling variation. Three mechanisms produce it:

1. `sd_plan` builds the plan prompt from scene **titles only** — the extraction bodies, which carry the `**[Speaker]**` labels, are loaded by `load_scene_extractions()` and then discarded.
2. `--characters` is the full campaign `party.yaml` roster (`server/routers/scene_editor.py:2171`), never narrowed to who actually spoke this session.
3. The only coverage check in the system checks coverage of the **roster**, not of the scene: `sd_plan.py:165` warns when a roster character gets no section, and `config/agents/session_doc/plan.md` instructs "Rotate through the roster so no character dominates" / "every character should appear if possible". The system therefore *demands* a scene for Brewbarry and warns if it does not get one.

This feature addresses all three. Who narrates a scene is an **attribution decision** (Constitution Principle II), and it is currently made by a model from a scene title under an instruction that rewards spreading narrators onto characters who were not there. This feature moves the *eligibility* half of that decision out of the prompt and into two deterministic filters, and hands the residue — a scene no eligible narrator can cover — back to the GM as an explicit choice.

## The two filters

**Filter A — session attendance.** A player is present iff one of their declared `display_names` in `players.yaml` appears as a speaker label in the session VTT. A character played only by absent players is removed from the narrator pool for the whole session.

**Filter B — scene presence.** Within the surviving pool, a character with no speaker label in a given scene's extraction cannot narrate that scene.

The two read different label spaces and this is deliberate: the VTT is labelled with **player display names** (`Kostadis Roussos`, `David Mendenhall`), while `scene_extract` normalises its output to **character names** (`Vukradin`, `Soma`, `GM`). Filter A resolves people; Filter B resolves characters.

When Filter B leaves a scene with no eligible narrator, the planner does not guess — see User Story 3.

Attendance also reaches Pass 5. The narration prompt's roster block — the "never contradict these" anchor — currently names every campaign-active character with no indication of who was at the table, so it tells the renderer that Brewbarry is in the party and nothing more. It gains a marker for a character nobody voiced. See User Story 6.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - An absent player's PC is not offered a scene (Priority: P1)

A player misses a session. The GM runs the narration planner as usual. The plan distributes scenes only among characters whose players were at the table; the absent PC is not assigned a scene, not counted as a gap, and not named as a narrator anywhere in `plan.md`.

**Why this priority**: This is the reported defect and the whole of the user's stated rule. It is also sufficient on its own — with Brewbarry removed from the pool, Scene 5 goes to Vukradin or Soma, both of whom carry it. Shipping only this story fixes campaigns#231.

**Independent Test**: Run `sd_plan` against `summaries/20260902` with the session VTT and `config/players.yaml`. Assert `plan.md` contains no `narrator: Brewbarry` line and that every scene's narrator is in {Vukradin, Soma, Valphine Sotorra}.

**Acceptance Scenarios**:

1. **Given** a session VTT whose speaker labels contain no `display_names` for the player of character C, and a campaign roster containing C, **When** the planner runs, **Then** C is absent from the narrator pool and no scene is assigned to C.
2. **Given** the same session, **When** the planner runs, **Then** the "these characters have no section" warning does **not** name C — C having no section is the correct outcome, not a gap to report.
3. **Given** a session where every roster player has at least one speaker label in the VTT, **When** the planner runs, **Then** the pool is the full roster and Filter A changes nothing.

---

### User Story 2 - A narrator was in the scene they narrate (Priority: P1)

Each scene is narrated by a character who actually spoke in it. A character who attended the session but is absent from a particular scene is not eligible to narrate that scene, so the plan can no longer assign a first-person narrator who could not have observed the events.

**Why this priority**: P1 alongside Story 1 because the GM asked for both, and because Story 1 alone leaves the defect class intact — a present-but-absent-from-this-scene character is exactly as unable to narrate it as an absent player's PC. This is also what removes cause (1): the per-scene candidate list is verified structure the prompt must carry, so the planner stops choosing from titles alone.

**Independent Test**: Build a fixture from the 20260902 shape and assert that for each scene the candidate set equals the characters with ≥1 speaker label in that scene's extraction, and that the written plan's narrator for each scene is drawn from it.

**Acceptance Scenarios**:

1. **Given** a scene whose extraction contains no speaker label for character C, **When** the planner runs, **Then** C is not a candidate for that scene, regardless of how the scene's title reads.
2. **Given** a scene with two or more eligible characters, **When** the planner runs, **Then** the narrator is one of them and the plan states the presence evidence that made them eligible.
3. **Given** scene 03 (Vukradin 66, Soma 2, Valphine 0), **When** the planner runs, **Then** Valphine is not a candidate and both Vukradin and Soma are — a low line count is not an exclusion.
4. **Given** the eligible set for a scene, **When** the planner chooses among them, **Then** rotation across the session is a tiebreak only and never promotes an ineligible character.

---

### User Story 3 - An uncoverable scene becomes an explicit choice (Priority: P2)

A scene in which no eligible character speaks — a stretch of pure GM narration, or a scene the party's PCs sat out — cannot honestly be given a first-person narrator. Rather than picking one anyway, the planner writes three plans that differ in how they treat that scene, and the GM picks one before Pass 5 runs.

**Why this priority**: P2 because it is the residue of Stories 1 and 2, not a precondition for them; a session with no uncoverable scene never reaches it. But it is the difference between a filter that *refuses* and a filter that *helps* — without it, the hard filter simply blocks and the GM has nothing to act on.

**Independent Test**: Construct a session with one scene whose extraction contains only GM labels; assert three plans are written, that they propose materially different treatments of that scene, and that Pass 5 will not run until one is chosen.

**Acceptance Scenarios**:

1. **Given** a scene with no eligible narrator, **When** the planner runs, **Then** it writes the base plan plus two alternates, each proposing a different treatment of that scene — for example folding it into an adjacent scene, narrating it in a non-first-person or ensemble register, or assigning the character nearest it in the session and marking that they report it second-hand.
2. **Given** the three plans, **When** the GM reads them, **Then** each states which scene was uncoverable, why, and what its treatment is, without the GM opening the extractions.
3. **Given** three plans and no choice yet made, **When** the next pipeline stage is invoked, **Then** it refuses and names the pending choice — the selection is an explicit act, never a default (Principle X).
4. **Given** a session where every scene has at least one eligible narrator, **When** the planner runs, **Then** exactly one plan is written and no choice is requested.

---

### User Story 4 - The GM can see who was excluded and why (Priority: P2)

Before spending tokens on the plan call, the GM sees which characters were dropped — from the session and from each scene — and on what evidence, so a wrong exclusion is caught when it happens rather than discovered in the rendered prose.

**Why this priority**: Both filters are silent otherwise, and a silent exclusion is the same class of failure as the silent inclusion it replaces. It also carries the cost of the no-override ruling in *Assumptions*: the GM corrects a covered-PC misfire by hand, and cannot correct what they were not told.

**Independent Test**: Run the planner on a session with an absent player and a scene-level exclusion; assert the pre-call output names both, with their evidence.

**Acceptance Scenarios**:

1. **Given** a character excluded by Filter A, **When** the planner runs, **Then** it prints the character, the player, and the VTT path before the model call.
2. **Given** a character excluded from a scene by Filter B, **When** the planner runs, **Then** the scene, the character, and the eligible set for that scene are reported.
3. **Given** any exclusion, **When** the plan is written, **Then** the exclusions and their evidence are recorded on disk so the pool a plan was drawn from is recoverable afterwards (Principle VIII).

---

### User Story 5 - The filters are reachable from the web UI (Priority: P2)

A GM who runs the pipeline from the Session Doc Editor gets the same pool, the same per-scene candidates, and the same uncoverable-scene choice as a GM at the CLI, without configuring anything extra.

**Why this priority**: Principle XI — a capability the engine has and the UI cannot reach is an orphaned capability, and the UI is where this pipeline is actually driven. `_vtt_path(cfg)` and the `--players-config` helper already exist in `server/routers/scene_editor.py`, so the input wiring is small; presenting the three-plan choice is the real work.

**Independent Test**: Trigger the plan stage from the editor on a session with an absent player and assert the produced plan matches the CLI's for the same session; on a session with an uncoverable scene, assert the choice is presented and blocks Pass 5 until made.

**Acceptance Scenarios**:

1. **Given** a campaign whose editor config resolves both a session VTT and a `players.yaml`, **When** the plan stage runs from the UI, **Then** the subprocess command includes both and the pool is narrowed identically to the CLI.
2. **Given** an uncoverable scene, **When** the plan stage runs from the UI, **Then** the three plans and their differing treatments are presented as a choice, and the chosen plan is written to disk as the selection (Principle IX — the choice is a file, not browser state).

---

### User Story 6 - Pass 5 knows who was unvoiced (Priority: P2)

The narration prompt distinguishes "in the party" from "voiced at this session", so the renderer knows that no dialogue from an unvoiced character is real — while still holding enough about them to narrate the GM's placement of them accurately.

**Why this priority**: Filters A and B stop an unvoiced character *narrating*. They do nothing about how they are *rendered*, and Pass 5's roster block is the anchor the renderer is told never to contradict. A character the GM parked in a tavern must still be narratable; a character nobody voiced must not acquire invented dialogue.

**Independent Test**: Render a scene from the 20260902 session and assert the roster block marks Brewbarry as unvoiced while still carrying his species, class and player.

**Acceptance Scenarios**:

1. **Given** a character whose player was absent, **When** the narration prompt is built, **Then** the roster block names them, keeps their full grounding, and marks that nobody voiced them this session.
2. **Given** that marker, **When** the scene's extraction places the character in the fiction (a GM beat), **Then** nothing in the roster block contradicts that placement.
3. **Given** a session where everyone was voiced, **When** the narration prompt is built, **Then** the roster block is unchanged from today's.

---

### Edge Cases

- **No VTT available at plan time.** Attendance cannot be established. The planner must not silently fall back to the full roster — that is the current defect restored by omission. It refuses, naming the missing input. (A VTT always exists by Pass 3: `scene_extract` consumed it two stages earlier.)
- **Every roster player is absent from the VTT.** Almost certainly the wrong VTT, not a session nobody attended. Refuse rather than plan with an empty pool.
- **Exactly one player attended.** The pool is one character and every scene is theirs. Valid — rotation must degrade to this without warning about characters with no section.
- **Every scene is uncoverable.** Not a plan to choose between; refuse and say so, as with the empty pool.
- **A character nobody plays** (`plays: []` — a retired or NPC-held PC). No player means no attendance, so not eligible.
- **An inactive player** (`active: false`). Already excluded from the prompt roster by `player_name_for`; this feature's logic must not reintroduce them. Their historical VTT labels still resolve for archived sessions.
- **A player who attended under a display name not declared in `players.yaml`.** Indistinguishable from absence by Filter A. `players check --vtt` already reports undeclared labels; this feature must not paper over that, and its exclusion notice should be legible enough that the GM recognises the cause.
- **A scene whose only PC speaker is the same character as the adjacent scenes'.** Eligible set of one; that character narrates consecutive scenes. Correct, and rotation must not override it.
- **Speaker labels that are neither GM nor a roster character** (an NPC label, a guest). Ignored for eligibility — they were never narrator candidates.
- **A character nobody voiced whom the GM placed in a scene.** Exactly the Brewbarry case. They cannot narrate (Filters A and B), but they remain in the fiction and must stay renderable — the roster marker says "unvoiced", never "not present".
- **A `.scaffold.md` or smoothed extraction differing from the raw** in its speaker labels. Presence must be read from the same file the scene checklist is built from, so the evidence and the scene list cannot disagree.

## Requirements *(mandatory)*

### Functional Requirements

**Filter A — session attendance**

- **FR-001**: The system MUST derive per-session player attendance from the session VTT's speaker labels, matched against each player's declared `display_names` in `players.yaml`. A player with no matching label is absent.
- **FR-002**: The system MUST exclude every character played only by absent players from the narrator pool for the entire session.
- **FR-003**: The system MUST refuse to plan when attendance cannot be established (no VTT), rather than falling back to the full roster.
- **FR-004**: The system MUST refuse to plan when the derived pool is empty, naming the likely cause (wrong VTT).

**Filter B — scene presence**

- **FR-005**: The system MUST derive, per scene, the set of pool characters with at least one speaker label in that scene's extraction.
- **FR-006**: The system MUST treat that set as the scene's candidate narrators, and MUST NOT assign a narrator outside it.
- **FR-007**: The system MUST carry the per-scene candidate sets into the plan prompt as verified structure, replacing today's title-only checklist.
- **FR-008**: Presence MUST be read from the same scene files the checklist is built from, so the evidence and the scene list cannot disagree.
- **FR-009**: Any threshold MUST be presence, not volume: one speaker label makes a character eligible. Line counts MAY be reported as evidence but MUST NOT gate eligibility.

**Uncoverable scenes**

- **FR-010**: When any scene has an empty candidate set, the system MUST write three plans — a base and two alternates — differing in their treatment of that scene.
- **FR-011**: Each plan MUST state which scene was uncoverable, the evidence, and the treatment it proposes.
- **FR-012**: The system MUST NOT proceed to Pass 5 until the GM has chosen one of the three; the choice MUST be an explicit act recorded on disk, never a default (Principles IX, X).
- **FR-013**: When no scene is uncoverable, exactly one plan MUST be written and no choice requested.

**Pass 5 roster block**

- **FR-022**: The narration prompt's roster block MUST distinguish characters voiced at this session from campaign-active characters who were not, using the same attendance derivation as Filter A.
- **FR-023**: The marker MUST assert that the character was *unvoiced*, never that they were absent from the fiction — a GM may place an unvoiced character in a scene, and the roster block must not contradict the extraction.
- **FR-024**: An unvoiced character MUST retain full grounding in the block (name, player, species, class, subclass). Omitting them would leave the renderer narrating a GM placement with no facts.
- **FR-025**: `sd_narrate` MUST accept the attendance input under the same `--vtt` spelling as its siblings (Principle XII).
- **FR-026**: When every character was voiced, the roster block MUST be byte-identical to today's.

**Reporting, parity, and conduct**

- **FR-014**: The system MUST NOT report an excluded character as "having no section". The existing gap warning MUST be computed against the eligible sets, not the campaign roster — as written it demands the defect this feature removes.
- **FR-015**: Rotation across the session MUST act only as a tiebreak among eligible candidates and MUST never promote an ineligible character.
- **FR-016**: The system MUST report every exclusion before the model call, naming the character, the cause, and the artifact the decision was read from.
- **FR-017**: The system MUST record exclusions and their evidence in the run's on-disk artifacts (Principle VIII).
- **FR-018**: Both filters MUST be deterministic and MUST NOT consume a model call.
- **FR-019**: New planner inputs MUST reuse the existing option vocabulary — `--vtt` and `--players-config`, spelled and defaulted as on `sd_verify_quotes`, `scene_extract`, `sd_narrate` and `enhance_summary` (Principle XII).
- **FR-020**: The web UI MUST supply the same inputs and present the same choice, so CLI and UI produce the same result for the same session (Principle XI).
- **FR-021**: When every roster player attended and every scene has an eligible narrator, behaviour MUST be indistinguishable from today's.

### Key Entities

- **Player**: a person at the table. Already modelled in `players.yaml` with `display_names`, `plays`, and `active`. This feature adds no field.
- **Session attendance**: a derived, per-session set of players — those whose `display_names` appear in that session's VTT. Derived at plan time; not authored state, not editable, not a new file.
- **Narrator pool**: the campaign roster minus characters all of whose players were absent. Today this is silently the whole roster.
- **Scene candidate set**: per scene, the pool characters with at least one speaker label in that scene's extraction. Empty means uncoverable.
- **Plan alternates**: the two additional plans written when a scene is uncoverable, differing in that scene's treatment. Transient until the GM chooses; the choice is the durable artifact.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Re-running the planner on `summaries/20260902` produces a plan with no `narrator: Brewbarry` line, across repeated runs.
- **SC-002**: In that run, every scene's narrator has at least one speaker label in that scene's own extraction — verifiable without reading the prose.
- **SC-003**: For scene 03 the candidate set is exactly {Vukradin, Soma}; Valphine is excluded and Soma's two lines are not.
- **SC-004**: A GM reading the planner's output can name every excluded character and its cause without opening the VTT, `players.yaml`, or the extractions.
- **SC-005**: A session where everyone attended and every scene has an eligible narrator produces one plan, comparable to today's for the same inputs and model settings — the feature is inert when it has nothing to correct.
- **SC-006**: A session with an uncoverable scene produces three plans with materially different treatments of it, and the next stage refuses until one is chosen.
- **SC-007**: Both filters add no model call and no measurable wall-clock cost to the plan stage.
- **SC-009**: For 20260902, the narration prompt's roster block marks Brewbarry unvoiced while still carrying his player and class, and asserts nothing that the scene-05 extraction contradicts.
- **SC-008**: A regression test built from the 20260902 shape — five scenes, one roster character with zero VTT labels, one scene with a character absent from it — fails against today's code and passes after the change.

## Assumptions

- **Attendance is read from the tape, with no override.** Ruled by the GM on 2026-09-06. A player is present iff one of their declared `display_names` appears as a speaker label in the session VTT. There is no per-session attendance file, no UI toggle, and no way to overrule the derivation.
  - **Accepted cost:** the covered-PC case is wrong. If one player voices an absent player's PC for the night, those lines carry the *covering player's* label, so the covered character reads as absent and is excluded. The GM reinstates them by editing the chosen plan before Pass 5. This is why User Story 4 is not optional — an invisible wrong exclusion is not correctable.
- **Scene presence is a hard filter, not a weighting.** Ruled by the GM on 2026-09-06. A character with zero speaker labels in a scene cannot narrate it, and no volume threshold is applied above zero.
- **An uncoverable scene produces three plans, not a refusal.** Ruled by the GM on 2026-09-06, differing in the treatment of that scene and in any scene a treatment explicitly absorbs it into.
- **Attendance reaches Pass 5's roster block.** Ruled by the GM on 2026-09-06 when the Principle XII family question was reviewed. The marker says *unvoiced*, not *absent*, because the character may still be in the fiction.
- **All three refusals are hard, with no opt-out.** Ruled by the GM on 2026-09-06. Verified first that no session on disk across any campaign has a `plan.md` without a VTT, so nothing existing is blocked.
- The session VTT is available whenever the planner runs — by construction, since `scene_extract` consumed it two stages earlier and the editor config resolves it via `_vtt_path`.
- `players.yaml` is current for the campaign. A player whose real display name is undeclared reads as absent; `players check --vtt` is the existing tool for that and this feature does not duplicate it.
- Speaker-label extraction reuses the shape `pipelines/workspace/players.py:_read_vtt_speakers` already matches, so "this label is present" cannot mean two different things in two places.
- `scene_extract`'s speaker normalisation ("Character (Player)" → character, "GM (Name)" → GM) is reliable enough to read presence from. Where it is not, the failure is visible as an unrecognised label rather than a silent exclusion.
- The `.cleaned.vtt` and the raw `.transcript.vtt` carry the same speaker labels; corrections change words, not attribution. Either is acceptable for Filter A.
- No state on disk changes shape, so Principle XIII's migration document does not apply. The plan-choice artifact is new state, not migrated state.

## Out of Scope

Deferred to **kostadis/CampaignGenerator#385**:

- **Genuine split-party multi-POV.** When two eligible characters covered disjoint halves of a scene, both remain eligible and the planner picks one. Splitting a scene into multiple POV sections is a change to Pass 5's rendering contract, not to eligibility. (The ensemble-register treatment in User Story 3 overlaps this, but only for a scene with *no* eligible narrator.)
- **The prompt's "most interesting perspective" criterion**, which remains the tiebreak among eligible candidates and is not being replaced by a better literary rule.
