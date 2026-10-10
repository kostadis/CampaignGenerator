import { expect, test } from '@playwright/test'
import { installAppShellMocks } from './fixtures/appShell'

async function shell(page:any) {
  await installAppShellMocks(page, { catchAll: true })
  await page.route('**/api/grounding/config', route => route.fulfill({ json: {
    summary_native: { summaries_dir: 'docs/summaries', range_since: 1, range_until: 3 },
  } }))
  await page.route('**/api/grounding/summary-native/chapters', route => route.fulfill({ json: { present:[1,2,3], files:[], duplicate_chapters:[] } }))
  await page.route('**/api/grounding/summary-native/state', route => route.fulfill({ json: {
    extract:{present:false,complete:false,stale:false,chunks:[],totals:{}}, audit:{present:false,complete:false,stale:false}, budgets:{}, annotations:{}, threads:{present:false,pending_groups:0},
  } }))
  await page.route('**/api/grounding/summary-native/report', route => route.fulfill({ status:404, json:{} }))
  await page.route('**/api/grounding/summary-native/drafts', route => route.fulfill({ json:[] }))
}

test('claims panel confirms exact scope and renders blocked CLI-shaped coverage', async ({ page }) => {
  await shell(page)
  let savePayload:any
  let extractPayload:any
  await page.route('**/api/grounding/summary-native/claims/select', route => route.fulfill({ json: {
    ok:false, code:'CLAIMS_SCOPE_UNRESOLVED', message:'Confirm every required source and selected chunk.', data:{selection:{
      sources:[{source_id:'source-1',path:'docs/private/gm.md',source_audience:'gm',applicability:'mapping_evidence'}],
      chunks:[{chunk_id:'chunk-1',locator:'bytes:0-40',sha256:'a'.repeat(64)}],
    }},
  } }))
  await page.route('**/api/grounding/summary-native/claims/selection/save', async route => {
    savePayload=route.request().postDataJSON()
    await route.fulfill({json:{ok:true,code:'OK',message:'saved',data:{path:'private/selection.json'}}})
  })
  await page.route('**/api/grounding/summary-native/claims/extract', async route => {
    extractPayload=route.request().postDataJSON()
    await route.fulfill({json:{ok:true,code:'OK',message:'extracted',data:{path:'private/runs/extracted.json'}}})
  })
  await page.route('**/api/grounding/summary-native/claims/check', route => route.fulfill({ json: {
    ok:false, code:'CLAIMS_INCOMPLETE', message:'One required semantic mapping remains unresolved.', data:{
      paths:['docs/summary_native/checks/report.json'], report:{outcome:'blocked',findings:[{finding_id:'f-1'}],coverage_limitations:['No reviewed identity for one candidate.']},
    },
  } }))
  await page.goto('/grounding/summary-native')
  const panel=page.locator('[data-test="grounding-claims"]')
  await panel.getByRole('button',{name:'Load exact source selection'}).click()
  await expect(panel.getByRole('alert')).toContainText('Confirm every required source')
  await panel.getByText('docs/private/gm.md').click(); await panel.getByText('bytes:0-40').click()
  await panel.getByLabel('Confirm this exact chunk scope').check()
  await expect(panel.getByRole('button',{name:'Save exact confirmation'})).toBeEnabled()
  await panel.getByRole('button',{name:'Save exact confirmation'}).click()
  expect(savePayload.reviewer).toBe('GM')
  expect(savePayload.selection.sources.map((item:any)=>item.source_id)).toEqual(['source-1'])
  expect(savePayload.selection.chunks.map((item:any)=>item.chunk_id)).toEqual(['chunk-1'])
  await panel.getByLabel('Run optional model extraction').check()
  await panel.getByLabel('Backend').fill('local-backend')
  await panel.getByLabel('Model',{exact:true}).fill('claims-model')
  await panel.getByLabel('Maximum output tokens').fill('777')
  await panel.getByLabel('Chunk character bound').fill('2222')
  await panel.getByLabel('Force a fresh extraction run').check()
  await panel.getByRole('button',{name:'Extract selected chunks'}).click()
  expect(extractPayload).toEqual({selection:'private/selection.json',backend:'local-backend',model:'claims-model',max_tokens:777,chunk_chars:2222,force:true})
  await panel.getByRole('button',{name:'Run deterministic checks'}).click()
  await expect(panel.locator('[data-test="claims-report"]')).toContainText('blocked')
  await expect(panel.locator('[data-test="claims-report"]')).toContainText('No reviewed identity')
  // The review queue lives on its own page; this page only links to it.
  await expect(page.getByRole('heading',{name:'Shared review'})).toHaveCount(0)
  await expect(page.getByRole('link',{name:'Shared review'}).first()).toHaveAttribute('href','/grounding/review')
  const promotion=page.locator('[data-test="grounding-promotion-preview"]')
  await expect(promotion.locator('[data-test="promotion-review"]')).toHaveValue('claims-review')
  await expect(promotion.locator('[data-test="promotion-report"]')).toHaveValue('docs/summary_native/checks/report.json')
})

test('empty discovery materializes explicit chunks and review uses persisted import artifact', async ({page}) => {
  await shell(page)
  let reviewPayload:any,extractPayload:any
  await page.route('**/api/grounding/summary-native/claims/select', route => route.fulfill({json:{ok:true,code:'OK',message:'selected',data:{selection:{sources:[{source_id:'s1',path:'docs/a.md',source_audience:'gm',applicability:'mapping_evidence',required:true}],chunks:[]}}}}))
  await page.route('**/api/grounding/summary-native/claims/selection/chunks', async route => {
    const body=route.request().postDataJSON(); expect(body.source_ids).toEqual(['s1'])
    await route.fulfill({json:{ok:true,code:'OK',message:'chunks',data:{selection:{...body.selection,chunks:[{chunk_id:'c1',source_id:'s1',locator:'bytes:0-25',sha256:'b'.repeat(64)}]}}}})
  })
  await page.route('**/api/grounding/summary-native/claims/selection/save', route => route.fulfill({json:{ok:true,code:'OK',message:'saved',data:{path:'private/selection.json'}}}))
  await page.route('**/api/grounding/summary-native/claims/extract', async route => {extractPayload=route.request().postDataJSON();await route.fulfill({json:{ok:true,code:'OK',message:'extracted',data:{path:'private/runs/run.json'}}})})
  await page.route('**/api/grounding/summary-native/claims/import', route => route.fulfill({json:{ok:true,code:'OK',message:'imported',data:{path:'private/imports/candidates.json'}}}))
  await page.route('**/api/grounding/summary-native/claims/review', async route => {reviewPayload=route.request().postDataJSON();await route.fulfill({json:{ok:true,code:'OK',message:'reviewed',data:{}}})})
  await page.goto('/grounding/summary-native')
  const panel=page.locator('[data-test="grounding-claims"]')
  await panel.getByRole('button',{name:'Load exact source selection'}).click()
  await panel.getByText('docs/a.md').click()
  await panel.getByRole('button',{name:'Materialize whole-source chunks'}).click()
  await expect(panel.getByText('bytes:0-25')).toBeVisible()
  await panel.getByLabel('Confirm this exact chunk scope').check()
  await panel.getByRole('button',{name:'Save exact confirmation'}).click()
  await panel.getByLabel('Run optional model extraction').check()
  await panel.getByRole('button',{name:'Extract selected chunks'}).click()
  expect(extractPayload).toEqual({selection:'private/selection.json'})
  await panel.getByLabel('Candidate import file').fill('incoming.json')
  await panel.getByRole('button',{name:'Import candidates'}).click()
  await expect(panel.getByLabel('Persisted candidate artifact')).toHaveValue('private/imports/candidates.json')
  await panel.getByRole('button',{name:'Create or refresh claim review'}).click()
  expect(reviewPayload.candidates).toBe('private/imports/candidates.json')
})

test('zero-chunk no-model selection saves while required closure remains intact', async ({ page }) => {
  await shell(page)
  let payload:any
  await page.route('**/api/grounding/summary-native/claims/select', route => route.fulfill({json:{
    ok:true,code:'OK',message:'selected',data:{selection:{
      sources:[{source_id:'required-1',path:'docs/required.md',source_audience:'gm',applicability:'fact_authority',required:true}],
      chunks:[],
    }},
  }}))
  await page.route('**/api/grounding/summary-native/claims/selection/save', async route => {
    payload=route.request().postDataJSON()
    await route.fulfill({json:{ok:true,code:'OK',message:'saved',data:{path:'private/zero.json'}}})
  })
  await page.goto('/grounding/summary-native')
  const panel=page.locator('[data-test="grounding-claims"]')
  await panel.getByRole('button',{name:'Load exact source selection'}).click()
  await panel.getByText('docs/required.md').click()
  await panel.getByLabel('Confirm this exact chunk scope').check()
  await panel.getByRole('button',{name:'Save exact confirmation'}).click()
  expect(payload.selection.sources).toHaveLength(1)
  expect(payload.selection.sources[0].required).toBe(true)
  expect(payload.selection.chunks).toEqual([])
  await panel.getByLabel('Run optional model extraction').check()
  await expect(panel.getByRole('button',{name:'Extract selected chunks'})).toBeDisabled()
  await expect(panel).toContainText('Empty scope never expands implicitly')
})

test('selection-null diagnostics and panel remain contained at narrow width', async ({ page }) => {
  await page.setViewportSize({width:320,height:760}); await shell(page)
  await page.route('**/api/grounding/summary-native/claims/select', route => route.fulfill({ json: {
    ok:false, code:'CLAIMS_SOURCE_MISSING', message:'A required GM source is missing.', data:{selection:null},
  } }))
  await page.goto('/grounding/summary-native')
  const panel=page.locator('[data-test="grounding-claims"]')
  await panel.getByRole('button',{name:'Load exact source selection'}).click()
  await expect(panel.locator('[data-test="claims-selection-null"]')).toBeVisible()
  await expect(panel.getByRole('alert')).toContainText('required GM source is missing')
  const box=await panel.boundingBox(); expect(box).not.toBeNull(); expect(box!.x+box!.width).toBeLessThanOrEqual(320)
})
