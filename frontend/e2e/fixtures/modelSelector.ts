import type { Page, Request } from '@playwright/test'

/**
 * Mocks for the app-wide MODEL control (feature 024).
 *
 * The sidebar is rendered on every route, so these tests drive it from the app's
 * home route (`/`, which redirects to `/workflow/config`) rather than a page
 * built for them.
 *
 * The `/api/config/` mock is deliberately **stateful**: `configStore.updateRuntime`
 * PUTs and then calls `refresh()`, which refetches `/api/config/`. A static mock
 * would serve the pre-write value back and make every persistence assertion
 * vacuous — the field would appear to keep its value only because the component
 * never re-read it.
 */

/** A model id the app has never heard of. It does not exist, and that is the
 *  point: if it were in `MODELS` the test would prove nothing. */
export const UNLISTED_MODEL = 'claude-opus-6'

/** Deliberately not in `CURATED_MODELS`, and below the synthesis bar. Used to
 *  show that "unlisted" and "weak" are now separate ideas. */
export const UNLISTED_HAIKU = 'claude-haiku-6'

export const CURATED_MODELS = [
  'claude-opus-5',
  'claude-fable-5',
  'claude-opus-4-8',
  'claude-sonnet-5',
  'claude-sonnet-4-6',
  'claude-haiku-4-5',
]

export const BACKENDS = ['anthropic', 'dgx', 'openrouter', 'claude-code', 'codex-cli']

export interface RuntimeState {
  default_model: string
  default_backend: string
  default_models: Record<string, string>
  default_batch: boolean
  session_dir: string | null
  default_codex_reasoning_effort: string | null
  default_claude_code_effort: string | null
  default_claude_code_thinking: boolean | null
}

export interface SelectorHarness {
  /** Every `PUT /api/config/runtime` body seen, in order. */
  puts: Record<string, any>[]
  /** The server's view of `runtime`, mutated by each PUT. */
  runtime: RuntimeState
}

function freshRuntime(): RuntimeState {
  return {
    default_model: 'claude-sonnet-4-6',
    default_backend: 'anthropic',
    default_models: {},
    default_batch: false,
    session_dir: null,
    default_codex_reasoning_effort: null,
    default_claude_code_effort: null,
    default_claude_code_thinking: null,
  }
}

export async function installModelSelectorMocks(page: Page): Promise<SelectorHarness> {
  const harness: SelectorHarness = { puts: [], runtime: freshRuntime() }

  // Ordered before the GET route so the PUT is captured rather than answered
  // by the generic handler; Playwright matches routes most-recently-added
  // first, so the GET below would otherwise win on the same URL pattern.
  await page.route('**/api/config/runtime', async route => {
    const request: Request = route.request()
    if (request.method() !== 'PUT') return route.fallback()
    const body = request.postDataJSON()
    harness.puts.push(body.values)
    Object.assign(harness.runtime, body.values)
    return route.fulfill({ json: { ok: true } })
  })

  await page.route('**/api/config/', route => route.fulfill({
    json: {
      campaign_id: 'campaign',
      resolved: { campaign_dir: '/campaign', runtime: { ...harness.runtime } },
      migration_warnings: [],
    },
  }))

  await page.route('**/api/config/models', route => route.fulfill({
    json: {
      models: CURATED_MODELS,
      default: 'claude-sonnet-4-6',
      backends: BACKENDS,
      default_backend: harness.runtime.default_backend,
      codex_reasoning_efforts: ['low', 'medium', 'high'],
      claude_code_efforts: ['low', 'medium', 'high', 'xhigh', 'max'],
    },
  }))

  await page.route('**/api/config/status', route => route.fulfill({ json: { cwd: '/campaign' } }))
  await page.route('**/api/editor/config', route => route.fulfill({
    json: { campaign_dir: '/campaign', session_dir: '/campaign/sessions/one' },
  }))
  await page.route('**/api/grounding/config', route => route.fulfill({ json: {} }))

  return harness
}

/**
 * The MODEL input.
 *
 * A CSS locator rather than `getByLabel`: the sidebar's `<label class="model-label">MODEL</label>`
 * is a visual caption with no `for`/`id` pairing, so there is no accessible name
 * to query by. Wiring one up is a real accessibility improvement and a
 * deliberately separate change — doing it here would mean this feature's tests
 * silently depend on an unrelated edit.
 */
export function modelInput(page: Page) {
  return page.locator('.model-selector input')
}

/** Suggestion values currently offered by the datalist, in document order. */
export function suggestionValues(page: Page) {
  return page.locator('.model-selector datalist option').evaluateAll(
    options => options.map(o => (o as HTMLOptionElement).value),
  )
}

/** Click a backend by its button caption in the sidebar's BACKEND toggle. */
export async function selectBackend(page: Page, caption: string) {
  await page.locator('.backend-selector').getByRole('button', { name: caption, exact: true }).click()
}

/** Type a value into the MODEL field and commit it (the input persists on `change`). */
export async function enterModel(page: Page, value: string) {
  const input = modelInput(page)
  await input.fill(value)
  await input.blur()
}
