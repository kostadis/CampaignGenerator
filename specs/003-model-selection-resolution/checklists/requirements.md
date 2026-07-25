# Specification Quality Checklist: Model Selection Resolution

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-07-25
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

- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`

### Validation notes (iteration 2 — all items pass)

**Content Quality.** The "Current behaviour" table names operator-visible surfaces (Grounding,
Session Prep, Setup, Connection Graph) rather than modules or functions. Config document names
appear only as citations to existing docs, never as prescriptions for how to build the fix. No
language, framework, or endpoint is named.

**Requirement Completeness.** All three [NEEDS CLARIFICATION] markers from iteration 1 were
resolved by the operator and recorded in the `## Clarifications` section — none were guessed:

1. **Scope** → the four config-owning services get an override; the four stateless ones inherit.
   This preserves D1 ("stateless by decision"), which the "all six services" option would have
   reversed. Drove FR-003 and FR-004.
2. **Backend tier** → backend moves to the platform tier with per-service override, making the
   backend rule identical to the model rule. Drove FR-006, FR-007, FR-008, and made the ensemble's
   per-stage split an instance of the rule rather than an exception.
3. **Stale override** → refuse the run and report the incompatibility. Drove FR-009, FR-010,
   FR-011 and SC-008.

Requirements grew 11 → 15 and success criteria 7 → 9 as a result; each new one traces to a
clarification above.

**One flagged consequence, not a defect in the spec.** Clarification 3 reverses documented,
tested ensemble behaviour (silent substitution of a foreign model name). It is recorded in
Assumptions as the single non-backward-compatible change in the feature, with the note that the
existing tests asserting silent substitution must be rewritten to assert refusal. Planning should
treat that as known work, not discover it.

### Amendment during planning (2026-07-25)

Phase 0 research found that clarification 1 had been answered against a factually wrong list: it
named **Setup** as a config-owning service (it owns none — there is no `SetupConfigService` and no
`setup.yaml`) and omitted **Party** and **Planning**, which each own a document. The question was
re-put to the operator with the correction and re-answered on the same rationale: the override set
is the five services that own a configuration document — Ensemble, Session Doc Editor, Grounding,
Party, Planning — and Setup joins the inheriting group. FR-003, FR-004, the Key Entities and the
Clarifications section were updated to match; the feature now creates **zero** new config files.

Checklist verdict is unchanged — all items still pass — but this is recorded because the spec's
scope moved after the checklist first passed, and a reader comparing the two would otherwise find
an unexplained discrepancy.

**Feature Readiness.** Each user story is independently testable and independently valuable:
US1 delivers correctness with no override mechanism at all, US2 adds the override tier, US3 adds
visibility over both. US2 gained two scenarios in iteration 2 covering the ensemble's per-stage
case and the absence of an override on inheriting services.
