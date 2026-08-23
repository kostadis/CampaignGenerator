# Specification Quality Checklist: Batched Scene Extraction

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-22
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

All items pass. The three scope decisions that were open at first draft were
ruled on by the GM and are recorded in the spec's "Resolved decisions" table:

1. **Default output ceiling → 32,000** (from the per-scene 8,192), sized against
   the measured ~29K full-session output. FR-017 / FR-017a / FR-017b.
2. **Call shape → one call when the projection fits, fewest fitting groups when
   it does not**, with the ceiling as the GM's lever to collapse a run back to
   one call. FR-006a–FR-006d, SC-001a/b, SC-009.
3. **Activation → the editor pre-selects batched on the subscription backend**,
   off on the metered API, visible and overridable either way. FR-007 / FR-007a.

A fourth area was raised by the GM after the rulings and is now explicit rather
than implied: **Force / skip-if-exists**. The per-scene mode already gets this
right, but batching introduces a specific way to lose it — building the request
from all scenes and discarding the already-extracted ones on the way out, which
would spend the full projection on a nearly-finished session. FR-008a forbids
that (the filter runs before the request is built, and already-extracted scenes
do not influence group sizing); FR-008b makes the all-done case a zero-call
no-op; FR-008d ties both modes to the same on-disk evidence so they cannot
disagree about what is left. SC-005a–SC-005d measure it.

Two notes on the shape of the spec, both deliberate:

- **Three P1 user stories.** Ordinarily a spec has one. Here the token saving
  (US1) is a regression unless partial-response resumability (US2) and verbatim
  fidelity (US3) hold, so none of the three is independently shippable and all
  three carry the same priority.
- **A measurements section precedes the user stories.** The call-shape and
  ceiling decisions turn entirely on measured sizes, so the numbers are stated
  as evidence up front rather than asserted inside requirements.
