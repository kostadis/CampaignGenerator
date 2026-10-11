import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  expect,
  test,
  type BrowserContext,
  type Page,
  type Route,
} from '@playwright/test'

// Spec 036, T014. The browser runs the packaged capability viewer rather than
// the trusted desktop application. Only the capability-relative HTTP contract
// is mocked; state is shared across pages so concurrency and reconnect behavior
// exercise the same client paths used by a real review service.

const ORIGIN = 'http://review.test'
const CAPABILITY = `${ORIGIN}/r/acceptance/`
const CSRF = 'acceptance-csrf-nonce'
const viewerRoot = fileURLToPath(
  new URL('../../pipelines/summary_native/review/web/', import.meta.url),
)
const shell = readFileSync(`${viewerRoot}/viewer.html`, 'utf8')
const script = readFileSync(`${viewerRoot}/viewer.js`, 'utf8')
const styles = readFileSync(`${viewerRoot}/viewer.css`, 'utf8')

type Verdict = 'approve' | 'reject' | 'discuss'

type SavedDecision = {
  event_id: string
  decision_revision: number
  verdict: Verdict
  disposition: 'accept_no_change' | 'reject_action' | 'defer'
  note: string
  reviewer: string
  recorded_at: string
}

type RerunFeedback = {
  check_ids: string[]
  outcome: 'completed' | 'failed' | 'unprocessed'
  message: string
}

type ReviewItem = {
  item_id: string
  revision: number
  review_digest: string
  domain: 'npc_finding' | 'grounding_document' | 'duplicate_identity'
  claim_text: string
  locator: { source_path: string; anchor: string }
  evidence: Array<{
    source_id: string
    source_path: string
    anchor: string
    exact_excerpt: string
    selected_span_sha256: string
  }>
  diagnostics: Array<{
    diagnostic_id: string
    legacy_code: string
    message: string
    blocking: boolean
  }>
  categories: string[]
  severity: 'needs_judgment' | 'warning'
  rationale: string
  proposed_action: { action: string }
  subject_kind?: string
  subject_identity_resolved?: boolean
  freshness: 'current' | 'stale'
  stale_reason?: string
  rerun?: RerunFeedback
}

function makeItems(): ReviewItem[] {
  return Array.from({ length: 25 }, (_, index) => {
    const number = index + 1
    const category = number % 2 ? 'citation_non_entailment' : 'identity_ambiguity'
    return {
      item_id: `item-${number}`,
      revision: 1,
      review_digest: number.toString(16).padStart(64, '0'),
      domain: 'npc_finding',
      claim_text: `Claim ${number}: the NPC made a consequential promise.`,
      locator: {
        source_path: 'summaries/001/session-summary.md',
        anchor: `scene-${number}`,
      },
      evidence: [{
        source_id: 'summary-1',
        source_path: 'summaries/001/session-summary.md',
        anchor: `scene-${number}`,
        exact_excerpt: `Evidence ${number}: the exact captured passage.`,
        selected_span_sha256: 'e'.repeat(64),
      }],
      diagnostics: [{
        diagnostic_id: `diagnostic-${number}`,
        legacy_code: category,
        message: `Diagnostic ${number} needs a human ruling.`,
        blocking: false,
      }],
      categories: [category],
      severity: number % 5 ? 'needs_judgment' : 'warning',
      rationale: `Rationale ${number}: the citation is valid but the meaning needs review.`,
      proposed_action: { action: 'accept_no_change_or_correct' },
      freshness: 'current',
    }
  })
}

class ReviewBackend {
  readonly items = makeItems()
  readonly decisions = new Map<string, SavedDecision>()
  readonly reruns = new Map<string, RerunFeedback>()
  requestCount = 0
  failNextSave = false
  delayNextSaveMs = 0
  failNextItemId: string | null = null
  kind = 'npc_verification'
  longDocument = ''
  lastDecisionBody: Record<string, unknown> | null = null

  private counts() {
    const current = this.items.filter(item => item.freshness === 'current')
    const values = current.flatMap(item => {
      const decision = this.decisions.get(item.item_id)
      return decision ? [decision] : []
    })
    const stale = this.items.filter(item =>
      item.freshness === 'stale' && this.decisions.has(item.item_id),
    ).length
    return {
      total: this.items.length,
      pending: this.items.length - values.filter(value => value.verdict === 'approve').length,
      approved: values.filter(value => value.verdict === 'approve').length,
      rejected: values.filter(value => value.verdict === 'reject').length,
      discussed: values.filter(value => value.verdict === 'discuss').length,
      stale,
      settled: values.filter(value => value.verdict === 'approve').length,
    }
  }

  private summary(item: ReviewItem) {
    const decision = this.decisions.get(item.item_id)
    return {
      item_id: item.item_id,
      revision: item.revision,
      review_digest: item.review_digest,
      claim_text: item.claim_text,
      categories: item.categories,
      severity: item.severity,
      freshness: item.freshness,
      stale_reason: item.stale_reason,
      rerun: this.reruns.get(item.item_id),
      disposition: item.freshness === 'stale' ? 'pending' : decision?.verdict ?? 'pending',
      decision_revision: decision?.decision_revision ?? 0,
    }
  }

  async handle(route: Route) {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const headers = { 'Cache-Control': 'no-store' }

    if (request.method() === 'GET' && path === '/r/acceptance/') {
      return route.fulfill({
        status: 200,
        contentType: 'text/html; charset=utf-8',
        headers: { ...headers, 'X-Review-CSRF': CSRF },
        body: shell,
      })
    }
    if (request.method() === 'GET' && path === '/r/acceptance/assets/viewer.js') {
      return route.fulfill({ status: 200, contentType: 'text/javascript', headers, body: script })
    }
    if (request.method() === 'GET' && path === '/r/acceptance/assets/viewer.css') {
      return route.fulfill({ status: 200, contentType: 'text/css', headers, body: styles })
    }
    if (request.method() === 'GET' && path === '/r/acceptance/review') {
      return route.fulfill({
        status: 200,
        headers,
        json: {
          ok: true,
          data: {
            review_id: 'npc-review',
            kind: this.kind,
            generation: 1,
            title: 'NPC verification review',
            transport: 'Private review link',
            counts: this.counts(),
            items: this.items.map(item => this.summary(item)),
            next_cursor: null,
          },
        },
      })
    }
    const itemMatch = path.match(/^\/r\/acceptance\/items\/(item-\d+)$/)
    if (request.method() === 'GET' && itemMatch) {
      if (this.failNextItemId === itemMatch[1]) {
        this.failNextItemId = null
        return route.fulfill({ status: 503, json: { ok: false, message: 'Next item temporarily unavailable.' } })
      }
      const item = this.items.find(candidate => candidate.item_id === itemMatch[1])
      if (!item) return route.fulfill({ status: 404, json: { ok: false, code: 'NOT_FOUND' } })
      const offset = Number(url.searchParams.get('section_offset') ?? 0)
      const documentSection = item.domain === 'grounding_document' && url.searchParams.has('section_offset')
        ? {
            content: this.longDocument.slice(offset, offset + 65536),
            offset,
            next_offset: offset + 65536 < this.longDocument.length ? offset + 65536 : null,
            total_bytes: this.longDocument.length,
            full_document_sha256: 'd'.repeat(64),
          }
        : undefined
      return route.fulfill({
        status: 200,
        headers,
        json: {
          ok: true,
          data: {
            ...item,
            rerun: this.reruns.get(item.item_id),
            decision: this.decisions.get(item.item_id) ?? null,
            decision_revision: this.decisions.get(item.item_id)?.decision_revision ?? 0,
            ...(documentSection ? { document_section: documentSection } : {}),
          },
        },
      })
    }
    const historyMatch = path.match(/^\/r\/acceptance\/history\/(item-\d+)$/)
    if (request.method() === 'GET' && historyMatch) {
      const decision = this.decisions.get(historyMatch[1])
      return route.fulfill({
        status: 200,
        headers,
        json: { ok: true, data: { events: decision ? [decision] : [] } },
      })
    }
    if (request.method() === 'POST' && path === '/r/acceptance/decisions') {
      if (request.headers()['x-review-csrf'] !== CSRF) {
        return route.fulfill({ status: 400, json: { ok: false, code: 'REVIEW_CSRF_REQUIRED' } })
      }
      if (this.delayNextSaveMs) {
        const delay = this.delayNextSaveMs
        this.delayNextSaveMs = 0
        await new Promise(resolve => setTimeout(resolve, delay))
      }
      if (this.failNextSave) {
        this.failNextSave = false
        return route.fulfill({
          status: 503,
          json: {
            ok: false,
            code: 'REVIEW_SAVE_UNAVAILABLE',
            message: 'The decision was not saved. Retry with the same request.',
          },
        })
      }
      const body = request.postDataJSON() as {
        request_id: string
        review_generation: number
        reviewer: string
        decisions: Array<{
          item_id: string
          item_revision: number
          review_digest: string
          expected_decision_revision: number
          verdict: Verdict
          disposition: SavedDecision['disposition']
          note: string
        }>
      }
      this.lastDecisionBody = body as unknown as Record<string, unknown>
      const conflict = body.decisions.find(decision =>
        (this.decisions.get(decision.item_id)?.decision_revision ?? 0)
          !== decision.expected_decision_revision,
      )
      if (conflict) {
        return route.fulfill({
          status: 409,
          json: {
            ok: false,
            code: 'REVIEW_STALE_DECISION',
            message: 'A newer decision exists. Reload it before deciding again.',
            data: { item_id: conflict.item_id },
          },
        })
      }
      const events = body.decisions.map(decision => {
        const saved: SavedDecision = {
          event_id: `event-${++this.requestCount}`,
          decision_revision: decision.expected_decision_revision + 1,
          verdict: decision.verdict,
          disposition: decision.disposition,
          note: decision.note,
          reviewer: body.reviewer,
          recorded_at: '2026-10-09T12:00:00Z',
        }
        this.decisions.set(decision.item_id, saved)
        return { item_id: decision.item_id, ...saved }
      })
      return route.fulfill({
        status: 200,
        headers,
        json: { ok: true, data: { events, counts: this.counts() } },
      })
    }
    return route.fulfill({ status: 404, json: { ok: false, code: 'NOT_FOUND' } })
  }
}

async function installReview(context: BrowserContext, backend: ReviewBackend) {
  await context.route(`${ORIGIN}/**`, route => backend.handle(route))
}

async function openReview(page: Page) {
  await page.goto(CAPABILITY)
  await expect(page.getByRole('heading', { name: 'NPC verification review' })).toBeVisible()
  await expect(page.getByRole('list', { name: 'Review queue' })).toBeVisible()
}

function itemRow(page: Page, number: number) {
  return page.getByRole('listitem').filter({ hasText: `Claim ${number}:` })
}

async function openItem(page: Page, number: number) {
  await itemRow(page, number).getByRole('button', { name: new RegExp(`Claim ${number}:`) }).click()
  await expect(page.getByRole('heading', { name: `Claim ${number}: the NPC made a consequential promise.` })).toBeVisible()
}

async function saveCurrent(page: Page, verdict: Verdict, note: string) {
  await page.getByRole('button', { name: new RegExp(`^${verdict}$`, 'i') }).click()
  await page.getByLabel('Decision note').fill(note)
  await page.getByRole('button', { name: 'Save decision' }).click()
}

test.describe('packaged summary-native review viewer', () => {
  test.describe.configure({ timeout: 15_000 })

  test.beforeEach(async ({ context }) => {
    await installReview(context, new ReviewBackend())
  })

  for (const width of [320, 375]) {
    test(`the full 25-item queue and paired evidence remain usable at ${width}px`, async ({ page, context }) => {
      const backend=new ReviewBackend()
      backend.items[0].subject_kind='entity'
      backend.items[0].subject_identity_resolved=true
      backend.items[0].proposed_action={action:'confirm_claim_mapping',details:{subject_id:'entity-1'}} as any
      backend.items[0].evidence.push({source_id:'authority-1',source_path:'docs/authority/a-very-long-ledger-location-that-must-wrap-without-horizontal-scrolling.yaml',anchor:'records.entity-1.effective-value',exact_excerpt:'Paired authority evidence for the exact normalized meaning.',selected_span_sha256:'f'.repeat(64)})
      await context.unroute(`${ORIGIN}/**`)
      await installReview(context,backend)
      await page.setViewportSize({ width, height: 720 })
      await openReview(page)

      await expect(page.getByRole('list', { name: 'Review queue' }).getByRole('listitem')).toHaveCount(25)
      await openItem(page, 1)
      await expect(page.getByText('Evidence 1: the exact captured passage.')).toBeVisible()
      await expect(page.getByText('summaries/001/session-summary.md',{exact:true})).toBeVisible()
      await expect(page.getByText('docs/authority/a-very-long-ledger-location-that-must-wrap-without-horizontal-scrolling.yaml')).toBeVisible()
      await expect(page.getByText('records.entity-1.effective-value')).toBeVisible()
      await expect(page.getByText('Subject kind')).toBeVisible()
      await expect(page.getByText('entity', {exact:true})).toBeVisible()
      await expect(page.getByText('Subject identity resolved')).toBeVisible()
      await expect(page.getByText('true', {exact:true})).toBeVisible()
      await expect(page.getByText(/Rationale 1:/)).toBeVisible()
      await expect(page.getByText('citation_non_entailment')).toBeVisible()
      await expect(page.getByText('needs_judgment')).toBeVisible()

      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
      for (const control of await page.getByRole('button', { name: /Approve|Reject|Discuss/ }).all()) {
        expect((await control.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
      }
    })
  }

  test('verdict selection switches, resets between items, and restores after save', async ({ page, context }) => {
    const backend = new ReviewBackend()
    await context.unroute(`${ORIGIN}/**`)
    await installReview(context, backend)
    await openReview(page)

    await openItem(page, 1)
    const approve = page.getByRole('button', { name: /^Approve$/ })
    const reject = page.getByRole('button', { name: /^Reject$/ })
    const discuss = page.getByRole('button', { name: /^Discuss$/ })
    await expect(approve).toHaveAttribute('aria-pressed', 'false')
    await approve.click()
    await expect(approve).toHaveAttribute('aria-pressed', 'true')
    await expect(page.locator('#decision-selection')).toHaveText(
      'Unsaved selection: Approve. Save decision to record it.',
    )

    await reject.click()
    await expect(approve).toHaveAttribute('aria-pressed', 'false')
    await expect(reject).toHaveAttribute('aria-pressed', 'true')
    await page.getByRole('button', { name: 'Back to queue' }).click()

    await openItem(page, 2)
    await expect(reject).toHaveAttribute('aria-pressed', 'false')
    await expect(page.locator('#decision-selection')).toHaveText('No decision selected.')
    await page.getByRole('button', { name: 'Back to queue' }).click()

    await openItem(page, 1)
    await expect(reject).toHaveAttribute('aria-pressed', 'false')
    await discuss.click()
    await page.getByLabel('Decision note').fill('Return to this saved choice.')
    await page.getByRole('button', { name: 'Save decision' }).click()
    await expect(discuss).toHaveAttribute('aria-pressed', 'true')
    await expect(page.locator('#decision-selection')).toHaveText('Saved decision: Discuss.')
    await page.getByRole('button', { name: 'Back to queue' }).click()

    await openItem(page, 1)
    await expect(discuss).toHaveAttribute('aria-pressed', 'true')
    await expect(page.locator('#decision-selection')).toHaveText('Saved decision: Discuss.')
  })

  test('queue badges show only persisted verdicts after save, back, and reload', async ({ page, context }) => {
    const backend = new ReviewBackend()
    await context.unroute(`${ORIGIN}/**`)
    await installReview(context, backend)
    await openReview(page)

    await expect(itemRow(page, 1).getByText('Pending', { exact: true })).toBeVisible()
    await openItem(page, 1)
    await page.getByRole('button', { name: /^Approve$/ }).click()
    await page.getByRole('button', { name: 'Back to queue' }).click()
    await expect(itemRow(page, 1).getByText('Pending', { exact: true })).toBeVisible()

    const cases: Array<[number, Verdict, string, string]> = [
      [1, 'approve', 'Approved', 'Approved after checking the source.'],
      [2, 'reject', 'Rejected', 'Rejected because the source conflicts.'],
      [3, 'discuss', 'Discuss', 'Discuss this ruling with the group.'],
    ]
    for (const [number, verdict, badge, note] of cases) {
      await openItem(page, number)
      await saveCurrent(page, verdict, note)
      await page.getByRole('button', { name: 'Back to queue' }).click()
      await expect(itemRow(page, number).getByText(badge, { exact: true })).toBeVisible()
      await expect(itemRow(page, number)).toContainText(`Saved note: ${note}`)
    }

    await page.reload()
    await expect(page.getByRole('list', { name: 'Review queue' })).toBeVisible()
    for (const [number, , badge] of cases) {
      await expect(itemRow(page, number).getByText(badge, { exact: true })).toBeVisible()
    }
    await expect(itemRow(page, 4).getByText('Pending', { exact: true })).toBeVisible()
  })

  test('save and next advances only after the decision is durably saved', async ({ page, context }) => {
    const backend = new ReviewBackend()
    await context.unroute(`${ORIGIN}/**`)
    await installReview(context, backend)
    await openReview(page)
    await openItem(page, 1)
    await page.getByRole('button', { name: /^Approve$/ }).click()
    await page.getByLabel('Decision note').fill('Save before advancing.')
    await page.getByRole('button', { name: 'Save and next' }).click()

    await expect(page.getByRole('heading', { name: /Claim 2:/ })).toBeVisible()
    await expect(page.getByRole('heading', { name: /Claim 2:/ })).toBeFocused()
    expect(backend.decisions.get('item-1')?.note).toBe('Save before advancing.')
    expect(backend.decisions.has('item-2')).toBe(false)
  })

  test('failed save and next stays on the item and retry preserves the advance', async ({ page, context }) => {
    const backend = new ReviewBackend()
    backend.failNextSave = true
    await context.unroute(`${ORIGIN}/**`)
    await installReview(context, backend)
    await openReview(page)
    await openItem(page, 3)
    await page.getByRole('button', { name: /^Discuss$/ }).click()
    await page.getByLabel('Decision note').fill('Keep this note through retry.')
    await page.getByRole('button', { name: 'Save and next' }).click()

    await expect(page.getByRole('heading', { name: /Claim 3:/ })).toBeVisible()
    await expect(page.getByLabel('Decision note')).toHaveValue('Keep this note through retry.')
    expect(backend.decisions.has('item-3')).toBe(false)
    await page.getByRole('button', { name: 'Retry save' }).click()
    await expect(page.getByRole('heading', { name: /Claim 4:/ })).toBeVisible()
    expect(backend.decisions.get('item-3')?.note).toBe('Keep this note through retry.')
  })

  test('save and next does not wrap after the final visible item', async ({ page, context }) => {
    const backend = new ReviewBackend()
    await context.unroute(`${ORIGIN}/**`)
    await installReview(context, backend)
    await openReview(page)
    await openItem(page, 25)
    await page.getByRole('button', { name: /^Reject$/ }).click()
    await page.getByLabel('Decision note').fill('Final visible item.')
    await page.getByRole('button', { name: 'Save and next' }).click()

    await expect(page.getByRole('heading', { name: /Claim 25:/ })).toBeVisible()
    await expect(page.getByText('Saved. End of the visible review queue.')).toBeVisible()
    expect(backend.decisions.get('item-25')?.verdict).toBe('reject')
  })

  test('save and next retries only navigation when the committed next item fails to load', async ({ page, context }) => {
    const backend = new ReviewBackend()
    await context.unroute(`${ORIGIN}/**`)
    await installReview(context, backend)
    await openReview(page)
    await openItem(page, 6)
    backend.failNextItemId = 'item-7'
    await page.getByRole('button', { name: /^Approve$/ }).click()
    await page.getByLabel('Decision note').fill('This save must happen exactly once.')
    await page.getByRole('button', { name: 'Save and next' }).click()

    await expect(page.getByRole('heading', { name: /Claim 6:/ })).toBeVisible()
    await expect(page.getByText(/Saved\. Next item could not be loaded/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Retry next item' })).toBeVisible()
    expect(backend.decisions.get('item-6')?.decision_revision).toBe(1)
    await page.getByRole('button', { name: 'Retry next item' }).click()
    await expect(page.getByRole('heading', { name: /Claim 7:/ })).toBeVisible()
    expect(backend.decisions.get('item-6')?.decision_revision).toBe(1)
  })

  test('notes, filters, explicit selection and saved progress agree', async ({ page }) => {
    await openReview(page)
    await expect(page.getByText('0 of 25 settled')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Save selected' })).toBeDisabled()

    await openItem(page, 1)
    await saveCurrent(page, 'approve', 'The excerpt supports this claim.')
    await expect(page.locator('#save-state')).toHaveText(/^Saved/)
    await expect(page.getByText('1 of 25 settled')).toBeVisible()
    await page.getByRole('button', { name: 'Back to queue' }).click()

    await page.getByLabel('Category').selectOption('identity_ambiguity')
    await expect(page.getByText('12 filtered')).toBeVisible()
    await page.getByLabel('Select all visible').check()
    await expect(page.getByText('12 selected')).toBeVisible()
    await page.getByLabel('Select item-2').uncheck()
    await expect(page.getByText('11 selected')).toBeVisible()

    await page.getByLabel('Hide approved').check()
    await page.getByLabel('Category').selectOption('all')
    await expect(itemRow(page, 1)).toHaveCount(0)
    await expect(page.getByText('24 filtered')).toBeVisible()
  })

  test('a pending or failed save never advances saved progress and can be retried', async ({ page, context }) => {
    const backend = new ReviewBackend()
    await context.unroute(`${ORIGIN}/**`)
    await installReview(context, backend)
    await openReview(page)
    await openItem(page, 2)

    backend.delayNextSaveMs = 400
    backend.failNextSave = true
    await saveCurrent(page, 'reject', 'This conflicts with the cited passage.')
    await expect(page.getByText('Saving…')).toBeVisible()
    await expect(page.getByText('0 of 25 settled')).toBeVisible()
    await expect(page.getByText(/not saved|save failed/i)).toBeVisible()
    await expect(page.getByText('0 of 25 settled')).toBeVisible()

    await page.getByRole('button', { name: 'Retry save' }).click()
    await expect(page.locator('#save-state')).toHaveText(/^Saved/)
    await expect(page.getByText('0 of 25 settled')).toBeVisible()
  })

  test('competing tabs surface a stale decision instead of overwriting it', async ({ browser }) => {
    const backend = new ReviewBackend()
    const context = await browser.newContext()
    await installReview(context, backend)
    const first = await context.newPage()
    const second = await context.newPage()
    await openReview(first)
    await openReview(second)
    await openItem(first, 3)
    await openItem(second, 3)

    await saveCurrent(first, 'approve', 'First tab ruling.')
    await expect(first.locator('#save-state')).toHaveText(/^Saved/)
    await saveCurrent(second, 'reject', 'Second tab ruling.')
    await expect(second.getByText(/changed in another|newer decision|stale/i)).toBeVisible()
    await expect(second.getByRole('button', { name: 'Reload latest' })).toBeVisible()
    expect(backend.decisions.get('item-3')?.verdict).toBe('approve')

    await second.getByRole('button', { name: 'Reload latest' }).click()
    await expect(second.getByText('First tab ruling.')).toBeVisible()
    await context.close()
  })

  test('saved work survives reload and service restart while offline work remains unsaved', async ({ page, context }) => {
    const backend = new ReviewBackend()
    await context.unroute(`${ORIGIN}/**`)
    await installReview(context, backend)
    await openReview(page)
    await openItem(page, 4)
    await saveCurrent(page, 'discuss', 'Need the next chapter before resolving this.')
    await expect(page.locator('#save-state')).toHaveText(/^Saved/)

    await page.reload()
    await expect(page.getByText('0 of 25 settled')).toBeVisible()
    await openItem(page, 5)
    await page.getByRole('button', { name: /^approve$/i }).click()
    await page.getByLabel('Decision note').fill('Written while disconnected.')
    await context.setOffline(true)
    await page.getByRole('button', { name: 'Save decision' }).click()
    await expect(page.getByText(/not saved|save failed|offline/i)).toBeVisible()
    await expect(page.getByText('0 of 25 settled')).toBeVisible()
    expect(backend.decisions.has('item-5')).toBe(false)

    await context.setOffline(false)
    await page.getByRole('button', { name: 'Retry save' }).click()
    await expect(page.getByText('1 of 25 settled')).toBeVisible()
    await page.reload()
    await expect(page.getByText('1 of 25 settled')).toBeVisible()
    expect(backend.decisions.get('item-4')?.note).toBe('Need the next chapter before resolving this.')
  })

  test('selected rerun outcomes identify the exact checks and leave unrelated rows untouched', async ({ page, context }) => {
    const backend = new ReviewBackend()
    backend.reruns.set('item-2', {
      check_ids: ['citation'],
      outcome: 'completed',
      message: 'The selected citation check completed.',
    })
    backend.reruns.set('item-3', {
      check_ids: ['quote', 'status-word'],
      outcome: 'failed',
      message: 'The selected quote check failed; status-word was left unprocessed.',
    })
    await context.unroute(`${ORIGIN}/**`)
    await installReview(context, backend)
    await openReview(page)

    await expect(itemRow(page, 2)).toContainText(/citation.*completed/i)
    await expect(itemRow(page, 3)).toContainText(/quote.*status-word.*failed/i)
    await expect(itemRow(page, 4)).not.toContainText(/rerun|completed|failed|unprocessed/i)

    await openItem(page, 3)
    await expect(page.getByText('Selected checks: quote, status-word')).toBeVisible()
    await expect(page.locator('#rerun')).toContainText(/quote check failed.*left unprocessed/i)
  })

  test('a stale approval is visibly reopened with its exact freshness reason', async ({ page, context }) => {
    const backend = new ReviewBackend()
    backend.decisions.set('item-1', {
      event_id: 'event-stale-approval',
      decision_revision: 1,
      verdict: 'approve',
      disposition: 'accept_no_change',
      note: 'Approved against the earlier evidence revision.',
      reviewer: 'GM',
      recorded_at: '2026-10-09T12:00:00Z',
    })
    backend.items[0].freshness = 'stale'
    backend.items[0].stale_reason = 'Relevant evidence changed after approval.'
    await context.unroute(`${ORIGIN}/**`)
    await installReview(context, backend)
    await openReview(page)

    await expect(page.getByText('0 of 25 settled')).toBeVisible()
    await expect(page.getByText(/1 stale/i)).toBeVisible()
    await expect(itemRow(page, 1)).toContainText(/stale approval/i)
    await openItem(page, 1)
    await expect(page.getByText('Relevant evidence changed after approval.')).toBeVisible()
    await expect(page.locator('#freshness')).toContainText(/approval.*no longer current|review again/i)
    await expect(page.getByRole('button', { name: /^approve$/i })).toBeEnabled()
  })

  test('a long document is rendered in bounded sections at narrow width and saved as sign-off', async ({ page, context }) => {
    const backend = new ReviewBackend()
    backend.kind = 'grounding_documents'
    backend.longDocument = Array.from({ length: 7000 }, (_, index) => `Section line ${index + 1}: reviewed grounding text.\n`).join('')
    backend.items[0].domain = 'grounding_document'
    backend.items[0].claim_text = 'Approve exact world state draft for promotion.'
    backend.items[0].proposed_action = { action: 'signoff_document' }
    await context.unroute(`${ORIGIN}/**`)
    await installReview(context, backend)
    await page.setViewportSize({ width: 320, height: 720 })
    await openReview(page)
    await page.getByRole('list', { name: 'Review queue' }).getByRole('listitem').first().getByRole('button').click()

    await expect(page.getByText(/Exact full-document digest:/)).toBeVisible()
    await expect(page.locator('#document-text')).toContainText('Section line 1: reviewed grounding text.')
    await expect(page.getByRole('button', { name: 'Load next section' })).toBeVisible()
    await page.getByRole('button', { name: 'Load next section' }).click()
    await expect(page.locator('#document-text')).toContainText('Section line 2000: reviewed grounding text.')
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)

    await saveCurrent(page, 'approve', 'Signed after reading the exact bounded document.')
    await expect(page.locator('#save-state')).toHaveText(/^Saved/)
  })

  test('identity approval selects one exact prepared canonical digest', async ({ page, context }) => {
    const backend = new ReviewBackend()
    backend.kind = 'duplicate_identity'
    const item = backend.items[0] as ReviewItem & {
      identity_proposals?: unknown[]
      application?: unknown
    }
    item.domain = 'duplicate_identity'
    item.identity_proposals = [
      { proposal_id: 'identity-item-1-a', proposal_digest: 'a'.repeat(64), canonical_registry_name: 'Ada Stone', applicable: true, blocked_reasons: [], affected_paths: ['docs/entity_registry.yaml'], inspected_paths: ['summaries/001.md'], generative_rebuilds: [], targets: [] },
      { proposal_id: 'identity-item-1-b', proposal_digest: 'b'.repeat(64), canonical_registry_name: 'Aeda Stone', applicable: false, blocked_reasons: ['REVIEW_SCOPED_ALIAS_UNSUPPORTED'], affected_paths: [], inspected_paths: ['summaries/001.md'], generative_rebuilds: [], targets: [] },
    ]
    item.application = {
      state: 'applied',
      receipt_id: 'identity-receipt-item-1',
      changed_paths: ['docs/entity_registry.yaml'],
      remaining_review_work: ['docs/npcs/ada_stone.md'],
    }
    await context.unroute(`${ORIGIN}/**`)
    await installReview(context, backend)
    await openReview(page)
    await openItem(page, 1)
    await expect(page.getByText(/Applied as receipt identity-receipt-item-1/)).toBeVisible()
    await expect(page.getByText(/docs\/npcs\/ada_stone\.md/)).toBeVisible()
    await expect(page.getByText(/REVIEW_SCOPED_ALIAS_UNSUPPORTED/)).toBeVisible()
    await expect(page.getByRole('button', { name: /Select Aeda Stone/ })).toBeDisabled()
    await page.getByRole('button', { name: /Select Ada Stone/ }).click()
    await saveCurrent(page, 'approve', 'Use the exact reviewed global alias proposal.')
    await expect(page.locator('#save-state')).toContainText('Saved')
    const body = backend.lastDecisionBody as { decisions: Array<Record<string, unknown>> }
    expect(body.decisions[0]).toMatchObject({ disposition: 'merge', proposal_id: 'identity-item-1-a', proposal_digest: 'a'.repeat(64) })

    await page.getByRole('button', { name: 'Confirm these are distinct identities' }).click()
    await page.getByLabel('Decision note').fill('Keep the reviewed pair distinct.')
    await page.getByRole('button', { name: 'Approve' }).click()
    await page.getByRole('button', { name: 'Save decision' }).click()
    await expect(page.locator('#saved-note')).toHaveText('Keep the reviewed pair distinct.')
    const distinct = backend.lastDecisionBody as { decisions: Array<Record<string, unknown>> }
    expect(distinct.decisions[0]).toMatchObject({ disposition: 'distinct' })
    expect(distinct.decisions[0]).not.toHaveProperty('proposal_id')
  })
})
