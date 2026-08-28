<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useConfigStore } from '../../stores/config'
import PathField from '../../components/shared/PathField.vue'
import StreamOutput from '../../components/shared/StreamOutput.vue'

const config = useConfigStore()

// These are intentionally component-local. The access key is submitted only
// in the POST body and no run result is persisted in browser storage.
const campaignId = ref('')
const username = ref('')
const accessKey = ref('')
const worldState = ref('')
const campaignState = ref('')
const party = ref('')
const extractFile = ref('scabard_entities.json')
const manifest = ref('scabard_manifest.json')
const extractOnly = ref(true)
const dryRun = ref(false)

const output = ref('')
const status = ref<'idle' | 'running' | 'done' | 'error'>('idle')
const returnCode = ref<number | null>(null)
const errorMessage = ref('')
let controller: AbortController | null = null

const ready = computed(() =>
  campaignId.value.trim() !== ''
  && username.value.trim() !== ''
  && accessKey.value.trim() !== ''
  && (extractOnly.value || !!worldState.value.trim() || !!campaignState.value.trim() || !!party.value.trim()),
)

function appendSseEvent(block: string): boolean {
  let event = 'message'
  const dataLines: string[] = []
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
  }
  if (!dataLines.length) return false
  const data = dataLines.join('\n')
  if (event === 'done') {
    try {
      const done = JSON.parse(data) as { returncode?: number; error?: string }
      returnCode.value = done.returncode ?? 1
      errorMessage.value = done.error || ''
      status.value = returnCode.value === 0 ? 'done' : 'error'
      return true
    } catch {
      status.value = 'error'
      errorMessage.value = 'The Scabard run returned an invalid completion event.'
      return false
    }
  } else if (event === 'message') {
    try {
      output.value += JSON.parse(data) as string
    } catch {
      output.value += data
    }
  }
  return false
}

async function run() {
  if (!ready.value || status.value === 'running') return
  controller?.abort()
  controller = new AbortController()
  status.value = 'running'
  returnCode.value = null
  errorMessage.value = ''
  output.value = ''

  // Keep the credential out of the URL, command preview, and any client-side
  // result state. The server forwards it only as a child environment value.
  const body = {
    campaign_id: Number(campaignId.value.trim()),
    username: username.value.trim(),
    access_key: accessKey.value.trim(),
    world_state: worldState.value.trim(),
    campaign_state: campaignState.value.trim(),
    party: party.value.trim(),
    extract_file: extractFile.value.trim(),
    manifest: manifest.value.trim(),
    extract_only: extractOnly.value,
    dry_run: dryRun.value,
    backend: config.backend,
    model: config.model || undefined,
  }

  try {
    const response = await fetch('/api/integrations/scabard', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    if (!response.ok) throw new Error(`Scabard request failed (${response.status}).`)
    if (!response.body) throw new Error('Scabard returned no output stream.')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let pending = ''
    let sawDone = false
    const append = (block: string) => { sawDone = appendSseEvent(block) || sawDone }
    while (true) {
      const { value, done } = await reader.read()
      pending += decoder.decode(value || new Uint8Array(), { stream: !done })
      let boundary = pending.indexOf('\n\n')
      while (boundary >= 0) {
        append(pending.slice(0, boundary))
        pending = pending.slice(boundary + 2)
        boundary = pending.indexOf('\n\n')
      }
      if (done) break
    }
    if (pending.trim()) append(pending)
    if (status.value === 'running' && !sawDone) {
      status.value = 'error'
      returnCode.value = 1
      errorMessage.value = 'Scabard stream ended before a completion event.'
    }
  } catch (error) {
    if ((error as Error).name === 'AbortError') {
      status.value = 'idle'
      return
    }
    status.value = 'error'
    errorMessage.value = error instanceof Error ? error.message : 'Scabard request failed.'
  } finally {
    controller = null
  }
}

function abort() {
  controller?.abort()
}

function clear() {
  output.value = ''
  errorMessage.value = ''
  returnCode.value = null
  status.value = 'idle'
}

onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Scabard Sync</h2>
      <p class="subtitle">
        Extract campaign entities to a reviewable JSON artifact, then sync approved data to Scabard.
        Your access key is submitted securely in the request body and is never shown in the run preview.
      </p>
    </div>

    <div class="form-grid">
      <div class="form-section two-col">
        <div class="field">
          <label class="field-label" for="scabard-campaign-id">Campaign ID <span class="required">*</span></label>
          <input id="scabard-campaign-id" v-model="campaignId" class="field-input" inputmode="numeric" autocomplete="off" />
        </div>
        <div class="field">
          <label class="field-label" for="scabard-username">Username <span class="required">*</span></label>
          <input id="scabard-username" v-model="username" class="field-input" autocomplete="username" />
        </div>
        <div class="field">
          <label class="field-label" for="scabard-access-key">Access key <span class="required">*</span></label>
          <input id="scabard-access-key" v-model="accessKey" class="field-input" type="password" autocomplete="off" />
          <span class="field-help">Sent only in the request body; it is not included in the command preview or URL.</span>
        </div>
      </div>

      <div class="form-section">
        <PathField v-model="worldState" label="World state" resolve-base="campaign" />
        <PathField v-model="campaignState" label="Campaign state" resolve-base="campaign" />
        <PathField v-model="party" label="Party" resolve-base="campaign" />
      </div>

      <div class="form-section two-col">
        <PathField v-model="extractFile" label="Entity artifact" required is-output resolve-base="campaign"
          help="Disk-backed JSON extraction; review it before syncing." />
        <PathField v-model="manifest" label="Sync manifest" is-output resolve-base="campaign" />
      </div>

      <div class="form-section options">
        <label class="checkbox-label"><input v-model="extractOnly" type="checkbox" /> Extract only (review before sync)</label>
        <label class="checkbox-label"><input v-model="dryRun" type="checkbox" /> Dry run (do not write Scabard pages)</label>
      </div>

      <div class="run-controls">
        <button class="btn-success" :disabled="!ready || status === 'running'" @click="run">
          {{ status === 'running' ? 'Running…' : 'Run Scabard sync' }}
        </button>
        <button v-if="status === 'running'" class="btn-warn btn-sm" @click="abort">Abort</button>
        <span v-if="status === 'done'" class="ok">Success</span>
        <span v-else-if="status === 'error'" class="err">Exit {{ returnCode }}</span>
        <span v-if="errorMessage" class="err">{{ errorMessage }}</span>
        <span style="flex: 1"></span>
        <button v-if="output" class="btn-neutral btn-sm" @click="clear">Clear</button>
      </div>

      <div v-if="output" class="output-container">
        <div class="output-title">Scabard run output</div>
        <StreamOutput :text="output" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 20px 24px; max-width: 850px; overflow-y: auto; }
.page-header { margin-bottom: 20px; }
.page-header h2 { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.subtitle { font-size: 12px; color: var(--text-muted); line-height: 1.5; max-width: 72ch; }
.form-grid { display: flex; flex-direction: column; gap: 16px; }
.form-section { padding-bottom: 12px; border-bottom: 1px solid var(--bg-surface0); }
.two-col { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.field-label { display: block; font-size: 11px; font-weight: 600; color: var(--text-sub); margin-bottom: 3px; }
.required { color: var(--red); }
.field-input { width: 100%; box-sizing: border-box; font-size: 11px; padding: 6px 7px; border-radius: 4px; background: var(--bg-surface0); color: var(--text); border: 1px solid var(--bg-surface1); font-family: var(--mono); }
.field-help { display: block; margin-top: 4px; font-size: 10px; color: var(--text-muted); line-height: 1.4; }
.options { display: flex; flex-direction: column; gap: 8px; }
.checkbox-label { font-size: 11px; color: var(--text-sub); }
.run-controls { display: flex; align-items: center; gap: 10px; }
.ok { color: var(--green); font-size: 12px; font-weight: 600; }
.err { color: var(--red); font-size: 11px; font-weight: 600; }
.output-container { min-height: 160px; max-height: 450px; overflow: auto; }
.output-title { font-size: 11px; font-weight: 600; color: var(--text-sub); margin-bottom: 5px; }
@media (max-width: 700px) { .two-col { grid-template-columns: 1fr; } }
</style>
