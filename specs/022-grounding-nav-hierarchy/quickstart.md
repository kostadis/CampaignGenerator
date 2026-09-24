# Quickstart: validating the Grounding Navigation Hierarchy

**Feature**: `022-grounding-nav-hierarchy`

How to prove the feature works. What it must satisfy is in
[contracts/sidebar-navigation.md](contracts/sidebar-navigation.md), and the tree and
inventory are in [data-model.md](data-model.md). This file doesn't repeat them.

## Prerequisites

```bash
cd ~/src/CampaignGenerator/frontend
npm install                      # first time only
npx playwright install chromium  # first time only
```

## 1. Build type-checks

```bash
npm run build                    # vue-tsc -b && vite build
```

**Expected**: exits 0. The new optional `paths` / `matchPrefix` fields type-check
against every existing nav group.

## 2. Automated contract check

```bash
npx playwright test e2e/sidebar-navigation.spec.ts
npx playwright test               # full suite: the existing narration-wiki spec must still pass
```

**Expected**: all pass at 1280×720. Playwright starts the dev server itself (see
`playwright.config.ts`, `reuseExistingServer: true`). All API calls are stubbed; no
backend or campaign workspace is needed.

The spec covers contract C1–C4. C5 ("nothing else changes") is checked by diff in step 4.

## 3. Look at it (SC-001, SC-005)

```bash
npm run dev                      # then open http://localhost:5173
```

With a real backend running (`./start` from the repo root), check against the success
criteria. These are judgements the tests can't make:

1. **SC-001**: without clicking, can you point to every place that produces world-state
   content? All three are under `GROUNDING DOCS`, as three named paths.
2. **SC-005**: from the sidebar alone, which paths reuse the ensemble extraction?
   The descriptions should answer it: Dossier synthesis and State projection.
3. Open `/ensemble/extract`. The **Ensemble** entry and the **Dossier synthesis**
   header are both marked. Before this feature, nothing was marked on this stage.
4. Open `/grounding/world-state`. It lands on World State, with **Per-tool** marked.
5. At a 1280×720 window, scroll the sidebar: every entry is still reachable with the three
   extra header rows. The sidebar is a fixed 210px, so height is what's at risk, not width.
6. On State Projection, a path with no threads yet shows its signpost to Threads, and
   following it lands on Threads with **State projection** marked.
7. In a workspace where a path has produced nothing yet, its branch still looks like the
   others. Unbuilt is not the same as disabled (spec edge case).

## 4. Confirm the change stayed in its lane (FR-010, contract C5)

```bash
cd ~/src/CampaignGenerator
git diff --stat main -- frontend/src/router.ts frontend/src/views/   # expect: no output
git diff --stat main -- frontend/src/components/layout/AppSidebar.vue frontend/e2e/
```

**Expected**: the first command prints nothing. The second lists only the sidebar
component and the e2e files.
