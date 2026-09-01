# Persistent Narration Wiki: Analysis Findings

**Feature**: `358-narration-wiki`

**Feature directory**: `specs/020-narration-wiki/`

**Analysis date**: 2026-08-31

**Status**: Resolve the critical and high-severity findings before `$speckit-implement`.

## Purpose

This document preserves the read-only `$speckit-analyze` findings so work can resume in a later session. It compares [spec.md](spec.md), [plan.md](plan.md), [tasks.md](tasks.md), and the project [constitution](../../.specify/memory/constitution.md).

No remediation edits have been applied to the specification, plan, or task list.

## Findings

| ID | Category | Severity | Locations | Finding | Recommended remediation |
|---|---|---|---|---|---|
| C1 | Constitution | **CRITICAL** | `constitution.md:57-59`, `plan.md:42`, `tasks.md:143` | Constitution Principle VI requires FastAPI subprocess execution through `server/subprocess_runner.py` and its established streaming seam. T048 instead assigns threadpool subprocess delegation to `server/routers/narration_wiki.py`, although the plan marks the principle PASS. | Put process execution in the constitutional subprocess seam and leave the router responsible only for validated argv and response adaptation. Reconcile the JSON endpoint contract with the constitution's SSE requirement. |
| I1 | Ordering | **HIGH** | `plan.md:155-168`, `tasks.md:51-98` | The planned state flow requires `measure(before)` before pattern drafting and Gate 1, but the task list declares US1/Gate 1 independently complete—and the MVP—before US3 implements measurement. | Either move before-measurement into Foundation/US1 or change the state machine so Gate 1 legitimately follows collection without measurement. |
| A1 | Ambiguity | **HIGH** | `spec.md:155`, `tasks.md:111-113` | “Materially new evidence” has no deterministic definition. An artifact ID alone does not let the engine judge semantic materiality safely. | Define a mechanical criterion, such as evidence absent from the prior impact record, or require an explicit GM override and rationale whenever materiality requires judgment. |
| U1 | Underspecification | **HIGH** | `spec.md:100`, `spec.md:180`, `tasks.md:165-171` | FR-040 requires detection and adjudication of conflicting seed sources, including the Phandalin em-dash discrepancy, but no conflict artifact, fields, or focused test is defined. | Specify how conflicting sources and the GM ruling are persisted, then add a fixture and acceptance test for the named discrepancy. |
| G1 | Coverage | **HIGH** | `spec.md:224`, `plan.md:25`, `tasks.md:186` | SC-010 requires a measured under-15-minute usability check. T066 runs the exercise but does not require timing or recording the result. | Add a timed acceptance step with start/end criteria, model-response-time exclusion, and a persisted result. |
| G2 | Coverage | **HIGH** | `spec.md:181`, `plan.md:139`, `tasks.md:37-38`, `tasks.md:166` | FR-041 covers narration skills and review checklists, including companion-owned surfaces. Tasks test CampaignGenerator's resolver but do not verify that deployed companion skills removed hand-copied narrator rules. | Add a read-only companion capability/version contract that can be verified locally, or explicitly gate feature completion on a tracked companion-repository change. |
| A2 | Ambiguity | **MEDIUM** | `spec.md:228`, `plan.md:21`, `tasks.md:139`, `tasks.md:185` | SC-014 says “all supported viewport sizes” and each panel's “minimum supported dimensions,” but only 640×480 and a 200%-zoom-equivalent viewport are defined. Panel minimums remain unspecified. | Define the supported viewport/panel test matrix or rewrite SC-014 to name the exact automated cases. |
| I2 | Terminology | **MEDIUM** | `spec.md:159`, `plan.md:153-167`, `tasks.md:114-122` | FR-025 says “apply an approved patch” and “revert a rejected patch,” while the planned flow applies a candidate before Gate 2 and later retains or restores it. | Use consistent terms: “apply for comparison,” “accept/retain,” and “reject/restore.” |
| I3 | Parallelism | **MEDIUM** | `tasks.md:166-167`, `tasks.md:221`, `tasks.md:261-276` | T058 and T059 are both marked parallel but edit `tests/test_narration_wiki_isolation.py`. The US4 parallel example also pairs failing route test T044 with implementation T048, conflicting with the tests-first rule. | Split renderer isolation into a separate test file or serialize T058/T059. Require T044 to fail before T048 begins. |

## Decisions Needed Before Remediation

1. **Gate 1 sequencing**: Is a persisted before-measurement mandatory before the companion maintainer may write pattern drafts?
2. **HTTP execution contract**: Will narration-wiki endpoints use the existing SSE subprocess seam, or should a constitution-compliant JSON runner be added inside `server/subprocess_runner.py`?
3. **New evidence**: What deterministic condition distinguishes materially new evidence from a different but irrelevant artifact ID?
4. **Seed conflicts**: What on-disk artifact records competing source rules and the GM's conflict ruling?
5. **Companion verification**: What locally inspectable metadata proves the deployed maintainer/proposer skills use campaign-resolved guidance rather than copied tables?
6. **Responsive support matrix**: Which viewport and resizable-panel dimensions are officially supported and tested?

## Coverage Snapshot

- Total requirements: 61 — 47 functional requirements and 14 buildable success criteria
- Total tasks: 66
- Requirements with at least one associated task: 61/61 (100%)
- Requirements considered fully specified and verified by the current task wording: 56/61 (91.8%)
- Partial coverage: FR-024, FR-040, FR-041, SC-010, SC-014
- Unmapped implementation tasks: none
- Duplicated requirements found: none

## Constitution Status

One critical alignment issue remains: C1, the FastAPI subprocess seam. The analysis found no conflicts with the explicit-selection, human-gate, disk-truth, renderer-isolation, CLI/UI parity, or additive-state principles.

The constitution remains version 1.3.0. GitHub issue #360 continues to track the requested future UI-style and scrolling constitution amendment; that amendment is not part of this feature's current remediation.

## Suggested Restart Sequence

From the `358-narration-wiki` worktree:

1. Review the six decisions above.
2. Run `$speckit-clarify` to encode the semantic decisions for new evidence, seed conflicts, companion verification, and responsive dimensions.
3. Run `$speckit-plan` to correct the subprocess seam and Gate 1/measurement ordering.
4. Run `$speckit-tasks` to regenerate the dependency-ordered checklist.
5. Run `$speckit-analyze` again.
6. Proceed to `$speckit-implement` only when no critical issues remain.

## Worktree

Continue work in:

```text
/home/kroussos/src/CampaignGenerator-worktrees/358-narration-wiki
```

Do not implement this feature in `/home/kroussos/src/CampaignGenerator`.
