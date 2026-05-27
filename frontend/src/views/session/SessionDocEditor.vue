<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useConfigStore } from '../../stores/config'
import { resolvePath, resolvePathList } from '../../utils/paths'
import { apiFetch, apiPut, apiPost } from '../../api/client'
import { connectSSE } from '../../api/sse'
import SceneList from '../../components/scene-editor/SceneList.vue'
import type { Scene } from '../../components/scene-editor/SceneList.vue'
import ExtractionEditor from '../../components/scene-editor/ExtractionEditor.vue'
import NarrationOutput from '../../components/scene-editor/NarrationOutput.vue'
import VttPanel from '../../components/scene-editor/VttPanel.vue'
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
const characters = ref('')
const context = ref('')
const narrateTokens = ref(16000)
const proseMode = ref(false)
const reflections = ref(false)
const narrationGenre = ref('')
const useBatch = ref(false)
const backend = ref<'anthropic' | 'dgx'>('anthropic')

// Drawer open/closed — persisted in localStorage so it survives reloads.
const DRAWER_KEY = 'session-doc-editor.knob-drawer.open'
const drawerOpen = ref(localStorage.getItem(DRAWER_KEY) === 'true')
watch(drawerOpen, (v) => {
  localStorage.setItem(DRAWER_KEY, v ? 'true' : 'false')
})

// ── Field → config-store key map (legacy flat-key overlay) ───────
function loadConfigFields() {
  const v = config.values
  session.value = v.sd_session || ''
  outputDir.value = v.sd_output_dir || v.session_dir || ''
  sessionSummary.value = v.sd_session_summary || 'session-summary.md'
  sceneExtractionsDir.value = v.sd_scene_extractions_dir || 'scene_extractions_new'
  narrationDir.value = v.sd_narration_dir || 'narration'
  party.value = v.sd_party || ''
  voiceDir.value = v.sd_voice_dir || v.session_doc_voice_dir || ''
  examplesDir.value = v.sd_examples_dir || v.session_doc_examples_dir || ''
  characters.value = v.sd_characters || v.session_doc_characters || ''
  context.value = v.vtt_context || ''
  narrateTokens.value = v.sd_narrate_tokens || v.session_doc_narrate_tokens || 16000
  proseMode.value = v.sd_prose_mode || false
  reflections.value = v.sd_reflections || false
  narrationGenre.value = v.sd_narration_genre || ''
  useBatch.value = v.sd_batch === true
  backend.value = v.sd_backend === 'dgx' ? 'dgx' : 'anthropic'
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
    session: resolvePath(session.value),
    output_dir: resolvePath(outputDir.value) || config.cwd || '',
    session_summary: resolvePath(sessionSummary.value) || undefined,
    scene_extractions_dir: resolvePath(sceneExtractionsDir.value) || undefined,
    narration_dir: resolvePath(narrationDir.value) || undefined,
    party: resolvePath(party.value) || undefined,
    voice_dir: resolvePath(voiceDir.value) || undefined,
    examples: resolvePath(examplesDir.value) || undefined,
    characters: characters.value || undefined,
    context: contextFiles.value.length ? contextFiles.value : [],
    narrate_tokens: narrateTokens.value || undefined,
    prose_mode: proseMode.value || undefined,
    reflections: reflections.value || undefined,
    narration_genre: narrationGenre.value.trim() || undefined,
    work_dir: config.cwd,
  }
}

async function applyConfig() {
  try {
    await apiPut('/api/editor/config', buildEditorConfigPayload())
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
   party, voiceDir, examplesDir, characters, context,
   narrateTokens, proseMode, reflections, narrationGenre],
  scheduleApply,
)

async function persistBatchToggle() {
  config.values.sd_batch = useBatch.value
  try {
    await config.updateSection('session_doc', { batch: useBatch.value })
  } catch {
    /* non-fatal: toggle will still apply to in-flight calls */
  }
}
watch(useBatch, persistBatchToggle)

async function persistBackend() {
  config.values.sd_backend = backend.value
  try {
    await config.updateSection('session_doc', { backend: backend.value })
  } catch {
    /* non-fatal — the next subprocess will still read the in-memory CONFIG */
  }
}
watch(backend, persistBackend)

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
}
const pipeline = ref<{
  enhance: StageStatus
  extract: StageStatus
  plan: StageStatus
  narrate: StageStatus
} | null>(null)

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
    narration_genre?: string
    backend?: 'anthropic' | 'dgx'
  }
}
const profiles = ref<ProfileEntry[]>([])
const activeProfileName = ref<string | null>(null)

function loadProfilesFromStore() {
  const ps = config.resolved?.ui?.profiles
  if (ps && typeof ps === 'object') {
    profiles.value = Array.isArray(ps.profiles) ? ps.profiles : []
    activeProfileName.value = ps.active ?? null
  } else {
    profiles.value = []
    activeProfileName.value = null
  }
}

const currentKnobs = computed(() => ({
  narrate_tokens: narrateTokens.value,
  prose_mode: proseMode.value,
  reflections: reflections.value,
  narration_genre: narrationGenre.value,
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
    || (k.narration_genre ?? '') !== c.narration_genre
    || (k.backend ?? 'anthropic') !== c.backend
})

async function persistProfilesSection() {
  try {
    await config.updateSection('profiles', {
      profiles: profiles.value,
      active: activeProfileName.value,
    })
    loadProfilesFromStore()
  } catch (e: any) {
    setStatus(`Profile save failed: ${e?.message ?? 'unknown error'}`)
  }
}

function applyProfileKnobs(p: ProfileEntry) {
  const k = p.knobs
  if (typeof k.narrate_tokens === 'number') narrateTokens.value = k.narrate_tokens
  if (typeof k.prose_mode === 'boolean') proseMode.value = k.prose_mode
  if (typeof k.reflections === 'boolean') reflections.value = k.reflections
  if (typeof k.narration_genre === 'string') narrationGenre.value = k.narration_genre
  if (k.backend === 'anthropic' || k.backend === 'dgx') backend.value = k.backend
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
    profiles.value = [...profiles.value, { name: trimmed, knobs: { ...currentKnobs.value } }]
    activeProfileName.value = trimmed
    await persistProfilesSection()
    setStatus(`Saved profile "${trimmed}".`)
    return
  }
  if (name === '') {
    activeProfileName.value = null
    await persistProfilesSection()
    return
  }
  const p = profiles.value.find(prof => prof.name === name)
  if (!p) return
  activeProfileName.value = name
  applyProfileKnobs(p)
  await persistProfilesSection()
}

async function saveProfileChanges() {
  if (!activeProfile.value) return
  profiles.value = profiles.value.map(p =>
    p.name === activeProfileName.value
      ? { ...p, knobs: { ...currentKnobs.value } }
      : p,
  )
  await persistProfilesSection()
  setStatus(`Updated profile "${activeProfileName.value}".`)
}

function revertProfile() {
  if (activeProfile.value) applyProfileKnobs(activeProfile.value)
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
    onDone(rc) {
      activeSSE.value = null
      narrating.value = false
      setStatus(rc === 0 ? 'Done.' : 'Narration failed.')
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
    onDone(rc) {
      activeSSE.value = null
      scrubbing.value = false
      setStatus(rc === 0
        ? `Scrubbed scene ${currentScene.value} — .scrubbed.md written.`
        : 'Scrub failed.')
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
    onDone(rc) {
      activeSSE.value = null
      scrubbing.value = false
      setStatus(rc === 0
        ? 'Scrub-All complete — .scrubbed.md files written.'
        : 'Scrub-All failed.')
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
  setStatus(useBatch.value
    ? 'Submitting Stage 2 batch (Message Batches API)...'
    : 'Re-extracting quotes (Stage 2)...')

  const url = useBatch.value
    ? '/api/editor/extract?batch=1&force=1'
    : '/api/editor/extract?force=1'
  activeSSE.value = connectSSE(url, {
    onData(text) { narrationOutput.value += text },
    onDone(rc) {
      activeSSE.value = null
      extracting.value = false
      setStatus(rc === 0 ? 'Re-extraction complete.' : 'Re-extraction failed.')
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
    onDone(rc) {
      activeSSE.value = null
      planning.value = false
      setStatus(rc === 0
        ? 'Plan & check complete — plan.md saved.'
        : 'Plan & check failed.')
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
  setStatus(useBatch.value
    ? 'Submitting Stage 1 batch (Message Batches API)...'
    : 'Enhancing summary (Stage 1)...')

  const url = useBatch.value ? '/api/editor/enhance?batch=1' : '/api/editor/enhance'
  activeSSE.value = connectSSE(url, {
    onData(text) { narrationOutput.value += text },
    onDone(rc) {
      activeSSE.value = null
      enhancing.value = false
      setStatus(rc === 0 ? 'Stage 1 complete — review session-summary.md.' : 'Stage 1 failed.')
      refreshPipeline()
    },
    onError() {
      activeSSE.value = null
      enhancing.value = false
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
  // Hydrate form refs from the config store (legacy flat overlay), then
  // mark `configHydrated` so the watcher below doesn't echo the initial
  // values back to the server.
  loadConfigFields()

  try {
    const existing = await apiFetch('/api/editor/config')
    if (existing.session) session.value = existing.session
    if (existing.output_dir) outputDir.value = existing.output_dir
    if (existing.session_summary) sessionSummary.value = existing.session_summary
    if (existing.scene_extractions_dir) sceneExtractionsDir.value = existing.scene_extractions_dir
    if (existing.narration_dir) narrationDir.value = existing.narration_dir
    if (existing.party) party.value = existing.party
    if (existing.voice_dir) voiceDir.value = existing.voice_dir
    if (existing.examples) examplesDir.value = existing.examples
    if (existing.characters) characters.value = existing.characters
    if (typeof existing.narrate_tokens === 'number') narrateTokens.value = existing.narrate_tokens
    if (typeof existing.prose_mode === 'boolean') proseMode.value = existing.prose_mode
    if (typeof existing.reflections === 'boolean') reflections.value = existing.reflections
    if (existing.narration_genre) narrationGenre.value = existing.narration_genre
  } catch { /* server may not have CONFIG yet */ }

  configHydrated = true

  loadProfilesFromStore()

  if (configReady.value) {
    // Re-PUT once to make the server agree with our hydrated view, then
    // load scenes / enhanced sections.
    await applyConfig()
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

      <div class="right-panel">
        <VttPanel />
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
      v-model:characters="characters"
      v-model:context="context"
      v-model:use-batch="useBatch"
      v-model:backend="backend"
      v-model:narrate-tokens="narrateTokens"
      v-model:prose-mode="proseMode"
      v-model:reflections="reflections"
      v-model:narration-genre="narrationGenre"
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
  grid-template-columns: 220px 1fr 320px;
  flex: 1;
  overflow: hidden;
}

.center-col {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.right-panel {
  background: var(--bg-mantle);
  border-left: 1px solid var(--bg-surface0);
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
