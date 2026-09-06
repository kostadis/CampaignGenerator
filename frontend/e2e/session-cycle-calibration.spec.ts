import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

for (const width of [1280, 390]) {
  test(`calibration survives reload and CLI handoff without approving a draft at ${width}px`, async ({ page }) => {
    test.setTimeout(90000)
    await page.setViewportSize({ width, height: 800 })
    const campaign = mkdtempSync(join(tmpdir(), 'cycle-calibration-browser-'))
    const session = join(campaign, 'session')
    mkdirSync(session)
    writeFileSync(join(campaign, 'config.yaml'), '{}')
    writeFileSync(join(session, '01.md'), 'So, hello. Well, goodbye.')
    writeFileSync(join(session, '02.md'), 'Another scene.')
    writeFileSync(join(session, 'voice.md'), 'Plain voice.')
    const call = (op: string, payload: object = {}, revision?: number) => {
      const args = [op, '--campaign-dir', campaign, '--session-dir', 'session', '--config', join(campaign, 'config.yaml'), '--json', '--request-json', JSON.stringify(payload)]
      if (revision !== undefined && revision !== null) args.push('--expected-revision', String(revision))
      return JSON.parse(execFileSync(resolve('../.venv/bin/session_workflow'), args, { encoding: 'utf8' }))
    }
    try {
      call('init')
      execFileSync(resolve('../.venv/bin/python'), ['-c', `
from pathlib import Path
import sys
from session_doc.workflow.engine import Engine
from session_doc.workflow.models import Run, Generation
from session_doc.workflow.storage import now
root = Path(sys.argv[1])
e = Engine(root / 'session', root)
s = e.store.load()
refs = [e.store.preserve(root / 'session' / p, label='source') for p in ['01.md', '02.md', 'voice.md']]
r = Run(id='calibration-test', stage='voice-smooth', selection=['01.md','02.md'], inputs=refs, generation=Generation(backend='native-agent', model='test', producer='fixture'), started_at=now(), required_checks=['voice-smooth'])
s.runs.append(r)
e.store.save(s, expected_revision=s.revision)
p = root / 'session/.session-workflow/work/calibration-test/review/01.md'
p.parent.mkdir(parents=True)
p.write_text('Hello. Goodbye.')
sample = e.store.preserve(p, label='derived')
report = {'title':'Voice smoothing calibration', 'method':'Fixture sample', 'authorities':[refs[2].model_dump()], 'cards':[]}
for i, (before, after, category) in enumerate([('So, hello.', 'Hello.', 'Filler removal'), ('Well, goodbye.', 'Goodbye.', 'Grammar repair')]):
 report['cards'].append(dict(id=f'c{i+1}', category=category, scene='01', speaker='GM', location=f'Line {i+1}', source=refs[0].model_dump(), sample=sample.model_dump(), before=before, after=after, rationale='A representative example.', risk='Meaning needs review.' if i else ''))
e.mutate('calibration-register', {'run_id':r.id, 'report':report}, e.store.load().revision)
`, campaign])
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
      await page.goto('/workflow/cycle?session=session&run=calibration-test')
      const panel = page.getByRole('region', { name: 'Voice smoothing calibration', exact: true })
      await expect(panel).toBeVisible()
      const first = page.getByRole('article', { name: 'Calibration c1', exact: true })
      const second = page.getByRole('article', { name: 'Calibration c2', exact: true })
      await expect(first.getByText('So, hello.', { exact: true })).toBeVisible()
      await expect(panel.getByRole('button', { name: 'Use this calibration' })).toBeDisabled()
      await expect(page.getByRole('button', { name: 'I have reviewed this draft — approve' })).toHaveCount(0)
      await first.getByRole('button', { name: 'Approve', exact: true }).click()
      await expect(first.getByText('Saved Approved:', { exact: false })).toBeVisible()
      await second.getByRole('button', { name: 'Discuss', exact: true }).click()
      await second.getByLabel('Optional question or intended wording for the agent').fill('Please explain the voice choice.')
      await second.getByRole('button', { name: 'Save note' }).click()
      await expect(second.getByText('Saved Discuss: Please explain the voice choice.')).toBeVisible()
      await page.reload()
      await expect(second.getByText('Saved Discuss: Please explain the voice choice.')).toBeVisible()
      await expect(panel.getByRole('button', { name: 'Use this calibration' })).toBeDisabled()
      await page.getByRole('button', { name: 'Copy handoff for agent' }).click()
      expect(await page.getByLabel('Agent handoff').inputValue()).toContain('c2: discuss — Please explain the voice choice.')
      await second.getByRole('button', { name: 'Reject', exact: true }).click()
      await expect(second.getByText('Saved Rejected — keep original:', { exact: false })).toBeVisible()
      await expect(panel.getByRole('button', { name: 'Use this calibration' })).toBeEnabled()
      await panel.getByRole('button', { name: 'Use this calibration' }).click()
      await expect(panel.getByText('Calibration saved.', { exact: false })).toBeVisible()
      let state = call('status').state
      expect(state.runs[0].status).toBe('pending_agent')
      expect(state.runs[0].approval).toBeNull()
      expect(state.runs[0].outputs).toEqual([])
      await page.reload()
      await expect(panel.getByText('Calibration saved.', { exact: false })).toBeVisible()
      expect(call('calibration-export', { run_id: 'calibration-test' }).calibration.approved).toBe(true)
      await first.getByRole('button', { name: 'Discuss', exact: true }).click()
      await expect(panel.getByRole('button', { name: 'Use this calibration' })).toBeDisabled()
      expect(call('calibration-export', { run_id: 'calibration-test' }).calibration.approved).toBe(false)
      await panel.getByLabel('Only flagged examples').check()
      await expect(first).toHaveCount(0)
      await expect(second).toBeVisible()
      writeFileSync(join(session, 'voice.md'), 'Changed rule authority')
      await page.getByRole('button', { name: 'Load / refresh' }).click()
      await expect(page.getByRole('heading', { name: 'voice-smooth · stale', exact: true })).toBeVisible()
      await expect(second.getByRole('button', { name: 'Approve', exact: true })).toBeDisabled()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    } finally { rmSync(campaign, { recursive: true, force: true }) }
  })
}
