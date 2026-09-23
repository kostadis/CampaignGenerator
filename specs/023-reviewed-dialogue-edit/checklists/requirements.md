# Specification Quality Checklist: Dialogue Edit Skill

**Purpose**: Validate the revised skill specification before planning its implementation.
**Created**: 2026-09-06
**Feature**: [spec.md](../spec.md)
**Review ownership**: Checked items indicate requirements quality, not a built skill, GM approval of proposed narration edits, or successful behavioral trials.

## Content Quality

- [x] No implementation details (languages, frameworks, APIs).
- [x] Focused on user value and needs.
- [x] Written for non-technical stakeholders.
- [x] All mandatory sections completed.

## Requirement Completeness

- [x] No unresolved clarification markers remain.
- [x] Requirements are testable and unambiguous.
- [x] Success criteria are measurable.
- [x] Success criteria are technology-agnostic.
- [x] Acceptance scenarios are defined.
- [x] Edge cases are identified.
- [x] Scope is clearly bounded.
- [x] Dependencies and assumptions identified.

## Feature Readiness

- [x] All functional requirements have acceptance coverage.
- [x] User scenarios cover primary flows.
- [x] Requirements support the measurable success criteria.
- [x] No implementation design is substituted for user requirements.

## Acceptance Traceability

| Requirements | Coverage |
| --- | --- |
| FR-001–003 | Story 1; SC-001 and SC-007; inventory and full-reading cases. |
| FR-004–006 | Story 2; SC-002–003; protected regression conditions. |
| FR-007–008 | Stories 1–2; SC-001, SC-003, and SC-006; exact proposals and no mandatory external generation. |
| FR-009–010 | Stories 2–3; SC-003 and SC-005; per-scene chat/page rulings and invalid exports. |
| FR-011–012 | Story 3; SC-004; stale, ambiguous, conflicting, and protected-path refusals. |
| FR-013–016 | Stories 3–4; SC-005–006; new orphan proposals, seam findings, resumability, and scoped rulings. |
| FR-017–018 | Story 4; SC-006–007; separate upstream repair, authorized calls, and honest provenance. |
| FR-019–020 | SC-002 and SC-007; all three archived cases, shared review contract, and skill delivery scope. |

## Constitution Review

Specification-stage assessment against version 1.3.0. Any implementation plan must preserve the recorded user delivery ruling and the source/approval boundaries.

| Principle | Assessment |
| --- | --- |
| I. Disk is Truth, the Model is a Draft | FR-008 and FR-011–014 preserve original text, exact proposals, derived revisions, and durable human decisions. |
| II. The Human Checkpoint is Non-Negotiable | FR-009–011 require per-scene rulings before exact application; revised proposals require new review. No final precision decision is delegated to the model. |
| III. Retrieval and Render are Separated | FR-002–003 select explicit reviewed evidence before editing; no automatic scope expansion or new retrieval pipeline. |
| IV. Verbatim is Sacred | The written justification confines paraphrase to reviewed derived narration. FR-012 preserves every source layer and original narration. |
| V. One Seam per Boundary | No model adapter or application integration is introduced. Any separately authorized existing runner retains its own boundary and failure reporting under FR-017–018. |
| VI. CLI is the Engine, UI is a Face | The user explicitly chose an external skill. Deterministic helpers support exact transformations; no new CG engine or UI logic is required. |
| VII. Extract Once, Synthesize Deliberately | Existing reviewed extractions are evidence. FR-007 and FR-017 avoid mandatory full-scene regeneration and automatic pass chaining. |
| VIII. State is Discoverable | FR-014–016 record selected scope, decisions, outputs, not-run states, and carry-forward on disk. |
| IX. The UI Mechanizes; Claude Converses | Chat is the judgment surface; the existing optional page collects explicit decisions and does not write narration. |
| X. Selection is Explicit; There is No Silent \"All\" | FR-002 requires explicit scope; Story 1 refuses implicit expansion of empty or ambiguous selections. |
| XI. Parity is Bidirectional; Every CLI Capability Has a Face | GM ruling dated 2026-09-06 selects skill delivery instead of a CG feature. The specification records that no CG CLI/UI parity work is required. A later application feature is separate scope. |
| XII. One Spelling per Option; No Configuration Drift Across CLIs | No new CG flags/defaults are introduced. Any authorized use of existing tools preserves their vocabulary. |
| XIII. Breaking State Changes Migrate Out of Band and Ship a Migration Document | No CG schema migration or existing workspace rewrite is included. New review artifacts and derived revisions preserve inputs. |

## Notes

- All 16 requirements-quality items pass after revision for skill delivery.
- The proposed invocation and skills-collection location describe the requested deliverable, not an application architecture or new command-line API.
- The workflow adopts full reading and per-scene rulings from no-mech, and explicit returned decisions and durable manifests from staged-consistency. It does not invoke either skill on a campaign during specification.
- Deterministic helpers make no model calls; the active Codex reading pass is explicitly acknowledged as model work. Active-conversation metadata is not invented or required to resemble a separate runner's prompt snapshots.
- #369 is related work, not a prerequisite. The existing shared review contract is the concrete batch-review dependency.
- The #487-to-#387 assumption from the initial specification is retained, not relabeled as user confirmation.
- At specification review, structural checks and source review validated this document only. The skill has since been created and locally installed, with 15 offline helper tests passing. GM editorial acceptance trials remain pending; the historical 17 archive tests have not been rerun.
- The skill specification remains in its existing feature directory. Its implementation lives in the Codex skills collection. The later shared narration-v1 rollout is a separate user-authorized generation change documented in the specification.
