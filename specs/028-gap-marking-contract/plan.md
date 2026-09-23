# Implementation Plan: Port the gap-marking contract onto the repo's narration prompt

**Branch**: `feat/454-gap-marking-contract` | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/028-gap-marking-contract/spec.md`

Tracking: [#454](https://github.com/kostadis/CampaignGenerator/issues/454), a sub-issue of
[#418](https://github.com/kostadis/CampaignGenerator/issues/418).

## Summary

A tested contract makes the model mark GM description rather than silently reassign it to a
player character. It has never met the prompt this repo ships, and two fragments of that prompt
instruct exactly the absorption it forbids — `writing_brief.md` ¶6 always, `prose_mode.md` ¶2
under `--prose-mode`.

The approach: **replace the contradicting sentence in place with a placeholder, and let the mode
choose its value.** One statement of the GM-attribution rule, selected by a flag, rather than an
appended contract arguing with a fragment above it. The absorb variant is today's sentence
character-for-character, which makes "gap marking off changes nothing" a byte-identical claim
provable against a frozen copy of the existing prompt golden.

Then: a `--gap-marking` flag with its config field and UI toggle, the same treatment for the
bundle path, a render record written by the CLI rather than the server, and a re-confirmation run
against the 31 markers the GM accepted.

No new dependency, no schema migration, no model call in the deterministic half.

## Technical Context

**Language/Version**: Python 3.14; Vue 3 + TypeScript for the one toggle.

**Primary Dependencies**: none new. Existing `session_doc/narrate.py` template machinery
(`_load_template`, `_fill`), `campaignlib.load_agent_prompt`.

**Storage**: files. Prompt fragments under `config/agents/session_doc/narrate/`; per-campaign
`config/session_doc.yaml` gains one optional bool; a per-scene `*.knobs.json` gains three fields.
No file changes shape.

**Testing**: pytest. The existing prompt golden (`tests/golden/prompts/narrate_system_matrix.json`,
265 entries, byte-identical) plus a frozen pre-feature copy; a new gap-marking prompt suite; the
`test_apparatus_marker_pairing.py` pattern for the producer binding.

**Target Platform**: Linux. `sd_narrate` at the CLI and the FastAPI server that shells out to it.

**Performance Goals**: not a factor for the deterministic half. The prompt matrix doubles from
256 to 512 combinations, which lengthens two test builds and nothing at runtime.

**Constraints**: gap marking off must be byte-identical, in both render paths, with prose mode
either way. Re-confirmation runs on `claude-fable-5-1` at effort `medium` because that is what
was tested.

**Scale/Scope**: four prompt fragments, two placeholders, one flag across three surfaces, one
sidecar ownership split, one re-confirmation run of 4 scenes twice.

## Constitution Check

*GATE: passed before Phase 0. Re-checked after Phase 1 — see below.*

| Principle | Assessment |
|---|---|
| **I — Disk is Truth, the Model is a Draft** | PASS, and strengthened. The feature's whole purpose is to stop the model quietly authoring what the GM said and present it as a draft the human completes. The contract is a file; the record names it by digest rather than copying it. |
| **II — The Human Checkpoint is Non-Negotiable** | PASS, and this is the principle the feature implements. Attribution is the named precision class, and today's prompt makes silent reassignment the compliant move. The marker *is* the checkpoint. Note what is deliberately not built: no auto-resolve, ever — asked to resolve its own gaps the tested model gave both of the GM's lines to a character while keeping the real player lines around them, reproducing the exact failure the markers had prevented. |
| **III — Retrieval and Render are Separated** | PASS. No retrieval call is added to any touched function. |
| **IV — Verbatim is Sacred** | PASS, and the feature narrows an existing exposure. Traceability is universal, and a GM passage silently becoming a character's speech is a re-attribution — which v2.0.0 explicitly assigns to II, not IV. The gap marker carries a *summary* of what the source establishes, in a marker addressed to a human, and claims nothing verbatim. Research D6 keeps the marker visible to the unknown-name scan precisely so an invented name inside one is still caught. |
| **V — One Seam per Boundary** | PASS. No external dependency touched; all model calls stay behind `campaignlib`. |
| **VI — CLI is the Engine, UI is a Face** | PASS, and research D8 repairs an existing breach of it: the render record is produced today only by the server, so a terminal render records nothing. The CLI becomes the writer and the server merges its outcome. |
| **VII — Extract Once, Synthesize Deliberately** | N/A. No extract/synthesize passes. |
| **VIII — State is Discoverable** | PASS, improved. After this, a finished scene says from disk whether gap marking was on and against which contract text — for both launch paths. |
| **IX — The UI Mechanizes; Claude Converses** | PASS. The UI gains a toggle, not a judgement. Ruling on a gap stays with the GM and is `#456`'s surface. |
| **X — Selection is Explicit; No Silent "All"** | N/A. No batch selection set. The bundle path is a render mode, not a selection. |
| **XI — Parity is Bidirectional** | PASS. `--gap-marking` ships with its Session Doc Editor toggle in this feature, not a follow-up. No CLI-only capability, so no ruling to record. |
| **XII — One Spelling per Option** | PASS. One name, one meaning, one default across CLI / config / route. The default is declared once on `NarrateKnobs` and the route takes it from the resolved config rather than re-spelling a literal — the pattern `tests/test_ensemble_config_defaults.py` enforces next door. `sd_narrate` is the only renderer, so the family is one script. |
| **XIII — Breaking State Changes Migrate Out of Band** | PASS, no migration and no migration document. The principle is triggered by a change to the *shape* of state. `NarrateKnobs` gains an optional bool with a default: a config written before this feature loads unchanged and takes it. Nothing is retired, relocated, or given a new meaning; no workspace needs an operator action. The `*.knobs.json` gains fields, and its only reader (`_read_knobs_sidecar` → the Review screen's `applied_knobs`) tolerates absent keys, so an old sidecar stays readable. |

**Gate result: pass, no violations.** Complexity Tracking omitted.

**Post-Phase-1 re-check**: unchanged, with one thing worth stating rather than leaving implicit.
Research D8 splits one file between two writers (CLI: render identity, server: run outcome). Two
writers of one artifact is the shape of a Split-Brain, and it is admitted here only because the
writes are strictly sequential — the server merges only after the subprocess it launched has
exited — and because the alternative, two files, guarantees the disagreement rather than risking
it. If implementation finds the split invasive, the fallback is Q3's other branch, and that is a
ruling to go back and ask for rather than take silently.

## Project Structure

### Documentation (this feature)

```text
specs/028-gap-marking-contract/
├── plan.md                      # This file
├── spec.md                      # Feature specification, with the three rulings
├── research.md                  # Phase 0 — eight decisions
├── data-model.md                # Phase 1 — entities, and the one file that gains fields
├── quickstart.md                # Phase 1 — validation, deterministic half first
├── contracts/
│   └── gap-marking.md           # Phase 1 — P1–P6, refusal, the record
├── checklists/
│   └── requirements.md          # Spec quality checklist (16/16)
├── golden_pre_feature.json      # FROZEN before the first template edit — FR-005's evidence
├── accepted_gaps.json           # The 31 markers the GM ruled correct
└── tasks.md                     # Phase 2 — NOT created by /speckit-plan
```

### Source Code (repository root)

```text
config/agents/session_doc/narrate/
├── writing_brief.md              # CHANGE: the ¶6 sentence becomes {gm_attribution}
├── prose_mode.md                 # CHANGE: the ¶2 sentence becomes {gm_attribution_prose}
├── gm_attribution_absorb.md      # NEW: today's writing_brief sentence, character-for-character
├── gm_attribution_gap.md         # NEW: the contract
├── gm_attribution_prose_absorb.md# NEW: today's prose_mode sentence
└── gm_attribution_prose_gap.md   # NEW: its second clause alone

session_doc/
├── narrate.py                    # CHANGE: register the two placeholders; fill the brief before
│                                 #   interpolating it; thread `gap_marking` through
│                                 #   build_narrate_system and build_bundled_narrate_prompts.
├── sd_narrate.py                 # CHANGE: --gap-marking; refuse on a missing contract;
│                                 #   write the render record (research D8).
└── apparatus.py                  # UNCHANGED — the marker is content, not apparatus (D5).

server/
├── session_editor_config_shared.py  # CHANGE: narrate.gap_marking on NarrateKnobs.
└── routers/scene_editor.py          # CHANGE: pass the flag in _build_narrate_cmd; stop
                                     #   writing the sidecar, merge outcome into the CLI's.

frontend/                             # CHANGE: one toggle in the Stage-④ knobs (Principle XI).

tests/
├── test_prompt_golden_pre_feature.py # NEW: gap-off == frozen golden, byte for byte.
├── test_gap_marking_prompt.py        # NEW: P2–P6, both paths, prose on and off.
├── test_session_doc_prompts.py       # EXTEND: gap_marking joins the matrix (256 -> 512).
└── test_apparatus_marker_pairing.py  # EXTEND: the marker's producer binding (D5).
```

**Structure Decision**: existing layout. The contract is a prompt fragment rather than a
per-campaign file (Q1), so no campaign config gains a path and no workspace needs touching. The
four new fragments exist because two slots each need two variants and the two slots' current
texts differ in their second clause — research D3.

## Phasing

The feature splits cleanly at the token boundary, and the split is worth keeping.

| Phase | What | Cost |
|---|---|---|
| **A — the prompt** | Fragments, placeholders, `gap_marking` threaded through both builders, the frozen golden, P1–P6 tests. | Zero tokens. Fully verifiable. |
| **B — the surfaces** | `--gap-marking`, the config field, the route, the UI toggle, the refusal path. | Zero tokens. |
| **C — the record** | The sidecar ownership split (research D8). | Zero tokens. Separable; the riskiest. |
| **D — re-confirmation** | Four scenes per-scene, then four as a bundle, against `accepted_gaps.json`. | Tokens. The only part that can answer whether the contract *works* here. |

A–C are complete and testable without D. D is the only part whose result could send the design
back — specifically, a bundle run that marks materially fewer gaps than the per-scene run would
reopen the Q2 ruling.

## Risks

| Risk | Mitigation |
|---|---|
| The gap-off prompt moves without anyone noticing, and every existing render silently changes | The frozen pre-feature golden (research D4). Regenerating the live golden is the thing that would hide this, which is why the frozen copy is a separate file taken before the first edit. |
| The contract lands in the prompt and the contradicting sentence stays, so two rules argue | FR-004 binds every fragment, not just the always-on one; P6 asserts the rule appears exactly once; the prose-mode combination is tested explicitly, because that is the copy easiest to forget. |
| The bundle path is admitted on evidence that does not cover it | Recorded in the spec as the cost of the Q2 ruling, not buried. SC-009 and FR-013 make bundle re-confirmation a criterion; refusing the combination stays available as a fallback. |
| The sidecar split leaves two writers disagreeing | Sequential by construction — the server merges only after its subprocess exits. Named in the post-Phase-1 re-check rather than left implicit, with the fallback stated. |
| The marker gets stripped at assembly, or masked from the unknown-name scan, by analogy with audit comments | Research D5 and D6 state the distinction and why it is the opposite one. The marker is content; a name invented inside one is exactly what the scan should catch. |
| Deleting the fragment silently produces markerless renders | SC-008 and the producer binding, modelled on the test that exists because `26ec5b0` did precisely this to another marker. |
