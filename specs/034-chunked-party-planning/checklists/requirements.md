# Specification Quality Checklist: Chunked, Code-Checked Party and Planning Documents

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-08
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

## Notes

- **Domain artifacts:**
  - The spec names domain artifacts the GM already works with: `players.yaml`, `party.yaml`, `planning.yaml`, the entity registry, the published dossiers and the annotation markers.
  - These are the user-facing vocabulary of this tool, as in spec 033. They are not implementation choices.
- **Defaults taken without a clarification marker** (each one is consistent with a standing ruling or with spec 033):
  - Replace the one-shot path for party and planning (single-user migrate-and-delete).
  - planning's NPC section comes from published dossiers and refuses by default (GM ruling 2026-10-07 for world_state).
  - Code orders Active Plots by latest activity, replacing the model's "most urgent first".
  - Legacy `pipelines/grounding/` party and planning CLIs are out of scope.
- `/speckit-clarify` is the place to overturn any of them.
- **Revised 2026-10-08 during `/speckit-plan`.** Measuring the cached OOTA notes found two things:
  - Thread names don't carry identity across chunks (550 of 554 names appear only once).
  - Party notes don't state their subject in a form code can read.

  The GM chose to retarget the thread registry (survey approach 9) with model-proposed, GM-ratified groupings. This adds User Story 3 and FR-009–FR-009e. The party grammar change is FR-002. All items still pass.
