import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import { ref } from 'vue'

vi.mock('./useEnsembleRun', () => ({
  useEnsembleRun: () => ({
    output: ref(''), status: ref('idle'), returnCode: ref(null), command: ref(''),
    run: vi.fn(), abort: vi.fn(),
  }),
  fetchEnsembleConfig: vi.fn(async () => ({
    chapters_selected: [],
    extract: { backend: 'anthropic' },
    synthesize: { backend: 'anthropic' },
    paths: { inventory: '', merged_out: 'docs/ensemble/merged.json' },
    tuning: {},
    merge: {},
    planning: { synth_mode: 'config', npc: [], arc_scores: [], context: [], depth: 'scene', force_include: [] },
  })),
  saveEnsembleConfig: vi.fn(async () => ({})),
  fetchRegistrySummary: vi.fn(async () => ({ found: false, error: null })),
}))

import EnsembleSynthesize from './EnsembleSynthesize.vue'

// The real refusal body from server/routers/ensemble.py's retired /promote.
const REFUSAL = {
  ok: false,
  code: 'PROMOTION_WHOLE_BUNDLE_REQUIRED',
  message: 'Per-document promotion is retired: live grounding is published only as a whole reviewed bundle. '
    + 'Preview and publish it with `summary_native promote ...`.',
  artifacts: [],
  data: { promotion_path: '/api/grounding/summary-native/promotion/preview', command: 'summary_native promote' },
}

function stubFetch() {
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    calls.push(url)
    if (url.endsWith('/api/ensemble/promote')) {
      return { ok: false, status: 409, text: async () => JSON.stringify(REFUSAL), json: async () => REFUSAL } as Response
    }
    return { ok: true, status: 200, json: async () => ({}) } as Response
  }))
  return calls
}

function mountPage() {
  return mount(EnsembleSynthesize, {
    global: {
      plugins: [createTestingPinia({ createSpy: vi.fn })],
      stubs: { RouterLink: { template: '<a><slot /></a>' }, StreamOutput: true, EnsemblePlanningFields: true, PathField: true },
    },
  })
}

afterEach(() => vi.unstubAllGlobals())

describe('EnsembleSynthesize per-document promote (#548 FR-003)', () => {
  it('shows the whole-bundle refusal and reports nothing as promoted', async () => {
    const calls = stubFetch()
    const confirmSpy = vi.fn(() => true)
    vi.stubGlobal('confirm', confirmSpy)
    const wrapper = mountPage()
    await flushPromises()

    await wrapper.find('[data-test="promote-world_state"]').trigger('click')
    await flushPromises()

    expect(calls.some(url => url.endsWith('/api/ensemble/promote'))).toBe(true)
    const refusal = wrapper.find('[data-test="promote-refusal"]')
    expect(refusal.exists()).toBe(true)
    expect(refusal.text()).toContain('PROMOTION_WHOLE_BUNDLE_REQUIRED')
    expect(refusal.text()).toContain('summary_native promote')
    // No success path: the page never announces a change after a promote click.
    expect(wrapper.emitted('changed')).toBeUndefined()
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it('points the GM at the Summary-native Promotion panel and keeps the read-only diff', async () => {
    stubFetch()
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('Summary-native Promotion')
    expect(wrapper.text()).toContain('Diff vs live')
  })
})
