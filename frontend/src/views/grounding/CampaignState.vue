<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useConfigStore } from '../../stores/config'
import PathField from '../../components/shared/PathField.vue'
import ExtractSynthesizePanel from '../../components/shared/ExtractSynthesizePanel.vue'

const config = useConfigStore()

const input = ref('')
const output = ref('')
const trackFile = ref('')
const trackInline = ref('')
const extractDir = ref('')
const splitChapters = ref('# Chapter')
const noLog = ref(false)
const showAdvanced = ref(false)

function loadFromConfig() {
  const v = config.values
  input.value = v.cs_input || v.summaries || ''
  output.value = v.cs_output || v.campaign_state_output || v.campaign_state || ''
  trackFile.value = v.cs_track_file || v.tracking_file || ''
  extractDir.value = v.cs_extract_dir || ''
  splitChapters.value = v.cs_split_chapters || '# Chapter'
}

const ready = computed(() =>
  !!(input.value.trim() && output.value.trim())
)

const trackItems = computed(() =>
  trackInline.value.split('\n').map(l => l.trim()).filter(Boolean)
)

const runParams = computed(() => ({
  input: input.value,
  output: output.value,
  track_file: trackFile.value,
  track: trackItems.value,
  extract_dir: extractDir.value,
  split_chapters: splitChapters.value,
  no_log: noLog.value,
  model: config.model,
}))

watch(output, (newOutput) => {
  if (!extractDir.value && newOutput) {
    const idx = newOutput.lastIndexOf('/')
    const parent = idx >= 0 ? newOutput.slice(0, idx) : ''
    extractDir.value = parent ? `${parent}/state_extractions` : 'state_extractions'
  }
})

onMounted(() => { loadFromConfig() })
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Campaign State</h2>
      <p class="subtitle">
        Generate campaign_state.md &mdash; a grounding document that tells planning scripts what has been completed and what is currently true.
      </p>
    </div>

    <div class="form-grid">
      <div class="form-section">
        <PathField v-model="input" label="Canonical timeline" required resolve-base="campaign"
          help="The master narrative bible (one big chronologically-ordered file). Gets chunked and extracted into per-chunk state notes." />
      </div>

      <div class="form-section">
        <PathField v-model="output" label="Output file" required is-output resolve-base="campaign"
          help="campaign_state.md — loaded first by prep.py as grounding context." />
      </div>

      <div class="form-section">
        <PathField v-model="trackFile" label="Adventure module tracking list" resolve-base="campaign"
          help="Events from your adventure module to explicitly verify (done or not done). Generate with Make Tracking List, or write your own. Not for PC arc scores — those belong in Party Document." />
      </div>

      <div class="form-section">
        <PathField v-model="extractDir" label="Extractions directory" resolve-base="campaign"
          help="Where intermediate state_extractions/ files live. Review these between Extract and Synthesize." />
      </div>

      <!-- Advanced -->
      <div class="form-section">
        <div class="field">
          <label class="field-label">Additional events to track</label>
          <textarea class="field-textarea" v-model="trackInline" rows="4"
            placeholder="One item per line — added to the tracking list above" />
          <span class="field-help">Extra events to verify that aren't in the tracking file. Same format, same purpose — just typed directly instead of loaded from a file.</span>
        </div>
      </div>

      <div class="form-section">
        <button class="btn-neutral btn-sm" @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? 'Hide' : 'Show' }} advanced options
        </button>

        <div v-if="showAdvanced" class="advanced-panel">
          <div class="field">
            <label class="field-label">Split by session prefix</label>
            <input type="text" class="field-input" v-model="splitChapters"
              placeholder="e.g. # Session — splits at each session heading" />
            <span class="field-help">When set, each session becomes one extract chunk.</span>
          </div>
          <div class="field">
            <label class="checkbox-label">
              <input type="checkbox" v-model="noLog" />
              Skip log file
            </label>
          </div>
        </div>
      </div>

      <ExtractSynthesizePanel
        endpoint="/api/grounding/run/campaign-state"
        :params="runParams"
        :extract-dir="extractDir"
        :disabled="!ready"
        extract-label="1. Extract per-chunk state"
        synth-label="2. Synthesize campaign_state.md"
      />
    </div>
  </div>
</template>

<style scoped>
.page { padding: 20px 24px; max-width: 1400px; height: 100%; overflow-y: auto; box-sizing: border-box; }
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
.field-input, .field-textarea {
  width: 100%; padding: 6px 8px; border-radius: 4px;
  border: 1px solid var(--bg-surface1); background: var(--bg-base);
  color: var(--text); font-family: var(--mono); font-size: 11px;
  outline: none; box-sizing: border-box;
}
.field-textarea { resize: vertical; }
.field-input:focus, .field-textarea:focus { border-color: var(--mauve); }

.checkbox-label {
  font-size: 11px; color: var(--text-sub); display: flex;
  align-items: center; gap: 6px; cursor: pointer;
}
.checkbox-label input { accent-color: var(--mauve); }

.field-help { display: block; font-size: 10px; color: var(--text-muted); margin-top: 3px; }
.field-input:disabled { opacity: 0.4; cursor: not-allowed; }

.advanced-panel {
  margin-top: 10px; padding: 10px;
  background: var(--bg-mantle); border-radius: 4px;
}
</style>
