<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { connectSSE } from '../../api/sse'
import { useConfigStore } from '../../stores/config'
import StreamOutput from './StreamOutput.vue'

const props = defineProps<{
  /** SSE endpoint (e.g. '/api/grounding/run/distill') */
  endpoint: string
  /** Query params forwarded to the endpoint (same shape as RunPanel). */
  params: Record<string, any>
  /** Disable both buttons (form not ready). */
  disabled?: boolean
  /** Path of the extract dir — UI reads it to list files post-extract. */
  extractDir?: string
  /** Button labels. */
  extractLabel?: string
  synthLabel?: string
  /** Hide the synthesize step (used for --build-dossiers, which has no synthesize phase). */
  synthesizeDisabled?: boolean
  /** Disable the extract step (e.g. no summaries supplied — nothing to extract). */
  extractDisabled?: boolean
}>()

const emit = defineEmits<{
  done: [phase: 'extract' | 'synthesize', returncode: number]
}>()

const config = useConfigStore()

type Phase = 'extract' | 'synthesize'
type Status = 'idle' | 'running' | 'done' | 'error'

const extractStatus = ref<Status>('idle')
const synthStatus = ref<Status>('idle')
const extractOutput = ref('')
const synthOutput = ref('')
const activeTab = ref<Phase>('extract')

const files = ref<{ name: string; size: number }[]>([])
const filesLoaded = ref(false)
const selectedFile = ref<string>('')
const fileContent = ref('')
const fileDirty = ref(false)
const fileSaving = ref(false)
const fileSavedFlash = ref(false)

const extractButtonLabel = computed(() => {
  if (extractStatus.value === 'running') return 'Extracting…'
  return props.extractLabel || '1. Extract'
})
const synthButtonLabel = computed(() => {
  if (synthStatus.value === 'running') return 'Synthesizing…'
  return props.synthLabel || '2. Synthesize'
})

const canExtract = computed(() =>
  !props.disabled
  && !props.extractDisabled
  && extractStatus.value !== 'running'
  && synthStatus.value !== 'running'
)
const canSynthesize = computed(() =>
  !props.disabled
  && !props.synthesizeDisabled
  && extractStatus.value !== 'running'
  && synthStatus.value !== 'running'
)

function buildUrl(endpoint: string, params: Record<string, any>): string {
  const url = new URL(endpoint, window.location.origin)
  for (const [k, v] of Object.entries(params)) {
    if (v === '' || v === false || v === null || v === undefined) continue
    if (Array.isArray(v)) {
      for (const item of v) {
        if (item) url.searchParams.append(k, item)
      }
    } else if (typeof v === 'boolean') {
      url.searchParams.set(k, 'true')
    } else {
      url.searchParams.set(k, String(v))
    }
  }
  return url.pathname + url.search
}

function runExtract() {
  if (!canExtract.value || !config.apiKeyPresent) return
  extractStatus.value = 'running'
  extractOutput.value = ''
  activeTab.value = 'extract'

  const url = buildUrl(props.endpoint, { ...props.params, extract_only: true })
  connectSSE(url, {
    onData(text) { extractOutput.value += text },
    onDone(rc) {
      extractStatus.value = rc === 0 ? 'done' : 'error'
      if (rc === 0) refreshFiles()
      emit('done', 'extract', rc)
    },
    onError() { extractStatus.value = 'error' },
  })
}

function runSynthesize() {
  if (!canSynthesize.value || !config.apiKeyPresent) return
  synthStatus.value = 'running'
  synthOutput.value = ''
  activeTab.value = 'synthesize'

  // Passing synthesize_only=true is the right default when the extract dir
  // already holds reviewed files — skip re-extracting. Callers that want a
  // clean run-both can just hit Extract then Synthesize in order, or set
  // synthesize_only in params.
  const runParams = { ...props.params }
  if (runParams.synthesize_only === undefined) {
    runParams.synthesize_only = true
  }
  const url = buildUrl(props.endpoint, runParams)
  connectSSE(url, {
    onData(text) { synthOutput.value += text },
    onDone(rc) {
      synthStatus.value = rc === 0 ? 'done' : 'error'
      emit('done', 'synthesize', rc)
    },
    onError() { synthStatus.value = 'error' },
  })
}

async function refreshFiles() {
  if (!props.extractDir) {
    files.value = []
    filesLoaded.value = true
    return
  }
  try {
    const r = await fetch(
      `/api/grounding/extracts?extract_dir=${encodeURIComponent(props.extractDir)}`
    )
    if (!r.ok) {
      files.value = []
      filesLoaded.value = true
      return
    }
    const data = await r.json()
    files.value = data.files || []
    filesLoaded.value = true
    if (!selectedFile.value && files.value.length) {
      loadFile(files.value[0].name)
    }
  } catch {
    files.value = []
    filesLoaded.value = true
  }
}

async function loadFile(name: string) {
  if (fileDirty.value) {
    if (!confirm('Discard unsaved edits?')) return
  }
  selectedFile.value = name
  fileContent.value = ''
  fileDirty.value = false
  if (!props.extractDir) return
  const r = await fetch(
    `/api/grounding/extracts/${encodeURIComponent(name)}?extract_dir=${encodeURIComponent(props.extractDir)}`
  )
  if (!r.ok) return
  const data = await r.json()
  fileContent.value = data.content || ''
}

async function saveFile() {
  if (!selectedFile.value || !props.extractDir) return
  fileSaving.value = true
  const r = await fetch(
    `/api/grounding/extracts/${encodeURIComponent(selectedFile.value)}?extract_dir=${encodeURIComponent(props.extractDir)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: fileContent.value }),
    }
  )
  fileSaving.value = false
  if (r.ok) {
    fileDirty.value = false
    fileSavedFlash.value = true
    setTimeout(() => { fileSavedFlash.value = false }, 1500)
    refreshFiles()
  }
}

function onEdit(e: Event) {
  fileContent.value = (e.target as HTMLTextAreaElement).value
  fileDirty.value = true
}

function statusBadge(s: Status): string {
  if (s === 'running') return 'Running'
  if (s === 'done') return 'OK'
  if (s === 'error') return 'Error'
  return ''
}

watch(() => props.extractDir, (dir) => {
  if (dir) refreshFiles()
})

if (props.extractDir) refreshFiles()
</script>

<template>
  <div class="esp">
    <!-- Phase 1: Extract -->
    <div class="phase">
      <div class="phase-header">
        <span class="phase-label">1. Extract</span>
        <span
          v-if="extractStatus !== 'idle'"
          class="phase-status"
          :class="`status-${extractStatus}`"
        >{{ statusBadge(extractStatus) }}</span>
      </div>
      <div class="controls">
        <button
          class="btn-primary"
          :disabled="!canExtract || !config.apiKeyPresent"
          @click="runExtract"
        >{{ extractButtonLabel }}</button>
        <button
          class="btn-neutral btn-sm"
          :disabled="!extractDir"
          @click="refreshFiles"
        >Refresh files</button>
        <span v-if="!config.apiKeyPresent" class="warning">
          ANTHROPIC_API_KEY not set
        </span>
      </div>
    </div>

    <!-- Review panel: extraction files -->
    <div v-if="extractDir && filesLoaded" class="review">
      <div v-if="files.length === 0" class="review-empty">
        No extract files in <code>{{ extractDir }}</code>. Run Extract, or check the path.
      </div>
      <div v-else class="review-grid">
        <div class="file-list">
          <div class="file-list-header">
            {{ files.length }} file{{ files.length === 1 ? '' : 's' }}
          </div>
          <div
            v-for="f in files"
            :key="f.name"
            class="file-row"
            :class="{ active: f.name === selectedFile }"
            @click="loadFile(f.name)"
          >
            <span class="file-name">{{ f.name }}</span>
            <span class="file-size">{{ (f.size / 1024).toFixed(1) }}k</span>
          </div>
        </div>
        <div class="file-editor">
          <div class="editor-header">
            <span class="editor-title">{{ selectedFile || 'Select a file' }}</span>
            <span v-if="fileDirty" class="dirty">• unsaved</span>
            <span class="save-flash" :class="{ show: fileSavedFlash }">Saved</span>
            <span style="flex:1"></span>
            <button
              class="btn-primary btn-sm"
              :disabled="!fileDirty || fileSaving"
              @click="saveFile"
            >Save</button>
          </div>
          <textarea
            class="editor-ta"
            :value="fileContent"
            :disabled="!selectedFile"
            @input="onEdit"
            spellcheck="false"
            placeholder="Select an extract file to review and edit."
          />
        </div>
      </div>
    </div>

    <!-- Phase 2: Synthesize -->
    <div class="phase">
      <div class="phase-header">
        <span class="phase-label">2. Synthesize</span>
        <span
          v-if="synthStatus !== 'idle'"
          class="phase-status"
          :class="`status-${synthStatus}`"
        >{{ statusBadge(synthStatus) }}</span>
      </div>
      <div class="controls">
        <button
          class="btn-success"
          :disabled="!canSynthesize || !config.apiKeyPresent"
          @click="runSynthesize"
        >{{ synthButtonLabel }}</button>
        <span v-if="synthesizeDisabled" class="help">
          No synthesize pass for this flow — extract output is the final product.
        </span>
      </div>
    </div>

    <!-- Tabbed output -->
    <div v-if="extractOutput || synthOutput" class="output-tabs">
      <div class="tab-bar">
        <div
          class="tab"
          :class="{ active: activeTab === 'extract' }"
          @click="activeTab = 'extract'"
        >Extract output</div>
        <div
          class="tab"
          :class="{ active: activeTab === 'synthesize' }"
          @click="activeTab = 'synthesize'"
        >Synthesize output</div>
      </div>
      <div v-if="activeTab === 'extract'" class="output-container">
        <StreamOutput :text="extractOutput || '(no output yet)'" />
      </div>
      <div v-if="activeTab === 'synthesize'" class="output-container">
        <StreamOutput :text="synthOutput || '(no output yet)'" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.esp {
  display: flex;
  flex-direction: column;
  border-top: 1px solid var(--bg-surface0);
}

.phase {
  padding: 10px 12px;
  border-bottom: 1px solid var(--bg-surface0);
  background: var(--bg-mantle);
}
.phase-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.phase-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: .03em;
  text-transform: uppercase;
}
.phase-status {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: .04em;
}
.status-running { background: #2d2d4a; color: var(--blue); }
.status-done    { background: #1e3a2a; color: var(--green); }
.status-error   { background: #3a1e1e; color: var(--red); }

.controls {
  display: flex;
  align-items: center;
  gap: 8px;
}
.warning { font-size: 11px; color: var(--peach); font-weight: 600; }
.help { font-size: 11px; color: var(--text-muted); }

.review {
  padding: 10px 12px;
  border-bottom: 1px solid var(--bg-surface0);
  background: var(--bg-base);
}
.review-empty { font-size: 11px; color: var(--text-muted); }
.review-empty code {
  font-family: var(--mono); font-size: 10px;
  background: var(--bg-mantle); padding: 1px 4px; border-radius: 2px;
}

.review-grid {
  display: grid;
  grid-template-columns: minmax(180px, 240px) 1fr;
  gap: 10px;
  min-height: 220px;
  max-height: 380px;
}

.file-list {
  background: var(--bg-mantle);
  border-radius: 4px;
  overflow-y: auto;
  border: 1px solid var(--bg-surface0);
}
.file-list-header {
  padding: 5px 8px;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: .04em;
  color: var(--text-muted);
  border-bottom: 1px solid var(--bg-surface0);
  position: sticky;
  top: 0;
  background: var(--bg-mantle);
}
.file-row {
  display: flex;
  align-items: center;
  padding: 5px 8px;
  font-family: var(--mono);
  font-size: 11px;
  cursor: pointer;
  color: var(--text-sub);
  border-bottom: 1px solid var(--bg-surface0);
}
.file-row:hover { background: var(--bg-surface0); color: var(--text); }
.file-row.active { background: var(--bg-surface0); color: var(--mauve); font-weight: 600; }
.file-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-size { font-size: 10px; color: var(--text-muted); margin-left: 6px; }

.file-editor {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--bg-surface0);
  border-radius: 4px;
  overflow: hidden;
  background: var(--bg-base);
}
.editor-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  background: var(--bg-mantle);
  border-bottom: 1px solid var(--bg-surface0);
}
.editor-title {
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dirty { font-size: 10px; color: var(--peach); }
.save-flash { font-size: 10px; color: var(--green); opacity: 0; transition: opacity .3s; }
.save-flash.show { opacity: 1; }
.editor-ta {
  flex: 1;
  min-height: 200px;
  background: var(--bg-base);
  color: var(--text);
  border: none;
  outline: none;
  resize: vertical;
  padding: 8px 10px;
  font-family: var(--mono);
  font-size: 11px;
  line-height: 1.55;
}

.output-tabs {
  border-bottom: 1px solid var(--bg-surface0);
}
.tab-bar {
  background: var(--bg-mantle);
  border-bottom: 1px solid var(--bg-surface0);
  display: flex;
}
.tab {
  padding: 6px 14px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  color: var(--text-muted);
}
.tab:hover { color: var(--text); }
.tab.active { color: var(--mauve); border-bottom-color: var(--mauve); }
.output-container {
  max-height: 320px;
  min-height: 120px;
  overflow: auto;
}
</style>
