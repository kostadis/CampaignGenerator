import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import GroundingPromotion from './GroundingPromotion.vue'

// Shapes copied from a real `summary_native promote --dry-run --json` envelope (#548 review):
// gate ids `document-<id>`, `document-signoffs`, `claims`; `data.destination` carries
// `edited_since_publication`, `generation_id`, `live_digest`. No invented gates.
const SIGNOFF_REQUIRED = {
  gate: 'document-signoffs', state: 'blocked', code: 'PROMOTION_SIGNOFF_REQUIRED',
  message: 'four current grounding-bundle-signoff/2 decisions are required', relevant_digest: null,
}
const SIGNOFF_STALE = {
  gate: 'document-signoffs', state: 'blocked', code: 'PROMOTION_SIGNOFF_STALE',
  message: 'sign-off is stale for party', relevant_digest: null,
}
const CLAIMS_UNAVAILABLE = {
  gate: 'claims', state: 'not_available', code: 'CLAIMS_INCOMPLETE',
  message: 'no current cross-document check report was supplied', relevant_digest: null,
}

function documentGate(id: string) {
  return { gate: `document-${id}`, state: 'passed', code: null,
    message: 'draft outline, pointers, and enumerated bytes are current', relevant_digest: 'a'.repeat(64) }
}

function envelope({ signoff = SIGNOFF_REQUIRED, edited = true, eligible = false } = {}) {
  const gates = eligible
    ? ['world_state', 'campaign_state', 'party', 'planning'].map(documentGate)
    : [...['world_state', 'campaign_state', 'party', 'planning'].map(documentGate), signoff, CLAIMS_UNAVAILABLE]
  return {
    ok: eligible, code: eligible ? 'OK' : 'PROMOTION_BLOCKED',
    message: eligible ? 'promotion preview is eligible' : 'promotion preview is blocked', artifacts: [],
    data: {
      destination: { edited_since_publication: edited, generation_id: 'legacy-fixture', live_digest: '0'.repeat(64) },
      preview: {
        bundle_digest: 'c'.repeat(64), campaign_id: 'campaign-1', changes: [],
        destination_edited_since_publication: edited, eligible,
        expected_activation_id: 'baseline-fixture', expected_generation_id: 'legacy-fixture',
        gates, live_digest: '0'.repeat(64), preview_sha256: '1'.repeat(64),
        refusal_codes: eligible ? [] : [CLAIMS_UNAVAILABLE.code, signoff.code].sort(),
        report_analysis_digest: null, report_resolution_digest: null, schema_version: 1, signoff_context_digest: null,
      },
      selection: {
        documents: [{ document_id: 'world_state', path: 'docs/summary_native/ch001-003/state/drafts/world_state.draft.md', sha256: '2'.repeat(64), size: 10 }],
        timeline: { path: 'docs/summary_native/ch001-003/state/drafts/canon_events_timeline.md', sha256: '3'.repeat(64), size: 5 },
        references: [], retained_records: [], dependencies: [],
        alias_identities: [{ kind: 'symlink', path: 'docs/world_state.md', sha256: null, target: 'grounding/current/world_state.md' }],
        selected_range: { out_root: 'docs/summary_native', since: 1, until: 3 },
      },
    },
  }
}

type Call = { url: string; body: any }

function stubFetch(responses: Record<string, any>) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ url, body })
    const key = Object.keys(responses).find(suffix => url.endsWith(suffix))
    return { ok: true, status: 200, json: async () => (key ? responses[key] : {}) } as Response
  }))
  return calls
}

function mountPanel(outRoot = 'docs/summary_native') {
  return mount(GroundingPromotion, {
    props: { since: 1, until: 3, reviewId: 'review-1', checkReportPath: 'report-1' },
    global: { plugins: [createTestingPinia({ createSpy: vi.fn, initialState: { config: {
      groundingConfig: { summary_native: { out_root: outRoot } },
    } } })] },
  })
}

async function preview(wrapper: ReturnType<typeof mountPanel>) {
  await wrapper.find('button.btn-neutral').trigger('click')
  await flushPromises()
}

afterEach(() => vi.unstubAllGlobals())

describe('GroundingPromotion freshness renders the engine fields', () => {
  it('says sign-offs are missing (not stale) and shows the live hand edit', async () => {
    stubFetch({ '/promotion/preview': envelope() })
    const wrapper = mountPanel()
    await preview(wrapper)
    const text = wrapper.text()
    expect(text).toContain('Source approval freshness: Missing')
    expect(text).not.toContain('Source approval freshness: Stale')
    expect(text).toContain('PROMOTION_SIGNOFF_REQUIRED')
    expect(text).toContain('Draft custody: Current')
    expect(text).toContain('Destination preview freshness: Current')
    expect(text).not.toContain('Unknown')
    expect(text).toContain('Live destination: Hand-edited since last publication')
    expect(wrapper.find('[data-test="promotion-live-edited"]').exists()).toBe(true)
    expect(text).toContain('generation_id')
    expect(text).toContain('legacy-fixture')
    expect(text).toContain('baseline-fixture')
    expect(text).toContain('Claims gate: not_available')
    expect(text).toContain('alias (symlink)')
  })

  it('says stale only for a sign-off bound to other bytes, and no live-edit warning when unedited', async () => {
    stubFetch({ '/promotion/preview': envelope({ signoff: SIGNOFF_STALE, edited: false }) })
    const wrapper = mountPanel()
    await preview(wrapper)
    expect(wrapper.text()).toContain('Source approval freshness: Stale')
    expect(wrapper.text()).toContain('Live destination: Matches last publication')
    expect(wrapper.find('[data-test="promotion-live-edited"]').exists()).toBe(false)
  })

  it('marks the preview stale when publication reports PROMOTION_STALE_PREVIEW', async () => {
    stubFetch({
      '/promotion/preview': envelope({ eligible: true }),
      '/promotion/commit': { ok: false, code: 'PROMOTION_STALE_PREVIEW', message: 'preview digest is stale', data: {} },
    })
    const wrapper = mountPanel()
    await preview(wrapper)
    await wrapper.find('[data-test="promotion-request-id"]').setValue('request-1')
    await wrapper.find('[data-test="promotion-commit"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Destination preview freshness: Stale')
    expect(wrapper.text()).toContain('PROMOTION_STALE_PREVIEW')
  })
})

describe('GroundingPromotion out root', () => {
  it('placeholders the configured out root and does not send it when empty', async () => {
    const calls = stubFetch({ '/promotion/preview': envelope() })
    const wrapper = mountPanel('campaign/custom_root')
    expect(wrapper.find('[data-test="promotion-out-root"]').attributes('placeholder')).toBe('campaign/custom_root')
    await preview(wrapper)
    expect(calls[0].body).toEqual({ since: 1, until: 3, review: 'review-1', check_report: 'report-1' })
  })

  it('carries an explicit out root to both preview and commit', async () => {
    const calls = stubFetch({
      '/promotion/preview': envelope({ eligible: true }),
      '/promotion/commit': { ok: true, code: 'OK', message: 'committed', data: {} },
    })
    const wrapper = mountPanel()
    await wrapper.find('[data-test="promotion-out-root"]').setValue('docs/other_root')
    await preview(wrapper)
    await wrapper.find('[data-test="promotion-request-id"]').setValue('request-1')
    await wrapper.find('[data-test="promotion-commit"]').trigger('click')
    await flushPromises()
    expect(calls[0].body.out_root).toBe('docs/other_root')
    expect(calls[1].body).toEqual({
      since: 1, until: 3, review: 'review-1', check_report: 'report-1', out_root: 'docs/other_root',
      preview_sha256: '1'.repeat(64), request_id: 'request-1',
    })
  })
})

describe('GroundingPromotion binds Publish to the previewed inputs', () => {
  for (const [field, value] of [
    ['promotion-review', 'review-2'], ['promotion-report', 'report-2'],
    ['promotion-out-root', 'docs/other_root'], ['promotion-until', '2'],
  ] as const) {
    it(`clears the preview when ${field} changes`, async () => {
      stubFetch({ '/promotion/preview': envelope({ eligible: true }) })
      const wrapper = mountPanel()
      await preview(wrapper)
      expect(wrapper.find('[data-test="promotion-commit"]').exists()).toBe(true)
      await wrapper.find(`[data-test="${field}"]`).setValue(value)
      expect(wrapper.find('[data-test="promotion-commit"]').exists()).toBe(false)
      expect(wrapper.text()).toContain('Inputs changed after the preview')
    })
  }

  it('bounds the request id to the route limit of 96 characters', async () => {
    stubFetch({ '/promotion/preview': envelope({ eligible: true }) })
    const wrapper = mountPanel()
    await preview(wrapper)
    const input = wrapper.find('[data-test="promotion-request-id"]')
    expect(input.attributes('maxlength')).toBe('96')
    await input.setValue('r'.repeat(96))
    expect(wrapper.find('[data-test="promotion-commit"]').attributes('disabled')).toBeUndefined()
    await input.setValue('r'.repeat(97))
    expect(wrapper.find('[data-test="promotion-commit"]').attributes('disabled')).toBeDefined()
    await input.setValue('-starts-with-hyphen')
    expect(wrapper.find('[data-test="promotion-commit"]').attributes('disabled')).toBeDefined()
  })
})
