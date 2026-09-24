# Data Model: Grounding Navigation Hierarchy

**Feature**: `022-grounding-nav-hierarchy` | **Date**: 2026-09-23 | **Spec**: [spec.md](spec.md)

This feature has no persisted data. Nothing is read from or written to disk, and no API
changes (research R1). The "data" is the navigation structure the sidebar renders. It is
static and lives in the component. It is modelled here so the contract, the tests and the
review of the wording all point at one definition.

## Entities

### NavGroup *(existing, unchanged shape)*

A top-level sidebar section.

| Field | Type | Notes |
|---|---|---|
| `title` | string | Upper-case section title, e.g. `SESSION WORKFLOW` |
| `items` | NavItem[] | Present on every group except the grounding group |
| `paths` | RenderingPath[] | **New, optional.** Present only on the grounding group. A group has `items` or `paths`, never both |

### RenderingPath *(new)*

One of feature 006's three independent routes from session record to grounding
documents.

| Field | Type | Notes |
|---|---|---|
| `id` | `'per-tool' \| 'dossier-synthesis' \| 'state-projection'` | Stable key; feature 006's paths 1, 2, 3 |
| `label` | string | Path header text |
| `description` | string | One line: how this path differs from its siblings (FR-002). Must state whether it uses the shared ensemble extraction (FR-009) |
| `usesSharedExtraction` | boolean | `false` for per-tool; `true` for the other two. Drives no behaviour; it records the claim the description makes, so a test can check the two agree |
| `matchPrefixes` | string[] | Address prefixes this path owns, for path-level active marking (FR-008, research R5) |
| `items` | NavItem[] | The path's pages, in display order |

**Validation rules**
- Exactly three paths, in the order `per-tool`, `dossier-synthesis`, `state-projection`
  (research R7). The order is feature 006's numbering, not a ranking (FR-011).
- Every item's `path` falls under one of its own path's `matchPrefixes`.
- No address falls under two paths' `matchPrefixes`.
- Each `description` mentions the shared ensemble extraction if and only if
  `usesSharedExtraction` is `true`.

### NavItem *(existing, one optional field added)*

| Field | Type | Notes |
|---|---|---|
| `label` | string | Entry text |
| `path` | string | Address navigated to on click. **Unchanged for every existing entry** (research R1) |
| `matchPrefix` | string? | **New, optional.** When set, the item is active for any address under this prefix, instead of only its own `path`. Used by Ensemble (`/ensemble`) so all four wizard stages mark it (research R5) |

## Active-state rules (FR-008)

- An **item** is active when the current address equals its `path`, or starts with
  `path + '/'`, or (when `matchPrefix` is set) equals `matchPrefix` or starts with
  `matchPrefix + '/'`.
- A **path header** is active when the current address equals one of its
  `matchPrefixes` or starts with that prefix plus `/`. This is the same segment boundary
  items use, so `/grounding/party` does not match `/grounding/party-x`.
- At most one item and at most one path header are active at a time.

## The tree (wording approved by the GM 2026-09-23, research R8)

```
GROUNDING DOCS
│
├── Per-tool
│     "One tool per document, each with its own extraction."
│     usesSharedExtraction: false
│     matchPrefixes: /grounding/campaign-state, /grounding/distill,
│                    /grounding/party, /grounding/planning
│     (/grounding/world-state is not listed: the router redirects it to
│      /grounding/distill before the sidebar ever sees the address)
│     ├── Campaign State      → /grounding/campaign-state
│     ├── World State         → /grounding/distill
│     ├── Party Document      → /grounding/party
│     └── Planning Document   → /grounding/planning
│
├── Dossier synthesis
│     "Facts → per-entity dossiers → grounding docs. Reads the shared ensemble extraction."
│     usesSharedExtraction: true
│     matchPrefixes: /ensemble
│     └── Ensemble            → /ensemble/setup   (matchPrefix /ensemble)
│
└── State projection
      "Rebuilds only the sections that went stale. Reads the shared ensemble extraction."
      usesSharedExtraction: true
      matchPrefixes: /grounding/projections, /grounding/threads
      ├── State Projection    → /grounding/projections
      └── Threads             → /grounding/threads
```

**Wording changes, approved by the GM 2026-09-23:**
- Dossier synthesis originally read "… → world state". `/speckit-analyze` (finding I1)
  showed the path produces all four grounding documents (`GROUNDING_DOCS`,
  `server/routers/ensemble.py:68-73`), so the GM re-ruled it to "… → grounding docs".
- `Ensemble Grounding Docs` → `Ensemble`. Under a *Dossier synthesis* header inside
  *Grounding Docs*, the old suffix repeats both headers. The address is unchanged.
- The three path labels and descriptions above are new text.
- The group title stays `GROUNDING DOCS`.

**Order inside Per-tool**: Campaign State first, as today. `/grounding` already redirects
to `/grounding/campaign-state`, so the first entry in the branch stays the section's
landing page.

## Inventory: every entry before and after (FR-006, SC-002)

| # | Entry (before) | Group before | Group / path after | Address | Extra clicks |
|---|---|---|---|---|---|
| 1 | ① Session Config | SESSION WORKFLOW | unchanged | `/workflow/config` | 0 |
| 2 | ② Session Doc Editor | SESSION WORKFLOW | unchanged | `/workflow/editor` | 0 |
| 3 | ③ Narration Wiki | SESSION WORKFLOW | unchanged | `/workflow/wiki` | 0 |
| 4 | Campaign State | GROUNDING DOCS | GROUNDING DOCS › Per-tool | `/grounding/campaign-state` | 0 |
| 5 | World State | GROUNDING DOCS | GROUNDING DOCS › Per-tool | `/grounding/distill` | 0 |
| 6 | Party Document | GROUNDING DOCS | GROUNDING DOCS › Per-tool | `/grounding/party` | 0 |
| 7 | Planning Document | GROUNDING DOCS | GROUNDING DOCS › Per-tool | `/grounding/planning` | 0 |
| 8 | State Projection | GROUNDING DOCS | GROUNDING DOCS › State projection | `/grounding/projections` | 0 |
| 9 | Threads | GROUNDING DOCS | GROUNDING DOCS › State projection | `/grounding/threads` | 0 |
| 10 | Ensemble Grounding Docs | ENSEMBLE WORKFLOW | GROUNDING DOCS › Dossier synthesis (as *Ensemble*) | `/ensemble/setup` | 0 |
| 11 | Session Prep | PREP | unchanged | `/prep/session-prep` | 0 |
| 12 | NPC Table | PREP | unchanged | `/prep/npc-table` | 0 |
| 13 | Query Summaries | PREP | unchanged | `/prep/query` | 0 |
| 14 | Connection Graph | PREP | unchanged | `/prep/connections` | 0 |
| 15 | Players | SETUP | unchanged | `/setup/players` | 0 |
| 16 | D&D Sheet | SETUP | unchanged | `/setup/dnd-sheet` | 0 |
| 17 | Make Tracking | SETUP | unchanged | `/setup/make-tracking` | 0 |
| 18 | Scabard Sync | INTEGRATIONS | unchanged | `/integrations/scabard` | 0 |
| 19 | Settings | (standalone) | unchanged | `/settings` | 0 |

The ENSEMBLE WORKFLOW top-level group is removed; it held only entry 10 (FR-003, SC-004).

## Addresses that must keep resolving (FR-007, SC-003)

No route changes (research R1), so each of these opens the same page it opens today:

| Address | Opens |
|---|---|
| `/` | redirect → `/workflow/config` |
| `/workflow` | redirect → `/workflow/config` |
| `/workflow/editor/review` | Review & Assemble |
| `/grounding` | redirect → `/grounding/campaign-state` |
| `/grounding/world-state` | redirect → `/grounding/distill` |
| `/ensemble` | redirect → `/ensemble/setup` |
| `/ensemble/extract`, `/ensemble/bundle`, `/ensemble/synthesize` | the Ensemble wizard stages |
| `/prep` | redirect → `/prep/session-prep` |
| `/setup` | redirect → `/setup/players` |
| every address in the inventory above | its page |
