import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

test('human draft approval survives browser reload and a CLI handoff', async ({ page }) => {
  const campaign = mkdtempSync(join(tmpdir(), 'cycle-browser-'))
  const executable = resolve('../.venv/bin/session_workflow')
  const session = join(campaign, 'session')
  mkdirSync(session)
  writeFileSync(join(campaign, 'config.yaml'), '{}')
  writeFileSync(join(session, 'source.md'), 'Browser fixture source')
  const call = (operation: string, payload: object = {}, revision?: number) => {
    const args = [operation, '--campaign-dir', campaign, '--session-dir', 'session', '--config', join(campaign, 'config.yaml'), '--json', '--request-json', JSON.stringify(payload)]
    if (revision !== undefined && revision !== null) args.push('--expected-revision', String(revision))
    return JSON.parse(execFileSync(executable, args, { encoding: 'utf8' }))
  }
  try {
    const generation = { backend: 'fixture', model: 'deterministic', producer: 'browser-test' }
    let state = call('init').state
    state = call('start', { stage: 'capture', selection: ['source.md'], inputs: ['source.md'], dependencies: [], required_checks: [], generation }, state.revision).state
    const id = state.runs[0].id
    writeFileSync(join(session, 'draft.md'), 'Read this exact browser fixture draft.')
    state = call('submit', { run_id: id, outputs: ['draft.md'], generation }, state.revision).state
    state = call('check', { run_id: id, check: { name: 'capture-integrity', status: 'complete', sources: state.runs[0].outputs, findings: [], producer: 'fixture', at: new Date().toISOString() } }, state.revision).state
    await page.route('**/api/**', async route => {
      const url = new URL(route.request().url())
      if (!url.pathname.startsWith('/api/')) return route.continue()
      if (url.pathname === '/api/session-workflow/command') {
        const body = route.request().postDataJSON()
        try { return await route.fulfill({ json: call(body.operation, body.payload, body.expected_revision) }) }
        catch (error) { return await route.fulfill({ status: 409, json: { error: String(error) } }) }
      }
      const config = url.pathname === '/api/config/' ? { resolved: { campaign_dir: campaign, runtime: { session_dir: session } } } : url.pathname === '/api/config/models' ? { models: [], backends: [], codex_reasoning_efforts: [], claude_code_efforts: [] } : {}
      return route.fulfill({ json: config })
    })
    await page.goto(`/workflow/cycle?session=session&run=${id}`)
    await expect(page.getByRole('heading', { name: 'capture · generated' })).toBeVisible()
    await expect(page.getByText('Checks needed: none. Unresolved: 0.')).toBeVisible()
    expect(call('status').state.runs[0].approval).toBeNull()
    await page.getByRole('button', { name: 'Read draft.md (generated)' }).click()
    await expect(page.getByText('Read this exact browser fixture draft.')).toBeVisible()
    await page.getByLabel('Your name').fill('Browser fixture human')
    await page.getByLabel('Rationale', { exact: true }).fill('I read the displayed fixture draft.')
    await page.getByRole('button', { name: 'I have reviewed this draft — approve' }).click()
    await expect(page.getByRole('heading', { name: 'capture · approved' })).toBeVisible()
    expect(call('status').state.runs[0].approval.actor).toBe('Browser fixture human')
    await page.reload()
    await expect(page.getByRole('heading', { name: 'capture · approved' })).toBeVisible()
    writeFileSync(join(session, 'source.md'), 'Changed by a CLI collaborator')
    await page.getByRole('button', { name: 'Load / refresh' }).click()
    await expect(page.getByRole('heading', { name: 'capture · stale' })).toBeVisible()
    await expect(page.getByText('changed or missing: source.md')).toBeVisible()
  } finally { rmSync(campaign, { recursive: true, force: true }) }
})
