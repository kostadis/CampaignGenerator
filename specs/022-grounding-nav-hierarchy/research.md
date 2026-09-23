# Research: Grounding Navigation Hierarchy

**Feature**: `022-grounding-nav-hierarchy` | **Date**: 2026-09-23 | **Spec**: [spec.md](spec.md)

The spec left no `[NEEDS CLARIFICATION]` open (FR-012 was resolved as option B). The
decisions below are the design forks the plan had to settle. Each was checked against the
current code: `frontend/src/components/layout/AppSidebar.vue`, `frontend/src/router.ts`,
`frontend/src/views/GroundingDocs.vue`, `frontend/src/views/EnsembleWorkflow.vue`, and
`frontend/e2e/`.

## R1. Reorganize the sidebar only; leave every route address alone

**Decision**: The hierarchy exists in the sidebar only. `router.ts` is not changed: every
page keeps its current address (`/grounding/distill`, `/ensemble/setup`,
`/grounding/projections`, …).

**Rationale**: FR-007 requires every existing address to keep opening the same page. If
addresses don't move, that holds with no redirects to write, test, or keep forever. The
sidebar is the only place the user said the overlap is hidden; the addresses are not what
misleads anyone. It also makes FR-010 ("nothing any page runs or writes changes") hold
by construction, because no view, route or component tree is touched.

**Alternatives considered**:
- *Nest routes to mirror the hierarchy* (`/grounding/per-tool/distill`,
  `/grounding/ensemble/setup`, …) with redirects from every old address. Rejected: it adds
  about 16 permanent redirects for no user-visible gain, and keeps two spellings of every
  address alive. Principle XIII refuses exactly that for on-disk state ("no dual-location
  back-compat probe"), and the same logic applies to links.
- *Move Ensemble under `/grounding` and redirect `/ensemble/*`*. Rejected for the same
  reason, on a smaller scale.

## R2. Three levels, always expanded

**Decision**: The sidebar gets one extra level, and only inside the grounding section:

```
GROUNDING DOCUMENTS              ← top-level group title (existing style)
  Per-tool                       ← path header: label + one-line description
    World State                  ← page items (existing style, indented)
    …
  Dossier synthesis
    Ensemble
  State projection
    State Projection
    Threads
```

Path headers are always expanded. No collapse or accordion.

**Rationale**: Expanded headers cost **zero** extra clicks, so FR-006 ("within at most
one additional click") holds with room to spare. A collapsible accordion would add a
click and hide pages, which works against Principle VIII's "state is discoverable" and
against the whole point of the feature, which is to *show* the overlap. The section
grows by three header rows. At 1280×720 (the Playwright viewport) the sidebar already
scrolls independently, so the extra rows are acceptable.

**Alternatives considered**:
- *Collapsible path headers*: rejected as above (hides pages, adds a click).
- *Tabs inside one "Grounding Documents" page*: rejected. It adds a page that didn't
  exist and moves navigation out of the sidebar, which is a larger change than asked for.

## R3. Path headers are labels, not links

**Decision**: A path header is a heading with a description. It is not clickable and has
no page of its own.

**Rationale**: Every path already has its pages. A header page would be a new page
that no requirement asks for, and a clickable header next to its own children makes it
unclear what clicking does. Screen readers get a real heading element, so the hierarchy
is also available to assistive technology.

**Alternatives considered**: *Header links to the path's first page*: rejected. It
duplicates that page's own entry and quietly makes one child "the" page for the path.

## R4. Ensemble stays one sidebar entry

**Decision**: The dossier-synthesis branch holds a single entry, **Ensemble**, pointing at
`/ensemble/setup`, as today. The Setup → Extract → Bundle → Synthesize steps stay in
`EnsembleWorkflow.vue`'s own wizard.

**Rationale**: FR-006 is about the entries that existed before, and Ensemble was one
entry. The wizard already owns stage navigation and shows stage state read from disk.
Listing the four stages in the sidebar as well would give the same navigation two homes
that could drift apart.

**Alternatives considered**: *Four sidebar entries, one per stage*: rejected (duplicates
the wizard; not asked for).

## R5. Active marking by address prefix, per path

**Decision**: Each path declares the address prefixes it owns. A path header is marked
active when the current address falls under any of them. A page item keeps today's rule
(exact match, or the address starts with the item's path plus `/`).

**Rationale**: FR-008 requires the active page *and* its path to be marked. Doing this
by prefix also fixes an existing defect: today the only Ensemble entry is
`/ensemble/setup`, so on `/ensemble/extract`, `/ensemble/bundle` and
`/ensemble/synthesize` **nothing** in the sidebar is highlighted. With the dossier-synthesis
path owning `/ensemble/`, the path is marked on every stage, and the Ensemble item is
marked on every stage too (its match prefix is `/ensemble/`, not `/ensemble/setup`).

**Alternatives considered**: *Mark the path from the active item only*: rejected. It
would inherit the existing Ensemble gap.

## R6. The shared extraction is stated in the descriptions, not added as a node

**Decision**: FR-009 is met with the path descriptions alone. Dossier synthesis and
state projection each say they read the shared ensemble extraction; per-tool says it
extracts on its own. No page header changes, and no extraction node is added. The GM
chose option B over option C, which would have added one.

**Rationale**: The spec permits "branch description or page header". Descriptions keep
every change in the sidebar (R1), and option C was explicitly not chosen.

**Evidence the claim is true**: `docs/design/StateProjectionService_seed.md` defines the
shared *Extraction & State* service (`ensemble_batch` + `facts_to_state`) as the input to
both dossier synthesis and state projection, and says the per-tool path "keeps its own
extraction and its own config". `tests/test_projection_isolation.py:158` states the same
dependency: "State Projection depends on the Extraction & State service's OUTPUT".

## R7. Path order follows feature 006's numbering, not preference

**Decision**: Per-tool, then Dossier synthesis, then State projection.

**Rationale**: Any list has an order, and FR-011 forbids ranking. This order is feature
006's own numbering of the paths (path 1, 2, 3), so it carries a citable, non-evaluative
meaning. The plan records that the order implies no recommendation.

## R8. All copy is a draft for the GM

**Decision**: The path labels and one-line descriptions in
[data-model.md](data-model.md) are proposed wording. The GM approves or edits them before
implementation.

**Rationale**: The descriptions make factual claims about how the system works ("reads the
shared ensemble extraction"). The constitution's *Authority & the Human Checkpoint*
section treats Spec Kit output as a draft reviewed before it feeds implementation, and
this copy is the only user-facing decision this feature makes.

**Outcome**: approved by the GM as proposed, 2026-09-23.

## R9. Tests: one Playwright spec plus the type-checked build

**Decision**:
- New `frontend/e2e/sidebar-navigation.spec.ts` asserting: the grounding parent contains
  exactly the three paths in R7's order; each path contains the expected pages; every
  pre-existing sidebar entry is present and every pre-existing address resolves (the table
  in [data-model.md](data-model.md)); the old ENSEMBLE WORKFLOW top-level group is gone;
  path-level active marking on `/ensemble/extract` (R5's regression case) and on
  `/grounding/threads`.
- Lift the five startup API stubs from `e2e/fixtures/narrationWiki.ts`
  (`/api/config/`, `/api/config/models`, `/api/config/status`, `/api/editor/config`,
  `/api/grounding/config`) into a shared `e2e/fixtures/appShell.ts`, and have both specs
  use it. Page-specific APIs are stubbed with a catch-all so that the reachability test
  asserts navigation, not page behaviour.
- `npm run build` (`vue-tsc -b && vite build`) must pass.

**Rationale**: The feature is pure UI structure, so an end-to-end check of the rendered
sidebar is the direct test. The repo already runs Playwright at 1280×720 with API calls
mocked through `page.route`, so the pattern is established. No Python tests reference
the sidebar (checked: the `State Projection` hits in `tests/` are docstrings about the
service, not the navigation).

**Alternatives considered**: *Component unit tests*: rejected. The frontend has no unit
test runner, and adding Vitest for one feature is a new dependency the change doesn't
justify.
