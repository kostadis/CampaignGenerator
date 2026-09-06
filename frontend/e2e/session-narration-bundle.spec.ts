import { expect, test } from '@playwright/test'
import {
  bundlePartial,
  bundleSuccess,
  bundleUnreconcilable,
  bundleZeroWritePartial,
  installSessionNarrationBundleMocks,
  openReadySessionEditor,
} from './fixtures/sessionNarrationBundle'

test('shows ordered narrator and replacement scope before spending tokens', async ({ page }) => {
  const mocks = await installSessionNarrationBundleMocks(page)
  await openReadySessionEditor(page)

  await expect(page.getByRole('button', { name: 'Narrate', exact: true })).toBeVisible()
  await page.getByRole('button', { name: /Narrate all in one call/ }).click()

  const dialog = page.getByRole('dialog', { name: 'Narrate all in one call' })
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('3 scenes in plan order · 48,000 token total ceiling')
  const rows = dialog.getByRole('listitem')
  await expect(rows).toHaveCount(3)
  await expect(rows.nth(0)).toContainText('The First Door')
  await expect(rows.nth(0)).toContainText('Alice')
  await expect(rows.nth(0)).toContainText('new')
  await expect(rows.nth(1)).toContainText('A Name in the Ledger')
  await expect(rows.nth(1)).toContainText('Bob')
  await expect(rows.nth(1)).toContainText('will replace')
  await expect(rows.nth(2)).toContainText('Rain on the Quay')
  expect(mocks.bundleRequests).toEqual([])
})

test('cancel closes the confirmation without making a bundle request', async ({ page }) => {
  const mocks = await installSessionNarrationBundleMocks(page)
  await openReadySessionEditor(page)

  await page.getByRole('button', { name: /Narrate all in one call/ }).click()
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Narrate all in one call' })).toBeHidden()
  expect(mocks.bundleRequests).toEqual([])
})

test('materializes every displayed index and shows report-derived success', async ({ page }) => {
  const mocks = await installSessionNarrationBundleMocks(page, bundleSuccess)
  await openReadySessionEditor(page)
  const initialSceneRequests = mocks.sceneRequests.count

  await page.getByRole('button', { name: /Narrate all in one call/ }).click()
  await page.getByRole('button', { name: 'Narrate 3 in one call' }).click()

  await expect(page.getByText('Bundled narration complete — 3/3 scenes written.')).toBeVisible()
  await expect(page.getByText(/\$ sd_narrate --batch-scenes --scene 1 2 3/)).toBeVisible()
  await expect.poll(() => mocks.bundleRequests.length).toBe(1)
  const request = new URL(mocks.bundleRequests[0])
  expect(request.searchParams.getAll('scene')).toEqual(['1', '2', '3'])
  await expect.poll(() => mocks.sceneRequests.count).toBeGreaterThan(initialSceneRequests)
})

test('saves a dirty raw scene before launching the bundle', async ({ page }) => {
  const mocks = await installSessionNarrationBundleMocks(page, bundleSuccess)
  await openReadySessionEditor(page)

  await page.getByText('The First Door', { exact: true }).click()
  const editor = page.locator('textarea.editor-ta')
  await editor.fill('- edited reviewed source\n')
  await page.getByRole('button', { name: /Narrate all in one call/ }).click()
  await page.getByRole('button', { name: 'Narrate 3 in one call' }).click()
  await expect(page.getByText('Bundled narration complete — 3/3 scenes written.')).toBeVisible()

  expect(mocks.mutations.indexOf('save')).toBeGreaterThanOrEqual(0)
  expect(mocks.mutations.indexOf('save')).toBeLessThan(mocks.mutations.indexOf('bundle'))
})

test('partial completion names recovery scenes and keeps current-scene narration available', async ({ page }) => {
  const mocks = await installSessionNarrationBundleMocks(page, bundlePartial)
  await openReadySessionEditor(page)
  const initialSceneRequests = mocks.sceneRequests.count

  await page.getByRole('button', { name: /Narrate all in one call/ }).click()
  await page.getByRole('button', { name: 'Narrate 3 in one call' }).click()

  await expect(page.getByText(/Bundled narration partial — 1\/3 written/)).toBeVisible()
  await expect(page.getByText(/Scene 2 — A Name in the Ledger/)).toBeVisible()
  await expect(page.getByText(/Scene 3 — Rain on the Quay/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Narrate', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /Narrate all in one call/ })).toBeEnabled()
  await expect.poll(() => mocks.sceneRequests.count).toBeGreaterThan(initialSceneRequests)
})

test('unreconcilable completion has distinct no-write status and leaves recovery actions', async ({ page }) => {
  await installSessionNarrationBundleMocks(page, bundleUnreconcilable)
  await openReadySessionEditor(page)

  await page.getByRole('button', { name: /Narrate all in one call/ }).click()
  await page.getByRole('button', { name: 'Narrate 3 in one call' }).click()

  await expect(page.getByText(/Bundled response could not be reconciled — no bundle output was written/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Narrate', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /Narrate all in one call/ })).toBeEnabled()
})

test('zero-write partial remains a recoverable partial outcome', async ({ page }) => {
  await installSessionNarrationBundleMocks(page, bundleZeroWritePartial)
  await openReadySessionEditor(page)

  await page.getByRole('button', { name: /Narrate all in one call/ }).click()
  await page.getByRole('button', { name: 'Narrate 3 in one call' }).click()

  await expect(page.getByText(/Bundled narration partial — 0\/3 written/)).toBeVisible()
  await expect(page.getByText(/Scene 1 — The First Door/)).toBeVisible()
  await expect(page.getByText(/Scene 3 — Rain on the Quay/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Narrate', exact: true })).toBeVisible()
})

test('drawer distinguishes sequential, bundled, and provider batch controls', async ({ page }) => {
  await installSessionNarrationBundleMocks(page)
  await openReadySessionEditor(page)

  await page.getByRole('button', { name: /Config/ }).click()
  await expect(page.getByText('Content bundling and provider Message Batches are separate choices.')).toBeVisible()
  await expect(page.locator('#narrate-batch-token-limit')).toHaveValue('48000')
  await expect(page.getByText('Per-scene output cap for sequential narration.')).toBeVisible()
})
