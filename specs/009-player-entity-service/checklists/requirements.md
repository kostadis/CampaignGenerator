# Specification Quality Checklist: Player Entity & Config Service

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-15
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

### Iteration 1 — 2026-08-15

Three `[NEEDS CLARIFICATION]` markers were raised, all of them GM rulings rather than
lookups, because each changed what gets built. All three were answered explicitly and
are recorded in the spec header.

| Question | Ruling |
|---|---|
| How far "renders from the entity" reaches | **All the way into routing.** Retire the second hand-typed character list; replace first-name-prefix resolution of voice and example files with an explicit declaration. |
| Per-campaign or shared | **Per-campaign, with a stable person identifier** that is the same string across campaigns. No cross-campaign read in this feature. |
| Who owns the character↔player binding | **The player entity.** `party.yaml` drops its `player:` field. |

### Iteration 2 — 2026-08-15

Re-validated after the rulings landed. All items pass.

- "Scope is clearly bounded" now passes: rulings 1 and 2 were the boundary, and the
  Assumptions section lists five named exclusions (#129, campaigns#172, #312, #293, any
  cross-campaign read).
- Ruling 1 grew the spec by one user story (US3, declared routing) and six functional
  requirements (FR-026 … FR-031), and added SC-006 — a countable outcome: **zero**
  identity joins resolved by name prefix.
- The spec carries a `## Context — what exists today` section outside the template's
  shape. Kept deliberately: it records measured facts from CG#314 and nine related
  issues, so a reader does not take the premises on faith.

### Iteration 3 — 2026-08-15 (`/speckit-clarify`)

Five questions asked, five answered, recorded under `## Clarifications` in the spec.
Checklist state unchanged: **16/16 → 16/16 items passing**, no regressions, nothing
newly checked (the spec already passed every item; clarification removed latent
ambiguity rather than a failing check).

| # | Gap closed | Where it landed |
|---|---|---|
| 1 | A person who both runs the game and plays a PC had no stated speaker label | FR-021a, US2 scenario 2a, edge cases |
| 2 | The stable identifier's form and producer were unstated, so FR-005 was unachievable as written | FR-004, FR-005, FR-005a, US1 scenarios 6–7, Key Entities |
| 3 | FR-030 required shared examples to be "declared" without saying how — and the old mechanism was the filename rule FR-027 deletes | FR-030, FR-030a, FR-030b, US3 scenarios 3/3a, edge cases |
| 4 | Two players sharing a display name left speaker normalisation with two valid answers | FR-005b, US1 scenario 8, edge cases, Key Entities |
| 5 | A departed player collided with FR-038 — deleting them breaks the transcript archive, keeping them lies about the table | FR-001, FR-011a, FR-019, FR-038, US1 scenario 9, edge cases, Key Entities |

Functional requirements grew from 40 to 46. Three of the five answers **narrow** the
system rather than widening it (refuse a duplicate identifier, refuse a duplicate
display name, no fall-through for an undeclared file), which is the intended direction:
this feature's whole thesis is that a refusal is better than a guess.

### Constitution note

Checked against `.specify/memory/constitution.md` v1.2.0. No LLM call is introduced.
Adoption reports conflicts instead of resolving them (Principle II), the check is
read-only and model-free (Principle I), and everything the page does is doable at the
CLI with the file as the interchange (Principles VI and IX). No deviation to record.
