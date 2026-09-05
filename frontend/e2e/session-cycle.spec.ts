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
    await expect(page.getByLabel('Your name')).toHaveCount(0)
    await expect(page.getByLabel('Rationale', { exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: 'I have reviewed this draft — approve' }).click()
    await expect(page.getByRole('heading', { name: 'capture · approved' })).toBeVisible()
    expect(call('status').state.runs[0].approval.actor).toBe('local user')
    const savedRevision = call('status').state.revision
    const nextPrompt = page.getByLabel('Next step for agent')
    await expect(nextPrompt).toBeVisible()
    expect(await nextPrompt.inputValue()).toContain('through the identify stage and stop at human review')
    expect(await nextPrompt.inputValue()).toContain(join(campaign, 'config.yaml'))
    expect(await nextPrompt.inputValue()).toContain(session)
    expect(await nextPrompt.inputValue()).toContain(id)
    await page.getByRole('button', { name: 'Copy next-step prompt' }).click()
    expect(call('status').state.revision).toBe(savedRevision)
    expect(call('status').state.runs).toHaveLength(1)

    await page.reload()
    await expect(page.getByRole('heading', { name: 'capture · approved' })).toBeVisible()
    writeFileSync(join(session, 'source.md'), 'Changed by a CLI collaborator')
    await page.getByRole('button', { name: 'Load / refresh' }).click()
    await expect(page.getByRole('heading', { name: 'capture · stale' })).toBeVisible()
    await expect(page.getByText('changed or missing: source.md')).toBeVisible()
    await expect(nextPrompt).toHaveCount(0)
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
      await expect(first.getByText('Saved Approved:', { exact: false })).toBeVisible()
      expect(call('export', { run_id: id }).decisions[0].finding_id).toBe('f1')
      expect(call('status').state.runs[0].approval).toBeNull()
      expect(call('status').state.applications).toHaveLength(0)
      await second.getByRole('button', { name: 'Reject', exact: true }).click()
      await expect(second.getByText('Saved Rejected:', { exact: false })).toBeVisible()
      await third.getByRole('button', { name: 'Discuss', exact: true }).click()
      await expect(third.getByText('Saved Discuss:', { exact: false })).toBeVisible()
      expect(call('status').runs[0].unresolved_findings).toEqual(['f3'])
      await third.getByLabel('Optional question or intended wording for the agent').fill('The location should stay uncertain. Please explain the evidence.')
      expect(call('export', { run_id: id }).decisions).toHaveLength(3)
      await third.getByRole('button', { name: 'Save note' }).click()
      await expect(third.getByText('Saved Discuss:', { exact: false })).toBeVisible()
      let exported = call('export', { run_id: id })
      expect(exported.decisions.map((d: any) => d.decision)).toEqual(['approve', 'reject', 'discuss', 'discuss'])
      expect(exported.decisions[3].rationale).toContain('Please explain the evidence.')
      expect(call('status').runs[0].unresolved_findings).toEqual(['f3'])
      await page.reload()
      await expect(third.getByText('Saved Discuss:', { exact: false })).toBeVisible()
      // A saved Discuss can become Approve with one click after reload.
      await third.getByRole('button', { name: 'Approve', exact: true }).click()
      await expect(third.getByText('Saved Approved:', { exact: false })).toBeVisible()
      expect(call('export', { run_id: id }).decisions.at(-1).decision).toBe('approve')
      expect(call('status').runs[0].unresolved_findings).toEqual([])
      expect(call('status').state.runs[0].approval).toBeNull()
      await third.getByRole('button', { name: 'Discuss', exact: true }).click()
      await third.getByLabel('Optional question or intended wording for the agent').fill('The location should stay uncertain. Please explain the evidence.')
      await third.getByRole('button', { name: 'Save note' }).click()
      await expect(third.getByText('Saved Discuss:', { exact: false })).toBeVisible()
      await page.getByRole('button', { name: 'Copy handoff for agent' }).click()
      expect(await page.getByLabel('Agent handoff').inputValue()).toContain('f3: discuss — The location should stay uncertain.')
      expect(await page.getByLabel('Agent handoff').inputValue()).toContain(id)
      await page.getByLabel('Scene', { exact: true }).selectOption('Scene 2')
      await expect(first).toHaveCount(0)
      await expect(second).toBeVisible()
      writeFileSync(join(session, 'source.md'), 'Changed source from another collaborator')
      await second.getByRole('button', { name: 'Approve', exact: true }).click()
      await expect(second.getByText('Saved Rejected:', { exact: false })).toBeVisible()
      expect(call('export', { run_id: id }).decisions).toHaveLength(7)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    } finally { rmSync(campaign, { recursive: true, force: true }) }
  })
}
