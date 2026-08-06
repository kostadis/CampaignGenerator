# Specification Quality Checklist: Two-Phase Extraction Agent

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-03
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Constitution Check

Per Governance, every spec is tested by name against all ten principles before
implementation begins.

| Principle | Verdict |
|---|---|
| I — Disk is Truth, the Model is a Draft | ✅ FR-009 puts findings on disk; the transcript is never modified |
| II — The Human Checkpoint is Non-Negotiable | ✅ FR-018 preserves the between-stage gate; FR-006 forbids autonomous correction; the consistency report is read by a human, not fed to another call |
| III — Retrieval and Render are Separated | ✅ Not engaged — this feature neither retrieves nor renders |
| IV — Verbatim is Sacred | ✅ The feature exists to enforce this. FR-006 and SC-007 forbid touching quote text |
| V — One Seam per Boundary | ✅ No new external dependency. FR-003 means the verifier crosses no model boundary at all |
| VI — CLI is the Engine, UI is a Face | ✅ FR-022 states it directly |
| VII — Extract Once, Synthesize Deliberately | ✅ No pass is collapsed; a check is added beside existing passes |
| VIII — State is Discoverable | ✅ FR-009 and FR-023 — the report is a file, and its staleness is visible |
| IX — The UI Mechanizes; Claude Converses | ✅ The UI runs the steps; the judgment (which findings are real, what to fix) happens in Claude, per the stated assumption |
| X — Selection is Explicit; No Silent "All" | ⚠️ Engaged by FR-013 — "checks every file in the extractions directory". Verification spends no tokens, so the blast-radius concern Principle X guards against does not apply; but the plan should confirm this reading rather than assume it |

## Notes

- Validation passed on the first iteration. No spec updates were required.
- **One open item for planning**, not a spec defect: the Principle X reading
  above. FR-013's directory-wide sweep is the right default for a free,
  read-only check, but it should be confirmed deliberately in `plan.md`.
- The spec deliberately **excludes** the "applies the output" step present in
  the original feature request. This was the GM's explicit choice; it is
  recorded in Assumptions so it can be revisited rather than silently lost.
