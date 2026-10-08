import { expect, test, type Page } from '@playwright/test'
import { installAppShellMocks } from './fixtures/appShell'

// Spec 033 (chunked grounding docs), T059. Every API route is mocked: the page only builds the
// documented query parameters and renders what the server reports (Principle VI/IX).
// Contract: specs/033-chunked-grounding-docs/contracts/http.md.

const BASE = '/api/grounding/summary-native'

const groundingConfig = {
  summary_native: { summaries_dir: 'docs/summaries', range_since: 2, range_until: 5 },
}

const stateBody = {
  extract: {
    present: true, complete: true, stale: false, stale_reason: null,
    backend: 'dgx', model: 'qwen3.8-flash-next', chunk_chars: 60000, absent_chapters: [],
    chunks: [{ index: 1, chapters: '002-005', status: 'checked', kept: 12, dropped: 1, outlier: false }],
    totals: { chunks: 1, checked: 1, kept: 12, dropped: 1 },
    outliers: [], drops_file: 'state/notes/drops.md',
  },
  audit: {
    present: false, complete: false, stale: false, stale_reason: null, counts: null,
    audit_file: null, track_files: ['docs/tracking/a.md', 'docs/tracking/b.md'],
  },
  world_budgets: null,
  annotations: {},
  missing_dossiers: null,
  missing_dossiers_refused: false,
}

/** An SSE body: one data frame per text, then the `done` event with the return code. */
function sse(text: string, returncode: number): string {
  return `data: ${JSON.stringify(text)}\n\nevent: done\ndata: ${JSON.stringify({ returncode })}\n\n`
}

/** Answer a run route with `body` and record each request URL. */
async function mockRun(page: Page, path: string, text = 'ok\n', returncode = 0): Promise<URL[]> {
  const seen: URL[] = []
  await page.route(url => url.pathname === `${BASE}/run/${path}`, route => {
    seen.push(new URL(route.request().url()))
    return route.fulfill({
      status: 200, contentType: 'text/event-stream', headers: { 'Cache-Control': 'no-cache' },
      body: sse(text, returncode),
    })
  })
  return seen
}

async function openPage(page: Page) {
  await installAppShellMocks(page)
  // Registered after the shell's own stub so this one wins (the most recent matching route does).
  await page.route('**/api/grounding/config', route => route.fulfill({ json: groundingConfig }))
  await page.route('**/api/config/path-status*', route => route.fulfill({ json: { exists: true } }))
  await page.route(url => url.pathname === `${BASE}/chapters`, route => route.fulfill({
    json: { present: [2, 3, 4, 5], files: [], duplicate_chapters: [] },
  }))
  await page.route(url => url.pathname === `${BASE}/state`, route => route.fulfill({ json: stateBody }))
  await page.route(url => url.pathname === `${BASE}/report`, route => route.fulfill({ status: 404, json: { error: 'none' } }))
  await page.route(url => url.pathname === `${BASE}/drafts`, route => route.fulfill({ json: [] }))
  await page.goto('/grounding/summary-native')
  await expect(page.getByRole('heading', { name: 'Summary-native' })).toBeVisible()
  // Hydration is complete when the range from grounding.yaml has reached the pickers.
  await expect(page.getByRole('button', { name: 'Extract notes' })).toBeEnabled()
}

const section = (page: Page, heading: RegExp) =>
  page.locator('.form-section').filter({ has: page.getByRole('heading', { name: heading }) })

test('Extract sends the range and repeated endpoints, never a singular endpoint', async ({ page }) => {
  await openPage(page)
  const seen = await mockRun(page, 'extract', 'chunk 01/01 ch 002-005 kept 12 dropped 1\n')
  const box = section(page, /3\. Extract notes/)
  await box.locator('textarea').fill('http://spark:8001/v1\nhttp://spark2:8001/v1')
  await box.locator('.field', { hasText: 'Workers per endpoint' }).locator('input').fill('4')
  await box.getByRole('button', { name: 'Extract notes' }).click()
  await expect(box.getByText('chunk 01/01 ch 002-005 kept 12 dropped 1')).toBeVisible()

  expect(seen).toHaveLength(1)
  const q = seen[0].searchParams
  expect(q.get('since')).toBe('2')
  expect(q.get('until')).toBe('5')
  expect(q.getAll('endpoints')).toEqual(['http://spark:8001/v1', 'http://spark2:8001/v1'])
  expect(q.get('parallel')).toBe('4')
  expect(q.has('endpoint')).toBe(false)
  // Blank fields and unchecked boxes are not sent at all (the CLI resolves its own defaults).
  expect(q.has('chunk_chars')).toBe(false)
  expect(q.has('force')).toBe(false)
  expect(q.has('dump_only')).toBe(false)
})

test('Extract shows the stored notes: chunk table, counts and the drops file', async ({ page }) => {
  await openPage(page)
  const box = section(page, /3\. Extract notes/)
  await expect(box.getByText('12 notes kept')).toBeVisible()
  await expect(box.getByText('1 dropped')).toBeVisible()
  await expect(box.getByRole('cell', { name: '002-005' })).toBeVisible()
  await expect(box.getByText('state/notes/drops.md')).toBeVisible()
})

test('Audit prefills the configured track files and sends one track_file each, plus candidates', async ({ page }) => {
  await openPage(page)
  const seen = await mockRun(page, 'audit', 'audit: 3 items\n')
  const box = section(page, /4\. Audit the tracking files/)
  const files = box.locator('textarea').first()
  await expect(files).toHaveValue('docs/tracking/a.md\ndocs/tracking/b.md')
  await box.locator('.field', { hasText: 'Candidate chapters per item' }).locator('input').fill('2')
  await box.getByRole('button', { name: 'Run audit' }).click()
  await expect(box.getByText('audit: 3 items')).toBeVisible()

  expect(seen).toHaveLength(1)
  const q = seen[0].searchParams
  expect(q.getAll('track_file')).toEqual(['docs/tracking/a.md', 'docs/tracking/b.md'])
  expect(q.get('candidates')).toBe('2')
  expect(q.get('since')).toBe('2')
  expect(q.get('until')).toBe('5')
})

test('Audit sends an edited track-file list for that run', async ({ page }) => {
  await openPage(page)
  const seen = await mockRun(page, 'audit')
  const box = section(page, /4\. Audit the tracking files/)
  await box.locator('textarea').first().fill('docs/tracking/only.md')
  await box.getByRole('button', { name: 'Run audit' }).click()
  await expect(box.getByText('Success')).toBeVisible()
  expect(seen[0].searchParams.getAll('track_file')).toEqual(['docs/tracking/only.md'])
})

test('Annotate runs per draft, with a dry-run preview that says so', async ({ page }) => {
  await openPage(page)
  const seen = await mockRun(page, 'annotate/world_state', 'annotations: 1 later, 0 since, 0 unverified; 0 removed\n')
  const box = section(page, /6\. Annotate the world_state draft/)
  await box.getByRole('button', { name: 'Preview annotations for world_state (dry run)' }).click()
  await expect(box.getByText('annotations: 1 later').first()).toBeVisible()
  expect(seen).toHaveLength(1)
  expect(seen[0].searchParams.get('dry_run')).toBe('true')

  await box.getByRole('button', { name: 'Annotate world_state', exact: true }).click()
  await expect.poll(() => seen.length).toBe(2)
  expect(seen[1].searchParams.has('dry_run')).toBe(false)
  expect(seen[1].searchParams.get('since')).toBe('2')
})

test('the fallback-lines box is unchecked on load, is sent when checked, and resets after a reload', async ({ page }) => {
  await openPage(page)
  const seen = await mockRun(page, 'synth/world_state', 'Wrote draft: state/drafts/world_state.draft.md\n')
  const box = section(page, /5\. Synthesize a draft/)
  const fallback = box.getByLabel('Write fallback lines for NPCs without a published dossier')

  await expect(fallback).not.toBeChecked()
  // A plain run does not carry the flag.
  await box.getByRole('button', { name: 'Synthesize world_state' }).click()
  await expect(box.getByText('Success')).toBeVisible()
  expect(seen[0].searchParams.has('fallback_npc_lines')).toBe(false)

  await fallback.check()
  await box.getByRole('button', { name: 'Synthesize world_state' }).click()
  await expect.poll(() => seen.length).toBe(2)
  expect(seen[1].searchParams.get('fallback_npc_lines')).toBe('true')

  // Never persisted: a reload starts unchecked again.
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Summary-native' })).toBeVisible()
  await expect(section(page, /5\. Synthesize a draft/)
    .getByLabel('Write fallback lines for NPCs without a published dossier')).not.toBeChecked()
})

test('the fallback-lines box exists for world_state only', async ({ page }) => {
  await openPage(page)
  const box = section(page, /5\. Synthesize a draft/)
  const label = 'Write fallback lines for NPCs without a published dossier'
  await expect(box.getByLabel(label)).toBeVisible()
  await box.locator('select').first().selectOption('campaign_state')
  await expect(box.getByLabel(label)).toHaveCount(0)
})

test('a missing-dossier refusal lists each NPC with its state and links to the NPC dossiers page', async ({ page }) => {
  await openPage(page)
  const refusal = [
    "Error: world_state's Key NPCs need a published, verified dossier for each selected NPC; 2 of 3 have none:",
    '  Ilvara Mizzrym: not drafted',
    '  Kalan: failed verification (not-found 2)',
    'Draft, verify and publish them, then build again:',
    '  summary_native npc-draft --since 2 --until 5 --name "Ilvara Mizzrym" "Kalan"',
    'or pass --fallback-npc-lines to write a code-built line for each of them.',
    '',
  ].join('\n')
  await mockRun(page, 'synth/world_state', refusal, 2)
  // What the server reports once that build has written state/missing_dossiers.json: the page re-reads
  // /state when the run ends, and that answer (not the stream) is what survives the refresh and a reload.
  await page.route(url => url.pathname === `${BASE}/state`, route => route.fulfill({
    json: {
      ...stateBody,
      missing_dossiers: [
        { name: 'Ilvara Mizzrym', state: 'not drafted' },
        { name: 'Kalan', state: 'failed verification (not-found 2)' },
      ],
      missing_dossiers_refused: true,
    },
  }))
  const box = section(page, /5\. Synthesize a draft/)
  await box.getByRole('button', { name: 'Synthesize world_state' }).click()

  const panel = box.locator('.missing-npcs')
  await expect(panel).toBeVisible()
  await expect(panel.getByText('Build refused: 2 selected NPC(s) have no published, verified dossier')).toBeVisible()
  await expect(panel.getByRole('row', { name: /Ilvara Mizzrym\s+not drafted/ })).toBeVisible()
  await expect(panel.getByRole('row', { name: /Kalan\s+failed verification \(not-found 2\)/ })).toBeVisible()
  // The command line that merely contains the NPC names is not mistaken for an NPC.
  await expect(panel.getByRole('row')).toHaveCount(3) // header + two NPCs
  await expect(panel.getByRole('link', { name: 'NPC dossiers page' })).toHaveAttribute('href', '/npcs/dossiers')
})
