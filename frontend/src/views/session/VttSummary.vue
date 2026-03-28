<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useConfigStore } from '../../stores/config'
import { resolvePath, resolvePathList } from '../../utils/paths'
import PathField from '../../components/shared/PathField.vue'
import MultiPathField from '../../components/shared/MultiPathField.vue'
import RunPanel from '../../components/shared/RunPanel.vue'

const config = useConfigStore()

// ── Form state ──
const vttInput = ref('')
const vttDate = ref('')
const vttSessionName = ref('')
const vttContext = ref('')
const referenceSummaries = ref('')
const vttOutput = ref('')
const roleplayOutput = ref('')
const synthOnly = ref(false)
const extractDir = ref('')
const chunkSize = ref(50000)
const noLog = ref(false)
const showAdvanced = ref(false)

function loadFromConfig() {
  const v = config.values
  vttInput.value = v.vtt_input || ''
  vttDate.value = v.vtt_date || ''
  vttSessionName.value = v.vtt_session_name || ''
  vttContext.value = v.vtt_context || ''
  vttOutput.value = v.vtt_output || ''
  roleplayOutput.value = v.vtt_roleplay_output || ''
  extractDir.value = v.vtt_extract_dir || ''
  chunkSize.value = v.vtt_chunk_size || 50000

  // Build reference summaries from GM recap + any existing
  const refs: string[] = []
  const gmRecap = v.sd_session || ''
  if (gmRecap) refs.push(gmRecap)
  const existing = (v.vtt_reference_summaries || '').split('\n').filter((l: string) => l.trim())
  for (const r of existing) {
    if (r.trim() !== gmRecap) refs.push(r.trim())
  }
  referenceSummaries.value = refs.join('\n')
}

const contextFiles = computed(() => resolvePathList(vttContext.value))

const referenceFiles = computed(() => resolvePathList(referenceSummaries.value))

const ready = computed(() => {
  if (synthOnly.value) return true
  return !!vttInput.value.trim()
})

const runParams = computed(() => ({
  vtt_input: resolvePath(vttInput.value),
  output: resolvePath(vttOutput.value),
  roleplay_output: resolvePath(roleplayOutput.value),
  date: vttDate.value,
  session_name: vttSessionName.value,
  context: contextFiles.value,
  reference_summaries: referenceFiles.value,
  extract_dir: resolvePath(extractDir.value),
  chunk_size: chunkSize.value,
  synthesize_only: synthOnly.value,
  no_log: noLog.value,
  model: config.model,
}))

function onDone(rc: number) {
  if (rc === 0) {
    config.values.sd_session_summary = resolvePath(vttOutput.value)
    config.values.sd_roleplay_summary = resolvePath(roleplayOutput.value)
  }
}

onMounted(() => {
  loadFromConfig()
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>VTT &rarr; Session Summary</h2>
      <p class="subtitle">Convert a Zoom .vtt transcript into a structured session summary using the extract &rarr; synthesize pipeline.</p>
    </div>

    <div class="form-grid">
      <!-- VTT input -->
      <div v-if="!synthOnly" class="form-section">
        <PathField
          v-model="vttInput"
          label="Zoom .vtt transcript file"
          required
          help="Download from Zoom cloud recordings or local recording folder."
        />
      </div>

      <!-- Session metadata -->
      <div class="form-section">
        <div class="form-row">
          <div class="field">
            <label class="field-label">Session date</label>
            <input type="text" class="field-input" v-model="vttDate" placeholder="2026-03-15" />
          </div>
          <div class="field">
            <label class="field-label">Session name</label>
            <input type="text" class="field-input" v-model="vttSessionName" placeholder="Session 12 — Icespire Hold" />
          </div>
        </div>
      </div>

      <!-- Context -->
      <div class="form-section">
        <MultiPathField
          v-model="vttContext"
          label="Campaign context files"
          help="Recommended: campaign_state.md, world_state.md, party.md — helps Claude identify NPCs and note changes vs. canon."
        />
      </div>

      <!-- Reference summaries -->
      <div class="form-section">
        <MultiPathField
          v-model="referenceSummaries"
          label="Reference summaries"
          help="GMassistant recap, Saga20 summary, etc. The model cross-references these during synthesis."
        />
      </div>

      <!-- Outputs -->
      <div class="form-section">
        <PathField
          v-model="vttOutput"
          label="Session summary output"
          required
          is-output
          help="The structured session summary. Auto-filled as <session_dir>/session-summary.md."
        />
        <PathField
          v-model="roleplayOutput"
          label="Roleplay highlights output"
          is-output
          help="Character voices and memorable exchanges. Required by Session Doc."
        />
      </div>

      <!-- Advanced -->
      <div class="form-section">
        <button class="btn-neutral btn-sm" @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? 'Hide' : 'Show' }} advanced options
        </button>

        <div v-if="showAdvanced" class="advanced-panel">
          <div class="field">
            <label class="checkbox-label">
              <input type="checkbox" v-model="synthOnly" />
              Re-synthesize from existing extractions
            </label>
          </div>
          <PathField
            v-model="extractDir"
            label="Extractions directory override"
            help="Override where extract_NNN.md files are saved/loaded. Normally auto-derived."
          />
          <div class="field">
            <label class="field-label">Chunk size (chars)</label>
            <input type="number" class="field-input" v-model.number="chunkSize" min="10000" step="5000" />
          </div>
          <div class="field">
            <label class="checkbox-label">
              <input type="checkbox" v-model="noLog" />
              Skip log file
            </label>
          </div>
        </div>
      </div>

      <!-- Run panel -->
      <RunPanel
        endpoint="/api/workflow/run/vtt-summary"
        :params="runParams"
        :disabled="!ready"
        label="Run VTT Summary"
        @done="onDone"
      />
    </div>
  </div>
</template>

<style scoped>
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
.form-row { display: flex; gap: 12px; }
.form-row > .field { flex: 1; }

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

.checkbox-label {
  font-size: 11px; color: var(--text-sub); display: flex;
  align-items: center; gap: 6px; cursor: pointer;
}
.checkbox-label input { accent-color: var(--mauve); }

.advanced-panel {
  margin-top: 10px; padding: 10px;
  background: var(--bg-mantle); border-radius: 4px;
}
</style>
