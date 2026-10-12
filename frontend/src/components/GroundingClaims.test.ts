import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import GroundingClaims from './GroundingClaims.vue'

function mountPanel(reviewId?: string) {
  return mount(GroundingClaims, {
    props: { since: 1, until: 3, ...(reviewId === undefined ? {} : { reviewId }) },
    global: { plugins: [createTestingPinia({ createSpy: vi.fn, initialState: { config: {
      groundingConfig: { summary_native: { out_root: 'campaign/custom_root' } },
    } } })] },
  })
}

function stubFetch() {
  const bodies: any[] = []
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
    bodies.push(JSON.parse(String(init?.body ?? '{}')))
    return { ok: true, status: 200, json: async () => ({ ok: true, code: 'OK', message: 'selected', data: { selection: null } }) } as Response
  }))
  return bodies
}

afterEach(() => vi.unstubAllGlobals())

describe('GroundingClaims', () => {
  it('starts with no review id (the CLI declares no default) and requires one', () => {
    const wrapper = mountPanel()
    const review = wrapper.find('[data-test="claims-review-id"]')
    expect((review.element as HTMLInputElement).value).toBe('')
    expect(wrapper.html()).not.toContain('claims-review"')
    expect(wrapper.text()).toContain('there is no default review')
  })

  it('follows a review id named in the promotion panel', async () => {
    const wrapper = mountPanel('')
    await wrapper.setProps({ reviewId: 'review-7' })
    expect((wrapper.find('[data-test="claims-review-id"]').element as HTMLInputElement).value).toBe('review-7')
  })

  it('placeholders the configured out root and sends out_root only when filled', async () => {
    const bodies = stubFetch()
    const wrapper = mountPanel()
    const outRoot = wrapper.find('[data-test="claims-out-root"]')
    expect(outRoot.attributes('placeholder')).toBe('campaign/custom_root')
    const select = wrapper.findAll('button').find(button => button.text() === 'Load exact source selection')!
    await select.trigger('click'); await flushPromises()
    expect(bodies[0]).toEqual({ since: 1, until: 3 })
    await outRoot.setValue('docs/other_root')
    await select.trigger('click'); await flushPromises()
    expect(bodies[1]).toEqual({ since: 1, until: 3, out_root: 'docs/other_root' })
  })
})
