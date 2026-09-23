# Implementation Plan: A bracketed speaker label is a speaker, not a scene tag

**Branch**: `feat/453-bracketed-speaker-labels` | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/027-bracketed-speaker-labels/spec.md`

Tracking: [#453](https://github.com/kostadis/CampaignGenerator/issues/453), a sub-issue of
[#418](https://github.com/kostadis/CampaignGenerator/issues/418) but independently valuable.

## Summary

Narrator eligibility decides which characters may narrate a scene, and its second filter asks
"did this character speak here?". That filter throws away every bracketed speaker label,
because the same bold-bracket shape is also used for beat markers. On a session written
entirely in the bracketed convention no character is recorded as speaking anywhere, the
narrator pool is empty, and the planner refuses. Two of the four sessions in the frozen
evidence corpus are in that state; one has 39 discarded turns for a single character.

The approach: **make the reader stop deciding identity, and make the module that already holds
the roster decide it.** `session_doc/io.py` becomes a pure label reader returning every bold
line-start label verbatim; `session_doc/plan_eligibility.py` tokenises brackets and joint
labels into candidate parts and resolves each against the roster and the declared game master
by folded exact match. Nothing is admitted or rejected for its shape, so a beat marker that
happens to contain a character's name — `[scene tag — Vukradin demands a meeting]` — stays
inert.

No model call, no new flag, no state change on disk.

## Technical Context

**Language/Version**: Python 3.14

**Primary Dependencies**: none new. Stdlib `re`; existing `campaignlib.players_config`
(`norm_name`, `GM_LABEL`) for folding and the game-master label.

**Storage**: files. Scene extractions (markdown), `party.yaml` (roster), `players.yaml`
(identities). All read-only in this feature; no file's shape changes.

**Testing**: pytest. `tests/test_plan_eligibility.py`, `tests/test_plan_review_regressions.py`,
plus new cases for the grammar.

**Target Platform**: Linux. CLI (`sd_plan`) and the FastAPI server that shells out to it.

**Project Type**: CLI-first pipeline library with a web face. This feature is library-internal.

**Performance Goals**: not a factor. A few hundred labels per session, one pass, no I/O beyond
files already read.

**Constraints**: deterministic, zero tokens, no network, no LLM call. Bare-convention sessions
must produce byte-identical output.

**Scale/Scope**: ~5–15 scenes per session, tens of labels per scene, 33 distinct label forms
observed across the four-session corpus.

## Constitution Check

*GATE: passed before Phase 0. Re-checked after Phase 1 — see below.*

| Principle | Assessment |
|---|---|
| **I — Disk is Truth, the Model is a Draft** | PASS. Reads files, calls no model, writes nothing. The roster on disk becomes *more* authoritative: it is now the only thing that makes a label resolve. |
| **II — The Human Checkpoint is Non-Negotiable** | PASS, and load-bearing. This is an **attribution** filter, the precision class the principle names. The one genuinely undecidable question — what a multi-character joint label means for presence — was put to the GM and ruled (option A, presence for every character named), recorded in the spec with its trade-off. Everything the system cannot resolve is reported to the GM rather than guessed. No LLM output feeds anything here. |
| **III — Retrieval and Render are Separated** | PASS. No retrieval call and no render call in any touched function. |
| **IV — Verbatim is Sacred** | PASS. No quoted span is read, rewritten, or re-attributed. The feature reads *labels*, and it makes the label's attribution more faithful to the source, not less. Note the principle's own clause: re-attribution is II's, not IV's, and nothing here adapts who said what — it stops discarding who said what. |
| **V — One Seam per Boundary** | PASS. No external dependency touched. Identity folding stays behind `norm_name`, its single existing seam. |
| **VI — CLI is the Engine, UI is a Face** | PASS. The change is in the library the CLI uses. The server continues to shell out to `sd_plan`; no logic is reimplemented in a router. |
| **VII — Extract Once, Synthesize Deliberately** | N/A. No extract/synthesize passes involved. |
| **VIII — State is Discoverable** | PASS, improved. Today a discarded label is invisible. After, every label that resolves to nobody is surfaced in the eligibility report. |
| **IX — The UI Mechanizes; Claude Converses** | PASS. No judgement moves into the UI. The GM's ruling on an exclusion stays where it is — reading the report and editing the plan. |
| **X — Selection is Explicit; No Silent "All"** | N/A. No batch operation, no selection set. |
| **XI — Parity is Bidirectional** | PASS, no new face required, and this is a **recorded ruling, not an omission**: the feature adds no CLI flag and no new capability. It corrects an existing one that the UI already reaches by invoking `sd_plan`. There is nothing new for a human to reach. |
| **XII — One Spelling per Option** | PASS. No option introduced, so no family to introduce it across. `norm_name` remains the single spelling of "fold a name for comparison" and is reused rather than re-implemented. |
| **XIII — Breaking State Changes Migrate Out of Band** | PASS, no migration. The principle is triggered by a change to the *shape* of state on disk; no file's schema, layout or name changes. Existing extractions are re-interpreted, not rewritten, and nothing on disk is upgraded as a side effect of a run. Eligibility *output* changes — that is the feature. |

**Gate result: pass, no violations.** Complexity Tracking is therefore omitted.

**Post-Phase-1 re-check**: unchanged. The design added one reporting decision (research
Decision 3, which bucket an unresolved bracketed label is printed in). It is a verbosity
choice with no effect on presence or attribution, so it does not engage Principle II's
checkpoint; it is recorded with its trade-off and is reversible in one line.

## Project Structure

### Documentation (this feature)

```text
specs/027-bracketed-speaker-labels/
├── plan.md                      # This file
├── spec.md                      # Feature specification
├── research.md                  # Phase 0 — four decisions, corpus measurements
├── data-model.md                # Phase 1 — label → part → resolution → class
├── quickstart.md                # Phase 1 — how to validate, against the frozen corpus
├── contracts/
│   └── label-grammar.md         # Phase 1 — the grammar and its guarantees
├── checklists/
│   └── requirements.md          # Spec quality checklist (16/16)
└── tasks.md                     # Phase 2 — NOT created by /speckit-plan
```

### Source Code (repository root)

```text
session_doc/
├── io.py                 # CHANGE: becomes a pure label reader. Drops the
│                         #   `startswith("[")` and `== GM_LABEL` filters, which are
│                         #   the identity rule in the module that cannot see the roster.
├── plan_eligibility.py   # CHANGE: owns tokenisation, resolution and classification.
│                         #   Filter B (`compute_eligibility`) and the report buckets
│                         #   (`_stranger_buckets`, `report_eligibility`).
└── sd_plan.py            # UNCHANGED: caller. Already supplies the roster.

campaignlib/
└── players_config.py     # UNCHANGED, read-only: `norm_name`, `GM_LABEL`.

tests/
├── test_plan_eligibility.py           # EXTEND: all four label conventions.
│                                      #   `test_scene_speakers_skips_bracketed_action_beats`
│                                      #   moves from the parse level to the eligibility level.
├── test_plan_review_regressions.py    # EXTEND: one-parse invariant (FR-009) still holds.
└── (new)                              # The grammar's worked examples, and a corpus
                                       #   regression pinning the two bare-convention sessions.

experiments/20260907-phandalin-gm-gaps-confirm/inputs/   # UNCHANGED, read-only evidence.
```

**Structure Decision**: Single project, existing layout, two files changed. No new module —
the feature removes a misplaced copy of the identity rule rather than adding a layer. Filter A
(`campaignlib/players_config.py`, player display names from the tape) and Filter B
(`session_doc/plan_eligibility.py`, character names from the extraction) stay separate, as
`CLAUDE.md` and `players_config.py:508` both require; this feature touches only Filter B.

## Risks

| Risk | Mitigation |
|---|---|
| Resolution drifts to containment, and `[scene tag — Vukradin demands a meeting]` fabricates presence | A named test case in the grammar suite. This is the feature's worst failure — a false attribution — and it is one keystroke away from the correct rule. |
| Beat markers flood the "looks like a roster character" report and dilute the channel `#385` built to be read | Research Decision 3 routes bracketed-unresolved to the quiet bucket; SC-008 asserts the loud bucket does not grow. |
| A bare-convention session changes behaviour | Tokenisation never touches a bare label — structural, not merely tested. SC-004 diffs against a captured baseline. |
| The short-form case (`[Valphine]` vs roster `Valphine Sotorra`) reads as a bug in review | Documented in spec Assumptions and in quickstart's expected results as out of scope, with the reason: folding is not approximate matching. |
