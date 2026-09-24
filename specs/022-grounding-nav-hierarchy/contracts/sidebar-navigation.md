# UI Contract: Sidebar Navigation

**Feature**: `022-grounding-nav-hierarchy` | **Consumer**: the GM, and `frontend/e2e/sidebar-navigation.spec.ts`

This is the contract the reorganized sidebar must meet. Each clause is phrased so a
Playwright assertion can check it against the rendered page. The structure and wording
are defined in [data-model.md](../data-model.md); this file states what must be *true*
of them.

## C1. Structure

1. The sidebar contains exactly one top-level group holding grounding-document paths:
   `GROUNDING DOCS`.
2. No top-level group titled `ENSEMBLE WORKFLOW` exists.
3. `GROUNDING DOCS` contains exactly three path headers, in this order:
   `Per-tool`, `Dossier synthesis`, `State projection`.
4. Each path header is exposed as a heading (accessible role `heading`) nested below the
   group title's heading level, so the hierarchy is available to assistive technology.
5. Each path header shows its one-line description as visible text directly beneath the
   label. It is not a tooltip.
6. Path headers are not interactive: clicking one does not navigate (research R3).
7. Page entries render under their own path header, in the order given in data-model.md.
8. All other top-level groups (`SESSION WORKFLOW`, `PREP`, `SETUP`, `INTEGRATIONS`) and
   the standalone Settings entry are unchanged in title, entries, order and addresses.

## C2. Reachability (FR-006, FR-007)

1. Every entry in data-model.md's inventory (19 entries) is present in the sidebar with
   the listed label.
2. Clicking each entry navigates to the listed address.
3. Every address in data-model.md's "Addresses that must keep resolving" table, loaded
   directly, ends on the page it opens today. This includes `/grounding/world-state` →
   `/grounding/distill` and `/ensemble` → `/ensemble/setup`.
4. No page requires more clicks to reach than before. With every header always expanded,
   every entry is one click away, as today.

## C3. Active marking (FR-008)

| Current address | Active item | Active path header |
|---|---|---|
| `/grounding/distill` | World State | Per-tool |
| `/grounding/world-state` (redirects) | World State | Per-tool |
| `/ensemble/setup` | Ensemble | Dossier synthesis |
| `/ensemble/extract` | Ensemble | Dossier synthesis |
| `/ensemble/synthesize` | Ensemble | Dossier synthesis |
| `/grounding/threads` | Threads | State projection |
| `/prep/query` | Query Summaries | *(none)* |

- At most one item and one path header are marked active at any time.
- The `/ensemble/extract` and `/ensemble/synthesize` rows are the regression cases for
  the existing defect where no entry was highlighted on those stages (research R5).

## C4. Descriptions state the shared extraction truthfully (FR-009)

1. The `Dossier synthesis` and `State projection` descriptions each state that the path
   reads the shared ensemble extraction.
2. The `Per-tool` description states that each tool does its own extraction, and does not
   mention the shared ensemble extraction.
3. No description ranks, recommends, or discourages a path (FR-011). Words such as
   "recommended", "preferred", "legacy", "deprecated", "old" and "new" do not appear.

## C5. Nothing else changes (FR-010)

1. No route in `frontend/src/router.ts` is added, removed or changed.
2. No view under `frontend/src/views/` is changed.
3. No request the app makes changes: the set of API calls made on startup and on each
   page is the same before and after.
4. The sidebar footer (backend, model, batch and effort selectors) is unchanged.
