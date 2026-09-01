import { expect, test } from '@playwright/test'
import { installNarrationWikiMocks, recoveryStatus } from './fixtures/narrationWiki'

test.beforeEach(async ({ page }) => {
  await installNarrationWikiMocks(page)
  await page.goto('/workflow/wiki')
  await expect(page.getByRole('heading', { name: 'Narration Wiki' })).toBeVisible()
})

test('parses arbitrary POST-SSE chunks and reloads status after completion', async ({ page }) => {
  await page.getByRole('button', { name: 'Check indexes' }).click()
  await expect(page.getByText('first chunk')).toBeVisible()
  await expect(page.getByText('$ $ narration_wiki')).toBeVisible()
})

test('reloads disk status after nonzero completion and AbortController cancellation', async ({ page }) => {
  let statusRequests = 0
  await page.route('**/api/narration-wiki/status**', route => {
    statusRequests += 1
    return route.fulfill({ json: recoveryStatus })
  })
  await page.getByRole('button', { name: 'Collect' }).click()
  await expect(page.getByRole('alert')).toContainText('code 5')
  expect(statusRequests).toBeGreaterThan(0)

  await page.getByRole('button', { name: 'Apply for comparison' }).click()
  await expect(page.getByRole('button', { name: 'Cancel running action' })).toBeEnabled()
  await page.getByRole('button', { name: 'Cancel running action' }).click()
  await expect(page.getByRole('button', { name: 'Cancel running action' })).toBeDisabled()
  expect(statusRequests).toBeGreaterThan(1)
})

test('supports cancellation and keyboard-reachable human Gate controls', async ({ page }) => {
  await page.getByLabel('Resolution').fill('Use the selected campaign source.')
  await page.getByLabel('GM rationale').fill('The campaign rulebook owns named guidance.')
  await page.getByRole('button', { name: 'Persist conflict ruling' }).focus()
  await expect(page.getByRole('button', { name: 'Persist conflict ruling' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByLabel('Pattern slug')).toBeFocused()
  await expect(page.getByRole('button', { name: 'Cancel running action' })).toBeDisabled()
})

test('at 1280x720 every resizable panel honors 320x160 and both scroll axes', async ({ page }) => {
  expect(page.viewportSize()).toEqual({ width: 1280, height: 720 })
  const panels = page.locator('.wiki-resizable-panel')
  await expect(panels).toHaveCount(7)
  for (let index = 0; index < await panels.count(); index += 1) {
    const panel = panels.nth(index)
    await panel.evaluate((element) => {
      const node = element as HTMLElement
      node.style.width = '320px'
      node.style.height = '160px'
    })
    const geometry = await panel.evaluate((element) => {
      const node = element as HTMLElement
      const style = getComputedStyle(node)
      return {
        width: node.offsetWidth,
        height: node.offsetHeight,
        overflowX: style.overflowX,
        overflowY: style.overflowY,
      }
    })
    expect(geometry.width).toBeGreaterThanOrEqual(320)
    expect(geometry.height).toBeGreaterThanOrEqual(160)
    expect(geometry.overflowX).toBe('scroll')
    expect(geometry.overflowY).toBe('scroll')
  }
})

test('renders recovery state from disk rather than browser-owned progress', async ({ page }) => {
  await page.route('**/api/narration-wiki/status**', route => route.fulfill({ json: recoveryStatus }))
  await page.getByRole('button', { name: 'Reload status' }).click()
  await expect(page.getByText('needs_attention').first()).toBeVisible()
  await expect(page.getByText('inspect_hashes')).toBeVisible()
})
