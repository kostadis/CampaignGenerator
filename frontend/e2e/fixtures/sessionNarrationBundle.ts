import type { Page } from '@playwright/test'

export const narrationBundleScenes = [
  { index: 1, narrator: 'Alice', scene: 'The First Door', focus: 'Opening the sealed archive', has_extraction: true, has_output: false, has_scrubbed: false, filename: '01_the_first_door.md', reviewed: true },
  { index: 2, narrator: 'Bob', scene: 'A Name in the Ledger', focus: 'Recognizing the hidden signature', has_extraction: true, has_output: true, has_scrubbed: false, filename: '02_a_name_in_the_ledger.md', reviewed: true },
  { index: 3, narrator: 'Alice', scene: 'Rain on the Quay', focus: 'Leaving with the evidence', has_extraction: true, has_output: false, has_scrubbed: false, filename: '03_rain_on_the_quay.md', reviewed: true },
]

export interface BundleTerminal {
  returncode: number
  status: string
  run_id: string
  written_count: number
  requested_count: number
  missing: unknown[]
  rejected: unknown[]
  error?: string
}

export const bundleSuccess: BundleTerminal = {
  returncode: 0,
  status: 'success',
  run_id: 'ui-success-001',
  written_count: 3,
  requested_count: 3,
  missing: [],
  rejected: [],
}

export const bundlePartial: BundleTerminal = {
  returncode: 3,
  status: 'partial',
  run_id: 'ui-partial-001',
  written_count: 1,
  requested_count: 3,
  missing: [
    { index: 2, scene_name: 'A Name in the Ledger' },
    { index: 3, scene_name: 'Rain on the Quay' },
  ],
  rejected: [],
}

export const bundleZeroWritePartial: BundleTerminal = {
  returncode: 3,
  status: 'partial',
  run_id: 'ui-zero-write-partial-001',
  written_count: 0,
  requested_count: 3,
  missing: [
    { index: 1, scene_name: 'The First Door' },
    { index: 2, scene_name: 'A Name in the Ledger' },
    { index: 3, scene_name: 'Rain on the Quay' },
  ],
  rejected: [],
}

export const bundleUnreconcilable: BundleTerminal = {
  returncode: 4,
  status: 'unreconcilable',
  run_id: 'ui-unreconcilable-001',
  written_count: 0,
  requested_count: 3,
  missing: [],
  rejected: [{ code: 'OUT_OF_ORDER', message: 'sections arrived out of plan order' }],
}

function editorConfig() {
  return {
    campaign_dir: '/campaign',
    session_dir: '/campaign/summaries/session-one',
    work_dir: '/campaign',
    paths_stored: {
      session_recap: 'gm-assist.md', session_summary: 'session-summary.md',
      scene_extractions_dir: 'scene_extractions', narration_dir: 'narration',
      output_dir: '.', party: null, voice_dir: null, examples_dir: null, genre_file: null,
    },
    paths: {
      session_recap: '/campaign/summaries/session-one/gm-assist.md',
      session_summary: '/campaign/summaries/session-one/session-summary.md',
      scene_extractions_dir: '/campaign/summaries/session-one/scene_extractions',
      narration_dir: '/campaign/summaries/session-one/narration',
      output_dir: '/campaign/summaries/session-one',
      party: null, voice_dir: null, examples_dir: null, genre_file: null,
    },
    extract: { tokens: 8192, batch_scenes: null, batch_tokens: 32000 },
    narrate: { tokens: 16000, batch_tokens: 48000, prose_mode: false, reflections: false, context: [] },
    backends: { active: 'anthropic', anthropic: { backend: 'anthropic', batch: false } },
    profiles: [], active_profile: null, warnings: [], genre: null,
  }
}

function pipelineStatus() {
  const ready = { status: 'ok', ago: '1m', mtime: 1 }
  return {
    enhance: ready,
    extract: ready,
    plan: ready,
    narrate: { ...ready, count_done: 1, count_total: 3 },
    verify: { ...ready, verified: 4, near: 0, unverified: 0 },
  }
}

function extractionDetail(index: number) {
  const scene = narrationBundleScenes.find(item => item.index === index) ?? narrationBundleScenes[0]
  const path = `/campaign/summaries/session-one/scene_extractions/${scene.filename}`
  return {
    exists: true,
    content: `- reviewed source for ${scene.scene}\n`,
    editor_readable: true,
    editor_error: null,
    scene_label: `Scene ${scene.index}: ${scene.scene}`,
    estimated_tokens: 1000,
    narrate_source: {
      scene_index: scene.index,
      scene_name: scene.scene,
      smoothed: { layer: 'smoothed', directory: '/campaign/summaries/session-one/scene_extractions_smoothed', directory_exists: false, path: null, filename: null, exists: false, readable: null, reason: null },
      raw: { layer: 'raw', directory: '/campaign/summaries/session-one/scene_extractions', directory_exists: true, path, filename: scene.filename, exists: true, readable: true, reason: null },
      active_layer: 'raw', active_file: path, status: 'ready', available: true,
      fallback_to_raw: true, message: 'Using raw extraction.',
    },
  }
}

function sseBody(terminal: BundleTerminal): string {
  return [
    `event: command\ndata: ${JSON.stringify('$ sd_narrate --batch-scenes --scene 1 2 3')}\n\n`,
    `data: ${JSON.stringify('Bundled narration exchange started.\n')}\n\n`,
    `event: done\ndata: ${JSON.stringify(terminal)}\n\n`,
  ].join('')
}

export interface InstalledBundleMocks {
  bundleRequests: string[]
  mutations: string[]
  sceneRequests: { count: number }
}

export async function installSessionNarrationBundleMocks(
  page: Page,
  terminal: BundleTerminal = bundleSuccess,
): Promise<InstalledBundleMocks> {
  const bundleRequests: string[] = []
  const mutations: string[] = []
  const sceneRequests = { count: 0 }

  await page.route('**/api/editor/narrate-bundle?*', async route => {
    bundleRequests.push(route.request().url())
    mutations.push('bundle')
    await route.fulfill({ status: 200, contentType: 'text/event-stream', headers: { 'Cache-Control': 'no-cache' }, body: sseBody(terminal) })
  })
  await page.route('**/api/editor/extraction/*/prev', route => route.fulfill({ json: { exists: false, content: '' } }))
  await page.route('**/api/editor/extraction/*', async route => {
    const index = Number(new URL(route.request().url()).pathname.split('/').pop())
    if (route.request().method() === 'PUT') {
      mutations.push('save')
      return route.fulfill({ json: { ok: true } })
    }
    return route.fulfill({ json: extractionDetail(index) })
  })
  await page.route('**/api/editor/output/*', route => route.fulfill({ json: { exists: false, content: '' } }))
  await page.route('**/api/editor/scenes', route => {
    sceneRequests.count += 1
    return route.fulfill({ json: narrationBundleScenes })
  })
  await page.route('**/api/editor/pipeline-status', route => route.fulfill({ json: pipelineStatus() }))
  await page.route('**/api/editor/assembled-exists', route => route.fulfill({ json: { exists: false } }))
  await page.route('**/api/editor/config', route => {
    if (route.request().method() === 'PUT') mutations.push('config')
    return route.fulfill({ json: editorConfig() })
  })
  await page.route('**/api/config/', route => route.fulfill({ json: {
    campaign_id: 'campaign',
    resolved: { campaign_dir: '/campaign', runtime: { session_dir: '/campaign/summaries/session-one', default_backend: 'anthropic', default_model: 'claude-opus-5', default_models: {}, default_batch: false }, server: {}, nav: {} },
    migration_warnings: [],
  } }))
  await page.route('**/api/config/models', route => route.fulfill({ json: {
    models: ['claude-opus-5'], default: 'claude-opus-5',
    backends: ['anthropic', 'claude-code', 'codex-cli'], default_backend: 'anthropic',
    codex_reasoning_efforts: ['medium'], claude_code_efforts: ['medium'],
  } }))
  await page.route('**/api/config/status', route => route.fulfill({ json: { cwd: '/campaign' } }))
  await page.route('**/api/config/path-status?*', route => route.fulfill({ json: { exists: true, is_file: true, is_dir: false } }))
  await page.route('**/api/grounding/config', route => route.fulfill({ json: {} }))

  return { bundleRequests, mutations, sceneRequests }
}

export async function openReadySessionEditor(page: Page) {
  // Let the root store hydrate before mounting the editor. SessionDocEditor
  // intentionally reads its service config from that store on mount.
  await page.goto('/workflow/config')
  await page.waitForTimeout(100)
  await page.goto('/workflow/editor')
  await page.getByText('The First Door').waitFor()
}
