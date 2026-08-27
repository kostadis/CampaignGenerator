# Specification Quality Checklist: Thread Registry Surface

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-25
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

Three scope questions were put to the GM rather than guessed, per the
constitution's "Authority & the Human Checkpoint" clause (a spec that decides
scope autonomously is the precision-decision-without-a-checkpoint Principle II
forbids). All three were answered on 2026-08-25 and are recorded in the spec:

1. **Which of #337's three fixes** — option 1, the thread registry surface.
   Options 2 and 3 explicitly not adopted (Assumptions).
2. **How ratification works** — through the interface, not as copyable
   commands, with the three-way accept / reject / discuss ruling the GM
   specified (US2, FR-007).
3. **How far multi-select reaches** — it does not. One candidate, one ruling,
   one act (FR-007, SC-004). "Discuss" behaves like a reject for the registry
   and additionally exports an adjudication bundle for a Claude conversation
   (FR-011).

Two items are worth flagging for the plan rather than the spec:

- **FR-018/FR-019 look like implementation constraints and are.** "Every write
  goes through the same engine the command line uses" is Constitution VI (CLI
  is the engine, UI is a face) stated as a requirement because the GM's
  workflow depends on it observably — SC-005 and SC-009 are the user-visible
  tests of it. Kept deliberately.
- **An engine gap exists that the spec names but does not design.** Nothing
  today records a candidate's ruling or exports an adjudication bundle; the
  harvest only *preserves* rulings it finds already written. `/speckit-plan`
  must account for new command-line capability, not just a new page.

This feature also reverses a scope call made in `specs/006-state-projection-service`
(thread triage deliberately excluded from the interface). The reversal is the
GM's, is recorded in Assumptions, and preserves the principle behind the
original exclusion rather than the exclusion itself. Expect the plan to update
the state-projection router's own docstring so the two do not contradict.

All items pass.

---

**Amended 2026-08-25 during `/speckit-plan` Phase 0.** A measurement (not an
assumption) changed the spec after it was validated: harvesting the live
62-chapter Out of the Abyss corpus yields **986 candidates, 16 of which span
more than one chapter**; toee's 31 chapters yield 415 and 2 (research D15).
The spec's primary flow — one ruling per candidate, no bulk control — is
correct and unchanged, but SC-003 had assumed a queue of ~20. Added:
FR-027–FR-029 (order by plausibility; a filtered default view is allowed only
if the hidden count is on screen and the full set is one click away; filtering
is presentation, never a decision), SC-010, two edge cases, and one assumption.
SC-003 was corrected to name the multi-chapter head as the target rather than
the whole queue.

These additions were made without a fresh GM ruling because they constrain the
interface *away* from deciding anything — the alternative reading (filter in
the engine by default) is the one that would have made a scope decision on the
GM's behalf, and it was rejected on those grounds. If the GM prefers the
engine-side default, FR-028 and plan Complexity Tracking row 1 are where to
change it.

**Amended again 2026-08-25, on a GM ruling.** Reviewing the D15 amendment, the
GM endorsed the filtered default and rejected the escape hatch I had specified
with it: a "Show all" button that lists 970 single-chapter candidates satisfies
"reachable in one action" while being useless. FR-028 was rewritten to forbid
that control, FR-029/FR-030 now require search (title, all title variants, and
evidence text) plus a chapter filter covering the full set *including
already-ruled candidates*, old FR-029 renumbered to FR-031, and SC-011 added.
Search runs in the browser — the payload was measured at 484 KB for the
986-candidate corpus, so no server-side query route is needed and none is
specified (research D16).

**Amended a third time 2026-08-25, after `/speckit-analyze`.** The analysis
found 21 issues, 1 critical and 6 high; all six high-severity findings were
verified against the code before acting. Three were defects introduced by the
earlier amendments:

- The banded/filtered default view's own arithmetic was wrong — span≥2 *implies*
  ≥2 evidence rows, so the "OR" filter was 70 candidates, not the 16 stated as a
  literal header string in four artifacts. **GM ruled**: two named bands with
  counts computed from the loaded set (FR-027, FR-028, FR-028a; research D17a).
- `propose()`'s short-circuit runs before its `matches`/`logged` filter and
  counts `ratified` as prior, so the accept sequence would have frozen every
  ratified thread at the chapter it was ratified on. **GM ruled**: narrow the
  short-circuit to `rejected`/`deferred` (FR-009a, FR-013; research D17b).
- FR-031 — the renumbered old FR-029 — had **zero** task coverage. Now T031/T031a.

Also closed: three of the four "absence" requirements had no enforcing task
despite tasks.md claiming otherwise (now T040a, T040b, T045a, T031a); two
binding guards (`test_projection_isolation.py`, `test_thread_registry.py`) were
missing from the plan and the baseline; the `emerging` section's dependency on
`thread_proposals.yaml` was undocumented; and `/threads/ratify` had no pinned
HTTP status for a partial apply.

**All three parked questions are now ruled** (2026-08-25), rather than silently
resolved by whichever branch got written first:

- **T000a → the atomic `ratify` verb** (D18). One call, no partial-apply state;
  `/threads/ratify` loses its 207 branch and the page loses a second
  error-display path.
- **T000b → a dedicated run control, not a flag on the shared `RunPanel`**
  (D19). Two behaviours, two buttons; refactor if duplication becomes real. The
  same gate on the State Projection page was filed as #341 (T065a) and left
  unfixed — **reopened the next day; see the amendment below.**
- **T000c → the corpus preview lists files only** (D20). No chapter numbers, so
  no second seam and no verb built to feed one column; the chapterless warning
  moves onto the candidate card, at the point of decision.

**Fourth amendment, 2026-08-26 — #341 pulled into scope (GM ruling; research
D21, tasks Phase 6b, T057a–T057k):**

The deferral in D19 was wrong on scope, not on design. `RunPanel`'s gate keys on
`ANTHROPIC_API_KEY` alone, so it refuses deterministic section builds and every
run on `dgx`/`openrouter`/`claude-code`. US4 signposts the GM to a build the
interface will not start on a keyless machine — so the defect gates **SC-001**,
and shipping without it relocates #337's dead-end rather than removing it.

Spec additions: **FR-032** (gate on the resolved backend's credential, not one
provider's key), **FR-033** (the refusal names the backend and the credential),
**FR-034** (the requirement declared once, beside the backend list), **SC-012**,
and a third US4 acceptance scenario. Contract additions: `GET
/api/config/status` returns a `credentials` map, replacing `api_key_present`.

**D19 is not reversed.** It ruled against an opt-out *prop* — a second mode on
the shared button. Phase 6b changes what the gate *asks*, adds no mode, and
leaves the Threads page's own control exactly as ruled.

**Fifth amendment, 2026-08-26 — the fourth amendment's remedy was replaced.**
The GM ruled on the wider design question (#342): delete the credential
predicate rather than correct it. Shipped as PR #343 off `main`. FR-032–FR-034
are restated (no gate, refusal at the call, no global probe anywhere), SC-012
stands, Phase 6b is cancelled down to a single verification step, and research
D21's diagnosis stands while its four proposed decisions do not. `BACKEND_CREDENTIAL`
was never built.

Ready for `/speckit-implement`.

**Sixth amendment, 2026-08-26 — coverage sweep and post-design gate re-run.**
No requirement changed. A `/speckit-tasks` re-run re-derived the FR/SC
inventory from `spec.md` instead of scanning task text for IDs, and found
three requirements that were named only inside a task's *description* and so
were invisible to every earlier sweep: **FR-006** (a harvest writes no
registry), **FR-018/019** (every write goes through the engine), and
**FR-028a** (counts computed, never literal). Each now has an enforcing task
(T019a, T041a, T031b) and `tasks.md` carries a full requirement-coverage table
so the next sweep does not have to rediscover them.

Two factual errors were corrected in the same pass, both of the same kind —
a claim stated more confidently than the evidence supported:

- `plan.md`'s Phase E still read *"✅ Landed elsewhere"* for PR #343, which is
  **open**. The `tasks.md` copy had been corrected the day before; this one was
  missed. Both now carry the same conditional gate.
- `research.md`'s D17a band table read *"1 chapter, ≥2 mentions"*, which
  contradicts D20: a candidate with `chapters: []` has **zero** chapters, so
  `== 1` drops it into the excluded tail — the one place the GM cannot see the
  chapterless warning D20 put on the card. `contracts/ui.md` and `tasks.md`
  T029 both already said `< 2`; research was the stale copy. That table is now
  declared the single authority for the band rules.

**Still open, and deliberately not closed here:** SC-003's timed budget has no
verification task, and T045a's component-harness question is unruled. Both are
GM calls; neither was quietly assigned to a nearby task to make the coverage
table look complete.
