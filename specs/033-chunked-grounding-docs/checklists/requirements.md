# Specification Quality Checklist: Chunked, Code-Checked Grounding Documents

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-07
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

- **Resolved (GM ruling, 2026-10-07):** an NPC who matters but has no publishable dossier makes the build **refuse by default**, naming each NPC and its dossier state; an explicit per-run option writes a **code-built fallback line** (no model) marked "no published dossier — from checked notes". Recorded in User Story 3 scenarios 3–4 and FR-018a/FR-018b.
- **Named systems are deliberate, not leakage.** The spec names product surfaces and data that already exist in this repo and are the feature's inputs: `players.yaml`, the entity registry, published dossiers (spec 032), the summary-native page, `gm-session-prep`. Model names (Qwen3-Next, Sonnet 5.5) and "Sparks" appear only as measured evidence in "Why this priority" and as defaults in Assumptions; no requirement depends on a specific model or framework (FR-022 makes both backends choices).
- **Success criteria reference the Out of the Abyss corpus** because the experiment measured it. They are verifiable without knowing the implementation.
- **Constitution alignment, to be confirmed in plan.md's Constitution Check:**
  - II (human checkpoint): the code check between extraction and prose, and code ownership of precision sections, follow spec 032's chunked-drafting precedent.
  - VII (extract once, synthesize deliberately): one cached extraction feeding both documents.
  - XI (every CLI capability has a face): FR-030 puts the feature on the web UI page.
  - XII (one spelling per option): FR-022 reuses the existing `--backend` / `--model` options.
