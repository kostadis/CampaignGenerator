import { expect, test, type Page } from '@playwright/test'
import { installAppShellMocks } from './fixtures/appShell'

// Spec 034 (chunked party and planning), US3, T031. Every API route is mocked: the page builds the
// documented requests and renders what the server reports (Principle VI/IX).
// Contract: specs/034-chunked-party-planning/contracts/http.md.
//
// The flow under test is propose -> edit -> ratify -> refresh, and that there is NO one-click accept:
// the editor starts from GET /threads/plan and what is written is the plan the GM posts.

const API = '/api/projections/threads'

const CARVER = 'g-111111111111'
const RING = 'g-222222222222'

const m = (id: string, chapter: number, tag: string, name: string, text: string) => ({
  id, chapter, tag, name, text, cite: `[ch ${String(chapter).padStart(3, '0')} / ${String(chapter).padStart(3, '0')}.01]`,
})
const N1 = m('n-0000000001', 2, 'OPENED', "The Carver's march", 'A horde is spoken of in whispers.')
const N2 = m('n-0000000002', 3, 'ADVANCED', 'Carver march', 'Daz counts the banners from the ridge.')
const N3 = m('n-0000000003', 4, 'ADVANCED', "The Carver's march", 'The march breaks against the gate.')
const N4 = m('n-0000000004', 2, 'OPENED', 'The signet ring', 'Ilvara leaves a signet ring at the fire.')

const group = (key: string, kind: string, title: string, members: unknown[], status = 'pending', extra = {}) => ({
  key, kind, title, members, status, source: 'summary_native ch002-004 run R1', ...extra,
})

const plan = {
  id: 'the-carvers-march',
  title: "The Carver's march",
  status: 'open',
  opened: 2,
  aliases_add: ['Carver march'],
  members: [N1.id, N2.id, N3.id],
  log: [
    { chapter: 2, change: 'opened', summary: N1.text, cite: N1.cite },
    { chapter: 3, change: 'advanced', summary: N2.text, cite: N2.cite },
    { chapter: 4, change: 'advanced', summary: N3.text, cite: N3.cite },
  ],
}

/** An SSE body: one data frame per text, then the `done` event with the return code. */
function sse(text: string, returncode: number): string {
  return `data: ${JSON.stringify(text)}\n\nevent: done\ndata: ${JSON.stringify({ returncode })}\n\n`
}

interface World {
  proposals: unknown[]
  runs: URL[]
  planKeys: string[]
  ratifies: Record<string, any>[]
  rules: Record<string, any>[]
}

/** The mocked server. `proposals` is what the proposals file holds; it changes only when a write route is hit. */
async function openPage(page: Page): Promise<World> {
  const world: World = { proposals: [], runs: [], planKeys: [], ratifies: [], rules: [] }
  await installAppShellMocks(page)
  await page.route('**/api/grounding/config', route => route.fulfill({
    json: { summary_native: { summaries_dir: 'docs/summaries', range_since: 2, range_until: 4 } },
  }))
  await page.route(url => url.pathname === `${API}/registry`, route => route.fulfill({
    json: { version: 1, threads: [], count: 0 },
  }))
  await page.route(url => url.pathname === `${API}/check`, route => route.fulfill({ json: { threads: 0, problems: [] } }))
  await page.route(url => url.pathname === `${API}/proposals`, route => route.fulfill({
    json: { proposals: world.proposals, counts: {} },
  }))
  await page.route(url => url.pathname === `${API}/run/group-propose`, route => {
    world.runs.push(new URL(route.request().url()))
    // The CLI has written the proposals by the time the stream ends.
    world.proposals = [
      group(CARVER, 'new', "The Carver's march", [N3, N1, N2].sort((a, b) => a.chapter - b.chapter)),
      group(RING, 'single', 'The signet ring', [N4]),
    ]
    return route.fulfill({
      status: 200, contentType: 'text/event-stream', headers: { 'Cache-Control': 'no-cache' },
      body: sse('threads: 4 notes — 0 attached to 0 ratified threads, 4 unattached → 2 group proposals (1 single), 0 dropped\n', 0),
    })
  })
  await page.route(url => url.pathname === `${API}/plan`, route => {
    world.planKeys.push(new URL(route.request().url()).searchParams.get('key') ?? '')
    return route.fulfill({ json: plan })
  })
  await page.route(url => url.pathname === `${API}/ratify`, route => {
    const body = route.request().postDataJSON()
    world.ratifies.push(body)
    const covered: string[] = body.members
    const left = [N1, N2, N3].filter(n => !covered.includes(n.id))
    world.proposals = [
      group(CARVER, 'new', "The Carver's march", [N1, N2, N3].filter(n => covered.includes(n.id)), 'ratified',
        { ruled_thread: body.id || 'the-carvers-march' }),
      ...(left.length ? [group('g-333333333333', 'single', left[0].name, left, 'pending')] : []),
      group(RING, 'single', 'The signet ring', [N4]),
    ]
    return route.fulfill({ json: { ok: true, output: `ok: ratified ${body.key}` } })
  })
  await page.route(url => url.pathname === `${API}/rule`, route => {
    const body = route.request().postDataJSON()
    world.rules.push(body)
    world.proposals = (world.proposals as any[]).map(p => (p.key === body.key ? { ...p, status: body.status } : p))
    return route.fulfill({ json: { ok: true, output: `ok: ${body.key} -> ${body.status}` } })
  })
  await page.goto('/grounding/threads')
  await expect(page.getByRole('heading', { name: 'Threads', exact: true })).toBeVisible()
  return world
}

const card = (page: Page, key: string) => page.locator(`.group-card[data-key="${key}"]`)

test('the range is prefilled from the summary-native config, and Run sends exactly that range', async ({ page }) => {
  const world = await openPage(page)
  await expect(page.getByLabel('First chapter')).toHaveValue('2')
  await expect(page.getByLabel('Last chapter')).toHaveValue('4')
  await expect(page.getByText('No group proposals yet')).toBeVisible()

  await page.getByRole('button', { name: 'Run', exact: true }).click()
  await expect(card(page, CARVER)).toBeVisible()
  await expect(card(page, RING)).toBeVisible()

  expect(world.runs).toHaveLength(1)
  const q = world.runs[0].searchParams
  expect(q.get('since')).toBe('2')
  expect(q.get('until')).toBe('4')
  // Blank fields and the unchecked dump are not sent: the CLI resolves its own defaults.
  for (const name of ['model', 'claude_code_effort', 'max_input_chars', 'dump_only']) expect(q.has(name)).toBe(false)
})

test('Run is refused in the page when no range is chosen, and Dump sends dump_only', async ({ page }) => {
  const world = await openPage(page)
  await page.getByLabel('First chapter').fill('')
  await page.getByRole('button', { name: 'Run', exact: true }).click()
  await expect(page.getByText('Choose the first and last chapter first')).toBeVisible()
  expect(world.runs).toHaveLength(0)

  await page.getByLabel('First chapter').fill('3')
  await page.getByLabel('Model').fill('claude-opus-5-5')
  await page.getByLabel('Effort').selectOption('high')
  await page.getByLabel('Max input characters').fill('5000')
  await page.getByRole('button', { name: 'Dump prompts only' }).click()
  await expect.poll(() => world.runs.length).toBe(1)
  const q = world.runs[0].searchParams
  expect(q.get('since')).toBe('3')
  expect(q.get('dump_only')).toBe('true')
  expect(q.get('model')).toBe('claude-opus-5-5')
  expect(q.get('claude_code_effort')).toBe('high')
  expect(q.get('max_input_chars')).toBe('5000')
})

test('a group card shows its kind, title and every member with chapter, tag, name, text and citation', async ({ page }) => {
  await openPage(page)
  await page.getByRole('button', { name: 'Run', exact: true }).click()
  const c = card(page, CARVER)
  await expect(c.getByText('new', { exact: true })).toBeVisible()
  await expect(c.getByText("The Carver's march").first()).toBeVisible()
  const items = c.locator('.evidence li')
  await expect(items).toHaveCount(3)
  await expect(items.first()).toContainText('ch2')
  await expect(items.first()).toContainText('OPENED')
  await expect(items.first()).toContainText('A horde is spoken of in whispers.')
  await expect(items.first()).toContainText('[ch 002 / 002.01]')
  await expect(card(page, RING).getByText('single', { exact: true })).toBeVisible()
})

test('there is no one-click accept: ratifying starts from /threads/plan and posts only what was edited', async ({ page }) => {
  const world = await openPage(page)
  await page.getByRole('button', { name: 'Run', exact: true }).click()
  const c = card(page, CARVER)
  await expect(c).toBeVisible()
  await expect(c.getByRole('button', { name: /accept/i })).toHaveCount(0)

  await c.getByRole('button', { name: 'Ratify…' }).click()
  await expect(c.getByLabel('Thread title')).toHaveValue("The Carver's march")
  expect(world.planKeys).toEqual([CARVER])
  expect(world.ratifies).toHaveLength(0) // opening the editor writes nothing

  // The GM edits: a new title, one more alias, a corrected summary, and splits the last note off.
  await c.getByLabel('Thread title').fill('The march of the Carver')
  await c.getByLabel('Aliases').fill('Carver march\nthe Carver')
  await c.locator('input[aria-label="Log summary"]').first().fill('Edited by the GM.')
  await c.getByLabel("Include The Carver's march ch4").uncheck()
  await expect(c.getByText('1 note(s) stay behind as a new pending group.')).toBeVisible()
  await expect(c.locator('.logrow input[aria-label="Log chapter"]')).toHaveCount(2) // the split note's row is gone
  expect(world.ratifies).toHaveLength(0)

  await c.getByRole('button', { name: 'Confirm' }).click()
  await expect.poll(() => world.ratifies.length).toBe(1)
  const body = world.ratifies[0]
  expect(body.key).toBe(CARVER)
  expect(body.title).toBe('The march of the Carver')
  expect(body.status).toBe('open')
  expect(body.opened).toBe(2)
  expect(body.members).toEqual([N1.id, N2.id]) // a subset: N3 was split off
  expect(body.aliases_add).toEqual(['Carver march', 'the Carver'])
  expect(body.log).toEqual([
    { chapter: 2, change: 'opened', summary: 'Edited by the GM.', cite: N1.cite },
    { chapter: 3, change: 'advanced', summary: N2.text, cite: N2.cite },
  ])
  expect('thread' in body).toBe(false)
})

test('after ratifying, the page refreshes from the server: the ratified group leaves Pending and the split-off note is its own card', async ({ page }) => {
  const world = await openPage(page)
  await page.getByRole('button', { name: 'Run', exact: true }).click()
  const c = card(page, CARVER)
  await c.getByRole('button', { name: 'Ratify…' }).click()
  await c.getByLabel("Include The Carver's march ch4").uncheck()
  await c.getByRole('button', { name: 'Confirm' }).click()
  await expect.poll(() => world.ratifies.length).toBe(1)

  await expect(card(page, CARVER)).toHaveCount(0) // no longer pending
  await expect(card(page, 'g-333333333333')).toBeVisible() // the remainder, with its own key
  await expect(card(page, 'g-333333333333').locator('.evidence li')).toHaveCount(1)
  await expect(card(page, RING)).toBeVisible()

  await page.getByLabel('Show groups').selectOption('ratified')
  await expect(card(page, CARVER)).toBeVisible()
  await expect(card(page, CARVER)).toContainText('ratified')
  await expect(card(page, CARVER).locator('.evidence li')).toHaveCount(2)
})

test('an engine refusal is shown verbatim and the editor stays open', async ({ page }) => {
  await openPage(page)
  // Registered after openPage's own ratify stub, so this one wins (the most recent matching route does).
  await page.route(url => url.pathname === `${API}/ratify`, route => route.fulfill({
    status: 400, contentType: 'application/json',
    body: JSON.stringify({ detail: "error: alias 'Carver march' collides with thread 'old'" }),
  }))
  await page.getByRole('button', { name: 'Run', exact: true }).click()
  const c = card(page, CARVER)
  await c.getByRole('button', { name: 'Ratify…' }).click()
  await c.getByRole('button', { name: 'Confirm' }).click()
  await expect(c.getByText("alias 'Carver march' collides with thread 'old'")).toBeVisible()
  await expect(c.getByLabel('Thread title')).toBeVisible()
})

test('Confirm is disabled when every note is unticked', async ({ page }) => {
  await openPage(page)
  await page.getByRole('button', { name: 'Run', exact: true }).click()
  const c = card(page, CARVER)
  await c.getByRole('button', { name: 'Ratify…' }).click()
  for (const label of ["Include The Carver's march ch2", 'Include Carver march ch3', "Include The Carver's march ch4"]) {
    await c.getByLabel(label).uncheck()
  }
  await expect(c.getByRole('button', { name: 'Confirm' })).toBeDisabled()
})

test('Reject and Defer rule by key, one group per act', async ({ page }) => {
  const world = await openPage(page)
  await page.getByRole('button', { name: 'Run', exact: true }).click()

  const ring = card(page, RING)
  await ring.getByRole('button', { name: 'Reject' }).click()
  await ring.getByLabel('Note').fill('not a plot')
  await ring.getByRole('button', { name: 'Confirm' }).click()
  await expect.poll(() => world.rules.length).toBe(1)
  expect(world.rules[0]).toEqual({ key: RING, status: 'rejected', note: 'not a plot' })
  await expect(card(page, RING)).toHaveCount(0) // rejected groups leave the Pending view

  await card(page, CARVER).getByRole('button', { name: 'Defer' }).click()
  await card(page, CARVER).getByRole('button', { name: 'Confirm' }).click()
  await expect.poll(() => world.rules.length).toBe(2)
  expect(world.rules[1]).toEqual({ key: CARVER, status: 'deferred' })
  expect(world.rules.every(r => !('norm' in r))).toBe(true)
})

test('a re-offered note says why it is back and its editor defaults to continuing the thread it left (#525)', async ({ page }) => {
  const world = await openPage(page)
  const REOFFER = 'g-444444444444'
  await page.route(url => url.pathname === `${API}/registry`, route => route.fulfill({
    json: { version: 1, threads: [{ id: 'the-carvers-march', title: "The Carver's march", status: 'open', aliases: [], log: [] }], count: 1 },
  }))
  await page.route(url => url.pathname === `${API}/plan`, route => route.fulfill({
    json: {
      thread: 'the-carvers-march', aliases_add: ['Carver march'], members: [N2.id],
      log: [{ chapter: 3, change: 'advanced', summary: N2.text, cite: N2.cite }],
    },
  }))
  world.proposals = [
    group(REOFFER, 'single', 'Carver march', [N2], 'pending', { reoffer: { from_group: CARVER, thread: 'the-carvers-march' } }),
    group(RING, 'single', 'The signet ring', [N4]),
  ]
  await page.reload()
  const c = card(page, REOFFER)
  await expect(c.locator('.reoffer')).toContainText("alias removed from The Carver's march")
  await expect(card(page, RING).locator('.reoffer')).toHaveCount(0) // an ordinary single says nothing

  await c.getByRole('button', { name: 'Ratify…' }).click()
  await expect(c.getByLabel('Continues thread')).toHaveValue('the-carvers-march')
  await expect(c.getByLabel('Thread title')).toHaveCount(0) // not a new thread
  await expect(c.getByLabel('Aliases')).toHaveValue('Carver march') // the alias that was removed comes back
  await c.getByRole('button', { name: 'Confirm' }).click()
  await expect.poll(() => world.ratifies.length).toBe(1)
  expect(world.ratifies[0].thread).toBe('the-carvers-march')
  expect(world.ratifies[0].aliases_add).toEqual(['Carver march'])
})

test('unticking a note removes the name only it carries from the alias box; a name a ticked note shares stays (#529)', async ({ page }) => {
  const world = await openPage(page)
  // The plan the engine derives lists every member's name, the title's own spelling included.
  await page.route(url => url.pathname === `${API}/plan`, route => route.fulfill({
    json: { ...plan, aliases_add: ["The Carver's march", 'Carver march'] },
  }))
  await page.getByRole('button', { name: 'Run', exact: true }).click()
  const c = card(page, CARVER)
  await c.getByRole('button', { name: 'Ratify…' }).click()
  const aliases = c.getByLabel('Aliases')
  await expect(aliases).toHaveValue("The Carver's march\nCarver march")

  // ch3 is the only "Carver march" note: its name leaves the box.
  await c.getByLabel('Include Carver march ch3').uncheck()
  await expect(aliases).toHaveValue("The Carver's march")
  // ch4 shares "The Carver's march" with the still-ticked ch2: the name stays.
  await c.getByLabel("Include The Carver's march ch4").uncheck()
  await expect(aliases).toHaveValue("The Carver's march")
  // ticking ch3 again puts its name back; unticking the last carrier of a name removes it.
  await c.getByLabel('Include Carver march ch3').check()
  await expect(aliases).toHaveValue("The Carver's march\nCarver march")
  await c.getByLabel('Include Carver march ch3').uncheck()
  await c.getByLabel("Include The Carver's march ch2").uncheck()
  await c.getByLabel("Include The Carver's march ch4").check()
  await expect(aliases).toHaveValue("The Carver's march") // ch4 carries it now

  await c.getByRole('button', { name: 'Confirm' }).click()
  await expect.poll(() => world.ratifies.length).toBe(1)
  expect(world.ratifies[0].members).toEqual([N3.id])
  expect(world.ratifies[0].aliases_add).toEqual(["The Carver's march"])
})

test('a ratified thread lists the notes a split held out of it, by chapter and name when the proposal still has them (#529)', async ({ page }) => {
  const world = await openPage(page)
  await page.route(url => url.pathname === `${API}/registry`, route => route.fulfill({
    json: {
      version: 1, count: 2,
      threads: [
        { id: 'the-carvers-march', title: "The Carver's march", status: 'open', aliases: ['Carver march'], log: [],
          excluded_notes: [N3.id, 'n-reextracted'] },
        { id: 'plain', title: 'A plain thread', status: 'open', aliases: [], log: [] },
      ],
    },
  }))
  world.proposals = [group('g-333333333333', 'single', N3.name, [N3], 'pending')]
  await page.reload()
  const held = page.locator('.thread', { hasText: "The Carver's march" }).locator('.excluded')
  await expect(held).toContainText('Held out by a split')
  await expect(held).toContainText(`ch4 The Carver's march (${N3.id})`)
  await expect(held).toContainText('n-reextracted') // no proposal carries it: the bare id
  await expect(page.locator('.thread', { hasText: 'A plain thread' }).locator('.excluded')).toHaveCount(0)
})

test('a group holding notes a thread excluded says so, and a thread lists the notes pinned to it by id (#529)', async ({ page }) => {
  const world = await openPage(page)
  await page.route(url => url.pathname === `${API}/registry`, route => route.fulfill({
    json: {
      version: 1, count: 1,
      threads: [{ id: 'the-carvers-march', title: "The Carver's march", status: 'open', aliases: [], log: [],
        excluded_notes: [N3.id], included_notes: [N2.id] }],
    },
  }))
  world.proposals = [
    group('g-555555555555', 'continues', '', [N3], 'pending', { thread: 'the-carvers-march', split_off: { thread: 'the-carvers-march', notes: [N3.id] } }),
    group(RING, 'single', 'The signet ring', [N4]),
    group('g-666666666666', 'single', 'Carver march', [N2], 'ratified', { ruled_thread: 'the-carvers-march' }),
  ]
  await page.reload()
  await expect(card(page, 'g-555555555555').locator('.split-off')).toContainText("you split off The Carver's march")
  await expect(card(page, 'g-555555555555').locator('.split-off')).toContainText('lifts the')
  await expect(card(page, RING).locator('.split-off')).toHaveCount(0)
  const thread = page.locator('.thread', { hasText: "The Carver's march" })
  await expect(thread.locator('.included')).toContainText('Pinned by id')
  await expect(thread.locator('.included')).toContainText('ch3 Carver march')
})
