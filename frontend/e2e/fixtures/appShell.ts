import type { Page } from '@playwright/test'

/**
 * Stub the API calls the app shell makes on startup (`useConfigStore().load()`
 * in `src/stores/config.ts`), so any page can boot without a backend.
 *
 * `catchAll` additionally answers every other `/api/` request with `{}`, for
 * tests that assert navigation rather than page behaviour. It is registered
 * FIRST because Playwright gives precedence to the most recently registered
 * matching route, so the specific stubs below it still win.
 *
 * The catch-all matches on the URL *pathname*, not the glob `**\/api/**`: that
 * glob also matches Vite's module URLs for `src/api/*.ts` (`/src/api/client.ts`),
 * would answer them with JSON, and the app would never mount.
 */
export async function installAppShellMocks(page: Page, { catchAll = false }: { catchAll?: boolean } = {}) {
  if (catchAll) {
    await page.route(url => url.pathname.startsWith('/api/'), route => route.fulfill({ json: {} }))
  }
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
}
