import { expect, test, type Page } from '@playwright/test'
import { installAppShellMocks } from './fixtures/appShell'

// Contract: specs/022-grounding-nav-hierarchy/contracts/sidebar-navigation.md
// Every page-specific API call is answered with {} (catch-all), so these tests
// assert navigation, never page behaviour.

test.beforeEach(async ({ page }) => {
  await installAppShellMocks(page, { catchAll: true })
  await page.goto('/')
  await expect(page.locator('.sidebar-nav')).toBeVisible()
})

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

// data-model.md "Inventory": every sidebar entry that existed before 022.
// Keyed on address, not label, so the same test holds before and after the
// approved 'Ensemble Grounding Docs' -> 'Ensemble' rename.
const INVENTORY = [
  '/workflow/config', '/workflow/editor', '/workflow/wiki',
  '/grounding/campaign-state', '/grounding/distill', '/grounding/party',
  '/grounding/planning', '/grounding/projections', '/grounding/threads',
  '/ensemble/setup',
  '/prep/session-prep', '/prep/npc-table', '/prep/query', '/prep/connections',
  '/setup/players', '/setup/dnd-sheet', '/setup/make-tracking',
  '/integrations/scabard',
  '/settings',
]

// data-model.md "Addresses that must keep resolving" (FR-007, contract C2.3).
const RESOLVES: [string, string][] = [
  ['/', '/workflow/config'],
  ['/workflow', '/workflow/config'],
  ['/workflow/editor/review', '/workflow/editor/review'],
  ['/grounding', '/grounding/campaign-state'],
  ['/grounding/world-state', '/grounding/distill'],
  ['/ensemble', '/ensemble/setup'],
  ['/ensemble/extract', '/ensemble/extract'],
  ['/ensemble/bundle', '/ensemble/bundle'],
  ['/ensemble/synthesize', '/ensemble/synthesize'],
  ['/prep', '/prep/session-prep'],
  ['/setup', '/setup/players'],
  ...INVENTORY.map((a): [string, string] => [a, a]),
]

// The Session Doc Editor deliberately opens its config drawer on a cold start
// (SessionDocEditor.vue: `drawerOpen.value = true` when config isn't ready), and
// the drawer's scrim is modal over the whole window, sidebar included. With the
// stubbed config it always cold-starts. Dismiss it the way a person does, by
// clicking the scrim, rather than bypassing pointer events: a bypass would also
// hide an overlay that blocked the sidebar by mistake.
async function dismissModalScrim(page: Page) {
  await page.waitForLoadState('networkidle')
  const scrim = page.locator('.drawer-scrim')
  if (await scrim.isVisible()) await scrim.click()
}

test('every pre-existing entry is one click from its address', async ({ page }) => {
  expect(INVENTORY).toHaveLength(19)
  for (const address of INVENTORY) {
    const entry = page.locator(`.sidebar-nav [data-nav-path="${address}"]`)
    await expect(entry, `sidebar entry for ${address}`).toHaveCount(1)
    await entry.click()
    await expect(page).toHaveURL(new RegExp(`${escape(address)}$`))
    await dismissModalScrim(page)
  }
})

test('every existing address still opens the same page', async ({ page }) => {
  for (const [address, expected] of RESOLVES) {
    await page.goto(address)
    await expect(page, `${address} should resolve to ${expected}`)
      .toHaveURL(new RegExp(`^[^/]+//[^/]+${escape(expected)}$`))
  }
})

// ── US1: the hierarchy (contract C1, C3) ────────────────────────────────────

// data-model.md "The tree". Descriptions are the GM-approved wording, verbatim.
const PATHS = [
  {
    id: 'per-tool',
    label: 'Per-tool',
    description: 'One tool per document, each with its own extraction.',
    items: ['Campaign State', 'World State', 'Party Document', 'Planning Document'],
  },
  {
    id: 'dossier-synthesis',
    label: 'Dossier synthesis',
    description: 'Facts → per-entity dossiers → grounding docs. Reads the shared ensemble extraction.',
    items: ['Ensemble'],
  },
  {
    id: 'state-projection',
    label: 'State projection',
    description: 'Rebuilds only the sections that went stale. Reads the shared ensemble extraction.',
    items: ['State Projection', 'Threads'],
  },
]

// Groups outside the grounding section: unchanged in title, entries and order.
const UNCHANGED_GROUPS: Record<string, string[]> = {
  'SESSION WORKFLOW': ['① Session Config', '② Session Doc Editor', '③ Narration Wiki'],
  PREP: ['Session Prep', 'NPC Table', 'Query Summaries', 'Connection Graph'],
  SETUP: ['Players', 'D&D Sheet', 'Make Tracking'],
  INTEGRATIONS: ['Scabard Sync'],
}

function group(page: Page, title: string) {
  return page.locator('.nav-group', { has: page.locator('.nav-group-title', { hasText: new RegExp(`^${escape(title)}$`) }) })
}

test('grounding paths form one hierarchy', async ({ page }) => {
  const titles = (await page.locator('.nav-group-title').allInnerTexts()).map(t => t.trim())
  expect(titles).toEqual(['SESSION WORKFLOW', 'GROUNDING DOCS', 'PREP', 'SETUP', 'INTEGRATIONS'])
  expect(titles).not.toContain('ENSEMBLE WORKFLOW')

  const grounding = group(page, 'GROUNDING DOCS')
  await expect(grounding.getByRole('heading', { level: 3 })).toHaveText(PATHS.map(p => p.label))

  for (const p of PATHS) {
    const section = grounding.locator(`[data-path-id="${p.id}"]`)
    await expect(section.locator('.nav-path-desc')).toHaveText(p.description)
    await expect(section.locator('.nav-path-desc')).toBeVisible()
    await expect(section.locator('.nav-item')).toHaveText(p.items)
  }

  // Path headings are labels, not links (research R3).
  const before = page.url()
  await grounding.getByRole('heading', { level: 3, name: 'State projection' }).click()
  expect(page.url()).toBe(before)

  for (const [title, items] of Object.entries(UNCHANGED_GROUPS)) {
    await expect(group(page, title).locator('.nav-item')).toHaveText(items)
  }
  await expect(page.locator('.sidebar-nav [data-nav-path="/settings"]')).toHaveText('Settings')
})

// contracts C3: [address, active item, active path heading or null]
const ACTIVE: [string, string, string | null][] = [
  ['/grounding/distill', 'World State', 'Per-tool'],
  ['/grounding/world-state', 'World State', 'Per-tool'],
  ['/ensemble/setup', 'Ensemble', 'Dossier synthesis'],
  ['/ensemble/extract', 'Ensemble', 'Dossier synthesis'],
  ['/ensemble/synthesize', 'Ensemble', 'Dossier synthesis'],
  ['/grounding/threads', 'Threads', 'State projection'],
  ['/prep/query', 'Query Summaries', null],
]

test('active page and its path are both marked', async ({ page }) => {
  for (const [address, item, path] of ACTIVE) {
    await page.goto(address)
    await expect(page.locator('.sidebar-nav .nav-item.active'), `active item on ${address}`).toHaveText([item])
    const activePaths = page.locator('.sidebar-nav .nav-path-title.active')
    if (path) await expect(activePaths, `active path on ${address}`).toHaveText([path])
    else await expect(activePaths, `no active path on ${address}`).toHaveCount(0)
  }
})
