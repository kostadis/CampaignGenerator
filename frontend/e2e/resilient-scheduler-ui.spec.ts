import { expect, test, type Page } from '@playwright/test'
import { installAppShellMocks } from './fixtures/appShell'

const summaryBase = '/api/grounding/summary-native'
const npcBase = '/api/npc-dossiers'
const status = (operation: string) => ({
  present: true, run_id: `${operation}-17`, operation, status: 'incomplete',
  concurrency: { value: 8, source: 'dgxlib', model: 'qwen3.8-flash-next' },
  counts: { total: 2, cached: 1, completed: 0, unfinished: 1, failed: 1 },
  endpoints: [{ id: 'spark-a', state: 'quarantined', active: 0, limit: 8, reason: 'timeout' }],
  outcomes: { 'item-2': { category: 'transport', code: 'timeout', message: 'retry on another endpoint' } },
  resume_available: true,
})

function sse() { return 'data: "resumed"\n\nevent: done\ndata: {"returncode":0}\n\n' }

async function mockSummary(page: Page) {
  await installAppShellMocks(page)
  await page.route('**/api/grounding/config', route => route.fulfill({ json: {
    summary_native: { summaries_dir: 'docs/summaries', range_since: 2, range_until: 5 },
  } }))
  await page.route(url => url.pathname === '/api/config/path-status', route => route.fulfill({ json: { exists: true } }))
  await page.route(url => url.pathname === `${summaryBase}/chapters`, route => route.fulfill({ json: { present: [2, 3, 4, 5], files: [], duplicate_chapters: [] } }))
  await page.route(url => url.pathname === `${summaryBase}/state`, route => route.fulfill({ json: {
    extract: { present: false, complete: false, stale: false, stale_reason: null, chunks: [], totals: { chunks: 0, checked: 0, kept: 0, dropped: 0 }, outliers: [], drops_file: null },
    audit: { present: false, complete: false, stale: false, stale_reason: null, counts: null, audit_file: null, track_files: ['docs/tracking.md'] },
    budgets: {}, annotations: {}, missing_dossiers: null, missing_dossiers_refused: false, planning_missing_dossiers: null, planning_missing_dossiers_refused: false,
    threads: { present: false, ratified_in_range: null, open: null, dormant: null, unattached: null, ambiguous: null, pending_groups: 0 },
  } }))
  await page.route(url => url.pathname === `${summaryBase}/status/extract`, route => route.fulfill({ json: status('extract') }))
  await page.route(url => url.pathname === `${summaryBase}/status/audit`, route => route.fulfill({ json: status('audit') }))
  await page.route(url => url.pathname.startsWith(`${summaryBase}/authority/`) || url.pathname === '/api/planning/notes', route => route.fulfill({ json: { ok: true, data: { state: 'absent' } } }))
  await page.route(url => [ `${summaryBase}/report`, `${summaryBase}/drafts` ].includes(url.pathname), route => route.fulfill({ json: [] }))
  await page.route('**/api/grounding/summary-native/drafts**', route => route.fulfill({ json: [] }))
}

test('Summary Native reloads scheduler status and sends a bare resume without a live endpoint', async ({ page }) => {
  await mockSummary(page)
  const requests: URL[] = []
  await page.route(url => url.pathname === `${summaryBase}/run/extract`, route => { requests.push(new URL(route.request().url())); return route.fulfill({ contentType: 'text/event-stream', body: sse() }) })
  await page.goto('/grounding/summary-native')
  const extractStatus = page.locator('[data-test="extract-scheduler-status"]')
  await expect(extractStatus.getByText('parallel 8 (dgxlib)')).toBeVisible()
  await expect(extractStatus.getByText('spark-a: quarantined · 0/8 active · timeout')).toBeVisible()
  await expect(extractStatus.getByText('item-2: transport timeout retry on another endpoint')).toBeVisible()
  await page.getByLabel('Resume an interrupted run').check()
  await page.getByRole('button', { name: 'Resume extract' }).click()
  await expect.poll(() => requests.length).toBe(1)
  expect(requests[0].searchParams.has('resume')).toBe(true)
  expect(requests[0].searchParams.get('resume')).toBe('')
  await page.reload()
  await expect(extractStatus.getByText('extract-17')).toBeVisible()
  await expect(extractStatus.getByText('spark-a: quarantined · 0/8 active · timeout')).toBeVisible()
})

async function mockNpcs(page: Page) {
  await installAppShellMocks(page)
  await page.route('**/api/grounding/config', route => route.fulfill({ json: { summary_native: { summaries_dir: 'docs/summaries', range_since: 2, range_until: 5 } } }))
  await page.route(url => url.pathname === '/api/config/path-status', route => route.fulfill({ json: { exists: true } }))
  await page.route(url => url.pathname === `${npcBase}/config`, route => route.fulfill({ json: { npc_root: 'docs/npcs/summary_native', recent_chapters: 2, recurring_min: 3, max_tokens: 2000, selection: {}, draft: { backend: 'dgx', model: 'qwen3.8-flash-next', mode: 'one-shot', chunk_chars: 1000 } } }))
  await page.route(url => url.pathname === `${npcBase}/chapters`, route => route.fulfill({ json: { present: [2, 3, 4, 5], files: [], duplicate_chapters: [] } }))
  await page.route(url => url.pathname === `${npcBase}/state`, route => route.fulfill({ json: { range: '2-5', linked: true, link_stale: false, warnings: { ambiguous: 0, generic_unruled: 0 }, npcs: [{ stem: 'npc_jimjar', subject: 'Jimjar', global: true, exclusion: null, n_entries: 2, n_scenes: 1, n_moments: 2, first_seen: 2, last_seen: 5, draft: 'none', published: false, verify: 'none', authored: false, composed: false, manual_dropped: [] }] } }))
  await page.route(url => url.pathname === `${npcBase}/report/link`, route => route.fulfill({ json: { findings: [] } }))
  await page.route(url => url.pathname === `${npcBase}/status/draft`, route => route.fulfill({ json: status('npc-draft') }))
  await page.route(url => url.pathname === `${npcBase}/status/verify`, route => route.fulfill({ json: status('npc-verify') }))
}

test('NPC Dossiers requires a materialized selection, then resumes and reloads status', async ({ page }) => {
  await mockNpcs(page)
  const requests: URL[] = []
  await page.route(url => url.pathname === `${npcBase}/run/draft`, route => { requests.push(new URL(route.request().url())); return route.fulfill({ contentType: 'text/event-stream', body: sse() }) })
  await page.goto('/npcs/dossiers')
  const draft = page.locator('[data-section="draft"]')
  await expect(draft.getByRole('button', { name: 'Draft' })).toBeDisabled()
  await draft.getByRole('radio', { name: /Every global NPC/ }).check()
  await draft.getByLabel('Resume an interrupted draft').check()
  await draft.getByRole('button', { name: 'Resume draft' }).click()
  await expect.poll(() => requests.length).toBe(1)
  expect(requests[0].searchParams.get('select')).toBe('all')
  expect(requests[0].searchParams.get('resume')).toBe('')
  await page.reload()
  await expect(page.getByText('Last draft npc-draft-17: incomplete')).toBeVisible()
})
