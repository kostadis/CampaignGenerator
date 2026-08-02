# Specification Quality Checklist: State-Projection Rendering as its own service

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-01
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

### Iteration 1 — 2026-08-01

**One item failing**: three `[NEEDS CLARIFICATION]` markers remain, at FR-007, FR-022 and FR-024.
They are deliberate, not gaps in the survey — each is a genuine design fork with more than one
defensible answer and a different resulting scope:

- **FR-007** — the per-path output layout, and the fate of the one existing cross-path input.
  Scope-impacting: it decides whether this feature changes an existing path's behaviour.
- **FR-022** — how much of the review surface the first interface release covers.
  Scope-impacting: the difference between a two-control page and the full checkpoint set.
- **FR-024** — whether the shared service's own curation decisions surface in this path's interface.
  Scope boundary between two services' interfaces.

Two further questions from the research seed (where the shared service's configuration document
lands; which service owns the synthesis engine both renderers invoke) were **not** marked here —
they are placement decisions that do not change what the feature must do, and are recorded in
Assumptions for `/speckit-plan` to settle.

**Content-quality note**: the `Input` field quotes the operator's description verbatim, which names
several scripts. Kept as given — it is a quotation of the request, not a requirement written in
implementation terms. The requirements themselves name no module, framework, or file path.

### Iteration 2 — 2026-08-01, after `/speckit-clarify`

**All 16 items passing.** Five questions asked and answered; all three `[NEEDS CLARIFICATION]`
markers resolved and two further ambiguities surfaced by the coverage scan closed.

Changes that affected checklist state:

- *No [NEEDS CLARIFICATION] markers remain* — now passing. FR-007 split into FR-007/007a, FR-022
  into FR-022/022a, FR-024 into FR-024/024a/024b.
- Two requirements added that did not exist at iteration 1: **FR-007b** (pre-existing drafts are
  never moved or deleted; a rendering service refuses while one is present) and **SC-011** (its
  measurable outcome). Both come from a gap the coverage scan found, not from the original markers —
  both live campuses have drafts at the old shared locations, so every campaign hits this on first
  run.
- Terminology normalised to "service" throughout, with "path" reserved for prose descriptions of a
  route through the pipeline. A glossary of the four canonical service names is recorded under
  Clarifications. User Story 4's scenarios were rewritten so they no longer promise thread triage
  and draft promotion in the interface, which the Q2 answer moved out of this release.
