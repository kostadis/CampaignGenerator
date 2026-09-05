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


for (const width of [1280, 390]) {
  test(`per-finding decisions and discussion survive CLI handoff at ${width}px`, async ({ page }) => {
    test.setTimeout(60000)
    await page.setViewportSize({ width, height: 800 })
    const campaign = mkdtempSync(join(tmpdir(), 'cycle-finding-browser-'))
    const executable = resolve('../.venv/bin/session_workflow')
    const session = join(campaign, 'session')
    mkdirSync(session)
    writeFileSync(join(campaign, 'config.yaml'), '{}')
    writeFileSync(join(session, 'source.md'), 'Preserved source')
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
      writeFileSync(join(session, 'draft.md'), 'First disputed line. Second disputed line. Third disputed line.')
      state = call('submit', { run_id: id, outputs: ['draft.md'], generation }, state.revision).state
      const evidence = state.runs[0].outputs[0]
      const findings = ['First', 'Second', 'Third'].map((word, i) => ({
        id: `f${i + 1}`, scene: `Scene ${i + 1}`, evidence, location: `Line ${i + 1}`, description: `${word} finding`, proposed_action: `Correct ${word.toLowerCase()} wording`,
        consequences: { approve: 'Authorize the displayed replacement.', reject: 'Keep this wording.', discuss: 'Resolve this with the agent.' },
        change: { source: evidence, target: 'draft.md', before: `${word} disputed line.`, after: `${word} corrected line.` },
      }))
      state = call('check', { run_id: id, check: { name: 'capture-integrity', status: 'complete', sources: [evidence], findings, producer: 'fixture', at: new Date().toISOString() } }, state.revision).state
      await page.route('**/api/**', async route => {
        const url = new URL(route.request().url())
        if (!url.pathname.startsWith('/api/')) return route.continue()
        if (url.pathname === '/api/session-workflow/command') {
          const body = route.request().postDataJSON()
          try { return await route.fulfill({ json: call(body.operation, body.payload, body.expected_revision) }) }
          catch (error) { return await route.fulfill({ status: 409, json: { error: String(error) } }) }
        }
        return route.fulfill({ json: url.pathname === '/api/config/' ? { resolved: { campaign_dir: campaign, runtime: { session_dir: session } } } : url.pathname === '/api/config/models' ? { models: [], backends: [], codex_reasoning_efforts: [], claude_code_efforts: [] } : {} })
      })
      await page.goto(`/workflow/cycle?session=session&run=${id}`)
      const first = page.getByRole('article', { name: 'Finding f1', exact: true })
      const second = page.getByRole('article', { name: 'Finding f2', exact: true })
      const third = page.getByRole('article', { name: 'Finding f3', exact: true })
      await expect(first.getByRole('button', { name: 'Approve', exact: true })).toBeEnabled()
      await first.getByRole('button', { name: 'Approve', exact: true }).click()
      await expect(first.getByRole('button', { name: 'Save approval' })).toBeDisabled()
      expect(call('export', { run_id: id }).decisions).toHaveLength(0)
      await first.getByLabel('Your name for this decision').fill('Reviewing human')
      await first.getByRole('button', { name: 'Save approval' }).click()
      await expect(first.getByText('Saved Approved by Reviewing human:', { exact: false })).toBeVisible()
      expect(call('export', { run_id: id }).decisions[0].finding_id).toBe('f1')
      expect(call('status').state.runs[0].approval).toBeNull()
      expect(call('status').state.applications).toHaveLength(0)
      await second.getByRole('button', { name: 'Reject', exact: true }).click()
      await expect(second.getByText('Saved Rejected by Reviewing human:', { exact: false })).toBeVisible()
      await third.getByRole('button', { name: 'Discuss', exact: true }).click()
      await expect(third.getByRole('button', { name: 'Save discussion' })).toBeDisabled()
      await third.getByLabel('Question or intended wording for the agent').fill('The location should stay uncertain. Please explain the evidence.')
      expect(call('export', { run_id: id }).decisions).toHaveLength(2)
      await third.getByRole('button', { name: 'Save discussion' }).click()
      await expect(third.getByText('Saved Discuss by Reviewing human:', { exact: false })).toBeVisible()
      let exported = call('export', { run_id: id })
      expect(exported.decisions.map((d: any) => d.decision)).toEqual(['approve', 'reject', 'discuss'])
      expect(exported.decisions[2].rationale).toContain('Please explain the evidence.')
      expect(call('status').runs[0].unresolved_findings).toEqual(['f3'])
      await page.reload()
      await expect(third.getByText('Saved Discuss by Reviewing human:', { exact: false })).toBeVisible()
      // A saved Discuss must not prevent Approve, including after a reload clears the name field.
      await third.getByRole('button', { name: 'Approve', exact: true }).click()
      await third.getByLabel('Your name for this decision').fill('Reviewing human')
      await third.getByRole('button', { name: 'Save approval' }).click()
      await expect(third.getByText('Saved Approved by Reviewing human:', { exact: false })).toBeVisible()
      expect(call('export', { run_id: id }).decisions.at(-1).decision).toBe('approve')
      expect(call('status').runs[0].unresolved_findings).toEqual([])
      expect(call('status').state.runs[0].approval).toBeNull()
      await third.getByRole('button', { name: 'Discuss', exact: true }).click()
      await third.getByLabel('Question or intended wording for the agent').fill('The location should stay uncertain. Please explain the evidence.')
      await third.getByRole('button', { name: 'Save discussion' }).click()
      await expect(third.getByText('Saved Discuss by Reviewing human:', { exact: false })).toBeVisible()
      await page.getByRole('button', { name: 'Copy handoff for agent' }).click()
      expect(await page.getByLabel('Agent handoff').inputValue()).toContain('f3: discuss — The location should stay uncertain.')
      expect(await page.getByLabel('Agent handoff').inputValue()).toContain(id)
      await page.getByLabel('Scene', { exact: true }).selectOption('Scene 2')
      await expect(first).toHaveCount(0)
      await expect(second).toBeVisible()
      await page.getByLabel('Your name').fill('Reviewing human')
      writeFileSync(join(session, 'source.md'), 'Changed source from another collaborator')
      await second.getByRole('button', { name: 'Approve', exact: true }).click()
      await expect(second.getByText('Saved Rejected by Reviewing human:', { exact: false })).toBeVisible()
      expect(call('export', { run_id: id }).decisions).toHaveLength(5)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    } finally { rmSync(campaign, { recursive: true, force: true }) }
  })
}
