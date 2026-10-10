import { expect, test } from '@playwright/test'
import { installAppShellMocks } from './fixtures/appShell'

const SUMMARY_BASE = '/api/grounding/summary-native'

async function installSummaryNativeMocks(page: Parameters<typeof installAppShellMocks>[0]) {
  await installAppShellMocks(page, { catchAll: true })
  await page.route('**/api/grounding/config', route => route.fulfill({ json: {
    summary_native: { summaries_dir: 'docs/summaries', range_since: 1, range_until: 3 },
  } }))
  await page.route(url => url.pathname === `${SUMMARY_BASE}/chapters`, route => route.fulfill({
    json: { present: [1, 2, 3], files: [], duplicate_chapters: [] },
  }))
  await page.route(url => url.pathname === `${SUMMARY_BASE}/state`, route => route.fulfill({ json: {
    extract: { present: false, complete: false, stale: false, absent_chapters: [], chunks: [], totals: { chunks: 0, checked: 0, kept: 0, dropped: 0 }, outliers: [] },
    audit: { present: false, complete: false, stale: false, track_files: [] },
    budgets: { world_state: null, party: null, planning: null }, annotations: {},
    missing_dossiers: null, missing_dossiers_refused: false,
    planning_missing_dossiers: null, planning_missing_dossiers_refused: false,
    threads: { present: false, pending_groups: 0 },
  } }))
  await page.route(url => url.pathname === `${SUMMARY_BASE}/report`, route => route.fulfill({ status: 404, json: { error: 'none' } }))
  await page.route(url => url.pathname === `${SUMMARY_BASE}/drafts`, route => route.fulfill({ json: [] }))
}

test('promotion preview unpacks the CLI envelope and renders every result class', async ({ page }) => {
  await installSummaryNativeMocks(page)
  await page.route('**/api/grounding/summary-native/promotion/preview', async route => {
    expect(route.request().postDataJSON()).toEqual({
      since: 1, until: 3, review: 'promotion-check', check_report: 'report-1',
    })
    await route.fulfill({ status: 409, json: {
      ok: false, code: 'PROMOTION_BLOCKED', message: 'Preview is available with blockers.',
      data: {
        selection: {
          documents: [{ document_id: 'world_state', path: 'state/drafts/world_state.draft.md', sha256: 'a'.repeat(64) }],
          timeline: { path: 'state/drafts/canon_events_timeline.md', sha256: 'b'.repeat(64) },
          references: [{ path: 'state/drafts/reference/nested/road.md', sha256: 'c'.repeat(64) }],
          retained_records: [{ path: 'state/runs/world/record.json', sha256: 'd'.repeat(64) }],
          dependencies: [{ path: 'manifest.json', sha256: 'e'.repeat(64) }],
        },
        preview: {
          eligible: false, preview_sha256: 'f'.repeat(64), bundle_digest: '0'.repeat(64),
          claims: { state: 'not_available', message: 'Claims checking is not installed.' },
          gates: [
            { gate: 'source_review', state: 'passed', message: 'Source approvals are current.' },
            { gate: 'destination', state: 'blocked', code: 'PROMOTION_DESTINATION_STALE', message: 'Live destination changed.' },
            { gate: 'claims', state: 'not_available', code: 'CLAIMS_NOT_AVAILABLE', message: 'Claims checking is not installed.' },
          ],
          refusal_codes: ['PROMOTION_DESTINATION_STALE'],
          changes: [{ path: 'reference/removed.md', kind: 'remove', before_sha256: '1'.repeat(64), after_sha256: null,
            unified_diff: '-old generated member' }],
        },
        destination: { live_digest: '2'.repeat(64) },
      },
    } })
  })

  await page.goto('/grounding/summary-native')
  const panel = page.locator('[data-test="grounding-promotion-preview"]')
  await panel.locator('[data-test="promotion-review"]').fill('promotion-check')
  await panel.locator('[data-test="promotion-report"]').fill('report-1')
  await panel.getByRole('button', { name: 'Preview complete bundle' }).click()

  await expect(panel.getByText('Preview is available with blockers.', { exact: true })).toBeVisible()
  await expect(panel.getByText('Claims gate: not_available')).toBeVisible()
  await expect(panel.getByText('Source approval freshness: Current')).toBeVisible()
  await expect(panel.getByText('Destination preview freshness: Stale')).toBeVisible()
  await expect(panel.getByText('state/drafts/canon_events_timeline.md')).toBeVisible()
  await expect(panel.getByText('state/drafts/reference/nested/road.md')).toBeVisible()
  await expect(panel.getByText('state/runs/world/record.json')).toBeVisible()
  await expect(panel.getByText('reference/removed.md')).toBeVisible()
  await expect(panel.getByText('-old generated member')).toBeVisible()
})

test('freshness is unknown until the server returns explicit source and destination gates', async ({ page }) => {
  await installSummaryNativeMocks(page)
  await page.route('**/api/grounding/summary-native/promotion/preview', route => route.fulfill({ json: {
    ok: false, code: 'PROMOTION_BLOCKED', message: 'Claims unavailable.',
    data: { selection: { documents: [] }, preview: { eligible: false, gates: [], changes: [] }, destination: null },
  } }))
  await page.goto('/grounding/summary-native')
  const panel = page.locator('[data-test="grounding-promotion-preview"]')
  await panel.locator('[data-test="promotion-since"]').fill('1')
  await panel.locator('[data-test="promotion-until"]').fill('3')
  await panel.locator('[data-test="promotion-review"]').fill('promotion-check')
  await panel.locator('[data-test="promotion-report"]').fill('report-1')
  await panel.getByRole('button', { name: 'Preview complete bundle' }).click()
  await expect(panel.getByText('Source approval freshness: Unknown')).toBeVisible()
  await expect(panel.getByText('Destination preview freshness: Unknown')).toBeVisible()
  await expect(panel.getByText('Claims gate: not_available')).toBeVisible()
})

test('publication stays bound to the displayed digest and exposes receipt and recovery controls', async ({ page }) => {
  await installSummaryNativeMocks(page)
  await page.route('**/api/grounding/summary-native/promotion/preview', route => route.fulfill({ json: {
    ok: true, code: 'OK', message: 'eligible', data: {
      selection: { documents: [] }, destination: { generation_id: 'baseline-1' },
      preview: { eligible: true, preview_sha256: 'a'.repeat(64), gates: [], changes: [] },
    },
  } }))
  await page.route('**/api/grounding/summary-native/promotion/commit', async route => {
    expect(route.request().postDataJSON()).toEqual({
      since: 1, until: 3, review: 'review-1', check_report: 'report-1',
      preview_sha256: 'a'.repeat(64), request_id: 'request-1',
    })
    await route.fulfill({ json: { ok: true, code: 'OK', message: 'committed', data: {
      activation: { operation_id: 'operation-request-1' },
    } } })
  })
  await page.route('**/api/grounding/summary-native/promotion/receipt', async route => {
    expect(route.request().postDataJSON()).toEqual({ operation: 'operation-request-1' })
    await route.fulfill({ json: { ok: true, code: 'OK', message: 'receipt loaded', data: {
      activation: { activation_id: 'activation-request-1' }, publication: { request_id: 'request-1' },
    } } })
  })

  await page.goto('/grounding/summary-native')
  const panel = page.locator('[data-test="grounding-promotion-preview"]')
  await panel.locator('[data-test="promotion-review"]').fill('review-1')
  await panel.locator('[data-test="promotion-report"]').fill('report-1')
  await panel.getByRole('button', { name: 'Preview complete bundle' }).click()
  await panel.locator('[data-test="promotion-request-id"]').fill('request-1')
  await panel.locator('[data-test="promotion-commit"]').click()
  await expect(panel.locator('[data-test="promotion-commit"]')).toBeDisabled()
  await expect(panel).toContainText('preview consent was consumed')
  await expect(panel.locator('[data-test="promotion-operation"]')).toHaveValue('operation-request-1')
  await panel.getByRole('button', { name: 'View receipt' }).click()
  await expect(panel.locator('[data-test="promotion-inspection"]')).toContainText('activation-request-1')
  await expect(panel.getByRole('button', { name: 'Recover publication' })).toBeEnabled()
  await expect(panel.getByRole('button', { name: 'Recover migration' })).toBeEnabled()
})

test('unknown commit is recovered by operation id without repeating publication', async ({page}) => {
  await installSummaryNativeMocks(page)
  let commits=0
  await page.route('**/api/grounding/summary-native/promotion/preview', route => route.fulfill({json:{ok:true,code:'OK',message:'prepared',data:{selection:{documents:[]},destination:{generation_id:'old-generation'},preview:{eligible:true,preview_sha256:'a'.repeat(64),gates:[],changes:[]}}}}))
  await page.route('**/api/grounding/summary-native/promotion/commit', async route => {commits++;await route.fulfill({status:503,json:{ok:false,code:'PROMOTION_COMMIT_UNKNOWN',message:'Commit transport ended before acknowledgment.',data:{operation_id:'op-unknown',state:'unknown',prior_identity:'old-generation'}}})})
  await page.route('**/api/grounding/summary-native/promotion/status?operation=op-unknown', route => route.fulfill({json:{ok:true,code:'OK',message:'journal found',data:{state:'saved',prior_identity:'old-generation',new_identity:'new-generation'}}}))
  await page.route('**/api/grounding/summary-native/promotion/recover', async route => {expect(route.request().postDataJSON()).toEqual({operation:'op-unknown'});await route.fulfill({json:{ok:true,code:'OK',message:'recovered',data:{state:'committed',prior_identity:'old-generation',new_identity:'new-generation'}}})})
  await page.goto('/grounding/summary-native')
  const panel=page.locator('[data-test="grounding-promotion-preview"]')
  await panel.locator('[data-test="promotion-review"]').fill('review-1');await panel.locator('[data-test="promotion-report"]').fill('report-1')
  await panel.getByRole('button',{name:'Preview complete bundle'}).click();await panel.locator('[data-test="promotion-request-id"]').fill('request-stable');await panel.locator('[data-test="promotion-commit"]').click()
  await expect(panel.locator('[data-test="promotion-outcome"]')).toContainText('unknown')
  await expect(panel).toContainText('Refresh status')
  expect(commits).toBe(1)
  await panel.locator('[data-test="promotion-operation"]').fill('op-unknown')
  await panel.getByRole('button',{name:'Refresh status'}).click()
  await expect(panel.locator('[data-test="promotion-outcome"]')).toContainText('saved')
  await expect(panel.locator('[data-test="promotion-outcome"]')).toContainText('old-generation')
  await expect(panel.locator('[data-test="promotion-outcome"]')).toContainText('new-generation')
  await panel.getByRole('button',{name:'Recover publication'}).click()
  await expect(panel.locator('[data-test="promotion-outcome"]')).toContainText('committed')
  expect(commits).toBe(1)
})

for (const width of [320,375]) test(`long manifest and diff stay contained at ${width}px`, async ({page}) => {
  await page.setViewportSize({width,height:760});await installSummaryNativeMocks(page)
  const long='nested/'.repeat(18)+'reference-with-a-long-name.md'
  await page.route('**/api/grounding/summary-native/promotion/preview',route=>route.fulfill({json:{ok:false,code:'PROMOTION_BLOCKED',message:'edited live',data:{selection:{references:[{path:long,sha256:'f'.repeat(64)}]},destination:{live_digest:'e'.repeat(64)},preview:{eligible:false,gates:[{gate:'destination',state:'blocked',code:'PROMOTION_EDITED_LIVE',message:'A very long destination explanation '.repeat(12)}],changes:[{path:long,kind:'modify',before_sha256:'a'.repeat(64),after_sha256:'b'.repeat(64),unified_diff:('-long evidence line '.repeat(80))}]}}}}))
  await page.goto('/grounding/summary-native');const panel=page.locator('[data-test="grounding-promotion-preview"]');await panel.locator('[data-test="promotion-review"]').fill('r');await panel.locator('[data-test="promotion-report"]').fill('p');await panel.getByRole('button',{name:'Preview complete bundle'}).click()
  await expect(panel.getByText(long,{exact:true}).first()).toBeVisible()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
})
