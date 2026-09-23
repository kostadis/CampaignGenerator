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
