# Specification Quality Checklist: Roster-Named Sheets & Level Archival

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-13
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain — all three resolved by GM ruling, 2026-08-13
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

Three decisions were the GM's, not defaults, and each carries a consequence for planning:

1. **The roster becomes authoritative for the player name (FR-008).** This reverses
   the ruling in `docs/design/PartyRosterCanonicalFormat.md` ("the D&D Beyond sheet
   is canonical, `party.yaml` just points at it") for that one field. The design
   document must be amended, not left contradicting the shipped behaviour. The
   reason is stronger than drift: the D&D Beyond export stamps the *downloader's*
   name into the player field, so the value is wrong for every character in the
   party on every download. That is why FR-009 drops the downloaded value rather
   than keeping it as a fallback, and why FR-010a requires both the machine- and
   human-readable player fields to be replaced — replacing one leaves the GM's name
   legible in the document while tooling reports someone else.
2. **Attribution keys on the character name read out of the sheet (FR-002), and the
   match is exact — no fuzzy fallback (FR-002a).** A model-extracted value selects
   which file gets moved, so the risk is bounded by a closed candidate set,
   refuse-on-anything-but-one-exact-match, and per-file reporting (FR-002b) — never
   by a threshold. The live Phandalin disagreement ("Valphine Sotorra" on the sheet,
   "Valphine" in the roster) is therefore a **loud failure the GM resolves by hand**,
   which FR-003a requires the message to say. Planning should note that this feature
   ships broken-until-fixed for Phandalin by design: the first run refuses, the GM
   edits, and it then succeeds.
3. **The archive layout is `old/level/<N>/` (FR-012)**, matching the GM's existing
   hand-built archive rather than the literal `old/<level>` of the request. No
   migration of existing archives is needed.

Multiclass and missing-level handling were resolved as a refusal (FR-013) rather
than a fourth clarification, per the project's refuse-rather-than-guess convention.
**Amended 2026-08-22:** a complete multiclass phrase is now totalled, not refused —
the character level *is* the sum, so it was never a guess. Missing levels, whether
the whole phrase or one class within it, still refuse.

The UI requirements (FR-019–FR-025) came in as a follow-up and are worth flagging to
planning: the existing D&D Sheet page already sends an output location, which under
FR-017 would disable this feature on every UI run, and the roster's savers hand-build
their output, so the new player field must be named on the write path or a UI save
persists nothing.
