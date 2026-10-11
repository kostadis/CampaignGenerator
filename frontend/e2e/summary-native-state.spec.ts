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
  budgets: { world_state: null, party: null, planning: null },
  annotations: {},
  missing_dossiers: null,
  missing_dossiers_refused: false,
  // spec 034: planning has its own missing-dossier list and the ratified-thread counts of its last build
  planning_missing_dossiers: null,
  planning_missing_dossiers_refused: false,
  threads: {
    present: false, ratified_in_range: null, open: null, dormant: null,
    unattached: null, ambiguous: null, pending_groups: 0,
  },
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

test('the fallback-lines box exists for world_state and planning only', async ({ page }) => {
  await openPage(page)
  const box = section(page, /5\. Synthesize a draft/)
  const label = 'Write fallback lines for NPCs without a published dossier'
  await expect(box.getByLabel(label)).toBeVisible()
  await box.locator('select').first().selectOption('planning')
  await expect(box.getByLabel(label)).toBeVisible()
  await box.locator('select').first().selectOption('campaign_state')
  await expect(box.getByLabel(label)).toHaveCount(0)
})

// ── spec 034 US2: planning ──────────────────────────────────────────────────

test('planning sends the fallback flag only when checked, plus its selection and config, and never the retired parts', async ({ page }) => {
  await openPage(page)
  const seen = await mockRun(page, 'synth/planning', 'Wrote draft: state/drafts/planning.draft.md\n')
  const box = section(page, /5\. Synthesize a draft/)
  await box.locator('select').first().selectOption('planning')
  await box.getByPlaceholder('One subject per line — force-includes these dossiers').fill('Ront')
  const fallback = box.getByLabel('Write fallback lines for NPCs without a published dossier')
  await expect(fallback).not.toBeChecked()

  await box.getByRole('button', { name: 'Synthesize planning' }).click()
  await expect(box.getByText('Success')).toBeVisible()
  expect(seen[0].searchParams.has('fallback_npc_lines')).toBe(false)
  expect(seen[0].searchParams.getAll('name')).toEqual(['Ront'])
  expect(seen[0].searchParams.has('parts')).toBe(false)
  expect(seen[0].searchParams.has('world_state')).toBe(false)

  await fallback.check()
  await box.getByRole('button', { name: 'Synthesize planning' }).click()
  await expect.poll(() => seen.length).toBe(2)
  expect(seen[1].searchParams.get('fallback_npc_lines')).toBe('true')

  // Never persisted: a reload starts unchecked again.
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Summary-native' })).toBeVisible()
  await section(page, /5\. Synthesize a draft/).locator('select').first().selectOption('planning')
  await expect(section(page, /5\. Synthesize a draft/)
    .getByLabel('Write fallback lines for NPCs without a published dossier')).not.toBeChecked()
})

test('planning shows the ratified-thread counts of the last build and links to the Threads page', async ({ page }) => {
  await openPage(page)
  await page.route(url => url.pathname === `${BASE}/state`, route => route.fulfill({
    json: {
      ...stateBody,
      threads: {
        present: true, ratified_in_range: 3, open: 2, dormant: 1, unattached: 7, ambiguous: 1, pending_groups: 4,
      },
    },
  }))
  await page.reload()
  const box = section(page, /5\. Synthesize a draft/)
  await expect(box.locator('.threads')).toHaveCount(0) // only planning has the panel
  await box.locator('select').first().selectOption('planning')
  const panel = box.locator('.threads')
  await expect(panel.getByText('3 with notes in range')).toBeVisible()
  await expect(panel.getByText('2 open')).toBeVisible()
  await expect(panel.getByText('1 dormant')).toBeVisible()
  await expect(panel.getByText('7 unratified notes')).toBeVisible()
  await expect(panel.getByText('1 ambiguous name(s)')).toBeVisible()
  await expect(panel.getByText('4 proposal group(s) awaiting a ruling')).toBeVisible()
  await expect(panel.getByRole('link', { name: 'Threads page' })).toHaveAttribute('href', '/grounding/threads')
})

test('planning says so before any build, and a planning refusal lists its NPCs', async ({ page }) => {
  await openPage(page)
  const box = section(page, /5\. Synthesize a draft/)
  await box.locator('select').first().selectOption('planning')
  await expect(box.locator('.threads').getByText('not built yet')).toBeVisible()

  const refusal = [
    "Error: planning's NPC Dossiers need a published, verified dossier for each selected NPC; 1 of 2 have none:",
    '  Ront: not drafted',
    'Draft, verify and publish them, then build again:',
    '  summary_native npc-draft --since 2 --until 5 --name "Ront"',
    '',
  ].join('\n')
  await mockRun(page, 'synth/planning', refusal, 2)
  await page.route(url => url.pathname === `${BASE}/state`, route => route.fulfill({
    json: {
      ...stateBody,
      planning_missing_dossiers: [{ name: 'Ront', state: 'not drafted' }],
      planning_missing_dossiers_refused: true,
    },
  }))
  await box.getByRole('button', { name: 'Synthesize planning' }).click()
  const panel = box.locator('.missing-npcs')
  await expect(panel.getByText('Build refused: 1 selected NPC(s) have no published, verified dossier')).toBeVisible()
  await expect(panel.getByRole('row', { name: /Ront\s+not drafted/ })).toBeVisible()
  // world_state's own list is another file: switching documents does not show planning's refusal there.
  await box.locator('select').first().selectOption('world_state')
  await expect(box.locator('.missing-npcs')).toHaveCount(0)
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

// ── spec 034 US6: one build surface, the one-shot controls removed ──────────

test('no document has a Parts control, an upstream-draft picker or an audit box on its synth step', async ({ page }) => {
  await openPage(page)
  const box = section(page, /5\. Synthesize a draft/)
  for (const doc of ['world_state', 'campaign_state', 'party', 'planning']) {
    await box.locator('select').first().selectOption(doc)
    await expect(box.getByText('Parts', { exact: true })).toHaveCount(0)
    await expect(box.getByText('World-state draft (context)')).toHaveCount(0)
    await expect(box.getByText('Campaign-state draft (context)')).toHaveCount(0)
    await expect(box.getByText('Audit files')).toHaveCount(0)
    // every document has the prose controls, and Annotate follows the step for every document
    await expect(box.getByLabel('Prose effort')).toBeVisible()
    await expect(box.getByLabel('Dump only', { exact: false })).toBeVisible()
    await expect(section(page, /6\. Annotate the .* draft/)).toBeVisible()
  }
})

test('party is a chunked step: its roster, prose model and effort, Dump only and Force are sent; no NPC selection', async ({ page }) => {
  await openPage(page)
  const seen = await mockRun(page, 'synth/party', 'Wrote draft: state/drafts/party.draft.md\n')
  const box = section(page, /5\. Synthesize a draft/)
  await box.locator('select').first().selectOption('party')
  await expect(box.getByText('One call per character, then the overview and the dynamics.')).toBeVisible()
  // party selects no NPCs and has no fallback lines: none of these controls exists for it
  await expect(box.getByText('Named subjects')).toHaveCount(0)
  await expect(box.getByText('Recent chapters')).toHaveCount(0)
  await expect(box.getByText('Recurring minimum')).toHaveCount(0)
  await expect(box.getByLabel('Write fallback lines for NPCs without a published dossier')).toHaveCount(0)

  await box.locator('.path-field', { hasText: 'Party config' }).locator('input').fill('config/party.yaml')
  await box.locator('.field', { hasText: 'Prose model' }).locator('input').fill('claude-opus-5-5')
  await box.getByLabel('Prose effort').selectOption('high')
  await box.getByLabel('Dump only', { exact: false }).check()
  await box.getByLabel('Replace existing reviewed draft (--force)').check()
  await box.getByRole('button', { name: 'Synthesize party' }).click()
  await expect(box.getByText('Success')).toBeVisible()

  expect(seen).toHaveLength(1)
  const q = seen[0].searchParams
  expect(q.get('party_config')).toBe('config/party.yaml')
  expect(q.get('model')).toBe('claude-opus-5-5')
  expect(q.get('claude_code_effort')).toBe('high')
  expect(q.get('dump_only')).toBe('true')
  expect(q.get('force')).toBe('true')
  expect(q.get('since')).toBe('2')
  expect(q.get('until')).toBe('5')
  for (const gone of ['name', 'recent_chapters', 'recurring_min', 'fallback_npc_lines', 'parts', 'world_state',
    'campaign_state', 'audit', 'planning_config']) {
    expect(q.has(gone), gone).toBe(false)
  }
})

test('a plain party run sends only the range: the CLI resolves the roster, the prose block and the budgets', async ({ page }) => {
  await openPage(page)
  const seen = await mockRun(page, 'synth/party')
  const box = section(page, /5\. Synthesize a draft/)
  await box.locator('select').first().selectOption('party')
  await box.getByRole('button', { name: 'Synthesize party' }).click()
  await expect(box.getByText('Success')).toBeVisible()
  expect([...seen[0].searchParams.keys()].sort()).toEqual(['since', 'summaries_dir', 'until'])
})

test('no document ever sends a retired parameter', async ({ page }) => {
  await openPage(page)
  const box = section(page, /5\. Synthesize a draft/)
  for (const doc of ['world_state', 'campaign_state', 'party', 'planning']) {
    const seen = await mockRun(page, `synth/${doc}`)
    await box.locator('select').first().selectOption(doc)
    await box.getByRole('button', { name: `Synthesize ${doc}` }).click()
    await expect(box.getByText('Success')).toBeVisible()
    for (const gone of ['parts', 'world_state', 'campaign_state', 'audit']) {
      expect(seen[0].searchParams.has(gone), `${doc}: ${gone}`).toBe(false)
    }
  }
})

// ── #528: Annotate and the budget panel for party and planning ──────────────

test('Annotate for party runs a dry-run preview and a real run against the party route', async ({ page }) => {
  await openPage(page)
  const seen = await mockRun(page, 'annotate/party', 'annotations: 2 later, 0 since, 1 unverified; 0 removed\n')
  await section(page, /5\. Synthesize a draft/).locator('select').first().selectOption('party')
  const box = section(page, /6\. Annotate the party draft/)
  await box.getByRole('button', { name: 'Preview annotations for party (dry run)' }).click()
  await expect(box.getByText('annotations: 2 later').first()).toBeVisible()
  expect(seen).toHaveLength(1)
  expect(seen[0].searchParams.get('dry_run')).toBe('true')

  await box.getByRole('button', { name: 'Annotate party', exact: true }).click()
  await expect.poll(() => seen.length).toBe(2)
  expect(seen[1].searchParams.has('dry_run')).toBe(false)
  expect(seen[1].searchParams.get('since')).toBe('2')
  expect(seen[1].searchParams.get('until')).toBe('5')
})

test('party and planning each show their own budget panel with the overrun flagged; world_state stays absent until built', async ({ page }) => {
  await openPage(page)
  await page.route(url => url.pathname === `${BASE}/state`, route => route.fulfill({
    json: {
      ...stateBody,
      budgets: {
        world_state: null,
        party: {
          'Party Overview': { budget: 300, words: 241, over: false },
          'Party Dynamics': { budget: 300, words: 355, over: true },
        },
        planning: { 'Active Plots': { budget: 600, words: 640, over: true } },
      },
    },
  }))
  await page.reload()
  const box = section(page, /5\. Synthesize a draft/)
  await expect(box.locator('.budgets')).toHaveCount(0) // world_state has no report yet

  await box.locator('select').first().selectOption('party')
  const party = box.locator('.budgets')
  await expect(party.getByText('Word budgets (last party build; citations not counted)')).toBeVisible()
  await expect(party.getByText('1 over budget')).toBeVisible()
  await expect(party.getByRole('row', { name: /Party Dynamics\s+355\s+300\s+OVER/ })).toBeVisible()
  await expect(party.getByRole('row', { name: /Party Overview\s+241\s+300\s+ok/ })).toBeVisible()

  await box.locator('select').first().selectOption('planning')
  const planning = box.locator('.budgets')
  await expect(planning.getByText('Word budgets (last planning build; citations not counted)')).toBeVisible()
  await expect(planning.getByText('1 over budget')).toBeVisible()
  await expect(planning.getByRole('row', { name: /Active Plots\s+640\s+600\s+OVER/ })).toBeVisible()
  await expect(planning.getByRole('row', { name: /Party Dynamics/ })).toHaveCount(0)

  await box.locator('select').first().selectOption('campaign_state')
  await expect(box.locator('.budgets')).toHaveCount(0)
})

test('the world_state budget panel still reads its own report', async ({ page }) => {
  await openPage(page)
  await page.route(url => url.pathname === `${BASE}/state`, route => route.fulfill({
    json: { ...stateBody, budgets: { world_state: { Locations: { budget: 450, words: 400, over: false } }, party: null, planning: null } },
  }))
  await page.reload()
  const panel = section(page, /5\. Synthesize a draft/).locator('.budgets')
  await expect(panel.getByText('all within budget')).toBeVisible()
  await expect(panel.getByRole('row', { name: /Locations\s+400\s+450\s+ok/ })).toBeVisible()
})

test('authority correction follows the CLI parity flow in five explicit GM actions', async ({ page }) => {
  await openPage(page)
  let initialized = false
  let revision = 1
  let recordRevision = 1
  const calls: { path: string; body: Record<string, unknown> }[] = []
  const envelope = (data: Record<string, unknown> = {}, message = 'ok') => ({
    ok: true, code: 'OK', message, artifacts: [], data,
  })
  const status = () => envelope({ campaign: 'fixture', revision, sha256: `ledger-${revision}`, records: initialized ? 1 : 0, pending_transaction: null })
  const records = () => envelope({ records: initialized ? [{ id: 'earthstone-actor', revision: recordRevision, status: 'draft' }] : [] })

  await page.route(url => url.pathname === `${BASE}/authority/status`, route => {
    if (!initialized) return route.fulfill({ json: envelope({ state: 'absent', campaign: null, revision: null, sha256: null, records: 0, pending_transaction: null }) })
    return route.fulfill({ json: status() })
  })
  await page.route(url => url.pathname === `${BASE}/authority/records`, route => route.fulfill({ json: records() }))
  await page.route(url => url.pathname === `${BASE}/authority/records/earthstone-actor/history`, route => route.fulfill({ json: envelope({ events: [] }) }))
  await page.route(url => url.pathname.startsWith(`${BASE}/authority/`), async route => {
    if (route.request().method() !== 'POST') return route.fallback()
    const path = new URL(route.request().url()).pathname.slice(`${BASE}/authority/`.length)
    const body = route.request().postDataJSON() as Record<string, unknown>
    calls.push({ path, body })
    let result = envelope()
    if (path === 'init') initialized = true
    if (path === 'records/stage') result = envelope({ id: 'stage-1', sha256: 'stage-digest', record: { id: 'earthstone-actor' } }, 'record staged')
    if (path === 'records/stages/stage-1/apply') {
      revision = 2; recordRevision = 2
      result = envelope({ id: 'earthstone-actor', revision: recordRevision, ledger_revision: revision }, 'stage applied')
    }
    if (path === 'records/earthstone-actor/propose') {
      result = envelope({ id: 'proposal-1', proposal_sha256: 'proposal-digest', diff: '--- before\n+++ after\n-Earthstone fell\n+Earthstone was taken' }, 'proposal ready')
    }
    if (path === 'records/earthstone-actor/apply') { revision = 3; result = envelope({ transaction_id: 'tx-1' }, 'correction applied') }
    await route.fulfill({ contentType: 'text/event-stream', body: sse(JSON.stringify(result), 0) })
  })
  await page.reload()

  // The ledger lives on its own Rulings page, off the build flow.
  await page.goto('/grounding/authority')
  const authority = page.locator('[data-test="authority-panel"]')
  await authority.getByRole('button', { name: 'Initialize authority ledger' }).click() // 1
  await expect(authority.getByText('ledger revision 1')).toBeVisible()
  await authority.getByPlaceholder('docs/authority/records/earthstone.yaml').fill('docs/authority/earthstone.yaml')
  await authority.getByRole('button', { name: 'Stage record revision' }).click() // 2
  await authority.getByRole('button', { name: 'Apply staged revision' }).click() // 3
  await expect(authority.getByRole('button', { name: 'Apply staged revision' })).toHaveCount(0)
  await expect(authority.getByRole('row', { name: /earthstone-actor\s+draft\s+2/ })).toBeVisible()
  await authority.getByRole('button', { name: 'Propose source correction' }).click() // 4
  await expect(authority.getByLabel('Exact proposed source diff')).toContainText('Earthstone was taken')
  await authority.getByRole('button', { name: 'Apply displayed correction' }).click() // 5

  expect(calls.map(c => c.path)).toEqual([
    'init', 'records/stage', 'records/stages/stage-1/apply',
    'records/earthstone-actor/propose', 'records/earthstone-actor/apply',
  ])
  expect(calls[4].body.proposal_sha256).toBe('proposal-digest')
})

test('authority keeps stale, recovery, withdrawal, retirement, and proposal binding visible to the GM', async ({ page }) => {
  await openPage(page)
  const calls: { path: string; body: Record<string, unknown> }[] = []
  const envelope = (data: Record<string, unknown> = {}, message = 'ok') => ({ ok: true, code: 'OK', message, artifacts: [], data })
  const recordRows = [
    { id: 'note-a', revision: 3, status: 'applied', classification: 'RULED', audience: 'gm' },
    { id: 'note-b', revision: 1, status: 'active', classification: 'PREP', audience: 'gm' },
  ]
  await page.route(url => url.pathname === `${BASE}/authority/status`, route => route.fulfill({
    json: envelope({ state: 'pending', campaign: 'fixture', revision: 7, sha256: 'ledger-7', records: 2,
      pending_transaction: 'tx-pending', stale_projections: [{ doc: 'planning', draft: 'state/drafts/planning.draft.md', reason: 'authority manifest changed; regenerate with --force' }] }),
  }))
  await page.route(url => url.pathname === `${BASE}/authority/records`, route => route.fulfill({ json: envelope({ records: recordRows }) }))
  await page.route(url => url.pathname.startsWith(`${BASE}/authority/`), async route => {
    if (route.request().method() !== 'POST') return route.fallback()
    const path = new URL(route.request().url()).pathname.slice(`${BASE}/authority/`.length)
    const body = route.request().postDataJSON() as Record<string, unknown>
    calls.push({ path, body })
    const result = path === 'records/note-a/propose'
      ? envelope({ id: 'proposal-a', proposal_sha256: 'proposal-a-sha', diff: '--- before\n+++ after\n-old\n+new' })
      : envelope()
    await route.fulfill({ contentType: 'text/event-stream', body: sse(JSON.stringify(result), 0) })
  })
  await page.reload()

  // The ledger lives on its own Rulings page, off the build flow.
  await page.goto('/grounding/authority')
  const authority = page.locator('[data-test="authority-panel"]')
  await expect(authority.getByText('recovery required')).toBeVisible()
  await expect(authority.getByText('Stale projections: planning: authority manifest changed; regenerate with --force')).toBeVisible()
  await authority.getByRole('button', { name: 'Recover transaction' }).click()
  await authority.getByRole('button', { name: 'Propose source correction' }).first().click()
  await expect(authority.getByLabel('Exact proposed source diff')).toBeVisible()
  await authority.getByRole('button', { name: 'Select' }).nth(1).click()
  await expect(authority.getByLabel('Exact proposed source diff')).toHaveCount(0)
  await expect(authority.getByRole('button', { name: 'Apply displayed correction' })).toHaveCount(0)
  await authority.getByRole('button', { name: 'Select' }).first().click()
  await authority.getByPlaceholder('Reason for requesting a safe reversal').fill('Superseded by table ruling')
  await authority.getByRole('button', { name: 'Request withdrawal' }).click()
  await authority.getByRole('button', { name: 'Select' }).nth(1).click()
  await authority.getByRole('button', { name: 'Retire record' }).click()

  expect(calls.map(call => call.path)).toEqual([
    'transactions/tx-pending/recover', 'records/note-a/propose', 'records/note-a/withdraw', 'records/note-b/retire',
  ])
  expect(calls[2].body.reason).toBe('Superseded by table ruling')
  expect(calls[3].body).toMatchObject({ reason: 'Superseded by table ruling', expected_revision: 1, expected_ledger_sha256: 'ledger-7' })
})

test('authority conflict review invokes the CLI-backed history, dismissal, and human finding controls', async ({ page }) => {
  await openPage(page)
  const calls: { path: string; body: Record<string, unknown> }[] = []
  const envelope = (data: Record<string, unknown> = {}) => ({ ok: true, code: 'OK', message: 'ok', artifacts: [], data })
  await page.route(url => url.pathname === `${BASE}/authority/status`, route => route.fulfill({ json: envelope({ state: 'initialized', campaign: 'fixture', revision: 4, sha256: 'ledger-4', records: 2, conflicts: 1 }) }))
  await page.route(url => url.pathname === `${BASE}/authority/records`, route => route.fulfill({ json: envelope({ records: [] }) }))
  await page.route(url => url.pathname === `${BASE}/authority/conflicts`, route => route.fulfill({ json: envelope({ conflicts: [{ id: 'gate-conflict', basis: 'structured_value', status: 'open', record_ids: ['gate-open', 'gate-closed'], projections: ['planning'], records: [{ id: 'gate-open', source: 'notes/gate.md', anchor: 'gate', normalized_value: 'open', effective: { from_chapter: 1, through_chapter: 3 }, projections: ['planning'] }, { id: 'gate-closed', source: 'notes/gate.md', anchor: 'gate', normalized_value: 'closed', effective: { from_chapter: 1, through_chapter: 3 }, projections: ['planning'] }] }] }) }))
  await page.route(url => url.pathname === `${BASE}/authority/conflicts/gate-conflict/history`, route => route.fulfill({ json: envelope({ events: [] }) }))
  await page.route(url => url.pathname.startsWith(`${BASE}/authority/conflicts/`), async route => {
    if (route.request().method() !== 'POST') return route.fallback()
    calls.push({ path: new URL(route.request().url()).pathname.slice(`${BASE}/authority/`.length), body: route.request().postDataJSON() as Record<string, unknown> })
    await route.fulfill({ contentType: 'text/event-stream', body: sse(JSON.stringify(envelope()), 0) })
  })
  await page.reload()
  // The ledger lives on its own Rulings page, off the build flow.
  await page.goto('/grounding/authority')
  const authority = page.locator('[data-test="authority-panel"]')
  await expect(authority.getByText('gate-conflict')).toBeVisible()
  await expect(authority.getByText(/notes\/gate\.md#gate = open/)).toBeVisible()
  await authority.getByPlaceholder('Reason for requesting a safe reversal').fill('Reviewed as compatible')
  await authority.getByRole('button', { name: 'Dismiss conflict' }).click()
  await authority.getByPlaceholder('contradictory-gate-account').fill('prose-tension')
  await authority.getByPlaceholder('record IDs, one per line').fill('gate-open\ngate-closed')
  await authority.getByRole('button', { name: 'Record conflict' }).click()
  expect(calls).toEqual([
    { path: 'conflicts/gate-conflict/dismiss', body: { reason: 'Reviewed as compatible', expected_ledger_sha256: 'ledger-4' } },
    { path: 'conflicts/identify', body: { id: 'prose-tension', record_ids: ['gate-open', 'gate-closed'], basis: 'human_identified', reason: 'Reviewed as compatible', expected_ledger_sha256: 'ledger-4' } },
  ])
})

test('planning preview makes the reviewed selector set and GM audience repeatable synth arguments', async ({ page }) => {
  await openPage(page)
  const selector = { id: 'gm-notes', path: 'notes/gm/*.md', record_ids: ['note-a'] }
  const previewCalls: Record<string, unknown>[] = []
  await page.route(url => url.pathname === '/api/planning/notes', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json: [selector] })
    return route.fallback()
  })
  await page.route(url => url.pathname === `${BASE}/authority/notes/preview`, async route => {
    previewCalls.push(route.request().postDataJSON() as Record<string, unknown>)
    return route.fulfill({ json: {
      ok: true, code: 'OK', message: 'authority note selection preview', artifacts: [], data: {
        selection_sha256: 'selection-sha', membership_digest: 'members-sha', warnings: ['future plan may be stale'],
        members: [{ selector_id: 'gm-notes', path: 'notes/gm/*.md', resolved_path: '/campaign/notes/gm/plot.md',
          external: true, record_ids: ['note-a'], reason: 'selector:gm-notes', sha256: 'note-sha', records: [{
            id: 'note-a', classification: 'PREP', audience: ['gm'], effective: { horizon: 'future' },
            status: 'active', anchor: 'plot', section_sha256: 'section-sha',
          }] }],
      },
    } })
  })
  await page.reload()
  const seen = await mockRun(page, 'synth/planning')
  const box = section(page, /5\. Synthesize a draft/)
  await box.locator('select').first().selectOption('planning')
  const notes = box.locator('[data-test="authority-note-selection"]')
  await notes.getByRole('button', { name: 'Preview configured note selection' }).click()
  const preview = box.locator('[data-test="authority-note-preview"]')
  await expect(preview.getByLabel('Reviewed selection digest')).toHaveValue('selection-sha')
  await expect(preview.getByText('external')).toBeVisible()
  await expect(preview.getByRole('row', { name: /gm-notes.*note-a.*PREP.*gm.*selector:gm-notes.*note-sha/ })).toBeVisible()
  await expect(preview.getByText('future plan may be stale')).toBeVisible()
  await box.getByRole('button', { name: 'Synthesize planning' }).click()

  expect(previewCalls).toEqual([{ audience: 'gm' }])
  await expect.poll(() => seen.length).toBe(1)
  expect(seen[0].searchParams.getAll('authority_selection')).toEqual(['selection-sha'])
  expect(seen[0].searchParams.get('audience')).toBe('gm')

  // Any path/membership edit discards the reviewed snapshot. The next run
  // cannot reuse a selector set that the GM did not inspect.
  await box.getByLabel('Path for gm-notes').fill('notes/gm/next.md')
  await expect(preview).toHaveCount(0)
  await box.getByRole('button', { name: 'Synthesize planning' }).click()
  await expect.poll(() => seen.length).toBe(2)
  expect(seen[1].searchParams.has('authority_selection')).toBe(false)
  expect(seen[1].searchParams.has('audience')).toBe(false)
})

test('a non-GM coverage refusal is safe and cannot fall back to GM synthesis', async ({ page }) => {
  await openPage(page)
  const selector = { id: 'restricted', path: 'notes/restricted.md' }
  await page.route(url => url.pathname === '/api/planning/notes', route => route.fulfill({ json: [selector] }))
  await page.route(url => url.pathname === `${BASE}/authority/notes/preview`, route => route.fulfill({
    status: 422,
    json: { ok: false, code: 'AUTH_VALIDATION', message: 'non-GM generation is unavailable until authority audience filtering is enabled', artifacts: [], data: {} },
  }))
  await page.reload()
  const box = section(page, /5\. Synthesize a draft/)
  await box.locator('select').first().selectOption('planning')
  const notes = box.locator('[data-test="authority-note-selection"]')
  await notes.locator('select').selectOption('players')
  await expect(box.getByText('Preview complete authorized support for this audience before planning synthesis.')).toBeVisible()
  await notes.getByRole('button', { name: 'Preview configured note selection' }).click()
  await expect(box.getByText('non-GM generation is unavailable until authority audience filtering is enabled')).toBeVisible()
  await expect(box.getByRole('button', { name: 'Synthesize planning' })).toBeDisabled()
  await expect(box.getByText('GM_SECRET_SENTINEL')).toHaveCount(0)
})

test('player and named-character previews run in distinct restricted namespaces', async ({ page }) => {
  await openPage(page)
  const selector = { id: 'restricted', path: 'notes/restricted.md' }
  const previews: string[] = []
  await page.route(url => url.pathname === '/api/planning/notes', route => route.fulfill({ json: [selector] }))
  await page.route(url => url.pathname === `${BASE}/authority/notes/preview`, route => {
    const audience = String((route.request().postDataJSON() as Record<string, unknown>).audience)
    previews.push(audience)
    return route.fulfill({ json: { ok: true, code: 'OK', message: 'authorized selection preview', artifacts: [], data: {
      audience, selection_sha256: `${audience}-selection`, membership_digest: `${audience}-members`, warnings: [],
      members: [{ authorized: true, reason: 'selected support' }],
    } } })
  })
  await page.reload()
  const seen = await mockRun(page, 'synth/planning')
  const box = section(page, /5\. Synthesize a draft/)
  await box.locator('select').first().selectOption('planning')
  const notes = box.locator('[data-test="authority-note-selection"]')

  await notes.locator('select').selectOption('players')
  await notes.getByRole('button', { name: 'Preview configured note selection' }).click()
  await expect(box.locator('[data-test="authority-note-preview"]').getByText('restricted member')).toBeVisible()
  await expect(box.getByRole('button', { name: 'Synthesize planning' })).toBeEnabled()
  await box.getByRole('button', { name: 'Synthesize planning' }).click()
  await notes.locator('select').selectOption('character')
  await notes.getByLabel('Stable character id').fill('sable')
  await expect(box.getByRole('button', { name: 'Synthesize planning' })).toBeDisabled()
  await notes.getByRole('button', { name: 'Preview configured note selection' }).click()
  await expect.poll(() => previews).toEqual(['players', 'character:sable'])
  await expect(box.getByRole('button', { name: 'Synthesize planning' })).toBeEnabled()
  await box.getByRole('button', { name: 'Synthesize planning' }).click()
  await expect.poll(() => seen.length).toBe(2)
  expect(seen.map(call => call.searchParams.get('audience'))).toEqual(['players', 'character:sable'])
  expect(seen.map(call => call.searchParams.get('authority_selection'))).toEqual(['players-selection', 'character:sable-selection'])
  await expect(box.getByText('GM_SECRET_SENTINEL')).toHaveCount(0)
})
