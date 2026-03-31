<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useConfigStore } from '../../stores/config'
import { resolvePath, resolvePathList } from '../../utils/paths'
import { apiFetch, apiPut, apiPost } from '../../api/client'
import { connectSSE } from '../../api/sse'
import PathField from '../../components/shared/PathField.vue'
import MultiPathField from '../../components/shared/MultiPathField.vue'
import SceneList from '../../components/scene-editor/SceneList.vue'
import type { Scene } from '../../components/scene-editor/SceneList.vue'
import ExtractionEditor from '../../components/scene-editor/ExtractionEditor.vue'
import NarrationOutput from '../../components/scene-editor/NarrationOutput.vue'
import VttPanel from '../../components/scene-editor/VttPanel.vue'
import QuoteLedger from '../../components/scene-editor/QuoteLedger.vue'
import QuoteAssignmentPanel from '../../components/scene-editor/QuoteAssignmentPanel.vue'
import QuotePicker from '../../components/scene-editor/QuotePicker.vue'

const config = useConfigStore()

// ── Editor config ─────────────────────────────────────────────────
const configured = ref(false)
const configError = ref('')

// Form fields for editor config
const session = ref('')
const extractDir = ref('')
const roleplayExtractDir = ref('')
const outputDir = ref('')
const summaryExtractDir = ref('')
const sessionSummary = ref('')
const roleplaySummary = ref('')
const party = ref('')
const voiceDir = ref('')
const examplesDir = ref('')
const characters = ref('')
const context = ref('')
const narrateTokens = ref(4000)
const showOverrides = ref(false)

function loadConfigFields() {
  const v = config.values
  session.value = v.sd_session || ''
  extractDir.value = v.sd_extract_dir || 'scene_extractions'
  roleplayExtractDir.value = v.sd_roleplay_dir || 'vtt_roleplay_extractions'
  outputDir.value = v.sd_output_dir || v.session_dir || ''
  summaryExtractDir.value = v.sd_summary_dir || 'vtt_extractions'
  sessionSummary.value = v.sd_session_summary || ''
  roleplaySummary.value = v.sd_roleplay_summary || ''
  party.value = v.sd_party || ''
  voiceDir.value = v.sd_voice_dir || v.session_doc_voice_dir || ''
  examplesDir.value = v.sd_examples_dir || v.session_doc_examples_dir || ''
  characters.value = v.sd_characters || v.session_doc_characters || ''
  context.value = v.vtt_context || ''
  narrateTokens.value = v.sd_narrate_tokens || v.session_doc_narrate_tokens || 4000
}

const contextFiles = computed(() => resolvePathList(context.value))

const configReady = computed(() =>
  !!(session.value.trim() && extractDir.value.trim() &&
     roleplayExtractDir.value.trim())
)

async function applyConfig() {
  configError.value = ''
  const editorConfig = {
    session: resolvePath(session.value),
    extract_dir: resolvePath(extractDir.value),
    roleplay_extract_dir: resolvePath(roleplayExtractDir.value),
    output_dir: resolvePath(outputDir.value) || config.cwd || '',
    summary_extract_dir: resolvePath(summaryExtractDir.value) || undefined,
    session_summary: resolvePath(sessionSummary.value) || undefined,
    roleplay_summary: resolvePath(roleplaySummary.value) || undefined,
    party: resolvePath(party.value) || undefined,
    voice_dir: resolvePath(voiceDir.value) || undefined,
    examples: resolvePath(examplesDir.value) || undefined,
    characters: characters.value || undefined,
    context: contextFiles.value.length ? contextFiles.value : [],
    narrate_tokens: narrateTokens.value || undefined,
    work_dir: config.cwd,
  }
  try {
    await apiPut('/api/editor/config', editorConfig)
    configured.value = true
    await loadScenes()
    await checkAssembled()
  } catch (e: any) {
    configError.value = `Failed to configure editor: ${e.message}`
  }
}

// ── Mode toggle ──────────────────────────────────────────────────
const editorMode = ref<'quotes' | 'editor'>('quotes')

// ── Scene state ───────────────────────────────────────────────────
const scenes = ref<Scene[]>([])
const currentScene = ref<number | null>(null)
const extractionContent = ref('')
const roleplayContent = ref('')
const sceneLabel = ref('')
const estimatedTokens = ref<number | null>(null)
const hasExtraction = ref(false)
const isRoleplayLocal = ref(false)
const narrating = ref(false)
const extracting = ref(false)
const narrationOutput = ref('')
const statusMsg = ref('')
const rightTab = ref<'vtt' | 'ledger'>('vtt')
const assembledExists = ref(false)

const activeSSE = ref<EventSource | null>(null)

// ── Quote state ──────────────────────────────────────────────────
const quoteCounts = ref<Record<number, number>>({})
const syncing = ref(false)
const autoAssigning = ref(false)
const showPicker = ref(false)
const assignmentPanel = ref<InstanceType<typeof QuoteAssignmentPanel> | null>(null)

async function loadQuoteCounts() {
  try {
    const data = await apiFetch('/api/ledger/quotes')
    const counts: Record<number, number> = {}
    for (const s of data.scenes || []) {
      counts[s.index] = s.quotes.length
    }
    quoteCounts.value = counts
  } catch {
    // Ledger may not be synced yet
  }
}

async function syncQuotes() {
  syncing.value = true
  setStatus('Syncing quotes...')
  try {
    const result = await apiPost('/api/ledger/sync')
    setStatus(`Synced: ${result.total} quotes, ${result.matched} matched`)
    await loadQuoteCounts()
    assignmentPanel.value?.reload()
  } catch {
    setStatus('Sync error')
  }
  syncing.value = false
}

async function autoAssign() {
  autoAssigning.value = true
  narrationOutput.value = ''
  setStatus('Running auto-assign...')

  activeSSE.value = connectSSE('/api/ledger/auto-assign', {
    onData(text) {
      narrationOutput.value += text
    },
    onDone(rc) {
      activeSSE.value = null
      autoAssigning.value = false
      setStatus(rc === 0 ? 'Auto-assign complete.' : 'Auto-assign failed.')
      loadQuoteCounts()
      assignmentPanel.value?.reload()
    },
    onError() {
      activeSSE.value = null
      autoAssigning.value = false
      setStatus('Auto-assign stream error.')
    },
  })
}

async function generateExtraction(sceneNum: number) {
  narrationOutput.value = ''
  setStatus(`Generating extraction for scene ${sceneNum}...`)

  activeSSE.value = connectSSE(`/api/ledger/generate-extraction/${sceneNum}`, {
    onData(text) {
      narrationOutput.value += text
    },
    onDone(rc) {
      activeSSE.value = null
      setStatus(rc === 0 ? 'Extraction generated.' : 'Generation failed.')
      loadScenes()
    },
    onError() {
      activeSSE.value = null
      setStatus('Generation stream error.')
    },
  })
}

function onPickerAdded(count: number) {
  showPicker.value = false
  setStatus(`Added ${count} quotes`)
  loadQuoteCounts()
  assignmentPanel.value?.reload()
}

function onQuotesChanged() {
  loadQuoteCounts()
}

// ── Scene navigation ─────────────────────────────────────────────

async function loadScenes() {
  try {
    scenes.value = await apiFetch('/api/editor/scenes')
  } catch {
    scenes.value = []
  }
}

async function selectScene(n: number) {
  currentScene.value = n

  // Only load extraction data if in editor mode (quote panel loads its own data)
  if (editorMode.value === 'editor') {
    await loadEditorScene(n)
  }
}

async function loadEditorScene(n: number) {
  const data = await apiFetch(`/api/editor/extraction/${n}`)
  extractionContent.value = data.content || ''
  hasExtraction.value = data.exists
  sceneLabel.value = data.scene_label || `Scene ${n}`
  estimatedTokens.value = data.estimated_tokens || null

  const rpData = await apiFetch(`/api/editor/roleplay/${n}`).catch(() => ({
    content: '', is_local: false, exists: false
  }))
  roleplayContent.value = rpData.content || ''
  isRoleplayLocal.value = rpData.is_local || false

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

async function saveRoleplay(content: string) {
  if (currentScene.value === null) return
  roleplayContent.value = content
  await apiPut(`/api/editor/roleplay/${currentScene.value}`, { content })
  isRoleplayLocal.value = true
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
    onData(text) {
      narrationOutput.value += text
    },
    onDone(rc) {
      activeSSE.value = null
      narrating.value = false
      setStatus(rc === 0 ? 'Done.' : 'Narration failed.')
      loadScenes()
    },
    onError() {
      activeSSE.value = null
      narrating.value = false
      setStatus('Stream error \u2014 check terminal.')
    },
  })
}

async function runExtract() {
  if (extracting.value || narrating.value) return
  extracting.value = true
  narrationOutput.value = ''
  setStatus('Running extraction (passes 1\u20134)...')

  activeSSE.value = connectSSE('/api/editor/extract', {
    onData(text) {
      narrationOutput.value += text
    },
    onDone(rc) {
      activeSSE.value = null
      extracting.value = false
      setStatus(rc === 0 ? 'Extraction complete.' : 'Extraction failed.')
      loadScenes()
    },
    onError() {
      activeSSE.value = null
      extracting.value = false
      setStatus('Stream error \u2014 check terminal.')
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

async function assembleDoc() {
  setStatus('Assembling session doc...')
  try {
    const data = await apiPost('/api/editor/assemble')
    if (data.ok) {
      setStatus(`Saved \u2192 ${data.filename} (${data.scenes_included} scenes)`)
      assembledExists.value = true
    } else {
      setStatus(`Assembly failed: ${data.error}`)
    }
  } catch {
    setStatus('Assembly error.')
  }
}

async function openAssembled() {
  try {
    await apiPost('/api/editor/open/assembled/0')
  } catch {
    setStatus('Could not open assembled file.')
  }
}

function setStatus(msg: string) {
  statusMsg.value = msg
  if (msg) setTimeout(() => { if (statusMsg.value === msg) statusMsg.value = '' }, 5000)
}

function clearOutput() {
  narrationOutput.value = ''
}

async function checkAssembled() {
  try {
    const data = await apiFetch('/api/editor/assembled-exists')
    assembledExists.value = data.exists
  } catch { /* ignore */ }
}

function backToConfig() {
  configured.value = false
}

// When switching to editor mode and a scene is selected, load its extraction
function onModeChange(mode: 'quotes' | 'editor') {
  editorMode.value = mode
  if (mode === 'editor' && currentScene.value !== null) {
    loadEditorScene(currentScene.value)
  }
}

// ── Init ──────────────────────────────────────────────────────────
onMounted(async () => {
  loadConfigFields()

  // Check if editor is already configured (e.g. from CLI startup)
  try {
    const existing = await apiFetch('/api/editor/config')
    if (existing.session && existing.extract_dir) {
      configured.value = true
      await loadScenes()
      await checkAssembled()
      await loadQuoteCounts()
      return
    }
  } catch { /* not configured yet */ }

  // Auto-apply if we have enough from the config store
  if (configReady.value) {
    await applyConfig()
    await loadQuoteCounts()
  }
})
</script>

<template>
  <!-- Config panel (shown when not yet configured) -->
  <div v-if="!configured" class="config-panel">
    <div class="page">
      <div class="page-header">
        <h2>Session Doc Editor</h2>
        <p class="subtitle">
          Configure the editor with your session files, then edit extractions and narrate scene by scene.
        </p>
      </div>

      <div class="form-grid">
        <!-- Required -->
        <div class="form-section">
          <PathField v-model="session" label="GMassistant recap file" required
            help="The structured session notes (e.g. gm-assist.md)." />
          <PathField v-model="extractDir" label="Scene extractions directory" required
            help="plan.md + per-scene extraction files. Run Extract on the previous page to generate." />
          <PathField v-model="roleplayExtractDir" label="Roleplay extractions directory" required
            help="vtt_roleplay_extractions/ — shown in the right panel for reference." />
        </div>

        <div class="form-section">
          <PathField v-model="outputDir" label="Output directory"
            help="Where sceneN.md files and the assembled doc are saved." />
          <div class="field">
            <label class="field-label">Characters</label>
            <input type="text" class="field-input" v-model="characters"
              placeholder="Zalthir, Grygum, Daz, Thorin" />
            <div class="field-help">Comma-separated narrator roster (used by Extract)</div>
          </div>
          <div class="field">
            <label class="field-label">Narration token limit</label>
            <input type="number" class="field-input" v-model.number="narrateTokens"
              min="1000" step="500" />
            <div class="field-help">Per-scene output cap (default: 4000). Override per-scene with "tokens: N" in extraction file.</div>
          </div>
        </div>

        <!-- Optional overrides -->
        <div class="form-section">
          <button class="btn-neutral btn-sm" @click="showOverrides = !showOverrides">
            {{ showOverrides ? 'Hide' : 'Show' }} path overrides
          </button>

          <div v-if="showOverrides" class="advanced-panel">
            <PathField v-model="summaryExtractDir" label="Summary extractions directory"
              help="vtt_extractions/ — event context for narration." />
            <PathField v-model="sessionSummary" label="VTT session summary"
              help="session-summary.md — used in consistency check and narration." />
            <PathField v-model="roleplaySummary" label="Roleplay summary"
              help="session-roleplay.md — injected into narration if no per-scene roleplay exists." />
            <PathField v-model="party" label="Party document"
              help="party.md — backstory, personality, relationships." />
            <PathField v-model="voiceDir" label="Voice files directory"
              help="Directory of {name}_voice.md files." />
            <PathField v-model="examplesDir" label="Examples directory"
              help="Handcrafted .md style references for narration." />
            <MultiPathField v-model="context" label="Campaign context files"
              help="campaign_state.md, world_state.md — used by extraction passes." />
          </div>
        </div>

        <div v-if="configError" class="error-box">{{ configError }}</div>

        <div class="form-section">
          <button
            class="btn-primary"
            :disabled="!configReady"
            @click="applyConfig"
          >
            Open Editor
          </button>
          <span v-if="!configReady" class="field-help" style="margin-left:8px">
            Fill in the required fields above.
          </span>
        </div>
      </div>
    </div>
  </div>

  <!-- Editor (shown after config is applied) -->
  <div v-else class="session-editor">
    <!-- Header -->
    <header class="editor-global-header">
      <h1>Session Doc</h1>

      <!-- Mode toggle -->
      <div class="mode-toggle">
        <button
          class="mode-btn"
          :class="{ active: editorMode === 'quotes' }"
          @click="onModeChange('quotes')"
        >Quotes</button>
        <button
          class="mode-btn"
          :class="{ active: editorMode === 'editor' }"
          @click="onModeChange('editor')"
        >Editor</button>
      </div>

      <span class="status-msg">{{ statusMsg }}</span>
      <button
        class="btn-neutral btn-sm"
        :disabled="extracting || narrating"
        @click="runExtract"
        style="margin-left:8px"
      >{{ extracting ? 'Extracting\u2026' : 'Extract' }}</button>
      <button class="btn-neutral btn-sm" @click="assembleDoc" style="margin-left:4px">
        Assemble Doc
      </button>
      <button
        v-if="assembledExists"
        class="btn-neutral btn-sm"
        @click="openAssembled"
        style="margin-left:4px"
      >Open in Typora</button>
      <button
        class="btn-neutral btn-sm"
        @click="backToConfig"
        style="margin-left:4px"
      >Config</button>
    </header>

    <!-- Three-column layout -->
    <div class="columns">
      <!-- Left: scene list -->
      <SceneList
        :scenes="scenes"
        :current-scene="currentScene"
        :quote-counts="editorMode === 'quotes' ? quoteCounts : undefined"
        :show-quote-actions="editorMode === 'quotes'"
        :syncing="syncing"
        :auto-assigning="autoAssigning"
        @select="selectScene"
        @sync="syncQuotes"
        @auto-assign="autoAssign"
      />

      <!-- Center: depends on mode -->
      <template v-if="editorMode === 'quotes'">
        <QuoteAssignmentPanel
          ref="assignmentPanel"
          :current-scene="currentScene"
          :scenes="scenes"
          @status="setStatus"
          @quotes-changed="onQuotesChanged"
          @generate="generateExtraction"
          @show-picker="showPicker = true"
        />
      </template>

      <template v-else>
        <div class="center-col">
          <ExtractionEditor
            :extraction-content="extractionContent"
            :roleplay-content="roleplayContent"
            :scene-label="sceneLabel"
            :estimated-tokens="estimatedTokens"
            :default-narrate-tokens="narrateTokens"
            :has-extraction="hasExtraction"
            :is-roleplay-local="isRoleplayLocal"
            :narrating="narrating"
            :extracting="extracting"
            @save-extraction="saveExtraction"
            @save-roleplay="saveRoleplay"
            @reload="reload"
            @narrate="narrate"
            @open-typora="openTypora"
            @update:extraction-content="extractionContent = $event"
            @update:roleplay-content="roleplayContent = $event"
          />
          <NarrationOutput
            :output="narrationOutput"
            :current-scene="currentScene"
            @clear="clearOutput"
          />
        </div>
      </template>

      <!-- Right: stream output (quotes mode) or VTT/Ledger (editor mode) -->
      <div class="right-panel">
        <template v-if="editorMode === 'quotes'">
          <div class="right-header">Stream Output</div>
          <NarrationOutput
            :output="narrationOutput"
            :current-scene="currentScene"
            @clear="clearOutput"
          />
        </template>
        <template v-else>
          <div class="tab-bar">
            <div class="tab" :class="{ active: rightTab === 'vtt' }" @click="rightTab = 'vtt'">
              VTT Source
            </div>
            <div class="tab" :class="{ active: rightTab === 'ledger' }" @click="rightTab = 'ledger'">
              Quote Ledger
            </div>
          </div>
          <VttPanel v-show="rightTab === 'vtt'" />
          <QuoteLedger v-show="rightTab === 'ledger'" :current-scene="currentScene" />
        </template>
      </div>
    </div>
  </div>

  <!-- Quote Picker modal -->
  <QuotePicker
    v-if="showPicker && currentScene !== null"
    :current-scene="currentScene"
    :scenes="scenes"
    @close="showPicker = false"
    @added="onPickerAdded"
  />
</template>

<style scoped>
/* Config panel styles */
.config-panel {
  height: 100%;
  overflow-y: auto;
}
.page { padding: 20px 24px; max-width: 700px; }
.page-header { margin-bottom: 20px; }
.page-header h2 { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.subtitle { font-size: 12px; color: var(--text-muted); }

.form-grid { display: flex; flex-direction: column; gap: 16px; }
.form-section {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--bg-surface0);
}
.form-section:last-child { border-bottom: none; }

.field { margin-bottom: 10px; }
.field-label {
  display: block; font-size: 11px; font-weight: 600;
  color: var(--text-sub); margin-bottom: 3px;
}
.field-input {
  width: 100%; padding: 6px 8px; border-radius: 4px;
  border: 1px solid var(--bg-surface1); background: var(--bg-base);
  color: var(--text); font-family: var(--mono); font-size: 11px;
  outline: none; box-sizing: border-box;
}
.field-input:focus { border-color: var(--mauve); }
.field-help { font-size: 10px; color: var(--text-muted); margin-top: 2px; }

.advanced-panel {
  margin-top: 10px; padding: 10px;
  background: var(--bg-mantle); border-radius: 4px;
}

.error-box {
  padding: 10px 14px; background: #3a1e1e; border-radius: 4px;
  font-size: 11px; color: var(--red); line-height: 1.5;
}

/* Editor styles */
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

.mode-toggle {
  display: flex;
  border: 1px solid var(--bg-surface1);
  border-radius: 4px;
  overflow: hidden;
}
.mode-btn {
  padding: 4px 12px;
  font-size: 11px;
  font-weight: 600;
  background: var(--bg-base);
  color: var(--text-sub);
  border: none;
  cursor: pointer;
  transition: background .1s;
}
.mode-btn:not(:last-child) { border-right: 1px solid var(--bg-surface1); }
.mode-btn:hover { background: var(--bg-surface0); }
.mode-btn.active {
  background: var(--bg-surface0);
  color: var(--mauve);
  font-weight: 700;
}

.status-msg {
  font-size: 11px;
  color: var(--blue);
  margin-left: auto;
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

.right-header {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--text-muted);
  padding: 8px 12px;
  border-bottom: 1px solid var(--bg-surface0);
  flex-shrink: 0;
}

.tab-bar {
  background: var(--bg-mantle);
  border-bottom: 1px solid var(--bg-surface0);
  display: flex;
  flex-shrink: 0;
}
.tab {
  padding: 6px 14px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  color: var(--text-muted);
  transition: color .1s;
}
.tab:hover { color: var(--text); }
.tab.active { color: var(--mauve); border-bottom-color: var(--mauve); }
</style>
