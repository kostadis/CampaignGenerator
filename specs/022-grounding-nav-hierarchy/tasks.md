---

description: "Task list for 022-grounding-nav-hierarchy"
---

# Tasks: Grounding Navigation Hierarchy

**Input**: Design documents from `/specs/022-grounding-nav-hierarchy/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/sidebar-navigation.md, quickstart.md

**Tests**: Included. The plan made the Playwright spec part of the design (research R9;
plan.md Project Structure lists `frontend/e2e/sidebar-navigation.spec.ts` as a new file),
so contract C1–C4 is checked by automated tests. C5 is checked by diff in the Polish phase.

**Organization**: Tasks are grouped by user story. **US2 runs before US1**, even though
both are P1: US2's reachability tests are written against *today's* sidebar and must pass
on it before any change is made. They then stay green through US1, which is how the
feature proves nothing became unreachable (FR-006, FR-007).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Paths are from the repository root

## Path Conventions

Web application; this feature touches `frontend/` only (plan.md Structure Decision).
The component is `frontend/src/components/layout/AppSidebar.vue`. Its nav types and
`navGroups` array are at lines 113–172, `isActive`/`navigate` at 174–180, the nav markup at
183–213, and the nav styles at 341–391. Locate by symbol name if these drift.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: A shared test fixture, so a sidebar test can boot the app shell without a backend.

- [X] T001 Create `frontend/e2e/fixtures/appShell.ts` exporting `installAppShellMocks(page, { catchAll?: boolean })`. It registers the five startup stubs copied verbatim from `frontend/e2e/fixtures/narrationWiki.ts` (lines 67–76: `**/api/config/`, `**/api/config/models`, `**/api/config/status`, `**/api/editor/config`, `**/api/grounding/config`). When `catchAll` is true, it **first** registers `page.route(url => url.pathname.startsWith('/api/'), r => r.fulfill({ json: {} }))`, before the five specific stubs. Match on the pathname, **not** the glob `**/api/**`: the glob also matches Vite's module URLs for `frontend/src/api/*.ts` (`/src/api/client.ts`), answers them with JSON, and stops the app from mounting. Playwright gives precedence to the most recently registered matching route, so registering the catch-all first lets the specific stubs win.
- [X] T002 Update `frontend/e2e/fixtures/narrationWiki.ts` so `installNarrationWikiMocks` calls `installAppShellMocks(page)` (no catch-all) in place of its five inline startup stubs, keeping its `**/api/narration-wiki/status**` stub and everything after it unchanged.
- [X] T003 Run `cd frontend && npx playwright test e2e/narration-wiki.spec.ts` and confirm it passes unchanged. This is the fixture refactor's baseline.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Types, active-state rules and a stable test hook, **with no visible change** to the sidebar. Every later phase depends on these.

**⚠️ CRITICAL**: The rendered sidebar must look and behave exactly as today at the end of this phase.

- [X] T004 In `frontend/src/components/layout/AppSidebar.vue`, extend the nav types per data-model.md: add optional `matchPrefix?: string` to `NavItem`; add a `RenderingPath` interface (`id: 'per-tool' | 'dossier-synthesis' | 'state-projection'`, `label`, `description`, `usesSharedExtraction: boolean`, `matchPrefixes: string[]`, `items: NavItem[]`); make `NavGroup` carry `items?: NavItem[]` and `paths?: RenderingPath[]`, never both.
- [X] T005 In `frontend/src/components/layout/AppSidebar.vue`, keep the existing `isActive(path)` helper (Settings keeps calling `isActive('/settings')` unchanged) and add `isItemActive(item: NavItem)` (true when `isActive(item.path)`, or `item.matchPrefix` is set and the current path equals it or starts with `item.matchPrefix + '/'`) and `isPathActive(p: RenderingPath)` (true when the current path equals any of `p.matchPrefixes` or starts with one of them plus `/`), per data-model.md's active-state rules. Switch the group items to `isItemActive`. **Implementation note:** `isPathActive` was moved to T016. `vue-tsc` runs with `noUnusedLocals`, which refuses a function with no caller, and nothing calls it until the path headers exist. Existing items have no `matchPrefix`, so their behaviour is unchanged.
- [X] T006 In `frontend/src/components/layout/AppSidebar.vue`'s markup, add `:data-nav-path="item.path"` to every rendered nav item, and `data-nav-path="/settings"` to Settings. This is the stable hook the reachability tests use, so they stay valid when a label changes. No visual change.
- [X] T007 Run `cd frontend && npm run build` and confirm it exits 0 (type-checks `frontend/src/components/layout/AppSidebar.vue`).

**Checkpoint**: The sidebar looks and behaves exactly as before, but now has typed paths, prefix-aware active rules and `data-nav-path` hooks.

---

## Phase 3: User Story 2 - Nothing becomes unreachable (Priority: P1) 🛡️ Guard

**Goal**: Lock in, before anything moves, that every existing entry and address still works (FR-006, FR-007; contract C2).

**Independent Test**: Run the reachability tests against today's sidebar. They pass, and they keep passing after US1.

### Tests for User Story 2

- [X] T008 [US2] Create `frontend/e2e/sidebar-navigation.spec.ts`. In `beforeEach`, call `installAppShellMocks(page, { catchAll: true })` and load `/`. Add the test **"every pre-existing entry is one click from its address"**: for each of the 19 addresses in data-model.md's inventory, click `[data-nav-path="<address>"]` in the sidebar and assert `page.url()` ends with that address. Key on the address, not the label.
- [X] T009 [US2] In `frontend/e2e/sidebar-navigation.spec.ts`, add the test **"every existing address still opens the same page"**: for each row of data-model.md's "Addresses that must keep resolving" table, `page.goto(address)` and assert the final path equals the expected destination (for example `/grounding/world-state` → `/grounding/distill`, `/ensemble` → `/ensemble/setup`, `/grounding` → `/grounding/campaign-state`, `/` → `/workflow/config`). Assert on the resolved path, not page content.
- [X] T010 [US2] Run `cd frontend && npx playwright test e2e/sidebar-navigation.spec.ts` **against the current, unreorganized sidebar** and confirm both tests pass. If one fails here, the fault is in the test or an existing defect, not in this feature; resolve it before starting US1. **Resolved during implementation:** the first run failed because the Session Doc Editor opens its config drawer on a cold start (`SessionDocEditor.vue`, `drawerOpen.value = true`), and the drawer's full-window scrim blocked the next sidebar click. That is intentional modal behaviour triggered by the stubbed config, not a defect. The test now dismisses the scrim by clicking it, as a person would, rather than bypassing pointer events, so a stray overlay would still be caught. Also found: Playwright 1.55 needed its own Chromium build (`npx playwright install chromium`); the existing suite failed until then.

**Checkpoint**: The guard is green on today's sidebar. From here on, any change that loses a page or breaks a link turns it red.

---

## Phase 4: User Story 1 - See that the paths are alternatives (Priority: P1) 🎯 MVP

**Goal**: One `GROUNDING DOCS` parent holding the three rendering paths as described, marked branches (FR-001–FR-005, FR-008, FR-011, FR-012; contract C1, C3).

**Independent Test**: A GM shown the sidebar can point to all three places that produce world-state content without opening a page (SC-001).

### Tests for User Story 1 (write first; they must FAIL on the current sidebar)

- [X] T011 [US1] In `frontend/e2e/sidebar-navigation.spec.ts`, add **"grounding paths form one hierarchy"** (contract C1): exactly one group titled `GROUNDING DOCS`; no group titled `ENSEMBLE WORKFLOW`; three path headings (role `heading`) under `GROUNDING DOCS`, in the order `Per-tool`, `Dossier synthesis`, `State projection`; each path's description visible as text; each path containing exactly the entries listed for it in data-model.md's tree, in order (Per-tool: Campaign State, World State, Party Document, Planning Document; Dossier synthesis: Ensemble; State projection: State Projection, Threads); clicking a path heading leaves the URL unchanged; `SESSION WORKFLOW`, `PREP`, `SETUP`, `INTEGRATIONS` and Settings unchanged in title, entries and order.
- [X] T012 [US1] In `frontend/e2e/sidebar-navigation.spec.ts`, add **"active page and its path are both marked"** (contract C3): for each row of the contract's C3 table, go to the address and assert the named item and the named path heading carry the active state, and that no other item or path heading does. Include the `/ensemble/extract` and `/ensemble/synthesize` rows (research R5's regression case) and `/prep/query` (no path heading active).
- [X] T013 [US1] Run `cd frontend && npx playwright test e2e/sidebar-navigation.spec.ts` and confirm T011 and T012 **fail** on the current sidebar while T008 and T009 still pass.

### Implementation for User Story 1

- [X] T014 [US1] In `frontend/src/components/layout/AppSidebar.vue`'s `navGroups`, replace the `GROUNDING DOCS` group's `items` with `paths` exactly as data-model.md's tree specifies: the three `RenderingPath` entries in order, with their labels, the **GM-approved descriptions verbatim**, `usesSharedExtraction`, `matchPrefixes`, and items (labels and `path`s unchanged except as in T015).
- [X] T015 [US1] In `frontend/src/components/layout/AppSidebar.vue`'s `navGroups`, delete the `ENSEMBLE WORKFLOW` group, and put its entry under the `dossier-synthesis` path as `{ label: 'Ensemble', path: '/ensemble/setup', matchPrefix: '/ensemble' }` (the approved rename; the address is unchanged).
- [X] T016 [US1] In `frontend/src/components/layout/AppSidebar.vue`'s markup, render a group with `paths` as: the existing group title, then for each path a container with an `h3` path heading (label), a `p` description, and its items using the existing nav-item markup (click to navigate, `data-nav-path`, `isItemActive`). The heading gets an active class from `isPathActive` and has no click handler (research R3). Groups with `items` render exactly as today. Settings is unchanged.
- [X] T017 [US1] In `frontend/src/components/layout/AppSidebar.vue`'s `<style scoped>`, add styles for the path container, heading, description and nested items. The heading is visually subordinate to the group title and dominant over items; the description is muted and wraps within the 210px sidebar; nested items get a small indent; the active path heading uses the existing accent colour. Do not change any footer (backend/model/batch/effort) styles.
- [X] T018 [US1] Run `cd frontend && npx playwright test e2e/sidebar-navigation.spec.ts`. T011, T012, T008 and T009 all pass.

**Checkpoint**: The hierarchy is visible, both P1 stories pass, and the MVP is shippable.

---

## Phase 5: User Story 3 - See the shared stages between paths (Priority: P2)

**Goal**: The descriptions tell the truth about which paths share the ensemble extraction, and rank nothing (FR-009, FR-011; contract C4).

**Independent Test**: From the sidebar alone, a GM answers "which paths reuse the ensemble extraction?" correctly (SC-005).

### Implementation for User Story 3 (test hook)

- [X] T019 [US3] In `frontend/src/components/layout/AppSidebar.vue`'s markup, add `:data-uses-shared-extraction="String(p.usesSharedExtraction)"` to each path container, so a test can check that the description agrees with the declared flag.
### Tests for User Story 3

- [X] T020 [US3] In `frontend/e2e/sidebar-navigation.spec.ts`, add **"descriptions state the shared extraction truthfully"** (contract C4): the `Dossier synthesis` and `State projection` descriptions contain "shared ensemble extraction" and their containers have `data-uses-shared-extraction="true"`; the `Per-tool` description does not contain it and its container has `"false"`; no description contains "recommended", "preferred", "legacy", "deprecated", "old" or "new" (case-insensitive, whole words).
- [X] T021 [US3] Run `cd frontend && npx playwright test e2e/sidebar-navigation.spec.ts`. All tests pass.

**Checkpoint**: All three stories pass independently.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T022 Run `cd frontend && npm run build` (type-checks every file under `frontend/src/`). Exits 0.
- [X] T023 Run `cd frontend && npx playwright test`, the full suite under `frontend/e2e/` including `frontend/e2e/narration-wiki.spec.ts`. Everything passes.
- [X] T024 Contract C5 check, per quickstart.md §4: `git diff --stat main -- frontend/src/router.ts frontend/src/views/` prints nothing, and `git diff --stat main -- frontend/` lists only `AppSidebar.vue` and files under `frontend/e2e/`. Then check `git diff main -- frontend/src/components/layout/AppSidebar.vue`: no hunk touches the `sidebar-footer` template block or the `.sidebar-footer`, `.backend-*`, `.model-*` or `.batch-*` styles (contract C5.4), and no hunk adds an `apiFetch` or `fetch` call. Since no store, view or router file changed, that also proves the app's API calls are unchanged (contract C5.3).
- [ ] T025 Hand quickstart.md §3 to the GM for the judgements the tests can't make: SC-001 (point to all three world-state paths without clicking), SC-005 (which paths share the extraction), the `/ensemble/extract` and `/grounding/world-state` spot checks, the sidebar-height check at 1280×720 (every entry reachable by scrolling), the State Projection page's signpost to Threads still working (`ProjectionSections.vue`), and a path with nothing built yet not looking disabled. Record the outcome in `specs/022-grounding-nav-hierarchy/checklists/requirements.md` Notes.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none.
- **Foundational (Phase 2)**: after Setup. Blocks every story.
- **US2 guard (Phase 3)**: after Foundational. **Must be green on the unreorganized sidebar before US1 starts** (T010).
- **US1 (Phase 4)**: after US2.
- **US3 (Phase 5)**: after US1. Its descriptions and path containers only exist once US1 has rendered them.
- **Polish (Phase 6)**: after all stories.

### Story independence, honestly stated

- **US2** is independent: it tests addresses, which this feature never changes.
- **US1** is independent of US3 but must run after US2, by design, so the guard exists first.
- **US3** depends on US1's markup. Its *test* is independent (it checks only description text and one attribute), but there's nothing for it to test until US1 renders the paths.

### Within each story

- Tests are written first and must fail before implementation (T013 checks this for US1).
- Most tasks edit one of two files, `AppSidebar.vue` and `sidebar-navigation.spec.ts`, so tasks on the same file run in order.

### Parallel Opportunities

Few, because the feature is one component and one spec file:

- T001 and T004 touch different files and can run in parallel.
- Within US1, writing the tests (T011–T012, spec file) can overlap with drafting the implementation (T014–T017, component) by two people, but T013 must confirm the tests fail against the **unchanged** component before T014 lands.

No task is marked [P]. Every candidate pair either shares a file or has an ordering constraint, and marking them would invite exactly the conflict the rule exists to prevent.

---

## Parallel Example: Setup + Foundational

```bash
# Different files, no dependency between them:
Task: "Create frontend/e2e/fixtures/appShell.ts (T001)"
Task: "Extend nav types in frontend/src/components/layout/AppSidebar.vue (T004)"
```

---

## Implementation Strategy

### MVP (US2 guard + US1)

1. Phase 1 → Phase 2. Nothing visible changes.
2. Phase 3: reachability guard, green on today's sidebar.
3. Phase 4: the hierarchy. **Stop and validate**: guard still green, T011/T012 green, and a GM look at the sidebar (quickstart §3 items 1, 3, 4).
4. Ship. The overlap is visible and nothing is lost.

### Incremental delivery

1. MVP as above.
2. US3: the truthful-descriptions test (the descriptions themselves already shipped with US1).
3. Polish: full suite, C5 diff, GM sign-off.

---

## Notes

- Every `AppSidebar.vue` task preserves the sidebar footer (backend, model, batch and effort selectors) untouched.
- The descriptions are GM-approved text (research R8). Copy them verbatim from data-model.md; don't edit them during implementation.
- Commit after each phase checkpoint.
