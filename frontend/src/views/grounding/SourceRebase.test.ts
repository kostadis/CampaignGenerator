import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import SourceRebase from './SourceRebase.vue'

const INSPECT = {
  ok: true, code: 'OK', message: 'm',
  data: {
    checked: 2,
    stale: [
      { chapter: 3, path: 'docs/summaries/003-a.md', expected_sha256: 'e3', actual_sha256: 'a3', pinned_by: 'g1',
        old_bytes: [{ provider: 'git', available: true, detail: 'commit abc' }] },
      { chapter: 4, path: 'docs/summaries/004-b.md', expected_sha256: 'e4', actual_sha256: 'a4', pinned_by: 'g1', old_bytes: [] },
    ],
  },
}
const SHOW = {
  ok: true, code: 'OK', message: 'm',
  data: {
    plan_id: 'r1',
    sources: [{ chapter: 3, path: 'docs/summaries/003-a.md', diff: '-old\n+new' }],
    affected_lines: [{ line_id: 'L1', document: 'world_state', line_no: 4, citation: '[ch 3 / 003.01]', chapter: 3, entry: '003.01', reason: 'changed', origin: 'baseline', state: 'unruled' }],
    unknown_members: [{ member: 'Brannoc', reason: 'no_citations' }],
    followup_consumers: [], decisions: [],
  },
}

interface Call { url: string; method: string; body: any }

function stub() {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const call = { url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined }
    calls.push(call)
    let payload: any = { ok: true }
    if (url.includes('/rebase/inspect')) payload = INSPECT
    else if (url.endsWith('/rebase') && call.method === 'POST') payload = { ok: true, data: { plan_id: 'r1' } }
    else if (url.endsWith('/rebase/r1')) payload = SHOW
    return { ok: true, status: 200, json: async () => payload, text: async () => JSON.stringify(payload) } as Response
  }))
  return calls
}

async function inspected() {
  const calls = stub()
  const w = mount(SourceRebase, { global: { stubs: { 'router-link': true } } })
  await w.get('[data-testid=inspect]').trigger('click')
  await flushPromises()
  return { w, calls }
}

async function prepared() {
  const ctx = await inspected()
  await ctx.w.findAll('[data-testid=stale-source]')[0].setValue(true)
  await ctx.w.get('[data-testid=prepare]').trigger('click')
  await flushPromises()
  return ctx
}

afterEach(() => vi.unstubAllGlobals())

describe('SourceRebase', () => {
  it('preselects nothing and disables Prepare while the selection is empty', async () => {
    const { w } = await inspected()
    const boxes = w.findAll('[data-testid=stale-source]')
    expect(boxes).toHaveLength(2)
    expect(boxes.every(b => !(b.element as HTMLInputElement).checked)).toBe(true)
    expect(w.get('[data-testid=prepare]').attributes('disabled')).toBeDefined()
    await boxes[0].setValue(true)
    expect(w.get('[data-testid=prepare]').attributes('disabled')).toBeUndefined()
    await boxes[0].setValue(false)
    expect(w.get('[data-testid=prepare]').attributes('disabled')).toBeDefined()
  })

  it('POSTs an explicit sources list', async () => {
    const { calls } = await prepared()
    const post = calls.find(c => c.method === 'POST' && c.url.endsWith('/rebase'))!
    expect(post.body.sources).toEqual(['docs/summaries/003-a.md'])
    expect(post.body.sources).not.toContain('docs/summaries/004-b.md')
  })

  it('shows diff, affected lines and unknown members after prepare', async () => {
    const { w } = await prepared()
    expect(w.get('[data-testid=source-diff]').text()).toContain('+new')
    expect(w.get('[data-testid=affected-lines]').text()).toContain('L1')
    expect(w.get('[data-testid=unknown-members]').text()).toContain('Brannoc')
  })

  it('preselects no decision', async () => {
    const { w } = await prepared()
    const radios = w.findAll('input[type=radio]')
    expect(radios.length).toBeGreaterThan(0)
    expect(radios.every(r => !(r.element as HTMLInputElement).checked)).toBe(true)
    expect(w.get('[data-testid=decide]').attributes('disabled')).toBeDefined()
  })

  it('requires a reviewer to record decisions', async () => {
    const { w, calls } = await prepared()
    await w.get('[data-testid=src-3-reject]').setValue(true)
    // a decision is chosen but no reviewer: the button stays disabled and nothing is sent
    expect(w.get('[data-testid=decide]').attributes('disabled')).toBeDefined()
    await w.get('[data-testid=decide]').trigger('click')
    expect(calls.some(c => c.url.endsWith('/decisions'))).toBe(false)
    await w.get('[data-testid=reviewer]').setValue('gm')
    expect(w.get('[data-testid=decide]').attributes('disabled')).toBeUndefined()
    await w.get('[data-testid=decide]').trigger('click')
    await flushPromises()
    const post = calls.find(c => c.url.endsWith('/rebase/r1/decisions'))!
    expect(post.body.reviewer).toBe('gm')
    expect(post.body.source_decisions).toEqual({ '3': 'reject' })
    expect(post.body.member_decisions).toEqual({})
  })

  it('a repair without a reviewer is refused in the page', async () => {
    const { w, calls } = await prepared()
    await w.get('[data-testid=repair-form]').trigger('submit')
    expect(w.get('[data-testid=error]').text()).toContain('reviewer')
    expect(calls.some(c => c.url.endsWith('/repairs'))).toBe(false)
  })

  it('deep-links publish and rebind steps to the incremental update page with ?plan=', async () => {
    const calls = stub()
    void calls
    const w = mount(SourceRebase, { global: { stubs: { 'router-link': { props: ['to'], template: '<a><slot /></a>' } } } })
    await w.get('[data-testid=inspect]').trigger('click')
    await flushPromises()
    await w.get('[data-testid=for-plan]').setValue('plan-pending')
    await w.findAll('[data-testid=stale-source]')[0].setValue(true)
    await w.get('[data-testid=prepare]').trigger('click')
    await flushPromises()
    expect((w.getComponent('[data-testid=delta-link]') as any).props('to')).toEqual({ name: 'grounding-delta', query: { plan: 'r1' } })
    expect((w.getComponent('[data-testid=pending-link]') as any).props('to')).toEqual({ name: 'grounding-delta', query: { plan: 'plan-pending' } })
  })
})
