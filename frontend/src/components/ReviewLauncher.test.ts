import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ReviewLauncher from './ReviewLauncher.vue'

// Shape copied from contracts/custody-refusal.md: the trusted local route relays the CLI's `data`.
const MESSAGE = 'REVIEW_STALE_CUSTODY: 1 source file(s) changed; 1 submitted item(s) depend on them; nothing was saved'
const CUSTODY = {
  version: 1, operation: 'decide', review_id: 'review-1', review_generation: 5,
  changed_files: [{ path: 'docs/npcs/summary_native/ch001-086/draft/npc_nug.md', source_id: 'draft-1', role: 'draft',
    state: 'changed', items: [{ item_id: 'npc-signoff-1', npc: 'nug', action: 'signoff_npc_draft' }] }],
  stale_items: [{ item_id: 'npc-signoff-1', npc: 'nug', paths: ['docs/npcs/summary_native/ch001-086/draft/npc_nug.md'] }],
  by_npc: [{ npc: 'nug', item_ids: ['npc-signoff-1'], paths: ['docs/npcs/summary_native/ch001-086/draft/npc_nug.md'] }],
  remedy: { command: 'summary_native review refresh review-1 --expected-generation 5' },
}

function reply(status: number, body: unknown) {
  return Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) })
}

describe('ReviewLauncher custody refusal', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the changed file in the result and the refusal message in the note', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string, init?: { method?: string }) => {
      if (init?.method === 'POST') return reply(409, { ok: false, code: 'REVIEW_STALE_CUSTODY', message: MESSAGE, data: CUSTODY })
      if (String(url).endsWith('/status')) return reply(200, { ok: true, data: { generation: 5 } })
      return reply(200, { ok: true, data: { item_id: 'npc-signoff-1', revision: 1, review_digest: 'a'.repeat(64), decision_revision: 0 } })
    }))
    vi.stubGlobal('crypto', { getRandomValues: (b: Uint8Array) => b })
    const wrapper = mount(ReviewLauncher, { props: { context: 'npc' } })
    const inputs = wrapper.findAll('label').filter(l => /^(Review ID|Item ID)/.test(l.text()))
    for (const label of inputs) await label.find('input').setValue(label.text().startsWith('Review ID') ? 'review-1' : 'npc-signoff-1')
    await wrapper.findAll('button').find(b => b.text() === 'Record decision')!.trigger('click')
    await flushPromises()
    const result = wrapper.find('pre[aria-label="Review command result"]')
    expect(result.exists()).toBe(true)
    expect(result.text()).toContain('docs/npcs/summary_native/ch001-086/draft/npc_nug.md')
    expect(result.text()).toContain('summary_native review refresh review-1 --expected-generation 5')
    expect(wrapper.text()).toContain(MESSAGE)
  })
})

const HASH = 'c'.repeat(64)
// Trimmed from a real `review cards decide --json` envelope's `data` (custody fixture): a supersede, a noop,
// a record, an unmarked card (members is EMPTY for an unmarked card) and a refused card (members carry
// category "refused"; the refusal is on the card). A written plan has the same shape plus `saved` (a list).
const decision = (id: string, verdict: string, disposition: string) => ({ item_id: id, item_revision: 1, verdict, disposition, expected_decision_revision: 0, review_digest: 'd'.repeat(64), note: 'GM card verdict [' + id + ']' })
const PLAN = {
  reviewId: 'npc-review-000000000000', packetId: 'packet-6fd2ef8a7a07f677da29', generation: 1, planSha256: HASH,
  counts: { record: 2, supersede: 1, noop: 1, unmarked: 1, refused: 1 },
  cards: [
    { cardId: 'card-rec', state: 'applied', verdict: 'approve', refusal: null, members: [{ itemId: 'item-rec', category: 'record', disposition: 'accept_no_change', previous: null, decision: decision('item-rec', 'approve', 'accept_no_change') }] },
    { cardId: 'card-sup', state: 'applied', verdict: 'reject', refusal: null, members: [{ itemId: 'item-sup', category: 'supersede', disposition: 'reject_action', previous: { verdict: 'approve', disposition: 'accept_no_change', note: 'GM card verdict [card-sup]: fine', decisionRevision: 1 }, decision: decision('item-sup', 'reject', 'reject_action') }] },
    { cardId: 'card-noop', state: 'applied', verdict: 'approve', refusal: null, members: [{ itemId: 'item-noop', category: 'noop', disposition: 'document_signoff', previous: { verdict: 'approve', disposition: 'document_signoff', note: 'GM card verdict [card-noop]', decisionRevision: 1 }, decision: null }] },
    { cardId: 'card-signed', state: 'applied', verdict: 'approve', refusal: null, withRejectedFindings: [{ itemId: 'item-bad', line: 16, note: 'wrong quote' }, { itemId: 'item-worse', line: null, note: '' }], members: [{ itemId: 'item-signed', category: 'record', disposition: 'document_signoff', previous: null, decision: decision('item-signed', 'approve', 'document_signoff') }] },
    { cardId: 'card-un', state: 'unmarked', verdict: null, refusal: null, members: [] },
    { cardId: 'card-ref', state: 'refused', verdict: 'approve', members: [{ itemId: 'item-ref-1', category: 'refused', disposition: null, previous: null, decision: null }, { itemId: 'item-ref-2', category: 'refused', disposition: null, previous: null, decision: null }], refusal: { code: 'REVIEW_CARDS_MEMBER_STALE', message: 'an item changed since the packet was exported; export a new packet', data: { items: ['item-ref-1'] } } },
  ],
}

function cardsMount() {
  const calls: { url: string; body: any }[] = []
  vi.stubGlobal('fetch', vi.fn((url: string, init?: { method?: string; body?: string }) => {
    const body = init?.body ? JSON.parse(init.body) : undefined
    calls.push({ url: String(url), body })
    if (String(url).endsWith('/cards/export')) return reply(200, { ok: true, code: 'REVIEW_CARDS_EXPORTED', message: 'packet p1: 3 cards (5 members) for review review-1',
      data: { packetId: 'p1', reviewId: 'review-1', cards: 3, members: 5, skippedSignoffs: [{ itemId: 'npc-s', npc: 'nug', code: 'REVIEW_STALE_CUSTODY', message: 'changed' }] } })
    if (String(url).endsWith('/cards/decide')) {
      if (body.write) return reply(200, { ok: true, code: 'REVIEW_CARDS_SAVED', message: 'saved', data: { ...PLAN, saved: [{ request_id: 'cards-packet-6fd2ef8a7a07f677da29-e6cf', events: [{ event_id: 'decision-2d3e-0000', item_id: 'item-rec', decision_revision: 1 }] }] } })
      return reply(200, { ok: true, code: 'REVIEW_CARDS_PLAN', message: 'plan', data: PLAN })
    }
    return reply(200, { ok: true, data: {} })
  }))
  const wrapper = mount(ReviewLauncher, { props: { context: 'npc' } })
  const field = async (label: string, value: string) => {
    const l = wrapper.findAll('label').find(x => x.text().startsWith(label))!
    await l.find('input').setValue(value)
  }
  const button = (name: string) => wrapper.findAll('button').find(b => b.text() === name)!
  return { wrapper, calls, field, button }
}

describe('ReviewLauncher card packet', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('exports a card packet with filters', async () => {
    const { wrapper, calls, field, button } = cardsMount()
    await field('Review ID', 'review-1')
    await field('Item ids', 'a, b  c')
    await field('Action names', 'review_presentation')
    await button('Export card packet').trigger('click')
    await flushPromises()
    expect(calls[0].url).toBe('/api/reviews/review-1/cards/export')
    expect(calls[0].body).toEqual({ items: ['a', 'b', 'c'], actions: ['review_presentation'] })
    const text = wrapper.text()
    expect(text).toContain('p1')
    expect(text).toContain('3 cards')
    expect(text).toContain('5 members')
    expect(text).toContain('npc-s')
    expect(text).toContain('REVIEW_STALE_CUSTODY')
  })

  it('sends empty filters when the inputs are blank', async () => {
    const { calls, field, button } = cardsMount()
    await field('Review ID', 'review-1')
    await button('Export card packet').trigger('click')
    await flushPromises()
    expect(calls[0].body).toEqual({ items: [], actions: [] })
  })

  it('plans then confirms with the plan hash', async () => {
    const { wrapper, calls, field, button } = cardsMount()
    await field('Review ID', 'review-1')
    await field('Decisions file', 'decisions.json')
    expect(button('Confirm and record').attributes('disabled')).toBeDefined()
    await button('Plan').trigger('click')
    await flushPromises()
    expect(calls[0].body).toEqual({ decisions_path: 'decisions.json', reviewer: 'GM', write: false, plan_sha256: null })
    const plan = wrapper.find('[data-test="card-plan"]')
    expect(plan.text()).toContain(HASH)
    for (const heading of ['Record', 'Supersede', 'No change', 'Unmarked', 'Refused']) expect(plan.text()).toContain(heading)
    expect(plan.text()).toContain('item-rec')
    expect(plan.text()).toContain('card-signed: approved with 2 rejected finding(s): item-bad L16, item-worse')
    expect(plan.text()).toMatch(/item-sup.*approve.*accept_no_change.*reject.*reject_action/s)
    expect(plan.text()).toContain('item-ref-1')
    expect(plan.text()).toContain('item-ref-2')
    const section = (name: string) => plan.findAll('h3').find(h => h.text().startsWith(name))!.element.nextElementSibling!.textContent!
    expect(section('Refused')).toContain('item-ref-1')
    expect(section('No change')).toContain('item-noop')
    expect(section('No change')).not.toContain('item-ref')
    expect(section('Record')).toContain('item-rec')
    expect(section('Unmarked')).toBe('card-un')
    expect(plan.text()).toContain('REVIEW_CARDS_MEMBER_STALE')
    expect(button('Confirm and record').attributes('disabled')).toBeUndefined()
    await button('Confirm and record').trigger('click')
    await flushPromises()
    expect(calls[1].body).toEqual({ decisions_path: 'decisions.json', reviewer: 'GM', write: true, plan_sha256: HASH })
    expect(wrapper.text()).toContain('saved')
  })

  it('editing the path or reviewer resets confirm', async () => {
    const { wrapper, field, button } = cardsMount()
    await field('Review ID', 'review-1')
    await field('Decisions file', 'decisions.json')
    await button('Plan').trigger('click')
    await flushPromises()
    expect(button('Confirm and record').attributes('disabled')).toBeUndefined()
    await field('Decisions file', 'other.json')
    expect(button('Confirm and record').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-test="card-plan"]').exists()).toBe(false)
    await field('Decisions file', 'decisions.json')
    await button('Plan').trigger('click')
    await flushPromises()
    await field('Reviewer (card decisions)', 'Someone')
    expect(button('Confirm and record').attributes('disabled')).toBeDefined()
  })

  it('shows a refusal like the CLI', async () => {
    const message = 'REVIEW_CARDS_PACKET_STALE: the review moved'
    vi.stubGlobal('fetch', vi.fn(() => reply(409, { ok: false, code: 'REVIEW_CARDS_PACKET_STALE', message, data: { packetId: 'p1', generation: 7 } })))
    const wrapper = mount(ReviewLauncher, { props: { context: 'npc' } })
    await wrapper.findAll('label').find(l => l.text().startsWith('Review ID'))!.find('input').setValue('review-1')
    await wrapper.findAll('button').find(b => b.text() === 'Export card packet')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain(message)
    expect(wrapper.find('pre[aria-label="Review command result"]').text()).toContain('"generation": 7')
  })
})
