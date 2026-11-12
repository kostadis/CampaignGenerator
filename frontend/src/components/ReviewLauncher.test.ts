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
