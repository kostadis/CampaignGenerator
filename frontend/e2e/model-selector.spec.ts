import { expect, test } from '@playwright/test'
import {
  CURATED_MODELS,
  UNLISTED_MODEL,
  enterModel,
  installModelSelectorMocks,
  modelInput,
  selectBackend,
  suggestionValues,
  type SelectorHarness,
} from './fixtures/modelSelector'

/**
 * Feature 024 — the app-wide MODEL control accepts a hand-typed id.
 *
 * These are the assertions `tests/test_model_selector_ui.py` explicitly cannot
 * make: that the control *renders*, *persists*, and *round-trips*. Everything
 * here is driven through the real component against mocked HTTP.
 */

let harness: SelectorHarness

test.beforeEach(async ({ page }) => {
  harness = await installModelSelectorMocks(page)
  await page.goto('/')
  await expect(modelInput(page)).toBeVisible()
})

// ── US1: adopt a model the app has never heard of ──────────────────────────

test('accepts an unlisted Claude id on the metered Anthropic backend', async ({ page }) => {
  await enterModel(page, UNLISTED_MODEL)

  expect(harness.puts).toHaveLength(1)
  expect(harness.puts[0].default_model).toBe(UNLISTED_MODEL)
  expect(harness.puts[0].default_models.anthropic).toBe(UNLISTED_MODEL)
})

test('stores one trimmed value in both fields when an id is pasted with whitespace', async ({ page }) => {
  // Regression guard for research R5: `setModel` used to trim into the memory
  // map and persist the raw string as `default_model`, so a single paste wrote
  // two different strings for one choice. This assertion fails without that fix.
  await enterModel(page, `  ${UNLISTED_MODEL}  `)

  expect(harness.puts[0].default_model).toBe(UNLISTED_MODEL)
  expect(harness.puts[0].default_models.anthropic).toBe(UNLISTED_MODEL)
})

test('a hand-entered id survives a reload', async ({ page }) => {
  await enterModel(page, UNLISTED_MODEL)
  await page.reload()

  await expect(modelInput(page)).toHaveValue(UNLISTED_MODEL)
})

test('a typed id reaches run dispatch even before the field is committed', async ({ page }) => {
  // A <select> commits on click; a text input commits on blur or Enter. Every
  // run view forwards `config.model` explicitly, and that beats the persisted
  // runtime value server-side — so if `change` never fires, a run launched
  // without leaving the field would carry the PREVIOUS model while the field
  // displays the new one. `@input` keeps the store honest per keystroke.
  await modelInput(page).fill(UNLISTED_MODEL)   // no blur

  const staged = await page.evaluate(() => {
    const el = document.querySelector('.model-selector input') as HTMLInputElement
    return el.value
  })
  expect(staged).toBe(UNLISTED_MODEL)
  // Nothing persisted yet: platform.yaml is not a scratchpad.
  expect(harness.puts).toHaveLength(0)

  await modelInput(page).blur()
  await expect.poll(() => harness.puts.length).toBe(1)
})

test('an unlisted id is not marked, warned about, or restyled', async ({ page }) => {
  // FR-001 / contract C8. Absence from the shortlist carries no meaning, so it
  // must not be dressed up as irregular either.
  await enterModel(page, UNLISTED_MODEL)

  const input = modelInput(page)
  await expect(input).toHaveValue(UNLISTED_MODEL)
  await expect(input).not.toHaveAttribute('aria-invalid', 'true')
  await expect(page.locator('.model-selector [role="alert"]')).toHaveCount(0)
})

// ── US2: parity across backends, and per-backend memory ────────────────────

test('accepts an unlisted Claude id on the subscription backend too', async ({ page }) => {
  await selectBackend(page, 'Sub')
  await enterModel(page, UNLISTED_MODEL)

  const last = harness.puts[harness.puts.length - 1]
  expect(last.default_model).toBe(UNLISTED_MODEL)
  expect(last.default_models['claude-code']).toBe(UNLISTED_MODEL)
})

test('every backend offers the same model-entry mechanism', async ({ page }) => {
  // FR-011. The control must not change shape as the backend changes — that
  // fork is the defect, and one `<select>` anywhere reintroduces it.
  for (const caption of ['API', 'Sub', 'Codex', 'DGX', 'OR']) {
    await selectBackend(page, caption)
    await expect(modelInput(page)).toBeVisible()
    await expect(page.locator('.model-selector select')).toHaveCount(0)
  }
})

test('each backend remembers its own model across a switch', async ({ page }) => {
  await enterModel(page, UNLISTED_MODEL)

  await selectBackend(page, 'DGX')
  await enterModel(page, 'Qwen/Qwen3-Next-80B')
  await expect(modelInput(page)).toHaveValue('Qwen/Qwen3-Next-80B')

  await selectBackend(page, 'API')
  await expect(modelInput(page)).toHaveValue(UNLISTED_MODEL)
})

test('switching to a backend with no remembered model leaves the field empty', async ({ page }) => {
  // Contract C13. Empty means "defer to this backend's own default" — not
  // another backend's model, and not a curated fallback.
  await selectBackend(page, 'OR')

  await expect(modelInput(page)).toHaveValue('')
})

// ── US4: the shortlist survives as suggestions ─────────────────────────────

test('offers the curated ids as suggestions on both Claude backends', async ({ page }) => {
  await expect.poll(() => suggestionValues(page)).toEqual(CURATED_MODELS)

  await selectBackend(page, 'Sub')
  await expect.poll(() => suggestionValues(page)).toEqual(CURATED_MODELS)
})

test('offers no suggestions on backends whose ids are not enumerable', async ({ page }) => {
  // `MODELS` is the Anthropic registry; a Claude id suggested on a DGX endpoint
  // would be an actively wrong hint, not merely a useless one.
  for (const caption of ['DGX', 'OR', 'Codex']) {
    await selectBackend(page, caption)
    await expect.poll(() => suggestionValues(page)).toEqual([])
  }
})

test('a curated id can still be applied without typing it', async ({ page }) => {
  // SC-004 — the common case must not get slower. A datalist option is applied
  // by setting the value, which is what the browser does on click.
  const input = modelInput(page)
  await input.evaluate((el, value) => {
    const field = el as HTMLInputElement
    field.value = value
    field.dispatchEvent(new Event('change', { bubbles: true }))
  }, CURATED_MODELS[0])

  await expect.poll(() => harness.puts.length).toBeGreaterThan(0)
  expect(harness.puts[harness.puts.length - 1].default_model).toBe(CURATED_MODELS[0])
})
