# Specification Quality Checklist: Scene Extraction Token Limit from the UI

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-17
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

- Verified via `codebase-memory-mcp` before drafting: `server/session_editor_
  config_shared.py` defines `NarrateKnobs.tokens` (default 16000, persisted,
  UI-editable) but no equivalent `ExtractKnobs`; `server/routers/
  scene_editor.py::_build_narrate_cmd` forwards `cfg.narrate.tokens` as
  `--narrate-tokens`, while `_build_reextract_cmd` never forwards any
  `--max-tokens` value to `scene_extract` (which defaults to 8192 via its own
  argparse default); `frontend/.../KnobDrawer.vue`'s Stage ④ Narrate section
  has a "Token limit" input, Stage ② Extract has none.
- All items pass on first pass — the request is a well-scoped parity gap with
  an existing, working pattern (Narrate's token field) to mirror, so no
  [NEEDS CLARIFICATION] markers were needed.
