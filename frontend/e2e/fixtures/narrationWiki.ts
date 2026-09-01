import type { Page } from '@playwright/test'
import type { WikiStatus } from '../../src/api/narrationWiki'

const checks = Array.from({ length: 18 }, (_, index) => ({
  key: index % 2 ? 'shape_of' : 'em_dash',
  scope: 'document',
  subject: `narration/a-very-wide-document-name-${index}.md`,
  observed: index,
  budget: { operator: '<=', value: 1, unit: 'occurrences' },
  verdict: index > 1 ? 'breach' as const : 'ok' as const,
  reason: null,
}))

export const selectedStatus: WikiStatus = {
  ok: true,
  command: 'status',
  campaign_id: 'campaign',
  session_relative: 'sessions/one',
  iteration_id: 'iter-001',
  state: 'measured_before',
  corpus_id: 'a'.repeat(64),
  pattern_counts: { pending: 2, accepted: 1, rejected: 1, pending_portable_sync: 1 },
  unresolved_conflict_ids: ['seed-voice'],
  active_proposal_id: 'proposal-001',
  dependency: {
    present: true,
    compatible: true,
    source_repository: 'kostadis/narration-wiki-companion',
    source_revision: 'fixture-revision-with-a-wide-value-for-horizontal-scrolling',
    capabilities: ['maintainer', 'proposer'],
  },
  recovery: null,
  measurement_checks: checks,
}

export const emptyStatus: WikiStatus = {
  ...selectedStatus,
  state: 'collected',
  pattern_counts: { pending: 0, accepted: 0, rejected: 0, pending_portable_sync: 0 },
  unresolved_conflict_ids: [],
  active_proposal_id: null,
  measurement_checks: [],
}

export const recoveryStatus: WikiStatus = {
  ...selectedStatus,
  state: 'needs_attention',
  recovery: {
    transaction_id: 'iter-001-gate2-reject-proposal-001',
    operation: 'gate2_reject',
    state: 'needs_attention',
    next_action: 'inspect_hashes',
  },
}

export const largeDiff = Array.from({ length: 40 }, (_, index) =>
  `-${index} old very wide line ${'before '.repeat(20)}\n+${index} new very wide line ${'after '.repeat(20)}`,
).join('\n')

export async function installNarrationWikiMocks(page: Page, state: WikiStatus = selectedStatus) {
  await page.route('**/api/config/', route => route.fulfill({ json: {
    campaign_id: 'campaign',
    resolved: { campaign_dir: '/campaign', runtime: { session_dir: '/campaign/sessions/one' } },
  } }))
  await page.route('**/api/config/models', route => route.fulfill({ json: {
    models: [], default: '', backends: ['anthropic'], default_backend: 'anthropic', codex_reasoning_efforts: [],
  } }))
  await page.route('**/api/config/status', route => route.fulfill({ json: { cwd: '/campaign' } }))
  await page.route('**/api/editor/config', route => route.fulfill({ json: { campaign_dir: '/campaign', session_dir: '/campaign/sessions/one' } }))
  await page.route('**/api/grounding/config', route => route.fulfill({ json: {} }))
  await page.route('**/api/narration-wiki/status**', route => route.fulfill({ json: state }))
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window)
    window.fetch = async (input, init) => {
      const url = String(input)
      if (init?.method === 'POST' && url.includes('/api/narration-wiki/')) {
        const encoder = new TextEncoder()
        if (url.endsWith('/proposal-apply')) {
          const signal = init.signal
          return new Response(new ReadableStream({
            start(controller) {
              controller.enqueue(encoder.encode('event: command\ndata: "$ narration_wiki proposal-apply"\n\n'))
              signal?.addEventListener('abort', () => controller.error(new DOMException('Aborted', 'AbortError')), { once: true })
            },
          }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
        }
        const returncode = url.endsWith('/collect') ? 5 : 0
        const fragments = [
          'event: command\nda', 'ta: "$ narration_wiki"\n\n',
          'data: "first ', 'chunk\\n"\n\n',
          'event: done\ndata: {"ret', `urncode":${returncode},"result":"${returncode ? 'failed' : 'success'}"}\n\n`,
        ]
        return new Response(new ReadableStream({
          start(controller) {
            for (const fragment of fragments) controller.enqueue(encoder.encode(fragment))
            controller.close()
          },
        }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
      }
      return originalFetch(input, init)
    }
  })
}
