# Research: Thread UI Consistency and Overflow Access

**Date**: 2026-08-28 · **Spec**: [spec.md](./spec.md) · **Feature**: `018-align-thread-ui`

The findings below are a draft codebase survey for human review. They remove
research and rendering effort, not the human architecture checkpoint.

## D1 — The mismatch comes from undefined local theme variables

**Decision**: Restyle the Threads view with the application tokens already
defined in `frontend/src/style.css`: `--bg-base`, `--bg-mantle`,
`--bg-surface0`, `--bg-surface1`, `--text`, `--text-sub`, `--text-muted`, and
the existing semantic accent colors.

**Rationale**: The global application theme is Catppuccin Mocha. Threads uses
different variable names (`--muted`, `--border`, `--chip`, and `--panel`) that
are not defined globally, so its light fallbacks (`#ddd`, `#eee`, `#fafafa`,
`#fff5f5`, and related colors) become the rendered style. Peer grounding views
use the defined global tokens directly for page backgrounds, text, borders,
forms, and states.

**Alternatives considered**:

- Define the four legacy variables globally: rejected because it preserves a
  second visual dialect and can change unrelated pages.
- Introduce a new theme/component library: rejected because the application
  already has an authoritative palette and the feature needs no dependency.

## D2 — The application shell requires each page to own scrolling

**Decision**: Make the root `.threads` element the page-local scroll container
for both axes, with a bounded flex size (`width: 100%`, `min-width: 0`,
`height: 100%`, `box-sizing: border-box`) and `overflow: auto`.

**Rationale**: `body`, `#app`, `.app-layout`, and `.app-main` all deliberately
use `overflow: hidden`. Established pages compensate by owning an internal
scroll container. Threads currently declares only `max-width: 60rem`, so no
ancestor can expose overflow and oversized descendants are clipped. A
page-local owner fixes Threads without changing the shell or non-Threads pages.

**Alternatives considered**:

- Change `.app-main` or the document body to `overflow: auto`: rejected because
  it changes every application page and risks nested/double scrollbars.
- Add overflow to individual cards, tables, forms, and lists: rejected because
  users would have to discover multiple horizontal scroll regions and content
  spanning regions could still be clipped.

## D3 — Native CSS overflow is the dynamic-content mechanism

**Decision**: Use `overflow: auto` on the Threads page and rely on normal
browser layout to recalculate `scrollWidth` after loads, expansions,
collapses, and resizes.

**Rationale**: CSS overflow is recomputed whenever layout changes. It provides
a horizontal control only when `scrollWidth > clientWidth`, preserves normal
vertical scrolling in the same container, and requires no application state.
This directly covers the dynamic cases in FR-008 through FR-011.

**Alternatives considered**:

- `overflow-x: scroll`: rejected because it shows an unnecessary horizontal
  control when content fits, violating FR-010.
- `ResizeObserver`, mutation observers, or JavaScript width calculations:
  rejected because they duplicate browser layout, add lifecycle failure modes,
  and create state for a purely presentational fact.
- Force all long content to wrap: rejected because some forms, tables, and
  evidence are legitimately wide and the specification explicitly requires
  horizontal access.

## D4 — Existing grounding pages are the component-level visual authority

**Decision**: Match the Threads page shell, header, spacing, forms, controls,
borders, messages, and type scale to `ProjectionSections.vue`, while consuming
the palette and global button rules in `style.css`.

**Rationale**: `ProjectionSections.vue` is a sibling route in the same
grounding workflow and already uses the application conventions: 20px/24px
page padding, compact 16px/12px header hierarchy, standard form controls,
surface borders, and semantic token colors. This is a closer authority than a
new design or a mechanically copied page from another workflow.

**Alternatives considered**:

- Preserve Threads' current rem-based light-card styling and change only its
  colors: rejected because FR-002 includes typography, spacing, panels,
  controls, borders, and interaction states.
- Redesign all grounding pages together: rejected as outside the feature and
  contrary to FR-013.

## D5 — Semantic distinctions stay meaningful inside the shared palette

**Decision**: Use the standard semantic roles consistently: errors/rejections
use `--red`, warnings/deferred or dormant states use `--peach`, successful or
healthy states use `--green`, matched/informational states use `--blue`, and
neutral/pending states use normal surface and text tokens. Status text remains
present; color is supplemental.

**Rationale**: FR-003 requires both visual consistency and distinguishable
thread-specific states. Existing application views already combine color with
labels/badges, so the change can preserve meaning without keeping light-theme
colors. Text labels ensure meaning is not color-only.

**Alternatives considered**:

- Make every badge neutral: rejected because semantic states become harder to
  distinguish.
- Preserve the current hard-coded light colors for meaning: rejected because
  they conflict with the application palette and often have poor dark-theme
  contrast.

## D6 — The implementation boundary is one view

**Decision**: Change `Threads.vue` only in application code. Treat `App.vue`,
`style.css`, and peer views as read-only references.

**Rationale**: The defect is local: Threads neither owns scrolling nor uses
the existing tokens. A local repair satisfies FR-013 and avoids regressions in
the many views that intentionally use their own overflow models. Markup may be
adjusted to expose the already-existing `loading` state and attach semantic
status/style classes, but no behavior or request path changes.

**Alternatives considered**:

- Add shared layout/card components now: rejected because this one-page repair
  does not justify a cross-application refactor.
- Change server response shapes to carry presentation metadata: rejected
  because semantic meaning is already present in existing status strings.

## D7 — Automated tests guard structure; browser review guards rendering

**Decision**: Add a focused `pytest` source-contract file for the durable
invariants, keep the existing Threads precision guards green, run the frontend
production build, and require manual browser acceptance for the actual
scrollbar and visual comparison.

**Rationale**: This repository has no Vitest, Vue Test Utils, Playwright, or
other browser/component harness in `frontend/package.json`. Existing Threads
UI requirements are guarded by Python tests that inspect the Vue source. A new
source-contract test can cheaply prevent removal of the page scroll owner,
reintroduction of undefined legacy variables/light fallbacks, and omission of
an explicit loading presentation. It cannot honestly prove computed layout or
visual parity; those remain human browser checks.

**Alternatives considered**:

- Introduce a browser-test stack for this fix: rejected as disproportionate
  new infrastructure and dependency scope.
- Claim source inspection proves the scrollbar works: rejected as an
  optimistic lie; layout and visual results need a rendered-browser check.
- Manual testing only: rejected because the key structural regression is
  deterministic and inexpensive to guard automatically.

## D8 — No data, API, CLI, or migration contract changes

**Decision**: Keep all existing interfaces and persistent models unchanged;
publish only a UI behavior contract for this feature.

**Rationale**: The specification explicitly preserves Threads workflows,
actions, data, and outcomes. The overflow condition is derived by the browser,
and the visual-role mapping is derived from status strings already rendered by
the page. No new field, route, store, option, or disk shape is needed.

**Alternatives considered**:

- Persist page width or scroll position: rejected because layout is ephemeral
  and browser-local, and persistent UI-only state would violate the project's
  disk/CLI interchange model.
- Add API fields for color/status classes: rejected because that moves
  presentation concerns into the server contract.

## Research resolution

All technical unknowns are resolved. There are **no `NEEDS CLARIFICATION`
markers** and no decision in this draft is authorized to feed task generation
until the human reviews the architecture.
