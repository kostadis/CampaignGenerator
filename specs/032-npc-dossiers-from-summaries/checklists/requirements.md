# Specification Quality Checklist: Summary-Native NPC Dossiers

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-06
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain (FR-004: whole scene; creatures: registry NPCs only; UI: separate NPC dossiers page)
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

- Names such as `summary_native`, `canon.yaml` and `docs/npcs/` are user-facing artifacts of the existing pipeline, not implementation choices. They are kept so the GM can tell which files are meant (same convention as spec 031).
- The input listed five GM-undecided questions. Three are `[NEEDS CLARIFICATION]` markers. The other two (promotion target, GM-secrets source) are recorded under "Open Questions Carried to Clarification" and are not decided. FR-018 holds the conservative position the input already required (no invented secrets) until the GM rules.
- SC-001 depends on the proposal's scratch-script counts. Planning should re-derive them with the real linker rules before treating them as goldens.
- Clarify session 2026-10-06 (5 questions): withheld-form rulings (FR-003/003a), generic detection (FR-003b), three-part dossier with secrets and publish (FR-018–018b), authored file plus compose (FR-018/018b), `docs/npcs/{distilled,summary_native}` layout with a Constitution XIII migration (FR-022a–022d). The migration widens scope: existing `docs/npcs/` consumers get repointed and must refuse loose files.
