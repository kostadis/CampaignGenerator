import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import DeltaRun from './DeltaRun.vue'

const CHAPTERS = {
  present: [1, 2, 3],
  files: [
    { chapter: 1, path: '001-the-cold-forge.md' },
    { chapter: 2, path: '002-the-ledger.md' },
    { chapter: 3, path: '003-the-new-fire.md' },
  ],
}
const STAGES = [
  { name: 'sources', status: 'complete', artifacts: [{ path: 'docs/summaries/delta/selection.json', sha256: 'abc123' }] },
  { name: 'census', status: 'running', artifacts: [] },
]

interface Call { url: string; method: string; body: any }

function stub(status: any = { status: 'running', stages: STAGES, members: [] }) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const call = { url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined }
    calls.push(call)
    let payload: any = {}
    if (url.includes('/chapters')) payload = CHAPTERS
    else if (url.endsWith('/status')) payload = status
    else if (url.endsWith('/plans') && call.method === 'POST') payload = { plan_id: 'p1' }
    else if (url.endsWith('/npc/publish/preview')) {
      payload = { plan_id: 'p1', preview_sha256: 'sha-preview-1', members: [{ subject: 'Brannoc', slug: 'brannoc' }] }
    } else if (url.endsWith('/npc/publish')) {
      return new Response('event: line\ndata: "published"\n\nevent: exit\ndata: 0\n\n') as Response
    }
    return { ok: true, status: 200, json: async () => payload, text: async () => JSON.stringify(payload) } as Response
  }))
  return calls
}

async function mountWithPlan(status?: any) {
  const calls = stub(status)
  const w = mount(DeltaRun)
  await w.get('[data-testid=plan-id]').setValue('p1')
  await w.get('[data-testid=plan-id]').trigger('change')
  await flushPromises()
  return { w, calls }
}

async function loadChapters(w: ReturnType<typeof mount>) {
  await w.get('[data-testid=summaries-dir]').setValue('docs/summaries')
  await w.get('[data-testid=summaries-dir]').trigger('change')
  await flushPromises()
}

afterEach(() => vi.unstubAllGlobals())

describe('DeltaRun', () => {
  it('renders the stepper from /status with each stage artifact path and sha', async () => {
    const { w, calls } = await mountWithPlan()
    expect(calls.some(c => c.url.endsWith('/plans/p1/status'))).toBe(true)
    const stages = w.findAll('[data-testid=stage]')
    expect(stages.map(s => s.find('.stage-name').text())).toEqual(['sources', 'census'])
    expect(stages[0].text()).toContain('docs/summaries/delta/selection.json')
    expect(stages[0].text()).toContain('abc123')
    expect(w.find('[data-testid=status-banner]').exists()).toBe(false)
  })

  it('select all writes every resolved chapter into the explicit sources list', async () => {
    const calls = stub()
    const w = mount(DeltaRun)
    await loadChapters(w)
    await w.get('[data-testid=select-all]').trigger('click')
    await w.get('[data-testid=product-grounding]').setValue(true)
    await w.get('[data-testid=create-plan]').trigger('click')
    await flushPromises()
    const post = calls.find(c => c.method === 'POST' && c.url.endsWith('/plans'))!
    expect(post.body).toEqual({
      product: ['grounding'],
      sources: [
        'docs/summaries/001-the-cold-forge.md',
        'docs/summaries/002-the-ledger.md',
        'docs/summaries/003-the-new-fire.md',
      ],
    })
    expect(Object.keys(post.body).sort()).toEqual(['product', 'sources'])
  })

  it('sends only the ticked chapters, never an implicit set', async () => {
    const calls = stub()
    const w = mount(DeltaRun)
    await loadChapters(w)
    await w.findAll('[data-testid=chapter]')[2].setValue(true)
    await w.get('[data-testid=product-npc]').setValue(true)
    await w.get('[data-testid=product-grounding]').setValue(true)
    await w.get('[data-testid=stop]').setValue('verify')
    await w.get('[data-testid=create-plan]').trigger('click')
    await flushPromises()
    const post = calls.find(c => c.method === 'POST' && c.url.endsWith('/plans'))!
    expect(post.body.product).toEqual(['npc', 'grounding'])
    expect(post.body.stop).toBe('verify')
    expect(post.body.sources).toEqual(['docs/summaries/003-the-new-fire.md'])
  })

  it('refuses an empty selection: create is disabled and nothing is posted', async () => {
    const calls = stub()
    const w = mount(DeltaRun)
    await loadChapters(w)
    const btn = w.get('[data-testid=create-plan]')
    expect(btn.attributes('disabled')).toBeDefined()
    await btn.trigger('click')
    await flushPromises()
    expect(calls.some(c => c.method === 'POST')).toBe(false)
  })

  it('create stays disabled until a product is chosen, even with chapters selected', async () => {
    const calls = stub()
    const w = mount(DeltaRun)
    await loadChapters(w)
    await w.get('[data-testid=select-all]').trigger('click')
    const btn = w.get('[data-testid=create-plan]')
    expect(btn.attributes('disabled')).toBeDefined()
    await btn.trigger('click')
    expect(calls.some(c => c.method === 'POST')).toBe(false)
    expect((w.get('[data-testid=product-npc]').element as HTMLInputElement).checked).toBe(false)
    await w.get('[data-testid=product-npc]').setValue(true)
    expect(btn.attributes('disabled')).toBeUndefined()
  })

  it.each([
    ['stale', 'stale'],
    ['partial', 'partial'],
    ['recovery_required', 'recovery_required'],
  ])('shows the %s banner on load from /status', async (state, cls) => {
    const { w } = await mountWithPlan({ status: state, stages: STAGES, members: [] })
    const banner = w.get('[data-testid=status-banner]')
    expect(banner.classes()).toContain(`banner-${cls}`)
    expect(banner.text()).toContain(state)
  })

  it('decision buttons send the explicit decision and there are exactly three', async () => {
    const { w, calls } = await mountWithPlan()
    await w.get('[data-testid=assoc-id]').setValue('a1')
    await w.get('[data-testid=proposal-id]').setValue('g1')
    await w.get('[data-testid=reviewer]').setValue('GM Kostadis')
    expect(w.findAll('[data-testid^=assoc-]').filter(b => b.element.tagName === 'BUTTON')).toHaveLength(3)
    await w.get('[data-testid=assoc-discuss]').trigger('click')
    await w.get('[data-testid=proposal-reject]').trigger('click')
    await w.get('[data-testid=proposal-approve]').trigger('click')
    await flushPromises()
    const posts = calls.filter(c => c.method === 'POST')
    expect(posts[0]).toMatchObject({ url: '/api/summary-native/delta/associations/a1/decision', body: { plan: 'p1', decision: 'discuss', reviewer: 'GM Kostadis' } })
    expect(posts[1]).toMatchObject({ url: '/api/summary-native/delta/grounding/proposals/g1/decision', body: { plan: 'p1', decision: 'reject', reviewer: 'GM Kostadis' } })
    expect(posts[2].body).toEqual({ plan: 'p1', decision: 'approve', reviewer: 'GM Kostadis' })
  })

  it('does not send a decision without a reviewer name', async () => {
    localStorage.clear()
    const { w, calls } = await mountWithPlan()
    await w.get('[data-testid=assoc-id]').setValue('a1')
    await w.get('[data-testid=assoc-approve]').trigger('click')
    await w.get('[data-testid=proposal-id]').setValue('g1')
    await w.get('[data-testid=proposal-approve]').trigger('click')
    await flushPromises()
    expect(calls.some(c => c.method === 'POST')).toBe(false)
    expect(w.get('[data-testid=error]').text()).toContain('reviewer')
  })

  it('does not send a decision without an id', async () => {
    const { w, calls } = await mountWithPlan()
    await w.get('[data-testid=assoc-approve]').trigger('click')
    await flushPromises()
    expect(calls.some(c => c.method === 'POST')).toBe(false)
    expect(w.find('[data-testid=error]').exists()).toBe(true)
  })

  it('npc publish refuses an empty member list', async () => {
    const { w, calls } = await mountWithPlan()
    await w.get('[data-testid=npc-publish]').trigger('click')
    await flushPromises()
    expect(calls.some(c => c.url.endsWith('/npc/publish'))).toBe(false)
    expect(w.get('[data-testid=error]').text()).toContain('explicit member list')
  })

  it('npc publish is two steps: preview shows the digest, then publish sends it with the explicit members', async () => {
    const { w, calls } = await mountWithPlan()
    await w.get('[data-testid=member-input]').setValue('Brannoc')
    await w.get('[data-testid=member-input]').trigger('keyup.enter')
    // publishing before a preview is refused and posts nothing
    await w.get('[data-testid=npc-publish]').trigger('click')
    await flushPromises()
    expect(calls.some(c => c.url.endsWith('/npc/publish'))).toBe(false)
    expect(w.get('[data-testid=error]').text()).toContain('preview')

    await w.get('[data-testid=npc-preview]').trigger('click')
    await flushPromises()
    const pv = calls.find(c => c.url.endsWith('/npc/publish/preview'))!
    expect(pv.body).toEqual({ members: ['Brannoc'] })
    expect(w.get('[data-testid=npc-preview-sha]').text()).toBe('sha-preview-1')

    await w.get('[data-testid=npc-publish]').trigger('click')
    await flushPromises()
    const pub = calls.find(c => c.url.endsWith('/npc/publish'))!
    expect(pub.body).toEqual({ members: ['Brannoc'], preview_sha: 'sha-preview-1' })
  })

  it('changing the member list discards the previewed digest', async () => {
    const { w, calls } = await mountWithPlan()
    await w.get('[data-testid=member-input]').setValue('Brannoc')
    await w.get('[data-testid=member-input]').trigger('keyup.enter')
    await w.get('[data-testid=npc-preview]').trigger('click')
    await flushPromises()
    await w.get('[data-testid=member-input]').setValue('Tobin')
    await w.get('[data-testid=member-input]').trigger('keyup.enter')
    expect(w.find('[data-testid=npc-preview-detail]').exists()).toBe(false)
    await w.get('[data-testid=npc-publish]').trigger('click')
    await flushPromises()
    expect(calls.some(c => c.url.endsWith('/npc/publish'))).toBe(false)
  })

  it('attestation requires a reason', async () => {
    const { w, calls } = await mountWithPlan()
    await w.get('[data-testid=attest-subject]').setValue('Brannoc')
    await w.get('[data-testid=attest-publication]').setValue('deadbeef')
    await w.get('[data-testid=attest-submit]').trigger('submit')
    await flushPromises()
    expect(calls.some(c => c.url.includes('/attest'))).toBe(false)
    await w.get('[data-testid=attest-reason]').setValue('no change')
    await w.get('[data-testid=attest-submit]').trigger('submit')
    await flushPromises()
    const post = calls.find(c => c.url.includes('/attest'))!
    expect(post.body).toEqual({ reason: 'no change', publication: 'deadbeef' })
  })
})
