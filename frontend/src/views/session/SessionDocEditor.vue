<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useConfigStore } from '../../stores/config'
import { resolvePath, resolvePathList, resolvePathWithBase } from '../../utils/paths'
import { apiFetch, apiPut, apiPost } from '../../api/client'
import { connectSSE } from '../../api/sse'
import SceneList from '../../components/scene-editor/SceneList.vue'
import type { Scene } from '../../components/scene-editor/SceneList.vue'
import ExtractionEditor from '../../components/scene-editor/ExtractionEditor.vue'
import NarrationOutput from '../../components/scene-editor/NarrationOutput.vue'
import KnobDrawer from '../../components/scene-editor/KnobDrawer.vue'

const config = useConfigStore()
const router = useRouter()

// ── Editor config (driven by the KnobDrawer) ──────────────────────
const session = ref('')
const outputDir = ref('')
const sessionSummary = ref('')
const sceneExtractionsDir = ref('')
const narrationDir = ref('')
const party = ref('')
const voiceDir = ref('')
const examplesDir = ref('')
const context = ref('')
const narrateTokens = ref(16000)
const proseMode = ref(false)
const reflections = ref(false)
const genreFile = ref('')
const backend = ref<'anthropic' | 'dgx' | 'openrouter' | 'claude-code'>('anthropic')
const dgxEndpoint = ref('')
const dgxModel = ref('')
const openrouterModel = ref('')

// Drawer open/closed — always starts closed. The Config button opens it, and
// onMounted auto-opens it on a cold start (required fields missing). Not
// persisted: a stale persisted 'true' otherwise inverts the button's first
// click (it would close an already-open drawer).
const drawerOpen = ref(false)

// Server-side summary of the resolved genre rulebook — path, whether it
// exists, line/char counts and a preview (#276 fix 2). Display only: the
// drawer renders it read-only and the file is edited in an editor, not here.
// Recomputed from the store, so it refreshes with every config GET/PUT.
const genreInfo = computed(() => (config.editorConfig as any)?.genre ?? null)

// ── Field ← store.editorConfig (grouped GET /api/editor/config) ──
// Coerce an arbitrary backends.active value to one of the four known
// backends — shared by the initial hydration and profile activation.
function normalizeBackend(value: any): 'anthropic' | 'dgx' | 'openrouter' | 'claude-code' {
  return value === 'dgx' || value === 'openrouter' || value === 'claude-code' ? value : 'anthropic'
}

function loadConfigFields() {
  const ec = config.editorConfig
  const paths = ec?.paths ?? {}
  const narrate = ec?.narrate ?? {}
  const backends = ec?.backends ?? {}

  session.value = paths.session_recap || ''
  outputDir.value = paths.output_dir || config.resolved?.runtime?.session_dir || ''
  sessionSummary.value = paths.session_summary || 'session-summary.md'
  sceneExtractionsDir.value = paths.scene_extractions_dir || 'scene_extractions'
  narrationDir.value = paths.narration_dir || 'narration'
  party.value = paths.party || ''
  voiceDir.value = paths.voice_dir || ''
  examplesDir.value = paths.examples_dir || ''
  context.value = (narrate.context ?? []).join('\n')
  narrateTokens.value = narrate.tokens || 16000
  proseMode.value = !!narrate.prose_mode
  reflections.value = !!narrate.reflections
  genreFile.value = paths.genre_file || ''
  backend.value = normalizeBackend(backends.active)
  dgxEndpoint.value = backends.dgx?.endpoint || ''
  dgxModel.value = backends.dgx?.model || ''
  openrouterModel.value = backends.openrouter?.model || ''
}

// ── Auto-apply: debounce-PUT changes to /api/editor/config ───────
//
// The pre-flight config form is gone; every drawer field auto-saves on
// change. We debounce so rapid typing in a path field doesn't fire a PUT
// per keystroke. The PUT body is partial — only the fields included get
// updated.
const contextFiles = computed(() => resolvePathList(context.value))
const configReady = computed(() =>
  !!(session.value.trim() && sceneExtractionsDir.value.trim())
)

let applyTimer: ReturnType<typeof setTimeout> | null = null
let configHydrated = false

function buildEditorConfigPayload() {
  return {
    paths: {
      session_recap: resolvePath(session.value),
      session_summary: resolvePath(sessionSummary.value) || undefined,
      scene_extractions_dir: resolvePath(sceneExtractionsDir.value) || undefined,
      narration_dir: resolvePath(narrationDir.value) || undefined,
      party: resolvePath(party.value) || undefined,
      voice_dir: resolvePath(voiceDir.value) || undefined,
      examples_dir: resolvePath(examplesDir.value) || undefined,
      // Campaign-scoped, like the rulebook it points at (#276 fix 2).
      genre_file: resolvePathWithBase(genreFile.value, 'campaign') || undefined,
    },
    narrate: {
      context: contextFiles.value.length ? contextFiles.value : [],
      tokens: narrateTokens.value || undefined,
      prose_mode: proseMode.value || undefined,
      reflections: reflections.value || undefined,
    },
  }
}

async function applyConfig() {
  try {
    await config.updateEditor(buildEditorConfigPayload())
    if (configReady.value) {
      await loadScenes()
      await checkAssembled()
      await refreshPipeline()
    }
  } catch (e: any) {
    setStatus(`Config save failed: ${e?.message ?? 'unknown error'}`)
  }
}

function scheduleApply() {
  if (!configHydrated) return  // initial load — don't echo back to the server
  if (applyTimer) clearTimeout(applyTimer)
  applyTimer = setTimeout(applyConfig, 350)
}

watch(
  [session, outputDir, sessionSummary, sceneExtractionsDir, narrationDir,
   party, voiceDir, examplesDir, context,
   narrateTokens, proseMode, reflections, genreFile],
  scheduleApply,
)

async function persistBackend() {
  try {
    await config.updateEditor({ backends: { active: backend.value } })
  } catch {
    /* non-fatal — the next subprocess will still read the resolved config */
  }
}
watch(backend, persistBackend)

// DGX endpoint/model are free-text — debounce so per-keystroke edits don't
// spam updateEditor. Empty string persists as null ("use the runtime default").
let dgxPersistTimer: ReturnType<typeof setTimeout> | undefined
async function persistDgx() {
  try {
    await config.updateEditor({
      backends: {
        dgx: {
          endpoint: dgxEndpoint.value.trim() || null,
          model: dgxModel.value.trim() || null,
        },
      },
    })
  } catch {
    /* non-fatal — the next subprocess will still read the resolved config */
  }
}
watch([dgxEndpoint, dgxModel], () => {
  if (dgxPersistTimer) clearTimeout(dgxPersistTimer)
  dgxPersistTimer = setTimeout(persistDgx, 350)
})

// OpenRouter model is free-text — same debounce pattern as DGX. There is no
// user-configurable endpoint (OpenRouter uses its own fixed base URL).
let openrouterPersistTimer: ReturnType<typeof setTimeout> | undefined
async function persistOpenrouter() {
  try {
    await config.updateEditor({
      backends: { openrouter: { model: openrouterModel.value.trim() || null } },
    })
  } catch {
    /* non-fatal — the next subprocess will still read the resolved config */
  }
}
watch(openrouterModel, () => {
  if (openrouterPersistTimer) clearTimeout(openrouterPersistTimer)
  openrouterPersistTimer = setTimeout(persistOpenrouter, 350)
})

// ── Scene state ───────────────────────────────────────────────────
const scenes = ref<Scene[]>([])
const currentScene = ref<number | null>(null)
const extractionContent = ref('')
const sceneLabel = ref('')
const estimatedTokens = ref<number | null>(null)
const hasExtraction = ref(false)
const narrating = ref(false)
const scrubbing = ref(false)
const extracting = ref(false)
const enhancing = ref(false)
const planning = ref(false)
const verifying = ref(false)
const narrationOutput = ref('')
const statusMsg = ref('')
const assembledExists = ref(false)

const activeSSE = ref<EventSource | null>(null)

// ── Pipeline status (header strip) ────────────────────────────────
interface StageStatus {
  status: 'ok' | 'warn' | 'bad' | 'cold'
  ago: string | null
  mtime: number | null
  count?: number
  count_done?: number
  count_total?: number
  // Verify only. `null` means the report could not be read — which is NOT the
  // same as zero, and the strip must not render it as a pass.
  verified?: number | null
  near?: number | null
  unverified?: number | null
}
const pipeline = ref<{
  enhance: StageStatus
  extract: StageStatus
  plan: StageStatus
  narrate: StageStatus
  verify: StageStatus
} | null>(null)

const verifyLabel = computed(() => {
  const v = pipeline.value?.verify
  if (!v || v.status === 'cold') return '—'
  if (v.unverified == null) return '?'
  return v.unverified > 0 ? `${v.unverified}!` : 'ok'
})

const verifyTitle = computed(() => {
  const v = pipeline.value?.verify
  if (!v || v.status === 'cold') return 'Verify quotes · never run'
  if (v.unverified == null) return 'Verify quotes · report unreadable — re-run'
  return `Verify quotes · ${v.unverified} unverified, ${v.near ?? 0} near, ` +
         `${v.verified ?? 0} verified · ${v.ago ?? 'unknown age'}`
})

async function refreshPipeline() {
  if (!configReady.value) {
    pipeline.value = null
    return
  }
  try {
    pipeline.value = await apiFetch('/api/editor/pipeline-status')
  } catch {
    pipeline.value = null
  }
}

// ── Profiles (Stage-④ knob presets) ──────────────────────────────
interface ProfileEntry {
  name: string
  knobs: {
    narrate_tokens?: number
    prose_mode?: boolean
    reflections?: boolean
    narration_genre_file?: string
    backend?: 'anthropic' | 'dgx' | 'openrouter' | 'claude-code'
  }
}
const profiles = ref<ProfileEntry[]>([])
const activeProfileName = ref<string | null>(null)

function loadProfilesFromStore() {
  const ec = config.editorConfig
  profiles.value = Array.isArray(ec?.profiles) ? ec.profiles : []
  activeProfileName.value = ec?.active_profile ?? null
}

const currentKnobs = computed(() => ({
  narrate_tokens: narrateTokens.value,
  prose_mode: proseMode.value,
  reflections: reflections.value,
  narration_genre_file: genreFile.value,
  backend: backend.value,
}))

const activeProfile = computed(() =>
  profiles.value.find(p => p.name === activeProfileName.value) ?? null,
)

const profileDirty = computed(() => {
  const ap = activeProfile.value
  if (!ap) return false
  const c = currentKnobs.value
  const k = ap.knobs
  return (k.narrate_tokens ?? 16000) !== c.narrate_tokens
    || !!k.prose_mode !== c.prose_mode
    || !!k.reflections !== c.reflections
    || (k.narration_genre_file ?? '') !== c.narration_genre_file
    || (k.backend ?? 'anthropic') !== c.backend
})

// Re-hydrate the knob refs from a resolved editor config, e.g. after
// server-side profile activation. Replaces the old client-side
// applyProfileKnobs watcher-mirror.
//
// Profiles own exactly ONE path: `paths.genre_file`, the genre rulebook
// (#276 fix 2). Everything else under `paths` is session-scoped and stays
// out of profiles. It has to be re-hydrated here too, or activating a
// profile that switches rulebooks would leave the drawer showing the
// previous file — the stale-display half of the bug #220 is about.
function hydrateKnobsFromEditorConfig(ec: any) {
  const narrate = ec?.narrate ?? {}
  const backends = ec?.backends ?? {}
  narrateTokens.value = narrate.tokens ?? 16000
  proseMode.value = !!narrate.prose_mode
  reflections.value = !!narrate.reflections
  genreFile.value = ec?.paths?.genre_file || ''
  backend.value = normalizeBackend(backends.active)
}

async function activateProfileByName(name: string) {
  try {
    const ec = await config.activateProfile(name)
    hydrateKnobsFromEditorConfig(ec)
    loadProfilesFromStore()
  } catch (e: any) {
    setStatus(`Profile activation failed: ${e?.message ?? 'unknown error'}`)
  }
}

async function selectProfile(name: string) {
  if (name === '__new__') {
    const proposed = window.prompt('Profile name:')
    if (!proposed) return
    const trimmed = proposed.trim()
    if (!trimmed) return
    if (profiles.value.some(p => p.name === trimmed)) {
      setStatus(`Profile "${trimmed}" already exists.`)
      return
    }
    try {
      await config.createProfile({ name: trimmed, knobs: { ...currentKnobs.value } })
      await activateProfileByName(trimmed)
      setStatus(`Saved profile "${trimmed}".`)
    } catch (e: any) {
      setStatus(`Profile save failed: ${e?.message ?? 'unknown error'}`)
    }
    return
  }
  if (name === '') {
    try {
      await config.updateEditor({ active_profile: null })
      loadProfilesFromStore()
    } catch (e: any) {
      setStatus(`Profile save failed: ${e?.message ?? 'unknown error'}`)
    }
    return
  }
  await activateProfileByName(name)
}

async function saveProfileChanges() {
  if (!activeProfile.value || !activeProfileName.value) return
  const name = activeProfileName.value
  try {
    await config.updateProfile(name, { name, knobs: { ...currentKnobs.value } })
    loadProfilesFromStore()
    setStatus(`Updated profile "${name}".`)
  } catch (e: any) {
    setStatus(`Profile save failed: ${e?.message ?? 'unknown error'}`)
  }
}

function revertProfile() {
  if (activeProfileName.value) activateProfileByName(activeProfileName.value)
}

// ── Scene navigation ─────────────────────────────────────────────

async function loadScenes() {
  try {
    scenes.value = await apiFetch('/api/editor/scenes')
  } catch {
    scenes.value = []
  }
}

const currentSceneReviewed = computed(() => {
  if (currentScene.value == null) return false
  const s = scenes.value.find(sc => sc.index === currentScene.value)
  return !!s?.reviewed
})

async function setReviewed(reviewed: boolean) {
  if (currentScene.value == null) return
  await apiPut(`/api/editor/reviewed/${currentScene.value}`, { reviewed })
  await loadScenes()
}

async function selectScene(n: number) {
  currentScene.value = n
  await loadEditorScene(n)
}

async function loadEditorScene(n: number) {
  const data = await apiFetch(`/api/editor/extraction/${n}`)
  extractionContent.value = data.content || ''
  hasExtraction.value = data.exists
  sceneLabel.value = data.scene_label || `Scene ${n}`
  estimatedTokens.value = data.estimated_tokens || null

  try {
    await apiFetch(`/api/editor/output/${n}`)
  } catch { /* no output yet */ }
}

async function saveExtraction(content: string) {
  if (currentScene.value === null) return
  extractionContent.value = content
  await apiPut(`/api/editor/extraction/${currentScene.value}`, { content })
  await loadScenes()
}

async function reload() {
  if (currentScene.value !== null) {
    await loadEditorScene(currentScene.value)
    setStatus('Reloaded from disk.')
  }
}

async function narrate() {
  if (currentScene.value === null || narrating.value) return
  await saveExtraction(extractionContent.value)
  narrating.value = true
  narrationOutput.value = ''
  setStatus('Running narration...')

  activeSSE.value = connectSSE(`/api/editor/narrate/${currentScene.value}`, {
    onData(text) { narrationOutput.value += text },
    onDone(rc, error) {
      activeSSE.value = null
      narrating.value = false
      setStatus(rc === 0 ? 'Done.' : `Narration failed${error ? ': ' + error : ''}.`)
      loadScenes()
      refreshPipeline()
    },
    onError() {
      activeSSE.value = null
      narrating.value = false
      setStatus('Stream error — check terminal.')
    },
  })
}

async function scrubScene() {
  if (currentScene.value === null || scrubbing.value || narrating.value) return
  scrubbing.value = true
  narrationOutput.value = ''
  setStatus(`Scrubbing scene ${currentScene.value}...`)

  activeSSE.value = connectSSE(`/api/editor/scrub/${currentScene.value}`, {
    onData(text) { narrationOutput.value += text },
    onDone(rc, error) {
      activeSSE.value = null
      scrubbing.value = false
      setStatus(rc === 0
        ? `Scrubbed scene ${currentScene.value} — .scrubbed.md written.`
        : `Scrub failed${error ? ': ' + error : ''}.`)
      loadScenes()
      refreshPipeline()
    },
    onError() {
      activeSSE.value = null
      scrubbing.value = false
      setStatus('Stream error — check terminal.')
    },
  })
}

async function scrubAll() {
  if (scrubbing.value || narrating.value) return
  scrubbing.value = true
  narrationOutput.value = ''
  setStatus('Scrubbing all scene narrations...')

  activeSSE.value = connectSSE('/api/editor/scrub-all', {
    onData(text) { narrationOutput.value += text },
    onDone(rc, error) {
      activeSSE.value = null
      scrubbing.value = false
      setStatus(rc === 0
        ? 'Scrub-All complete — .scrubbed.md files written.'
        : `Scrub-All failed${error ? ': ' + error : ''}.`)
      loadScenes()
      refreshPipeline()
    },
    onError() {
      activeSSE.value = null
      scrubbing.value = false
      setStatus('Stream error — check terminal.')
    },
  })
}

async function runExtract() {
  if (extracting.value || narrating.value || enhancing.value || planning.value) return
  extracting.value = true
  narrationOutput.value = ''
  setStatus('Re-extracting quotes (Stage 2)...')

  // Batch (Message Batches API; 50% off list price) is no longer a
  // `?batch=1` query param the page decides here — it comes from the
  // resolved selection (app-wide, or this editor's own per-backend
  // override) the same way every other service's run does
  // (005-ui-batch-selection, T029). A batch submission shows up in the
  // streamed output itself ("Batch submitted: …") rather than needing to
  // be predicted here.
  activeSSE.value = connectSSE('/api/editor/extract?force=1', {
    onData(text) { narrationOutput.value += text },
    onDone(rc, error) {
      activeSSE.value = null
      extracting.value = false
      setStatus(rc === 0 ? 'Re-extraction complete.' : `Re-extraction failed${error ? ': ' + error : ''}.`)
      loadScenes()
      refreshPipeline()
    },
    onError() {
      activeSSE.value = null
      extracting.value = false
      setStatus('Stream error — check terminal.')
    },
  })
}

async function runPlan() {
  if (planning.value || enhancing.value || extracting.value || narrating.value) return
  planning.value = true
  narrationOutput.value = ''
  setStatus('Planning & consistency check (Stage 3)...')

  activeSSE.value = connectSSE('/api/editor/plan', {
    onData(text) { narrationOutput.value += text },
    onDone(rc, error) {
      activeSSE.value = null
      planning.value = false
      setStatus(rc === 0
        ? 'Plan & check complete — plan.md saved.'
        : `Plan & check failed${error ? ': ' + error : ''}.`)
      loadScenes()
      refreshPipeline()
    },
    onError() {
      activeSSE.value = null
      planning.value = false
      setStatus('Stream error — check terminal.')
    },
  })
}

async function runEnhance() {
  if (enhancing.value || extracting.value || narrating.value || planning.value) return
  enhancing.value = true
  narrationOutput.value = ''
  setStatus('Enhancing summary (Stage 1)...')

  // Same retirement as runExtract above — no `?batch=1`; the resolved
  // selection decides, and a batch submission announces itself in the
  // stream.
  activeSSE.value = connectSSE('/api/editor/enhance', {
    onData(text) { narrationOutput.value += text },
    onDone(rc, error) {
      activeSSE.value = null
      enhancing.value = false
      setStatus(rc === 0 ? 'Stage 1 complete — review session-summary.md.' : `Stage 1 failed${error ? ': ' + error : ''}.`)
      refreshPipeline()
    },
    onError() {
      activeSSE.value = null
      enhancing.value = false
      setStatus('Stream error — check terminal.')
    },
  })
}

async function runVerify() {
  if (enhancing.value || extracting.value || narrating.value || planning.value || verifying.value) return
  verifying.value = true
  narrationOutput.value = ''
  setStatus('Verifying quotes against the transcript...')

  // No batch/model params: this calls no model, so there is nothing to route
  // and nothing to discount.
  activeSSE.value = connectSSE('/api/editor/verify', {
    onData(text) { narrationOutput.value += text },
    onDone(rc, error) {
      activeSSE.value = null
      verifying.value = false
      // rc 1 means "ran, found unverified quotes" — the tool working, not a
      // failure. Only rc 2 (and stream errors) mean it could not run.
      if (rc === 0) setStatus('Quotes verified — none unverified.')
      else if (rc === 1) setStatus('Verification found unverified quotes — see quote_report.md.')
      else setStatus(`Verification could not run${error ? ': ' + error : ''}.`)
      refreshPipeline()
    },
    onError() {
      activeSSE.value = null
      verifying.value = false
      setStatus('Stream error — check terminal.')
    },
  })
}

async function openTypora(type: string) {
  if (currentScene.value === null) return
  try {
    await apiPost(`/api/editor/open/${type}/${currentScene.value}`)
  } catch {
    setStatus('File not found.')
  }
}

function gotoReview() {
  router.push('/workflow/editor/review')
}

function setStatus(msg: string) {
  statusMsg.value = msg
  if (msg) setTimeout(() => { if (statusMsg.value === msg) statusMsg.value = '' }, 5000)
}

function clearOutput() {
  narrationOutput.value = ''
}

async function checkAssembled() {
  // Kept as a no-op stub so older code paths calling it don't break;
  // the Review screen now handles assembled-state visibility.
  try {
    const data = await apiFetch('/api/editor/assembled-exists')
    assembledExists.value = data.exists
  } catch { /* ignore */ }
}

// ── Init ──────────────────────────────────────────────────────────
onMounted(async () => {
  // Hydrate form refs from the config store (the single source of truth —
  // ui.session_doc + runtime.session_dir), then mark `configHydrated` so
  // the watcher below doesn't echo the initial values back to the server.
  loadConfigFields()

  configHydrated = true

  loadProfilesFromStore()

  if (configReady.value) {
    // Config is already in sync with the server — just load the derived
    // views. Do NOT re-PUT here; that would just re-write what we loaded.
    await loadScenes()
    await checkAssembled()
    await refreshPipeline()
  } else {
    // Cold start — pop the drawer so the user can fill in required fields.
    drawerOpen.value = true
  }
})
</script>

<template>
  <div class="session-editor">
    <!-- Header -->
    <header class="editor-global-header">
      <h1>Session Doc</h1>

      <!-- Profile picker -->
      <div class="profile-picker" :title="activeProfileName ? `Active profile: ${activeProfileName}` : 'No profile selected'">
        <select
          class="profile-select"
          :value="activeProfileName ?? ''"
          @change="selectProfile(($event.target as HTMLSelectElement).value)"
        >
          <option value="">— no profile —</option>
          <option v-for="p in profiles" :key="p.name" :value="p.name">
            {{ p.name }}{{ activeProfileName === p.name && profileDirty ? ' *' : '' }}
          </option>
          <option value="__new__">＋ Save current as new…</option>
        </select>
        <button
          v-if="activeProfile && profileDirty"
          class="btn-sm profile-btn"
          @click="saveProfileChanges"
          title="Overwrite this profile with the current knob values"
        >Save</button>
        <button
          v-if="activeProfile && profileDirty"
          class="btn-sm profile-btn revert"
          @click="revertProfile"
          title="Discard local edits and re-apply the saved profile"
        >Revert</button>
      </div>

      <!-- Pipeline-status strip (read-only) -->
      <div v-if="pipeline" class="pipe-strip">
        <span class="pipe-stage" :title="`Enhance · ${pipeline.enhance.ago ?? 'never'}`">
          <span class="pipe-glyph">①</span>
          <span class="pipe-dot" :class="pipeline.enhance.status"></span>
          <span class="pipe-age">{{ pipeline.enhance.ago ?? '—' }}</span>
        </span>
        <span class="pipe-stage" :title="`Extract · ${pipeline.extract.ago ?? 'never'}`">
          <span class="pipe-glyph">②</span>
          <span class="pipe-dot" :class="pipeline.extract.status"></span>
          <span class="pipe-age">{{ pipeline.extract.ago ?? '—' }}</span>
        </span>
        <span class="pipe-stage" :title="`Plan · ${pipeline.plan.ago ?? 'never'}`">
          <span class="pipe-glyph">③</span>
          <span class="pipe-dot" :class="pipeline.plan.status"></span>
          <span class="pipe-age">{{ pipeline.plan.ago ?? '—' }}</span>
        </span>
        <span class="pipe-stage" :title="`Narrate · ${pipeline.narrate.count_done}/${pipeline.narrate.count_total}`">
          <span class="pipe-glyph">④</span>
          <span class="pipe-dot" :class="pipeline.narrate.status"></span>
          <span class="pipe-age">
            {{ pipeline.narrate.count_done ?? 0 }}/{{ pipeline.narrate.count_total ?? 0 }}
          </span>
        </span>
        <span class="pipe-stage" :title="verifyTitle">
          <span class="pipe-glyph">✓</span>
          <span class="pipe-dot" :class="pipeline.verify.status"></span>
          <span class="pipe-age">{{ verifyLabel }}</span>
        </span>
      </div>

      <span class="status-msg">{{ statusMsg }}</span>

      <span class="stage-group">
        <span class="stage-label">Stage 1</span>
        <button
          class="btn-neutral btn-sm"
          :disabled="!configReady || enhancing || extracting || narrating || planning"
          @click="runEnhance"
          title="Stage 1 — rebuild session-summary.md from VTT + gm-assist.md"
        >{{ enhancing ? 'Enhancing…' : 'Enhance Summary' }}</button>
      </span>

      <span class="stage-group">
        <span class="stage-label">Stage 2</span>
        <button
          class="btn-neutral btn-sm"
          :disabled="!configReady || enhancing || extracting || narrating || planning"
          @click="runExtract"
          title="Stage 2 — rebuild per-scene quote files from session-summary.md"
        >{{ extracting ? 'Re-extracting…' : 'Re-Extract Quotes' }}</button>
      </span>

      <span class="stage-group">
        <span class="stage-label">Verify</span>
        <button
          class="btn-neutral btn-sm"
          :disabled="!configReady || enhancing || extracting || narrating || planning || verifying"
          @click="runVerify"
          title="Check every quote against the transcript. Deterministic and free — calls no model. Nothing is auto-corrected; findings go to quote_report.md for you to review."
        >{{ verifying ? 'Verifying…' : 'Verify Quotes' }}</button>
      </span>

      <span class="stage-group">
        <span class="stage-label">Stage 3</span>
        <button
          class="btn-neutral btn-sm"
          :disabled="!configReady || planning || enhancing || extracting || narrating"
          @click="runPlan"
          title="Stage 3 — consistency check + plan + enhanced sections"
        >{{ planning ? 'Planning…' : 'Plan &amp; Check' }}</button>
      </span>

      <span class="stage-group">
        <span class="stage-label">Stage 4½</span>
        <button
          class="btn-success btn-sm"
          :disabled="!configReady || scrubbing || narrating"
          @click="scrubAll"
          title="Run the second-pass mechanical scrub over every scene narration."
        >{{ scrubbing ? 'Scrubbing…' : 'Scrub All' }}</button>
      </span>

      <span class="stage-group">
        <span class="stage-label">Final</span>
        <button
          class="btn-primary btn-sm"
          :disabled="!configReady"
          @click="gotoReview"
          title="Review every scene's status, knobs, and preview before assembling the doc"
        >Assemble →</button>
      </span>

      <button
        class="btn-neutral btn-sm config-btn"
        @click="drawerOpen = !drawerOpen"
        :class="{ active: drawerOpen }"
        title="Open config drawer"
      >Config ⚙</button>
    </header>

    <!-- Three-column layout -->
    <div v-if="configReady" class="columns">
      <SceneList
        :scenes="scenes"
        :current-scene="currentScene"
        @select="selectScene"
      />

      <div class="center-col">
        <ExtractionEditor
          :extraction-content="extractionContent"
          :scene-label="sceneLabel"
          :estimated-tokens="estimatedTokens"
          :default-narrate-tokens="narrateTokens"
          :has-extraction="hasExtraction"
          :current-scene="currentScene"
          :narrating="narrating"
          :extracting="extracting"
          :scrubbing="scrubbing"
          :prose-mode="proseMode"
          :reflections="reflections"
          :reviewed="currentSceneReviewed"
          @save-extraction="saveExtraction"
          @reload="reload"
          @narrate="narrate"
          @scrub="scrubScene"
          @open-typora="openTypora"
          @update:extraction-content="extractionContent = $event"
          @update:prose-mode="proseMode = $event"
          @update:reflections="reflections = $event"
          @update:reviewed="setReviewed"
        />
        <NarrationOutput
          :output="narrationOutput"
          :current-scene="currentScene"
          @clear="clearOutput"
        />
      </div>
    </div>

    <!-- Empty state — drives the user to fill in the drawer -->
    <div v-else class="empty-shell">
      <div class="empty-card">
        <h2>Set the session file to begin</h2>
        <p>The editor needs at least a <strong>GMassistant recap</strong> and a
        <strong>Scene extractions directory</strong>.</p>
        <button class="btn-primary" @click="drawerOpen = true">Open Config</button>
      </div>
    </div>

    <KnobDrawer
      v-model:open="drawerOpen"
      v-model:session="session"
      v-model:session-summary="sessionSummary"
      v-model:scene-extractions-dir="sceneExtractionsDir"
      v-model:narration-dir="narrationDir"
      v-model:output-dir="outputDir"
      v-model:party="party"
      v-model:voice-dir="voiceDir"
      v-model:examples-dir="examplesDir"
      v-model:context="context"
      v-model:backend="backend"
      v-model:dgx-endpoint="dgxEndpoint"
      v-model:dgx-model="dgxModel"
      v-model:openrouter-model="openrouterModel"
      v-model:narrate-tokens="narrateTokens"
      v-model:prose-mode="proseMode"
      v-model:reflections="reflections"
      v-model:genre-file="genreFile"
      :genre-info="genreInfo"
    />
  </div>
</template>

<style scoped>
.session-editor {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.editor-global-header {
  background: var(--bg-mantle);
  border-bottom: 1px solid var(--bg-surface0);
  padding: 8px 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.editor-global-header h1 {
  font-size: 13px;
  font-weight: 700;
  color: var(--mauve);
}

.status-msg {
  font-size: 11px;
  color: var(--blue);
  margin-left: auto;
}

.profile-picker {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.profile-select {
  background: var(--bg-base);
  color: var(--text-sub);
  border: 1px solid var(--bg-surface1);
  border-radius: 4px;
  padding: 3px 6px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  outline: none;
}
.profile-select:focus { border-color: var(--mauve); }
.profile-btn {
  background: var(--bg-surface0);
  color: var(--mauve);
  border: 1px solid var(--bg-surface1);
  border-radius: 3px;
  padding: 2px 8px;
  font-size: 10px;
  font-weight: 700;
  cursor: pointer;
}
.profile-btn:hover { background: var(--bg-surface1); }
.profile-btn.revert { color: var(--text-muted); }

.pipe-strip {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px 8px;
  border-left: 1px solid var(--bg-surface0);
  border-right: 1px solid var(--bg-surface0);
}
.pipe-stage {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 6px;
  font-size: 10px;
  color: var(--text-muted);
}
.pipe-glyph {
  font-weight: 700;
  color: var(--text-sub);
  font-size: 11px;
}
.pipe-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--bg-surface1);
  display: inline-block;
}
.pipe-dot.ok   { background: var(--green, #a6d189); }
.pipe-dot.warn { background: var(--yellow, #e5c890); }
.pipe-dot.bad  { background: var(--red, #e78284); }
.pipe-dot.cold { background: var(--bg-surface1); }
.pipe-age {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-muted);
  min-width: 22px;
}

.stage-group {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-left: 1px solid var(--bg-surface0);
}
.stage-group:first-of-type {
  margin-left: 4px;
}
.stage-label {
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--text-muted);
  margin-right: 2px;
}
.config-btn {
  margin-left: 4px;
}
.config-btn.active {
  background: var(--bg-surface0);
  color: var(--mauve);
}

.columns {
  display: grid;
  grid-template-columns: 220px 1fr;
  flex: 1;
  overflow: hidden;
}

.center-col {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Empty-state shell shown when configReady is false */
.empty-shell {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-base);
}
.empty-card {
  max-width: 440px;
  padding: 24px;
  text-align: center;
  background: var(--bg-mantle);
  border: 1px solid var(--bg-surface0);
  border-radius: 6px;
}
.empty-card h2 {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 10px;
}
.empty-card p {
  font-size: 12px;
  color: var(--text-sub);
  line-height: 1.5;
  margin-bottom: 14px;
}
.empty-card strong { color: var(--mauve); }
</style>
